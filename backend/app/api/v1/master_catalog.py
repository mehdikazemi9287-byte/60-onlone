"""Master Product Catalog API — Phase 4.

Routes:
  GET  /api/v1/catalog/resolve                          — resolve identifier to master product
  GET  /api/v1/catalog/search                           — search master products
  GET  /api/v1/catalog/products/<public_id>             — get master product by UUID

Admin routes:
  POST /api/v1/admin/catalog/products                   — create master product
  GET  /api/v1/admin/catalog/products                   — list/search master products
  POST /api/v1/admin/catalog/products/<id>/identifiers  — add identifier
  GET  /api/v1/admin/catalog/products/<id>/identifiers  — list identifiers
  GET  /api/v1/admin/catalog/unresolved                 — list unresolved external mappings
  POST /api/v1/admin/catalog/unresolved/<id>/resolve    — resolve a mapping
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ValidationError
import app.services.master_catalog_service as svc

bp = Blueprint("master_catalog", __name__, url_prefix="/api/v1")


# ── Public / authenticated catalog endpoints ──────────────────────────────────

@bp.get("/catalog/resolve")
@require_auth()
def resolve_identifier():
    """Resolve a product identifier to a master product."""
    identifier_type = (request.args.get("type") or "").strip().upper()
    identifier_value = (request.args.get("value") or "").strip()
    supplier_id = request.args.get("supplier_id", type=int)
    organization_id = request.args.get("organization_id", type=int)

    if not identifier_type or not identifier_value:
        raise ValidationError("پارامترهای 'type' و 'value' الزامی هستند")

    db = get_db()
    with db.read_transaction() as conn:
        product = svc.resolve_product(
            conn,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            supplier_id=supplier_id,
            organization_id=organization_id,
        )
    if product is None:
        from app.core.errors import NotFoundError
        raise NotFoundError("محصولی با این شناسه یافت نشد")
    return jsonify(product)


@bp.get("/catalog/search")
@require_auth()
def search_catalog():
    """Search master products."""
    db = get_db()
    with db.read_transaction() as conn:
        result = svc.search_master_products(
            conn,
            q=request.args.get("q", ""),
            category=request.args.get("category"),
            brand=request.args.get("brand"),
            status="active",
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 20, type=int),
        )
    return jsonify(result)


@bp.get("/catalog/products/<string:public_product_id>")
@require_auth()
def get_product_by_public_id(public_product_id: str):
    db = get_db()
    with db.read_transaction() as conn:
        product = svc.get_master_product_by_public_id(conn, public_product_id)
    return jsonify(product)


# ── Admin catalog endpoints ────────────────────────────────────────────────────

@bp.post("/admin/catalog/products")
@require_auth("admin")
def create_master_product():
    data = request.get_json(silent=True) or {}
    canonical_name_fa = (data.get("canonical_name_fa") or "").strip()
    if not canonical_name_fa:
        raise ValidationError("نام فارسی کالا الزامی است")

    db = get_db()
    with db.write_transaction() as conn:
        product = svc.create_master_product(
            conn,
            canonical_name_fa=canonical_name_fa,
            canonical_name_en=data.get("canonical_name_en"),
            category=data.get("category"),
            subcategory=data.get("subcategory"),
            brand=data.get("brand"),
            model=data.get("model"),
            description_fa=data.get("description_fa"),
            specifications=data.get("specifications"),
            tax_category=data.get("tax_category", "standard"),
            vat_applicable=data.get("vat_applicable", True),
            vat_rate_bps=data.get("vat_rate_bps", 900),
            created_by_user_id=current_user()["id"],
        )
    return jsonify(product), 201


@bp.get("/admin/catalog/products")
@require_auth("admin")
def list_master_products():
    db = get_db()
    with db.read_transaction() as conn:
        result = svc.search_master_products(
            conn,
            q=request.args.get("q", ""),
            category=request.args.get("category"),
            brand=request.args.get("brand"),
            status=request.args.get("status", "active"),
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 20, type=int),
        )
    return jsonify(result)


@bp.post("/admin/catalog/products/<int:product_id>/identifiers")
@require_auth("admin")
def add_identifier(product_id: int):
    data = request.get_json(silent=True) or {}
    identifier_type = (data.get("identifier_type") or "").strip().upper()
    identifier_value = (data.get("identifier_value") or "").strip()
    if not identifier_type or not identifier_value:
        raise ValidationError("نوع و مقدار شناسه الزامی هستند")

    db = get_db()
    with db.write_transaction() as conn:
        ident = svc.add_identifier(
            conn,
            master_product_id=product_id,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            issuer=data.get("issuer"),
            supplier_id=data.get("supplier_id"),
            organization_id=data.get("organization_id"),
            metadata=data.get("metadata"),
        )
    return jsonify(ident), 201


@bp.get("/admin/catalog/products/<int:product_id>/identifiers")
@require_auth("admin")
def list_identifiers(product_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        identifiers = svc.list_identifiers(conn, product_id)
    return jsonify({"items": identifiers})


@bp.get("/admin/catalog/unresolved")
@require_auth("admin")
def list_unresolved():
    db = get_db()
    with db.read_transaction() as conn:
        result = svc.list_unresolved_mappings(
            conn,
            status=request.args.get("status", "pending"),
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 20, type=int),
        )
    return jsonify(result)


@bp.post("/admin/catalog/unresolved/<int:mapping_id>/resolve")
@require_auth("admin")
def resolve_mapping(mapping_id: int):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("map", "reject", "create_new"):
        raise ValidationError("اقدام باید 'map'، 'reject' یا 'create_new' باشد")

    db = get_db()
    with db.write_transaction() as conn:
        result = svc.resolve_mapping(
            conn,
            mapping_id=mapping_id,
            action=action,
            master_product_id=data.get("master_product_id"),
            reviewer_user_id=current_user()["id"],
            notes=data.get("notes"),
            new_product_data=data.get("new_product_data"),
        )
    return jsonify(result)
