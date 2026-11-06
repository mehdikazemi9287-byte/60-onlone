"""Supplier-managed marketplace offers: price, stock, MOQ, lead time, pricing mode and quantity tiers.

An offer's provenance is always its supplier's (a DEMO supplier can only create DEMO offers).
Saving with confirm=true stamps price/stock confirmation (valid 24h); tiers are replaced atomically
and must not overlap. Every change is written to the append-only offer_events table.
"""
from __future__ import annotations

import datetime
import json

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import product_channel_policy as policy

MODES = ("fixed", "bulk", "contract", "rfq_only", "out_of_stock", "unavailable")
CHANNELS = ("retail", "organization", "both")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _int(v, field, lo=0, hi=10**13, optional=False):
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValidationError(f"{field} نامعتبر است")
    return v


def _tiers(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValidationError("پله‌های قیمت نامعتبر است")
    out = []
    for t in raw:
        if not isinstance(t, dict) or t.get("channel") not in ("retail", "organization"):
            raise ValidationError("کانال پله قیمت باید retail یا organization باشد")
        out.append({"channel": t["channel"], "min_qty": _int(t.get("min_qty"), "حداقل تعداد پله", 1),
                    "max_qty": _int(t.get("max_qty"), "حداکثر تعداد پله", 1, optional=True),
                    "unit_price_minor": _int(t.get("unit_price_minor"), "قیمت پله", 1),
                    "organization_id": _int(t.get("organization_id"), "سازمان", 1, optional=True)})
    for ch in ("retail", "organization"):
        rows = sorted((t for t in out if t["channel"] == ch), key=lambda t: (t["organization_id"] or 0, t["min_qty"]))
        for a, b in zip(rows, rows[1:]):
            if a["organization_id"] == b["organization_id"] and (a["max_qty"] is None or a["max_qty"] >= b["min_qty"]):
                raise ValidationError("پله‌های قیمت هم‌پوشانی دارند")
        for t in rows:
            if t["max_qty"] is not None and t["max_qty"] < t["min_qty"]:
                raise ValidationError("بازه پله قیمت نامعتبر است")
    return out


def _clean(data: dict) -> dict:
    mode = data.get("pricing_mode", "fixed")
    if mode not in MODES:
        raise ValidationError("حالت قیمت‌گذاری نامعتبر است")
    channel = data.get("channel", "both")
    if channel not in CHANNELS:
        raise ValidationError("کانال فروش نامعتبر است")
    price = _int(data.get("selling_price_minor"), "قیمت", 0)
    if mode in ("fixed", "bulk") and price <= 0:
        raise ValidationError("برای قیمت ثابت/عمده، قیمت واحد الزامی است")
    tiers = _tiers(data.get("tiers"))
    if mode == "bulk" and not tiers:
        raise ValidationError("حالت عمده حداقل یک پله قیمت لازم دارد")
    moq = _int(data.get("min_order_quantity", 1), "حداقل سفارش", 1)
    mx = _int(data.get("max_order_quantity"), "حداکثر سفارش", 1, optional=True)
    if mx is not None and mx < moq:
        raise ValidationError("حداکثر سفارش کمتر از حداقل سفارش است")
    valid = data.get("valid_until")
    if valid is not None:
        try:
            valid = datetime.date.fromisoformat(str(valid)).isoformat()
        except ValueError:
            raise ValidationError("تاریخ اعتبار نامعتبر است")
    sku = data.get("supplier_sku")
    source = data.get('source_reference')
    if source is not None and not isinstance(source,str):
        raise ValidationError('مرجع منبع باید متن باشد')
    return {"pricing_mode": mode, "channel": channel, "selling_price_minor": price, "tiers": tiers,
            "stock_quantity": _int(data.get("stock_quantity"), "موجودی", 0),
            "min_order_quantity": moq, "max_order_quantity": mx,
            "lead_time_days": _int(data.get("lead_time_days"), "زمان تأمین", 0, 365, optional=True),
            "valid_until": valid, "supplier_sku": sku.strip()[:80] if isinstance(sku, str) and sku.strip() else None,
            "source_reference": (source or "").strip()[:200] or None,
            "confirm": data.get("confirm") is True}


def _snapshot(conn, offer_id: int) -> dict:
    o = dict(conn.execute("SELECT * FROM seller_offers WHERE id=?", (offer_id,)).fetchone())
    o["tiers"] = [dict(t) for t in conn.execute(
        "SELECT channel, organization_id, min_qty, max_qty, unit_price_minor, confirmed_at FROM offer_price_tiers WHERE offer_id=? ORDER BY channel, min_qty",
        (offer_id,))]
    o.update(policy.offer_fields(conn,o["product_id"],o["channel"]))
    return o


def _event(conn, offer_id, actor, action, before, after):
    conn.execute("INSERT INTO offer_events (offer_id, actor_user_id, action, before_json, after_json) VALUES (?,?,?,?,?)",
                 (offer_id, actor, action, json.dumps(before, ensure_ascii=False, default=str) if before else None,
                  json.dumps(after, ensure_ascii=False, default=str)))


def _write_tiers(conn, offer_id, tiers, actor, stamp):
    conn.execute("DELETE FROM offer_price_tiers WHERE offer_id=?", (offer_id,))
    for t in tiers:
        conn.execute("""INSERT INTO offer_price_tiers (offer_id, channel, organization_id, min_qty, max_qty, unit_price_minor,
                        confirmed_at, created_by_user_id) VALUES (?,?,?,?,?,?,?,?)""",
                     (offer_id, t["channel"], t["organization_id"], t["min_qty"], t["max_qty"], t["unit_price_minor"], stamp, actor))


def create(conn, *, supplier_id: int, actor: int, data: dict) -> dict:
    sup = conn.execute("SELECT id, status, provenance FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if not sup or sup["status"] != "active":
        raise ConflictError("تأمین‌کننده فعال نیست")
    sku_id = _int(data.get("product_id"), "کالا", 1)
    sku = conn.execute("SELECT id, provenance FROM products WHERE id=? AND is_active=1", (sku_id,)).fetchone()
    if not sku or sku["provenance"] == "demo":
        raise NotFoundError("کالای قابل عرضه یافت نشد")
    loc = data.get("supplier_location_id")
    loc_row = conn.execute("SELECT id FROM supplier_locations WHERE supplier_id=? AND status='active' AND (? IS NULL OR id=?) ORDER BY id LIMIT 1",
                           (supplier_id, loc, loc)).fetchone()
    if not loc_row:
        raise ConflictError("ابتدا یک انبار/محل ارسال فعال ثبت کنید", code="location_required")
    if conn.execute("SELECT 1 FROM seller_offers WHERE product_id=? AND supplier_id=? AND supplier_location_id=?",
                    (sku_id, supplier_id, loc_row["id"])).fetchone():
        raise ConflictError("برای این کالا و انبار قبلاً پیشنهاد ثبت کرده‌اید", code="offer_exists")
    c = _clean(data)
    if c['selling_price_minor'] <= 0:
        raise ValidationError('برای ایجاد پیشنهاد، قیمت واقعی تأمین‌کننده لازم است؛ کالای بدون قیمت در کاتالوگ برای استعلام باقی می‌ماند')
    _scope(conn,sku_id,c)
    _check_contract_orgs(conn, supplier_id, c["tiers"])
    from app.services import catalog_quality_service as cq
    catalog_warnings = cq.offer_gate(conn, sku_id)  # CATALOG_ENFORCE_REQUIRED=1 → raises; default warn-only
    stamp = _now() if c["confirm"] else None
    offer_id = conn.execute(
        """INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, supplier_sku, selling_price_minor, stock_quantity,
               status, min_order_quantity, max_order_quantity, lead_time_days, pricing_mode, channel, valid_until, source_reference,
               provenance, last_price_confirmed_at, last_inventory_confirmed_at, fulfillment_type)
           VALUES (?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?,'delivery')""",
        (sku_id, supplier_id, loc_row["id"], c["supplier_sku"], c["selling_price_minor"], c["stock_quantity"], c["min_order_quantity"],
         c["max_order_quantity"], c["lead_time_days"], c["pricing_mode"], c["channel"], c["valid_until"], c["source_reference"],
         sup["provenance"], stamp, stamp)).lastrowid
    _write_tiers(conn, offer_id, c["tiers"], actor, stamp or _now())
    after = _snapshot(conn, offer_id)
    _event(conn, offer_id, actor, "created", None, after)
    _fire(conn, sku_id)
    if catalog_warnings:
        after = {**after, "catalog_warnings": catalog_warnings}
    return after


def _fire(conn, product_id: int) -> None:
    from app.services.commerce_ops_service import fire_alerts
    fire_alerts(conn, product_id)


def _own(conn, supplier_id, offer_id):
    o = conn.execute("SELECT * FROM seller_offers WHERE id=? AND supplier_id=?", (offer_id, supplier_id)).fetchone()
    if not o:
        raise NotFoundError("پیشنهاد یافت نشد")
    return o


def update(conn, *, supplier_id: int, offer_id: int, actor: int, data: dict) -> dict:
    _own(conn, supplier_id, offer_id)
    before = _snapshot(conn, offer_id)
    c = _clean({**data,'source_reference':data.get('source_reference',before['source_reference'])})
    _scope(conn,before["product_id"],c)
    if c["stock_quantity"] < before["stock_reserved"]:
        raise ConflictError("موجودی نمی‌تواند کمتر از مقدار رزروشده سفارش‌های باز باشد")
    _check_contract_orgs(conn, supplier_id, c["tiers"])
    stamp = _now() if c["confirm"] else None
    conn.execute(
        """UPDATE seller_offers SET supplier_sku=?, selling_price_minor=?, stock_quantity=?, min_order_quantity=?, max_order_quantity=?,
               lead_time_days=?, pricing_mode=?, channel=?, valid_until=?, source_reference=?,
               last_price_confirmed_at=COALESCE(?, last_price_confirmed_at), last_inventory_confirmed_at=COALESCE(?, last_inventory_confirmed_at),
               updated_at=datetime('now') WHERE id=?""",
        (c["supplier_sku"], c["selling_price_minor"], c["stock_quantity"], c["min_order_quantity"], c["max_order_quantity"],
         c["lead_time_days"], c["pricing_mode"], c["channel"], c["valid_until"], c["source_reference"], stamp, stamp, offer_id))
    _write_tiers(conn, offer_id, c["tiers"], actor, stamp or (before["tiers"][0]["confirmed_at"] if before["tiers"] else _now()))
    after = _snapshot(conn, offer_id)
    _event(conn, offer_id, actor, "updated", before, after)
    _fire(conn, after["product_id"])
    return after


def confirm(conn, *, supplier_id: int, offer_id: int, actor: int) -> dict:
    offer=_own(conn, supplier_id, offer_id)
    if not policy.effective(conn,offer["product_id"],offer["channel"]):raise ConflictError("وضعیت یا نوع عرضه کالا اجازه تأیید نمی‌دهد",code="product_channel_unavailable")
    stamp = _now()
    conn.execute("UPDATE seller_offers SET last_price_confirmed_at=?, last_inventory_confirmed_at=?, updated_at=datetime('now') WHERE id=?",
                 (stamp, stamp, offer_id))
    conn.execute("UPDATE offer_price_tiers SET confirmed_at=? WHERE offer_id=?", (stamp, offer_id))
    after = _snapshot(conn, offer_id)
    _event(conn, offer_id, actor, "confirmed", None, {"confirmed_at": stamp})
    _fire(conn, after["product_id"])
    return after


def list_mine(conn, *, supplier_id: int) -> list[dict]:
    rows = conn.execute("""SELECT so.id FROM seller_offers so WHERE so.supplier_id=? ORDER BY so.id DESC""", (supplier_id,)).fetchall()
    out = []
    for r in rows:
        o = _snapshot(conn, r["id"])
        p = conn.execute("""SELECT p.slug, p.sku, p.title_fa, m.variant_label FROM products p LEFT JOIN master_products m ON m.id=p.master_product_id
                            WHERE p.id=?""", (o["product_id"],)).fetchone()
        o["product"] = dict(p) if p else None
        o["fresh"] = bool(conn.execute("""SELECT datetime(?) >= datetime('now','-24 hours') AND datetime(?) >= datetime('now','-24 hours')""",
                                       (o["last_price_confirmed_at"], o["last_inventory_confirmed_at"])).fetchone()[0]) \
            if o["last_price_confirmed_at"] and o["last_inventory_confirmed_at"] else False
        out.append(o)
    return out


def sellable_catalog(conn, *, q: str | None) -> list[dict]:
    from app.services import storefront_service
    res = storefront_service.search(conn, q=q, page=1, page_size=48)
    ids = []
    for c in res["items"]:
        ids.append(c["id"])
    data = storefront_service._load(conn)
    out = []
    fams = {c["family_slug"] for c in res["items"] if c["family_slug"]}
    for s in data["skus"]:
        if s.id in ids or (s.family_slug and s.family_slug in fams):
            out.append({"product_id": s.id, "slug": s.slug, "sku": s.sku, "title_fa": s.title, "variant_label": s.label, "brand_fa": s.brand,"product_supply_channel":s.supply_channel,"allowed_channels":list(policy.channels(s.supply_channel))})
    return out


def contract_organizations(conn, *, supplier_id: int) -> list[dict]:
    """Organizations this supplier actually works with (RFQ invitations or purchase orders) — the only valid
    targets for organization-specific contract tiers. Never the full organization directory."""
    return [dict(r) for r in conn.execute(
        """SELECT DISTINCT o.id, o.display_name, o.provenance FROM organizations o
           WHERE o.id IN (SELECT r.organization_id FROM rfq_suppliers rs JOIN rfqs r ON r.id=rs.rfq_id WHERE rs.supplier_id=?)
              OR o.id IN (SELECT po.organization_id FROM purchase_orders po JOIN supplier_quotes q ON q.id=po.awarded_supplier_quote_id
                          WHERE q.supplier_id=?)
           ORDER BY o.display_name""", (supplier_id, supplier_id))]


def _check_contract_orgs(conn, supplier_id: int, tiers: list[dict]) -> None:
    allowed = {o["id"] for o in contract_organizations(conn, supplier_id=supplier_id)}
    for t in tiers:
        if t["organization_id"] and (t["channel"] != "organization" or t["organization_id"] not in allowed):
            raise ValidationError("قیمت قراردادی فقط برای سازمان‌هایی که با شما کار می‌کنند و در کانال سازمانی مجاز است")


def _scope(conn,pid,data):
    p=policy.sku_policy(conn,pid)
    if not p or p['status']!='active':raise ConflictError('کالا غیرفعال است',code='product_channel_unavailable')
    if not set(policy.channels(data['channel'])).issubset(policy.channels(p['supply_channel'])):
        raise ValidationError('کانال Offer باید در نوع عرضه مجاز کالا باشد')
    for tier in data['tiers']:
        if tier['channel'] not in policy.channels(data['channel']):raise ValidationError('کانال پله قیمت با نوع عرضه Offer سازگار نیست')
