"""Checkout: the one place in the system that moves money and stock.

Phase 2 rewrote this as a two-phase command so that the PSP call happens with
no database transaction open — see the long comment at the top of
`payment_service.py` for why, and for how a real gateway plugs in.

Guarantees, each covered by a test:

  * Idempotent  - replaying an Idempotency-Key returns the first response and
                  creates exactly one order, one charge and one set of ledger
                  entries. An attempt that is still in flight is rejected
                  rather than duplicated.
  * Race-safe   - stock uses a conditional UPDATE guarded by
                  `quantity_available >= qty`; credit re-derives its balance
                  from the credit ledger. Both run inside BEGIN IMMEDIATE, so
                  two buyers competing for the last unit — or an employee
                  firing two checkouts at the same remaining credit — produce
                  exactly one success.
  * Atomic where it can be - everything before the PSP call commits together;
                  everything after commits together. A failed charge releases
                  the credit hold and restores the stock.
  * Balanced    - every completed checkout posts one balanced double-entry
                  transaction whose debits name the funding source: PSP
                  clearing for the cash leg, organization receivable for the
                  credit leg.

Observable Flow 1 behaviour is unchanged: a retail customer with no
organization still gets 201 with a paid order, and a declined card still
leaves no order, no payment and no ledger entry.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.adapters.payment.base import GatewayError, PaymentRequest, RedirectPaymentProvider
from app.adapters.payment.registry import get_payment_provider
from app.core.db import Database
from app.services.freshness_service import enforce_freshness_for_checkout
from app.core.errors import (
    ApiError,
    ConflictError,
    FulfillmentUnavailableError,
    OutOfStockError,
    PaymentFailedError,
    ValidationError,
)
from app.services import (
    audit_service,
    cart_service,
    credit_service,
    fulfillment_service,
    ledger_service,
    loyalty_service,
    order_service,
    payment_service,
    quote_service,
)
from app.services.integration_event_service import fan_out_business_event

log = logging.getLogger("70online.checkout")

ENDPOINT = "POST /api/v1/checkout"
REQUIRED_ADDRESS_FIELDS = ("recipient_name", "recipient_phone", "province", "city", "line1")

# 60Coin purchase-earning rate (see backend/migrations/0025_loyalty_foundation.sql).
# Approved rule: 1,000 Toman of eligible merchandise value = 1 60Coin.
# Amounts in this file are IRR minor units (currency_exponent=0, 1 Toman = 10 Rial),
# so 1,000 Toman = 10,000 minor units. Eligible value is the merchandise subtotal
# only — shipping and VAT are excluded unless a documented rule says otherwise.
RIAL_PER_TOMAN = 10
TOMAN_PER_COIN = 1_000
LOYALTY_EARN_MINOR_PER_COIN = RIAL_PER_TOMAN * TOMAN_PER_COIN  # 10,000


def _request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _new_order_number(conn: sqlite3.Connection) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"ORD-{stamp}-{secrets.token_hex(3).upper()}"
        if conn.execute("SELECT 1 FROM orders WHERE order_number = ?", (candidate,)).fetchone() is None:
            return candidate
    raise ConflictError("could not allocate an order number")


def validate_address(address: dict) -> dict:
    errors, cleaned = {}, {}
    for field in REQUIRED_ADDRESS_FIELDS:
        value = (address.get(field) or "").strip() if isinstance(address, dict) else ""
        if not value:
            errors[field] = "این فیلد الزامی است"
        cleaned[field] = value
    if not errors and len(cleaned["recipient_phone"]) < 8:
        errors["recipient_phone"] = "شماره تماس معتبر نیست"
    if errors:
        raise ValidationError("آدرس ارسال ناقص است", details=errors)
    postal = (address.get("postal_code") or "").strip() if isinstance(address, dict) else ""
    cleaned["postal_code"] = postal or None
    return cleaned


def _store_idempotent_result(
    conn: sqlite3.Connection, *, key: str, user_id: int, request_hash: str,
    status_code: int, body: dict, intent_id: int | None,
) -> None:
    conn.execute(
        """
        UPDATE idempotency_keys
        SET status_code = ?, response_json = ?, state = 'completed', payment_intent_id = ?
        WHERE key = ? AND user_id = ? AND endpoint = ?
        """,
        (status_code, json.dumps(body, ensure_ascii=False), intent_id, key, user_id, ENDPOINT),
    )
    if conn.total_changes == 0:  # pragma: no cover - defensive
        conn.execute(
            """
            INSERT INTO idempotency_keys
                (key, user_id, endpoint, request_hash, status_code, response_json, state, payment_intent_id)
            VALUES (?,?,?,?,?,?, 'completed', ?)
            """,
            (key, user_id, ENDPOINT, request_hash, status_code,
             json.dumps(body, ensure_ascii=False), intent_id),
        )


# ---------------------------------------------------------------- phase one
def _begin_attempt(
    db: Database, *, user_id: int, cleaned_address: dict, idempotency_key: str,
    payload_hash: str, exponent: int, ip_address: str | None, redeem_coins: int = 0,
) -> tuple[int, dict] | tuple[None, tuple[int, dict]]:
    """Reserve everything and commit. Returns (intent_id, quote) or a replayed response."""
    with db.write_transaction() as conn:
        stored = conn.execute(
            "SELECT request_hash, status_code, response_json, state, payment_intent_id "
            "FROM idempotency_keys WHERE key = ? AND user_id = ? AND endpoint = ?",
            (idempotency_key, user_id, ENDPOINT),
        ).fetchone()
        if stored is not None:
            if stored["request_hash"] != payload_hash:
                raise ConflictError(
                    "این Idempotency-Key قبلاً با درخواست متفاوتی استفاده شده است",
                    code="idempotency_key_reuse",
                )
            if stored["state"] == "completed":
                return None, (int(stored["status_code"]), json.loads(stored["response_json"]))

            # Still in flight. Reclaim only if it has clearly been abandoned;
            # otherwise refuse, because two live attempts on one key would
            # double-charge.
            intent_row = payment_service.get_intent(conn, int(stored["payment_intent_id"]))
            if (int(stored["status_code"]) == 202 and intent_row["status"] == "authorized"
                    and not payment_service.is_stale(intent_row)):
                # Waiting on the bank page: hand back the same redirect, never open a second session.
                return None, (202, json.loads(stored["response_json"]))
            if not payment_service.is_stale(intent_row):
                raise ConflictError(
                    "پرداخت قبلی با همین کلید هنوز در جریان است. لطفاً چند لحظه صبر کنید.",
                    code="checkout_in_progress",
                )
            # Release any supplier-stock reserved by the stale plan before reclaiming
            fulfillment_service.release_supplier_stock_for_plan(
                conn, plan_json=dict(intent_row).get("fulfillment_plan_json")
            )
            payment_service.reclaim_stale_intent(
                conn, int(stored["payment_intent_id"]), actor_user_id=user_id
            )
            conn.execute(
                "DELETE FROM idempotency_keys WHERE key = ? AND user_id = ? AND endpoint = ?",
                (idempotency_key, user_id, ENDPOINT),
            )

        cart = cart_service.read_cart(conn, user_id, exponent)
        if not cart["items"]:
            raise ValidationError("سبد خرید خالی است", code="cart_empty")

        # Server-authoritative split. Recomputed here, inside the transaction —
        # a quote the client saw earlier is never trusted.
        quote = quote_service.build_quote(
            conn, user_id=user_id, exponent=exponent, redeem_coins=redeem_coins,
        )

        for item in cart["items"]:
            result = conn.execute(
                """
                UPDATE inventory
                SET quantity_available = quantity_available - ?,
                    quantity_reserved = quantity_reserved + ?,
                    updated_at = datetime('now')
                WHERE product_id = ? AND quantity_available >= ?
                """,
                (item["quantity"], item["quantity"], item["product_id"], item["quantity"]),
            )
            has_legacy_stock = conn.execute("SELECT 1 FROM inventory WHERE product_id=?", (item["product_id"],)).fetchone()
            if result.rowcount != 1 and (has_legacy_stock or not item.get("offer_id")):
                # Offer-bound SKUs without a legacy inventory row are reserved on the seller offer below.
                raise OutOfStockError(
                    f"موجودی «{item['title_fa']}» کافی نیست",
                    details={"product_id": item["product_id"]},
                )

        lines = []
        for item in cart["items"]:
            row = conn.execute(
                "SELECT c.slug AS s FROM products p JOIN categories c ON c.id = p.category_id WHERE p.id = ?",
                (item["product_id"],),
            ).fetchone()
            lines.append({
                "product_id": item["product_id"], "title_fa": item["title_fa"], "sku": item["sku"],
                "category_slug": row["s"] if row else "",
                "unit_price_minor": item["unit_price_minor"], "quantity": item["quantity"],
                "line_total_minor": item["line_total_minor"],
            })

        # ── Phase 3: Fulfillment-First ─────────────────────────────────────────
        # Plan fulfillment for every cart item BEFORE creating the payment intent.
        # If no valid supplier exists for any item, raise FulfillmentUnavailableError —
        # the transaction rolls back and NO MONEY MOVES.
        # The plan is stored in payment_intents.fulfillment_plan_json so that:
        #   _complete_attempt → creates FOs from the confirmed plan (no re-routing)
        #   _fail_attempt     → releases the reserved supplier stock
        fulfillment_plan = fulfillment_service.plan_fulfillment(
            conn,
            cart_items        = cart["items"],
            customer_province = cleaned_address["province"],
            customer_city     = cleaned_address["city"],
        )
        # Enforce freshness for all offers in the plan.
        # If any offer is EXPIRED and its expired_action is block_checkout/block_all,
        # FreshnessError (409) is raised here — before any stock is reserved or money moved.
        for item in fulfillment_plan.get("items", []):
            if item.get("offer_id"):
                enforce_freshness_for_checkout(conn, item["offer_id"])
        # Reserve supplier stock under BEGIN IMMEDIATE — race-safe.
        # If any reservation fails (another concurrent checkout grabbed the last unit),
        # ConflictError (supplier_stock_changed) propagates and the transaction rolls back.
        fulfillment_service.reserve_supplier_stock_for_plan(conn, plan=fulfillment_plan)
        # ── End fulfillment-first block ────────────────────────────────────────

        intent_id = payment_service.create_intent(
            conn, user_id=user_id, idempotency_key=idempotency_key, request_hash=payload_hash,
            quote=quote, address=cleaned_address, lines=lines,
        )

        # Persist the plan so _fail_attempt and _complete_attempt can use it
        conn.execute(
            "UPDATE payment_intents SET fulfillment_plan_json = ? WHERE id = ?",
            (json.dumps(fulfillment_plan, ensure_ascii=False), intent_id),
        )

        if quote["credit_to_use_minor"] > 0:
            # Re-derives available credit inside this serialised transaction.
            # A concurrent attempt cannot see the same credit as free.
            credit_service.reserve(
                conn,
                allocation_id=quote["allocation"]["id"],
                amount_minor=quote["credit_to_use_minor"],
                payment_intent_id=intent_id,
                actor_user_id=user_id,
            )

        payment_service.transition(conn, intent_id, "authorized")
        conn.execute(
            """
            INSERT INTO idempotency_keys
                (key, user_id, endpoint, request_hash, status_code, response_json, state, payment_intent_id)
            VALUES (?,?,?,?, 0, '{}', 'in_progress', ?)
            """,
            (idempotency_key, user_id, ENDPOINT, payload_hash, intent_id),
        )
        audit_service.record(
            conn, action="payment.intent_created", entity_type="payment_intent", entity_id=intent_id,
            actor_user_id=user_id,
            metadata={"total_minor": quote["cart"]["total_minor"],
                      "credit_minor": quote["credit_to_use_minor"],
                      "cash_minor": quote["cash_due_minor"],
                      "organization_id": (quote.get("organization") or {}).get("id")},
            ip_address=ip_address,
        )
        return intent_id, quote


# ---------------------------------------------------------------- phase two
def _complete_attempt(
    db: Database, *, intent_id: int, user_id: int, payment_result, payment_method: str,
    idempotency_key: str, payload_hash: str, exponent: int, ip_address: str | None,
) -> tuple[int, dict, list[int]]:
    """Returns (http_status, response_body, created_fo_ids).

    created_fo_ids is the list of fulfillment_order IDs created in this call.
    It is EMPTY when returning a replayed/concurrent-complete result — the
    caller must NOT re-trigger shipment planning for those.
    """
    with db.write_transaction() as conn:
        intent = payment_service.get_intent(conn, intent_id)
        if intent["status"] == "captured":  # a concurrent completer won
            return 201, order_service.read_order(
                conn, order_id=int(intent["order_id"]), user_id=user_id, exponent=exponent
            ), []

        subtotal_minor     = int(intent["subtotal_minor"])
        shipping_minor     = int(intent["shipping_fee_minor"])
        total_minor        = int(intent["total_minor"])
        credit_minor       = int(intent["credit_minor"])
        cash_minor         = int(intent["cash_minor"])
        # ── Tax snapshot (calculated during build_quote, persisted in intent) ──
        # We use the persisted snapshot — NEVER recalculate — so the tax amount
        # collected always equals the tax amount recorded in the order and ledger.
        tax_minor          = int(intent["tax_minor"])
        taxable_base_minor = int(intent["taxable_base_minor"])
        tax_rate_bps       = int(intent["tax_rate_bps"])
        redeem_coins           = int(dict(intent).get("redeem_coins") or 0)
        redeem_discount_minor  = int(dict(intent).get("redeem_discount_minor") or 0)

        order_number = _new_order_number(conn)
        cursor = conn.execute(
            """
            INSERT INTO orders (order_number, user_id, status, subtotal_minor, shipping_fee_minor,
                                total_minor, tax_minor, taxable_base_minor, tax_rate_bps,
                                currency, recipient_name, recipient_phone,
                                shipping_province, shipping_city, shipping_line1, shipping_postal_code,
                                organization_id, credit_minor, cash_minor, payment_intent_id,
                                redeem_coins, redeem_discount_minor)
            VALUES (?,?,'pending',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (order_number, user_id, subtotal_minor, shipping_minor, total_minor,
             tax_minor, taxable_base_minor, tax_rate_bps,
             intent["currency"],
             intent["recipient_name"], intent["recipient_phone"], intent["shipping_province"],
             intent["shipping_city"], intent["shipping_line1"], intent["shipping_postal_code"],
             intent["organization_id"], credit_minor, cash_minor, intent_id,
             redeem_coins, redeem_discount_minor),
        )
        order_id = int(cursor.lastrowid)

        for item in payment_service.intent_items(conn, intent_id):
            conn.execute(
                """
                INSERT INTO order_items (order_id, product_id, title_fa, sku, unit_price_minor,
                                         quantity, line_total_minor)
                VALUES (?,?,?,?,?,?,?)
                """,
                (order_id, item["product_id"], item["title_fa"], item["sku"],
                 item["unit_price_minor"], item["quantity"], item["line_total_minor"]),
            )

        if cash_minor > 0 and payment_result is not None:
            conn.execute(
                """
                INSERT INTO payments (order_id, provider, provider_ref, method, amount_minor, currency, status)
                VALUES (?,?,?,?,?,?,?)
                """,
                (order_id, payment_result.provider, payment_result.provider_ref, payment_method,
                 payment_result.amount_minor, payment_result.currency, payment_result.status.value),
            )

        if credit_minor > 0:
            credit_service.capture(
                conn, payment_intent_id=intent_id, order_id=order_id, actor_user_id=user_id
            )

        payment_service.consume_stock_reservation(conn, intent_id)

        # ---- double-entry -------------------------------------------------------
        # Debit side: where the money came from (funding sources)
        #   1010 PSP Clearing   = cash leg (card payment)
        #   1020 Org Receivable = credit leg (employer-funded credit)
        # Credit side: what the money represents
        #   4010 Sales Revenue  = merchandise subtotal
        #   4020 Shipping       = shipping fee (if any)
        #   2010 VAT Payable    = tax collected (if any) — a LIABILITY, not revenue
        #
        # Invariant: sum(debits) = cash_minor + credit_minor = total_minor
        #            = subtotal_minor + shipping_minor + tax_minor = sum(credits)
        entries = []
        if cash_minor > 0:
            entries.append(ledger_service.Entry(ledger_service.ACCOUNT_PSP_CLEARING, "debit", cash_minor))
        if credit_minor > 0:
            entries.append(
                ledger_service.Entry(ledger_service.ACCOUNT_ORG_RECEIVABLE, "debit", credit_minor)
            )
        entries.append(ledger_service.Entry(ledger_service.ACCOUNT_SALES_REVENUE, "credit", subtotal_minor))
        if shipping_minor > 0:
            entries.append(
                ledger_service.Entry(ledger_service.ACCOUNT_SHIPPING_REVENUE, "credit", shipping_minor)
            )
        if tax_minor > 0:
            entries.append(
                ledger_service.Entry(ledger_service.ACCOUNT_VAT_PAYABLE, "credit", tax_minor)
            )
        ledger_service.post_transaction(
            conn, reference=f"order:{order_number}",
            description=f"فروش سفارش {order_number}", entries=entries, currency=intent["currency"],
        )

        conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
        payment_service.transition(
            conn, intent_id, "captured", order_id=order_id,
            provider=payment_result.provider if payment_result else "credit_only",
            provider_ref=payment_result.provider_ref if payment_result else f"credit:{intent['reference']}",
        )

        active_cart = conn.execute(
            "SELECT id FROM carts WHERE user_id = ? AND status = 'active'", (user_id,)
        ).fetchone()
        if active_cart is not None:
            conn.execute("UPDATE carts SET status = 'ordered' WHERE id = ?", (active_cart["id"],))

        audit_service.record(
            conn, action="order.placed", entity_type="order", entity_id=order_id,
            actor_user_id=user_id,
            metadata={"order_number": order_number, "total_minor": total_minor,
                      "credit_minor": credit_minor, "cash_minor": cash_minor,
                      "organization_id": intent["organization_id"],
                      "provider": payment_result.provider if payment_result else "credit_only",
                      "provider_ref": payment_result.provider_ref if payment_result else None},
            ip_address=ip_address,
        )
        if credit_minor > 0:
            audit_service.record(
                conn, action="order.split_payment", entity_type="order", entity_id=order_id,
                actor_user_id=user_id,
                metadata={"order_number": order_number, "credit_minor": credit_minor,
                          "cash_minor": cash_minor, "organization_id": intent["organization_id"]},
                ip_address=ip_address,
            )

        # Phase 3: Create fulfillment orders from the pre-approved plan.
        # Stock was already reserved in phase 1 — we do NOT re-route or re-reserve.
        created_fo_ids: list[int] = []
        plan_json = dict(intent).get("fulfillment_plan_json")
        if plan_json:
            order_items_rows = conn.execute(
                "SELECT id, product_id FROM order_items WHERE order_id = ?", (order_id,)
            ).fetchall()
            created_fo_ids = fulfillment_service.confirm_fulfillment_orders_from_plan(
                conn,
                order_id     = order_id,
                order_items  = [dict(r) for r in order_items_rows],
                plan         = json.loads(plan_json),
                actor_user_id = user_id,
            )

        body = order_service.read_order(conn, order_id=order_id, user_id=user_id, exponent=exponent)
        _store_idempotent_result(
            conn, key=idempotency_key, user_id=user_id, request_hash=payload_hash,
            status_code=201, body=body, intent_id=intent_id,
        )

        # Outbox: fan-out ORDER_CREATED to connectors belonging to the buying
        # organization. supplier_id is None here because the order is the buyer-
        # facing event; fulfillment-side events are emitted separately.
        fan_out_business_event(
            conn,
            event_type="ORDER_CREATED",
            supplier_id=None,
            organization_id=intent["organization_id"],
            payload={
                "order_id": order_id,
                "order_number": order_number,
                "total_minor": total_minor,
                "status": "paid",
            },
            base_idempotency_key=f"order_created:{order_id}",
        )

        return 201, body, created_fo_ids


def _award_purchase_coins(
    db: Database, *, order_id: int, user_id: int, subtotal_minor: int,
) -> None:
    """Credit 60Coin for a committed purchase.

    Called AFTER _complete_attempt's transaction has already committed the
    order and payment — never from inside it. 60Coin is a loyalty ledger,
    structurally isolated from the financial ledger (see loyalty_service
    module docstring and migration 0025); it never touches orders.total_minor,
    credit_ledger_entries, or ledger_entries. A failure here is caught and
    logged, and must never undo, retry, or re-charge the payment.

    The idempotency key is deterministic per order (`purchase:{order_id}`),
    so a checkout retry, a concurrent-completer race, or a future manual
    replay can never award coins twice for the same order.
    """
    coins = subtotal_minor // LOYALTY_EARN_MINOR_PER_COIN
    if coins <= 0:
        # Below the minimum conversion threshold (1,000 Toman) — earn nothing,
        # deterministically. loyalty_service.earn() rejects a zero amount, so
        # this must be a guard here rather than a call with amount_coins=0.
        return
    try:
        loyalty_service.earn(
            db,
            user_id=user_id,
            amount_coins=coins,
            source="purchase",
            order_id=order_id,
            idempotency_key=f"purchase:{order_id}",
            expires_at=loyalty_service.expiry_stamp_for_new_earn(),
        )
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        log.warning(
            "checkout: loyalty earn failed for order_id=%s (payment already committed): %s",
            order_id, exc, exc_info=True,
        )


def _redeem_purchase_coins(
    db: Database, *, order_id: int, user_id: int, redeem_coins: int,
) -> None:
    """Debit the 60Coin the customer chose to redeem on this order.

    Same safety shape as _award_purchase_coins: called AFTER the order and
    payment have already committed, never from inside that transaction, so a
    failure here can never undo or re-charge a successful order. The coin
    discount was already reflected in what the customer was actually
    charged (quote_service reduced the taxable subtotal before the PSP was
    called) — this call only records the ledger debit for it. Idempotent
    per order (`redeem:{order_id}`): a retry or concurrent-completer replay
    can never double-debit.
    """
    if redeem_coins <= 0:
        return
    try:
        loyalty_service.redeem(
            db,
            user_id=user_id,
            amount_coins=redeem_coins,
            order_id=order_id,
            idempotency_key=f"redeem:{order_id}",
            note="استفاده از ۶۰کوین در تسویه‌حساب",
        )
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        log.warning(
            "checkout: loyalty redeem failed for order_id=%s (payment already committed, "
            "customer was already charged the discounted amount): %s",
            order_id, exc, exc_info=True,
        )


def _fail_attempt(
    db: Database, *, intent_id: int, user_id: int, error: ApiError, idempotency_key: str,
    payload_hash: str, ip_address: str | None,
) -> None:
    """Undo phase one. Compensating actions, not a rollback — phase one committed."""
    with db.write_transaction() as conn:
        # Release supplier-stock reservation before any other compensation
        intent_row = payment_service.get_intent(conn, intent_id)
        fulfillment_service.release_supplier_stock_for_plan(
            conn, plan_json=dict(intent_row).get("fulfillment_plan_json")
        )
        credit_service.release(
            conn, payment_intent_id=intent_id, actor_user_id=user_id, reason="پرداخت ناموفق"
        )
        payment_service.restore_stock(conn, intent_id)
        payment_service.transition(conn, intent_id, "failed", failure_reason=error.message[:500])
        audit_service.record(
            conn, action="payment.failed", entity_type="payment_intent", entity_id=intent_id,
            actor_user_id=user_id, metadata={"code": error.code, "message": error.message},
            ip_address=ip_address,
        )
        # Store the failure as the idempotent outcome: replaying the same key
        # must reproduce the same answer, not start a second charge.
        _store_idempotent_result(
            conn, key=idempotency_key, user_id=user_id, request_hash=payload_hash,
            status_code=error.status_code, body=error.to_dict(), intent_id=intent_id,
        )


# -------------------------------------------------------------------- entry
def _mock_payments_allowed() -> bool:
    """Mock captures exist only for the automated unit-test harness (APP_ENV=test)."""
    from app.services.sale_eligibility import _test_override_enabled
    return _test_override_enabled()


def checkout(
    db: Database,
    *,
    user_id: int,
    user_email: str,
    address: dict,
    idempotency_key: str,
    payment_provider_name: str,
    payment_method: str = "card",
    exponent: int = 0,
    ip_address: str | None = None,
    redeem_coins: int = 0,
    callback_url: str | None = None,
) -> tuple[int, dict]:
    """Returns (http_status, response_body).

    With a redirect gateway (Sepehr) and cash to pay, returns 202 with ``payment_redirect``:
    the order is created later by ``complete_redirect_payment`` when the bank returns.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise ValidationError("هدر Idempotency-Key الزامی است", code="idempotency_key_required")
    idempotency_key = idempotency_key.strip()
    if len(idempotency_key) > 200:
        raise ValidationError("Idempotency-Key بیش از حد طولانی است")
    if not isinstance(redeem_coins, int) or isinstance(redeem_coins, bool) or redeem_coins < 0:
        raise ValidationError("redeem_coins باید عدد صحیح نامنفی باشد")

    cleaned_address = validate_address(address)
    payload_hash = _request_hash({
        "address": cleaned_address, "method": payment_method, "redeem_coins": redeem_coins,
    })
    if payment_provider_name == "mock" and not _mock_payments_allowed():
        # Payment boundary: without a real gateway no charge, capture or paid order is ever simulated.
        # Cart problems (unverified/ineligible items) are reported first, as they would be at a real gateway.
        with db.write_transaction() as conn:
            cart_service.read_cart(conn, user_id, exponent)
        raise ConflictError(
            "درگاه پرداخت آنلاین هنوز متصل نیست؛ پرداخت انجام نشد. می‌توانید سبد را به‌صورت درخواست خرید ثبت کنید.",
            code="payment_gateway_unavailable", details={"alternative": "purchase_request"},
        )
    provider = get_payment_provider(payment_provider_name)
    if isinstance(provider, RedirectPaymentProvider):
        try:  # cheap housekeeping so abandoned bank visits never strand stock or credit
            release_abandoned_redirects(db, limit=20)
        except Exception:
            log.warning("release_abandoned_redirects failed", exc_info=True)

    # ---- phase one (committed) -------------------------------------------
    intent_id, quote_or_replay = _begin_attempt(
        db, user_id=user_id, cleaned_address=cleaned_address, idempotency_key=idempotency_key,
        payload_hash=payload_hash, exponent=exponent, ip_address=ip_address,
        redeem_coins=redeem_coins,
    )
    if intent_id is None:
        return quote_or_replay  # replayed a completed attempt

    quote = quote_or_replay
    cash_minor = int(quote["cash_due_minor"])

    if cash_minor > 0 and isinstance(provider, RedirectPaymentProvider):
        return _start_redirect(
            db, provider=provider, intent_id=intent_id, quote=quote, user_id=user_id,
            user_email=user_email, idempotency_key=idempotency_key, payload_hash=payload_hash,
            payment_method=payment_method, ip_address=ip_address, callback_url=callback_url,
        )

    # ---- external call, deliberately outside every transaction ------------
    payment_result = None
    failure: ApiError | None = None
    try:
        if cash_minor > 0:
            payment_result = provider.charge(
                PaymentRequest(
                    amount_minor=cash_minor,
                    currency=quote["currency"],
                    order_reference=f"intent:{intent_id}",
                    idempotency_key=f"{user_id}:{idempotency_key}",
                    customer_email=user_email,
                    method=payment_method,
                    metadata={"payment_intent_id": intent_id,
                              "credit_minor": quote["credit_to_use_minor"]},
                )
            )
            if not payment_result.succeeded:
                failure = PaymentFailedError(
                    f"پرداخت ناموفق بود: {payment_result.failure_reason or 'نامشخص'}",
                    details={"provider": payment_result.provider},
                )
    except ApiError as exc:  # pragma: no cover - provider contract violation
        failure = exc
    except Exception as exc:  # pragma: no cover - defensive
        failure = PaymentFailedError(f"خطا در ارتباط با درگاه پرداخت: {exc}")

    if failure is not None:
        _fail_attempt(
            db, intent_id=intent_id, user_id=user_id, error=failure,
            idempotency_key=idempotency_key, payload_hash=payload_hash, ip_address=ip_address,
        )
        raise failure

    # ---- phase two (committed) -------------------------------------------
    status, body, created_fo_ids = _complete_attempt(
        db, intent_id=intent_id, user_id=user_id, payment_result=payment_result,
        payment_method="split" if (quote["credit_to_use_minor"] and cash_minor)
        else ("credit" if quote["credit_to_use_minor"] else payment_method),
        idempotency_key=idempotency_key, payload_hash=payload_hash,
        exponent=exponent, ip_address=ip_address,
    )

    _after_capture(db, body=body, created_fo_ids=created_fo_ids, user_id=user_id)
    return status, body


def _after_capture(db: Database, *, body: dict, created_fo_ids: list[int], user_id: int) -> None:
    # BLOCKER 1: trigger carrier shipment planning AFTER payment commits,
    # deliberately OUTSIDE any DB transaction — logistics failure must NOT
    # re-charge or roll back a successful payment.
    if created_fo_ids:
        from app.services import logistics_service  # lazy import — avoids circular
        for fo_id in created_fo_ids:
            try:
                logistics_service.ensure_shipment_plan(db, fo_id)
            except Exception as exc:
                log.warning(
                    "checkout: ensure_shipment_plan failed for fo_id=%s (payment already committed): %s",
                    fo_id, exc, exc_info=True,
                )

    # Loyalty: award 60Coin for the completed purchase. Deliberately AFTER
    # payment has committed and OUTSIDE any DB transaction — same rule as the
    # shipment planning above. A loyalty failure must never roll back or
    # re-charge a successful order.
    _award_purchase_coins(
        db, order_id=body["id"], user_id=user_id, subtotal_minor=body["subtotal_minor"],
    )
    _redeem_purchase_coins(
        db, order_id=body["id"], user_id=user_id, redeem_coins=body.get("redeem_coins", 0),
    )


# ------------------------------------------------------------ redirect gateway
def _start_redirect(
    db: Database, *, provider: RedirectPaymentProvider, intent_id: int, quote: dict, user_id: int,
    user_email: str, idempotency_key: str, payload_hash: str, payment_method: str,
    ip_address: str | None, callback_url: str | None,
) -> tuple[int, dict]:
    """Phase one is committed; open a bank session and send the browser there."""
    cash_minor = int(quote["cash_due_minor"])
    failure: ApiError | None = None
    instruction = None
    if not callback_url:
        failure = PaymentFailedError("نشانی بازگشت از درگاه تنظیم نشده است", code="payment_gateway_unavailable")
    else:
        try:
            instruction = provider.initiate(
                PaymentRequest(
                    amount_minor=cash_minor, currency=quote["currency"],
                    order_reference=f"intent:{intent_id}", idempotency_key=f"{user_id}:{idempotency_key}",
                    customer_email=user_email, method=payment_method,
                    metadata={"payment_intent_id": intent_id, "credit_minor": quote["credit_to_use_minor"]},
                ),
                invoice_id=intent_id, callback_url=callback_url,
            )
        except GatewayError as exc:
            log.warning("checkout: gateway initiate failed for intent %s: %s", intent_id, exc)
            failure = PaymentFailedError(
                "درگاه پرداخت در دسترس نیست؛ پولی کسر نشد. لطفاً دوباره تلاش کنید.",
                code="payment_gateway_unavailable",
            )
    if failure is not None:
        _fail_attempt(
            db, intent_id=intent_id, user_id=user_id, error=failure,
            idempotency_key=idempotency_key, payload_hash=payload_hash, ip_address=ip_address,
        )
        raise failure

    with db.write_transaction() as conn:
        intent = payment_service.get_intent(conn, intent_id)
        conn.execute(
            "UPDATE payment_intents SET provider = ?, provider_ref = ? WHERE id = ?",
            (instruction.provider, instruction.provider_ref, intent_id),
        )
        body = {
            "status": "payment_redirect",
            "payment_intent_id": intent_id,
            "reference": intent["reference"],
            "cash_due_minor": cash_minor,
            "credit_minor": int(quote["credit_to_use_minor"]),
            "currency": quote["currency"],
            "payment_redirect": instruction.to_dict(),
        }
        conn.execute(
            "UPDATE idempotency_keys SET status_code = 202, response_json = ? "
            "WHERE key = ? AND user_id = ? AND endpoint = ?",
            (json.dumps(body, ensure_ascii=False), idempotency_key, user_id, ENDPOINT),
        )
        audit_service.record(
            conn, action="payment.redirected", entity_type="payment_intent", entity_id=intent_id,
            actor_user_id=user_id, metadata={"provider": instruction.provider, "cash_minor": cash_minor},
            ip_address=ip_address,
        )
    return 202, body


def complete_redirect_payment(
    db: Database, *, provider_name: str, callback: dict, exponent: int = 0, ip_address: str | None = None,
) -> dict:
    """Run phase two when the bank returns the browser. Safe to call twice for one payment.

    Returns {"ok": True, "order_number": ...} or {"ok": False, "reason": ..., "reference": ...}.
    Any money taken for a payment we cannot honour is given back through the gateway.
    """
    provider = get_payment_provider(provider_name)
    if not isinstance(provider, RedirectPaymentProvider):
        return {"ok": False, "reason": "unsupported_provider"}

    invoice_id = provider.invoice_id_of(callback)
    intent = None
    if invoice_id:
        with db.write_transaction() as conn:
            intent = conn.execute("SELECT * FROM payment_intents WHERE id = ?", (invoice_id,)).fetchone()
    if intent is None or intent["provider"] != provider.name:
        log.warning("payment callback for unknown intent %r (provider %s)", invoice_id, provider.name)
        provider.reverse(callback)
        return {"ok": False, "reason": "unknown_payment"}

    reference = intent["reference"]
    if intent["status"] == "captured":
        with db.write_transaction() as conn:
            row = conn.execute(
                "SELECT order_number FROM orders WHERE payment_intent_id = ?", (intent["id"],)
            ).fetchone()
        return {"ok": True, "order_number": row["order_number"] if row else None, "reference": reference}
    if intent["status"] != "authorized":
        # Expired or released meanwhile: the stock/credit holds are gone, so the money must go back.
        reversed_ok = provider.reverse(callback)
        audit_kwargs = {"reversed": reversed_ok, "status": intent["status"]}
        with db.write_transaction() as conn:
            audit_service.record(
                conn, action="payment.late_callback_reversed", entity_type="payment_intent",
                entity_id=intent["id"], actor_user_id=intent["user_id"], metadata=audit_kwargs,
                ip_address=ip_address,
            )
        return {"ok": False, "reason": "payment_expired", "reference": reference}

    try:
        result = provider.verify(
            callback, expected_amount_minor=int(intent["cash_minor"]), currency=intent["currency"],
        )
    except GatewayError as exc:
        # The bank never got our confirmation, so it returns the money by itself. Keep the
        # holds until the stale-intent reclaim releases them; do not create an order.
        log.error("payment verify unreachable for intent %s: %s", intent["id"], exc)
        return {"ok": False, "reason": "verify_unavailable", "reference": reference}

    user_id = int(intent["user_id"])
    common = dict(intent_id=int(intent["id"]), user_id=user_id,
                  idempotency_key=intent["idempotency_key"], payload_hash=intent["request_hash"],
                  ip_address=ip_address)
    if not result.succeeded:
        provider.reverse(callback)
        _fail_attempt(db, error=PaymentFailedError(
            f"پرداخت ناموفق بود: {result.failure_reason or 'نامشخص'}", details={"provider": provider.name},
        ), **common)
        return {"ok": False, "reason": "payment_failed", "reference": reference}

    try:
        _status, body, created_fo_ids = _complete_attempt(
            db, payment_result=result, exponent=exponent,
            payment_method="split" if int(intent["credit_minor"]) else "card", **common,
        )
    except Exception as exc:  # the order could not be created: the money must not stay with us
        log.exception("order creation failed after verified payment, intent %s", intent["id"])
        provider.reverse(callback)
        error = exc if isinstance(exc, ApiError) else PaymentFailedError("ثبت سفارش پس از پرداخت ناموفق بود")
        _fail_attempt(db, error=error, **common)
        return {"ok": False, "reason": "order_failed", "reference": reference}

    _after_capture(db, body=body, created_fo_ids=created_fo_ids, user_id=user_id)
    return {"ok": True, "order_number": body.get("order_number"), "reference": reference}


# How long a customer may stay on the bank page. Longer than the gateway's own session,
# so a slow but successful payment is never released under it; a later callback is reversed anyway.
REDIRECT_ABANDON_AFTER_SECONDS = 1800


def release_abandoned_redirects(db: Database, *, now: datetime | None = None, limit: int = 100) -> int:
    """Free the stock and credit held by customers who left the bank page. Returns how many were released."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=REDIRECT_ABANDON_AFTER_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")
    with db.read_transaction() as conn:
        rows = conn.execute(
            "SELECT id, user_id, idempotency_key, request_hash FROM payment_intents "
            "WHERE status = 'authorized' AND provider_ref IS NOT NULL AND provider IS NOT NULL "
            "AND provider != 'mock' AND created_at < ? ORDER BY id LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    released = 0
    for row in rows:
        try:
            _fail_attempt(
                db, intent_id=int(row["id"]), user_id=int(row["user_id"]),
                error=PaymentFailedError("مهلت پرداخت در درگاه بانک تمام شد", code="payment_expired"),
                idempotency_key=row["idempotency_key"], payload_hash=row["request_hash"], ip_address=None,
            )
            released += 1
        except Exception:  # a concurrent callback may have just completed it
            log.warning("release_abandoned_redirects: intent %s not released", row["id"], exc_info=True)
    return released
