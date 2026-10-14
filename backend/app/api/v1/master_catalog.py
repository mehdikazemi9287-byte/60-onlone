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
            variant=data.get("variant"),
            size_label=data.get("size_label"),
            unit=data.get("unit"),
            package_quantity=data.get("package_quantity"),
            net_quantity=data.get("net_quantity"),
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


@bp.post("/admin/catalog/import")
@require_auth("admin")
def import_catalog():
    import hashlib, json
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    from app.core.deps import get_settings
    from app.core.errors import ConflictError
    from app.services.catalog_bulk_import_service import import_catalog_csv

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    csv_text = body.get("csv_text")
    source = body.get("source")
    confirm = body.get("confirm", False)
    if not isinstance(csv_text, str) or not csv_text.strip() or len(csv_text.encode()) > 2000000:
        raise ValidationError("فایل CSV باید غیرخالی و حداکثر دو مگابایت باشد")
    if not isinstance(source, str) or not source.strip() or len(source) > 500:
        raise ValidationError("منشأ فایل را مشخص کنید")
    if not isinstance(confirm, bool):
        raise ValidationError("تأیید نامعتبر است")
    signer = URLSafeTimedSerializer(get_settings().secret_key, salt="catalog-import-preview")
    db = get_db()

    def fingerprint(conn):
        digest = hashlib.sha256()
        for table in (
            "master_products",
            "products",
            "categories",
            "inventory",
            "product_identifiers_legacy",
            "catalog_publications",
        ):
            for row in conn.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall():
                digest.update(json.dumps(dict(row), sort_keys=True, ensure_ascii=False).encode())
        return digest.hexdigest()

    manager = db.write_transaction() if confirm else db.read_transaction()
    with manager as conn:
        payload = {
            "user": current_user()["id"],
            "csv": hashlib.sha256(csv_text.encode()).hexdigest(),
            "source": source.strip(),
            "state": fingerprint(conn),
        }
        if confirm:
            try:
                old = signer.loads(body.get("preview_token", ""), max_age=900)
            except (BadSignature, SignatureExpired, TypeError):
                raise ConflictError("پیش‌نمایش منقضی یا نامعتبر است؛ دوباره بررسی کنید")
            if old != payload:
                raise ConflictError("فایل یا داده‌ها پس از پیش‌نمایش تغییر کرده‌اند")
        from app.services.catalog_bulk_import_service import parse_catalog_csv

        parsed = parse_catalog_csv(csv_text)
        categories = {
            r["slug"]: r["name_fa"] for r in conn.execute("SELECT slug,name_fa FROM categories")
        }
        for row in parsed["rows"]:
            if row["status"] in ("invalid", "skip"):
                continue
            item = row["data"]
            if item["category_slug"] not in categories:
                raise ValidationError("دسته باید از taxonomy موجود انتخاب شود")
            if (
                item.get("category_name_fa")
                and item["category_name_fa"] != categories[item["category_slug"]]
            ):
                raise ValidationError("نام دسته با taxonomy موجود مطابقت ندارد")
        result = import_catalog_csv(conn, csv_text, confirm=confirm)
        if confirm and result["confirmed"]:
            from app.services import audit_service

            audit_service.record(
                conn,
                actor_user_id=current_user()["id"],
                action="catalog_import",
                entity_type="catalog",
                entity_id=None,
                metadata={
                    "source": source.strip(),
                    "sha256": payload["csv"],
                    "created": result["created"],
                    "updated": result["updated"],
                    "published": result["published"],
                },
            )
        result["preview_token"] = (
            signer.dumps(payload) if not confirm and not result["invalid"] else None
        )
    return jsonify(result)


@bp.get("/admin/catalog/legacy-products")
@require_auth("admin")
def legacy_products():
    rows = get_db().query(
        "SELECT id,sku,title_fa FROM products WHERE master_product_id IS NULL ORDER BY id"
    )
    return jsonify({"items": [dict(r) for r in rows]})


@bp.post("/admin/catalog/legacy-products/<int:product_id>/link")
@require_auth("admin")
def link_legacy_product(product_id):
    from app.core.errors import ConflictError, NotFoundError
    from app.services import audit_service

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    mid = body.get("master_product_id")
    proof = body.get("evidence")
    if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
        raise ValidationError("شناسه مرجع نامعتبر است")
    if not isinstance(proof, str) or not 20 <= len(proof.strip()) <= 1000:
        raise ValidationError("مدرک تطبیق باید بین ۲۰ و ۱۰۰۰ نویسه باشد")
    with get_db().write_transaction() as conn:
        product = conn.execute(
            "SELECT id,master_product_id FROM products WHERE id=?", (product_id,)
        ).fetchone()
        master = conn.execute(
            "SELECT id FROM master_products WHERE id=? AND status!='merged'", (mid,)
        ).fetchone()
        if not product or not master:
            raise NotFoundError("محصول یا مرجع یافت نشد")
        if product["master_product_id"] == mid:
            return jsonify({"product_id": product_id, "master_product_id": mid, "changed": False})
        if product["master_product_id"] is not None:
            raise ConflictError("محصول قبلاً به مرجع دیگری متصل است")
        if conn.execute(
            "SELECT 1 FROM products WHERE master_product_id=? AND is_active=1 AND id!=?",
            (mid, product_id),
        ).fetchone():
            raise ConflictError("این مرجع محصول فعال دیگری دارد؛ ادغام نیازمند بررسی تاریخچه است")
        conn.execute("UPDATE products SET master_product_id=? WHERE id=?", (mid, product_id))
        audit_service.record(
            conn,
            actor_user_id=current_user()["id"],
            action="catalog_legacy_link",
            entity_type="product",
            entity_id=product_id,
            metadata={"master_product_id": mid, "evidence": proof.strip()},
        )
    return jsonify({"product_id": product_id, "master_product_id": mid, "changed": True})


@bp.get("/catalog/selection")
def selection_catalog():
    # Public projection of published masters, never offers or private drafts.
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "12"))
    except ValueError as exc:
        raise ValidationError("صفحه نامعتبر است") from exc
    with get_db().read_transaction() as conn:
        return jsonify(svc.selection_catalog(conn, q=request.args.get("q", ""), category=request.args.get("category"), supplier=request.args.get("supplier"), page=page, page_size=page_size))
