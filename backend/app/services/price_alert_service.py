"""Tiered Vambi price alerts (هشدار قیمت سطح‌بندی‌شده).

Core rule: every user watches, sees and is alerted about the price of THEIR OWN level only.

Levels are derived server-side from the account (never from the client) and re-checked on every read and run:
  consumer  — no active organization membership: retail price (qty 1).
  employee  — active member of an active organization without a buying role: retail price (qty 1) + welfare basket.
  org_buyer — buying role (organization_admin / procurement_agent / procurement_officer) in an active
              organization (buyer_kind='organization'): that organization's price at the watch quantity.
  shop      — buying role in an active retailer organization (buyer_kind='retailer', migration 0069):
              wholesale (organization-channel) price at the watch quantity (pack/carton).
  seller    — supplier account: automatic "no longer the best offer" per product and channel, never the
              competitor's price or name.

Prices come from cashier_service.buy_box (the single buy-box/price engine): retail context for consumer and
employee; buyer_context(organization) for org_buyer and shop, so an organization's contract tier is applied for
that organization only. The price shown and compared is the winner's landed unit price incl. VAT (consumer law).

STOREFRONT_PRICE_VISIBILITY: a user who may not see catalog prices gets no price in any watch response,
notification or chart, and cannot set a target price.

Delivery: an in-site notification for every alert; SMS (only to a verified phone) are batched into ONE digest per
user per run, at most one SMS per item per user per day (Tehran day) and a global daily cap
(PRICE_ALERT_DAILY_SMS_CAP, default 500). SMS texts carry no prices at all. A rerun in the same hour sends nothing
twice (state transitions + unique dedupe keys + one digest per user and run hour).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os

from app.core.errors import ApiError, ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import cashier_service as cashier
from app.services import sale_eligibility as se
from app.services.commerce_ops_service import notify

log = logging.getLogger(__name__)

LEVELS = ("consumer", "employee", "org_buyer", "shop")
LEVEL_FA = {"consumer": "مصرف‌کننده", "employee": "کارمند سازمان", "org_buyer": "خرید سازمانی",
            "shop": "فروشگاه طرف قرارداد", "seller": "فروشنده"}
LEVEL_ALERTS = {
    "consumer": ("price_target", "back_in_stock"),
    "employee": ("price_target", "back_in_stock", "welfare_added"),
    "org_buyer": ("price_drop", "new_seller", "contract_expiring"),
    "shop": ("price_drop", "new_tier", "back_in_stock"),
}
PRICE_ALERTS = {"price_target", "price_drop", "new_tier", "contract_expiring"}  # need price visibility
ALERT_FA = {"price_target": "ارزان شد", "back_in_stock": "موجود شد", "welfare_added": "به سبد رفاهی اضافه شد",
            "price_drop": "کاهش قیمت", "new_seller": "فروشندهٔ تازه", "contract_expiring": "پایان قیمت قراردادی",
            "new_tier": "پلهٔ تخفیف تعدادی جدید", "lost_best_offer": "دیگر بهترین پیشنهاد نیستی"}
SELLER_LEVEL_FA = {"retail": "خرده‌فروشی", "organization": "سازمانی و عمده"}
BUYER_ROLES = ("organization_admin", "procurement_agent")
MAX_WATCHES = 200
HISTORY_DAYS = 90
CONTRACT_WARN_DAYS = 7
DIGEST_ITEMS = 4
TEHRAN = _dt.timedelta(hours=3, minutes=30)  # Iran has had no DST since 2022


# ── time ─────────────────────────────────────────────────────────────────────

def _now(now=None) -> _dt.datetime:
    return now or _dt.datetime.now(_dt.timezone.utc)


def _stamp(now) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(now) -> str:
    return (now + TEHRAN).date().isoformat()


def _hour(now) -> str:
    return now.strftime("%Y-%m-%dT%H")


def daily_sms_cap() -> int:
    try:
        return max(0, int(os.environ.get("PRICE_ALERT_DAILY_SMS_CAP", "500")))
    except ValueError:
        return 500


def toman(minor: int | None) -> str:
    if minor is None:
        return "—"
    digits = f"{round(int(minor) / 10):,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
    return f"{digits} تومان"


# ── who may see prices (mirrors app.core.price_privacy._viewer_allowed, without a request) ──

def may_see_prices(conn, user) -> bool:
    from app.core import price_privacy
    from app.services.access_admin_service import acting_supplier_id
    mode = price_privacy.mode()
    if mode == "public" or mode == "members" or user["role"] == "admin":
        return True
    uid = int(user["id"])
    if conn.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND status='active' LIMIT 1", (uid,)).fetchone():
        return True
    return bool(acting_supplier_id(conn, uid))


# ── level detection ──────────────────────────────────────────────────────────

def _memberships(conn, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT m.id AS membership_id, m.organization_id, m.role, m.procurement_role, o.buyer_kind
           FROM organization_memberships m JOIN organizations o ON o.id = m.organization_id
           WHERE m.user_id=? AND m.status='active' AND o.status='active' ORDER BY m.organization_id""", (user_id,))]


def _level_of(m: dict) -> str:
    buyer = m["role"] in BUYER_ROLES or m["procurement_role"] == "procurement_officer"
    if not buyer:
        return "employee"
    return "shop" if m["buyer_kind"] == "retailer" else "org_buyer"


_PRIORITY = {"shop": 0, "org_buyer": 1, "employee": 2}


def detect_level(conn, user_id: int, organization_id=None) -> dict:
    """{level, organization_id, membership_id}. organization_id only chooses among the user's OWN active
    memberships; anything else is refused. A user with no membership is a consumer."""
    ms = _memberships(conn, user_id)
    if organization_id is not None:
        if isinstance(organization_id, bool) or not isinstance(organization_id, int):
            raise ValidationError("شناسهٔ سازمان نامعتبر است")
        m = next((x for x in ms if int(x["organization_id"]) == organization_id), None)
        if m is None:
            raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
        return {"level": _level_of(m), "organization_id": int(m["organization_id"]), "membership_id": int(m["membership_id"])}
    if not ms:
        return {"level": "consumer", "organization_id": None, "membership_id": None}
    m = sorted(ms, key=lambda x: (_PRIORITY[_level_of(x)], x["organization_id"]))[0]
    return {"level": _level_of(m), "organization_id": int(m["organization_id"]), "membership_id": int(m["membership_id"])}


def level_options(conn, user) -> dict:
    """What the client may show: the detected default level and the user's own organization contexts."""
    from app.services.access_admin_service import acting_supplier_id
    uid = int(user["id"])
    ms = _memberships(conn, uid)
    default = detect_level(conn, uid)
    names = {r["id"]: r["display_name"] for r in conn.execute(
        f"SELECT id, display_name FROM organizations WHERE id IN ({','.join('?' * len(ms)) or 'NULL'})",
        [m["organization_id"] for m in ms])} if ms else {}
    visible = may_see_prices(conn, user)
    return {"level": default["level"], "level_fa": LEVEL_FA[default["level"]], "organization_id": default["organization_id"],
            "alert_types": _allowed_types(default["level"], visible), "price_visible": visible,
            "is_seller": bool(acting_supplier_id(conn, uid)),
            "options": [{"organization_id": int(m["organization_id"]), "organization_name": names.get(m["organization_id"]),
                         "level": _level_of(m), "level_fa": LEVEL_FA[_level_of(m)]} for m in ms]}


def _allowed_types(level: str, visible: bool) -> list[str]:
    return [t for t in LEVEL_ALERTS[level] if visible or t not in PRICE_ALERTS]


# ── observation at a level (all prices via cashier_service.buy_box) ──────────

def _welfare_covers(conn, membership_id: int | None, product_id: int, now) -> bool:
    if not membership_id:
        return False
    from app.services import welfare_wallet_service as welfare
    row = conn.execute("SELECT c.slug FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=?",
                       (product_id,)).fetchone()
    slug = row["slug"] if row else None
    for p in welfare.eligible_plans(conn, membership_id, now):
        if (p["plan_type"] == "product" and product_id in p["product_ids"]) or \
                (p["plan_type"] == "category" and slug and slug in p["category_slugs"]):
            return True
    return False


def _org_tier_steps(conn, product_id: int, organization_id: int, now) -> list[int]:
    """min_qty of fresh organization-channel quantity tiers this organization can use (general + its own contract)."""
    cutoff = (now - _dt.timedelta(hours=se.MAX_CONFIRMATION_AGE_HOURS))
    steps = set()
    for t in conn.execute(
            """SELECT t.min_qty, t.confirmed_at FROM offer_price_tiers t
               JOIN seller_offers so ON so.id=t.offer_id JOIN suppliers s ON s.id=so.supplier_id
               WHERE so.product_id=? AND so.status='active' AND s.status='active' AND t.channel='organization'
                 AND (t.organization_id IS NULL OR t.organization_id=?)""", (product_id, organization_id)):
        ts = cashier._parse_ts(t["confirmed_at"])
        if ts and ts >= cutoff:
            steps.add(int(t["min_qty"]))
    return sorted(steps)


def _expiring_contracts(conn, product_id: int, organization_id: int, now) -> list[str]:
    """Offers carrying THIS organization's contract tier whose validity ends within 7 days (offer_id:date)."""
    today = _day(now)
    until = (now + TEHRAN + _dt.timedelta(days=CONTRACT_WARN_DAYS)).date().isoformat()
    return sorted({f"{r['id']}:{str(r['valid_until'])[:10]}" for r in conn.execute(
        """SELECT DISTINCT so.id, so.valid_until FROM seller_offers so
           JOIN offer_price_tiers t ON t.offer_id=so.id AND t.organization_id=? AND t.channel='organization'
           WHERE so.product_id=? AND so.status='active' AND so.valid_until IS NOT NULL""", (organization_id, product_id))
        if today <= str(r["valid_until"])[:10] <= until})


def observe(conn, *, user_id: int, product_id: int, level: str, organization_id, membership_id, quantity: int, now=None) -> dict:
    now = _now(now)
    if level in ("consumer", "employee"):
        ctx, qty = None, 1
    else:
        ctx = cashier.buyer_context(conn, user_id=user_id, organization_id=organization_id, use_credit=False)
        qty = quantity
    box = cashier.buy_box(conn, product_id, ctx, quantity=qty, now=now)
    w = box["winner"]
    obs = {"price": w["landed_unit_incl_vat_minor"] if w else None, "in_stock": w is not None,
           "sellers": sorted({int(o["supplier_id"]) for o in box["offers"] if o["eligible"]})}
    if level == "employee":
        obs["welfare"] = _welfare_covers(conn, membership_id, product_id, now)
    if level == "shop":
        obs["tiers"] = _org_tier_steps(conn, product_id, organization_id, now)
    if level == "org_buyer":
        obs["expiring"] = _expiring_contracts(conn, product_id, organization_id, now)
    return obs


# ── watches API ──────────────────────────────────────────────────────────────

def _product(conn, *, slug=None, product_id=None):
    if slug is not None:
        row = conn.execute("SELECT id, slug, title_fa, provenance, is_active FROM products WHERE slug=?", (str(slug)[:200],)).fetchone()
    elif product_id is not None and isinstance(product_id, int) and not isinstance(product_id, bool):
        row = conn.execute("SELECT id, slug, title_fa, provenance, is_active FROM products WHERE id=?", (product_id,)).fetchone()
    else:
        raise ValidationError("کالا مشخص نشده است", details={"slug": "لازم"})
    if not row or not row["is_active"] or row["provenance"] not in se.allowed_provenance():
        raise NotFoundError("محصول یافت نشد", code="product_not_found")
    return row


def _int(v, field, lo, hi, optional=True):
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValidationError(f"{field} نامعتبر است", details={field: "نامعتبر"})
    return v


def _types(raw, level: str, visible: bool) -> list[str]:
    allowed = _allowed_types(level, visible)
    if raw is None:
        return allowed
    if not isinstance(raw, list) or not raw or not all(isinstance(t, str) for t in raw):
        raise ValidationError("نوع هشدار نامعتبر است", details={"alert_types": "نامعتبر"})
    for t in raw:
        if t not in LEVEL_ALERTS[level]:
            raise ValidationError("این نوع هشدار برای سطح شما نیست", code="alert_type_not_for_level",
                                  details={"alert_types": t})
        if t not in allowed:
            raise PermissionError_("برای دیدن قیمت‌ها وارد حساب سازمانی شوید", code="login_required_for_prices")
    return sorted(set(raw), key=LEVEL_ALERTS[level].index)


def _default_quantity(conn, product_id: int) -> int:
    row = conn.execute("""SELECT MIN(COALESCE(min_order_quantity,1)) FROM seller_offers
                          WHERE product_id=? AND status='active' AND channel IN ('organization','both')""", (product_id,)).fetchone()
    return max(1, int(row[0] or 1))


def _current_view(conn, user, w: dict, visible: bool) -> dict:
    """The stored observation, shown only when the watch's level is still the user's level today."""
    try:
        now_level = detect_level(conn, int(user["id"]), w["organization_id"]) if w["organization_id"] else detect_level(conn, int(user["id"]))
        same = now_level["level"] == w["level"] and now_level["organization_id"] == w["organization_id"]
    except ApiError:
        same = False
    state = json.loads(w["state_json"] or "{}") if same else {}
    return {"price_minor": state.get("price") if (visible and same) else None, "in_stock": state.get("in_stock") if same else None,
            "checked_at": w["checked_at"] if same else None, "level_changed": not same}


def _view(conn, user, row, visible: bool, product=None) -> dict:
    w = dict(row)
    p = product or conn.execute("SELECT slug, title_fa FROM products WHERE id=?", (w["product_id"],)).fetchone()
    out = {"id": w["id"], "product": {"id": w["product_id"], "slug": p["slug"], "title_fa": p["title_fa"]},
           "level": w["level"], "level_fa": LEVEL_FA[w["level"]], "organization_id": w["organization_id"],
           "quantity": w["quantity"], "target_price_minor": w["target_price_minor"] if visible else None,
           "alert_types": [t for t in w["alert_types"].split(",") if t], "sms_enabled": bool(w["sms_enabled"]),
           "active": bool(w["active"]), "created_at": w["created_at"], "last_notified_at": w["last_notified_at"],
           "current": _current_view(conn, user, w, visible)}
    if not visible:
        out["price_hidden"] = True
    return out


def _own(conn, user_id: int, watch_id: int):
    row = conn.execute("SELECT * FROM price_watches WHERE id=? AND user_id=?", (watch_id, user_id)).fetchone()
    if row is None:
        raise NotFoundError("هشدار یافت نشد", code="price_watch_not_found")
    return row


def _buyer_level(conn, user, organization_id) -> dict:
    lv = detect_level(conn, int(user["id"]), organization_id)
    if lv["level"] == "consumer":
        from app.services.access_admin_service import acting_supplier_id
        if acting_supplier_id(conn, int(user["id"])):
            raise ConflictError("هشدار فروشنده‌ها خودکار است و در پنل فروشنده دیده می‌شود", code="seller_alerts_automatic")
    return lv


def create_watch(conn, user, data: dict, now=None) -> tuple[dict, bool]:
    now = _now(now)
    if not isinstance(data, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    uid = int(user["id"])
    product = _product(conn, slug=data.get("slug"), product_id=data.get("product_id"))
    lv = _buyer_level(conn, user, data.get("organization_id"))
    visible = may_see_prices(conn, user)
    types = _types(data.get("alert_types"), lv["level"], visible)
    target = _int(data.get("target_price_minor"), "target_price_minor", 1, 10**13)
    if target is not None and (not visible or "price_target" not in LEVEL_ALERTS[lv["level"]]):
        raise (PermissionError_("برای دیدن قیمت‌ها وارد حساب سازمانی شوید", code="login_required_for_prices") if not visible
               else ValidationError("قیمت هدف برای سطح شما نیست", code="alert_type_not_for_level"))
    if lv["level"] in ("consumer", "employee"):
        qty = 1
    else:
        qty = _int(data.get("quantity"), "quantity", 1, 100_000) or _default_quantity(conn, int(product["id"]))
    sms = data.get("sms_enabled", True)
    if not isinstance(sms, bool):
        raise ValidationError("sms_enabled نامعتبر است")
    obs = observe(conn, user_id=uid, product_id=int(product["id"]), level=lv["level"], organization_id=lv["organization_id"],
                  membership_id=lv["membership_id"], quantity=qty, now=now)
    existing = conn.execute("SELECT id FROM price_watches WHERE user_id=? AND product_id=? AND COALESCE(organization_id,0)=?",
                            (uid, int(product["id"]), lv["organization_id"] or 0)).fetchone()
    stamp = _stamp(now)
    if existing:
        conn.execute("""UPDATE price_watches SET level=?, quantity=?, target_price_minor=?, alert_types=?, sms_enabled=?,
                        state_json=?, checked_at=?, active=1, updated_at=? WHERE id=?""",
                     (lv["level"], qty, target, ",".join(types), int(sms), json.dumps(obs), stamp, stamp, int(existing["id"])))
        wid, created = int(existing["id"]), False
    else:
        if conn.execute("SELECT COUNT(*) FROM price_watches WHERE user_id=?", (uid,)).fetchone()[0] >= MAX_WATCHES:
            raise ConflictError("حداکثر تعداد کالاهای زیر نظر پر شده است", code="price_watch_limit")
        wid = int(conn.execute(
            """INSERT INTO price_watches (user_id, product_id, level, organization_id, quantity, target_price_minor, alert_types,
                                          sms_enabled, state_json, checked_at, active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (uid, int(product["id"]), lv["level"], lv["organization_id"], qty, target, ",".join(types), int(sms),
             json.dumps(obs), stamp, stamp, stamp)).lastrowid)
        created = True
    _record_history(conn, int(product["id"]), lv, qty, obs, now)
    return _view(conn, user, _own(conn, uid, wid), visible, product), created


def list_watches(conn, user) -> dict:
    visible = may_see_prices(conn, user)
    rows = conn.execute("SELECT * FROM price_watches WHERE user_id=? ORDER BY id DESC", (int(user["id"]),)).fetchall()
    out = {"items": [_view(conn, user, r, visible) for r in rows], "level": level_options(conn, user)}
    if not visible:
        out["price_hidden"] = True
    return out


def update_watch(conn, user, watch_id: int, data: dict, now=None) -> dict:
    now = _now(now)
    if not isinstance(data, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    row = dict(_own(conn, int(user["id"]), watch_id))
    visible = may_see_prices(conn, user)
    sets: dict = {}
    if "alert_types" in data:
        sets["alert_types"] = ",".join(_types(data["alert_types"], row["level"], visible))
    if "target_price_minor" in data:
        target = _int(data["target_price_minor"], "target_price_minor", 1, 10**13)
        if target is not None and (not visible or "price_target" not in LEVEL_ALERTS[row["level"]]):
            raise PermissionError_("برای دیدن قیمت‌ها وارد حساب سازمانی شوید", code="login_required_for_prices") if not visible \
                else ValidationError("قیمت هدف برای سطح شما نیست", code="alert_type_not_for_level")
        sets["target_price_minor"] = target
    if "quantity" in data and row["level"] in ("org_buyer", "shop"):
        sets["quantity"] = _int(data["quantity"], "quantity", 1, 100_000, optional=False)
    for key in ("active", "sms_enabled"):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValidationError(f"{key} نامعتبر است")
            sets[key] = int(data[key])
    if sets:
        if "quantity" in sets and sets["quantity"] != row["quantity"]:
            sets["state_json"] = None  # new quantity = new baseline on the next run (no alert from the switch itself)
        sets["updated_at"] = _stamp(now)
        conn.execute(f"UPDATE price_watches SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), watch_id))
    return _view(conn, user, _own(conn, int(user["id"]), watch_id), visible)


def delete_watch(conn, user, watch_id: int) -> None:
    _own(conn, int(user["id"]), watch_id)
    conn.execute("DELETE FROM price_watches WHERE id=? AND user_id=?", (watch_id, int(user["id"])))


def history(conn, user, watch_id: int, days: int = HISTORY_DAYS, now=None) -> dict:
    now = _now(now)
    w = dict(_own(conn, int(user["id"]), watch_id))
    if not may_see_prices(conn, user):
        raise PermissionError_("برای دیدن قیمت‌ها وارد حساب سازمانی شوید", code="login_required_for_prices")
    # Re-check the level: a former member must never read the organization's history again.
    try:
        lv = detect_level(conn, int(user["id"]), w["organization_id"]) if w["organization_id"] else detect_level(conn, int(user["id"]))
    except ApiError:
        lv = {"level": None, "organization_id": None}
    if lv["level"] != w["level"] or lv["organization_id"] != w["organization_id"]:
        raise ConflictError("سطح حساب شما تغییر کرده است؛ نمودار پس از بررسی بعدی به‌روز می‌شود", code="price_watch_level_changed")
    days = max(1, min(HISTORY_DAYS, int(days)))
    since = (now + TEHRAN - _dt.timedelta(days=days - 1)).date().isoformat()
    scope, key, qty = _history_key(lv, w["quantity"])
    rows = conn.execute("""SELECT day, min_price_minor, last_price_minor, in_stock FROM price_history_daily
                           WHERE product_id=? AND scope=? AND organization_key=? AND quantity=? AND day>=? ORDER BY day""",
                        (w["product_id"], scope, key, qty, since)).fetchall()
    return {"watch_id": watch_id, "level": w["level"], "level_fa": LEVEL_FA[w["level"]], "quantity": qty, "days": days,
            "points": [{"day": r["day"], "min_price_minor": r["min_price_minor"], "price_minor": r["last_price_minor"],
                        "in_stock": bool(r["in_stock"])} for r in rows]}


def _history_key(lv: dict, quantity: int) -> tuple[str, int, int]:
    if lv["level"] in ("consumer", "employee"):
        return "retail", 0, 1
    return "organization", int(lv["organization_id"]), int(quantity)


def _record_history(conn, product_id: int, lv: dict, quantity: int, obs: dict, now) -> None:
    scope, key, qty = _history_key(lv, quantity)
    _upsert_history(conn, product_id, scope, key, qty, obs["price"], obs["in_stock"], now)


def _upsert_history(conn, product_id, scope, key, qty, price, in_stock, now) -> None:
    conn.execute(
        """INSERT INTO price_history_daily (product_id, scope, organization_key, quantity, day, min_price_minor,
                                            last_price_minor, in_stock, updated_at) VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (product_id, scope, organization_key, quantity, day) DO UPDATE SET
             min_price_minor = CASE WHEN excluded.min_price_minor IS NULL THEN price_history_daily.min_price_minor
                                    WHEN price_history_daily.min_price_minor IS NULL THEN excluded.min_price_minor
                                    WHEN excluded.min_price_minor < price_history_daily.min_price_minor THEN excluded.min_price_minor
                                    ELSE price_history_daily.min_price_minor END,
             last_price_minor = excluded.last_price_minor,
             in_stock = CASE WHEN excluded.in_stock = 1 THEN 1 ELSE price_history_daily.in_stock END,
             updated_at = excluded.updated_at""",
        (product_id, scope, key, qty, _day(now), price, price, int(bool(in_stock)), _stamp(now)))


# ── the hourly run ───────────────────────────────────────────────────────────

def _event(conn, *, user_id, product, level, alert_type, dedupe, title, body, sms_text, now,
           watch_id=None, supplier_id=None, sms_ok=True, link=None) -> bool:
    phone = conn.execute("SELECT phone_verified, is_active FROM users WHERE id=?", (user_id,)).fetchone()
    if not phone or not phone["is_active"]:
        return False
    status = "pending" if (sms_ok and phone["phone_verified"]) else "none"
    cur = conn.execute(
        """INSERT INTO price_alert_events (user_id, product_id, watch_id, supplier_id, level, alert_type, dedupe_key,
                                           sms_text, sms_status, created_at, day) VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (dedupe_key) DO NOTHING""",
        (user_id, int(product["id"]), watch_id, supplier_id, level, alert_type, dedupe, sms_text[:160], status, _stamp(now), _day(now)))
    if not cur.rowcount:
        return False
    notify(conn, user_id, "price_alert_seller" if supplier_id else "price_alert", title, body,
           link or f"/products/{product['slug']}")
    return True


def _short(title: str) -> str:
    return title if len(title) <= 32 else title[:31] + "…"


def _alerts_for(w: dict, prev: dict, obs: dict, visible: bool) -> list[tuple[str, str, str]]:
    """[(alert_type, discriminator, body)] for the watch's own level only."""
    types = set(t for t in w["alert_types"].split(",") if t) & set(LEVEL_ALERTS[w["level"]])
    if not visible:
        types -= PRICE_ALERTS
    out = []
    price, before = obs.get("price"), prev.get("price")
    if "price_target" in types and price is not None:
        target = w["target_price_minor"]
        if target is not None:
            if price <= target and (before is None or before > target):
                out.append(("price_target", str(price), f"قیمت به {toman(price)} رسید (هدف شما: {toman(target)})."))
        elif before is not None and price < before:
            out.append(("price_target", str(price), f"قیمت از {toman(before)} به {toman(price)} رسید."))
    if "price_drop" in types and price is not None and before is not None and price < before:
        unit = "عدد" if w["quantity"] == 1 else f"{w['quantity']} عدد"
        out.append(("price_drop", str(price), f"قیمت هر واحد برای خرید {unit}: {toman(price)} (قبلاً {toman(before)})."))
    if "back_in_stock" in types and obs["in_stock"] and prev.get("in_stock") is False:
        out.append(("back_in_stock", "1", "قیمت و موجودی توسط فروشنده تأیید شده است."))
    if "new_seller" in types and set(obs["sellers"]) - set(prev.get("sellers", [])) and prev.get("sellers") is not None:
        out.append(("new_seller", ",".join(map(str, sorted(set(obs["sellers"]) - set(prev["sellers"])))),
                    "فروشندهٔ تازه‌ای این کالا را برای سازمان شما عرضه می‌کند."))
    if "new_tier" in types and prev.get("tiers") is not None:
        new = sorted(set(obs.get("tiers", [])) - set(prev["tiers"]))
        if new:
            out.append(("new_tier", ",".join(map(str, new)), f"تخفیف تعدادی تازه از {new[0]} عدد به بالا ثبت شد."))
    if "welfare_added" in types and obs.get("welfare") and prev.get("welfare") is False:
        out.append(("welfare_added", "1", "این کالا به سبد رفاهی سازمان شما اضافه شد."))
    if "contract_expiring" in types:
        seen = set(prev.get("expiring_notified", []))
        for key in obs.get("expiring", []):
            if key not in seen:
                out.append(("contract_expiring", key, f"قیمت قراردادی سازمان شما تا {key.split(':')[1]} اعتبار دارد."))
    return out


def run_watches(conn, now=None) -> dict:
    now = _now(now)
    hour = _hour(now)
    stats = {"checked": 0, "alerts": 0, "rebased": 0, "skipped": 0}
    users: dict = {}
    for w in [dict(r) for r in conn.execute("SELECT * FROM price_watches WHERE active=1 ORDER BY id")]:
        user = users.get(w["user_id"]) or conn.execute("SELECT id, role, is_active FROM users WHERE id=?", (w["user_id"],)).fetchone()
        users[w["user_id"]] = user
        if not user or not user["is_active"]:
            stats["skipped"] += 1
            continue
        product = conn.execute("SELECT id, slug, title_fa, provenance, is_active FROM products WHERE id=?", (w["product_id"],)).fetchone()
        if not product or not product["is_active"] or product["provenance"] not in se.allowed_provenance():
            stats["skipped"] += 1
            continue
        try:
            lv = detect_level(conn, w["user_id"], w["organization_id"]) if w["organization_id"] else detect_level(conn, w["user_id"])
        except ApiError:
            lv = detect_level(conn, w["user_id"])  # no longer a member: fall back to the user's real level
        stamp = _stamp(now)
        if lv["level"] != w["level"] or lv["organization_id"] != w["organization_id"]:
            clash = conn.execute("SELECT id FROM price_watches WHERE user_id=? AND product_id=? AND COALESCE(organization_id,0)=? AND id<>?",
                                 (w["user_id"], w["product_id"], lv["organization_id"] or 0, w["id"])).fetchone()
            if clash:
                conn.execute("UPDATE price_watches SET active=0, state_json=NULL, updated_at=? WHERE id=?", (stamp, w["id"]))
                stats["rebased"] += 1
                continue
            types = ",".join(t for t in w["alert_types"].split(",") if t in LEVEL_ALERTS[lv["level"]]) or ",".join(LEVEL_ALERTS[lv["level"]])
            qty = w["quantity"] if lv["level"] in ("org_buyer", "shop") else 1
            target = w["target_price_minor"] if "price_target" in LEVEL_ALERTS[lv["level"]] else None
            conn.execute("""UPDATE price_watches SET level=?, organization_id=?, quantity=?, alert_types=?, target_price_minor=?,
                            state_json=NULL, updated_at=? WHERE id=?""",
                         (lv["level"], lv["organization_id"], qty, types, target, stamp, w["id"]))
            w.update(level=lv["level"], organization_id=lv["organization_id"], quantity=qty, alert_types=types,
                     target_price_minor=target, state_json=None)
            stats["rebased"] += 1
        try:
            obs = observe(conn, user_id=w["user_id"], product_id=w["product_id"], level=w["level"], organization_id=w["organization_id"],
                          membership_id=lv["membership_id"], quantity=w["quantity"], now=now)
        except ApiError:
            stats["skipped"] += 1
            continue
        stats["checked"] += 1
        _record_history(conn, w["product_id"], lv, w["quantity"], obs, now)
        if w["state_json"] is None:  # new baseline: never alert on the first look
            obs["expiring_notified"] = obs.get("expiring", [])
            conn.execute("UPDATE price_watches SET state_json=?, checked_at=? WHERE id=?", (json.dumps(obs), stamp, w["id"]))
            continue
        prev = json.loads(w["state_json"])
        visible = may_see_prices(conn, user)
        fired = False
        for alert_type, disc, body in _alerts_for(w, prev, obs, visible):
            title = f"«{_short(product['title_fa'])}» {ALERT_FA[alert_type]}"
            if _event(conn, user_id=w["user_id"], product=product, level=w["level"], alert_type=alert_type,
                      dedupe=f"w{w['id']}:{alert_type}:{disc}:{hour}", title=title, body=body,
                      sms_text=f"«{_short(product['title_fa'])}» {ALERT_FA[alert_type]}", now=now, watch_id=w["id"],
                      sms_ok=bool(w["sms_enabled"])):
                stats["alerts"] += 1
                fired = True
        obs["expiring_notified"] = sorted(set(prev.get("expiring_notified", [])) | set(obs.get("expiring", [])))
        conn.execute("UPDATE price_watches SET state_json=?, checked_at=?" + (", last_notified_at=?" if fired else "") + " WHERE id=?",
                     (json.dumps(obs), stamp, *((stamp,) if fired else ()), w["id"]))
    return stats


def run_sellers(conn, now=None) -> dict:
    """Buy-box winner per product at the two public levels; a seller who was the best and no longer is gets one
    alert per transition. Contract (organization-specific) prices are never part of this comparison."""
    from app.services.procurement_notify import _supplier_users
    now = _now(now)
    hour, stamp = _hour(now), _stamp(now)
    stats = {"products": 0, "alerts": 0}
    prov = ",".join(f"'{p}'" for p in se.allowed_provenance())
    pids = [int(r[0]) for r in conn.execute(
        f"""SELECT DISTINCT so.product_id FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
            JOIN products p ON p.id=so.product_id
            WHERE so.status='active' AND s.status='active' AND p.is_active=1 AND p.provenance IN ({prov})
            ORDER BY so.product_id""")]
    org_ctx = {**cashier._retail_ctx(), "channel": "organization"}  # general organization price, no contract
    for pid in pids:
        stats["products"] += 1
        product = conn.execute("SELECT id, slug, title_fa FROM products WHERE id=?", (pid,)).fetchone()
        retail = cashier.buy_box(conn, pid, None, quantity=1, now=now)
        w = retail["winner"]
        _upsert_history(conn, pid, "retail", 0, 1, w["landed_unit_incl_vat_minor"] if w else None, w is not None, now)
        results: dict = {}  # (supplier_id, level) -> (is_best, offer_id)
        for o in retail["offers"]:
            if o["eligible"]:
                key = (int(o["supplier_id"]), "retail")
                best = bool(w and int(w["supplier_id"]) == key[0])
                results[key] = (results.get(key, (False, None))[0] or best, o["offer_id"])
        moqs = {int(r["id"]): int(r["min_order_quantity"] or 1) for r in conn.execute(
            "SELECT id, min_order_quantity FROM seller_offers WHERE product_id=? AND status='active'", (pid,))}
        for qty in sorted(set(max(1, q) for q in moqs.values()))[:5]:
            box = cashier.buy_box(conn, pid, org_ctx, quantity=qty, now=now)
            ow = box["winner"]
            for o in box["offers"]:
                if o["eligible"] and max(1, moqs.get(int(o["offer_id"]), 1)) == qty:
                    key = (int(o["supplier_id"]), "organization")
                    best = bool(ow and int(ow["supplier_id"]) == key[0])
                    results[key] = (results.get(key, (False, None))[0] or best, o["offer_id"])
        for (sid, level), (is_best, offer_id) in results.items():
            prev = conn.execute("SELECT is_best FROM price_alert_seller_state WHERE supplier_id=? AND product_id=? AND level=?",
                                (sid, pid, level)).fetchone()
            conn.execute("""INSERT INTO price_alert_seller_state (supplier_id, product_id, level, offer_id, is_best, updated_at)
                            VALUES (?,?,?,?,?,?) ON CONFLICT (supplier_id, product_id, level) DO UPDATE SET
                            offer_id=excluded.offer_id, is_best=excluded.is_best, updated_at=excluded.updated_at""",
                         (sid, pid, level, offer_id, int(is_best), stamp))
            if prev and prev["is_best"] and not is_best:
                title = f"«{_short(product['title_fa'])}»: {ALERT_FA['lost_best_offer']}"
                body = f"در سطح {SELLER_LEVEL_FA[level]} پیشنهاد دیگری اکنون بهتر از پیشنهاد شماست. قیمت، موجودی یا زمان تحویل خود را بررسی کنید."
                for uid in sorted(_supplier_users(conn, sid)):
                    if _event(conn, user_id=uid, product=product, level="seller", alert_type="lost_best_offer",
                              dedupe=f"s{sid}:{pid}:{level}:u{uid}:{hour}", title=title, body=body,
                              sms_text=f"«{_short(product['title_fa'])}» {SELLER_LEVEL_FA[level]}: {ALERT_FA['lost_best_offer']}",
                              now=now, supplier_id=sid, link="/sell"):
                        stats["alerts"] += 1
        # A seller whose offer dropped out of the eligible set keeps its old state row; it is not "beaten".
    return stats


def seller_alerts(conn, supplier_id: int) -> dict:
    """Seller panel: own buy-box status per product and level, plus recent alerts. Own prices only."""
    rows = conn.execute(
        """SELECT st.product_id, st.level, st.is_best, st.updated_at, st.offer_id, p.slug, p.title_fa,
                  so.selling_price_minor AS own_price_minor
           FROM price_alert_seller_state st JOIN products p ON p.id=st.product_id
           LEFT JOIN seller_offers so ON so.id=st.offer_id AND so.supplier_id=st.supplier_id
           WHERE st.supplier_id=? ORDER BY st.is_best, st.updated_at DESC LIMIT 200""", (supplier_id,)).fetchall()
    recent = conn.execute(
        """SELECT e.product_id, p.slug, p.title_fa, e.created_at, e.sms_text
           FROM price_alert_events e JOIN products p ON p.id=e.product_id
           WHERE e.supplier_id=? ORDER BY e.created_at DESC, e.id DESC LIMIT 200""", (supplier_id,)).fetchall()
    seen, items = set(), []
    for r in recent:
        k = (r["product_id"], r["created_at"], r["sms_text"])
        if k not in seen:
            seen.add(k)
            if len(items) >= 50:
                break
            items.append({"product": {"id": r["product_id"], "slug": r["slug"], "title_fa": r["title_fa"]},
                          "text": r["sms_text"], "created_at": r["created_at"]})
    return {"items": [{"product": {"id": r["product_id"], "slug": r["slug"], "title_fa": r["title_fa"]},
                       "level": r["level"], "level_fa": SELLER_LEVEL_FA[r["level"]], "is_best": bool(r["is_best"]),
                       "own_price_minor": r["own_price_minor"], "updated_at": r["updated_at"]} for r in rows],
            "recent": items}


# ── SMS digests ──────────────────────────────────────────────────────────────

def _digest_text(lines: list[str]) -> str:
    head = "شصت‌آنلاین | هشدار قیمت"
    body = "\n".join(lines[:DIGEST_ITEMS])
    more = f"\nو {len(lines) - DIGEST_ITEMS} مورد دیگر" if len(lines) > DIGEST_ITEMS else ""
    return f"{head}\n{body}{more}\nجزئیات: 60online.ir/me/price-alerts"


def send_digests(db, sender=None, now=None) -> dict:
    """One digest SMS per user per run hour from that user's own pending events (texts carry no prices)."""
    from app.adapters.sms import ConsoleSms, SmsError, sender_from_env
    now = _now(now)
    hour, day = _hour(now), _day(now)
    stats = {"sent": 0, "failed": 0, "skipped_item": 0, "skipped_cap": 0, "unavailable": 0}
    if sender is None:
        try:
            sender = sender_from_env()
        except SmsError:
            sender = None
        if isinstance(sender, ConsoleSms) and (os.environ.get("APP_ENV") or "").lower() == "production":
            sender = None  # never pretend a console "send" is a real SMS in production
    cap = daily_sms_cap()
    with db.read_transaction() as conn:
        users = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT user_id FROM price_alert_events WHERE sms_status='pending' ORDER BY user_id")]
    for uid in users:
        with db.write_transaction() as conn:
            pending = conn.execute("SELECT id, product_id, sms_text, day FROM price_alert_events WHERE user_id=? AND sms_status='pending' ORDER BY id",
                                   (uid,)).fetchall()
            if not pending:
                continue
            if conn.execute("SELECT 1 FROM price_alert_sms WHERE user_id=? AND run_hour=?", (uid, hour)).fetchone():
                continue  # this hour's digest already went out; the rest waits for the next run
            stale = [r["id"] for r in pending if r["day"] != day]  # yesterday's leftovers: in-site only
            texted_today = {int(r[0]) for r in conn.execute(
                "SELECT DISTINCT product_id FROM price_alert_events WHERE user_id=? AND day=? AND sms_status='sent'", (uid, day))}
            take, skip, seen = [], [], set()
            for r in pending:
                if r["id"] in stale:
                    continue
                if int(r["product_id"]) in texted_today:
                    skip.append(r["id"])
                    continue
                if int(r["product_id"]) in seen:
                    skip.append(r["id"])  # one line per item in a digest
                    continue
                seen.add(int(r["product_id"]))
                take.append(r)
            for ids, status in ((stale, "skipped_item"), (skip, "skipped_item")):
                if ids:
                    conn.execute(f"UPDATE price_alert_events SET sms_status=? WHERE id IN ({','.join('?' * len(ids))})", (status, *ids))
            stats["skipped_item"] += len(stale) + len(skip)
            if not take:
                continue
            phone = conn.execute("SELECT phone_verified FROM users WHERE id=? AND is_active=1", (uid,)).fetchone()
            ids = [r["id"] for r in take]
            marks = ",".join("?" * len(ids))
            if not phone or not phone["phone_verified"]:
                conn.execute(f"UPDATE price_alert_events SET sms_status='none' WHERE id IN ({marks})", ids)
                continue
            if sender is None:
                conn.execute(f"UPDATE price_alert_events SET sms_status='unavailable' WHERE id IN ({marks})", ids)
                stats["unavailable"] += len(ids)
                continue
            used = conn.execute("SELECT COUNT(*) FROM price_alert_sms WHERE day=? AND status IN ('sending','sent')", (day,)).fetchone()[0]
            if used >= cap:
                conn.execute(f"UPDATE price_alert_events SET sms_status='skipped_cap' WHERE id IN ({marks})", ids)
                stats["skipped_cap"] += len(ids)
                continue
            sms_id = int(conn.execute(
                "INSERT INTO price_alert_sms (user_id, run_hour, day, item_count, status, created_at) VALUES (?,?,?,?, 'sending', ?)",
                (uid, hour, day, len(ids), _stamp(now))).lastrowid)
            conn.execute(f"UPDATE price_alert_events SET sms_status='sent', sms_id=? WHERE id IN ({marks})", (sms_id, *ids))
            text, to = _digest_text([r["sms_text"] for r in take]), phone["phone_verified"]
        # Network call outside the DB transaction; the reservation above already blocks a second send this hour.
        try:
            sender.send_text(to, text)
            ok = True
        except Exception:  # noqa: BLE001 — a provider failure must not stop the other digests
            log.warning("price alert digest SMS failed for user %s", uid)
            ok = False
        with db.write_transaction() as conn:
            conn.execute("UPDATE price_alert_sms SET status=? WHERE id=?", ("sent" if ok else "failed", sms_id))
            if not ok:
                conn.execute("UPDATE price_alert_events SET sms_status='failed' WHERE sms_id=?", (sms_id,))
        stats["sent" if ok else "failed"] += 1
    return stats


def run(db, *, now=None, sender=None) -> dict:
    now = _now(now)
    with db.write_transaction() as conn:
        watches = run_watches(conn, now)
    with db.write_transaction() as conn:
        sellers = run_sellers(conn, now)
    sms = send_digests(db, sender=sender, now=now)
    return {"watches": watches, "sellers": sellers, "sms": sms}
