"""Legal texts, terms acceptance and statutory withdrawal (انصراف ۷ روزه)."""
from flask import Blueprint, jsonify, request

from app.core.deps import client_ip, current_user, get_db, require_auth
from app.core.errors import ValidationError
from app.services import consumer_rights_service as rights

bp = Blueprint("consumer_rights", __name__, url_prefix="/api/v1")


@bp.get("/legal/terms")
def terms():
    with get_db().read_transaction() as conn:
        return jsonify({"documents": rights.current_documents(conn),
                        "withdrawal": {"working_days": rights.WITHDRAWAL_WORKING_DAYS,
                                       "refund_due_days": rights.refund_due_days(),
                                       "exempt": rights.EXEMPT_FA}})


@bp.post("/me/terms-acceptances")
@require_auth()
def accept():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not isinstance(d.get("doc_key"), str) or not isinstance(d.get("version"), str):
        raise ValidationError("doc_key و version الزامی است")
    with get_db().write_transaction() as conn:
        return jsonify({"acceptance": rights.record_acceptance(
            conn, user_id=current_user()["id"], doc_key=d["doc_key"], version=d["version"], context="explicit",
            ip=client_ip(), user_agent=request.headers.get("User-Agent"))}), 201


@bp.get("/me/orders/<order_number>/withdrawal")
@require_auth()
def window(order_number: str):
    with get_db().read_transaction() as conn:
        return jsonify(rights.withdrawal_window(conn, user_id=current_user()["id"], order_number=order_number))


@bp.post("/me/orders/<order_number>/withdrawal")
@require_auth()
def withdraw(order_number: str):
    d = request.get_json(silent=True)
    if d is not None and not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    with get_db().write_transaction() as conn:
        return jsonify({"withdrawal": rights.request_withdrawal(conn, user_id=current_user()["id"],
                                                                order_number=order_number, data=d or {})}), 201
