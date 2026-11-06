from __future__ import annotations

from urllib.parse import urlencode

from flask import Blueprint, jsonify, redirect, request

from app.core.deps import client_ip, current_user, get_db, get_settings, require_auth
from app.core.errors import ValidationError
from app.services import checkout_service, fulfillment_service, order_service

bp = Blueprint("orders", __name__, url_prefix="/api/v1")


@bp.post("/checkout")
@require_auth("customer")
def checkout():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    settings = get_settings()
    user = current_user()
    raw_redeem = body.get("redeem_coins", 0)
    try:
        redeem_coins = int(raw_redeem) if raw_redeem not in (None, "") else 0
    except (TypeError, ValueError) as exc:
        raise ValidationError("redeem_coins باید عدد صحیح باشد") from exc
    # Buyer terms: record the accepted version as evidence; required when LEGAL_REQUIRE_BUYER_TERMS=1.
    accepted = body.get("accepted_terms_version")
    import os
    from app.services import consumer_rights_service
    if accepted is not None or os.environ.get("LEGAL_REQUIRE_BUYER_TERMS") == "1":
        if not isinstance(accepted, str):
            raise ValidationError("پذیرفتن شرایط خرید لازم است", code="terms_required")
        with get_db().write_transaction() as conn:
            consumer_rights_service.record_acceptance(
                conn, user_id=user["id"], doc_key="buyer_terms", version=accepted, context="checkout",
                context_ref=request.headers.get("Idempotency-Key", "")[:200], ip=client_ip(),
                user_agent=request.headers.get("User-Agent"))
    # Card gateway by default; an enabled external credit provider (Tara, Digipay, SnappPay) on request.
    from flask import current_app
    provider_name = settings.payment_provider
    chosen = body.get("payment_provider")
    if chosen is not None:
        allowed = set(current_app.extensions.get("external_credit_providers", [])) | {settings.payment_provider}
        if chosen not in allowed:
            raise ValidationError("این روش پرداخت فعال نیست", code="payment_provider_unavailable")
        provider_name = chosen
    status, payload = checkout_service.checkout(
        get_db(),
        user_id=user["id"],
        user_email=user["email"],
        address=body.get("shipping_address") or {},
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        payment_provider_name=provider_name,
        payment_method=body.get("payment_method", "card"),
        exponent=settings.currency_exponent,
        ip_address=client_ip(),
        redeem_coins=redeem_coins,
        callback_url=_callback_url(settings, provider_name),
        use_welfare=body.get("use_welfare") is True,
    )
    if status == 202:  # pay on the bank page first; the order is created on return
        return jsonify(payload), status
    return jsonify({"order": payload}), status


def _callback_url(settings, provider_name: str | None = None) -> str | None:
    if not settings.public_base_url:
        return None
    return f"{settings.public_base_url}/api/v1/payments/{provider_name or settings.payment_provider}/callback"


@bp.get("/checkout/payment-options")
def payment_options():
    """Methods the checkout page may offer. Labels are Persian; order = display order."""
    from flask import current_app
    from app.adapters.payment.external_credit import PROVIDERS
    settings = get_settings()
    opts = [{"provider": settings.payment_provider, "kind": "card", "label": "کارت بانکی (درگاه شتاب)"}]
    for name in current_app.extensions.get("external_credit_providers", []):
        opts.append({"provider": name, "kind": "external_credit", "label": PROVIDERS[name][0],
                     "note": "اعتبار را خود این شرکت می‌دهد؛ شرایط و اقساط با اوست."})
    return jsonify({"options": opts})


@bp.route("/payments/<provider>/callback", methods=["GET", "POST"])
def payment_callback(provider: str):
    """The bank returns the customer's browser here (no auth header on this hop)."""
    settings = get_settings()
    from flask import current_app
    known = {settings.payment_provider, *current_app.extensions.get("external_credit_providers", [])}
    if provider not in known or provider == "mock":
        return redirect("/checkout?" + urlencode({"payment": "failed", "reason": "unknown_gateway"}), 303)
    callback = {**request.args.to_dict(), **request.form.to_dict()}
    outcome = checkout_service.complete_redirect_payment(
        get_db(), provider_name=provider, callback=callback,
        exponent=settings.currency_exponent, ip_address=client_ip(),
    )
    if outcome.get("ok") and outcome.get("order_number"):
        return redirect(f"/orders/{outcome['order_number']}?" + urlencode({"payment": "success"}), 303)
    params = {"payment": "failed", "reason": outcome.get("reason", "payment_failed")}
    if outcome.get("reference"):
        params["ref"] = outcome["reference"]
    return redirect("/checkout?" + urlencode(params), 303)


@bp.get("/orders")
@require_auth("customer")
def list_orders():
    def _int(name: str, default: int) -> int:
        raw = request.args.get(name)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValidationError(f"پارامتر {name} باید عدد باشد") from exc

    return jsonify(
        order_service.list_orders(
            get_db(),
            user_id=current_user()["id"],
            page=_int("page", 1),
            page_size=_int("page_size", 10),
            exponent=get_settings().currency_exponent,
        )
    )


@bp.get("/orders/<order_number>")
@require_auth("customer")
def get_order(order_number: str):
    db   = get_db()
    user = current_user()
    exponent = get_settings().currency_exponent
    with db.read_transaction() as conn:
        row = conn.execute(
            "SELECT id FROM orders WHERE order_number = ? AND user_id = ?",
            (order_number, user["id"]),
        ).fetchone()
        from app.core.errors import NotFoundError
        if row is None:
            raise NotFoundError("سفارش یافت نشد", code="order_not_found")
        order_id = int(row["id"])
        order = order_service.read_order(conn, order_id=order_id, user_id=user["id"], exponent=exponent)
        # Phase 3: include fulfillment info
        fulfillment_orders = fulfillment_service.list_fulfillment_orders_for_order(
            conn, order_id=order_id
        )
    return jsonify({"order": order, "fulfillment_orders": fulfillment_orders})


@bp.get("/checkout/welfare")
@require_auth()
def welfare_for_cart():
    """How much of the current cart the buyer's welfare wallet can pay (0 when none)."""
    from app.services import cart_service, welfare_wallet_service
    user = current_user()
    with get_db().read_transaction() as conn:
        cart = cart_service.read_cart(conn, user["id"], get_settings().currency_exponent)
        lines = [{"product_id": i["product_id"], "line_total_minor": i["line_total_minor"]} for i in cart["items"]]
        membership, allowed = welfare_wallet_service.best_membership(conn, user["id"], lines) if lines else (None, 0)
        return jsonify({"available": allowed > 0, "allowed_minor": allowed,
                        "remaining_minor": welfare_wallet_service.member_summary(conn, user["id"])["remaining_minor"]})
