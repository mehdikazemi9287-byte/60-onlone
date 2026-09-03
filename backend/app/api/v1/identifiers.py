"""Product Identifier API — Phase 6.

Manages barcode / GTIN / SKU identifiers attached to products, cross-supplier
identifier resolution, and conflict management.

URL structure:
  POST   /api/v1/identifiers
  GET    /api/v1/identifiers
  DELETE /api/v1/identifiers/<id>
  GET    /api/v1/identifiers/resolve
  GET    /api/v1/identifiers/conflicts
  POST   /api/v1/identifiers/conflicts/<id>/resolve
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import identifier_service

bp = Blueprint("identifiers", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int_field(body: dict, name: str, required: bool = True):
    val = body.get(name)
    if val is None:
        if required:
            raise ValidationError(f"فیلد «{name}» الزامی است")
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValidationError(f"مقدار «{name}» باید عدد صحیح باشد")


def _is_admin() -> bool:
    return g.current_user.get("role") == "admin"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/identifiers")
@require_auth("supplier", "admin")
def add_identifier():
    """Add a product identifier (barcode, GTIN, SKU, …)."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    product_id       = _int_field(body, "product_id")
    identifier_type  = (body.get("identifier_type") or "").strip()
    identifier_value = (body.get("identifier_value") or "").strip()
    namespace        = (body.get("namespace") or "").strip()
    is_primary       = bool(body.get("is_primary", False))
    supplier_id      = _int_field(body, "supplier_id", required=False)

    if not identifier_type:
        raise ValidationError("فیلد «identifier_type» الزامی است")
    if not identifier_value:
        raise ValidationError("فیلد «identifier_value» الزامی است")

    with db.write_transaction() as conn:
        result = identifier_service.add_identifier(
            conn,
            product_id=product_id,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            namespace=namespace,
            is_primary=is_primary,
            supplier_id=supplier_id,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": result}), 201


@bp.get("/identifiers")
@require_auth("supplier", "admin")
def list_identifiers():
    """List identifiers with optional filters."""
    db = get_db()
    product_id      = request.args.get("product_id", type=int)
    supplier_id     = request.args.get("supplier_id", type=int)
    identifier_type = request.args.get("identifier_type")

    with db.read_transaction() as conn:
        results = identifier_service.list_identifiers(
            conn,
            product_id=product_id,
            supplier_id=supplier_id,
            identifier_type=identifier_type,
        )
    return jsonify({"data": results})


@bp.delete("/identifiers/<int:identifier_id>")
@require_auth("supplier", "admin")
def delete_identifier(identifier_id: int):
    """Delete an identifier. Suppliers may only delete their own."""
    db = get_db()
    supplier_id = None if _is_admin() else None  # resolved below from token

    # Non-admins: supply supplier_id for isolation enforcement in service layer
    if not _is_admin():
        supplier_id = request.args.get("supplier_id", type=int)

    with db.write_transaction() as conn:
        identifier_service.delete_identifier(
            conn,
            identifier_id=identifier_id,
            supplier_id=supplier_id,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": {"deleted": True}})


@bp.get("/identifiers/resolve")
@require_auth("supplier", "admin")
def resolve_identifier():
    """Resolve an identifier value to a product."""
    db = get_db()
    id_type   = request.args.get("type", "").strip()
    value     = request.args.get("value", "").strip()
    namespace = request.args.get("namespace", "").strip()
    supplier_id = request.args.get("supplier_id", type=int)

    if not id_type or not value:
        raise ValidationError("پارامترهای «type» و «value» الزامی هستند")

    with db.read_transaction() as conn:
        result = identifier_service.resolve_by_identifier(
            conn,
            identifier_type=id_type,
            identifier_value=value,
            namespace=namespace,
            supplier_id=supplier_id,
        )
    if result is None:
        raise NotFoundError("شناسه یافت نشد")
    return jsonify({"data": result})


@bp.get("/identifiers/conflicts")
@require_auth("admin")
def list_conflicts():
    """List identifier conflicts (admin only)."""
    db     = get_db()
    status = request.args.get("status", "open")

    with db.read_transaction() as conn:
        results = identifier_service.list_conflicts(conn, status=status)
    return jsonify({"data": results})


@bp.post("/identifiers/conflicts/<int:conflict_id>/resolve")
@require_auth("admin")
def resolve_conflict(conflict_id: int):
    """Resolve an identifier conflict (admin only)."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    resolution = (body.get("resolution") or "").strip()
    notes      = (body.get("notes") or "").strip()

    if not resolution:
        raise ValidationError("فیلد «resolution» الزامی است")

    with db.write_transaction() as conn:
        result = identifier_service.resolve_conflict(
            conn,
            conflict_id=conflict_id,
            resolution=resolution,
            notes=notes,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": result})
