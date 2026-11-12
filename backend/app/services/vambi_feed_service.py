"""فید فقط‌خواندنی وامبی (v2): every real, sellable SKU with every seller's offer and ALL of its price tiers.

Server-to-server only (see api/v1/vambi_feed.py for auth and rate limit). Read-only: no writes, no migration.

The tier model is exactly 60online's own (seller_offers + offer_price_tiers, as used by sale_eligibility.unit_price
and cashier_service):

  tier       source                                                    who may see/buy it on 60online
  ---------  --------------------------------------------------------  ---------------------------------------------
  public     seller_offers.selling_price_minor (channel retail),        everyone (retail channel; the storefront shows
             + offer_price_tiers channel=retail, organization_id NULL   them per STOREFRONT_PRICE_VISIBILITY)
             (retail quantity breaks, min_qty > 1)
  wholesale  seller_offers.selling_price_minor (channel organization),  any active member of a business account
             + offer_price_tiers channel=organization, org NULL         (organizations.buyer_kind organization|retailer)
             (B2B quantity breaks)
  org        offer_price_tiers with organization_id set                 active members of THAT organization only

Each price row carries min_qty/max_qty (quantity range), the net price, the VAT-inclusive price (minor units, the
storefront's standard VAT rate), confirmed_at and fresh_until (60online sells a price only while it is <= 24h old).
A stale price is never emitted. Offer pricing modes: fixed/bulk → public + wholesale; contract → wholesale/org only;
rfq_only/out_of_stock/unavailable → no price rows. cost_price_minor, commission, coupons and partner discounts are
never in the feed (cart-time adjustments, not offer prices).

Incremental: an item's updated_at is the newest of its master/family/product/offer/price-confirmation/tier
timestamps. Some legacy admin paths change a product without touching any timestamp, so a consumer must still run a
full sweep (no updated_since) at least daily; a full sweep also reports inactive products as tombstones.
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import re

from app.core.errors import ValidationError
from app.services import product_channel_policy as policy
from app.services import sale_eligibility as se

SPEC_VERSION = "v2"
DEFAULT_LIMIT = 200
MAX_LIMIT = 500
FRESH = _dt.timedelta(hours=se.MAX_CONFIRMATION_AGE_HOURS)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?\s*(Z|[+-]\d{2}:?\d{2})?$")


def to_latin(value) -> str:
    return str(value).translate(_DIGITS).strip()


def parse_ts(value) -> _dt.datetime | None:
    """Any timestamp spelling found in this DB (or sent by a client) → aware UTC datetime; None if absent/invalid."""
    if value is None:
        return None
    m = _TS.match(to_latin(value))
    if not m:
        return None
    date, time, tz = m.groups()
    raw = f"{date}T{time or '00:00:00'}"
    try:
        t = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        hh, mm = int(tz[1:3]), int(tz[-2:])
        t = t - sign * _dt.timedelta(hours=hh, minutes=mm)
    # Whole seconds: the cursor and updated_at are exchanged at second precision, so markers must be too.
    return t.replace(tzinfo=_dt.timezone.utc, microsecond=0)


def iso(t: _dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_limit(raw) -> int:
    if raw is None or raw == "":
        return DEFAULT_LIMIT
    s = to_latin(raw)
    if not s.isdigit() or not 1 <= int(s) <= MAX_LIMIT:
        raise ValidationError(f"limit باید عددی بین ۱ و {MAX_LIMIT} باشد", code="invalid_limit")
    return int(s)


def parse_since(raw) -> _dt.datetime | None:
    if raw is None or raw == "":
        return None
    t = parse_ts(raw)
    if t is None:
        raise ValidationError("updated_since باید زمان ISO-8601 باشد", code="invalid_updated_since")
    return t


def encode_cursor(marker: _dt.datetime, pid: int) -> str:
    raw = json.dumps([iso(marker), pid], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(raw) -> tuple[_dt.datetime, int] | None:
    if raw is None or raw == "":
        return None
    try:
        s = str(raw)
        data = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
        t, pid = parse_ts(data[0]), data[1]
        if t is None or isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
            raise ValueError
        return t, pid
    except (ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError):
        raise ValidationError("cursor نامعتبر است", code="invalid_cursor") from None


def _latest(*values) -> _dt.datetime:
    ts = [t for t in (parse_ts(v) for v in values) if t is not None]
    return max(ts) if ts else _EPOCH


def _markers(conn, prov: tuple) -> dict[int, tuple[_dt.datetime, bool]]:
    """product id → (change marker, currently listed on the storefront). Only real (allowed-provenance) products."""
    ph = ",".join("?" * len(prov))
    out: dict[int, list] = {}
    for r in conn.execute(
            f"""SELECT p.id, p.created_at, p.is_active, m.status, m.updated_at AS m_upd, f.updated_at AS f_upd,
                       f.provenance AS f_prov
                FROM products p JOIN master_products m ON m.id = p.master_product_id
                LEFT JOIN product_families f ON f.id = m.family_id
                WHERE p.provenance IN ({ph}) AND m.provenance IN ({ph})""", prov + prov):
        listed = bool(r["is_active"]) and r["status"] == "active" and (r["f_prov"] is None or r["f_prov"] in prov)
        out[int(r["id"])] = [_latest(r["created_at"], r["m_upd"], r["f_upd"]), listed]
    for r in conn.execute(
            """SELECT product_id, MAX(updated_at) AS a, MAX(last_price_confirmed_at) AS b,
                      MAX(last_inventory_confirmed_at) AS c, MAX(created_at) AS d
               FROM seller_offers GROUP BY product_id"""):
        rec = out.get(int(r["product_id"]))
        if rec:
            rec[0] = max(rec[0], _latest(r["a"], r["b"], r["c"], r["d"]))
    for r in conn.execute(
            """SELECT so.product_id, MAX(t.confirmed_at) AS a, MAX(t.created_at) AS b
               FROM offer_price_tiers t JOIN seller_offers so ON so.id = t.offer_id GROUP BY so.product_id"""):
        rec = out.get(int(r["product_id"]))
        if rec:
            rec[0] = max(rec[0], _latest(r["a"], r["b"]))
    return {k: (v[0], v[1]) for k, v in out.items()}


def _price_row(tier: str, channel: str, *, net: int, vat_bps: int, min_qty: int, max_qty, confirmed: _dt.datetime,
               org_id=None) -> dict:
    from app.services.consumer_rights_service import gross
    row = {"tier": tier, "channel": channel, "min_qty": int(min_qty), "max_qty": None if max_qty is None else int(max_qty),
           "price_net_minor": int(net), "price_incl_vat_minor": gross(int(net), vat_bps), "vat_bps": vat_bps,
           "confirmed_at": iso(confirmed), "fresh_until": iso(confirmed + FRESH)}
    if tier == "org":
        row["org_id"] = int(org_id)
    return row


def offers_for_product(conn, product_id: int, *, prov: tuple, vat_bps: int, now: _dt.datetime) -> list[dict]:
    ph = ",".join("?" * len(prov))
    today = now.date().isoformat()
    rows = conn.execute(
        f"""SELECT so.id, so.supplier_id, so.channel, so.pricing_mode, so.selling_price_minor, so.stock_quantity,
                   so.stock_reserved, so.min_order_quantity, so.max_order_quantity, so.lead_time_days, so.valid_until,
                   so.last_price_confirmed_at, so.last_inventory_confirmed_at, so.updated_at,
                   s.display_name AS seller, sl.city, sl.province
            FROM seller_offers so JOIN suppliers s ON s.id = so.supplier_id
            LEFT JOIN supplier_locations sl ON sl.id = so.supplier_location_id
            WHERE so.product_id = ? AND so.status = 'active' AND s.status = 'active'
              AND so.provenance IN ({ph}) AND s.provenance IN ({ph})
            ORDER BY so.id""", (product_id,) + prov + prov).fetchall()
    out = []
    for o in rows:
        if o["valid_until"] is not None and str(o["valid_until"])[:10] < today:
            continue
        scope = policy.effective(conn, product_id, o["channel"])
        if scope is None:
            continue
        allowed = policy.channels(scope)
        mode = o["pricing_mode"]
        moq = int(o["min_order_quantity"] or 1)
        prices: list[dict] = []
        confirmed = parse_ts(o["last_price_confirmed_at"])
        base_fresh = confirmed is not None and now - confirmed <= FRESH and int(o["selling_price_minor"]) > 0
        if base_fresh:
            if "retail" in allowed and mode in ("fixed", "bulk"):
                prices.append(_price_row("public", "retail", net=o["selling_price_minor"], vat_bps=vat_bps,
                                         min_qty=moq, max_qty=None, confirmed=confirmed))
            if "organization" in allowed and mode in ("fixed", "bulk", "contract"):
                prices.append(_price_row("wholesale", "organization", net=o["selling_price_minor"], vat_bps=vat_bps,
                                         min_qty=moq, max_qty=None, confirmed=confirmed))
        for t in conn.execute("""SELECT channel, organization_id, min_qty, max_qty, unit_price_minor, confirmed_at
                                 FROM offer_price_tiers WHERE offer_id = ? ORDER BY channel, organization_id, min_qty""",
                              (o["id"],)):
            tc = parse_ts(t["confirmed_at"])
            if tc is None or now - tc > FRESH or t["channel"] not in allowed:
                continue
            sellable = ("fixed", "bulk") if t["channel"] == "retail" else ("fixed", "bulk", "contract")
            if mode not in sellable:
                continue
            if t["organization_id"] is not None:
                tier = "org"
            else:
                tier = "public" if t["channel"] == "retail" else "wholesale"
            prices.append(_price_row(tier, t["channel"], net=t["unit_price_minor"], vat_bps=vat_bps,
                                     min_qty=t["min_qty"], max_qty=t["max_qty"], confirmed=tc,
                                     org_id=t["organization_id"]))
        inv = parse_ts(o["last_inventory_confirmed_at"])
        stock_fresh = inv is not None and now - inv <= FRESH
        available = int(o["stock_quantity"]) - int(o["stock_reserved"])
        stock_state = "unknown" if not stock_fresh else ("in_stock" if available > 0 else "out_of_stock")
        if mode == "out_of_stock":
            stock_state = "out_of_stock"
        out.append({
            "id": int(o["id"]), "supplier_id": int(o["supplier_id"]), "seller": o["seller"],
            "seller_city": o["city"], "seller_province": o["province"], "channel": scope, "pricing_mode": mode,
            "stock_state": stock_state, "available_qty": max(available, 0) if stock_fresh else None,
            "min_order_quantity": moq, "max_order_quantity": o["max_order_quantity"],
            "lead_time_days": o["lead_time_days"], "valid_until": o["valid_until"],
            "updated_at": iso(_latest(o["updated_at"], o["last_price_confirmed_at"], o["last_inventory_confirmed_at"])),
            "prices": prices,
        })
    return out


def _sorted_keys(conn, updated_since, marks=None) -> list[tuple]:
    marks = marks if marks is not None else _markers(conn, tuple(se.allowed_provenance()))
    return sorted((m, pid) for pid, (m, _) in marks.items() if updated_since is None or m >= updated_since)


def products(conn, *, updated_since: _dt.datetime | None, cursor: tuple | None, limit: int,
             now: _dt.datetime | None = None) -> dict:
    from app.core.price_privacy import mode as visibility_mode
    from app.services import consumer_rights_service as crs
    from app.services import storefront_service as store
    now = now or _dt.datetime.now(_dt.timezone.utc)
    prov = tuple(se.allowed_provenance())
    marks = _markers(conn, prov)
    keys = _sorted_keys(conn, updated_since, marks)
    if cursor is not None:
        keys = [k for k in keys if k > cursor]
    page, more = keys[:limit], len(keys) > limit
    data = store._load(conn)
    cats = data["cats"]
    vat_bps = crs.standard_vat_bps(conn)
    items = []
    for marker, pid in page:
        sku = data["by_id"].get(pid)
        if sku is None or not marks[pid][1]:
            slug = conn.execute("SELECT slug FROM products WHERE id = ?", (pid,)).fetchone()
            items.append({"id": pid, "slug": slug["slug"] if slug else None, "active": False,
                          "updated_at": iso(marker), "offers": []})
            continue
        items.append({
            "id": pid, "slug": sku.slug, "sku": sku.sku, "active": True, "updated_at": iso(marker),
            "title_fa": sku.title, "brand": sku.brand, "variant": sku.label, "description_fa": sku.description,
            "category_path": [{"slug": c["slug"], "name_fa": c["name_fa"]} for c in store.category_path(cats, sku.category_id)],
            "images": list(sku.images),
            "specs": [{"label": str(k), "value": str(v)} for k, v in (sku.specs or {}).items()
                      if not isinstance(v, (dict, list))],
            "supply_channel": sku.supply_channel,
            "offers": offers_for_product(conn, pid, prov=prov, vat_bps=vat_bps, now=now),
        })
    return {"spec_version": SPEC_VERSION, "server_time": iso(now),
            "storefront_price_visibility": visibility_mode(), "vat_bps": vat_bps,
            "next_cursor": encode_cursor(*page[-1]) if more and page else None, "items": items}


def _membership_view(conn, m, now: _dt.datetime) -> dict:
    """One active membership in an active business account → role + what it entitles (booleans only, no amounts).

    Uses 60online's own permission helpers so Vambi sees exactly what the organization panel enforces:
    procurement_service._can_procure/_can_approve, membership_service.ADMIN_ROLES/FINANCE_ROLES,
    commerce_ops_service (benefit programs: any active member may pick a pack while the program is open),
    welfare_wallet_service.eligible_plans (active welfare plan covering this membership).
    """
    from app.services import membership_service as ms
    from app.services import procurement_service as pr
    from app.services import welfare_wallet_service as ww
    md = {"role": m["role"], "procurement_role": m["procurement_role"]}
    org = int(m["organization_id"])
    pack_programs = conn.execute(
        "SELECT COUNT(*) FROM benefit_programs WHERE organization_id = ? AND status = 'open' "
        "AND mode IN ('fixed_pack', 'pack_choice')", (org,)).fetchone()[0]
    credit = False
    for a in conn.execute("SELECT valid_from, expires_at FROM credit_allocations WHERE membership_id = ? "
                          "AND status = 'active'", (int(m["id"]),)):
        start, end = parse_ts(a["valid_from"]), parse_ts(a["expires_at"])
        if (start is None or start <= now) and (end is None or end > now):
            credit = True
            break
    try:
        welfare = bool(ww.eligible_plans(conn, int(m["id"])))
    except Exception:  # an unreadable plan never grants anything
        welfare = False
    return {
        "org_id": org, "org_name": m["display_name"], "buyer_kind": m["buyer_kind"],
        "role": m["role"], "procurement_role": m["procurement_role"],
        "is_admin": m["role"] in ms.ADMIN_ROLES,
        "can_buy_for_org": pr._can_procure(md),
        "can_approve_purchases": pr._can_approve(md),
        "can_manage_finance": m["role"] in ms.FINANCE_ROLES,
        "pack_beneficiary": bool(pack_programs),
        "welfare_plan_active": welfare,
        "credit_allocation_active": credit,
        "price_tiers": ["wholesale", "org"],
    }


def pricing_context(conn, user_id: int, now: _dt.datetime | None = None) -> dict:
    """Minimal, secret-free pricing eligibility of a 60online user (SSO exchange + entitlement refresh).

    Only ACTIVE memberships of ACTIVE business accounts count; an inactive user gets the public context only.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    user = conn.execute("SELECT is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    rows = [] if not user or not user["is_active"] else conn.execute(
        """SELECT om.id, om.organization_id, om.role, om.procurement_role, o.display_name, o.buyer_kind
           FROM organization_memberships om JOIN organizations o ON o.id = om.organization_id
           WHERE om.user_id = ? AND om.status = 'active' AND o.status = 'active' ORDER BY o.id""", (user_id,)).fetchall()
    memberships = [_membership_view(conn, r, now) for r in rows]
    org_ids = [m["org_id"] for m in memberships]
    return {"active": bool(user and user["is_active"]),
            "tiers": ["public"] + (["wholesale", "org"] if org_ids else []), "org_ids": org_ids,
            "wholesale_eligible": bool(org_ids), "buyer_kinds": sorted({m["buyer_kind"] for m in memberships}),
            "memberships": memberships}


def user_ref(user_id: int, secret: str) -> str:
    """Stable, verifiable reference for a user, issued to Vambi at SSO exchange (no DB row; changes if SECRET_KEY rotates)."""
    import hashlib
    import hmac
    mac = hmac.new(secret.encode(), f"vambi-user-ref:{int(user_id)}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"u{int(user_id)}.{mac}"


def user_from_ref(ref, secret: str) -> int | None:
    import hmac
    if not isinstance(ref, str) or len(ref) > 64 or not re.fullmatch(r"u[1-9][0-9]{0,15}\.[0-9a-f]{32}", ref):
        return None
    uid = int(ref[1:ref.index(".")])
    return uid if hmac.compare_digest(user_ref(uid, secret), ref) else None
