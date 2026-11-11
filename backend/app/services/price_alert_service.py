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

Delivery: an in-site notification for every alert (organization-level bodies carry no price: a notification
outlives membership). SMS only to a verified phone, batched into ONE digest per user, kind (buyer/seller) and run;
at most one SMS per item per user per Tehran day; PRICE_ALERT_USER_DAILY_SMS digests per user and day, buyer and seller digests counted together (default 2);
global daily budgets in billed parts (PRICE_ALERT_DAILY_SMS_PARTS_CAP 1500, PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP 500);
held 22:00–08:00 Tehran; sellers can turn their SMS off. SMS texts carry no prices and sanitized titles.
The job is bounded (3 s SMS timeout, stop after 3 consecutive provider failures, PRICE_ALERT_JOB_BUDGET_S = 120 s
total), works in short transactions with a SAVEPOINT per item, and on PostgreSQL takes an advisory lock so
overlapping runs serialize. A rerun in the same hour sends nothing twice (state transitions + unique dedupe keys
+ one reserved digest row per user, kind and hour). Retention: history and events older than 120 days are deleted.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import time

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
            "new_tier": "پلهٔ تخفیف تعدادی جدید", "lost_best_offer": "دیگر بهترین پیشنهاد نیستید"}
# UI chip labels (returned by the API so the client keeps no copy of the table)
CHIP_FA = {"price_target": "رسیدن به قیمت هدف", "back_in_stock": "موجود شد", "welfare_added": "اضافه شدن به سبد رفاهی",
           "price_drop": "کاهش قیمت", "new_seller": "فروشندهٔ تازه", "contract_expiring": "پایان قیمت قراردادی (۷ روز)",
           "new_tier": "پلهٔ تخفیف تعدادی جدید"}
SELLER_LEVEL_FA = {"retail": "خرده‌فروشی", "organization": "سازمانی و عمده"}
BUYER_ROLES = ("organization_admin", "procurement_agent")
MAX_WATCHES = 200
HISTORY_DAYS = 90
CONTRACT_WARN_DAYS = 7
DIGEST_ITEMS = 3
BATCH = 50                      # watches / products per short write transaction
LOCK_NS, JOB_LOCK = 60079, 0    # pg_advisory_xact_lock namespace; key 0 = the job, key = user id for watch creation
QUIET_FROM, QUIET_UNTIL = 22, 8  # Tehran hours: digest SMS held, in-site notifications immediate
PENDING_MAX_HOURS = 24          # an SMS line older than this is dropped (in-site notice already delivered)
SMS_TIMEOUT_S = 3.0
MAX_CONSECUTIVE_FAILURES = 3
JOB_BUDGET_S = 120              # PRICE_ALERT_JOB_BUDGET_S; leftovers wait for the next run
RETENTION_DAYS = 120
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
            "alert_fa": {t: CHIP_FA[t] for t in _allowed_types(default["level"], visible)},
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
    allowed = _allowed_types(w["level"], visible)
    out = {"id": w["id"], "product": {"id": w["product_id"], "slug": p["slug"], "title_fa": p["title_fa"]},
           "level": w["level"], "level_fa": LEVEL_FA[w["level"]], "organization_id": w["organization_id"],
           "quantity": w["quantity"], "target_price_minor": w["target_price_minor"] if visible else None,
           "alert_types": [t for t in w["alert_types"].split(",") if t and t in allowed],
           "allowed_alert_types": allowed, "alert_fa": {t: CHIP_FA[t] for t in allowed},
           "sms_enabled": bool(w["sms_enabled"]),
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


def _is_pg(conn) -> bool:
    return type(conn).__name__ == "_PgConnectionShim"


def _pg_lock(conn, key: int) -> None:
    """PostgreSQL: serialize per key for the rest of the transaction. SQLite writes are already serial."""
    if _is_pg(conn):
        conn.execute("SELECT pg_advisory_xact_lock(?, ?)", (LOCK_NS, int(key)))


def _buyer_level(conn, user, organization_id) -> dict:
    lv = detect_level(conn, int(user["id"]), organization_id)
    if lv["level"] == "consumer":
        from app.services.access_admin_service import acting_supplier_id
        if acting_supplier_id(conn, int(user["id"])):
            raise ConflictError("هشدار فروشنده‌ها خودکار است و در پنل فروشنده دیده می‌شود", code="seller_alerts_automatic")
    return lv


def _check_target(target, level: str, visible: bool) -> None:
    if target is None:
        return
    if not visible:
        raise PermissionError_("برای دیدن قیمت‌ها وارد حساب سازمانی شوید", code="login_required_for_prices")
    if "price_target" not in LEVEL_ALERTS[level]:
        raise ValidationError("قیمت هدف برای سطح شما نیست", code="alert_type_not_for_level")


def create_watch(conn, user, data: dict, now=None) -> tuple[dict, bool]:
    """Create, or reactivate an existing watch. On an existing watch only the fields present in the body change."""
    now = _now(now)
    if not isinstance(data, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    uid = int(user["id"])
    product = _product(conn, slug=data.get("slug"), product_id=data.get("product_id"))
    lv = _buyer_level(conn, user, data.get("organization_id"))
    visible = may_see_prices(conn, user)
    # validate everything that was sent, before any write
    types = _types(data.get("alert_types"), lv["level"], visible) if "alert_types" in data else None
    target = _int(data.get("target_price_minor"), "target_price_minor", 1, 10**13)
    _check_target(target, lv["level"], visible)
    qty_in = _int(data.get("quantity"), "quantity", 1, 100_000) if lv["level"] in ("org_buyer", "shop") else None
    if "sms_enabled" in data and not isinstance(data["sms_enabled"], bool):
        raise ValidationError("sms_enabled نامعتبر است")
    _pg_lock(conn, uid)
    key = (uid, int(product["id"]), lv["organization_id"] or 0)
    existing = conn.execute("SELECT * FROM price_watches WHERE user_id=? AND product_id=? AND COALESCE(organization_id,0)=?",
                            key).fetchone()
    stamp = _stamp(now)
    if existing and existing["level"] == lv["level"]:
        patch = {k: data[k] for k in ("alert_types", "target_price_minor", "quantity", "sms_enabled") if k in data}
        if lv["level"] in ("consumer", "employee"):
            patch.pop("quantity", None)
        patch["active"] = True
        return update_watch(conn, user, int(existing["id"]), patch, now), False
    qty = 1 if lv["level"] in ("consumer", "employee") else (qty_in or _default_quantity(conn, int(product["id"])))
    obs = observe(conn, user_id=uid, product_id=int(product["id"]), level=lv["level"], organization_id=lv["organization_id"],
                  membership_id=lv["membership_id"], quantity=qty, now=now)
    obs["expiring_notified"] = obs.get("expiring", [])
    if existing:  # same organization context but the user's level there changed: re-level, keep what still applies
        old = [t for t in existing["alert_types"].split(",") if t in LEVEL_ALERTS[lv["level"]]]
        types = types or old or _allowed_types(lv["level"], visible)
        target = target if "target_price_minor" in data else (
            existing["target_price_minor"] if "price_target" in LEVEL_ALERTS[lv["level"]] else None)
        sms = int(data["sms_enabled"]) if "sms_enabled" in data else int(existing["sms_enabled"])
        conn.execute("""UPDATE price_watches SET level=?, quantity=?, target_price_minor=?, alert_types=?, sms_enabled=?,
                        state_json=?, checked_at=?, active=1, updated_at=? WHERE id=?""",
                     (lv["level"], qty, target, ",".join(types), sms, json.dumps(obs), stamp, stamp, int(existing["id"])))
        _record_history(conn, int(product["id"]), lv, qty, obs, now)
        return _view(conn, user, _own(conn, uid, int(existing["id"])), visible, product), False
    if conn.execute("SELECT COUNT(*) FROM price_watches WHERE user_id=?", (uid,)).fetchone()[0] >= MAX_WATCHES:
        raise ConflictError("حداکثر تعداد کالاهای زیر نظر پر شده است", code="price_watch_limit")
    types = types or _allowed_types(lv["level"], visible)
    cur = conn.execute(
        """INSERT INTO price_watches (user_id, product_id, level, organization_id, quantity, target_price_minor, alert_types,
                                      sms_enabled, state_json, checked_at, active, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT DO NOTHING""",
        (uid, int(product["id"]), lv["level"], lv["organization_id"], qty, target, ",".join(types),
         int(data.get("sms_enabled", True)), json.dumps(obs), stamp, stamp, stamp))
    row = conn.execute("SELECT * FROM price_watches WHERE user_id=? AND product_id=? AND COALESCE(organization_id,0)=?",
                       key).fetchone()
    if not cur.rowcount:  # a concurrent request created it first: answer like a re-POST
        return _view(conn, user, row, visible, product), False
    _record_history(conn, int(product["id"]), lv, qty, obs, now)
    return _view(conn, user, row, visible, product), True


def list_watches(conn, user, product_slug: str | None = None) -> dict:
    visible = may_see_prices(conn, user)
    if product_slug is not None:
        rows = conn.execute("""SELECT w.* FROM price_watches w JOIN products p ON p.id=w.product_id
                               WHERE w.user_id=? AND p.slug=? ORDER BY w.id DESC""", (int(user["id"]), product_slug[:200])).fetchall()
    else:
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
    if sets.get("active") == 1 and not row["active"]:
        sets["state_json"] = None  # reactivated: fresh baseline, no alert from changes made while paused
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

_URL = re.compile(r"(https?://\S+|www\.\S+|\S+\.(?:ir|com|net|org|me|io|co|app|shop|site|info)\b\S*)", re.I)
_DIGITS = re.compile(r"[0-9۰-۹٠-٩]{4,}")


def sms_safe(title: str, limit: int = 24) -> str:
    """Seller-written titles go into SMS: no links, handles or phone/card-like digit runs."""
    t = _URL.sub(" ", str(title or ""))
    t = t.replace("@", " ")
    t = _DIGITS.sub(" ", t)
    t = " ".join(t.split())
    return (t if len(t) <= limit else t[:limit - 1] + "…") or "کالا"


def sms_parts(text: str) -> int:
    """Billed SMS parts: GSM-7 160/153, otherwise UCS-2 70/67."""
    n = len(text)
    if all(ord(c) < 128 for c in text):
        return 1 if n <= 160 else -(-n // 153)
    return 1 if n <= 70 else -(-n // 67)


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


ORG_LEVELS = ("org_buyer", "shop")


def _alerts_for(w: dict, prev: dict, obs: dict, visible: bool) -> list[tuple[str, str, str]]:
    """[(alert_type, discriminator, body)] for the watch's own level only. Organization-level bodies never carry a
    price: a notification outlives membership, so the price is shown only on /me/price-alerts after a level re-check."""
    types = set(t for t in w["alert_types"].split(",") if t) & set(LEVEL_ALERTS[w["level"]])
    if not visible:
        types -= PRICE_ALERTS
    out = []
    price, before = obs.get("price"), prev.get("price")
    if "price_target" in types and price is not None:  # consumer / employee: public retail price only
        target = w["target_price_minor"]
        if target is not None:
            if price <= target and (before is None or before > target):
                out.append(("price_target", str(price), f"قیمت به {toman(price)} رسید (هدف شما: {toman(target)})."))
        elif before is not None and price < before:
            out.append(("price_target", str(price), f"قیمت از {toman(before)} به {toman(price)} رسید."))
    if "price_drop" in types and price is not None and before is not None and price < before:
        unit = "هر عدد" if w["quantity"] == 1 else f"خرید {w['quantity']} عددی"
        out.append(("price_drop", str(price), f"قیمت سطح شما برای {unit} کاهش یافت. قیمت فعلی را در «کالاهای زیر نظر» ببینید."))
    if "back_in_stock" in types and obs["in_stock"] and prev.get("in_stock") is False:
        out.append(("back_in_stock", "1", "قیمت و موجودی توسط فروشنده تأیید شده است."))
    if "new_seller" in types and prev.get("sellers") is not None and set(obs["sellers"]) - set(prev["sellers"]):
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


def _over(deadline) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _check_watch(conn, w: dict, now, users: dict, stats: dict) -> None:
    hour = _hour(now)
    user = users.get(w["user_id"]) or conn.execute("SELECT id, role, is_active FROM users WHERE id=?", (w["user_id"],)).fetchone()
    users[w["user_id"]] = user
    if not user or not user["is_active"]:
        stats["skipped"] += 1
        return
    product = conn.execute("SELECT id, slug, title_fa, provenance, is_active FROM products WHERE id=?", (w["product_id"],)).fetchone()
    if not product or not product["is_active"] or product["provenance"] not in se.allowed_provenance():
        stats["skipped"] += 1
        return
    try:
        lv = detect_level(conn, w["user_id"], w["organization_id"]) if w["organization_id"] else detect_level(conn, w["user_id"])
    except ApiError:
        lv = detect_level(conn, w["user_id"])  # no longer a member: fall back to the user's real level
    stamp = _stamp(now)
    if lv["level"] != w["level"] or lv["organization_id"] != w["organization_id"]:
        clash = conn.execute("SELECT id FROM price_watches WHERE user_id=? AND product_id=? AND COALESCE(organization_id,0)=? AND id<>?",
                             (w["user_id"], w["product_id"], lv["organization_id"] or 0, w["id"])).fetchone()
        stats["rebased"] += 1
        if clash:
            conn.execute("UPDATE price_watches SET active=0, state_json=NULL, updated_at=? WHERE id=?", (stamp, w["id"]))
            return
        types = ",".join(t for t in w["alert_types"].split(",") if t in LEVEL_ALERTS[lv["level"]]) or ",".join(LEVEL_ALERTS[lv["level"]])
        qty = w["quantity"] if lv["level"] in ORG_LEVELS else 1
        target = w["target_price_minor"] if "price_target" in LEVEL_ALERTS[lv["level"]] else None
        conn.execute("""UPDATE price_watches SET level=?, organization_id=?, quantity=?, alert_types=?, target_price_minor=?,
                        state_json=NULL, updated_at=? WHERE id=?""",
                     (lv["level"], lv["organization_id"], qty, types, target, stamp, w["id"]))
        w.update(level=lv["level"], organization_id=lv["organization_id"], quantity=qty, alert_types=types,
                 target_price_minor=target, state_json=None)
    obs = observe(conn, user_id=w["user_id"], product_id=w["product_id"], level=w["level"], organization_id=w["organization_id"],
                  membership_id=lv["membership_id"], quantity=w["quantity"], now=now)
    stats["checked"] += 1
    _record_history(conn, w["product_id"], lv, w["quantity"], obs, now)
    if w["state_json"] is None:  # new baseline: never alert on the first look
        obs["expiring_notified"] = obs.get("expiring", [])
        conn.execute("UPDATE price_watches SET state_json=?, checked_at=? WHERE id=?", (json.dumps(obs), stamp, w["id"]))
        return
    prev = json.loads(w["state_json"])
    visible = may_see_prices(conn, user)
    fired = False
    for alert_type, disc, body in _alerts_for(w, prev, obs, visible):
        org = w["level"] in ORG_LEVELS
        if _event(conn, user_id=w["user_id"], product=product, level=w["level"], alert_type=alert_type,
                  dedupe=f"w{w['id']}:{alert_type}:{disc}:{hour}", title=f"«{_short(product['title_fa'])}» {ALERT_FA[alert_type]}",
                  body=body, sms_text=f"«{sms_safe(product['title_fa'])}» {ALERT_FA[alert_type]}", now=now, watch_id=w["id"],
                  sms_ok=bool(w["sms_enabled"]), link="/me/price-alerts" if org else None):
            stats["alerts"] += 1
            fired = True
    obs["expiring_notified"] = sorted(set(prev.get("expiring_notified", [])) | set(obs.get("expiring", [])))
    conn.execute("UPDATE price_watches SET state_json=?, checked_at=?" + (", last_notified_at=?" if fired else "") + " WHERE id=?",
                 (json.dumps(obs), stamp, *((stamp,) if fired else ()), w["id"]))


def _guarded(conn, label: str, fn, stats: dict) -> None:
    """One bad row never aborts the run: each item runs in its own SAVEPOINT."""
    conn.execute("SAVEPOINT price_alert_item")
    try:
        fn()
    except Exception:  # noqa: BLE001 — logged and skipped; the next run retries it
        conn.execute("ROLLBACK TO SAVEPOINT price_alert_item")
        conn.execute("RELEASE SAVEPOINT price_alert_item")
        log.exception("price alerts: %s failed", label)
        stats["errors"] += 1
    else:
        conn.execute("RELEASE SAVEPOINT price_alert_item")


def run_watches(db, now=None, deadline=None) -> dict:
    now = _now(now)
    stats = {"checked": 0, "alerts": 0, "rebased": 0, "skipped": 0, "errors": 0, "deferred": 0}
    with db.read_transaction() as conn:
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM price_watches WHERE active=1 ORDER BY id")]
    users: dict = {}
    for start in range(0, len(ids), BATCH):
        if _over(deadline):
            stats["deferred"] += len(ids) - start
            break
        with db.write_transaction() as conn:  # short transactions: never hold the write lock for the whole run
            _pg_lock(conn, JOB_LOCK)
            for wid in ids[start:start + BATCH]:
                row = conn.execute("SELECT * FROM price_watches WHERE id=? AND active=1", (wid,)).fetchone()
                if row:
                    w = dict(row)
                    _guarded(conn, f"watch {wid}", lambda w=w: _check_watch(conn, w, now, users, stats), stats)
    return stats


def _seller_sms_on(conn, user_id: int) -> bool:
    row = conn.execute("SELECT seller_sms FROM price_alert_user_prefs WHERE user_id=?", (user_id,)).fetchone()
    return True if row is None else bool(row["seller_sms"])


def set_seller_sms(conn, user_id: int, enabled) -> dict:
    if not isinstance(enabled, bool):
        raise ValidationError("sms_enabled نامعتبر است")
    conn.execute("""INSERT INTO price_alert_user_prefs (user_id, seller_sms, updated_at) VALUES (?,?,?)
                    ON CONFLICT (user_id) DO UPDATE SET seller_sms=excluded.seller_sms, updated_at=excluded.updated_at""",
                 (user_id, int(enabled), _stamp(_now())))
    return {"sms_enabled": enabled}


def _check_product(conn, pid: int, now, stats: dict) -> None:
    from app.services.procurement_notify import _supplier_users
    hour, stamp = _hour(now), _stamp(now)
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
    org_ctx = {**cashier._retail_ctx(), "channel": "organization"}  # general organization price, no contract
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
            body = (f"در سطح {SELLER_LEVEL_FA[level]} پیشنهاد دیگری اکنون بهتر از پیشنهاد شماست. "
                    "قیمت، موجودی یا زمان تحویل خود را بررسی کنید.")
            for uid in sorted(_supplier_users(conn, sid)):
                if _event(conn, user_id=uid, product=product, level="seller", alert_type="lost_best_offer",
                          dedupe=f"s{sid}:{pid}:{level}:u{uid}:{hour}", title=title, body=body,
                          sms_text=f"«{sms_safe(product['title_fa'])}» ({SELLER_LEVEL_FA[level]}): {ALERT_FA['lost_best_offer']}",
                          now=now, supplier_id=sid, link="/sell#price-alerts", sms_ok=_seller_sms_on(conn, uid)):
                    stats["alerts"] += 1
    # A seller whose offer dropped out of the eligible set keeps its old state row; it is not "beaten".


def run_sellers(db, now=None, deadline=None) -> dict:
    """Buy-box winner per product at the two public levels; a seller who was the best and no longer is gets one
    alert per transition. Contract (organization-specific) prices are never part of this comparison."""
    now = _now(now)
    stats = {"products": 0, "alerts": 0, "errors": 0, "deferred": 0}
    prov = ",".join(f"'{p}'" for p in se.allowed_provenance())
    with db.read_transaction() as conn:
        pids = [int(r[0]) for r in conn.execute(
            f"""SELECT DISTINCT so.product_id FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                JOIN products p ON p.id=so.product_id
                WHERE so.status='active' AND s.status='active' AND p.is_active=1 AND p.provenance IN ({prov})
                ORDER BY so.product_id""")]
    for start in range(0, len(pids), BATCH):
        if _over(deadline):
            stats["deferred"] += len(pids) - start
            break
        with db.write_transaction() as conn:
            _pg_lock(conn, JOB_LOCK)
            for pid in pids[start:start + BATCH]:
                stats["products"] += 1
                _guarded(conn, f"product {pid}", lambda pid=pid: _check_product(conn, pid, now, stats), stats)
    return stats


def seller_alerts(conn, supplier_id: int, user_id: int | None = None) -> dict:
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
        if k not in seen and len(items) < 50:
            seen.add(k)
            items.append({"product": {"id": r["product_id"], "slug": r["slug"], "title_fa": r["title_fa"]},
                          "text": r["sms_text"], "created_at": r["created_at"]})
    return {"checked": bool(rows), "sms_enabled": _seller_sms_on(conn, user_id) if user_id else True,
            "items": [{"product": {"id": r["product_id"], "slug": r["slug"], "title_fa": r["title_fa"]},
                       "level": r["level"], "level_fa": SELLER_LEVEL_FA[r["level"]], "is_best": bool(r["is_best"]),
                       "own_price_minor": r["own_price_minor"], "updated_at": r["updated_at"]} for r in rows],
            "recent": items}


# ── SMS digests ──────────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def quiet_hours(now) -> bool:
    h = (now + TEHRAN).hour
    return h >= QUIET_FROM or h < QUIET_UNTIL


def _digest_text(lines: list[str]) -> str:
    more = f"\n+{len(lines) - DIGEST_ITEMS} مورد دیگر" if len(lines) > DIGEST_ITEMS else ""
    return "شصت‌آنلاین:\n" + "\n".join(lines[:DIGEST_ITEMS]) + more + "\n60online.ir/me/price-alerts"


def _reserve_digest(conn, uid: int, kind: str, now, sender, stats: dict):
    """Pick this user's pending events of one kind, apply every cap, and reserve one digest row.
    Returns (sms_id, phone, text) to send, or None."""
    hour, day = _hour(now), _day(now)
    run_key = hour if kind == "buyer" else f"{hour}:s"
    seller_kind = "=" if kind == "seller" else "<>"
    pending = conn.execute(f"""SELECT id, product_id, sms_text, created_at FROM price_alert_events
                               WHERE user_id=? AND sms_status='pending' AND level {seller_kind} 'seller' ORDER BY id""",
                           (uid,)).fetchall()
    if not pending:
        return None
    if conn.execute("SELECT 1 FROM price_alert_sms WHERE user_id=? AND run_hour=?", (uid, run_key)).fetchone():
        return None  # this hour's digest already went out; the rest waits for the next run
    cutoff = _stamp(now - _dt.timedelta(hours=PENDING_MAX_HOURS))
    texted_today = {int(r[0]) for r in conn.execute(
        """SELECT DISTINCT e.product_id FROM price_alert_events e JOIN price_alert_sms s ON s.id=e.sms_id
           WHERE e.user_id=? AND s.day=? AND s.kind=? AND s.status IN ('sending','sent')""", (uid, day, kind))}
    take, skip, seen = [], [], set()
    for r in pending:
        pid = int(r["product_id"])
        if r["created_at"] < cutoff or pid in texted_today or pid in seen:
            skip.append(r["id"])  # too old, already texted today, or a second line for the same item
            continue
        seen.add(pid)
        take.append(r)

    def mark(ids, status):
        if ids:
            conn.execute(f"UPDATE price_alert_events SET sms_status=? WHERE id IN ({','.join('?' * len(ids))})", (status, *ids))

    mark(skip, "skipped_item")
    stats["skipped_item"] += len(skip)
    if not take:
        return None
    ids = [r["id"] for r in take]
    phone = conn.execute("SELECT phone_verified FROM users WHERE id=? AND is_active=1", (uid,)).fetchone()
    if not phone or not phone["phone_verified"]:
        mark(ids, "none")
        return None
    if sender is None:
        mark(ids, "unavailable")
        stats["unavailable"] += len(ids)
        return None
    # The per-person limit counts buyer AND seller digests together: one phone, one daily allowance.
    sent_today = conn.execute("SELECT COUNT(*) FROM price_alert_sms WHERE user_id=? AND day=? AND status IN ('sending','sent')",
                              (uid, day)).fetchone()[0]
    text = _digest_text([r["sms_text"] for r in take])
    parts = sms_parts(text)
    cap = _env_int("PRICE_ALERT_DAILY_SMS_PARTS_CAP", 1500) if kind == "buyer" else _env_int("PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP", 500)
    used = conn.execute("SELECT COALESCE(SUM(parts),0) FROM price_alert_sms WHERE day=? AND kind=? AND status IN ('sending','sent')",
                        (day, kind)).fetchone()[0]
    if sent_today >= _env_int("PRICE_ALERT_USER_DAILY_SMS", 2) or int(used) + parts > cap:
        mark(ids, "skipped_cap")
        stats["skipped_cap"] += len(ids)
        return None
    cur = conn.execute("""INSERT INTO price_alert_sms (user_id, run_hour, day, item_count, status, created_at, parts, kind)
                          VALUES (?,?,?,?, 'sending', ?,?,?) ON CONFLICT DO NOTHING""",
                       (uid, run_key, day, len(ids), _stamp(now), parts, kind))
    if not cur.rowcount:
        return None  # an overlapping run reserved it first
    sms_id = int(conn.execute("SELECT id FROM price_alert_sms WHERE user_id=? AND run_hour=?", (uid, run_key)).fetchone()[0])
    conn.execute(f"UPDATE price_alert_events SET sms_status='sent', sms_id=? WHERE id IN ({','.join('?' * len(ids))})", (sms_id, *ids))
    return sms_id, phone["phone_verified"], text


def send_digests(db, sender=None, now=None, deadline=None) -> dict:
    """One digest SMS per user, kind (buyer/seller) and run hour from that user's own pending events (no prices).
    Held during quiet hours (22:00–08:00 Tehran); pending events wait for the first run after 08:00."""
    from app.adapters.sms import ConsoleSms, SmsError, sender_from_env
    now = _now(now)
    stats = {"sent": 0, "failed": 0, "skipped_item": 0, "skipped_cap": 0, "unavailable": 0, "held": 0, "deferred": 0}
    if quiet_hours(now):
        with db.read_transaction() as conn:
            stats["held"] = int(conn.execute("SELECT COUNT(*) FROM price_alert_events WHERE sms_status='pending'").fetchone()[0])
        return stats
    if sender is None:
        try:
            sender = sender_from_env()
        except SmsError:
            sender = None
        if isinstance(sender, ConsoleSms) and (os.environ.get("APP_ENV") or "").lower() == "production":
            sender = None  # never pretend a console "send" is a real SMS in production
    if sender is not None and hasattr(sender, "timeout"):
        sender.timeout = min(float(sender.timeout), SMS_TIMEOUT_S)  # the scheduler is sequential: never block it long
    with db.read_transaction() as conn:
        pairs = [(int(r[0]), "seller" if r[1] else "buyer") for r in conn.execute(
            """SELECT DISTINCT user_id, CASE WHEN level='seller' THEN 1 ELSE 0 END FROM price_alert_events
               WHERE sms_status='pending' ORDER BY 1, 2""")]
    failures = 0
    for i, (uid, kind) in enumerate(pairs):
        if _over(deadline) or failures >= MAX_CONSECUTIVE_FAILURES:
            stats["deferred"] = len(pairs) - i  # left pending for the next run
            break
        with db.write_transaction() as conn:
            reserved = _reserve_digest(conn, uid, kind, now, sender, stats)
        if reserved is None:
            continue
        sms_id, to, text = reserved
        try:  # network call outside the DB transaction; the reservation already blocks a second send this hour
            sender.send_text(to, text)
            ok = True
        except Exception:  # noqa: BLE001 — a provider failure must not stop the job
            log.warning("price alert digest SMS failed for user %s", uid)
            ok = False
        with db.write_transaction() as conn:
            conn.execute("UPDATE price_alert_sms SET status=? WHERE id=?", ("sent" if ok else "failed", sms_id))
            if not ok:
                conn.execute("UPDATE price_alert_events SET sms_status='failed' WHERE sms_id=?", (sms_id,))
        failures = 0 if ok else failures + 1
        stats["sent" if ok else "failed"] += 1
    return stats


def cleanup(conn, now=None) -> dict:
    """Retention: daily history and alert events older than 120 days (charts show 90)."""
    now = _now(now)
    day = (now + TEHRAN - _dt.timedelta(days=RETENTION_DAYS)).date().isoformat()
    stamp = _stamp(now - _dt.timedelta(days=RETENTION_DAYS))
    h = conn.execute("DELETE FROM price_history_daily WHERE day < ?", (day,)).rowcount
    e = conn.execute("DELETE FROM price_alert_events WHERE created_at < ?", (stamp,)).rowcount
    s = conn.execute("DELETE FROM price_alert_sms WHERE day < ?", (day,)).rowcount
    return {"history": h, "events": e, "sms": s}


def run(db, *, now=None, sender=None, budget_s: float | None = None) -> dict:
    now = _now(now)
    budget = _env_int("PRICE_ALERT_JOB_BUDGET_S", JOB_BUDGET_S) if budget_s is None else budget_s
    deadline = time.monotonic() + budget
    watches = run_watches(db, now, deadline)
    sellers = run_sellers(db, now, deadline)
    sms = send_digests(db, sender=sender, now=now, deadline=deadline)
    with db.write_transaction() as conn:
        _pg_lock(conn, JOB_LOCK)
        cleaned = cleanup(conn, now)
    return {"watches": watches, "sellers": sellers, "sms": sms, "cleanup": cleaned}
