"""Browse: categories, product search/listing, product detail."""
from __future__ import annotations

import json

from app.core.db import Database
from app.core.errors import NotFoundError, ValidationError
from app.core.money import format_minor

MAX_PAGE_SIZE = 48
DEFAULT_PAGE_SIZE = 12


def _image_url(row) -> str | None:
    """First official image from the linked master_products row, if any.

    Real, official-sourced images live in master_products.image_urls_json
    (see backend/scripts/enrich_official_images.py) — this is the one place
    that resolves it for the customer-facing catalog. A product with no
    linked master row, or an empty array, has no real image: the frontend
    falls back to image_emoji / a standard placeholder, never a guess.
    """
    keys = row.keys() if hasattr(row, "keys") else []
    if "image_urls_json" not in keys:
        return None
    raw = row["image_urls_json"]
    if not raw:
        return None
    try:
        urls = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return urls[0] if urls else None


def _product_dict(row, exponent: int) -> dict:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "sku": row["sku"],
        "title_fa": row["title_fa"],
        "brand_fa": row["brand_fa"],
        "category_slug": row["category_slug"],
        "category_name_fa": row["category_name_fa"],
        "price": format_minor(row["base_price_minor"], exponent),
        "price_minor": row["base_price_minor"],
        "currency": row["currency"],
        "image_emoji": row["image_emoji"],
        "image_url": _image_url(row),
        "rating": row["rating_x10"] / 10,
        "in_stock": bool(row["quantity_available"] > 0),
        "quantity_available": row["quantity_available"],
        "purchasable": True,
    }


def _publication_dict(row, exponent: int) -> dict:
    """A verified master-catalog identity which is visible but not sellable.

    These rows deliberately have no product/offer/inventory identity.  A
    synthetic negative API id prevents accidental collision with a commerce
    product id, while ``purchasable`` is always false and price may be NULL.
    """
    price_minor = row["verified_price_minor"]
    return {
        "id": -int(row["master_product_id"]),
        "master_product_id": row["master_product_id"],
        "slug": row["slug"],
        "sku": None,
        "title_fa": row["canonical_name_fa"],
        "brand_fa": row["brand"],
        "category_slug": row["category_slug"],
        "category_name_fa": row["category_name_fa"],
        "price": format_minor(price_minor, exponent) if price_minor is not None else None,
        "price_minor": price_minor,
        "currency": row["currency"],
        "image_emoji": None,
        "image_url": _image_url(row),
        "rating": None,
        "in_stock": False,
        "quantity_available": None,
        "purchasable": False,
        "price_status": "verified" if price_minor is not None else "pending",
    }


def list_categories(db: Database) -> list[dict]:
    rows = db.query(
        """
        SELECT c.id, c.slug, c.name_fa, c.parent_id, c.sort_order,
               ((SELECT COUNT(*) FROM products p WHERE p.category_id = c.id AND p.is_active = 1) +
                (SELECT COUNT(*) FROM catalog_publications cp
                 WHERE cp.category_slug = c.slug AND cp.is_visible = 1)) AS product_count
        FROM categories c
        ORDER BY c.sort_order, c.id
        """
    )
    return [dict(r) for r in rows]


def search_products(
    db: Database,
    *,
    exponent: int,
    q: str | None = None,
    category_slug: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str = "newest",
) -> dict:
    if page < 1:
        raise ValidationError("page باید بزرگتر از صفر باشد")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValidationError(f"page_size باید بین ۱ و {MAX_PAGE_SIZE} باشد")

    if sort not in {"newest", "price_asc", "price_desc", "rating"}:
        raise ValidationError("مقدار sort نامعتبر است")

    where = ["p.is_active = 1"]
    params: list = []
    if q and q.strip():
        # LIKE with escaped wildcards; parameterised, so no injection surface.
        needle = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(
            "(p.title_fa LIKE ? ESCAPE '\\' OR p.brand_fa LIKE ? ESCAPE '\\' "
            "OR p.description_fa LIKE ? ESCAPE '\\' OR p.sku LIKE ? ESCAPE '\\')"
        )
        params.extend([needle, needle, needle, needle])
    if category_slug and category_slug.strip():
        where.append("c.slug = ?")
        params.append(category_slug.strip())

    clause = " AND ".join(where)
    rows = db.query(
        f"""
        SELECT p.*, c.slug AS category_slug, c.name_fa AS category_name_fa,
               COALESCE(i.quantity_available, 0) AS quantity_available,
               mp.image_urls_json AS image_urls_json
        FROM products p
        JOIN categories c ON c.id = p.category_id
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN master_products mp ON mp.id = p.master_product_id
        WHERE {clause}
        """,
        params,
    )
    publication_where = ["cp.is_visible = 1"]
    publication_params: list = []
    if q and q.strip():
        needle = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        publication_where.append(
            "(mp.canonical_name_fa LIKE ? ESCAPE '\\' OR mp.brand LIKE ? ESCAPE '\\' "
            "OR COALESCE(mp.description_fa, '') LIKE ? ESCAPE '\\')"
        )
        publication_params.extend([needle, needle, needle])
    if category_slug and category_slug.strip():
        publication_where.append("cp.category_slug = ?")
        publication_params.append(category_slug.strip())
    publication_rows = db.query(
        f"""
        SELECT cp.*, mp.canonical_name_fa, mp.brand, mp.description_fa,
               mp.image_urls_json, c.name_fa AS category_name_fa
        FROM catalog_publications cp
        JOIN master_products mp ON mp.id = cp.master_product_id
        JOIN categories c ON c.slug = cp.category_slug
        WHERE {' AND '.join(publication_where)}
        """,
        publication_params,
    )
    items = [_product_dict(r, exponent) for r in rows]
    items.extend(_publication_dict(r, exponent) for r in publication_rows)
    if sort == "price_asc":
        items.sort(key=lambda x: (x["price_minor"] is None, x["price_minor"] or 0, -x["id"]))
    elif sort == "price_desc":
        items.sort(key=lambda x: (x["price_minor"] is not None, x["price_minor"] or 0, x["id"]), reverse=True)
    elif sort == "rating":
        items.sort(key=lambda x: (x["rating"] is not None, x["rating"] or 0, x["id"]), reverse=True)
    else:
        items.sort(key=lambda x: x["id"], reverse=True)
    total = len(items)
    offset = (page - 1) * page_size
    items = items[offset:offset + page_size]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "total_pages": (int(total) + page_size - 1) // page_size,
    }


def get_product_by_slug(db: Database, slug: str, *, exponent: int) -> dict:
    row = db.query_one(
        """
        SELECT p.*, c.slug AS category_slug, c.name_fa AS category_name_fa,
               COALESCE(i.quantity_available, 0) AS quantity_available,
               mp.image_urls_json AS image_urls_json
        FROM products p
        JOIN categories c ON c.id = p.category_id
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN master_products mp ON mp.id = p.master_product_id
        WHERE p.slug = ? AND p.is_active = 1
        """,
        (slug,),
    )
    if row is None:
        publication = db.query_one(
            """
            SELECT cp.*, mp.canonical_name_fa, mp.brand, mp.description_fa,
                   mp.image_urls_json, c.name_fa AS category_name_fa
            FROM catalog_publications cp
            JOIN master_products mp ON mp.id = cp.master_product_id
            JOIN categories c ON c.slug = cp.category_slug
            WHERE cp.slug = ? AND cp.is_visible = 1
            """,
            (slug,),
        )
        if publication is None:
            raise NotFoundError("محصول یافت نشد", code="product_not_found")
        data = _publication_dict(publication, exponent)
        data["description_fa"] = publication["description_fa"]
        return data
    data = _product_dict(row, exponent)
    data["description_fa"] = row["description_fa"]
    return data
