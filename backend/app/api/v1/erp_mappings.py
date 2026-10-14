"""ERP Mapping API — Phase 6.

Maps ERP product codes arriving from connectors to local products.
New mappings land in 'pending_review' status; an admin approves or rejects.

URL structure:
  POST   /api/v1/erp-mappings
  GET    /api/v1/erp-mappings
  GET    /api/v1/erp-mappings/<id>
  POST   /api/v1/erp-mappings/<id>/review
  DELETE /api/v1/erp-mappings/<id>
  GET    /api/v1/erp-mappings/resolve
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import mapping_service as erp_mapping_service

# Admin-operated: supplier self-service is disabled until per-supplier ownership is enforced (no supplier UI uses it).
bp = Blueprint("erp_mappings", __name__, url_prefix="/api/v1")

_VALID_STATUSES = {"active", "rejected", "pending_review"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int_field(body: dict, name: str, required: bool = True, default=None):
    val = body.get(name, default)
    if val is None:
        if required:
            raise ValidationError(f"فیلد «{name}» الزامی است")
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValidationError(f"مقدار «{name}» باید عدد صحیح باشد")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/erp-mappings")
@require_auth("admin")
def create_erp_mapping():
    """Create a new ERP product code → local product mapping."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    connector_account_id = _int_field(body, "connector_account_id")
    erp_product_code     = (body.get("erp_product_code") or "").strip()
    product_id           = _int_field(body, "product_id", required=False)
    supplier_id          = _int_field(body, "supplier_id")
    match_method         = (body.get("match_method") or "manual").strip()

    if not erp_product_code:
        raise ValidationError("فیلد «erp_product_code» الزامی است")

    with db.write_transaction() as conn:
        result = erp_mapping_service.create_mapping(
            conn,
            connector_account_id=connector_account_id,
            erp_product_code=erp_product_code,
            product_id=product_id,
            supplier_id=supplier_id,
            match_method=match_method,
        )
    return jsonify({"data": result}), 201


@bp.get("/erp-mappings")
@require_auth("admin")
def list_erp_mappings():
    """List ERP mappings with optional filters."""
    db                   = get_db()
    connector_account_id = request.args.get("connector_account_id", type=int)
    supplier_id          = request.args.get("supplier_id", type=int)
    status               = request.args.get("status")
    limit                = min(int(request.args.get("limit", "50")), 200)
    offset               = int(request.args.get("offset", "0"))

    with db.read_transaction() as conn:
        results = erp_mapping_service.list_mappings(
            conn,
            connector_account_id=connector_account_id,
            supplier_id=supplier_id,
            status=status,
        )
    return jsonify({"data": results[offset:offset + limit]})


@bp.get("/erp-mappings/<int:mapping_id>")
@require_auth("admin")
def get_erp_mapping(mapping_id: int):
    """Get a single ERP mapping by ID."""
    db = get_db()
    with db.read_transaction() as conn:
        result = erp_mapping_service.get_mapping(conn, mapping_id)  # raises NotFoundError
    return jsonify({"data": result})


@bp.post("/erp-mappings/<int:mapping_id>/review")
@require_auth("admin")
def review_erp_mapping(mapping_id: int):
    """Approve or reject a pending ERP mapping (admin only)."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    new_status = (body.get("new_status") or "").strip()
    product_id = _int_field(body, "product_id", required=False)

    if new_status not in ("active", "rejected"):
        raise ValidationError("مقدار «new_status» باید active یا rejected باشد")

    with db.write_transaction() as conn:
        result = erp_mapping_service.review_mapping(
            conn,
            mapping_id=mapping_id,
            new_status=new_status,
            product_id=product_id,
            reviewed_by=g.current_user["id"],
        )
    return jsonify({"data": result})


@bp.delete("/erp-mappings/<int:mapping_id>")
@require_auth("admin")
def delete_erp_mapping(mapping_id: int):
    """Delete an ERP mapping (admin only)."""
    db = get_db()
    with db.write_transaction() as conn:
        erp_mapping_service.delete_mapping(conn, mapping_id)  # raises NotFoundError
    return jsonify({"data": {"deleted": True}})


@bp.get("/erp-mappings/resolve")
@require_auth("admin")
def resolve_erp_mapping():
    """Resolve an ERP product code to its mapped local product."""
    db                   = get_db()
    connector_account_id = request.args.get("connector_account_id", type=int)
    erp_product_code     = (request.args.get("erp_product_code") or "").strip()

    if not connector_account_id:
        raise ValidationError("پارامتر «connector_account_id» الزامی است")
    if not erp_product_code:
        raise ValidationError("پارامتر «erp_product_code» الزامی است")

    with db.read_transaction() as conn:
        result = erp_mapping_service.resolve_erp_code(
            conn,
            connector_account_id=connector_account_id,
            erp_product_code=erp_product_code,
        )
    if result is None:
        raise NotFoundError("نگاشت برای این کد ERP یافت نشد")
    return jsonify({"data": result})
