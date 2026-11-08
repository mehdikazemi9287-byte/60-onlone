"""Access administration, payment-policy lifecycle and the operations workbench API."""
from flask import Blueprint, jsonify, request

from app.api.v1.enterprise_procurement import _idempotent
from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ValidationError
from app.services import access_admin_service as access
from app.services import enterprise_procurement_service as ent
from app.services import organization_operations_service as ops
from app.services import payment_policy_service as policy

bp = Blueprint("access_admin", __name__, url_prefix="/api/v1")


def _body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return data


def _write(fn):
    """Run a mutation in one transaction, honouring Idempotency-Key."""
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify(fn(conn)))


# ── Platform admin: access console ──

@bp.get("/admin/access")
@require_auth("admin")
def access_overview():
    with get_db().read_transaction() as conn:
        return jsonify(access.overview(conn) | {"policy_queue": policy.review_queue(conn)})


@bp.get("/admin/access/users")
@require_auth("admin")
def access_users():
    with get_db().read_transaction() as conn:
        return jsonify({"items": access.find_users(conn, request.args.get("q"))})


@bp.patch("/admin/access/organizations/<int:org_id>/members/<int:membership_id>")
@require_auth("admin")
def access_member(org_id: int, membership_id: int):
    data = _body()
    return _write(lambda c: {"membership": access.change_member(c, org=org_id, membership_id=membership_id,
                                                                actor=current_user()["id"], data=data)})


@bp.post("/admin/access/organizations/<int:org_id>/operations/<action>")
@require_auth("admin")
def access_operations(org_id: int, action: str):
    data = _body()
    fn = {"grant": access.grant_operations, "revoke": access.revoke_operations}.get(action)
    if not fn:
        raise ValidationError("اقدام نامعتبر است")
    return _write(lambda c: {"grant": fn(c, org=org_id, actor=current_user()["id"], data=data)})


@bp.post("/admin/access/suppliers/<int:supplier_id>/users/<action>")
@require_auth("admin")
def access_supplier_users(supplier_id: int, action: str):
    data = _body()
    fn = {"grant": access.grant_supplier_user, "revoke": access.revoke_supplier_user}.get(action)
    if not fn:
        raise ValidationError("اقدام نامعتبر است")
    return _write(lambda c: {"supplier_user": fn(c, supplier_id=supplier_id, actor=current_user()["id"], data=data)})


# ── Payment policy lifecycle ──

@bp.get("/organizations/<int:org_id>/payment-policies")
@require_auth()
def policies(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(policy.list_for_org(conn, org=org_id, actor=current_user()))


@bp.post("/organizations/<int:org_id>/payment-policies")
@require_auth()
def policy_create(org_id: int):
    data = _body()
    return _write(lambda c: {"policy": policy.create(c, org=org_id, actor=current_user(), data=data)})


@bp.put("/organizations/<int:org_id>/payment-policies/<int:draft_id>")
@require_auth()
def policy_edit(org_id: int, draft_id: int):
    data = _body()
    return _write(lambda c: {"policy": policy.edit(c, org=org_id, draft_id=draft_id, actor=current_user(), data=data)})


@bp.post("/organizations/<int:org_id>/payment-policies/<int:draft_id>/<action>")
@require_auth()
def policy_action(org_id: int, draft_id: int, action: str):
    data = _body()
    u = current_user()
    run = {
        "submit": lambda c: policy.submit(c, org=org_id, draft_id=draft_id, actor=u),
        "withdraw": lambda c: policy.withdraw(c, org=org_id, draft_id=draft_id, actor=u, note=data.get("note")),
        "review": lambda c: policy.review(c, org=org_id, draft_id=draft_id, actor=u, action=data.get("action"),
                                          note=data.get("note")),
    }.get(action)
    if not run:
        raise ValidationError("اقدام نامعتبر است")
    return _write(lambda c: {"policy": run(c)})


# ── Operations workbench ──

@bp.get("/internal/operations/queue")
@require_auth()
def operations_queue():
    org = request.args.get("org")
    try:
        org = int(org) if org else None
    except ValueError:
        raise ValidationError("سازمان نامعتبر است")
    with get_db().read_transaction() as conn:
        return jsonify(ops.queue(conn, current_user()["id"], org=org, q=request.args.get("q"),
                                 stage=request.args.get("stage") or None, ops_status=request.args.get("ops_status") or None,
                                 assignee=request.args.get("assignee") or None))


@bp.get("/internal/organizations/<int:org_id>/requests/<int:pr_id>/workspace")
@require_auth()
def operations_workspace(org_id: int, pr_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(ent.internal_workspace(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=current_user()["id"]))
