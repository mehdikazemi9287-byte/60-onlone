"""Customer cancellation of a retail order before shipment (لغو سفارش پیش از ارسال).

When an order may be cancelled — derived from the existing state machines, nothing new is invented:

* ``orders.status`` must be ``paid`` (a retail checkout moves pending → paid in one transaction; nothing in the
  code moves an order to ``fulfilling``/``delivered``). Organization orders (``order_sources``) have their own
  cancel path (``org_order_service.cancel_org_order``) and are refused here.
* Every fulfillment order must still be able to reach ``cancelled`` under
  ``fulfillment_engine.VALID_TRANSITIONS``: pending_assignment, assigned, accepted, preparing. ``ready`` (packed,
  waiting for pickup/courier), ``dispatched`` and ``delivered`` cannot be cancelled. ``rejected``/``cancelled``/
  ``failed`` FOs are already inactive and do not block.
* No carrier label/booking exists (logistics_shipments other than ``failed``; shipments other than
  planned/failed/booking_failed), no open return request, no active installment agreement and no Moadian
  e-invoice for any of the order's FOs — each of those needs a person, so the customer is sent to support.

What one cancellation does, all in ONE write transaction (BEGIN IMMEDIATE), so it is atomic:

1. FOs → ``cancelled`` (state log, reason) and their seller-offer reservations released; the legacy
   ``inventory`` rows decremented at checkout are given back. Stock is restored exactly once.
2. Organization credit captured for the order is reversed (``credit_service.reverse_capture``, append-only).
3. Welfare wallet spend is restored to the same plans (``welfare_wallet_service.restore_partial``).
4. 60Coin: the coins actually redeemed on the order (from the loyalty ledger) are given back; the purchase
   coins earned on it are clawed back, never below a zero balance (any shortfall is recorded, not hidden).
5. Ledger: one balanced reversal of the sale (debit 4010/4020/2010; credit 1020 for credit+welfare and
   2060 «بازپرداختنی به مشتریان» for the card share).
6. The card/gateway share becomes an ``order_refunds`` row in ``pending_finance``. No gateway refund is
   attempted automatically (the card gateway's rollback is same-day only and VandaPay refunds go through
   finance); finance pays it and records the reference (``mark_refund_paid``: debit 2060, credit 1010).
7. ``order_cancellations`` row (UNIQUE order_id: a second cancel returns the first result, idempotent),
   audit log entries and an in-app notification.

Supplier settlement: payables are created only when an FO is delivered
(``supplier_ledger_service.record_sale_payable``), and a cancelled FO can never be delivered, so a cancelled
order never reaches a settlement batch.
"""
from __future__ import annotations

import json
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import audit_service, ledger_service

CANCELLABLE_FO = ("pending_assignment", "assigned", "accepted", "preparing")
INACTIVE_FO = ("rejected", "cancelled", "failed")
ACCOUNT_CUSTOMER_REFUNDS_PAYABLE = "2060"
REASON_MAX = 500

MESSAGES = {
    "already_cancelled": "این سفارش قبلاً لغو شده است.",
    "order_not_paid": "فقط سفارش پرداخت‌شده‌ای که هنوز ارسال نشده قابل لغو است.",
    "org_order": "سفارش سازمانی از پنل سازمان لغو می‌شود.",
    "shipping_started": "آماده‌سازی یا ارسال این سفارش آغاز شده و دیگر قابل لغو نیست. برای مرجوعی پس از تحویل اقدام کنید یا با پشتیبانی تماس بگیرید.",
    "return_open": "برای این سفارش درخواست مرجوعی باز است؛ لطفاً با پشتیبانی تماس بگیرید.",
    "installment": "این سفارش قرارداد اقساط دارد و لغو آن باید با پشتیبانی انجام شود.",
    "tax_invoice": "برای این سفارش صورتحساب مالیاتی صادر شده و لغو آن باید با پشتیبانی انجام شود.",
}


def _order_for_user(conn: sqlite3.Connection, order_number: str, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM orders WHERE order_number = ? AND user_id = ?",
                       (order_number, user_id)).fetchone()
    if row is None:
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    return row


def _fos(conn: sqlite3.Connection, order_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, status, supplier_id FROM fulfillment_orders WHERE order_id = ? ORDER BY id",
                        (order_id,)).fetchall()


def check(conn: sqlite3.Connection, order: sqlite3.Row) -> dict:
    """{"cancellable": bool, "code": str|None, "message": str|None} — read-only."""
    def no(code: str) -> dict:
        return {"cancellable": False, "code": code, "message": MESSAGES[code]}

    if order["status"] == "cancelled":
        return no("already_cancelled")
    if conn.execute("SELECT 1 FROM order_sources WHERE order_id = ?", (order["id"],)).fetchone():
        return no("org_order")
    if order["status"] != "paid":
        return no("order_not_paid")
    fos = _fos(conn, int(order["id"]))
    if any(fo["status"] not in CANCELLABLE_FO + INACTIVE_FO for fo in fos):
        return no("shipping_started")
    fo_ids = [int(fo["id"]) for fo in fos]
    if conn.execute("SELECT 1 FROM logistics_shipments WHERE order_id = ? AND status <> 'failed' LIMIT 1",
                    (order["id"],)).fetchone():
        return no("shipping_started")
    if fo_ids:
        marks = ",".join("?" * len(fo_ids))
        if conn.execute(f"SELECT 1 FROM shipments WHERE fulfillment_order_id IN ({marks}) "
                        "AND status NOT IN ('planned','failed','booking_failed') LIMIT 1", fo_ids).fetchone():
            return no("shipping_started")
        if conn.execute(f"SELECT 1 FROM moadian_documents WHERE source_ref IN ({marks}) LIMIT 1",
                        [f"fo:{i}" for i in fo_ids]).fetchone():
            return no("tax_invoice")
    if conn.execute("SELECT 1 FROM order_return_requests WHERE order_id = ? AND status NOT IN ('rejected','cancelled') "
                    "LIMIT 1", (order["id"],)).fetchone():
        return no("return_open")
    if conn.execute("SELECT 1 FROM installment_agreements WHERE order_id = ? AND status <> 'cancelled' LIMIT 1",
                    (order["id"],)).fetchone():
        return no("installment")
    return {"cancellable": True, "code": None, "message": None}


def status_for(conn: sqlite3.Connection, *, order_id: int) -> dict:
    """What the customer's order page shows: whether it can be cancelled now, and the cancellation if any."""
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    result = check(conn, order)
    row = conn.execute("SELECT * FROM order_cancellations WHERE order_id = ?", (order_id,)).fetchone()
    result["cancellation"] = _view(conn, row) if row is not None else None
    return result


def _view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    refunds = [{"id": r["id"], "amount_minor": r["amount_minor"], "currency": r["currency"], "status": r["status"],
                "paid_at": r["paid_at"]}
               for r in conn.execute("SELECT * FROM order_refunds WHERE cancellation_id = ? ORDER BY id", (row["id"],))]
    return {
        "id": row["id"], "order_id": row["order_id"], "reason": row["reason"], "created_at": row["created_at"],
        "total_minor": row["total_minor"], "card_refund_minor": row["card_refund_minor"],
        "credit_restored_minor": row["credit_restored_minor"],
        "welfare_restored_minor": row["welfare_restored_minor"],
        "coins_restored": row["coins_restored"], "coins_clawed_back": row["coins_clawed_back"],
        "coins_clawback_shortfall": row["coins_clawback_shortfall"],
        "fulfillment_orders": json.loads(row["fulfillment_orders_json"] or "[]"),
        "ledger_reference": row["ledger_reference"], "refunds": refunds,
    }


def _clean_reason(reason) -> str | None:
    if reason is None:
        return None
    if not isinstance(reason, str):
        raise ValidationError("علت لغو باید متن باشد")
    reason = " ".join(reason.split())
    if len(reason) > REASON_MAX:
        raise ValidationError(f"علت لغو حداکثر {REASON_MAX} نویسه است")
    return reason or None


def cancel(conn: sqlite3.Connection, *, user_id: int, order_number: str, reason=None,
           ip_address: str | None = None) -> tuple[bool, dict]:
    """Cancel the caller's order. Must run inside ONE write transaction (the caller's BEGIN IMMEDIATE).

    Returns (created, cancellation_view). A repeated call for an already-cancelled order returns
    (False, the first cancellation) and changes nothing.
    """
    from app.services import credit_service, fulfillment_service, loyalty_service, welfare_wallet_service
    from app.services.commerce_ops_service import notify

    reason = _clean_reason(reason)
    order = _order_for_user(conn, order_number, user_id)
    order_id = int(order["id"])
    existing = conn.execute("SELECT * FROM order_cancellations WHERE order_id = ?", (order_id,)).fetchone()
    if existing is not None:
        return False, _view(conn, existing)
    verdict = check(conn, order)
    if not verdict["cancellable"]:
        raise ConflictError(verdict["message"], code="order_not_cancellable", details={"reason": verdict["code"]})

    total = int(order["total_minor"])
    credit_minor = int(order["credit_minor"] or 0)
    cash_minor = int(order["cash_minor"] or 0)
    welfare_minor = int(order["welfare_minor"] or 0) if "welfare_minor" in order.keys() else 0
    card_minor = cash_minor - welfare_minor
    if card_minor < 0 or card_minor + credit_minor + welfare_minor != total:
        raise ConflictError("مبالغ سفارش با هم نمی‌خوانند؛ لغو خودکار ممکن نیست. با پشتیبانی تماس بگیرید.",
                            code="order_amounts_inconsistent")
    intent_id = order["payment_intent_id"]

    # 1. Fulfillment orders → cancelled; their supplier-offer reservations released.
    fo_log = []
    for fo in _fos(conn, order_id):
        if fo["status"] not in CANCELLABLE_FO:
            continue
        for it in conn.execute("SELECT seller_offer_id, quantity FROM fulfillment_order_items "
                               "WHERE fulfillment_order_id = ?", (fo["id"],)).fetchall():
            fulfillment_service._release_stock(conn, offer_id=int(it["seller_offer_id"]), quantity=int(it["quantity"]))
        fulfillment_service._transition(
            conn, fulfillment_order_id=int(fo["id"]), to_status="cancelled", actor_type="system",
            actor_user_id=user_id, reason="لغو سفارش توسط مشتری پیش از ارسال",
            extra_updates={"cancellation_reason": ("لغو توسط مشتری" + (f": {reason}" if reason else ""))[:500]})
        fo_log.append({"id": int(fo["id"]), "from_status": fo["status"], "supplier_id": int(fo["supplier_id"])})

    # Legacy inventory rows were decremented at checkout (checkout_service._begin_attempt); give them back.
    for item in conn.execute("SELECT product_id, quantity FROM order_items WHERE order_id = ?", (order_id,)).fetchall():
        conn.execute("UPDATE inventory SET quantity_available = quantity_available + ?, updated_at = datetime('now') "
                     "WHERE product_id = ?", (int(item["quantity"]), int(item["product_id"])))

    if conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'paid'",
                    (order_id,)).rowcount != 1:  # compare-and-set; the whole cancellation rolls back otherwise
        raise ConflictError("وضعیت سفارش همزمان تغییر کرد؛ دوباره تلاش کنید", code="order_state_changed")

    # 2. Organization credit (append-only reversal; amount must match what the order used).
    credit_restored = 0
    if credit_minor > 0:
        credit_restored = credit_service.reverse_capture(
            conn, payment_intent_id=int(intent_id), order_id=order_id, actor_user_id=user_id,
            reason="لغو سفارش توسط مشتری")
        if credit_restored != credit_minor:
            raise ConflictError("برگشت اعتبار سازمانی با مبلغ سفارش نمی‌خواند؛ با پشتیبانی تماس بگیرید.",
                                code="credit_reversal_mismatch",
                                details={"expected_minor": credit_minor, "restored_minor": credit_restored})

    # 3. Welfare wallet.
    welfare_restored = 0
    if welfare_minor > 0:
        welfare_restored = welfare_wallet_service.restore_partial(
            conn, spend_key=f"intent:{intent_id}", amount_minor=welfare_minor,
            restore_key=f"intent:{intent_id}:restore:cancel")
        if welfare_restored != welfare_minor:
            raise ConflictError("برگشت کیف پول رفاهی با مبلغ سفارش نمی‌خواند؛ با پشتیبانی تماس بگیرید.",
                                code="welfare_reversal_mismatch",
                                details={"expected_minor": welfare_minor, "restored_minor": welfare_restored})

    # 4. 60Coin — from what the loyalty ledger actually holds for this order.
    coins = loyalty_service.order_coin_totals(conn, order_id)
    coins_restored = coins["redeemed"]
    if coins_restored > 0:
        loyalty_service.post_adjustment_conn(
            conn, user_id=user_id, amount_coins=coins_restored, order_id=order_id,
            idempotency_key=f"order-cancel:{order_id}:redeem-restore", actor_user_id=user_id,
            note=f"بازگشت ۶۰کوین خرج‌شده در سفارش لغوشده {order['order_number']}")
    clawback = min(coins["earned"], loyalty_service.balance(conn, user_id))
    shortfall = coins["earned"] - clawback
    if clawback > 0:
        loyalty_service.post_adjustment_conn(
            conn, user_id=user_id, amount_coins=-clawback, order_id=order_id,
            idempotency_key=f"order-cancel:{order_id}:earn-reverse", actor_user_id=user_id,
            note=f"کسر ۶۰کوین خرید سفارش لغوشده {order['order_number']}")

    # 5. Ledger reversal of the sale (only if the sale was posted — every checkout posts one).
    ledger_reference = None
    if total > 0 and conn.execute("SELECT 1 FROM ledger_transactions WHERE reference = ?",
                                  (f"order:{order['order_number']}",)).fetchone():
        E = ledger_service.Entry
        entries = [E(ledger_service.ACCOUNT_SALES_REVENUE, "debit", int(order["subtotal_minor"]))] \
            if int(order["subtotal_minor"]) > 0 else []
        if int(order["shipping_fee_minor"] or 0) > 0:
            entries.append(E(ledger_service.ACCOUNT_SHIPPING_REVENUE, "debit", int(order["shipping_fee_minor"])))
        if int(order["tax_minor"] or 0) > 0:
            entries.append(E(ledger_service.ACCOUNT_VAT_PAYABLE, "debit", int(order["tax_minor"])))
        if credit_minor + welfare_minor > 0:
            entries.append(E(ledger_service.ACCOUNT_ORG_RECEIVABLE, "credit", credit_minor + welfare_minor))
        if card_minor > 0:
            entries.append(E(ACCOUNT_CUSTOMER_REFUNDS_PAYABLE, "credit", card_minor))
        ledger_reference = f"order-cancel:{order['order_number']}"
        ledger_service.post_transaction(conn, reference=ledger_reference,
                                        description=f"لغو سفارش {order['order_number']} توسط مشتری",
                                        entries=entries, currency=order["currency"])

    cur = conn.execute(
        """INSERT INTO order_cancellations
               (order_id, user_id, reason, total_minor, card_refund_minor, credit_restored_minor,
                welfare_restored_minor, coins_restored, coins_clawed_back, coins_clawback_shortfall,
                fulfillment_orders_json, ledger_reference)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, user_id, reason, total, card_minor, credit_restored, welfare_restored, coins_restored,
         clawback, shortfall, json.dumps(fo_log), ledger_reference))
    cancellation_id = int(cur.lastrowid)

    # 6. Card/gateway share → a refund finance must pay (never pretended to be paid).
    if card_minor > 0:
        pay = conn.execute("SELECT provider, provider_ref FROM payments WHERE order_id = ? ORDER BY id LIMIT 1",
                           (order_id,)).fetchone()
        conn.execute(
            """INSERT INTO order_refunds (order_id, cancellation_id, kind, amount_minor, currency,
                                          payment_provider, payment_ref, idempotency_key)
               VALUES (?,?, 'customer_cancellation', ?,?,?,?,?)""",
            (order_id, cancellation_id, card_minor, order["currency"], pay["provider"] if pay else None,
             pay["provider_ref"] if pay else None, f"order-cancel:{order_id}:card"))

    # 7. Audit + customer notice.
    audit_service.record(
        conn, action="order.cancelled_by_customer", entity_type="order", entity_id=order_id, actor_user_id=user_id,
        metadata={"order_number": order["order_number"], "reason": reason, "total_minor": total,
                  "card_refund_minor": card_minor, "credit_restored_minor": credit_restored,
                  "welfare_restored_minor": welfare_restored, "coins_restored": coins_restored,
                  "coins_clawed_back": clawback, "coins_clawback_shortfall": shortfall,
                  "fulfillment_orders": fo_log, "ledger_reference": ledger_reference},
        ip_address=ip_address)
    body = ("مبلغ پرداختی با کارت پس از بررسی واحد مالی به حساب شما بازگردانده می‌شود."
            if card_minor > 0 else None)
    notify(conn, user_id, "order_status", f"سفارش {order['order_number']} لغو شد", body,
           f"/orders/{order['order_number']}")
    row = conn.execute("SELECT * FROM order_cancellations WHERE id = ?", (cancellation_id,)).fetchone()
    return True, _view(conn, row)


# ── finance: refunds owed for cancelled orders ──────────────────────────────

def list_refunds(conn: sqlite3.Connection, *, status: str | None = None) -> list[dict]:
    if status is not None and status not in ("pending_finance", "paid"):
        raise ValidationError("وضعیت نامعتبر است")
    sql = ("SELECT r.*, o.order_number, o.user_id FROM order_refunds r JOIN orders o ON o.id = r.order_id"
           + (" WHERE r.status = ?" if status else "") + " ORDER BY r.id DESC LIMIT 200")
    return [dict(r) for r in conn.execute(sql, (status,) if status else ())]


def mark_refund_paid(conn: sqlite3.Connection, *, refund_id: int, actor_user_id: int, bank_reference,
                     ip_address: str | None = None) -> dict:
    """Finance records that the refund was paid (bank transfer or gateway refund done outside this system)."""
    ref = (bank_reference or "").strip() if isinstance(bank_reference, str) else ""
    if not 3 <= len(ref) <= 200:
        raise ValidationError("مرجع بانکی بازپرداخت الزامی است (۳ تا ۲۰۰ نویسه)")
    r = conn.execute("SELECT r.*, o.order_number FROM order_refunds r JOIN orders o ON o.id = r.order_id "
                     "WHERE r.id = ?", (refund_id,)).fetchone()
    if r is None:
        raise NotFoundError("بازپرداخت یافت نشد", code="refund_not_found")
    if r["status"] == "paid":
        if r["bank_reference"] == ref:
            return dict(r)  # same request repeated
        raise ConflictError("این بازپرداخت قبلاً با مرجع دیگری ثبت شده است", code="refund_already_paid")
    changed = conn.execute(
        """UPDATE order_refunds SET status = 'paid', bank_reference = ?, paid_by_user_id = ?,
                  paid_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                  version = version + 1
           WHERE id = ? AND status = 'pending_finance' AND version = ?""",
        (ref, actor_user_id, refund_id, r["version"]))
    if changed.rowcount != 1:
        raise ConflictError("بازپرداخت همزمان تغییر کرد؛ دوباره تلاش کنید", code="stale_version")
    ledger_service.post_transaction(
        conn, reference=f"refund-paid:{refund_id}",
        description=f"پرداخت بازپرداخت سفارش لغوشده {r['order_number']} (مرجع {ref})",
        entries=[ledger_service.Entry(ACCOUNT_CUSTOMER_REFUNDS_PAYABLE, "debit", int(r["amount_minor"])),
                 ledger_service.Entry(ledger_service.ACCOUNT_PSP_CLEARING, "credit", int(r["amount_minor"]))],
        currency=r["currency"])
    audit_service.record(conn, action="order_refund.paid", entity_type="order_refund", entity_id=refund_id,
                         actor_user_id=actor_user_id,
                         metadata={"order_number": r["order_number"], "amount_minor": int(r["amount_minor"]),
                                   "bank_reference": ref}, ip_address=ip_address)
    return dict(conn.execute("SELECT r.*, o.order_number FROM order_refunds r JOIN orders o ON o.id = r.order_id "
                             "WHERE r.id = ?", (refund_id,)).fetchone())
