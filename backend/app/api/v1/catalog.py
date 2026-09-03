from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import get_db, get_settings
from app.core.errors import ValidationError
from app.services import catalog_service, offer_pricing_service

bp = Blueprint("catalog", __name__, url_prefix="/api/v1")


def _int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(f"پارامتر {name} باید عدد باشد") from exc


@bp.get("/categories")
def categories():
    return jsonify({"items": catalog_service.list_categories(get_db())})


@bp.get("/products")
def products():
    settings = get_settings()
    return jsonify(
        catalog_service.search_products(
            get_db(),
            exponent=settings.currency_exponent,
            q=request.args.get("q"),
            category_slug=request.args.get("category"),
            page=_int_arg("page", 1),
            page_size=_int_arg("page_size", catalog_service.DEFAULT_PAGE_SIZE),
            sort=request.args.get("sort", "newest"),
        )
    )


@bp.get("/products/<slug>")
def product_detail(slug: str):
    settings = get_settings()
    return jsonify(
        {
            "product": catalog_service.get_product_by_slug(
                get_db(), slug, exponent=settings.currency_exponent
            )
        }
    )


@bp.get("/products/<slug>/offers")
def product_offers(slug: str):
    """Real seller offers for one product — prepared for a future
    multi-offer Product Detail UI, not wired into any page yet. Never
    fabricates an offer: a product with zero real seller_offers returns
    best_offer=null and an empty offers array, exactly reflecting the DB."""
    settings = get_settings()
    db = get_db()
    product = catalog_service.get_product_by_slug(db, slug, exponent=settings.currency_exponent)
    with db.read_transaction() as conn:
        summary = offer_pricing_service.get_offer_summary(conn, product_id=product["id"])
    return jsonify(summary)
