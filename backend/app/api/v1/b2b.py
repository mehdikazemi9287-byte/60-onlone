"""حساب‌های سازمانی و فروشگاهی (شروع سازمانی).

  POST /api/v1/b2b/applications                      public: request a business account
  GET  /api/v1/admin/b2b/accounts?kind=              admin: every business account with credit status
  GET  /api/v1/admin/b2b/accounts/<id>
  POST /api/v1/admin/b2b/accounts                    admin: one-step onboarding (Idempotency-Key)
  POST /api/v1/admin/b2b/accounts/<id>/invites       admin: invite more people by mobile number
  GET  /api/v1/admin/b2b/applications?status=new
  POST /api/v1/admin/b2b/applications/<id>/reject
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import client_ip, current_user, get_db, require_auth
from app.core.errors import ValidationError
from app.services import b2b_service as b2b

bp = Blueprint("b2b", __name__, url_prefix="/api/v1")


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنهٔ درخواست باید JSON باشد")
    return d


@bp.post("/b2b/applications")
def apply():
    with get_db().write_transaction() as conn:
        return jsonify(b2b.submit_application(conn, data=_body(), ip_address=client_ip())), 201


@bp.get("/admin/b2b/accounts")
@require_auth("admin")
def accounts():
    with get_db().read_transaction() as conn:
        return jsonify({"items": b2b.overview(conn, buyer_kind=request.args.get("kind") or None)})


@bp.get("/admin/b2b/accounts/<int:org_id>")
@require_auth("admin")
def account(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(b2b.account(conn, org_id))


@bp.post("/admin/b2b/accounts")
@require_auth("admin")
def onboard():
    with get_db().write_transaction() as conn:
        created, acc = b2b.onboard(conn, actor_user_id=current_user()["id"], data=_body(),
                                   idempotency_key=request.headers.get("Idempotency-Key", ""), ip_address=client_ip())
    return jsonify({"account": acc, "created": created}), (201 if created else 200)


@bp.post("/admin/b2b/accounts/<int:org_id>/invites")
@require_auth("admin")
def add_invite(org_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        b2b.account(conn, org_id)  # 404 if missing
        return jsonify(b2b.invite(conn, organization_id=org_id, phone=d.get("phone"), role=d.get("role", "employee"),
                                  actor_user_id=current_user()["id"])), 201


@bp.get("/admin/b2b/applications")
@require_auth("admin")
def applications():
    with get_db().read_transaction() as conn:
        return jsonify({"items": b2b.list_applications(conn, status=request.args.get("status", "new"))})


@bp.post("/admin/b2b/applications/<int:app_id>/reject")
@require_auth("admin")
def reject(app_id: int):
    with get_db().write_transaction() as conn:
        return jsonify(b2b.reject_application(conn, application_id=app_id, actor_user_id=current_user()["id"],
                                              note=_body().get("note")))
