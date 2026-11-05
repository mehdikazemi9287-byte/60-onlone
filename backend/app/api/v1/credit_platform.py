"""Phase 4 — اعتبار و سوپراپ: credit contracts, statements, welfare plans, installments,
seller advances and the group-platform summary. Blueprint name: "credit_platform"."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.adapters.group_platform import get_group_platform
from app.core.deps import current_membership, current_user, get_db, require_auth, require_org_role
from app.core.errors import PermissionError_, ValidationError
from app.services import (
    credit_contract_service as contracts,
    installment_service as installments,
    seller_advance_service as advances,
    welfare_wallet_service as welfare,
)
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("credit_platform", __name__, url_prefix="/api/v1")

ADMIN = ("organization_admin",)
FINANCE = ("organization_admin", "organization_finance")


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    return body


def _key() -> str:
    return request.headers.get("Idempotency-Key", "")


def _created(created: bool, payload: dict):
    return jsonify(payload), (201 if created else 200)


def _supplier(conn) -> int:
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب فروشنده برای این کاربر یافت نشد")
    return sid


# ------------------------------------------------- admin: credit contracts
@bp.post("/admin/credit-contracts")
@require_auth("admin")
def admin_create_contract():
    body = _body()
    org_id = body.get("organization_id")
    if isinstance(org_id, bool) or not isinstance(org_id, int):
        raise ValidationError("organization_id لازم است")
    with get_db().write_transaction() as conn:
        created, contract = contracts.create_contract(conn, organization_id=org_id, payload=body,
                                                      actor_user_id=current_user()["id"], idempotency_key=_key())
    return _created(created, {"contract": contract})


@bp.get("/admin/credit-contracts")
@require_auth("admin")
def admin_list_contracts():
    with get_db().read_transaction() as conn:
        return jsonify({"contracts": contracts.list_contracts(conn)})


@bp.post("/admin/credit-contracts/<int:contract_id>/<action>")
@require_auth("admin")
def admin_contract_action(contract_id: int, action: str):
    actor = current_user()["id"]
    with get_db().write_transaction() as conn:
        if action == "freeze":
            return jsonify({"contract": contracts.freeze(conn, contract_id, actor_user_id=actor)})
        if action == "unfreeze":
            return jsonify({"contract": contracts.unfreeze(conn, contract_id, actor_user_id=actor)})
        if action == "close":
            return jsonify({"contract": contracts.close(conn, contract_id, actor_user_id=actor)})
        if action == "payments":
            body = _body()
            created, result = contracts.record_payment(
                conn, contract_id, amount_minor=body.get("amount_minor"), idempotency_key=_key(),
                actor_user_id=actor, received_at=body.get("received_at"),
                external_reference=body.get("external_reference"), note=body.get("note"))
            return _created(created, result)
    raise ValidationError("عملیات نامعتبر است", details={"action": ["freeze", "unfreeze", "close", "payments"]})


@bp.post("/admin/credit-cycle/run")
@require_auth("admin")
def admin_run_cycle():
    with get_db().write_transaction() as conn:
        return jsonify({"statements": contracts.run_weekly_statements(conn),
                        "overdue": contracts.enforce_overdue(conn),
                        "installments_late": installments.mark_late(conn)})


# ------------------------------------------------ organization: contract
@bp.get("/orgs/<int:org_id>/credit-contract")
@require_org_role(*FINANCE)
def org_contract(org_id: int):
    with get_db().read_transaction() as conn:
        row = contracts.live_contract(conn, org_id)
        return jsonify({"contract": contracts.contract_dict(conn, row) if row else None})


@bp.get("/orgs/<int:org_id>/credit-contracts")
@require_org_role(*FINANCE)
def org_contracts(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"contracts": contracts.list_contracts(conn, org_id)})


@bp.get("/orgs/<int:org_id>/statements")
@require_org_role(*FINANCE)
def org_statements(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"statements": contracts.list_statements(conn, org_id)})


@bp.get("/orgs/<int:org_id>/statements/<int:statement_id>")
@require_org_role(*FINANCE)
def org_statement(org_id: int, statement_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"statement": contracts.get_statement(conn, org_id, statement_id)})


# ------------------------------------------------ organization: welfare
@bp.post("/orgs/<int:org_id>/welfare-plans")
@require_org_role(*ADMIN)
def create_welfare_plan(org_id: int):
    with get_db().write_transaction() as conn:
        created, plan = welfare.create_plan(conn, organization_id=org_id, payload=_body(),
                                            actor_user_id=current_user()["id"], idempotency_key=_key())
    return _created(created, {"plan": plan})


@bp.get("/orgs/<int:org_id>/welfare-plans")
@require_org_role(*FINANCE)
def list_welfare_plans(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"plans": welfare.list_plans(conn, org_id)})


@bp.post("/orgs/<int:org_id>/welfare-plans/<int:plan_id>/members")
@require_org_role(*ADMIN)
def add_welfare_member(org_id: int, plan_id: int):
    body = _body()
    with get_db().write_transaction() as conn:
        welfare.add_member(conn, plan_id=plan_id, organization_id=org_id,
                           membership_id=body.get("membership_id"), cap_minor=body.get("cap_minor"))
        return jsonify({"plan": welfare.plan_dict(conn, welfare._plan_row(conn, plan_id))}), 201


@bp.post("/orgs/<int:org_id>/welfare-plans/<int:plan_id>/close")
@require_org_role(*ADMIN)
def close_welfare_plan(org_id: int, plan_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"plan": welfare.close_plan(conn, plan_id=plan_id, organization_id=org_id)})


@bp.post("/orgs/<int:org_id>/welfare-plans/can-spend")
@require_org_role()
def welfare_can_spend(org_id: int):
    """Caller's own membership; platform admins may pass membership_id."""
    body = _body()
    membership_id = current_membership().get("id") or body.get("membership_id")
    lines = body.get("lines")
    if not isinstance(lines, list) or not membership_id:
        raise ValidationError("lines و عضویت لازم است")
    with get_db().read_transaction() as conn:
        return jsonify(welfare.can_spend(conn, int(membership_id), lines))


# ---------------------------------------------------------- installments
@bp.get("/installments/plans")
def installment_plans():
    with get_db().read_transaction() as conn:
        return jsonify({"plans": installments.list_plans(conn)})


@bp.post("/installments/plans")
@require_auth("admin")
def create_installment_plan():
    with get_db().write_transaction() as conn:
        return jsonify({"plan": installments.create_plan(conn, _body())}), 201


@bp.post("/installments/quote")
@require_auth()
def installment_quote():
    body = _body()
    with get_db().read_transaction() as conn:
        return jsonify(installments.quote(conn, plan_id=body.get("plan_id"),
                                          principal_minor=body.get("principal_minor")))


@bp.post("/installments")
@require_auth()
def create_installment():
    body = _body()
    with get_db().write_transaction() as conn:
        created, agreement = installments.create_agreement(
            conn, order_id=body.get("order_id"), plan_id=body.get("plan_id"), actor=current_user(),
            idempotency_key=_key(), supplier_id=body.get("supplier_id"))
    return _created(created, {"installment": agreement})


@bp.get("/installments")
@require_auth()
def my_installments():
    with get_db().read_transaction() as conn:
        return jsonify({"installments": installments.list_for_user(conn, current_user()["id"])})


@bp.get("/installments/<int:agreement_id>")
@require_auth()
def get_installment(agreement_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"installment": installments.get_agreement(
            conn, agreement_id, user=current_user(), supplier_id=current_supplier_id(conn, current_user()["id"]))})


@bp.post("/installments/<int:agreement_id>/schedules/<int:schedule_id>/payments")
@require_auth("admin")
def pay_installment(agreement_id: int, schedule_id: int):
    body = _body()
    with get_db().write_transaction() as conn:
        created, agreement = installments.record_payment(
            conn, agreement_id=agreement_id, schedule_id=schedule_id, amount_minor=body.get("amount_minor"),
            idempotency_key=_key(), actor_user_id=current_user()["id"],
            external_reference=body.get("external_reference"))
    return _created(created, {"installment": agreement})


@bp.post("/installments/<int:agreement_id>/debt-sale")
@require_auth("admin")
def debt_sale(agreement_id: int):
    body = _body()
    with get_db().write_transaction() as conn:
        created, sale = installments.sell_debt(conn, agreement_id=agreement_id,
                                               discount_bps=body.get("discount_bps"), idempotency_key=_key(),
                                               actor_user_id=current_user()["id"])
    return _created(created, {"debt_sale": sale})


# ------------------------------------------------------- seller advances
@bp.get("/supplier/advances")
@require_auth()
def supplier_advances():
    with get_db().read_transaction() as conn:
        sid = _supplier(conn)
        return jsonify({"eligibility": advances.eligibility(conn, sid), "entries": advances.list_entries(conn, sid)})


@bp.post("/supplier/advances")
@require_auth()
def request_supplier_advance():
    body = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        sid = _supplier(conn)
        created, entry = advances.request_advance(conn, supplier_id=sid, idempotency_key=_key(),
                                                  actor_user_id=current_user()["id"],
                                                  amount_minor=body.get("amount_minor"))
        payload = {"advance": entry, "eligibility": advances.eligibility(conn, sid)}
    return _created(created, payload)


# ---------------------------------------------------------- group platform
@bp.get("/me/group")
@require_auth()
def my_group():
    with get_db().read_transaction() as conn:
        return jsonify(get_group_platform().summary(conn, current_user()["id"]))


@bp.post("/me/group")
@require_auth()
def enroll_group():
    body = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        account = get_group_platform().enroll(conn, current_user()["id"], body.get("businesses"))
    return jsonify({"group_account": account}), 201
