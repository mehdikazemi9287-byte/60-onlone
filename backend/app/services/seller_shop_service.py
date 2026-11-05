"""Phase 1 — seller shops (غرفه).

A seller registers themselves, gets a shop page and link, sells through seller_offers
(the existing marketplace core), pays a commission resolved per category and channel,
and is settled only after an escrow hold that follows delivery.

Ideas taken from working marketplaces:
- Basalam: sign-up with a mobile number and accepted terms; commission by category,
  lower for wholesale; settlement after the buyer's satisfaction window.
- Amazon: account health with defect < 1%, pre-fulfilment cancel < 2.5%, late < 4%;
  funds are withheld while an account is suspended (A-to-z style protection).
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError

SELLER_KINDS = ("shop", "brand", "partner")
TERMS_VERSION = "shop-terms-1405-1"
DEFAULT_RATE_BPS = 1000

# Health thresholds in basis points (1% = 100 bps). Twice the target suspends.
HEALTH_TARGETS = {"defect": 100, "cancel": 250, "late": 400}
HEALTH_MIN_ORDERS = 5
SUSPEND_MIN_ORDERS = 10

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
_MOBILE = re.compile(r"^09\d{9}$")
_RESERVED = {"admin", "api", "shop", "shops", "supplier", "seller", "60online", "official", "support", "terms", "apply"}


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def hold_days() -> int:
    """Days after delivery before a payable can be settled (Iran's e-commerce law gives 7)."""
    try:
        value = int(os.environ.get("MARKETPLACE_HOLD_DAYS", "7"))
    except ValueError:
        value = 7
    return max(0, min(value, 60))


# ── validation ────────────────────────────────────────────────────────────────

def _text(d: dict, key: str, limit: int, *, required: bool = False) -> str | None:
    value = d.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"«{key}» الزامی است", details={"field": key})
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValidationError(f"«{key}» نامعتبر است", details={"field": key})
    return value.strip()


def valid_national_id(value: str) -> bool:
    """10-digit individual code (with checksum) or 11-digit legal-entity id."""
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        return False
    if len(value) == 11:
        return len(set(value)) > 1
    if len(value) != 10 or len(set(value)) == 1:
        return False
    check = int(value[9])
    s = sum(int(value[i]) * (10 - i) for i in range(9)) % 11
    return check == s if s < 2 else check == 11 - s


def valid_sheba(value: str) -> bool:
    """IR + 24 digits, ISO 13616 mod-97 check."""
    if not isinstance(value, str):
        return False
    v = value.replace(" ", "").upper()
    if not re.fullmatch(r"IR\d{24}", v):
        return False
    moved = v[4:] + "1827" + v[2:4]  # I=18, R=27
    return int(moved) % 97 == 1


def _slug(value: str | None, fallback_id: int | None = None) -> str:
    if value is None:
        if fallback_id is None:
            raise ValidationError("آدرس غرفه (slug) الزامی است")
        return f"shop-{fallback_id}"
    v = value.strip().lower()
    if not _SLUG.fullmatch(v) or "--" in v or v in _RESERVED:
        raise ValidationError("آدرس غرفه فقط حروف لاتین کوچک، عدد و خط تیره، ۳ تا ۴۰ نویسه", details={"field": "shop_slug"})
    return v


# ── commission ────────────────────────────────────────────────────────────────

def resolve_commission_bps(conn: sqlite3.Connection, *, supplier_id: int,
                           category_id: int | None, channel: str) -> int:
    s = conn.execute("SELECT seller_kind, commission_rate_bps FROM suppliers WHERE id=?",
                     (supplier_id,)).fetchone()
    if s is None:
        raise NotFoundError("فروشنده یافت نشد")
    if s["commission_rate_bps"] is not None:
        return int(s["commission_rate_bps"])
    kind = s["seller_kind"]
    candidates = [(kind, category_id), (kind, None), (None, category_id), (None, None)]
    for k, cat in candidates:
        for ch in (channel, "any"):
            row = conn.execute(
                "SELECT rate_bps FROM commission_rules WHERE (seller_kind = ? OR (seller_kind IS NULL AND ? IS NULL)) "
                "AND (category_id = ? OR (category_id IS NULL AND ? IS NULL)) AND channel=? "
                "ORDER BY id DESC LIMIT 1", (k, k, cat, cat, ch)).fetchone()
            if row:
                # An organization-channel rule for any kind beats the kind's retail default.
                # Contracted suppliers keep their contract rate on every channel.
                if ch == "any" and channel == "organization" and k == kind and cat is None and kind != "supplier":
                    org = conn.execute(
                        "SELECT rate_bps FROM commission_rules WHERE seller_kind IS NULL AND category_id IS NULL "
                        "AND channel='organization' ORDER BY id DESC LIMIT 1").fetchone()
                    if org:
                        return min(int(row["rate_bps"]), int(org["rate_bps"]))
                return int(row["rate_bps"])
    return DEFAULT_RATE_BPS


def commission_for_fulfillment(conn: sqlite3.Connection, fulfillment_order_id: int) -> dict:
    """Per-line commission snapshot for a delivered fulfillment order."""
    fo = conn.execute(
        "SELECT fo.supplier_id, o.organization_id FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
        "WHERE fo.id=?", (fulfillment_order_id,)).fetchone()
    channel = "organization" if fo["organization_id"] else "retail"
    rows = conn.execute(
        "SELECT i.product_id, p.category_id, COALESCE(i.line_cost_minor, i.line_selling_minor) AS gross "
        "FROM fulfillment_order_items i JOIN products p ON p.id=i.product_id WHERE i.fulfillment_order_id=?",
        (fulfillment_order_id,)).fetchall()
    gross = commission = 0
    for r in rows:
        bps = resolve_commission_bps(conn, supplier_id=fo["supplier_id"], category_id=r["category_id"], channel=channel)
        gross += int(r["gross"])
        commission += (int(r["gross"]) * bps) // 10_000
    effective = (commission * 10_000) // gross if gross else 0
    return {"channel": channel, "gross_minor": gross, "commission_minor": commission, "rate_bps": effective}


# ── registration and review ───────────────────────────────────────────────────

def apply(conn: sqlite3.Connection, *, user_id: int, data: dict) -> dict:
    allowed = {"seller_kind", "legal_name", "shop_title", "shop_slug", "national_id", "mobile", "email",
               "province", "city", "address", "sheba", "bank_name", "shop_bio", "accept_terms"}
    extra = set(data) - allowed
    if extra:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(extra)})
    if data.get("accept_terms") is not True:
        raise ValidationError("پذیرفتن قوانین غرفه‌داری لازم است")
    kind = data.get("seller_kind", "shop")
    if kind not in SELLER_KINDS:
        raise ValidationError("نوع فروشنده باید غرفه‌دار، برند رسمی یا شریک باشد")
    if conn.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND status='active'", (user_id,)).fetchone():
        raise ConflictError("عضو فعال یک سازمان نمی‌تواند هم‌زمان غرفه‌دار باشد", code="org_member_cannot_sell")
    if conn.execute("SELECT 1 FROM supplier_users WHERE user_id=? AND status='active'", (user_id,)).fetchone():
        raise ConflictError("این حساب قبلاً غرفه دارد", code="shop_exists")
    legal = _text(data, "legal_name", 200, required=True)
    title = _text(data, "shop_title", 120, required=True)
    nid = _text(data, "national_id", 11, required=True)
    if not valid_national_id(nid):
        raise ValidationError("کد ملی یا شناسهٔ ملی نامعتبر است", details={"field": "national_id"})
    mobile = _text(data, "mobile", 11, required=True)
    if not _MOBILE.fullmatch(mobile):
        raise ValidationError("شمارهٔ همراه باید ۱۱ رقم و با ۰۹ شروع شود", details={"field": "mobile"})
    sheba = _text(data, "sheba", 34)
    if sheba is not None:
        sheba = sheba.replace(" ", "").upper()
        if not valid_sheba(sheba):
            raise ValidationError("شمارهٔ شبا نامعتبر است", details={"field": "sheba"})
    province = _text(data, "province", 100, required=True)
    city = _text(data, "city", 100, required=True)
    address = _text(data, "address", 1000)
    slug = _slug(data.get("shop_slug"))
    if conn.execute("SELECT 1 FROM suppliers WHERE shop_slug=?", (slug,)).fetchone():
        raise ConflictError("این آدرس غرفه قبلاً گرفته شده است", code="shop_slug_taken", details={"field": "shop_slug"})
    if conn.execute("SELECT 1 FROM suppliers WHERE national_id=?", (nid,)).fetchone():
        raise ConflictError("با این شناسه قبلاً فروشنده ثبت شده است", code="supplier_national_id_duplicate")
    stamp = _iso(_now())
    supplier_type = "producer" if kind == "brand" else "local_shop"
    cur = conn.execute(
        """INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, phone, email,
               bank_name, sheba, user_id, onboarding_stage, seller_kind, shop_slug, shop_title, shop_bio,
               shop_province, shop_city, terms_version, terms_accepted_at)
           VALUES (?,?,?,?, 'pending', ?,?,?,?,?, 'submitted', ?,?,?,?,?,?,?,?)""",
        (legal, title, nid, supplier_type, mobile, _text(data, "email", 200), _text(data, "bank_name", 100),
         sheba, user_id, kind, slug, title, _text(data, "shop_bio", 2000), province, city, TERMS_VERSION, stamp))
    sid = int(cur.lastrowid)
    conn.execute(
        """INSERT INTO supplier_locations (supplier_id, province, city, address, status, can_intercity_shipping)
           VALUES (?,?,?,?, 'active', 1)""", (sid, province, city, address))
    conn.execute("INSERT INTO supplier_users (supplier_id, user_id, role, status) VALUES (?,?, 'owner', 'active')",
                 (sid, user_id))
    conn.execute(
        "INSERT INTO supplier_onboarding_events (supplier_id, from_stage, to_stage, actor_user_id, note) "
        "VALUES (?, 'draft', 'submitted', ?, 'ثبت‌نام خودکار غرفه')", (sid, user_id))
    return shop_view(conn, sid, private=True)


def review(conn: sqlite3.Connection, *, admin_id: int, supplier_id: int, decision: str, note: str | None) -> dict:
    s = conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if s is None or s["seller_kind"] == "supplier":
        raise NotFoundError("درخواست غرفه یافت نشد")
    if s["onboarding_stage"] not in ("submitted", "under_review"):
        raise ConflictError("این درخواست قبلاً بررسی شده است", code="already_reviewed")
    if decision == "approve":
        stage, status = "approved", "active"
    elif decision == "reject":
        if not note:
            raise ValidationError("دلیل رد درخواست را بنویسید")
        stage, status = "rejected", "inactive"
    else:
        raise ValidationError("تصمیم باید approve یا reject باشد")
    conn.execute("UPDATE suppliers SET onboarding_stage=?, status=?, updated_at=datetime('now') WHERE id=?",
                 (stage, status, supplier_id))
    conn.execute(
        "INSERT INTO supplier_onboarding_events (supplier_id, from_stage, to_stage, actor_user_id, note) "
        "VALUES (?,?,?,?,?)", (supplier_id, s["onboarding_stage"], stage, admin_id, note))
    return shop_view(conn, supplier_id, private=True)


def update_profile(conn: sqlite3.Connection, *, supplier_id: int, data: dict, user_id: int | None = None) -> dict:
    allowed = {"shop_title", "shop_bio", "shop_logo_url", "sheba", "bank_name"}
    extra = set(data) - allowed
    if extra:
        raise ValidationError("این فیلدها از پنل غرفه قابل تغییر نیستند", details={"fields": sorted(extra)})
    sets, args = [], []
    for key, limit in (("shop_title", 120), ("shop_bio", 2000), ("bank_name", 100)):
        if key in data:
            sets.append(f"{key}=?")
            args.append(_text(data, key, limit, required=key == "shop_title"))
    if "shop_logo_url" in data:
        url = _text(data, "shop_logo_url", 1000)
        if url is not None and not (url.startswith("https://") or url.startswith("/")):
            raise ValidationError("نشانی لوگو باید https یا مسیر داخلی باشد")
        sets.append("shop_logo_url=?")
        args.append(url)
    if "sheba" in data:
        # Payout account: owner of a self-registered shop only; audited; payouts pause until an admin re-verifies.
        s = conn.execute("SELECT seller_kind, sheba FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        owner = user_id is not None and conn.execute(
            "SELECT 1 FROM supplier_users WHERE supplier_id=? AND user_id=? AND role='owner' AND status='active'",
            (supplier_id, user_id)).fetchone()
        if s["seller_kind"] == "supplier" or not owner:
            from app.core.errors import PermissionError_
            raise PermissionError_("فقط مالک غرفه می‌تواند شبا را تغییر دهد؛ تأمین‌کنندهٔ قراردادی از طریق ادمین")
        sheba = (_text(data, "sheba", 34) or "").replace(" ", "").upper()
        if not valid_sheba(sheba):
            raise ValidationError("شمارهٔ شبا نامعتبر است")
        if sheba != s["sheba"]:
            sets += ["sheba=?", "payout_hold=1"]
            args.append(sheba)
            conn.execute("INSERT INTO audit_logs(actor_user_id, action, entity_type, entity_id, metadata_json) "
                         "VALUES (?, 'shop_sheba_changed', 'supplier', ?, '{\"needs_review\": true}')",
                         (user_id, str(supplier_id)))
    if sets:
        conn.execute(f"UPDATE suppliers SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?",
                     (*args, supplier_id))
    return shop_view(conn, supplier_id, private=True)


# ── read models ───────────────────────────────────────────────────────────────

def shop_view(conn: sqlite3.Connection, supplier_id: int, *, private: bool = False) -> dict:
    s = conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if s is None:
        raise NotFoundError("غرفه یافت نشد")
    out = {"id": s["id"], "slug": s["shop_slug"], "title": s["shop_title"] or s["display_name"],
           "bio": s["shop_bio"], "logo_url": s["shop_logo_url"], "kind": s["seller_kind"],
           "province": s["shop_province"], "city": s["shop_city"], "rating_x10": s["rating_x10"],
           "official": _official(conn, s),
           "url": f"/shops/{s['shop_slug']}" if s["shop_slug"] else None}
    if private:
        out.update({"status": s["status"], "onboarding_stage": s["onboarding_stage"],
                    "health_status": s["health_status"], "legal_name": s["legal_name"],
                    "sheba_on_file": bool(s["sheba"]), "payout_hold": bool(s["payout_hold"]), "terms_version": s["terms_version"],
                    "commission_rate_bps": resolve_commission_bps(conn, supplier_id=supplier_id,
                                                                  category_id=None, channel="retail")})
    return out


def _official(conn, s) -> bool:
    if s["seller_kind"] != "brand" or s["status"] != "active":
        return False
    try:
        from app.services import brand_service
        return brand_service.is_official(conn, int(s["id"]))
    except Exception:  # brand tables absent on an old schema
        return False


def public_shop(conn: sqlite3.Connection, slug: str, *, page: int = 1, size: int = 24) -> dict:
    s = conn.execute(
        "SELECT id FROM suppliers WHERE shop_slug=? AND status='active' AND onboarding_stage='approved' "
        "AND provenance='real'", (slug.lower(),)).fetchone()
    if s is None:
        raise NotFoundError("غرفه یافت نشد یا فعال نیست")
    base = ("FROM seller_offers o JOIN products p ON p.id=o.product_id "
            "WHERE o.supplier_id=? AND o.status='active' AND o.provenance='real' AND p.is_active=1 "
            "AND o.channel IN ('retail','both')")
    total = conn.execute("SELECT COUNT(*) " + base, (s["id"],)).fetchone()[0]
    rows = conn.execute(
        "SELECT p.slug, p.title_fa, o.selling_price_minor, o.pricing_mode, o.stock_quantity - o.stock_reserved AS available, "
        "o.min_order_quantity " + base + " ORDER BY o.updated_at DESC LIMIT ? OFFSET ?",
        (s["id"], size, (page - 1) * size)).fetchall()
    items = [{"slug": r["slug"], "title": r["title_fa"],
              "price_minor": r["selling_price_minor"] if r["pricing_mode"] == "fixed" else None,
              "in_stock": (r["available"] or 0) > 0, "min_order_quantity": r["min_order_quantity"]} for r in rows]
    return {"shop": shop_view(conn, s["id"]), "items": items, "total": total, "page": page, "page_size": size}


def list_shops(conn: sqlite3.Connection, *, kind: str | None = None, q: str | None = None) -> list[dict]:
    where, args = ["status='active'", "onboarding_stage='approved'", "shop_slug IS NOT NULL", "provenance='real'"], []
    if kind:
        if kind not in SELLER_KINDS:
            raise ValidationError("نوع غرفه نامعتبر است")
        where.append("seller_kind=?")
        args.append(kind)
    if q:
        where.append("(shop_title LIKE ? OR display_name LIKE ?)")
        args += [f"%{q[:60]}%"] * 2
    rows = conn.execute(f"SELECT id FROM suppliers WHERE {' AND '.join(where)} ORDER BY "
                        "CASE seller_kind WHEN 'brand' THEN 0 ELSE 1 END, rating_x10 DESC, id LIMIT 200", args)
    return [shop_view(conn, r["id"]) for r in rows.fetchall()]


def applications(conn: sqlite3.Connection, *, stage: str = "submitted") -> list[dict]:
    rows = conn.execute("SELECT id FROM suppliers WHERE seller_kind<>'supplier' AND onboarding_stage=? ORDER BY id",
                        (stage,)).fetchall()
    return [shop_view(conn, r["id"], private=True) for r in rows]


def balance(conn: sqlite3.Connection, *, supplier_id: int, now: _dt.datetime | None = None) -> dict:
    """What the seller is owed: settleable now vs still in the escrow window."""
    stamp = _iso(now or _now())
    rows = conn.execute(
        "SELECT gross_minor, COALESCE(commission_minor, 0) AS c, available_at FROM supplier_payable_entries "
        "WHERE supplier_id=? AND status='unbatched'", (supplier_id,)).fetchall()
    ready = held = 0
    for r in rows:
        net = int(r["gross_minor"]) - int(r["c"])
        if r["available_at"] is None or r["available_at"] <= stamp:
            ready += net
        else:
            held += net
    health = conn.execute("SELECT health_status, payout_hold FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if health and (health["health_status"] == "suspended" or health["payout_hold"]):
        held, ready = held + ready, 0
    settled = conn.execute("SELECT COALESCE(SUM(net_minor),0) FROM settlement_batches WHERE supplier_id=? "
                           "AND status='completed'", (supplier_id,)).fetchone()[0]
    return {"ready_minor": ready, "held_minor": held, "settled_minor": int(settled), "hold_days": hold_days()}


# ── account health ────────────────────────────────────────────────────────────

def compute_health(conn: sqlite3.Connection, *, supplier_id: int, window_days: int = 60,
                   now: _dt.datetime | None = None, enforce: bool = True, record: bool = True) -> dict:
    t = now or _now()
    since = (t - _dt.timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
    stamp = t.strftime("%Y-%m-%d %H:%M:%S")
    fos = conn.execute(
        "SELECT id, order_id, status, promised_prep_at, dispatched_at, rejection_reason FROM fulfillment_orders "
        "WHERE supplier_id=? AND status<>'pending_assignment' AND replace(substr(created_at,1,19),'T',' ')>=?",
        (supplier_id, since)).fetchall()
    n = len(fos)
    cancel = sum(1 for f in fos if f["status"] == "rejected")
    late = 0
    for f in fos:
        promised = f["promised_prep_at"]
        if not promised or f["status"] in ("rejected", "cancelled"):
            continue
        done = f["dispatched_at"] or (None if f["status"] in ("delivered",) else stamp)
        if done and done.replace("T", " ")[:19] > promised.replace("T", " ")[:19]:
            late += 1
    order_ids = {f["order_id"] for f in fos}
    defect = 0
    if order_ids:
        marks = ",".join("?" * len(order_ids))
        defect = conn.execute(
            f"SELECT COUNT(DISTINCT order_id) FROM order_return_requests WHERE order_id IN ({marks}) "
            "AND status NOT IN ('rejected','cancelled')", list(order_ids)).fetchone()[0]
    rate = {k: (v * 10_000) // n if n else 0 for k, v in (("defect", defect), ("cancel", cancel), ("late", late))}
    status = "good"
    if n >= HEALTH_MIN_ORDERS and any(rate[k] >= HEALTH_TARGETS[k] for k in rate):
        status = "at_risk"
    if n >= SUSPEND_MIN_ORDERS and any(rate[k] >= 2 * HEALTH_TARGETS[k] for k in rate):
        status = "suspended"
    if record:
        conn.execute(
            """INSERT INTO seller_health_snapshots (supplier_id, window_days, orders_count, defect_count,
                   cancel_count, late_count, defect_bps, cancel_bps, late_bps, status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (supplier_id, window_days, n, defect, cancel, late, rate["defect"], rate["cancel"], rate["late"], status))
    if enforce:
        conn.execute("UPDATE suppliers SET health_status=? WHERE id=?", (status, supplier_id))
    return {"supplier_id": supplier_id, "orders": n, "defect_bps": rate["defect"], "cancel_bps": rate["cancel"],
            "late_bps": rate["late"], "targets_bps": HEALTH_TARGETS, "status": status}
