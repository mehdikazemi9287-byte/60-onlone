"""Customer address book: /api/v1/me/addresses (owner-scoped)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.services import address_book_service

bp = Blueprint("addresses", __name__, url_prefix="/api/v1/me/addresses")


@bp.get("")
@require_auth()
def list_addresses():
    with get_db().read_transaction() as conn:
        return jsonify({"items": address_book_service.list_for_user(conn, current_user()["id"]),
                        "max": address_book_service.MAX_ADDRESSES})


@bp.post("")
@require_auth()
def create_address():
    with get_db().write_transaction() as conn:
        return jsonify({"address": address_book_service.create(
            conn, user_id=current_user()["id"], data=request.get_json(silent=True))}), 201


@bp.patch("/<int:address_id>")
@require_auth()
def update_address(address_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"address": address_book_service.update(
            conn, user_id=current_user()["id"], address_id=address_id, data=request.get_json(silent=True))})


@bp.post("/<int:address_id>/default")
@require_auth()
def default_address(address_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"address": address_book_service.set_default(
            conn, user_id=current_user()["id"], address_id=address_id)})


@bp.delete("/<int:address_id>")
@require_auth()
def delete_address(address_id: int):
    with get_db().write_transaction() as conn:
        address_book_service.delete(conn, user_id=current_user()["id"], address_id=address_id)
        return jsonify({"items": address_book_service.list_for_user(conn, current_user()["id"])})
