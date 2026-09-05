"""Browse: categories, product search/listing, product detail."""
from __future__ import annotations

import json

from app.core.db import Database
from app.core.errors import NotFoundError, ValidationError
from app.core.money import format_minor
from app.services import sale_eligibility

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


def _product_dict(row, exponent: int, verified_offer=None) -> dict:
    price_minor = int(verified_offer["selling_price_minor"]) if verified_offer is not None else None
    available = int(verified_offer["available"]) if verified_offer is not None else None
    return {
        "id": row["id"],
        "slug": row["slug"],
        "sku": row["sku"],
        "title_fa": row["title_fa"],
        "brand_fa": row["brand_fa"],
        "category_slug": row["category_slug"],
        "category_name_fa": row["category_name_fa"],
        "price": format_minor(price_minor, exponent) if price_minor is not None else None,
        "price_minor": price_minor,
        "currency": row["currency"],
        "image_emoji": None,
        "image_url": _image_url(row),
        "rating": None,
        "in_stock": verified_offer is not None,
        "purchasable": verified_offer is not None,
        "quantity_available": available,
    }


def list_categories(db: Database) -> list[dict]:
    rows = db.query(
        """
        SELECT c.id, c.slug, c.name_fa, c.parent_id, c.sort_order,
               (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id AND p.is_active = 1) AS product_count
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

    order_by = {
        "newest": "p.id DESC",
        "price_asc": "p.base_price_minor ASC, p.id DESC",
        "price_desc": "p.base_price_minor DESC, p.id DESC",
        "rating": "p.rating_x10 DESC, p.id DESC",
    }.get(sort)
    if order_by is None:
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
    total = db.query_one(
        f"SELECT COUNT(*) AS n FROM products p JOIN categories c ON c.id = p.category_id WHERE {clause}",
        params,
    )["n"]

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
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, (page - 1) * page_size],
    )
    return {
        "items": [
            _product_dict(r, exponent, sale_eligibility.eligible_offer_db(db, int(r["id"])))
            for r in rows
        ],
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
        raise NotFoundError("محصول یافت نشد", code="product_not_found")
    data = _product_dict(
        row, exponent, sale_eligibility.eligible_offer_db(db, int(row["id"]))
    )
    data["description_fa"] = row["description_fa"]
    return data
