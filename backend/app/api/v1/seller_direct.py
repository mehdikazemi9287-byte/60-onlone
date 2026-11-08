"""Bring your own customer: seller invite links with 0% commission on the buyers they bring.

POST /api/v1/supplier/direct-invites            seller makes an invite link
GET  /api/v1/supplier/direct-customers          seller's linked customers
GET  /api/v1/direct-invites/<code>              public: whose invite is this
POST /api/v1/me/direct-invites/<code>/claim     buyer accepts
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import PermissionError_
from app.services import seller_direct_service as svc
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("seller_direct", __name__, url_prefix="/api/v1")


def _supplier(conn) -> int:
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب فروشنده یافت نشد")
    return sid


@bp.post("/supplier/direct-invites")
@require_auth()
def create_invite():
    with get_db().write_transaction() as conn:
        out = svc.create_invite(conn, supplier_id=_supplier(conn), actor_user_id=current_user()["id"],
                                note=(request.get_json(silent=True) or {}).get("note"))
    return jsonify(out), 201


@bp.get("/supplier/direct-customers")
@require_auth()
def my_customers():
    with get_db().read_transaction() as conn:
        return jsonify(svc.my_customers(conn, supplier_id=_supplier(conn)))


@bp.get("/direct-invites/<code>")
def invite_info(code: str):
    with get_db().read_transaction() as conn:
        return jsonify(svc.invite_info(conn, code=code))


@bp.post("/me/direct-invites/<code>/claim")
@require_auth()
def claim(code: str):
    with get_db().write_transaction() as conn:
        return jsonify(svc.claim(conn, code=code, user_id=current_user()["id"]))
