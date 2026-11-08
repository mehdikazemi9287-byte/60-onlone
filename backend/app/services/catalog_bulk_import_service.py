"""Safe bulk import for the canonical and storefront catalogues.

One physical product is created once in ``master_products``.  A row is only
published to the storefront when ``publish_status=active`` and SKU, price and
stock are all supplied.  Preview is the default; writes require ``confirm``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid

from app.core.errors import ValidationError

REQUIRED_COLUMNS = {"canonical_name_fa", "category_slug"}
ALLOWED_STATUS = {"draft", "active", "skip"}


def _clean(value) -> str:
    return str(value or "").strip()


def _integer(value, *, field: str, minimum: int = 0, allow_blank: bool = True):
    text = _clean(value)
    if not text and allow_blank:
        return None
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError(f"{field} باید عدد صحیح باشد")
    result = int(text)
    if result < minimum:
        raise ValueError(f"{field} باید حداقل {minimum} باشد")
    return result


def parse_catalog_csv(csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValidationError("ستون‌های الزامی وجود ندارند: " + ", ".join(sorted(missing)))

    rows, errors = [], []
    seen_skus = set()
    for number, raw in enumerate(reader, start=2):
        item = {key: _clean(value) for key, value in raw.items() if key}
        row_errors = []
        status = (item.get("publish_status") or item.get("row_status") or "draft").lower()
        if status not in ALLOWED_STATUS:
            row_errors.append("publish_status باید draft، active یا skip باشد")
        if not item.get("canonical_name_fa"):
            row_errors.append("canonical_name_fa خالی است")
        if not item.get("category_slug"):
            row_errors.append("category_slug خالی است")
        sku = item.get("sku", "").upper()
        if sku:
            if sku in seen_skus:
                row_errors.append("SKU در همین فایل تکراری است")
            seen_skus.add(sku)
            item["sku"] = sku
        try:
            item["package_quantity"] = (
                _integer(item.get("package_quantity"), field="package_quantity", minimum=1)
            )
            item["vat_rate_bps"] = _integer(
                item.get("vat_rate_bps"), field="vat_rate_bps", minimum=0
            )
            item["price_minor"] = _integer(item.get("price_minor"), field="price_minor", minimum=0)
            item["stock_quantity"] = _integer(
                item.get("stock_quantity"), field="stock_quantity", minimum=0
            )
        except ValueError as exc:
            row_errors.append(str(exc))

        item["publish_status"] = status

        parsed = {
            "row_number": number,
            "status": "invalid" if row_errors else status,
            "errors": row_errors,
            "data": item,
        }
        rows.append(parsed)
        if row_errors:
            errors.append({"row_number": number, "errors": row_errors})

    return {
        "rows": rows,
        "total": len(rows),
        "valid": sum(1 for row in rows if not row["errors"] and row["status"] != "skip"),
        "skipped": sum(1 for row in rows if row["status"] == "skip"),
        "invalid": len(errors),
        "errors": errors,
    }


def _find_master(conn, item):
    if item.get("sku"):
        row = conn.execute(
            "SELECT master_product_id FROM product_identifiers_legacy "
            "WHERE identifier_type='INTERNAL' AND identifier_value=? LIMIT 1",
            (item["sku"],),
        ).fetchone()
        if row:
            return int(row["master_product_id"])
    rows = conn.execute(
        "SELECT id FROM master_products WHERE canonical_name_fa=? "
        "AND COALESCE(brand,'')=? AND COALESCE(model,'')=? "
        "AND COALESCE(variant,'')=? AND COALESCE(size_label,'')=? "
        "AND COALESCE(net_quantity,'')=? AND status!='merged'",
        (
            item["canonical_name_fa"],
            item.get("brand", ""),
            item.get("model", ""),
            item.get("variant", ""),
            item.get("size_label", ""),
            item.get("net_quantity", ""),
        ),
    ).fetchall()
    if len(rows) > 1:
        raise ValidationError("تطبیق مبهم کالا؛ شناسه یکتا را مشخص کنید")
    return int(rows[0]["id"]) if rows else None


def _upsert_category(conn, item):
    slug = item["category_slug"]
    name = item.get("category_name_fa") or slug
    row = conn.execute("SELECT id,admin_managed FROM categories WHERE slug=?", (slug,)).fetchone()
    if row:
        if item.get("category_name_fa") and not row["admin_managed"]:
            conn.execute("UPDATE categories SET name_fa=? WHERE id=?", (name, row["id"]))
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO categories (slug,name_fa,sort_order) VALUES (?,?,?)",
        (slug, name, 900),
    )
    return int(cursor.lastrowid)


def _upsert_master(conn, item):
    master_id = _find_master(conn, item)
    existing = (
        conn.execute("SELECT * FROM master_products WHERE id=?", (master_id,)).fetchone()
        if master_id
        else None
    )
    if existing:
        item = dict(item)
        for field in (
            "canonical_name_en",
            "brand",
            "manufacturer",
            "subcategory",
            "product_type",
            "model",
            "variant",
            "size_label",
            "unit",
            "net_quantity",
            "description_fa",
            "country_of_origin",
        ):
            if not item.get(field):
                item[field] = existing[field]
        if item.get("vat_rate_bps") is None:
            item["vat_rate_bps"] = existing["vat_rate_bps"]
    # image_urls_json is NOT NULL on every supported schema version. A
    # catalogue row without an image still needs a valid empty JSON array.
    image_urls_json = (
        json.dumps([item["image_url"]], ensure_ascii=False)
        if item.get("image_url")
        else (existing["image_urls_json"] if existing else "[]")
    )
    values = (
        item["canonical_name_fa"],
        item.get("canonical_name_en") or None,
        item.get("brand") or None,
        item.get("manufacturer") or None,
        item["category_slug"],
        item.get("subcategory") or None,
        item.get("product_type") or None,
        item.get("model") or None,
        item.get("variant") or None,
        item.get("size_label") or None,
        item.get("unit") or None,
        item["package_quantity"],
        item.get("net_quantity") or None,
        item.get("description_fa") or None,
        image_urls_json,
        item.get("country_of_origin") or None,
        item["vat_rate_bps"] if item["vat_rate_bps"] is not None else 1000,
        existing["status"] if existing and conn.execute("SELECT 1 FROM direct_product_profiles WHERE master_product_id=?",(master_id,)).fetchone() else ("active" if item.get("publish_status", "draft").lower() == "active" else "draft"),
    )
    if master_id:
        conn.execute(
            """UPDATE master_products SET canonical_name_fa=?,canonical_name_en=?,brand=?,
            manufacturer=?,category=?,subcategory=?,product_type=?,model=?,variant=?,
            size_label=?,unit=COALESCE(?,unit),package_quantity=COALESCE(?,package_quantity),net_quantity=?,description_fa=?,
            image_urls_json=COALESCE(?,image_urls_json),country_of_origin=?,vat_rate_bps=?,
            status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (*values, master_id),
        )
    else:
        cursor = conn.execute(
            """INSERT INTO master_products
            (public_product_id,canonical_name_fa,canonical_name_en,brand,manufacturer,
             category,subcategory,product_type,model,variant,size_label,unit,
             package_quantity,net_quantity,description_fa,image_urls_json,country_of_origin,
             vat_rate_bps,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), *values),
        )
        master_id = int(cursor.lastrowid)
    if item.get("sku"):
        conn.execute(
            """INSERT INTO product_identifiers_legacy
            (master_product_id,identifier_type,identifier_value,issuer)
            SELECT ?, 'INTERNAL', ?, ? WHERE NOT EXISTS (
              SELECT 1 FROM product_identifiers_legacy
              WHERE identifier_type='INTERNAL' AND identifier_value=?
            )""",
            (master_id, item["sku"], item.get("brand") or None, item["sku"]),
        )
    if item.get("barcode"):
        conn.execute(
            """INSERT INTO product_identifiers_legacy
            (master_product_id,identifier_type,identifier_value,issuer)
            SELECT ?, 'BARCODE', ?, ? WHERE NOT EXISTS (
              SELECT 1 FROM product_identifiers_legacy
              WHERE identifier_type='BARCODE' AND identifier_value=?
            )""",
            (master_id, item["barcode"], item.get("brand") or None, item["barcode"]),
        )
    return master_id


def _upsert_storefront(conn, item, master_id, category_id):
    if item.get("publish_status", "draft").lower() != "active":
        return None
    if any(item.get(field) in (None, "") for field in ("sku", "price_minor", "stock_quantity")):
        linked = conn.execute(
            "SELECT id FROM products WHERE master_product_id=? AND is_active=1", (master_id,)
        ).fetchone()
        if linked:
            return int(linked["id"])
        master = conn.execute(
            "SELECT public_product_id FROM master_products WHERE id=?", (master_id,)
        ).fetchone()
        slug = item.get("slug") or "catalog-" + master["public_product_id"]
        conn.execute(
            """INSERT INTO catalog_publications
            (master_product_id,slug,category_slug,currency,is_visible,is_purchasable,price_status,publication_reason,created_at,updated_at)
            VALUES (?,?,?,?,1,0,'pending','admin_catalog_import',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            ON CONFLICT(master_product_id) DO UPDATE SET category_slug=excluded.category_slug,is_visible=1,updated_at=CURRENT_TIMESTAMP""",
            (master_id, slug, item["category_slug"], item.get("currency") or "IRR"),
        )
        return -master_id
    sku = item["sku"]
    row = conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()
    if not row:row=conn.execute("SELECT a.product_id AS id FROM product_code_aliases a JOIN products p ON p.id=a.product_id WHERE a.code=? AND p.master_product_id=?",(sku,master_id)).fetchone()
    if row and conn.execute("SELECT 1 FROM direct_product_profiles WHERE master_product_id=?",(master_id,)).fetchone():
        slug=conn.execute("SELECT slug FROM products WHERE id=?",(row["id"],)).fetchone()[0]
    else:slug = item.get("slug") or sku.lower().replace("_", "-")
    values = (
        slug,
        item["canonical_name_fa"],
        item.get("description_fa") or "",
        item.get("brand") or "",
        category_id,
        item["price_minor"],
        item.get("currency") or "IRR",
        item.get("image_emoji") or "📦",
        master_id,
    )
    if row:
        product_id = int(row["id"])
        conn.execute(
            """UPDATE products SET slug=?,title_fa=?,description_fa=?,brand_fa=?,
            category_id=?,base_price_minor=?,currency=?,image_emoji=?,master_product_id=?,
            is_active=1 WHERE id=?""",
            (*values, product_id),
        )
    else:
        cursor = conn.execute(
            """INSERT INTO products
            (slug,sku,title_fa,description_fa,brand_fa,category_id,base_price_minor,
             currency,image_emoji,master_product_id,is_active)
            VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (slug, sku, *values[1:]),
        )
        product_id = int(cursor.lastrowid)
    conn.execute(
        """INSERT INTO inventory (product_id,quantity_available,quantity_reserved)
        VALUES (?,?,0) ON CONFLICT(product_id) DO UPDATE SET
        quantity_available=excluded.quantity_available,updated_at=CURRENT_TIMESTAMP""",
        (product_id, item["stock_quantity"]),
    )
    return product_id


def import_catalog_csv(conn, csv_text: str, *, confirm: bool = False) -> dict:
    parsed = parse_catalog_csv(csv_text)
    if parsed["invalid"]:
        return {**parsed, "confirmed": False, "created": 0, "updated": 0, "published": 0}
    if not confirm:
        return {**parsed, "confirmed": False, "created": 0, "updated": 0, "published": 0}

    created = updated = published = 0
    for row in parsed["rows"]:
        if row["status"] == "skip":
            continue
        item = row["data"]
        existed = _find_master(conn, item) is not None
        category_id = _upsert_category(conn, item)
        master_id = _upsert_master(conn, item)
        product_id = _upsert_storefront(conn, item, master_id, category_id)
        updated += int(existed)
        created += int(not existed)
        published += int(product_id is not None)
    return {
        **parsed,
        "confirmed": True,
        "created": created,
        "updated": updated,
        "published": published,
    }
