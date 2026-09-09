"""Smart Pack Builder — saved packs, editing, bulk add-to-cart, proforma.

No fabrication: prices come only from the same eligibility check the storefront
uses; totals sum verified lines only; add-to-cart never forces an ineligible
product; proforma creates an owned procurement request with no invented quote.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, get_settings, require_auth
from app.core.errors import ValidationError
from app.services import pack_service

bp = Blueprint("packs", __name__, url_prefix="/api/v1/packs")


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    return body


def _exp() -> int:
    return get_settings().currency_exponent


@bp.get("")
@require_auth("customer")
def list_packs():
    return jsonify({"packs": pack_service.list_packs(get_db(), current_user()["id"])})


@bp.post("")
@require_auth("customer")
def create_pack():
    b = _body()
    return jsonify({"pack": pack_service.create_pack(
        get_db(), current_user()["id"], b.get("name", ""), b.get("kind", "custom"), _exp())}), 201


@bp.get("/<int:pack_id>")
@require_auth("customer")
def get_pack(pack_id: int):
    return jsonify({"pack": pack_service.get_pack(get_db(), current_user()["id"], pack_id, _exp())})


@bp.patch("/<int:pack_id>")
@require_auth("customer")
def rename_pack(pack_id: int):
    b = _body()
    return jsonify({"pack": pack_service.rename_pack(
        get_db(), current_user()["id"], pack_id, b.get("name", ""), _exp())})


@bp.delete("/<int:pack_id>")
@require_auth("customer")
def delete_pack(pack_id: int):
    return jsonify(pack_service.delete_pack(get_db(), current_user()["id"], pack_id))


@bp.put("/<int:pack_id>/items")
@require_auth("customer")
def set_item(pack_id: int):
    b = _body()
    return jsonify({"pack": pack_service.set_item(
        get_db(), current_user()["id"], pack_id,
        b.get("product_id"), b.get("quantity"), _exp())})


@bp.delete("/<int:pack_id>/items/<int:product_id>")
@require_auth("customer")
def remove_item(pack_id: int, product_id: int):
    return jsonify({"pack": pack_service.remove_item(
        get_db(), current_user()["id"], pack_id, product_id, _exp())})


@bp.post("/<int:pack_id>/add-to-cart")
@require_auth("customer")
def add_to_cart(pack_id: int):
    return jsonify(pack_service.add_to_cart(get_db(), current_user()["id"], pack_id, _exp()))


@bp.post("/<int:pack_id>/proforma")
@require_auth("customer")
def proforma(pack_id: int):
    b = _body()
    org_id = b.get("organization_id")
    if org_id is not None and (isinstance(org_id, bool) or not isinstance(org_id, int)):
        raise ValidationError("شناسه سازمان نامعتبر است")
    return jsonify(pack_service.create_proforma(
        get_db(), current_user()["id"], pack_id, b.get("message", ""), org_id)), 201
