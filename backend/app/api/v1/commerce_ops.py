"""Notifications, retail returns and employee benefit programs."""
from flask import Blueprint, jsonify, request

from app.api.v1.enterprise_procurement import _idempotent
from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ValidationError
from app.services import commerce_ops_service as ops

bp = Blueprint("commerce_ops", __name__, url_prefix="/api/v1")


def _body() -> dict:
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    return data


@bp.get("/me/notifications")
@require_auth()
def my_notifications():
    with get_db().read_transaction() as conn:
        return jsonify(ops.notifications(conn, current_user()["id"]))


@bp.post("/me/notifications/read")
@require_auth()
def read_notifications():
    nid = _body().get("id")
    with get_db().write_transaction() as conn:
        ops.mark_read(conn, current_user()["id"], nid if isinstance(nid, int) else None)
        return jsonify(ops.notifications(conn, current_user()["id"]))


@bp.get("/orders/<order_number>/returns")
@require_auth()
def order_returns(order_number: str):
    with get_db().read_transaction() as conn:
        return jsonify({"items": ops.returns_for_order(conn, user_id=current_user()["id"], order_number=order_number)})


@bp.post("/orders/<order_number>/returns")
@require_auth()
def order_return_create(order_number: str):
    data = _body()
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify({"return": ops.request_return(conn, user_id=current_user()["id"],
                                                                               order_number=order_number, data=data)}))


@bp.post("/returns/<int:return_id>/cancel")
@require_auth()
def order_return_cancel(return_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"return": ops.cancel_return(conn, user_id=current_user()["id"], return_id=return_id)})


@bp.get("/admin/returns")
@require_auth("admin")
def admin_returns():
    with get_db().read_transaction() as conn:
        return jsonify({"items": ops.admin_returns(conn, request.args.get("status") or None)})


@bp.post("/admin/returns/<int:return_id>/<action>")
@require_auth("admin")
def admin_return_action(return_id: int, action: str):
    data = _body()
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify({"return": ops.admin_transition(conn, actor=current_user()["id"], return_id=return_id,
                                                                                  action=action, data=data)}))


@bp.get("/orgs/<int:org_id>/benefits")
@require_auth()
def org_benefits(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"items": ops.org_programs(conn, org=org_id, actor=current_user()["id"])})


@bp.post("/orgs/<int:org_id>/benefits")
@require_auth()
def org_benefit_create(org_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify({"program": ops.create_program(conn, org=org_id, actor=current_user()["id"], data=data)}))


@bp.post("/orgs/<int:org_id>/benefits/<int:program_id>/status")
@require_auth()
def org_benefit_status(org_id: int, program_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"program": ops.set_program_status(conn, org=org_id, actor=current_user()["id"], program_id=program_id,
                                                          status=data.get("status"))})


@bp.post("/orgs/<int:org_id>/benefits/<int:program_id>/purchase-request")
@require_auth()
def org_benefit_request(org_id: int, program_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify(ops.to_purchase_request(conn, org=org_id, actor=current_user()["id"], program_id=program_id,
                                                                        destination=data.get("destination"))))


@bp.get("/me/benefits")
@require_auth()
def my_benefits():
    with get_db().read_transaction() as conn:
        return jsonify({"items": ops.my_programs(conn, user_id=current_user()["id"])})


@bp.post("/me/benefits/<int:program_id>/select")
@require_auth()
def my_benefit_select(program_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"program": ops.select(conn, user_id=current_user()["id"], program_id=program_id, pack_slug=data.get("pack_slug"))})
