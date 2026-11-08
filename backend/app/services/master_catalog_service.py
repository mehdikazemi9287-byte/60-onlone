"""Master Product Catalog service.

Manages canonical product definitions (master_products) and their identifiers
(product_identifiers). One real-world product = one master_product row.

Design invariants:
- Products are defined ONCE here; seller_offers reference products, not vice-versa.
- Identifiers are many-to-one: many codes may resolve to the same master product.
- Money fields use integer minor units; no floats.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError, ValidationError

ALLOWED_IDENTIFIER_TYPES = {
    "INTERNAL", "GTIN", "EAN", "UPC", "ISBN",
    "BARCODE", "QR", "RFID",
    "MFR_SKU", "SUPPLIER_SKU", "ERP_CODE",
    "ACCOUNTING_CODE", "WAREHOUSE_CODE",
    "LEGACY_CODE", "CUSTOMS_CODE", "TAX_CODE", "OTHER",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mp_dict(row) -> dict:
    return {
        "id": row["id"],
        "public_product_id": row["public_product_id"],
        "provenance": row["provenance"],
        "canonical_name_fa": row["canonical_name_fa"],
        "canonical_name_en": row["canonical_name_en"],
        "brand": row["brand"],
        "manufacturer": row["manufacturer"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "product_type": row["product_type"],
        "model": row["model"],
        "variant": row["variant"],
        "size_label": row["size_label"],
        "unit": row["unit"],
        "package_quantity": row["package_quantity"],
        "net_quantity": row["net_quantity"],
        "description_fa": row["description_fa"],
        "specifications": json.loads(row["specifications_json"] or "{}"),
        "image_urls": json.loads(row["image_urls_json"] or "[]"),
        "country_of_origin": row["country_of_origin"],
        "tax_category": row["tax_category"],
        "vat_applicable": bool(row["vat_applicable"]),
        "vat_rate_bps": row["vat_rate_bps"],
        "tax_classification": row["tax_classification"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _identifier_dict(row) -> dict:
    return {
        "id": row["id"],
        "master_product_id": row["master_product_id"],
        "identifier_type": row["identifier_type"],
        "identifier_value": row["identifier_value"],
        "issuer": row["issuer"],
        "supplier_id": row["supplier_id"],
        "organization_id": row["organization_id"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


# ── Master Product CRUD ────────────────────────────────────────────────────────

def create_master_product(
    conn,
    *,
    canonical_name_fa: str,
    canonical_name_en: str | None = None,
    brand: str | None = None,
    manufacturer: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    product_type: str | None = None,
    model: str | None = None,
    variant: str | None = None,
    size_label: str | None = None,
    unit: str | None = None,
    package_quantity: int | None = None,
    net_quantity: str | None = None,
    description_fa: str | None = None,
    specifications: dict | None = None,
    image_urls: list | None = None,
    country_of_origin: str | None = None,
    tax_category: str = "standard",
    vat_applicable: bool = True,
    vat_rate_bps: int = 900,
    tax_classification: str | None = None,
    created_by_user_id: int | None = None,
) -> dict:
    """Create a canonical master product. Returns the created record."""
    if not isinstance(canonical_name_fa, str):
        raise ValidationError("canonical_name_fa باید متن باشد")
    canonical_name_fa = (canonical_name_fa or "").strip()
    if not canonical_name_fa:
        raise ValidationError("canonical_name_fa نمی‌تواند خالی باشد")
    if unit is not None and (not isinstance(unit, str) or not unit.strip() or len(unit) > 50):
        raise ValidationError("unit باید رشته معتبر یا null باشد")
    if package_quantity is not None and (isinstance(package_quantity, bool) or not isinstance(package_quantity, int) or not 1 <= package_quantity <= 9223372036854775807):
        raise ValidationError("package_quantity باید حداقل ۱ باشد")
    if type(vat_applicable) is not bool:
        raise ValidationError("vat_applicable باید مقدار بولی باشد")
    if type(vat_rate_bps) is not int or not 0 <= vat_rate_bps <= 9223372036854775807:
        raise ValidationError("vat_rate_bps باید عدد صحیح نامنفی در محدوده ذخیره‌سازی باشد")

    public_id = str(uuid.uuid4())
    cur = conn.execute(
        """
        INSERT INTO master_products
            (public_product_id, canonical_name_fa, canonical_name_en,
             brand, manufacturer, category, subcategory, product_type,
             model, variant, size_label, unit, package_quantity, net_quantity,
             description_fa, specifications_json, image_urls_json,
             country_of_origin, tax_category, vat_applicable, vat_rate_bps,
             tax_classification, created_by_user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            public_id, canonical_name_fa, canonical_name_en,
            brand, manufacturer, category, subcategory, product_type,
            model, variant, size_label, unit, package_quantity, net_quantity,
            description_fa,
            json.dumps(specifications or {}, ensure_ascii=False),
            json.dumps(image_urls or [], ensure_ascii=False),
            country_of_origin, tax_category,
            int(vat_applicable), vat_rate_bps,
            tax_classification, created_by_user_id,
        ),
    )
    return get_master_product(conn, cur.lastrowid)


def get_master_product(conn, product_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM master_products WHERE id = ?", (product_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("محصول اصلی یافت نشد", code="master_product_not_found")
    return _mp_dict(row)


def get_master_product_by_public_id(conn, public_product_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM master_products WHERE public_product_id = ?", (public_product_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("محصول اصلی یافت نشد", code="master_product_not_found")
    return _mp_dict(row)


def search_master_products(
    conn,
    *,
    q: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    where = ["1=1"]
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if q and q.strip():
        needle = "%" + q.strip() + "%"
        where.append(
            "(canonical_name_fa LIKE ? OR canonical_name_en LIKE ? "
            "OR brand LIKE ? OR model LIKE ?)"
        )
        params.extend([needle, needle, needle, needle])
    if category:
        where.append("category = ?")
        params.append(category)
    if brand:
        where.append("brand = ?")
        params.append(brand)

    clause = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM master_products WHERE {clause}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM master_products WHERE {clause} "
        f"ORDER BY id DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {
        "items": [_mp_dict(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


# ── Product Identifiers ────────────────────────────────────────────────────────

def add_identifier(
    conn,
    *,
    master_product_id: int,
    identifier_type: str,
    identifier_value: str,
    issuer: str | None = None,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """Add an identifier to a master product. Raises ConflictError if duplicate."""
    identifier_type = identifier_type.upper()
    if identifier_type not in ALLOWED_IDENTIFIER_TYPES:
        raise ValidationError(f"نوع شناسه نامعتبر است: {identifier_type}")
    identifier_value = (identifier_value or "").strip()
    if not identifier_value:
        raise ValidationError("مقدار شناسه نمی‌تواند خالی باشد")

    # Verify master product exists
    exists = conn.execute(
        "SELECT id FROM master_products WHERE id = ?", (master_product_id,)
    ).fetchone()
    if not exists:
        raise NotFoundError("محصول اصلی یافت نشد", code="master_product_not_found")

    try:
        cur = conn.execute(
            """
            INSERT INTO product_identifiers_legacy
                (master_product_id, identifier_type, identifier_value,
                 issuer, supplier_id, organization_id, metadata_json)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                master_product_id, identifier_type, identifier_value,
                issuer, supplier_id, organization_id,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise ConflictError(
                f"شناسه '{identifier_value}' با نوع '{identifier_type}' قبلاً ثبت شده است",
                code="identifier_duplicate",
            ) from exc
        raise
    row = conn.execute(
        "SELECT * FROM product_identifiers_legacy WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _identifier_dict(row)


def list_identifiers(conn, master_product_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM product_identifiers_legacy WHERE master_product_id = ? AND is_active = 1 ORDER BY id",
        (master_product_id,),
    ).fetchall()
    return [_identifier_dict(r) for r in rows]


# ── Product Resolver ───────────────────────────────────────────────────────────

def resolve_product(
    conn,
    *,
    identifier_type: str,
    identifier_value: str,
    supplier_id: int | None = None,
    organization_id: int | None = None,
) -> dict | None:
    """
    Resolve an identifier to a master product.
    Returns None if no match found (caller decides whether to create an unresolved record).

    Resolution order:
    1. Exact match on (type, value, supplier_id, org_id)
    2. Exact match on (type, value, supplier_id) ignoring org
    3. Exact match on (type, value) globally
    """
    identifier_type = identifier_type.upper().strip()
    identifier_value = (identifier_value or "").strip()
    if not identifier_value:
        return None

    # Try progressively broader scopes
    queries = []
    if supplier_id and organization_id:
        queries.append((
            "SELECT pi.master_product_id FROM product_identifiers_legacy pi "
            "WHERE pi.identifier_type=? AND pi.identifier_value=? "
            "AND pi.supplier_id=? AND pi.organization_id=? AND pi.is_active=1 LIMIT 1",
            (identifier_type, identifier_value, supplier_id, organization_id),
        ))
    if supplier_id:
        queries.append((
            "SELECT pi.master_product_id FROM product_identifiers_legacy pi "
            "WHERE pi.identifier_type=? AND pi.identifier_value=? "
            "AND pi.supplier_id=? AND pi.is_active=1 LIMIT 1",
            (identifier_type, identifier_value, supplier_id),
        ))
    queries.append((
        "SELECT pi.master_product_id FROM product_identifiers_legacy pi "
        "WHERE pi.identifier_type=? AND pi.identifier_value=? "
        "AND pi.supplier_id IS NULL AND pi.organization_id IS NULL AND pi.is_active=1 LIMIT 1",
        (identifier_type, identifier_value),
    ))

    for sql, params in queries:
        row = conn.execute(sql, params).fetchone()
        if row:
            mp = conn.execute(
                "SELECT * FROM master_products WHERE id = ? AND status != 'merged'",
                (row["master_product_id"],),
            ).fetchone()
            if mp:
                return _mp_dict(mp)
    return None


def resolve_or_queue(
    conn,
    *,
    identifier_type: str,
    identifier_value: str,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    connector_account_id: int | None = None,
    external_description: str | None = None,
    metadata: dict | None = None,
) -> tuple[dict | None, bool]:
    """
    Attempt to resolve an identifier. If not found, queue it as unresolved.
    Returns (master_product_or_None, was_queued).
    """
    mp = resolve_product(
        conn,
        identifier_type=identifier_type,
        identifier_value=identifier_value,
        supplier_id=supplier_id,
        organization_id=organization_id,
    )
    if mp:
        return mp, False

    # Not found — queue as unresolved (idempotent: update if already queued)
    existing = conn.execute(
        """SELECT id FROM external_product_mappings
           WHERE external_identifier_type=? AND external_identifier_value=?
           AND COALESCE(supplier_id,-1)=COALESCE(?,-1)
           AND COALESCE(organization_id,-1)=COALESCE(?,-1)
           AND status='unresolved'""",
        (identifier_type, identifier_value, supplier_id, organization_id),
    ).fetchone()

    if not existing:
        conn.execute(
            """INSERT INTO external_product_mappings
               (external_identifier_type, external_identifier_value,
                external_description, external_metadata_json,
                source_connector_account_id, supplier_id, organization_id, status)
               VALUES (?,?,?,?,?,?,?,'unresolved')""",
            (
                identifier_type, identifier_value,
                external_description,
                json.dumps(metadata or {}, ensure_ascii=False),
                connector_account_id, supplier_id, organization_id,
            ),
        )
    return None, True


# ── External Mapping Queue ─────────────────────────────────────────────────────

def list_unresolved_mappings(conn, *, status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    where = ["1=1"]
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    else:
        where.append("status = 'unresolved'")

    clause = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM external_product_mappings WHERE {clause}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM external_product_mappings WHERE {clause} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    def _dict(r):
        return {
            "id": r["id"],
            "external_identifier_type": r["external_identifier_type"],
            "external_identifier_value": r["external_identifier_value"],
            "external_description": r["external_description"],
            "supplier_id": r["supplier_id"],
            "organization_id": r["organization_id"],
            "master_product_id": r["master_product_id"],
            "status": r["status"],
            "reviewed_by_user_id": r["reviewed_by_user_id"],
            "reviewed_at": r["reviewed_at"],
            "notes": r["notes"],
            "created_at": r["created_at"],
        }

    return {
        "items": [_dict(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def resolve_mapping(
    conn,
    *,
    mapping_id: int,
    action: str,          # 'map' | 'reject' | 'create_new'
    master_product_id: int | None = None,
    reviewer_user_id: int,
    notes: str | None = None,
    # For 'create_new' action — new product fields
    new_product_data: dict | None = None,
) -> dict:
    """Admin resolves a pending external mapping."""
    row = conn.execute(
        "SELECT * FROM external_product_mappings WHERE id = ?", (mapping_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("ردیف نگاشت یافت نشد")
    if row["status"] != "unresolved":
        raise ValidationError(f"وضعیت ردیف '{row['status']}' قابل تغییر نیست")

    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    if action == "map":
        if not master_product_id:
            raise ValidationError("master_product_id برای نگاشت الزامی است")
        # Verify product exists
        conn.execute("SELECT id FROM master_products WHERE id = ?", (master_product_id,)).fetchone() or (_ for _ in ()).throw(NotFoundError("محصول اصلی یافت نشد"))
        conn.execute(
            """UPDATE external_product_mappings
               SET status='mapped', master_product_id=?, reviewed_by_user_id=?,
                   reviewed_at=?, notes=?, updated_at=?
               WHERE id=?""",
            (master_product_id, reviewer_user_id, now, notes, now, mapping_id),
        )
        # Optionally auto-create identifier
        try:
            add_identifier(
                conn,
                master_product_id=master_product_id,
                identifier_type=row["external_identifier_type"],
                identifier_value=row["external_identifier_value"],
                supplier_id=row["supplier_id"],
                organization_id=row["organization_id"],
            )
        except ConflictError:
            pass  # Already registered — that's fine
        status = "mapped"

    elif action == "reject":
        conn.execute(
            """UPDATE external_product_mappings
               SET status='rejected', reviewed_by_user_id=?, reviewed_at=?, notes=?, updated_at=?
               WHERE id=?""",
            (reviewer_user_id, now, notes, now, mapping_id),
        )
        status = "rejected"

    elif action == "create_new":
        if not new_product_data:
            raise ValidationError("new_product_data برای ایجاد محصول جدید الزامی است")
        mp = create_master_product(conn, created_by_user_id=reviewer_user_id, **new_product_data)
        # Auto-add the identifier that triggered this mapping
        try:
            add_identifier(
                conn,
                master_product_id=mp["id"],
                identifier_type=row["external_identifier_type"],
                identifier_value=row["external_identifier_value"],
                supplier_id=row["supplier_id"],
                organization_id=row["organization_id"],
            )
        except ConflictError:
            pass
        conn.execute(
            """UPDATE external_product_mappings
               SET status='new_product_created', master_product_id=?,
                   reviewed_by_user_id=?, reviewed_at=?, notes=?, updated_at=?
               WHERE id=?""",
            (mp["id"], reviewer_user_id, now, notes, now, mapping_id),
        )
        status = "new_product_created"
        master_product_id = mp["id"]
    else:
        raise ValidationError(f"اقدام '{action}' نامعتبر است")

    return {"mapping_id": mapping_id, "status": status, "master_product_id": master_product_id}


def selection_catalog(conn, *, q='', category=None, supplier=None, page=1, page_size=12):
    """Only already-public active masters; request selection is not a sale offer."""
    if page < 1 or not 1 <= page_size <= 48:
        raise ValidationError('صفحه یا اندازه صفحه نامعتبر است')
    source = "json_extract(m.specifications_json, '$.pdf_catalog.sources[0].supplier')"
    where = ['m.status=\'active\'', 'p.is_visible=1', "NOT EXISTS(SELECT 1 FROM direct_product_profiles dp WHERE dp.master_product_id=m.id AND dp.supply_channel='retail')"]
    params = []
    if q.strip():
        where.append("(m.canonical_name_fa LIKE ? OR m.brand LIKE ? OR EXISTS (SELECT 1 FROM product_identifiers_legacy i WHERE i.master_product_id=m.id AND i.is_active=1 AND i.identifier_value LIKE ?))")
        params.extend(['%'+q.strip()+'%']*3)
    if category:
        where.append('m.category=?');params.append(category)
    if supplier:
        where.append(source+'=?');params.append(supplier)
    join = ' FROM master_products m JOIN catalog_publications p ON p.master_product_id=m.id WHERE '+' AND '.join(where)
    total=conn.execute('SELECT count(*)'+join,params).fetchone()[0]
    rows=conn.execute('SELECT m.*,p.slug,'+source+' AS source_supplier'+join+' ORDER BY m.id DESC LIMIT ? OFFSET ?',[*params,page_size,(page-1)*page_size]).fetchall()
    items=[]
    for row in rows:
        identifiers=conn.execute("SELECT identifier_value,issuer FROM product_identifiers_legacy WHERE master_product_id=? AND identifier_type='SUPPLIER_SKU' AND is_active=1 ORDER BY id",(row['id'],)).fetchall()
        items.append({'id':row['id'],'public_product_id':row['public_product_id'],'name':row['canonical_name_fa'],'category':row['category'],'brand':row['brand'],'variant':row['variant'],'size':row['size_label'],'net_quantity':row['net_quantity'],'unit':row['unit'],'package_quantity':row['package_quantity'],'supplier':row['source_supplier'],'supplier_codes':[r['identifier_value'] for r in identifiers],'slug':row['slug'],'selectable_for_request':True,'purchasable':False,'price':None,'stock':None})
    suppliers=[r[0] for r in conn.execute('SELECT DISTINCT '+source+" FROM master_products m JOIN catalog_publications p ON p.master_product_id=m.id WHERE m.status='active' AND p.is_visible=1 AND "+source+' IS NOT NULL ORDER BY 1')]
    return {'items':items,'total':total,'page':page,'total_pages':(total+page_size-1)//page_size,'suppliers':suppliers}
