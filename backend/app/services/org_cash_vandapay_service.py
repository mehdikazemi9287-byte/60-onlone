"""Organisation orders: pay the cash / prepayment share (``cash_status='due'``) through VandaPay.

Option, not a replacement: finance can still wire the money and confirm it by hand
(``org_order_service.confirm_cash_payment``). Off unless BOTH the VandaPay provider is enabled and
``VANDAPAY_ORG_CASH_ENABLED=1``.

Why a payment intent and not VandaPay "payment links": the secret-key merchant API that 60Online already
uses has ``POST /payment_intents`` (hosted checkout URL, signed webhooks, refunds). A secret-key
``/payment_links`` endpoint is still only a proposal (MASTER-PLAN VP-09). The hosted ``checkout_url`` works
as the link finance sends to the payer. When VP-09 exists only ``start`` changes.

State, without a new table or migration:
  * ``order_sources.cash_reference = 'vandapay-pending:<intent_id>'`` while a VandaPay session is open
    (the column is unused while the share is still due);
  * on a verified ``succeeded`` intent → ``cash_reference = 'vandapay:<intent_id>'`` and the existing
    ``finalize_paid`` (ledger, fulfillment release) with provider ``vandapay``.
  * money arriving for an order that is no longer due (cancelled, expired, confirmed by hand meanwhile)
    is given back with the adapter's ``reverse`` — never kept, never applied twice.

The browser return is never trusted: settlement re-fetches the intent server-to-server (amount, IRR, mode,
metadata ``org_order_id``), exactly like retail checkout.
"""
from __future__ import annotations

import json
import logging
import urllib.parse

from app.adapters.payment.base import GatewayError
from app.adapters.payment.registry import get_payment_provider
from app.adapters.payment.sepehr import to_rial
from app.adapters.payment.vandapay import (
    NAME as VANDAPAY, VandaPayPending, VandaPayProvider, build_items, org_cash_enabled,
)
from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError, PaymentFailedError, PermissionError_
from app.services import audit_service
from app.services import org_order_service as org

log = logging.getLogger("60online.org_cash_vandapay")

PENDING_PREFIX = "vandapay-pending:"
PAID_PREFIX = "vandapay:"


def provider_or_none() -> VandaPayProvider | None:
    if not org_cash_enabled():
        return None
    try:
        p = get_payment_provider(VANDAPAY)
    except KeyError:
        return None
    return p if isinstance(p, VandaPayProvider) else None


def _attempt_no(conn, order_id: int) -> int:
    """Failed sessions so far; part of the Idempotency-Key so a new attempt after a failure opens a new intent."""
    return int(conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'org_order.vandapay_failed' "
                            "AND entity_type = 'order' AND entity_id = ?", (str(order_id),)).fetchone()[0])


def _items(conn, order, cash_due: int) -> list[dict]:
    if cash_due != int(order["total_minor"]):
        # Prepayment share: one line (VandaPay requires sum(items) == amount; splitting a share per line would
        # invent a per-line prepayment). Category = default goods.
        return [{"sku": f"ORG-CASH-{order['order_number']}", "name": f"سهم نقدی سفارش {order['order_number']}",
                 "quantity": 1, "category": "goods.general", "amount": to_rial(cash_due, order["currency"])}]
    lines = [dict(r) for r in conn.execute(
        "SELECT oi.product_id, oi.title_fa, oi.sku, oi.quantity, oi.line_total_minor, c.slug AS category_slug "
        "FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id "
        "LEFT JOIN categories c ON c.id = p.category_id WHERE oi.order_id = ? ORDER BY oi.id", (order["id"],))]
    return lines  # converted by the caller (needs the provider's category map)


def start(db: Database, *, organization_id: int, order_id: int, actor_user_id: int, public_base_url: str | None,
          provider: VandaPayProvider | None = None) -> dict:
    """Open (or re-open, idempotently) a VandaPay checkout for the order's due cash share."""
    provider = provider or provider_or_none()
    if provider is None:
        raise NotFoundError("پرداخت سهم نقدی با ونداپی فعال نیست", code="not_found")
    if not public_base_url:
        raise ConflictError("نشانی عمومی سایت تنظیم نشده است", code="payment_gateway_unavailable")
    with db.read_transaction() as conn:
        m = org._membership(conn, actor_user_id, organization_id)
        if not org._is_finance(m):
            raise PermissionError_("فقط مالی یا مدیر سازمان می‌تواند پرداخت را آغاز کند")
        src = conn.execute("SELECT * FROM order_sources WHERE order_id = ? AND organization_id = ?",
                           (order_id, organization_id)).fetchone()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if src is None or order is None:
            raise NotFoundError("سفارش سازمانی یافت نشد")
        if src["cash_status"] != "due" or order["status"] != "pending" or src["fulfillment_released"]:
            raise ConflictError("این سفارش سهم نقدیِ پرداخت‌نشده ندارد", code="cash_not_due")
        cash_due = int(src["cash_due_minor"])
        if cash_due <= 0:
            raise ConflictError("این سفارش سهم نقدیِ پرداخت‌نشده ندارد", code="cash_not_due")
        attempt = _attempt_no(conn, order_id)
        raw = _items(conn, order, cash_due)
        phone = conn.execute("SELECT phone_verified FROM users WHERE id = ?", (actor_user_id,)).fetchone()
        tier = "org"  # organisation orders are priced at the org/wholesale tier by org_order_service

    if raw and "line_total_minor" in raw[0]:
        items = build_items(lines=raw, subtotal_minor=int(order["subtotal_minor"]),
                            shipping_minor=int(order["shipping_fee_minor"]), tax_minor=int(order["tax_minor"]),
                            tax_rate_bps=int(order["tax_rate_bps"] or 0), currency=order["currency"],
                            category_map=provider.category_map, default_category=provider.default_item_category)
    else:
        items = raw
    return_url = (f"{public_base_url}/api/v1/payments/vandapay/org-cash/return?"
                  + urllib.parse.urlencode({"order_id": int(order_id)}))
    metadata = {"source": "60online", "kind": "org_cash", "org_order_id": str(int(order_id)),
                "organization_id": str(int(organization_id)), "price_tier": tier,
                "vat_bps": int(order["tax_rate_bps"] or 0), "vat_rial": to_rial(int(order["tax_minor"]), order["currency"]),
                "shipping_rial": to_rial(int(order["shipping_fee_minor"]), order["currency"])}
    try:
        intent_id, url = provider.open_intent(
            amount_rial=to_rial(cash_due, order["currency"]), order_ref=f"org-order:{order['order_number']}",
            return_url=return_url, metadata=metadata,
            idempotency_key=f"60online-org-order-{int(order_id)}-cash-{cash_due}-a{attempt}",
            items=items, category=provider.order_category,
            customer_phone=phone["phone_verified"] if phone is not None else None)
    except GatewayError as exc:
        log.warning("org cash vandapay initiate failed for order %s: %s", order_id, exc)
        raise PaymentFailedError("درگاه ونداپی در دسترس نیست؛ پولی کسر نشد. دوباره تلاش کنید.",
                                 code="payment_gateway_unavailable") from exc
    with db.write_transaction() as conn:
        changed = conn.execute("UPDATE order_sources SET cash_reference = ? WHERE order_id = ? AND cash_status = 'due' "
                               "AND (cash_reference IS NULL OR cash_reference LIKE ?)",
                               (PENDING_PREFIX + intent_id, order_id, PENDING_PREFIX + "%"))
        if changed.rowcount != 1:
            raise ConflictError("وضعیت پرداخت سفارش همزمان تغییر کرد", code="cash_not_due")
        audit_service.record(conn, action="org_order.vandapay_link", entity_type="order", entity_id=order_id,
                             actor_user_id=actor_user_id, metadata={"intent_id": intent_id, "cash_due_minor": cash_due})
    return {"order_id": int(order_id), "intent_id": intent_id, "checkout_url": url, "cash_due_minor": cash_due}


def settle(db: Database, *, order_id: int, provider: VandaPayProvider | None = None) -> str:
    """Finish a VandaPay cash-share payment from OUR stored intent id. Returns an outcome string.

    Raises ``VandaPayPending`` while VandaPay has not finalised, ``GatewayError`` if unreachable.
    """
    provider = provider or provider_or_none()
    if provider is None:
        return "disabled"
    with db.read_transaction() as conn:
        src = conn.execute("SELECT * FROM order_sources WHERE order_id = ?", (order_id,)).fetchone()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if src is None or order is None:
        return "unknown_order"
    ref = str(src["cash_reference"] or "")
    if ref.startswith(PAID_PREFIX):
        return "already_paid"
    if not ref.startswith(PENDING_PREFIX):
        return "no_open_session"
    intent_id = ref[len(PENDING_PREFIX):]
    return _settle_intent(db, provider=provider, order_id=order_id, intent_id=intent_id)


def _settle_intent(db: Database, *, provider: VandaPayProvider, order_id: int, intent_id: str) -> str:
    with db.read_transaction() as conn:
        src = conn.execute("SELECT * FROM order_sources WHERE order_id = ?", (order_id,)).fetchone()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    still_due = (src["cash_status"] == "due" and order["status"] == "pending"
                 and str(src["cash_reference"] or "") == PENDING_PREFIX + intent_id)
    if not still_due:
        if str(src["cash_reference"] or "") == PAID_PREFIX + intent_id:
            return "already_paid"
        # Cancelled / expired / confirmed by hand meanwhile: any money taken on this intent goes back.
        reversed_ok = provider.reverse({"_provider_ref": intent_id})
        with db.write_transaction() as conn:
            audit_service.record(conn, action="org_order.vandapay_late_reversed", entity_type="order",
                                 entity_id=order_id, actor_user_id=None,
                                 metadata={"intent_id": intent_id, "reversed": reversed_ok})
        return "payment_expired"
    result = provider.check_paid(intent_id, expected_amount_minor=int(src["cash_due_minor"]),
                                 currency=order["currency"], metadata_match={"org_order_id": order_id})
    if not result.succeeded:
        provider.reverse({"_provider_ref": intent_id})  # amount/metadata mismatch after payment → give it back
        with db.write_transaction() as conn:
            conn.execute("UPDATE order_sources SET cash_reference = NULL WHERE order_id = ? AND cash_reference = ?",
                         (order_id, PENDING_PREFIX + intent_id))
            audit_service.record(conn, action="org_order.vandapay_failed", entity_type="order", entity_id=order_id,
                                 actor_user_id=None, metadata={"intent_id": intent_id, "reason": result.failure_reason})
        return "payment_failed"
    with db.write_transaction() as conn:
        changed = conn.execute("UPDATE order_sources SET cash_reference = ? WHERE order_id = ? AND cash_status = 'due' "
                               "AND cash_reference = ?", (PAID_PREFIX + intent_id, order_id, PENDING_PREFIX + intent_id))
        if changed.rowcount != 1:
            return "already_paid"
        org.finalize_paid(conn, order_id=order_id, actor_user_id=int(src["created_by_user_id"]),
                          provider=VANDAPAY, provider_ref=intent_id)
    return "ok"


def settle_by_intent(db: Database, *, provider: VandaPayProvider, intent_id: str) -> str | None:
    """Webhook entry: the org order whose open/paid session is this intent, settled; None if not an org cash intent."""
    with db.read_transaction() as conn:
        row = conn.execute("SELECT order_id FROM order_sources WHERE cash_reference IN (?, ?)",
                           (PENDING_PREFIX + intent_id, PAID_PREFIX + intent_id)).fetchone()
        if row is None:
            # The reference was overwritten (finance confirmed a wire meanwhile, or a newer session was opened):
            # find the order from the append-only audit of opened sessions so late money is still given back.
            hit = conn.execute("SELECT entity_id FROM audit_logs WHERE action = 'org_order.vandapay_link' "
                               "AND entity_type = 'order' AND metadata_json LIKE ? ORDER BY id DESC LIMIT 1",
                               ('%"intent_id": ' + json.dumps(intent_id) + '%',)).fetchone()
            row = {"order_id": int(hit["entity_id"])} if hit is not None else None
    if row is None:
        return None
    try:
        return _settle_intent(db, provider=provider, order_id=int(row["order_id"]), intent_id=intent_id)
    except VandaPayPending:
        return "pending"
