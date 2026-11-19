"""Refunds of retail returns paid through VandaPay — sent through the gateway, not wired by hand.

Before this module every return refund was a manual bank transfer recorded by finance
(``commerce_ops_service.admin_transition``). For an order whose money came through VandaPay that is wrong:
VandaPay must give each funding leg back to where it came from (organisation credit to the employer's purse,
gift card to the card, the card share to the card), so the refund is requested with the adapter instead.

Flow (``refund_return``):
  1. Read-only checks in one transaction: the return is ``refund_pending``, the order has a captured VandaPay
     payment, the amount fits what is still unrefunded. Under the exclusive-funding rule
     (docs/decisions/2026-11-18-federated-credit-vandapay.md) such an order carries no internal welfare share;
     if it ever does, the gateway path refuses and finance handles it by hand.
  2. The HTTP call runs OUTSIDE every DB transaction with a deterministic Idempotency-Key
     ``60online-return-<return_id>-<amount>``: a retry, a double click or a crash after the call can never
     refund twice.
  3. VandaPay 201 ``succeeded`` → the normal ``refund`` transition (order marked refunded when fully refunded).
     VandaPay 202 ``pending`` → the return stays ``refund_pending`` with ``refund_reference=vandapay:<re_id>``;
     the ``refund.succeeded`` webhook finishes it (``apply_refund_event``), idempotently.
     VandaPay 4xx (e.g. ``partial_refund_unsupported``, ``split_refund_manual_review``) → nothing changes; the
     admin gets ``gateway_refund_manual_review`` and may record a manual refund with ``manual_override``.
"""
from __future__ import annotations

import logging

from app.adapters.payment.base import GatewayError
from app.adapters.payment.registry import get_payment_provider
from app.adapters.payment.sepehr import to_rial
from app.adapters.payment.vandapay import NAME as VANDAPAY, VandaPayAPIError, VandaPayProvider
from app.core.db import Database
from app.core.errors import ApiError, ConflictError, NotFoundError, ValidationError

log = logging.getLogger("60online.gateway_refund")

REF_PREFIX = "vandapay:"


class GatewayUnavailableError(ApiError):
    status_code = 503
    code = "gateway_unavailable"


def gateway_payment(conn, order_id: int):
    """The captured VandaPay payment of an order, or None (card gateway / credit-only / manual orders)."""
    return conn.execute(
        "SELECT provider, provider_ref, amount_minor, currency FROM payments "
        "WHERE order_id = ? AND provider = ? AND status = 'captured' ORDER BY id LIMIT 1",
        (order_id, VANDAPAY),
    ).fetchone()


def gateway_for_return(conn, return_id: int) -> str | None:
    r = conn.execute("SELECT order_id FROM order_return_requests WHERE id = ?", (return_id,)).fetchone()
    if r is None:
        return None
    return VANDAPAY if gateway_payment(conn, int(r["order_id"])) is not None else None


def refund_key(return_id: int, amount_minor: int) -> str:
    return f"60online-return-{int(return_id)}-{int(amount_minor)}"


def _provider() -> VandaPayProvider:
    try:
        provider = get_payment_provider(VANDAPAY)
    except KeyError:
        provider = None
    if not isinstance(provider, VandaPayProvider):
        raise ConflictError("درگاه ونداپی روی این سرور فعال نیست؛ بازپرداخت را دستی ثبت کنید",
                            code="gateway_disabled")
    return provider


def refund_return(db: Database, *, actor: int, return_id: int, data: dict) -> tuple[int, dict]:
    """Refund a return of a VandaPay-paid order through VandaPay. Returns (http_status, return_view)."""
    from app.services import commerce_ops_service as ops

    amount = data.get("amount_minor")
    note = (data.get("note") or "").strip()[:1000] or None
    with db.read_transaction() as conn:
        r = conn.execute("SELECT * FROM order_return_requests WHERE id = ?", (return_id,)).fetchone()
        if r is None:
            raise NotFoundError("درخواست مرجوعی یافت نشد")
        if r["status"] != "refund_pending":
            raise ConflictError("این تغییر وضعیت مجاز نیست", code="invalid_transition")
        pay = gateway_payment(conn, int(r["order_id"]))
        if pay is None:
            raise ConflictError("این سفارش با ونداپی پرداخت نشده است", code="not_gateway_paid")
        order = conn.execute("SELECT total_minor, welfare_minor FROM orders WHERE id = ?", (r["order_id"],)).fetchone()
        prior = conn.execute("SELECT COALESCE(SUM(refund_amount_minor),0) FROM order_return_requests "
                             "WHERE order_id = ? AND status = 'refunded'", (r["order_id"],)).fetchone()[0]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 \
                or amount > int(order["total_minor"]) - int(prior):
            raise ValidationError("مبلغ بازپرداخت نامعتبر است یا از مانده سفارش بیشتر است")
        if int(order["welfare_minor"] or 0) > 0:  # cannot happen under exclusive funding; never guess a split
            raise ConflictError("این سفارش سهم کیف رفاهی داخلی دارد؛ بازپرداخت باید دستی بررسی شود",
                                code="gateway_refund_manual_review")
        intent_id, currency = str(pay["provider_ref"]), str(pay["currency"])

    provider = _provider()
    try:  # outside every transaction; deterministic key → at most one refund per (return, amount)
        res = provider.create_refund(intent_id, amount, key=refund_key(return_id, amount),
                                     reason=f"60online return {int(return_id)}")
    except VandaPayAPIError as exc:
        log.warning("vandapay refund refused for return %s: %s", return_id, exc.code)
        raise ConflictError("ونداپی این بازپرداخت را خودکار انجام نداد؛ بررسی و ثبت دستی لازم است",
                            code="gateway_refund_manual_review", details={"vandapay_code": exc.code}) from exc
    except GatewayError as exc:
        log.error("vandapay refund unreachable for return %s: %s", return_id, exc)
        raise GatewayUnavailableError("ونداپی در دسترس نیست؛ چیزی تغییر نکرد. دوباره تلاش کنید "
                                      "(تکرار درخواست، بازپرداخت دوم نمی‌سازد).") from exc

    refund_ref = REF_PREFIX + (res["id"] or f"{intent_id}:{amount}")
    status = res["status"]
    with db.write_transaction() as conn:
        if status == "succeeded":
            view = ops.admin_transition(conn, actor=actor, return_id=return_id, action="refund",
                                        data={"amount_minor": amount, "reference": refund_ref, "note": note},
                                        gateway_settled=True)
            return 200, dict(view, gateway={"provider": VANDAPAY, "status": "succeeded", "refund_id": res["id"]})
        if status == "pending":
            conn.execute("UPDATE order_return_requests SET refund_amount_minor = ?, refund_reference = ?, "
                         "version = version + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                         "WHERE id = ? AND status = 'refund_pending'", (amount, refund_ref, return_id))
            conn.execute("INSERT INTO order_return_events (return_id, actor_user_id, status, note) VALUES (?,?,?,?)",
                         (return_id, actor, "refund_pending",
                          f"بازپرداخت ونداپی در جریان ({refund_ref}); با وب‌هوک نهایی می‌شود"))
            view = ops._return_view(conn, conn.execute("SELECT * FROM order_return_requests WHERE id = ?",
                                                       (return_id,)).fetchone())
            return 202, dict(view, gateway={"provider": VANDAPAY, "status": "pending", "refund_id": res["id"]})
    raise ConflictError("ونداپی وضعیت بازپرداخت را نهایی اعلام نکرد؛ بررسی دستی لازم است",
                        code="gateway_refund_manual_review", details={"vandapay_status": status})


def apply_refund_event(db: Database, *, provider: VandaPayProvider, event_type: str, data: dict,
                       vp_intent_id: str) -> str:
    """Settle a ``refund.*`` webhook. Returns an outcome string. Idempotent (status-guarded).

    The event body is not trusted for money: for ``refund.succeeded`` the intent is re-read and its
    ``refunded_amount`` must cover every refund 60Online has recorded plus this one.
    """
    from app.services import audit_service, commerce_ops_service as ops

    refund_id = data.get("id") if isinstance(data.get("id"), str) else ""
    with db.read_transaction() as conn:
        pay = conn.execute("SELECT order_id, currency FROM payments WHERE provider = ? AND provider_ref = ? "
                           "AND status = 'captured'", (VANDAPAY, vp_intent_id)).fetchone()
        ret = None
        if pay is not None and refund_id:
            ret = conn.execute("SELECT * FROM order_return_requests WHERE order_id = ? AND refund_reference = ?",
                               (pay["order_id"], REF_PREFIX + refund_id)).fetchone()
    if pay is None:
        return "refund_unknown_payment"
    order_id = int(pay["order_id"])

    if ret is None:
        # A refund made in the VandaPay panel (no return request here): record it for finance, change nothing.
        with db.write_transaction() as conn:
            audit_service.record(conn, action="payment.refund_external", entity_type="order", entity_id=order_id,
                                 actor_user_id=None,
                                 metadata={"provider": VANDAPAY, "event": event_type, "refund_id": refund_id or None,
                                           "intent_id": vp_intent_id})
        return "refund_logged"
    if ret["status"] == "refunded":
        return "already_refunded"
    if ret["status"] != "refund_pending":
        return "refund_logged"

    if event_type == "refund.succeeded":
        live = provider.retrieve(vp_intent_id)  # GatewayError → caller answers 503 (VandaPay retries)
        with db.read_transaction() as conn:
            done = conn.execute("SELECT COALESCE(SUM(refund_amount_minor),0) FROM order_return_requests "
                                "WHERE order_id = ? AND status = 'refunded'", (order_id,)).fetchone()[0]
        need = to_rial(int(done) + int(ret["refund_amount_minor"] or 0), str(pay["currency"]))
        if live.get("mode") != provider.mode or int(live.get("refunded_amount") or 0) < need:
            return "refund_not_confirmed"
        with db.write_transaction() as conn:
            fresh = conn.execute("SELECT status FROM order_return_requests WHERE id = ?", (ret["id"],)).fetchone()
            if fresh["status"] != "refund_pending":  # a concurrent delivery got there first
                return "already_refunded"
            actor = conn.execute("SELECT actor_user_id FROM order_return_events WHERE return_id = ? "
                                 "ORDER BY id DESC LIMIT 1", (ret["id"],)).fetchone()["actor_user_id"]
            ops.admin_transition(conn, actor=int(actor), return_id=int(ret["id"]), action="refund",
                                 data={"amount_minor": int(ret["refund_amount_minor"]),
                                       "reference": ret["refund_reference"],
                                       "note": "بازپرداخت ونداپی نهایی شد (وب‌هوک)"},
                                 gateway_settled=True)
        return "refund_applied"

    if event_type in ("refund.failed", "refund.canceled"):
        with db.write_transaction() as conn:
            fresh = conn.execute("SELECT status, refund_reference FROM order_return_requests WHERE id = ?",
                                 (ret["id"],)).fetchone()
            if fresh["status"] != "refund_pending" or fresh["refund_reference"] != ret["refund_reference"]:
                return "already_handled"
            actor = conn.execute("SELECT actor_user_id FROM order_return_events WHERE return_id = ? "
                                 "ORDER BY id DESC LIMIT 1", (ret["id"],)).fetchone()["actor_user_id"]
            # Clear the gateway reference so finance can retry or record a manual refund; keep the audit trail.
            conn.execute("UPDATE order_return_requests SET refund_reference = NULL, version = version + 1, "
                         "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (ret["id"],))
            conn.execute("INSERT INTO order_return_events (return_id, actor_user_id, status, note) VALUES (?,?,?,?)",
                         (ret["id"], int(actor), "refund_pending",
                          f"بازپرداخت ونداپی ناموفق بود ({ret['refund_reference']}); اقدام دستی لازم است"))
        return "refund_failed_manual_review"
    return "refund_logged"
