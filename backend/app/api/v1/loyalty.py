"""60Coin loyalty API.

Customer-facing balance/history plus an admin-only earn endpoint (coins are
granted by the platform — purchase completion, campaigns, activity — never
self-granted by the customer). Redemption is customer-initiated but always
scoped to the caller's own balance, same isolation rule as credit.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ConflictError, ValidationError
from app.services import loyalty_service

bp = Blueprint("loyalty", __name__, url_prefix="/api/v1")


def _int(name: str, default: int) -> int:
    raw = request.args.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(f"پارامتر {name} باید عدد باشد") from exc


@bp.get("/me/loyalty")
@require_auth()  # any authenticated user — scoped to their own balance below
def my_loyalty():
    return jsonify(loyalty_service.wallet(get_db(), user_id=current_user()["id"]))


@bp.get("/loyalty/tiers")
@require_auth()  # informational, any authenticated user
def loyalty_tiers():
    """60Club tier list — thresholds only. benefit_note_fa is whatever a real
    business decision has configured (may be null); nothing here is invented."""
    return jsonify({"items": loyalty_service.list_tiers(get_db())})


@bp.get("/me/loyalty/transactions")
@require_auth()  # any authenticated user — scoped to their own balance below
def my_loyalty_transactions():
    return jsonify(loyalty_service.list_transactions(
        get_db(), user_id=current_user()["id"], page=_int("page", 1), page_size=_int("page_size", 25),
    ))


@bp.post("/me/loyalty/redeem")
@require_auth()  # any authenticated user — scoped to their own balance below
def redeem_my_loyalty():
    body = request.get_json(silent=True) or {}
    result = loyalty_service.redeem(
        get_db(),
        user_id=current_user()["id"],
        amount_coins=body.get("amount_coins"),
        order_id=body.get("order_id"),
        actor_user_id=current_user()["id"],
        note=body.get("note"),
        idempotency_key=request.headers.get("Idempotency-Key") or body.get("idempotency_key"),
    )
    status = 201 if result["created"] else 200
    return jsonify(result), status


@bp.post("/admin/loyalty/expire")
@require_auth("admin")
def admin_expire_loyalty():
    """Process due coin expiration for one user. No scheduler exists in this
    project yet — this is the manual/admin-triggered hook; a cron can call
    it (or backend/scripts/expire_loyalty_coins.py) once one is set up."""
    if not loyalty_service.expiration_policy_active():
        raise ConflictError(
            "سیاست انقضای 60Coin هنوز فعال نشده است",
            code="loyalty_expiration_policy_disabled",
        )
    body = request.get_json(silent=True) or {}
    if "user_id" not in body:
        raise ValidationError("user_id لازم است")
    result = loyalty_service.expire_due_coins(get_db(), user_id=int(body["user_id"]))
    return jsonify(result), 201 if result["created"] else 200


@bp.post("/loyalty/earn")
@require_auth("admin")
def earn_loyalty():
    """Platform-triggered coin grant (order completion, campaign, activity).

    Admin-only by design: a customer cannot mint their own coins by calling
    this directly. In production this is called server-to-server from the
    order-completion hook / campaign job, not from a customer's browser.
    """
    body = request.get_json(silent=True) or {}
    if "user_id" not in body:
        raise ValidationError("user_id لازم است")
    result = loyalty_service.earn(
        get_db(),
        user_id=body["user_id"],
        amount_coins=body.get("amount_coins"),
        source=body.get("source"),
        order_id=body.get("order_id"),
        actor_user_id=current_user()["id"],
        note=body.get("note"),
        idempotency_key=request.headers.get("Idempotency-Key") or body.get("idempotency_key"),
    )
    status = 201 if result["created"] else 200
    return jsonify(result), status
