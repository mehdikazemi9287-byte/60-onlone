"""Scanner / Barcode Lookup API — Phase 6.

Fast lookup endpoint for handheld scanners and mobile POS devices.
Resolves any identifier (barcode, GTIN, SKU, …) to the local product
and immediately enriches the result with authoritative stock and price.

Supports both GET (browser / REST clients) and POST (scanner devices that
always POST, even for lookups).

URL structure:
  GET  /api/v1/scanner/resolve    — query-string driven
  POST /api/v1/scanner/lookup     — body-driven (scanner-device friendly)

Response shape:
  {
    "product":     {...} | null,
    "stock":       {...} | null,
    "price":       {...} | null,
    "identifiers": [...]
  }
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import ValidationError
from app.services import identifier_service, inventory_source_service, price_source_service

bp = Blueprint("scanner", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

def _resolve(
    db,
    identifier_type: str,
    identifier_value: str,
    supplier_id: int | None,
) -> dict:
    """Resolve an identifier and enrich with stock + price.

    Returns the unified scanner response dict. 'product' is None when
    the identifier does not match any known product.
    """
    if not identifier_type or not identifier_value:
        raise ValidationError("پارامترهای «type» و «value» الزامی هستند")

    with db.read_transaction() as conn:
        resolved = identifier_service.resolve_by_identifier(
            conn,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            namespace="",
            supplier_id=supplier_id,
        )

    if resolved is None:
        return {
            "product":     None,
            "stock":       None,
            "price":       None,
            "identifiers": [],
        }

    product    = resolved.get("product")
    offer_id   = resolved.get("offer_id")
    identifiers = resolved.get("identifiers", [])

    # Fetch authoritative stock for the offer (if we have one)
    stock = None
    if offer_id is not None:
        try:
            with db.read_transaction() as conn:
                stock = inventory_source_service.get_authoritative_stock(
                    conn, offer_id=offer_id
                )
        except Exception:
            stock = None

    # Fetch authoritative price for the offer (if we have one)
    price = None
    if offer_id is not None:
        try:
            with db.read_transaction() as conn:
                price = price_source_service.get_authoritative_price(
                    conn, offer_id=offer_id
                )
        except Exception:
            price = None

    return {
        "product":     product,
        "stock":       stock,
        "price":       price,
        "identifiers": identifiers,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/scanner/resolve")
@require_auth("supplier", "admin")
def scanner_resolve():
    """Resolve a barcode / identifier via query string.

    Query params:
      type        — identifier type, e.g. "barcode", "gtin", "sku"
      value       — the identifier value, e.g. "6260001000010"
      supplier_id — (optional) restrict search to one supplier's catalogue
    """
    db              = get_db()
    identifier_type = (request.args.get("type") or "").strip()
    value           = (request.args.get("value") or "").strip()
    supplier_id     = request.args.get("supplier_id", type=int)

    result = _resolve(db, identifier_type, value, supplier_id)
    return jsonify(result)


@bp.post("/scanner/lookup")
@require_auth("supplier", "admin")
def scanner_lookup():
    """Resolve a barcode / identifier via POST body (scanner-device friendly).

    Body:
      {
        "type":        "barcode",
        "value":       "6260001000010",
        "supplier_id": 42          // optional
      }
    """
    db   = get_db()
    body = request.get_json(silent=True) or {}

    identifier_type = (body.get("type") or "").strip()
    value           = (body.get("value") or "").strip()
    supplier_id     = body.get("supplier_id")
    if supplier_id is not None:
        try:
            supplier_id = int(supplier_id)
        except (TypeError, ValueError):
            raise ValidationError("مقدار «supplier_id» باید عدد صحیح باشد")

    result = _resolve(db, identifier_type, value, supplier_id)
    return jsonify(result)
