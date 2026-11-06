"""Consumer rights required before launch (docs/LEGAL_CHECKLIST.md).

- Statutory withdrawal (E-commerce Law art. 37): the buyer may withdraw within 7 working days
  of delivery without giving a reason. Fridays are not working days; official holidays can be
  added through WITHDRAWAL_HOLIDAYS (comma-separated YYYY-MM-DD). Exempt goods are flagged on
  the product. A withdrawal is approved on filing; the refund is due within REFUND_DUE_DAYS.
- Terms acceptance: every acceptance is stored append-only with document version, text hash,
  IP and user agent, so it can be produced as evidence.
- Escrow: a shop's payable must not become settleable before the withdrawal window closes.

Rules to be confirmed by a licensed lawyer: working-day counting, the exempt categories,
who bears return shipping, and the refund deadline.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError

WITHDRAWAL_WORKING_DAYS = 7
EXEMPT_FA = {"perishable": "کالای فاسدشدنی", "custom_made": "کالای سفارشی و ساخته‌شده برای شما",
             "hygiene": "کالای بهداشتی بازشده", "digital": "کالای دیجیتال تحویل‌شده"}


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse(s: str) -> _dt.datetime:
    s = s.replace("T", " ").replace("Z", "")[:19]
    return _dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)


def refund_due_days() -> int:
    try:
        return max(1, min(int(os.environ.get("REFUND_DUE_DAYS", "7")), 30))
    except ValueError:
        return 7


def _holidays() -> set[str]:
    return {d.strip() for d in os.environ.get("WITHDRAWAL_HOLIDAYS", "").split(",") if d.strip()}


def add_working_days(start: _dt.datetime, days: int) -> _dt.datetime:
    """End of the Nth working day after `start` (Tehran calendar day; Friday off)."""
    tehran = _dt.timezone(_dt.timedelta(hours=3, minutes=30))
    local = start.astimezone(tehran)
    day, counted, holidays = local.date(), 0, _holidays()
    while counted < days:
        day += _dt.timedelta(days=1)
        if day.weekday() != 4 and day.isoformat() not in holidays:  # Monday=0 … Friday=4
            counted += 1
    end_local = _dt.datetime.combine(day, _dt.time(23, 59, 59), tzinfo=tehran)
    return end_local.astimezone(_dt.timezone.utc)


def delivered_at(conn: sqlite3.Connection, order_id: int) -> _dt.datetime | None:
    """Last delivery among the order's seller shipments; None until everything is delivered."""
    rows = conn.execute("SELECT status, delivered_at FROM fulfillment_orders WHERE order_id=? "
                        "AND status NOT IN ('rejected','cancelled','pending_assignment')", (order_id,)).fetchall()
    if not rows or any(r["status"] != "delivered" or not r["delivered_at"] for r in rows):
        return None
    return max(_parse(r["delivered_at"]) for r in rows)


def withdrawal_window(conn: sqlite3.Connection, *, user_id: int, order_number: str,
                      now: _dt.datetime | None = None) -> dict:
    o = conn.execute("SELECT id, status FROM orders WHERE order_number=? AND user_id=?",
                     (order_number, user_id)).fetchone()
    if o is None:
        raise NotFoundError("سفارش یافت نشد")
    t = now or _now()
    d = delivered_at(conn, o["id"])
    deadline = add_working_days(d, WITHDRAWAL_WORKING_DAYS) if d else None
    items = conn.execute(
        "SELECT oi.product_id, oi.title_fa, oi.quantity, p.withdrawal_exempt_reason FROM order_items oi "
        "JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?", (o["id"],)).fetchall()
    return {
        "order_number": order_number, "delivered_at": _iso(d) if d else None,
        "deadline": _iso(deadline) if deadline else None,
        "open": bool(deadline and t <= deadline),
        "working_days": WITHDRAWAL_WORKING_DAYS,
        "items": [{"product_id": r["product_id"], "title_fa": r["title_fa"], "quantity": r["quantity"],
                   "eligible": r["withdrawal_exempt_reason"] is None,
                   "exempt_reason_fa": EXEMPT_FA.get(r["withdrawal_exempt_reason"])} for r in items],
        "notice_fa": f"می‌توانید تا {WITHDRAWAL_WORKING_DAYS} روز کاری بعد از تحویل، بدون ذکر دلیل از خرید انصراف دهید. "
                     "هزینهٔ بازگرداندن کالا با خریدار است و مبلغ حداکثر ظرف "
                     f"{refund_due_days()} روز پس از ثبت انصراف برمی‌گردد.",
    }


def request_withdrawal(conn: sqlite3.Connection, *, user_id: int, order_number: str, data: dict,
                       now: _dt.datetime | None = None) -> dict:
    t = now or _now()
    w = withdrawal_window(conn, user_id=user_id, order_number=order_number, now=t)
    if w["delivered_at"] is None:
        raise ConflictError("انصراف بعد از تحویل کامل سفارش ممکن است؛ قبل از آن سفارش را لغو کنید",
                            code="not_delivered")
    if not w["open"]:
        raise ConflictError("مهلت ۷ روز کاری انصراف تمام شده است؛ برای کالای معیوب درخواست مرجوعی ثبت کنید",
                            code="withdrawal_window_closed")
    o = conn.execute("SELECT id FROM orders WHERE order_number=? AND user_id=?", (order_number, user_id)).fetchone()
    if conn.execute("SELECT 1 FROM order_return_requests WHERE order_id=? AND status IN "
                    "('requested','approved','received','refund_pending')", (o["id"],)).fetchone():
        raise ConflictError("برای این سفارش یک درخواست باز وجود دارد", code="return_open")
    eligible = {i["product_id"]: i for i in w["items"]}
    already: dict = {}
    for r in conn.execute("SELECT items_json FROM order_return_requests WHERE order_id=? "
                          "AND status NOT IN ('rejected','cancelled')", (o["id"],)):
        for it in json.loads(r["items_json"]):
            already[it["product_id"]] = already.get(it["product_id"], 0) + it["quantity"]
    raw = data.get("items")
    if raw is None:  # whole order by default
        raw = [{"product_id": i["product_id"], "quantity": i["quantity"] - already.get(i["product_id"], 0)}
               for i in w["items"] if i["eligible"] and i["quantity"] - already.get(i["product_id"], 0) > 0]
    if not isinstance(raw, list) or not raw:
        raise ValidationError("حداقل یک کالای قابل انصراف انتخاب کنید")
    items = []
    for it in raw:
        pid, qty = (it or {}).get("product_id"), (it or {}).get("quantity")
        if pid not in eligible or type(qty) is not int or qty < 1:
            raise ValidationError("قلم انصراف نامعتبر است")
        if not eligible[pid]["eligible"]:
            raise ConflictError(f"«{eligible[pid]['title_fa']}» {eligible[pid]['exempt_reason_fa']} است و انصراف ندارد",
                                code="withdrawal_exempt")
        if qty > eligible[pid]["quantity"] - already.get(pid, 0):
            raise ValidationError("تعداد انصراف از تعداد خریداری‌شده بیشتر است")
        items.append({"product_id": pid, "title_fa": eligible[pid]["title_fa"], "quantity": qty})
    reason = data.get("reason")
    reason = reason.strip()[:2000] if isinstance(reason, str) and len(reason.strip()) >= 3 else "انصراف قانونی بدون ذکر دلیل"
    due = _iso(t + _dt.timedelta(days=refund_due_days()))
    rid = conn.execute(
        "INSERT INTO order_return_requests (order_id, user_id, items_json, reason, status, kind, refund_due_at) "
        "VALUES (?,?,?,?, 'approved', 'withdrawal', ?)",
        (o["id"], user_id, json.dumps(items, ensure_ascii=False), reason, due)).lastrowid
    conn.execute("INSERT INTO order_return_events (return_id, actor_user_id, status, note) VALUES (?,?,?,?)",
                 (rid, user_id, "approved", "انصراف قانونی ثبت و خودکار پذیرفته شد"))
    from app.services import commerce_ops_service
    view = commerce_ops_service._return_view(
        conn, conn.execute("SELECT * FROM order_return_requests WHERE id=?", (rid,)).fetchone())
    view["kind"], view["refund_due_at"] = "withdrawal", due
    return view


def escrow_floor(conn: sqlite3.Connection, fulfillment_order_id: int) -> _dt.datetime | None:
    """Earliest moment a shop payable may settle: after the buyer's withdrawal window."""
    row = conn.execute("SELECT delivered_at FROM fulfillment_orders WHERE id=?", (fulfillment_order_id,)).fetchone()
    base = _parse(row["delivered_at"]) if row and row["delivered_at"] else _now()
    return add_working_days(base, WITHDRAWAL_WORKING_DAYS)


# ── terms acceptance ──────────────────────────────────────────────────────────

def current_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT d.* FROM legal_documents d WHERE d.id = (SELECT MAX(id) FROM legal_documents x WHERE x.doc_key=d.doc_key) "
        "ORDER BY d.doc_key").fetchall()
    return [{"doc_key": r["doc_key"], "version": r["version"], "sha256": r["text_sha256"], "url": r["url"],
             "effective_from": r["effective_from"]} for r in rows]


def record_acceptance(conn: sqlite3.Connection, *, user_id: int, doc_key: str, version: str, context: str,
                      context_ref: str | None = None, ip: str | None = None, user_agent: str | None = None) -> dict:
    doc = conn.execute("SELECT id, version FROM legal_documents WHERE doc_key=? AND id=(SELECT MAX(id) FROM "
                       "legal_documents WHERE doc_key=?)", (doc_key, doc_key)).fetchone()
    if doc is None:
        raise NotFoundError("متن قانونی یافت نشد")
    if version != doc["version"]:
        raise ConflictError("نسخهٔ شرایط تغییر کرده است؛ صفحه را تازه کنید و نسخهٔ جدید را بپذیرید",
                            code="terms_version_outdated", details={"current_version": doc["version"]})
    cur = conn.execute(
        "INSERT INTO terms_acceptances (user_id, document_id, context, context_ref, ip_address, user_agent) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, doc["id"], context, (context_ref or "")[:200] or None, (ip or "")[:64] or None,
         (user_agent or "")[:300] or None))
    return {"id": cur.lastrowid, "doc_key": doc_key, "version": version, "context": context}


def has_accepted_current(conn: sqlite3.Connection, *, user_id: int, doc_key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM terms_acceptances a WHERE a.user_id=? AND a.document_id=(SELECT MAX(id) FROM legal_documents "
        "WHERE doc_key=?)", (user_id, doc_key)).fetchone() is not None


# ── VAT-inclusive display ─────────────────────────────────────────────────────

def standard_vat_bps(conn: sqlite3.Connection) -> int:
    from app.services import tax_service
    try:
        return int(tax_service.get_rate_bps_with_conn(conn, "STANDARD",
                                                      effective_date=_now().strftime("%Y-%m-%d")))
    except Exception:  # no rate configured → show the net price rather than a wrong gross
        return 0


def gross(net_minor: int | None, vat_bps: int) -> int | None:
    return None if net_minor is None else net_minor + net_minor * vat_bps // 10000
