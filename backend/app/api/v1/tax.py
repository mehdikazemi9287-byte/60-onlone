"""Tax API — Phase 7 VAT/Tax Foundation.

Endpoints:
  GET  /api/v1/tax/categories              List tax categories
  GET  /api/v1/tax/categories/<code>       Get one category
  POST /api/v1/tax/categories              Create category (admin)
  GET  /api/v1/tax/rates/<code>            List rate history for a category
  POST /api/v1/tax/rates                   Create a new effective-dated rate (admin)
  POST /api/v1/tax/calculate               Calculate tax for a subtotal
  GET  /api/v1/tax/systems                 List available tax adapter systems

ORGANIZATION SCOPE RULES (calculate endpoint):
  - admin may supply any existing organization_id explicitly.
  - org member may supply an organization_id only for an org where they hold
    an ACTIVE membership; 404 is returned otherwise (not 403, to avoid
    confirming the org's existence to non-members).
  - any other caller (supplier, customer, employee without membership) receives
    404 when supplying a cross-tenant organization_id.
  - when organization_id is omitted, no exemption is applied; the caller's
    identity is never used to invent one.
  - all access decisions are derived from the organizations/memberships tables
    server-side; the caller-supplied organization_id is never trusted directly.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.db import query as _db_query
from app.core.deps import require_auth
from app.services import tax_service
from app.adapters.tax.registry import list_tax_systems
from app.core.errors import NotFoundError, ValidationError

bp = Blueprint("tax", __name__, url_prefix="/api/v1/tax")


@bp.route("/categories", methods=["GET"])
@require_auth()
def list_categories():
    active_only = request.args.get("active_only", "true").lower() != "false"
    categories = tax_service.get_tax_categories(active_only=active_only)
    return jsonify({"tax_categories": categories, "count": len(categories)})


@bp.route("/categories/<code>", methods=["GET"])
@require_auth()
def get_category(code: str):
    try:
        cat = tax_service.get_tax_category(code.upper())
    except NotFoundError as exc:
        return jsonify({"error": {"code": "not_found", "message": str(exc)}}), 404
    return jsonify(cat)


@bp.route("/categories", methods=["POST"])
@require_auth("admin")
def create_category():
    data = request.get_json(force=True) or {}
    try:
        cat = tax_service.create_tax_category(
            code=data.get("code", ""),
            name_fa=data.get("name_fa", ""),
            name_en=data.get("name_en", ""),
            description=data.get("description", ""),
            is_active=data.get("is_active", True),
        )
    except ValidationError as exc:
        return jsonify({"error": {"code": "validation_error", "message": str(exc)}}), 422
    return jsonify(cat), 201


@bp.route("/rates/<code>", methods=["GET"])
@require_auth()
def list_rates(code: str):
    try:
        rates = tax_service.get_all_rates(code.upper())
    except NotFoundError as exc:
        return jsonify({"error": {"code": "not_found", "message": str(exc)}}), 404
    return jsonify({"tax_category_code": code.upper(), "rates": rates})


@bp.route("/rates", methods=["POST"])
@require_auth("admin")
def create_rate():
    data = request.get_json(force=True) or {}
    try:
        rate = tax_service.create_tax_rate(
            tax_category_code=data.get("tax_category_code", ""),
            rate_bps=int(data.get("rate_bps", 0)),
            effective_from=data.get("effective_from", ""),
            effective_until=data.get("effective_until"),
            jurisdiction=data.get("jurisdiction", "IR"),
            jurisdiction_detail=data.get("jurisdiction_detail", ""),
            notes=data.get("notes", ""),
        )
    except (NotFoundError, ValidationError) as exc:
        status = 404 if isinstance(exc, NotFoundError) else 422
        return jsonify({"error": {"code": "error", "message": str(exc)}}), status
    return jsonify(rate), 201


@bp.route("/calculate", methods=["POST"])
@require_auth()
def calculate_tax():
    """Calculate tax for a given subtotal and category.

    Body: {subtotal_minor, tax_category_code, effective_date, organization_id?}

    organization_id access rules (server-side, never trusted from input):
      - admin: any existing organization_id accepted; non-existent → 404.
      - other authenticated user: must hold an ACTIVE membership in the
        referenced org; missing/inactive membership → 404 (not 403).
      - omitted: no exemption is applied.
    """
    data = request.get_json(force=True) or {}
    subtotal_minor = data.get("subtotal_minor")
    tax_category_code = data.get("tax_category_code", "STANDARD")
    effective_date = data.get("effective_date")

    if subtotal_minor is None or not effective_date:
        return jsonify({"error": {"code": "validation_error",
                                   "message": "subtotal_minor و effective_date الزامی است"}}), 422

    # ── Organization scope validation ─────────────────────────────────────────
    organization_id: int | None = None
    org_id_raw = data.get("organization_id")
    if org_id_raw is not None:
        try:
            org_id_int = int(org_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": {"code": "not_found",
                                       "message": "سازمان یافت نشد"}}), 404

        user = g.current_user
        if user["role"] == "admin":
            # Platform admin: verify the organization exists.
            exists = _db_query(
                "SELECT 1 FROM organizations WHERE id = ?", (org_id_int,), one=True
            )
            if exists is None:
                return jsonify({"error": {"code": "not_found",
                                           "message": "سازمان یافت نشد"}}), 404
        else:
            # Any other role: must have an ACTIVE membership in the referenced org.
            # Return 404 (not 403) so the endpoint does not confirm the org's
            # existence to callers who are not members of it.
            mem = _db_query(
                """
                SELECT id FROM organization_memberships
                WHERE organization_id = ? AND user_id = ? AND status = 'active'
                """,
                (org_id_int, user["id"]),
                one=True,
            )
            if mem is None:
                return jsonify({"error": {"code": "not_found",
                                           "message": "سازمان یافت نشد"}}), 404

        organization_id = org_id_int
    # ── End organization scope validation ─────────────────────────────────────

    try:
        result = tax_service.calculate_line_tax(
            subtotal_minor=int(subtotal_minor),
            tax_category_code=tax_category_code,
            effective_date=effective_date,
            organization_id=organization_id,
        )
    except NotFoundError as exc:
        return jsonify({"error": {"code": "not_found", "message": str(exc)}}), 404
    return jsonify(result)


@bp.route("/systems", methods=["GET"])
@require_auth()
def list_systems():
    """List available tax adapter systems."""
    systems = list_tax_systems()
    return jsonify({"tax_systems": systems})
