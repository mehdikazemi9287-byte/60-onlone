"""Logistics API — shipment planning, booking, tracking, and carrier webhooks.

URL structure:
  /api/v1/fulfillment-orders/:fo_id/shipment-plan    POST   admin/supplier only
  /api/v1/fulfillment-orders/:fo_id/book-shipment    POST   admin/supplier only
  /api/v1/fulfillment-orders/:fo_id/tracking         GET    authenticated
  /api/v1/webhooks/carrier/:provider_code            POST   public (carrier-signed)

Authorization (BLOCKER 2):
  - Plan and book endpoints: admin OR the supplier that owns the FO.
  - Customers get 403 on plan/book mutations — enforced by require_auth roles AND
    internally by _check_fo_access in logistics_service.
  - Tracking: any authenticated user (service enforces ownership for customers).
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError
from app.services import logistics_service, webhook_service
from app.services import fulfillment_service

bp = Blueprint("logistics", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_supplier_id(db, user_id: int, user_role: str) -> int | None:
    """Return the supplier_id for a supplier user, or None for admins."""
    if user_role == "admin":
        return None
    with db.read_transaction() as conn:
        sup = fulfillment_service.get_supplier_for_user(conn, user_id)
    if sup is None:
        raise NotFoundError(
            "حساب تأمین‌کننده یافت نشد. با پشتیبان تماس بگیرید.",
            code="supplier_not_linked",
        )
    return int(sup["id"])


# ---------------------------------------------------------------------------
# POST /api/v1/fulfillment-orders/<fo_id>/shipment-plan
# Trigger (or re-fetch) shipment plan for a fulfillment order.
# Authorization: admin OR owning supplier (BLOCKER 2).
# Note: logistics_service.plan_shipment() calls _check_fo_access internally.
# ---------------------------------------------------------------------------

@bp.route("/api/v1/fulfillment-orders/<int:fo_id>/shipment-plan", methods=["POST"])
@require_auth("admin", "supplier")
def plan_shipment_endpoint(fo_id: int):
    db = get_db()
    user = g.current_user
    supplier_id = _resolve_supplier_id(db, user["id"], user["role"])

    result = logistics_service.plan_shipment(
        db, fo_id,
        user_id=user["id"],
        user_role=user["role"],
        supplier_id=supplier_id,
    )
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# POST /api/v1/fulfillment-orders/<fo_id>/book-shipment
# Book the planned carrier for a fulfillment order.
# Authorization: admin OR owning supplier (BLOCKER 2).
# Note: logistics_service.book_shipment() calls _check_fo_access internally.
# ---------------------------------------------------------------------------

@bp.route("/api/v1/fulfillment-orders/<int:fo_id>/book-shipment", methods=["POST"])
@require_auth("admin", "supplier")
def book_shipment_endpoint(fo_id: int):
    db = get_db()
    user = g.current_user
    supplier_id = _resolve_supplier_id(db, user["id"], user["role"])

    shipment = logistics_service.book_shipment(
        db, fo_id,
        user_id=user["id"],
        user_role=user["role"],
        supplier_id=supplier_id,
    )
    return jsonify({"shipment": shipment}), 200


# ---------------------------------------------------------------------------
# GET /api/v1/fulfillment-orders/<fo_id>/tracking
# Retrieve shipment tracking info (customer-safe, no internal booking keys).
# Authorization: any authenticated user — service layer enforces ownership.
# ---------------------------------------------------------------------------

@bp.route("/api/v1/fulfillment-orders/<int:fo_id>/tracking", methods=["GET"])
@require_auth()
def get_tracking_endpoint(fo_id: int):
    db = get_db()
    user = g.current_user

    # For non-admin, non-supplier users (i.e. customers), enforce order ownership
    customer_user_id = user["id"] if user["role"] not in ("admin", "supplier") else None

    with db.read_transaction() as conn:
        tracking = logistics_service.get_tracking(
            conn, fo_id, customer_user_id=customer_user_id
        )
    return jsonify(tracking), 200


# ---------------------------------------------------------------------------
# POST /api/v1/webhooks/carrier/<provider_code>
# Receive inbound carrier webhook events.
# Security: verified by carrier-specific HMAC in webhook_service.
# NEVER raises — always returns 200 to prevent carrier retry storms.
# ---------------------------------------------------------------------------

@bp.route("/api/v1/webhooks/carrier/<provider_code>", methods=["POST"])
def carrier_webhook(provider_code: str):
    db = get_db()
    raw_body = request.get_data()
    headers = dict(request.headers)
    result = webhook_service.process_webhook(db, provider_code, headers, raw_body)
    # Always 200 — carrier should not retry on our application errors
    return jsonify(result), 200
