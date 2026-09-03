"""Organization admin API.

Every route is scoped by `<int:org_id>` and guarded by `require_org_role`,
which resolves the caller's membership of *that* organization. There is no
route on which an organization id is optional.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import (
    client_ip,
    current_membership,
    current_user,
    get_db,
    get_settings,
    require_auth,
    require_org_role,
)
from app.core.errors import ValidationError
from app.services import (
    credit_service,
    membership_service,
    organization_service,
)

bp = Blueprint("organizations", __name__, url_prefix="/api/v1")

ADMIN = ("organization_admin",)
FINANCE = ("organization_admin", "organization_finance")
ANY_MEMBER = ()  # any active membership


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    return body


def _exp() -> int:
    return get_settings().currency_exponent


def _int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(f"پارامتر {name} باید عدد باشد") from exc


def _idempotency_key() -> str:
    return request.headers.get("Idempotency-Key", "")


# ------------------------------------------------------------ platform admin
@bp.post("/admin/organizations")
@require_auth("admin")
def create_organization():
    """Creating an organization is a platform-admin action in Phase 2.

    Self-service organization signup is NOT implemented.
    """
    org = organization_service.create_organization(
        get_db(), actor_user_id=current_user()["id"], payload=_body(), ip_address=client_ip()
    )
    return jsonify({"organization": org}), 201


@bp.get("/admin/organizations")
@require_auth("admin")
def list_all_organizations():
    rows = get_db().query("SELECT id FROM organizations ORDER BY id DESC")
    return jsonify({
        "items": [
            organization_service.get_organization(
                get_db(), organization_id=int(r["id"]), exponent=_exp()
            )
            for r in rows
        ]
    })


# ------------------------------------------------------------------ employee
@bp.get("/organizations")
@require_auth()
def my_organizations():
    """Only organizations the caller belongs to."""
    return jsonify({
        "items": organization_service.list_organizations_for_user(
            get_db(), user_id=current_user()["id"], exponent=_exp()
        )
    })


# -------------------------------------------------------------- organization
@bp.get("/organizations/<int:org_id>")
@require_org_role(*ANY_MEMBER)
def get_organization(org_id: int):
    return jsonify({
        "organization": organization_service.get_organization(
            get_db(), organization_id=org_id, exponent=_exp()
        ),
        "membership": current_membership(),
    })


@bp.patch("/organizations/<int:org_id>")
@require_org_role(*ADMIN)
def update_organization(org_id: int):
    return jsonify({
        "organization": organization_service.update_organization(
            get_db(), organization_id=org_id, actor_user_id=current_user()["id"],
            payload=_body(), ip_address=client_ip(),
        )
    })


@bp.get("/organizations/<int:org_id>/summary")
@require_org_role(*FINANCE)
def summary(org_id: int):
    return jsonify(organization_service.organization_summary(
        get_db(), organization_id=org_id, exponent=_exp()
    ))


# ------------------------------------------------------------------- members
@bp.get("/organizations/<int:org_id>/members")
@require_org_role(*FINANCE)
def list_members(org_id: int):
    return jsonify(membership_service.list_members(get_db(), organization_id=org_id))


@bp.post("/organizations/<int:org_id>/members")
@require_org_role(*ADMIN)
def add_member(org_id: int):
    body = _body()
    member = membership_service.add_member(
        get_db(), organization_id=org_id, actor_user_id=current_user()["id"],
        email=body.get("email", ""), role=body.get("role", "employee"),
        employee_code=body.get("employee_code"), department=body.get("department"),
        status=body.get("status", "active"), ip_address=client_ip(),
    )
    return jsonify({"member": member}), 201


@bp.patch("/organizations/<int:org_id>/members/<int:membership_id>")
@require_org_role(*ADMIN)
def update_member(org_id: int, membership_id: int):
    body = _body()
    return jsonify({
        "member": membership_service.update_member(
            get_db(), organization_id=org_id, membership_id=membership_id,
            actor_user_id=current_user()["id"], role=body.get("role"),
            status=body.get("status"), ip_address=client_ip(),
        )
    })


# ------------------------------------------------------------------- credit
@bp.post("/organizations/<int:org_id>/credit-allocations")
@require_org_role(*FINANCE)
def allocate_credit(org_id: int):
    body = _body()
    created, allocation = credit_service.allocate_credit(
        get_db(), organization_id=org_id, actor_user_id=current_user()["id"],
        membership_id=body.get("membership_id"),
        amount_minor=body.get("amount_minor"),
        idempotency_key=_idempotency_key(),
        expires_at=body.get("expires_at"), valid_from=body.get("valid_from"),
        category_slugs=body.get("category_slugs"),
        per_transaction_limit_minor=body.get("per_transaction_limit_minor"),
        period_limit_minor=body.get("period_limit_minor"),
        note=body.get("note"), ip_address=client_ip(),
    )
    return jsonify({"allocation": allocation, "created": created}), (201 if created else 200)


@bp.get("/organizations/<int:org_id>/credit-allocations")
@require_org_role(*FINANCE)
def list_allocations(org_id: int):
    return jsonify(credit_service.list_allocations(
        get_db(), organization_id=org_id, exponent=_exp()
    ))


@bp.post("/organizations/<int:org_id>/credit-allocations/<int:allocation_id>/adjust")
@require_org_role(*FINANCE)
def adjust_allocation(org_id: int, allocation_id: int):
    body = _body()
    return jsonify({
        "allocation": credit_service.adjust_allocation(
            get_db(), organization_id=org_id, allocation_id=allocation_id,
            actor_user_id=current_user()["id"], delta_minor=body.get("delta_minor"),
            note=body.get("note", ""), ip_address=client_ip(),
        )
    })


@bp.post("/organizations/<int:org_id>/credit-allocations/<int:allocation_id>/revoke")
@require_org_role(*FINANCE)
def revoke_allocation(org_id: int, allocation_id: int):
    return jsonify({
        "allocation": credit_service.revoke_allocation(
            get_db(), organization_id=org_id, allocation_id=allocation_id,
            actor_user_id=current_user()["id"], ip_address=client_ip(),
        )
    })


@bp.get("/organizations/<int:org_id>/credit-transactions")
@require_org_role(*FINANCE)
def credit_transactions(org_id: int):
    return jsonify(credit_service.list_credit_transactions(
        get_db(), organization_id=org_id, page=_int_arg("page", 1),
        page_size=_int_arg("page_size", 25), exponent=_exp(),
    ))


@bp.get("/organizations/<int:org_id>/orders")
@require_org_role(*FINANCE)
def organization_orders(org_id: int):
    return jsonify(organization_service.list_organization_orders(
        get_db(), organization_id=org_id, page=_int_arg("page", 1),
        page_size=_int_arg("page_size", 20), exponent=_exp(),
    ))
