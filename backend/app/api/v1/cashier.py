"""Phase 2 — cashier quotes, multi-seller baskets, recurring lists and their admin rules."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import authenticate_request, current_user, get_db, require_auth
from app.core.errors import ValidationError
from app.services import cashier_service as cashier
from app.services import pack_builder_service, recurring_service

bp = Blueprint("cashier", __name__, url_prefix="/api/v1")


def _body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    return body


def _optional_user() -> dict | None:
    """A bad token is an error; no token is an anonymous retail quote."""
    if not request.headers.get("Authorization"):
        return None
    authenticate_request()
    return current_user()


def _ctx(conn, body: dict, user: dict | None) -> dict:
    use_credit = body.get("use_credit", True)
    if not isinstance(use_credit, bool):
        raise ValidationError("use_credit باید true یا false باشد")
    codes = body.get("coupon_codes") or []
    if not isinstance(codes, list):
        raise ValidationError("کدهای تخفیف باید فهرست باشد")
    return cashier.buyer_context(
        conn, user_id=user["id"] if user else None, organization_id=body.get("organization_id"),
        redeem_coins=body.get("redeem_coins", 0), coupon_codes=codes, use_credit=use_credit,
        platform_admin=bool(user and user["role"] == "admin"))


# ── cashier quotes ──

@bp.post("/cashier/quote")
def cashier_quote():
    body, user = _body(), _optional_user()
    with get_db().read_transaction() as conn:
        return jsonify({"quote": cashier.quote(conn, body.get("items"), _ctx(conn, body, user))})


@bp.post("/cashier/basket")
def cashier_basket():
    """Pack builder / جهیزیه‌ساز / gift basket: items from several shops, split per seller."""
    body, user = _body(), _optional_user()
    with get_db().read_transaction() as conn:
        return jsonify({"quote": pack_builder_service.basket_quote(conn, body.get("items"), _ctx(conn, body, user))})


# ── recurring delivery lists ──

@bp.get("/me/recurring")
@require_auth()
def recurring_list():
    with get_db().read_transaction() as conn:
        return jsonify({"items": recurring_service.list_mine(conn, user_id=current_user()["id"])})


@bp.post("/me/recurring")
@require_auth()
def recurring_create():
    with get_db().write_transaction() as conn:
        return jsonify({"list": recurring_service.create(conn, user_id=current_user()["id"], data=_body())}), 201


@bp.get("/me/recurring/<int:list_id>")
@require_auth()
def recurring_get(list_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"list": recurring_service.get(conn, user_id=current_user()["id"], list_id=list_id)})


@bp.post("/me/recurring/<int:list_id>/<action>")
@require_auth()
def recurring_status(list_id: int, action: str):
    if action not in ("pause", "resume", "cancel"):
        raise ValidationError("عملیات نامعتبر است")
    with get_db().write_transaction() as conn:
        return jsonify({"list": recurring_service.set_status(conn, user_id=current_user()["id"], list_id=list_id,
                                                             action=action)})


@bp.get("/me/recurring/<int:list_id>/quote")
@require_auth()
def recurring_preview(list_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"quote": recurring_service.preview(conn, user_id=current_user()["id"], list_id=list_id)})


@bp.get("/me/recurring/<int:list_id>/runs")
@require_auth()
def recurring_runs(list_id: int):
    with get_db().read_transaction() as conn:
        return jsonify({"items": recurring_service.list_runs(conn, user_id=current_user()["id"], list_id=list_id)})


# ── admin ──

@bp.get("/admin/cashier-rules")
@require_auth("admin")
def admin_rules():
    with get_db().read_transaction() as conn:
        return jsonify({"items": cashier.list_rules(conn)})


@bp.patch("/admin/cashier-rules/<rule_key>")
@require_auth("admin")
def admin_rule_update(rule_key: str):
    with get_db().write_transaction() as conn:
        return jsonify({"rule": cashier.update_rule(conn, rule_key=rule_key, data=_body(), actor=current_user()["id"])})


@bp.get("/admin/partner-discounts")
@require_auth("admin")
def admin_discounts():
    with get_db().read_transaction() as conn:
        return jsonify({"items": cashier.list_partner_discounts(conn, status=request.args.get("status") or None)})


@bp.post("/admin/partner-discounts")
@require_auth("admin")
def admin_discount_create():
    with get_db().write_transaction() as conn:
        return jsonify({"discount": cashier.create_partner_discount(conn, data=_body(), actor=current_user()["id"])}), 201


@bp.patch("/admin/partner-discounts/<int:discount_id>")
@require_auth("admin")
def admin_discount_update(discount_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"discount": cashier.update_partner_discount(conn, discount_id=discount_id, data=_body())})


@bp.post("/admin/cashier/recurring/run-due")
@require_auth("admin")
def admin_run_due():
    """Produces draft quotes for due lists. Never charges money."""
    with get_db().write_transaction() as conn:
        return jsonify(recurring_service.run_due(conn))
