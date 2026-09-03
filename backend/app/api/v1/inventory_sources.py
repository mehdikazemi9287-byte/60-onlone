"""Inventory Source API — Phase 6.

Manages multi-source inventory tracking. Each source (ERP feed, connector,
manual) reports stock; the authoritative layer picks the winning quantity.

URL structure:
  POST /api/v1/inventory-sources
  GET  /api/v1/inventory-sources
  GET  /api/v1/inventory-sources/<id>
  POST /api/v1/inventory-sources/<id>/stock
  GET  /api/v1/inventory-sources/<id>/stock
  GET  /api/v1/inventory-sources/authoritative-stock/<offer_id>
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import ValidationError
from app.services import inventory_source_service

bp = Blueprint("inventory_sources", __name__, url_prefix="/api/v1")


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


def _bool_arg(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/inventory-sources")
@require_auth("supplier", "admin")
def create_inventory_source():
    """Create a new inventory source."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    name                 = (body.get("name") or "").strip()
    source_type          = (body.get("source_type") or "").strip()
    supplier_id          = _int_field(body, "supplier_id")
    priority             = _int_field(body, "priority", required=False, default=0)
    connector_account_id = _int_field(body, "connector_account_id", required=False)

    if not name:
        raise ValidationError("فیلد «name» الزامی است")
    if not source_type:
        raise ValidationError("فیلد «source_type» الزامی است")

    with db.write_transaction() as conn:
        result = inventory_source_service.create_inventory_source(
            conn,
            name=name,
            source_type=source_type,
            supplier_id=supplier_id,
            priority=priority,
            connector_account_id=connector_account_id,
        )
    return jsonify({"data": result}), 201


@bp.get("/inventory-sources")
@require_auth("supplier", "admin")
def list_inventory_sources():
    """List inventory sources, optionally filtered."""
    db          = get_db()
    supplier_id = request.args.get("supplier_id", type=int)
    active_only = _bool_arg(request.args.get("active_only", "true"))

    with db.read_transaction() as conn:
        results = inventory_source_service.list_inventory_sources(
            conn,
            supplier_id=supplier_id,
            active_only=active_only,
        )
    return jsonify({"data": results})


@bp.get("/inventory-sources/<int:source_id>")
@require_auth("supplier", "admin")
def get_inventory_source(source_id: int):
    """Get a single inventory source by ID."""
    db = get_db()
    with db.read_transaction() as conn:
        result = inventory_source_service.get_inventory_source(conn, source_id=source_id)
    return jsonify({"data": result})


@bp.post("/inventory-sources/<int:source_id>/stock")
@require_auth("supplier", "admin")
def update_stock(source_id: int):
    """Report updated stock from this source for a specific offer."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    offer_id   = _int_field(body, "offer_id")
    quantity   = _int_field(body, "quantity")
    version    = _int_field(body, "version")
    source_ref = (body.get("source_ref") or "").strip() or None

    with db.write_transaction() as conn:
        result = inventory_source_service.update_stock(
            conn,
            source_id=source_id,
            offer_id=offer_id,
            quantity=quantity,
            version=version,
            source_ref=source_ref,
        )
    return jsonify({"data": result})


@bp.get("/inventory-sources/<int:source_id>/stock")
@require_auth("supplier", "admin")
def list_stock_by_source(source_id: int):
    """List all stock records reported by this inventory source."""
    db = get_db()
    with db.read_transaction() as conn:
        results = inventory_source_service.list_stock_by_source(
            conn, source_id=source_id
        )
    return jsonify({"data": results})


@bp.get("/inventory-sources/authoritative-stock/<int:offer_id>")
@require_auth("supplier", "admin")
def get_authoritative_stock(offer_id: int):
    """Return the winning (authoritative) stock level for an offer."""
    db = get_db()
    with db.read_transaction() as conn:
        result = inventory_source_service.get_authoritative_stock(
            conn, offer_id=offer_id
        )
    return jsonify({"data": result})
