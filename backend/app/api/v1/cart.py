from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, get_settings, require_auth
from app.core.errors import ValidationError
from app.services import cart_service, shopping_mode

bp = Blueprint("cart", __name__, url_prefix="/api/v1/cart")


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    return body


def _require_int(body: dict, field: str) -> int:
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"فیلد {field} باید عدد صحیح باشد", details={field: "عدد صحیح لازم است"})
    return value


@bp.get("")
@require_auth("customer")
def get_cart():
    return jsonify(
        cart_service.get_cart(
            get_db(), user_id=current_user()["id"], exponent=get_settings().currency_exponent,
            mode=shopping_mode.from_request(),
        )
    )


@bp.get("/summary")
@require_auth("customer")
def cart_summary():
    """Item count of each shopping mode's cart. Never creates a cart."""
    return jsonify(cart_service.summary(get_db(), user_id=current_user()["id"]))


@bp.post("/items")
@require_auth("customer")
def add_item():
    body = _body()
    return (
        jsonify(
            cart_service.add_item(
                get_db(),
                user_id=current_user()["id"],
                product_id=_require_int(body, "product_id"),
                quantity=_require_int(body, "quantity"),
                mode=shopping_mode.from_request(body),
            )
        ),
        201,
    )


@bp.patch("/items/<int:product_id>")
@require_auth("customer")
def update_item(product_id: int):
    body = _body()
    return jsonify(
        cart_service.set_item_quantity(
            get_db(),
            user_id=current_user()["id"],
            product_id=product_id,
            quantity=_require_int(body, "quantity"),
            mode=shopping_mode.from_request(body),
        )
    )


@bp.delete("/items/<int:product_id>")
@require_auth("customer")
def remove_item(product_id: int):
    return jsonify(
        cart_service.remove_item(get_db(), user_id=current_user()["id"], product_id=product_id,
                                 mode=shopping_mode.from_request())
    )


@bp.delete("")
@require_auth("customer")
def clear():
    return jsonify(cart_service.clear_cart(get_db(), user_id=current_user()["id"], mode=shopping_mode.from_request()))
