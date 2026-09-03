"""Employee-facing credit API and the checkout quote."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, get_settings, require_auth
from app.core.errors import ValidationError
from app.services import credit_service, quote_service

bp = Blueprint("credit", __name__, url_prefix="/api/v1")


def _exp() -> int:
    return get_settings().currency_exponent


@bp.get("/me/credit")
@require_auth("customer")
def my_credit():
    """Everything the credit widget needs. Scoped to the caller by user_id."""
    return jsonify(credit_service.wallet(
        get_db(), user_id=current_user()["id"], exponent=_exp()
    ))


@bp.get("/me/credit/transactions")
@require_auth("customer")
def my_credit_transactions():
    def _int(name: str, default: int) -> int:
        raw = request.args.get(name)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValidationError(f"پارامتر {name} باید عدد باشد") from exc

    # user_id is forced to the caller: an employee cannot read a colleague's
    # credit history by passing someone else's id.
    return jsonify(credit_service.list_credit_transactions(
        get_db(), user_id=current_user()["id"], page=_int("page", 1),
        page_size=_int("page_size", 25), exponent=_exp(),
    ))


@bp.post("/checkout/quote")
@bp.get("/checkout/quote")
@require_auth("customer")
def checkout_quote():
    """Server-authoritative split-payment breakdown for the caller's cart.

    The client renders this and posts nothing monetary back. `checkout`
    recomputes the same quote inside its own transaction, so a stale quote
    cannot be exploited.
    """
    raw_redeem = request.args.get("redeem_coins")
    if raw_redeem is None and request.is_json:
        raw_redeem = (request.get_json(silent=True) or {}).get("redeem_coins")
    try:
        redeem_coins = int(raw_redeem) if raw_redeem not in (None, "") else 0
    except (TypeError, ValueError) as exc:
        raise ValidationError("redeem_coins باید عدد صحیح باشد") from exc
    return jsonify(quote_service.get_quote(
        get_db(), user_id=current_user()["id"], exponent=_exp(), redeem_coins=redeem_coins,
    ))
