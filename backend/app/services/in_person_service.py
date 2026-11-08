"""In-person (مراجعهٔ حضوری): store locator, collect-in-store with a one-time code, visit appointments.

Pickup flow: the buyer switches a not-yet-dispatched seller part of the order to pickup at one of the
seller's pickup locations and receives a 6-digit code (shown once; only its hash is stored). At the
counter the seller enters the code; that marks the part delivered through the existing
fulfillment transition, so stock, escrow and the withdrawal window start exactly as for a delivery.
Shipping already paid for that part is not refunded automatically (ops decision, see ROADMAP).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import re
import secrets
import sqlite3

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError

PICKUP_DAYS = 7
MAX_CODE_ATTEMPTS = 5
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?Z?$")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _location_view(r) -> dict:
    return {"id": r["id"], "title": r["public_title"] or r["shop_title"] or r["display_name"],
            "shop_slug": r["shop_slug"], "province": r["province"], "city": r["city"], "district": r["district"],
            "address": r["address"], "latitude": r["latitude"], "longitude": r["longitude"],
            "phone": r["public_phone"], "opening_hours": r["operating_hours_json"],
            "pickup": bool(r["can_pickup"]), "walk_in": bool(r["accepts_walk_in"]),
            "appointments": bool(r["accepts_appointments"])}


def store_locator(conn: sqlite3.Connection, *, city: str | None = None, province: str | None = None,
                  supplier_id: int | None = None) -> list[dict]:
    where = ["l.status='active'", "s.status='active'", "s.provenance='real'",
             "(l.can_pickup=1 OR l.accepts_walk_in=1 OR l.accepts_appointments=1)"]
    args: list = []
    for col, val in (("l.city", city), ("l.province", province)):
        if val:
            where.append(f"{col}=?")
            args.append(val.strip()[:100])
    if supplier_id is not None:
        where.append("s.id=?")
        args.append(int(supplier_id))
    rows = conn.execute(
        "SELECT l.*, s.shop_title, s.display_name, s.shop_slug FROM supplier_locations l JOIN suppliers s ON s.id=l.supplier_id "
        f"WHERE {' AND '.join(where)} ORDER BY l.province, l.city, l.id LIMIT 300", args).fetchall()
    return [_location_view(r) for r in rows]


def pickup_locations(conn: sqlite3.Connection, *, user_id: int, fulfillment_order_id: int) -> dict:
    fo = conn.execute("SELECT fo.supplier_id, fo.status, o.user_id FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
                      "WHERE fo.id=?", (fulfillment_order_id,)).fetchone()
    if fo is None or fo["user_id"] != user_id:
        raise NotFoundError("سفارش یافت نشد")
    chosen = conn.execute("SELECT location_id, status, code_last2, expires_at FROM pickup_handoffs WHERE fulfillment_order_id=?",
                          (fulfillment_order_id,)).fetchone()
    return {"eligible": fo["status"] in ("assigned", "accepted", "preparing", "ready") and not chosen,
            "locations": [l for l in store_locator(conn, supplier_id=fo["supplier_id"]) if l["pickup"]],
            "chosen": dict(chosen) if chosen else None}


def choose_pickup(conn: sqlite3.Connection, *, user_id: int, fulfillment_order_id: int, location_id: int,
                  now: _dt.datetime | None = None) -> dict:
    fo = conn.execute("SELECT fo.*, o.user_id FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
                      "WHERE fo.id=?", (fulfillment_order_id,)).fetchone()
    if fo is None or fo["user_id"] != user_id:
        raise NotFoundError("سفارش یافت نشد")
    if fo["status"] not in ("assigned", "accepted", "preparing", "ready"):
        raise ConflictError("این بخش از سفارش دیگر قابل تبدیل به دریافت حضوری نیست", code="pickup_too_late")
    loc = conn.execute("SELECT * FROM supplier_locations WHERE id=? AND supplier_id=? AND status='active' AND can_pickup=1",
                       (location_id, fo["supplier_id"])).fetchone()
    if loc is None:
        raise ValidationError("این فروشگاه دریافت حضوری ندارد")
    if conn.execute("SELECT 1 FROM pickup_handoffs WHERE fulfillment_order_id=? AND status='waiting'",
                    (fulfillment_order_id,)).fetchone():
        raise ConflictError("دریافت حضوری قبلاً ثبت شده است", code="pickup_exists")
    code = f"{secrets.randbelow(1_000_000):06d}"
    t = now or _now()
    conn.execute("DELETE FROM pickup_handoffs WHERE fulfillment_order_id=? AND status='cancelled'", (fulfillment_order_id,))
    conn.execute(
        "INSERT INTO pickup_handoffs (fulfillment_order_id, location_id, code_sha256, code_last2, expires_at) VALUES (?,?,?,?,?)",
        (fulfillment_order_id, location_id, _hash(code), code[-2:], _iso(t + _dt.timedelta(days=PICKUP_DAYS))))
    conn.execute("UPDATE fulfillment_orders SET fulfillment_type='pickup', supplier_location_id=?, updated_at=datetime('now') "
                 "WHERE id=?", (location_id, fulfillment_order_id))
    return {"fulfillment_order_id": fulfillment_order_id, "location": _location_view(conn.execute(
        "SELECT l.*, s.shop_title, s.display_name, s.shop_slug FROM supplier_locations l JOIN suppliers s ON s.id=l.supplier_id "
        "WHERE l.id=?", (location_id,)).fetchone()), "pickup_code": code,
            "expires_at": _iso(t + _dt.timedelta(days=PICKUP_DAYS)),
            "notice_fa": "این کد را فقط هنگام تحویل کالا به فروشنده بگو. کد یک‌بار نمایش داده می‌شود."}


def confirm_pickup(conn: sqlite3.Connection, *, supplier_id: int, actor_user_id: int, fulfillment_order_id: int,
                   code: str, now: _dt.datetime | None = None) -> dict:
    h = conn.execute("SELECT h.*, fo.supplier_id, fo.status AS fo_status FROM pickup_handoffs h "
                     "JOIN fulfillment_orders fo ON fo.id=h.fulfillment_order_id WHERE h.fulfillment_order_id=?",
                     (fulfillment_order_id,)).fetchone()
    if h is None or h["supplier_id"] != supplier_id:
        raise NotFoundError("دریافت حضوری یافت نشد")
    if h["status"] != "waiting":
        raise ConflictError("این کالا قبلاً تحویل شده یا لغو شده است", code="pickup_closed")
    t = now or _now()
    if _iso(t) > h["expires_at"]:
        raise ConflictError("مهلت دریافت حضوری تمام شده است", code="pickup_expired")
    if h["attempts"] >= MAX_CODE_ATTEMPTS:
        raise ConflictError("تعداد تلاش برای کد بیش از حد مجاز است؛ با پشتیبانی تماس بگیرید", code="pickup_locked")
    if not isinstance(code, str) or not hmac.compare_digest(_hash(code.strip()), h["code_sha256"]):
        conn.execute("UPDATE pickup_handoffs SET attempts=attempts+1 WHERE id=?", (h["id"],))
        raise ValidationError("کد تحویل درست نیست", code="pickup_code_wrong")
    if h["fo_status"] != "ready":
        raise ConflictError("کالا هنوز «آماده تحویل» نشده است", code="pickup_not_ready")
    from app.services import fulfillment_service
    fulfillment_service.supplier_mark_delivered(conn, fulfillment_order_id=fulfillment_order_id,
                                                supplier_id=supplier_id, actor_user_id=actor_user_id)
    conn.execute("UPDATE pickup_handoffs SET status='collected', collected_at=?, collected_by_user_id=? WHERE id=?",
                 (_iso(t), actor_user_id, h["id"]))
    return {"fulfillment_order_id": fulfillment_order_id, "status": "collected"}


def book_visit(conn: sqlite3.Connection, *, user_id: int, data: dict, now: _dt.datetime | None = None) -> dict:
    loc_id, starts, purpose = data.get("location_id"), data.get("starts_at"), data.get("purpose", "showroom")
    if type(loc_id) is not int or not isinstance(starts, str) or not _ISO.match(starts):
        raise ValidationError("مکان و زمان مراجعه را درست وارد کنید")
    if purpose not in ("showroom", "consultation", "samples", "pickup", "other"):
        raise ValidationError("هدف مراجعه نامعتبر است")
    loc = conn.execute("SELECT * FROM supplier_locations WHERE id=? AND status='active' AND accepts_appointments=1",
                       (loc_id,)).fetchone()
    if loc is None:
        raise ValidationError("این فروشگاه نوبت مراجعه نمی‌دهد")
    t = now or _now()
    start = _dt.datetime.fromisoformat(starts.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=_dt.timezone.utc)
    if not t + _dt.timedelta(hours=1) <= start <= t + _dt.timedelta(days=60):
        raise ValidationError("زمان مراجعه باید از یک ساعت بعد تا ۶۰ روز آینده باشد")
    duration = data.get("duration_min", 30)
    if type(duration) is not int or not 15 <= duration <= 180:
        raise ValidationError("مدت مراجعه نامعتبر است")
    stamp = _iso(start)
    end = _iso(start + _dt.timedelta(minutes=duration))
    clash = conn.execute(
        "SELECT 1 FROM visit_appointments WHERE location_id=? AND status IN ('requested','confirmed') "
        "AND starts_at < ? AND strftime('%Y-%m-%dT%H:%M:%S.000Z', datetime(starts_at, '+' || duration_min || ' minutes')) > ?",
        (loc_id, end, stamp)).fetchone()
    if clash:
        raise ConflictError("این زمان قبلاً رزرو شده است؛ زمان دیگری انتخاب کنید", code="slot_taken")
    org = data.get("organization_id")
    if org is not None and not conn.execute("SELECT 1 FROM organization_memberships WHERE organization_id=? AND user_id=? "
                                            "AND status='active'", (org, user_id)).fetchone():
        raise PermissionError_("عضو این سازمان نیستید")
    cur = conn.execute(
        "INSERT INTO visit_appointments (user_id, location_id, starts_at, duration_min, purpose, note, organization_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_id, loc_id, stamp, duration, purpose, (data.get("note") or "")[:500] or None, org))
    return dict(conn.execute("SELECT * FROM visit_appointments WHERE id=?", (cur.lastrowid,)).fetchone())


def my_visits(conn: sqlite3.Connection, *, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM visit_appointments WHERE user_id=? ORDER BY starts_at DESC LIMIT 100",
                                          (user_id,))]


def cancel_visit(conn: sqlite3.Connection, *, user_id: int, visit_id: int) -> dict:
    r = conn.execute("SELECT * FROM visit_appointments WHERE id=? AND user_id=?", (visit_id, user_id)).fetchone()
    if r is None:
        raise NotFoundError("نوبت یافت نشد")
    if r["status"] not in ("requested", "confirmed"):
        raise ConflictError("این نوبت قابل لغو نیست", code="visit_closed")
    conn.execute("UPDATE visit_appointments SET status='cancelled', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                 (visit_id,))
    return dict(conn.execute("SELECT * FROM visit_appointments WHERE id=?", (visit_id,)).fetchone())


def seller_visits(conn: sqlite3.Connection, *, supplier_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT v.id, v.starts_at, v.duration_min, v.purpose, v.note, v.status, v.location_id, u.full_name "
        "FROM visit_appointments v JOIN supplier_locations l ON l.id=v.location_id JOIN users u ON u.id=v.user_id "
        "WHERE l.supplier_id=? ORDER BY v.starts_at DESC LIMIT 200", (supplier_id,)).fetchall()
    return [dict(r) for r in rows]  # visitor name only; no phone/email to the seller


def seller_decide_visit(conn: sqlite3.Connection, *, supplier_id: int, visit_id: int, decision: str) -> dict:
    r = conn.execute("SELECT v.* FROM visit_appointments v JOIN supplier_locations l ON l.id=v.location_id "
                     "WHERE v.id=? AND l.supplier_id=?", (visit_id, supplier_id)).fetchone()
    if r is None:
        raise NotFoundError("نوبت یافت نشد")
    moves = {"confirm": ("requested", "confirmed"), "decline": ("requested", "declined"), "done": ("confirmed", "done")}
    if decision not in moves or r["status"] != moves[decision][0]:
        raise ConflictError("این تغییر وضعیت مجاز نیست", code="invalid_transition")
    conn.execute("UPDATE visit_appointments SET status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                 (moves[decision][1], visit_id))
    return dict(conn.execute("SELECT * FROM visit_appointments WHERE id=?", (visit_id,)).fetchone())
