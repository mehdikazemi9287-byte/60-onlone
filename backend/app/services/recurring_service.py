"""Phase 2 — recurring delivery lists (Subscribe & Save) for restaurants and offices.

A list holds products + quantities and a schedule (weekly / biweekly / monthly). When due, the
list is priced through the cashier with the recurring discount rule; the result is stored as a
`recurring_runs` row with status 'quoted' — a draft for the buyer to confirm. Nothing here
reserves stock or charges money.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import json

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import cashier_service as cashier

FREQUENCIES = ("weekly", "biweekly", "monthly")
MAX_ITEMS = 100


def _today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def next_date(day: _dt.date, frequency: str) -> _dt.date:
    if frequency == "weekly":
        return day + _dt.timedelta(days=7)
    if frequency == "biweekly":
        return day + _dt.timedelta(days=14)
    y, m = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return _dt.date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def _items(conn, raw) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError("فهرست دوره‌ای حداقل یک کالا لازم دارد")
    if len(raw) > MAX_ITEMS:
        raise ValidationError("تعداد اقلام فهرست دوره‌ای بیش از حد مجاز است")
    out, seen = [], set()
    for it in raw:
        if not isinstance(it, dict):
            raise ValidationError("قلم فهرست نامعتبر است")
        pid, q, oid = it.get("product_id"), it.get("quantity", 1), it.get("offer_id")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
            raise ValidationError("شناسهٔ کالا نامعتبر است")
        if isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= 100_000:
            raise ValidationError("تعداد کالا نامعتبر است")
        if pid in seen:
            raise ValidationError("هر کالا فقط یک بار در فهرست می‌آید")
        seen.add(pid)
        if not conn.execute("SELECT 1 FROM products WHERE id=? AND is_active=1", (pid,)).fetchone():
            raise NotFoundError("کالا یافت نشد", details={"product_id": pid})
        if oid is not None:
            if isinstance(oid, bool) or not isinstance(oid, int) \
                    or not conn.execute("SELECT 1 FROM seller_offers WHERE id=? AND product_id=?", (oid, pid)).fetchone():
                raise ValidationError("پیشنهاد فروشنده با کالا هم‌خوان نیست", details={"product_id": pid})
        out.append({"product_id": pid, "quantity": q, "offer_id": oid})
    return out


def create(conn, *, user_id: int, data: dict) -> dict:
    allowed = {"title", "frequency", "start_on", "organization_id", "items"}
    extra = set(data) - allowed
    if extra:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(extra)})
    title = data.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValidationError("عنوان فهرست الزامی است")
    freq = data.get("frequency")
    if freq not in FREQUENCIES:
        raise ValidationError("دورهٔ ارسال باید هفتگی، دوهفته‌یکبار یا ماهانه باشد")
    start = data.get("start_on")
    try:
        start = _dt.date.fromisoformat(start) if start is not None else _today()
    except (TypeError, ValueError):
        raise ValidationError("تاریخ شروع نامعتبر است")
    if start < _today():
        raise ValidationError("تاریخ شروع نمی‌تواند گذشته باشد")
    org = data.get("organization_id")
    if org is not None:
        # Validates active membership of an active organization.
        cashier.buyer_context(conn, user_id=user_id, organization_id=org, use_credit=False)
    items = _items(conn, data.get("items"))
    lid = int(conn.execute(
        "INSERT INTO recurring_lists (user_id, organization_id, title, frequency, next_run_on) VALUES (?,?,?,?,?)",
        (user_id, org, title.strip(), freq, start.isoformat())).lastrowid)
    for it in items:
        conn.execute("INSERT INTO recurring_list_items (list_id, product_id, offer_id, quantity) VALUES (?,?,?,?)",
                     (lid, it["product_id"], it["offer_id"], it["quantity"]))
    return get(conn, user_id=user_id, list_id=lid)


def _row(conn, user_id: int, list_id: int):
    row = conn.execute("SELECT * FROM recurring_lists WHERE id=? AND user_id=?", (list_id, user_id)).fetchone()
    if row is None:
        raise NotFoundError("فهرست دوره‌ای یافت نشد")
    return row


def _dict(conn, row) -> dict:
    d = dict(row)
    d["items"] = [dict(r) for r in conn.execute(
        """SELECT i.product_id, i.offer_id, i.quantity, p.slug, p.title_fa FROM recurring_list_items i
           JOIN products p ON p.id=i.product_id WHERE i.list_id=? ORDER BY i.id""", (row["id"],))]
    return d


def get(conn, *, user_id: int, list_id: int) -> dict:
    return _dict(conn, _row(conn, user_id, list_id))


def list_mine(conn, *, user_id: int) -> list[dict]:
    return [_dict(conn, r) for r in conn.execute(
        "SELECT * FROM recurring_lists WHERE user_id=? AND status<>'cancelled' ORDER BY id DESC", (user_id,))]


def set_status(conn, *, user_id: int, list_id: int, action: str) -> dict:
    row = _row(conn, user_id, list_id)
    target = {"pause": "paused", "resume": "active", "cancel": "cancelled"}.get(action)
    if target is None:
        raise ValidationError("عملیات نامعتبر است")
    if row["status"] == "cancelled":
        raise ConflictError("فهرست لغوشده قابل تغییر نیست", code="recurring_cancelled")
    next_on = row["next_run_on"]
    if target == "active" and next_on < _today().isoformat():
        next_on = _today().isoformat()  # resuming never back-fills missed deliveries
    conn.execute("UPDATE recurring_lists SET status=?, next_run_on=?, updated_at=? WHERE id=?",
                 (target, next_on, _stamp(), list_id))
    return get(conn, user_id=user_id, list_id=list_id)


def quote_list(conn, row, *, now: _dt.datetime | None = None) -> dict:
    items = [{"product_id": int(i["product_id"]), "offer_id": i["offer_id"], "quantity": int(i["quantity"])}
             for i in conn.execute("SELECT product_id, offer_id, quantity FROM recurring_list_items WHERE list_id=? "
                                   "ORDER BY id", (row["id"],))]
    ctx = cashier.buyer_context(conn, user_id=int(row["user_id"]), organization_id=row["organization_id"],
                                recurring=True)
    return cashier.quote(conn, items, ctx, now=now)


def preview(conn, *, user_id: int, list_id: int) -> dict:
    return quote_list(conn, _row(conn, user_id, list_id))


def run_due(conn, *, today: _dt.date | None = None, now: _dt.datetime | None = None, limit: int = 200) -> dict:
    """Quote every active list due on or before `today`; one run per scheduled date (idempotent).
    Advances next_run_on past today; missed periods are skipped, not back-filled."""
    today = today or _today()
    done = {"quoted": 0, "failed": 0, "runs": []}
    rows = conn.execute("SELECT * FROM recurring_lists WHERE status='active' AND next_run_on<=? ORDER BY id LIMIT ?",
                        (today.isoformat(), limit)).fetchall()
    for row in rows:
        scheduled = row["next_run_on"]
        if not conn.execute("SELECT 1 FROM recurring_runs WHERE list_id=? AND scheduled_for=?",
                            (row["id"], scheduled)).fetchone():
            status, payable, body, error = "quoted", None, None, None
            try:
                q = quote_list(conn, row, now=now)
                if not q["lines"]:
                    status, error = "failed", "هیچ‌یک از اقلام فهرست فعلاً قابل فروش نیست"
                payable = q["totals"]["payable_minor"]
                body = json.dumps(q, ensure_ascii=False, default=str)
            except (ValidationError, NotFoundError, ConflictError) as exc:
                status, error = "failed", exc.message
            except Exception as exc:  # noqa: BLE001 - permission errors etc. must not stop other lists
                status, error = "failed", getattr(exc, "message", "خطا در محاسبهٔ پیش‌فاکتور")
            run_id = int(conn.execute(
                "INSERT INTO recurring_runs (list_id, scheduled_for, status, payable_minor, quote_json, error) "
                "VALUES (?,?,?,?,?,?)", (row["id"], scheduled, status, payable, body, error)).lastrowid)
            done[status] += 1
            done["runs"].append({"run_id": run_id, "list_id": int(row["id"]), "status": status,
                                 "scheduled_for": scheduled, "payable_minor": payable})
        nxt = _dt.date.fromisoformat(scheduled)
        while nxt <= today:
            nxt = next_date(nxt, row["frequency"])
        conn.execute("UPDATE recurring_lists SET next_run_on=?, last_run_on=?, updated_at=? WHERE id=?",
                     (nxt.isoformat(), scheduled, _stamp(), row["id"]))
    return done


def list_runs(conn, *, user_id: int, list_id: int) -> list[dict]:
    _row(conn, user_id, list_id)
    out = []
    for r in conn.execute("SELECT * FROM recurring_runs WHERE list_id=? ORDER BY id DESC LIMIT 50", (list_id,)):
        d = dict(r)
        d["quote"] = json.loads(d.pop("quote_json")) if d.get("quote_json") else None
        out.append(d)
    return out
