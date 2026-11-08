"""Price Source API — Phase 6.

Manages multi-source price tracking. Each source (ERP, connector, manual)
reports prices; the authoritative layer selects the winning price.

URL structure:
  POST /api/v1/price-sources
  GET  /api/v1/price-sources
  GET  /api/v1/price-sources/<id>
  POST /api/v1/price-sources/<id>/prices
  GET  /api/v1/price-sources/<id>/prices
  GET  /api/v1/price-sources/authoritative-price/<offer_id>
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import ValidationError
from app.services import price_source_service

# Admin-operated: supplier self-service is disabled until per-supplier ownership is enforced (no supplier UI uses it).
bp = Blueprint("price_sources", __name__, url_prefix="/api/v1")


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

@bp.post("/price-sources")
@require_auth("admin")
def create_price_source():
    """Create a new price source."""
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
        result = price_source_service.create_price_source(
            conn,
            name=name,
            source_type=source_type,
            supplier_id=supplier_id,
            priority=priority,
            connector_account_id=connector_account_id,
        )
    return jsonify({"data": result}), 201


@bp.get("/price-sources")
@require_auth("admin")
def list_price_sources():
    """List price sources, optionally filtered."""
    db          = get_db()
    supplier_id = request.args.get("supplier_id", type=int)
    active_only = _bool_arg(request.args.get("active_only", "true"))

    with db.read_transaction() as conn:
        results = price_source_service.list_price_sources(
            conn,
            supplier_id=supplier_id,
            active_only=active_only,
        )
    return jsonify({"data": results})


@bp.get("/price-sources/<int:source_id>")
@require_auth("admin")
def get_price_source(source_id: int):
    """Get a single price source by ID."""
    db = get_db()
    with db.read_transaction() as conn:
        result = price_source_service.get_price_source(conn, source_id=source_id)
    return jsonify({"data": result})


@bp.post("/price-sources/<int:source_id>/prices")
@require_auth("admin")
def update_price(source_id: int):
    """Report an updated price from this source for a specific offer."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    offer_id    = _int_field(body, "offer_id")
    price_minor = _int_field(body, "price_minor")
    version     = _int_field(body, "version")
    currency    = (body.get("currency") or "IRR").strip().upper()
    source_ref  = (body.get("source_ref") or "").strip() or None

    with db.write_transaction() as conn:
        result = price_source_service.update_price(
            conn,
            source_id=source_id,
            offer_id=offer_id,
            price_minor=price_minor,
            currency=currency,
            version=version,
            source_ref=source_ref,
        )
    return jsonify({"data": result})


@bp.get("/price-sources/<int:source_id>/prices")
@require_auth("admin")
def list_prices_by_source(source_id: int):
    """List all price records reported by this price source."""
    db = get_db()
    with db.read_transaction() as conn:
        results = price_source_service.list_prices_by_source(conn, source_id)
    return jsonify({"data": results})


@bp.get("/price-sources/authoritative-price/<int:offer_id>")
@require_auth("admin")
def get_authoritative_price(offer_id: int):
    """Return the winning (authoritative) price for an offer."""
    db = get_db()
    with db.read_transaction() as conn:
        result = price_source_service.get_authoritative_price(
            conn, offer_id=offer_id
        )
    return jsonify({"data": result})
