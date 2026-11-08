"""Phase 3 — organization orders, buying controls, brand zone and pre-orders."""
from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import PermissionError_, ValidationError
from app.services import brand_service as brands
from app.services import org_order_service as svc
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("org_brands", __name__)


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d


def _uid() -> int:
    return current_user()["id"]


def _my_supplier(conn) -> int:
    sid = current_supplier_id(conn, _uid())
    if not sid:
        raise PermissionError_("حساب فروشنده برای این کاربر یافت نشد")
    return sid


# ── organization orders ───────────────────────────────────────────────────────
@bp.post("/api/v1/orgs/<int:org_id>/orders")
@require_auth()
def create_org_order(org_id: int):
    with get_db().write_transaction() as conn:
        status, body = svc.convert_purchase_request(conn, organization_id=org_id, actor_user_id=_uid(),
                                                    data=_body(), idempotency_key=request.headers.get("Idempotency-Key"))
    return jsonify({"order": body}), status


@bp.get("/api/v1/orgs/<int:org_id>/orders")
@require_auth()
def list_org_orders(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.list_org_orders(conn, organization_id=org_id, actor_user_id=_uid())})


@bp.get("/api/v1/orgs/<int:org_id>/orders/<int:order_id>")
@require_auth()
def get_org_order(org_id: int, order_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"order": svc.get_org_order(conn, organization_id=org_id, order_id=order_id, actor_user_id=_uid())})


@bp.get("/api/v1/orgs/<int:org_id>/orders/<int:order_id>/invoice")
@require_auth()
def org_order_invoice(org_id: int, order_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"invoice": svc.invoice(conn, organization_id=org_id, order_id=order_id, actor_user_id=_uid())})


@bp.post("/api/v1/orgs/<int:org_id>/orders/<int:order_id>/confirm-payment")
@require_auth()
def confirm_org_payment(org_id: int, order_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"order": svc.confirm_cash_payment(conn, organization_id=org_id, order_id=order_id,
                                                          actor_user_id=_uid(), reference=_body().get("reference"))})


@bp.post("/api/v1/orgs/<int:org_id>/orders/<int:order_id>/cancel")
@require_auth()
def cancel_org_order(org_id: int, order_id: int):
    body = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        return jsonify({"order": svc.cancel_org_order(conn, organization_id=org_id, order_id=order_id,
                                                      actor_user_id=_uid(), reason=body.get("reason"))})


@bp.get("/api/v1/orgs/<int:org_id>/statement")
@require_auth()
def org_statement(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(svc.monthly_statement(conn, organization_id=org_id, actor_user_id=_uid(),
                                             month=request.args.get("month")))


# ── approval rules / submit / approve ─────────────────────────────────────────
@bp.get("/api/v1/orgs/<int:org_id>/approval-rules")
@require_auth()
def list_rules(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.list_rules(conn, organization_id=org_id, actor_user_id=_uid())})


@bp.post("/api/v1/orgs/<int:org_id>/approval-rules")
@require_auth()
def create_rule(org_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"rule": svc.create_rule(conn, organization_id=org_id, actor_user_id=_uid(), data=_body())}), 201


@bp.delete("/api/v1/orgs/<int:org_id>/approval-rules/<int:rule_id>")
@require_auth()
def deactivate_rule(org_id: int, rule_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"rule": svc.deactivate_rule(conn, organization_id=org_id, actor_user_id=_uid(), rule_id=rule_id)})


@bp.post("/api/v1/orgs/<int:org_id>/purchase-requests/<int:pr_id>/submit-with-rules")
@require_auth()
def submit_with_rules(org_id: int, pr_id: int):
    with get_db().write_transaction() as conn:
        return jsonify(svc.submit_with_rules(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=_uid()))


@bp.post("/api/v1/orgs/<int:org_id>/purchase-requests/<int:pr_id>/rule-approvals")
@require_auth()
def rule_approval(org_id: int, pr_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        return jsonify(svc.approve_with_rules(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=_uid(),
                                              action=d.get("action"), reason=d.get("reason")))


@bp.put("/api/v1/orgs/<int:org_id>/purchase-requests/<int:pr_id>/po-reference")
@require_auth()
def po_reference(org_id: int, pr_id: int):
    with get_db().write_transaction() as conn:
        return jsonify(svc.set_po_reference(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=_uid(),
                                            po_reference=_body().get("po_reference")))


# ── buying policy / guided buying ─────────────────────────────────────────────
@bp.get("/api/v1/orgs/<int:org_id>/buying-policy")
@require_auth()
def get_policy(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"policy": svc.read_buying_policy(conn, organization_id=org_id, actor_user_id=_uid())})


@bp.put("/api/v1/orgs/<int:org_id>/buying-policy")
@require_auth()
def put_policy(org_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"policy": svc.update_buying_policy(conn, organization_id=org_id, actor_user_id=_uid(),
                                                           data=_body())})


@bp.get("/api/v1/orgs/<int:org_id>/preferred-sellers")
@require_auth()
def list_preferred(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(svc.list_preferred(conn, organization_id=org_id, actor_user_id=_uid()))


@bp.post("/api/v1/orgs/<int:org_id>/preferred-sellers")
@require_auth()
def add_preferred(org_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"item": svc.add_preferred(conn, organization_id=org_id, actor_user_id=_uid(), data=_body())}), 201


@bp.delete("/api/v1/orgs/<int:org_id>/preferred-sellers/<int:pref_id>")
@require_auth()
def remove_preferred(org_id: int, pref_id: int):
    with get_db().write_transaction() as conn:
        svc.remove_preferred(conn, organization_id=org_id, actor_user_id=_uid(), preferred_id=pref_id)
    return jsonify({"ok": True})


@bp.get("/api/v1/orgs/<int:org_id>/preferred-sellers/check")
@require_auth()
def check_preferred(org_id: int):
    raw = request.args.get("offer_id", "")
    if not raw.isdigit():
        raise ValidationError("offer_id نامعتبر است")
    with get_db().read_transaction() as conn:
        return jsonify(svc.check_offer(conn, organization_id=org_id, actor_user_id=_uid(), offer_id=int(raw)))


# ── brand zone ────────────────────────────────────────────────────────────────
@bp.get("/api/v1/brands")
def list_brands():
    with get_db().read_transaction() as conn:
        return jsonify({"items": brands.list_brands(conn)})


@bp.get("/api/v1/brands/<int:supplier_id>")
def brand_page(supplier_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(brands.brand_page(conn, supplier_id))


@bp.get("/api/v1/supplier/brand-registration")
@require_auth()
def my_registration():
    with get_db().read_transaction() as conn:
        return jsonify(brands.my_registrations(conn, supplier_id=_my_supplier(conn)))


@bp.post("/api/v1/supplier/brand-registration")
@require_auth()
def submit_registration():
    with get_db().write_transaction() as conn:
        return jsonify({"registration": brands.submit_registration(conn, supplier_id=_my_supplier(conn), user_id=_uid(),
                                                                   data=_body())}), 201


@bp.put("/api/v1/supplier/offers/<int:offer_id>/preorder")
@require_auth()
def set_preorder_window(offer_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"window": brands.set_window(conn, supplier_id=_my_supplier(conn), user_id=_uid(),
                                                    offer_id=offer_id, data=_body())})


@bp.post("/api/v1/supplier/preorders/<int:preorder_id>/convert")
@require_auth()
def supplier_convert(preorder_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"order": brands.convert(conn, preorder_id=preorder_id, actor_user_id=_uid(),
                                                supplier_id=_my_supplier(conn))})


@bp.get("/api/v1/admin/brand-registrations")
@require_auth("admin")
def admin_registrations():
    with get_db().read_transaction() as conn:
        return jsonify({"items": brands.admin_list(conn, status=request.args.get("status", "pending"))})


@bp.post("/api/v1/admin/brand-registrations/<int:reg_id>/review")
@require_auth("admin")
def admin_review(reg_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"registration": brands.review(conn, registration_id=reg_id, admin_user_id=_uid(),
                                                      decision=d.get("decision"), note=d.get("note"))})


# ── pre-orders ────────────────────────────────────────────────────────────────
@bp.post("/api/v1/preorders")
@require_auth()
def create_preorder():
    with get_db().write_transaction() as conn:
        status, body = brands.create_preorder(conn, user_id=_uid(), data=_body(),
                                              idempotency_key=request.headers.get("Idempotency-Key"))
    return jsonify({"preorder": body}), status


@bp.get("/api/v1/preorders")
@require_auth()
def my_preorders():
    with get_db().read_transaction() as conn:
        return jsonify({"items": brands.my_preorders(conn, user_id=_uid())})


@bp.post("/api/v1/preorders/<int:preorder_id>/cancel")
@require_auth()
def cancel_preorder(preorder_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"preorder": brands.cancel(conn, preorder_id=preorder_id, user_id=_uid())})


@bp.post("/api/v1/admin/preorders/<int:preorder_id>/deposit")
@require_auth("admin")
def admin_deposit(preorder_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"preorder": brands.confirm_deposit(conn, preorder_id=preorder_id, admin_user_id=_uid(),
                                                           reference=_body().get("reference"))})


@bp.post("/api/v1/admin/preorders/<int:preorder_id>/convert")
@require_auth("admin")
def admin_convert(preorder_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"order": brands.convert(conn, preorder_id=preorder_id, actor_user_id=_uid(), supplier_id=None)})


@bp.post("/api/v1/admin/preorders/<int:preorder_id>/balance")
@require_auth("admin")
def admin_balance(preorder_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"order": brands.confirm_balance(conn, preorder_id=preorder_id, admin_user_id=_uid(),
                                                        reference=_body().get("reference"))})
