"""Phase 4 — installments (اقساط) and debt sales (خرید دین).

Records obligations only; no money moves. Math (integer Rial):
    down      = principal * down_payment_bps // 10000          (seq 0, due at creation)
    financed  = principal - down
    fee_total = financed * fee_bps * months // 10000            (fee per installment = fee_bps of financed)
    installment k (1..months): principal financed//months, fee fee_total//months,
    the remainders of both land on the LAST installment, so the schedule sums exactly.
Due dates are every 30 days from creation (Jalali months are 29–31 days).

Debt sale: the seller holding the receivable sells the unpaid remainder to the platform:
    discount = remaining * discount_bps // 10000, price = remaining - discount
    GL: Dr 1030 remaining / Cr 2030 price / Cr 2035 discount (unearned until collected).
"""
from __future__ import annotations

import json

import secrets
from datetime import datetime, timedelta

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import audit_service, ledger_service
from app.services.credit_contract_service import _int, _utc, fmt, parse_ts
from app.services.ledger_service import Entry

INSTALLMENT_DAYS = 30
ACCOUNT_PURCHASED_RECEIVABLES = "1030"
ACCOUNT_DEBT_PURCHASE_PAYABLE = "2030"
ACCOUNT_UNEARNED_DISCOUNT = "2035"


def _ref(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


def list_plans(conn, active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM installment_plans" + (" WHERE status = 'active'" if active_only else "") + " ORDER BY months"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def create_plan(conn, payload: dict) -> dict:
    months = _int(payload.get("months"), "months", minimum=3, maximum=18)
    if months not in (3, 6, 12, 18):
        raise ValidationError("تعداد اقساط باید ۳، ۶، ۱۲ یا ۱۸ باشد", details={"months": [3, 6, 12, 18]})
    code = (payload.get("code") or "").strip()
    if not code:
        raise ValidationError("کد طرح لازم است", details={"code": "لازم"})
    if conn.execute("SELECT 1 FROM installment_plans WHERE code = ?", (code,)).fetchone():
        raise ConflictError("این کد طرح قبلاً ثبت شده است", code="installment_plan_exists")
    cursor = conn.execute(
        "INSERT INTO installment_plans (code, title_fa, months, fee_bps, down_payment_bps, late_grace_days) "
        "VALUES (?,?,?,?,?,?)",
        (code, payload.get("title_fa") or code, months,
         _int(payload.get("fee_bps", 300), "fee_bps", minimum=0, maximum=2000),
         _int(payload.get("down_payment_bps", 0), "down_payment_bps", minimum=0, maximum=9000),
         _int(payload.get("late_grace_days", 3), "late_grace_days", minimum=0, maximum=60)),
    )
    return dict(conn.execute("SELECT * FROM installment_plans WHERE id = ?", (int(cursor.lastrowid),)).fetchone())


def _plan(conn, plan_id: int):
    row = conn.execute("SELECT * FROM installment_plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None or row["status"] != "active":
        raise NotFoundError("طرح اقساط یافت نشد", code="installment_plan_not_found")
    return row


def build_schedule(principal_minor: int, months: int, fee_bps: int, down_payment_bps: int,
                   start: datetime | None = None) -> dict:
    """Pure schedule math; the sum of `rows` equals total_payable_minor exactly."""
    principal_minor = _int(principal_minor, "principal_minor")
    start = _utc(start)
    down = principal_minor * down_payment_bps // 10_000
    financed = principal_minor - down
    fee_total = financed * fee_bps * months // 10_000
    base_p, base_f = financed // months, fee_total // months
    rows = []
    if down > 0:
        rows.append({"seq": 0, "due_at": fmt(start), "principal_minor": down, "fee_minor": 0, "amount_minor": down})
    for k in range(1, months + 1):
        p = base_p + (financed - base_p * months if k == months else 0)
        f = base_f + (fee_total - base_f * months if k == months else 0)
        if p + f > 0:
            rows.append({"seq": k, "due_at": fmt(start + timedelta(days=INSTALLMENT_DAYS * k)),
                         "principal_minor": p, "fee_minor": f, "amount_minor": p + f})
    return {"principal_minor": principal_minor, "down_payment_minor": down, "financed_minor": financed,
            "fee_total_minor": fee_total, "total_payable_minor": principal_minor + fee_total,
            "months": months, "fee_bps": fee_bps, "down_payment_bps": down_payment_bps, "rows": rows}


def quote(conn, *, plan_id: int, principal_minor: int, now: datetime | None = None) -> dict:
    plan = _plan(conn, plan_id)
    return build_schedule(principal_minor, int(plan["months"]), int(plan["fee_bps"]),
                          int(plan["down_payment_bps"]), now)


def _agreement_row(conn, agreement_id: int):
    row = conn.execute("SELECT * FROM installment_agreements WHERE id = ?", (agreement_id,)).fetchone()
    if row is None:
        raise NotFoundError("قرارداد اقساط یافت نشد", code="installment_not_found")
    return row


def _paid_on(conn, schedule_id: int) -> int:
    row = conn.execute("SELECT COALESCE(SUM(amount_minor),0) AS n FROM installment_payments WHERE schedule_id = ?",
                       (schedule_id,)).fetchone()
    return int(row["n"])


def agreement_dict(conn, row) -> dict:
    data = {k: row[k] for k in row.keys()}
    data.pop("idempotency_key", None)
    schedules = []
    for s in conn.execute("SELECT * FROM installment_schedules WHERE agreement_id = ? ORDER BY seq",
                          (int(row["id"]),)).fetchall():
        item = dict(s)
        item["paid_minor"] = _paid_on(conn, int(s["id"]))
        schedules.append(item)
    data["schedules"] = schedules
    data["remaining_minor"] = remaining_minor(conn, int(row["id"]))
    sale = conn.execute("SELECT * FROM debt_sales WHERE agreement_id = ?", (int(row["id"]),)).fetchone()
    data["debt_sale"] = dict(sale) if sale else None
    return data


SELLER_VISIBLE_FIELDS = ("id", "reference", "order_id", "supplier_id", "months", "principal_minor",
                         "down_payment_minor", "financed_minor", "fee_total_minor", "total_payable_minor",
                         "creditor_kind", "status", "created_at", "updated_at", "schedules", "remaining_minor")


def get_agreement(conn, agreement_id: int, *, user: dict | None = None, supplier_id: int | None = None) -> dict:
    row = _agreement_row(conn, agreement_id)
    if user is None or user["role"] == "admin" or int(row["user_id"]) == user["id"]:
        return agreement_dict(conn, row)
    if supplier_id is None or row["supplier_id"] is None or int(row["supplier_id"]) != supplier_id:
        raise NotFoundError("قرارداد اقساط یافت نشد", code="installment_not_found")
    # Seller (creditor) view: repayment progress only — no buyer identity/contact, no debt-sale terms.
    data = agreement_dict(conn, row)
    return {k: data[k] for k in SELLER_VISIBLE_FIELDS if k in data}


def _order_suppliers(conn, order_id: int) -> set[int]:
    """Sellers of an order, from its own fulfillment orders / stored fulfillment plan (never the request)."""
    found = {int(r[0]) for r in conn.execute("SELECT DISTINCT supplier_id FROM fulfillment_orders WHERE order_id = ?",
                                             (order_id,)).fetchall()}
    plans = [r[0] for r in conn.execute("SELECT fulfillment_plan_json FROM order_sources WHERE order_id = ?",
                                        (order_id,)).fetchall()]
    plans += [r[0] for r in conn.execute("SELECT fulfillment_plan_json FROM payment_intents WHERE order_id = ?",
                                         (order_id,)).fetchall()]
    for raw in plans:
        try:
            items = (json.loads(raw) or {}).get("items", []) if raw else []
        except (TypeError, ValueError):
            items = []
        found |= {int(i["supplier_id"]) for i in items if isinstance(i, dict) and i.get("supplier_id") is not None}
    return found


def list_for_user(conn, user_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM installment_agreements WHERE user_id = ? ORDER BY id DESC",
                        (user_id,)).fetchall()
    return [agreement_dict(conn, r) for r in rows]


def create_agreement(conn, *, order_id: int, plan_id: int, actor: dict, idempotency_key: str,
                     supplier_id: int | None = None, now: datetime | None = None) -> tuple[bool, dict]:
    """Put an order on installments. Principal = order total. Idempotent.

    The creditor (supplier_id) is derived from the order's own lines; the `supplier_id` argument is
    accepted only for backward compatibility and must match it if given. One seller per contract:
    multi-seller orders are refused.
    """
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    order = conn.execute("SELECT id, user_id, status, total_minor, payment_intent_id FROM orders WHERE id = ?",
                         (order_id,)).fetchone()
    if order is None or (actor["role"] != "admin" and int(order["user_id"]) != actor["id"]):
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    existing = conn.execute("SELECT * FROM installment_agreements WHERE idempotency_key = ?",
                            (idempotency_key,)).fetchone()
    if existing is not None:
        if actor["role"] != "admin" and int(existing["user_id"]) != actor["id"]:
            raise ConflictError("کلید یکتایی با درخواست دیگری استفاده شده است", code="idempotency_conflict")
        if int(existing["order_id"]) != order_id or int(existing["plan_id"]) != plan_id:
            raise ConflictError("کلید یکتایی با درخواست دیگری استفاده شده است", code="idempotency_conflict")
        return False, agreement_dict(conn, existing)
    if order["status"] in ("cancelled", "refunded"):
        raise ConflictError("سفارش لغوشده قابل اقساط نیست", code="order_not_eligible")
    intent = None
    if order["payment_intent_id"] is not None:
        intent = conn.execute("SELECT status, provider FROM payment_intents WHERE id = ?",
                              (order["payment_intent_id"],)).fetchone()
    if intent is not None and intent["status"] == "captured":
        raise ConflictError("مبلغ این سفارش قبلاً به‌طور کامل پرداخت شده و قابل اقساط نیست",
                            code="order_already_paid")
    sellers = _order_suppliers(conn, order_id)
    if len(sellers) > 1:
        raise ConflictError("این سفارش از چند فروشنده است؛ قرارداد اقساط فقط برای سفارش تک‌فروشنده ثبت می‌شود. "
                            "لطفاً سفارش را به تفکیک فروشنده ثبت کنید",
                            code="multi_seller_order", details={"supplier_ids": sorted(sellers)})
    if not sellers:
        raise ConflictError("فروشندهٔ این سفارش مشخص نیست و قرارداد اقساط قابل ثبت نیست",
                            code="order_seller_unknown")
    derived = next(iter(sellers))
    if supplier_id is not None and int(supplier_id) != derived:
        raise ValidationError("فروشندهٔ قرارداد از ردیف‌های سفارش تعیین می‌شود و با مقدار ارسالی مطابقت ندارد",
                              code="supplier_mismatch")
    supplier_id = derived
    if conn.execute("SELECT 1 FROM installment_agreements WHERE order_id = ? AND status <> 'cancelled'",
                    (order_id,)).fetchone():
        raise ConflictError("این سفارش قبلاً اقساطی شده است", code="installment_exists")
    plan = _plan(conn, plan_id)
    sched = build_schedule(int(order["total_minor"]), int(plan["months"]), int(plan["fee_bps"]),
                           int(plan["down_payment_bps"]), now)
    stamp = fmt(_utc(now))
    cursor = conn.execute(
        """
        INSERT INTO installment_agreements (reference, order_id, user_id, plan_id, supplier_id, months, fee_bps,
            down_payment_bps, principal_minor, down_payment_minor, financed_minor, fee_total_minor,
            total_payable_minor, creditor_kind, status, idempotency_key, created_by_user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'seller', 'active', ?,?,?,?)
        """,
        (_ref("INS"), order_id, int(order["user_id"]), plan_id, supplier_id, sched["months"], sched["fee_bps"],
         sched["down_payment_bps"], sched["principal_minor"], sched["down_payment_minor"],
         sched["financed_minor"], sched["fee_total_minor"], sched["total_payable_minor"],
         idempotency_key, actor["id"], stamp, stamp),
    )
    agreement_id = int(cursor.lastrowid)
    for r in sched["rows"]:
        conn.execute(
            "INSERT INTO installment_schedules (agreement_id, seq, due_at, principal_minor, fee_minor, amount_minor, "
            "updated_at) VALUES (?,?,?,?,?,?,?)",
            (agreement_id, r["seq"], r["due_at"], r["principal_minor"], r["fee_minor"], r["amount_minor"], stamp),
        )
    audit_service.record(conn, action="installment.created", entity_type="installment_agreement",
                         entity_id=agreement_id, actor_user_id=actor["id"],
                         metadata={"order_id": order_id, "total_payable_minor": sched["total_payable_minor"]})
    return True, agreement_dict(conn, _agreement_row(conn, agreement_id))


def record_payment(conn, *, agreement_id: int, schedule_id: int, amount_minor: int, idempotency_key: str,
                   actor_user_id: int | None, external_reference: str | None = None,
                   now: datetime | None = None) -> tuple[bool, dict]:
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    existing = conn.execute("SELECT * FROM installment_payments WHERE idempotency_key = ?",
                            (idempotency_key,)).fetchone()
    if existing is not None:
        if int(existing["schedule_id"]) != schedule_id or int(existing["amount_minor"]) != amount_minor:
            raise ConflictError("کلید یکتایی با درخواست دیگری استفاده شده است", code="idempotency_conflict")
        return False, agreement_dict(conn, _agreement_row(conn, agreement_id))
    agreement = _agreement_row(conn, agreement_id)
    if agreement["status"] != "active":
        raise ConflictError("قرارداد اقساط فعال نیست", code="installment_not_active")
    sched = conn.execute("SELECT * FROM installment_schedules WHERE id = ? AND agreement_id = ?",
                         (schedule_id, agreement_id)).fetchone()
    if sched is None:
        raise NotFoundError("قسط یافت نشد", code="schedule_not_found")
    amount_minor = _int(amount_minor, "amount_minor")
    due = int(sched["amount_minor"]) - _paid_on(conn, schedule_id)
    if amount_minor > due:
        raise ValidationError("مبلغ بیشتر از ماندهٔ قسط است", code="overpayment", details={"due_minor": due})
    stamp = fmt(_utc(now))
    conn.execute(
        "INSERT INTO installment_payments (reference, schedule_id, agreement_id, amount_minor, paid_at, "
        "external_reference, idempotency_key, actor_user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (_ref("INP"), schedule_id, agreement_id, amount_minor, stamp, external_reference, idempotency_key,
         actor_user_id, stamp),
    )
    if amount_minor == due:
        conn.execute("UPDATE installment_schedules SET status = 'paid', paid_at = ?, updated_at = ? WHERE id = ?",
                     (stamp, stamp, schedule_id))
    if not conn.execute("SELECT 1 FROM installment_schedules WHERE agreement_id = ? AND status <> 'paid'",
                        (agreement_id,)).fetchone():
        conn.execute("UPDATE installment_agreements SET status = 'completed', updated_at = ? WHERE id = ?",
                     (stamp, agreement_id))
    return True, agreement_dict(conn, _agreement_row(conn, agreement_id))


def mark_late(conn, now: datetime | None = None) -> int:
    """Flag pending installments past due + plan grace days. Returns rows flagged."""
    now = _utc(now)
    count = 0
    rows = conn.execute(
        "SELECT s.id, s.due_at, p.late_grace_days FROM installment_schedules s "
        "JOIN installment_agreements a ON a.id = s.agreement_id JOIN installment_plans p ON p.id = a.plan_id "
        "WHERE s.status = 'pending' AND a.status = 'active'"
    ).fetchall()
    for r in rows:
        if parse_ts(r["due_at"]) + timedelta(days=int(r["late_grace_days"])) <= now:
            conn.execute("UPDATE installment_schedules SET status = 'late', is_late = 1, updated_at = ? WHERE id = ?",
                         (fmt(now), int(r["id"])))
            count += 1
    return count


def remaining_minor(conn, agreement_id: int) -> int:
    """Unpaid installments (seq >= 1; the down payment is the buyer's, not a receivable)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(s.amount_minor),0) AS due, "
        "(SELECT COALESCE(SUM(p.amount_minor),0) FROM installment_payments p JOIN installment_schedules s2 "
        " ON s2.id = p.schedule_id WHERE s2.agreement_id = ? AND s2.seq >= 1) AS paid "
        "FROM installment_schedules s WHERE s.agreement_id = ? AND s.seq >= 1",
        (agreement_id, agreement_id),
    ).fetchone()
    return int(row["due"]) - int(row["paid"])


def debt_sale_quote(conn, agreement_id: int, discount_bps: int) -> dict:
    discount_bps = _int(discount_bps, "discount_bps", minimum=0, maximum=5000)
    remaining = remaining_minor(conn, agreement_id)
    discount = remaining * discount_bps // 10_000
    return {"agreement_id": agreement_id, "remaining_minor": remaining, "discount_bps": discount_bps,
            "discount_minor": discount, "purchase_price_minor": remaining - discount}


def sell_debt(conn, *, agreement_id: int, discount_bps: int, idempotency_key: str, actor_user_id: int | None,
              supplier_id: int | None = None, now: datetime | None = None) -> tuple[bool, dict]:
    """Seller sells the remaining receivable to the platform at a discount (ledger only)."""
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    existing = conn.execute("SELECT * FROM debt_sales WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if existing is not None:
        if int(existing["agreement_id"]) != agreement_id:
            raise ConflictError("کلید یکتایی با درخواست دیگری استفاده شده است", code="idempotency_conflict")
        return False, dict(existing)
    agreement = _agreement_row(conn, agreement_id)
    if agreement["supplier_id"] is None or agreement["creditor_kind"] != "seller":
        raise ConflictError("این قرارداد دین قابل فروش ندارد", code="debt_not_sellable")
    if supplier_id is not None and int(agreement["supplier_id"]) != supplier_id:
        raise PermissionError_("این قرارداد متعلق به شما نیست")
    if agreement["status"] != "active":
        raise ConflictError("قرارداد اقساط فعال نیست", code="installment_not_active")
    q = debt_sale_quote(conn, agreement_id, discount_bps)
    if q["remaining_minor"] <= 0 or q["purchase_price_minor"] <= 0:
        raise ConflictError("ماندهٔ قابل فروش وجود ندارد", code="nothing_to_sell")
    reference = _ref("DS")
    entries = [Entry(ACCOUNT_PURCHASED_RECEIVABLES, "debit", q["remaining_minor"]),
               Entry(ACCOUNT_DEBT_PURCHASE_PAYABLE, "credit", q["purchase_price_minor"])]
    if q["discount_minor"]:
        entries.append(Entry(ACCOUNT_UNEARNED_DISCOUNT, "credit", q["discount_minor"]))
    ledger_service.post_transaction(conn, reference=reference,
                                    description=f"خرید دین اقساطی {agreement['reference']}", entries=entries)
    stamp = fmt(_utc(now))
    conn.execute(
        "INSERT INTO debt_sales (reference, agreement_id, supplier_id, remaining_minor, discount_bps, discount_minor, "
        "purchase_price_minor, ledger_reference, idempotency_key, actor_user_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (reference, agreement_id, int(agreement["supplier_id"]), q["remaining_minor"], q["discount_bps"],
         q["discount_minor"], q["purchase_price_minor"], reference, idempotency_key, actor_user_id, stamp),
    )
    conn.execute("UPDATE installment_agreements SET creditor_kind = 'platform', updated_at = ? WHERE id = ?",
                 (stamp, agreement_id))
    audit_service.record(conn, action="installment.debt_sold", entity_type="installment_agreement",
                         entity_id=agreement_id, actor_user_id=actor_user_id, metadata=q)
    return True, dict(conn.execute("SELECT * FROM debt_sales WHERE reference = ?", (reference,)).fetchone())


def user_summary(conn, user_id: int) -> dict:
    total = sum(remaining_minor(conn, int(r["id"])) for r in conn.execute(
        "SELECT id FROM installment_agreements WHERE user_id = ? AND status = 'active'", (user_id,)).fetchall())
    return {"outstanding_minor": total}
