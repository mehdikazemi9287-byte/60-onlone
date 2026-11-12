"""وامبی (Vambi): جستجو و مقایسهٔ قیمت درون اکوسیستم شصت آنلاین.

  GET /api/v1/vambi/search?q=&category=&page=&sort=relevance|price_asc|sellers
Each result is one exact product (SKU) with every in-ecosystem seller's offer side by side: VAT-inclusive price,
lead time, stock and city. Only marketplace sellers/shops — nothing outside the ecosystem is crawled or shown. The
separate Vambi product (vambi.ir) reads the authenticated server-to-server feed in vambi_feed.py, not this page. Price visibility follows STOREFRONT_PRICE_VISIBILITY (this path is a public catalog surface).
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.api.v1.marketplace import _viewer_orgs
from app.core.deps import get_db
from app.core.errors import ValidationError
from app.services import storefront_service as store

bp = Blueprint("vambi", __name__, url_prefix="/api/v1/vambi")
PAGE_SIZE = 12
MAX_OFFERS = 8


def _summary(offers: list[dict]) -> dict:
    priced = [o["price_incl_vat_minor"] for o in offers if o.get("price_incl_vat_minor")]
    leads = [o["lead_time_days"] for o in offers if o.get("lead_time_days") is not None]
    return {"seller_count": len({o["seller"] for o in offers}), "min_price_minor": min(priced) if priced else None,
            "max_price_minor": max(priced) if priced else None, "fastest_lead_days": min(leads) if leads else None,
            "in_stock_count": sum(1 for o in offers if o.get("stock_state") == "in_stock")}


@bp.get("/search")
def search():
    q = (request.args.get("q") or "").strip()[:120]
    sort = request.args.get("sort", "relevance")
    if sort not in ("relevance", "price_asc", "sellers"):
        raise ValidationError("مرتب‌سازی نامعتبر است")
    try:
        page = max(1, min(500, int(request.args.get("page", 1))))
    except ValueError:
        raise ValidationError("صفحه نامعتبر است") from None
    orgs = _viewer_orgs()
    with get_db().read_transaction() as conn:
        res = store.search(conn, q=q or None, category=request.args.get("category") or None, group="sku",
                           sort="price_asc" if sort == "price_asc" else "relevance", page=page, page_size=PAGE_SIZE)
        items = []
        for c in res["items"]:
            offers = store.offers_for(conn, c["id"], viewer_org_ids=orgs)
            hidden = getattr(g, "price_hidden", False)
            rows = sorted(({"seller": o["seller"], "city": o["seller_city"], "price_incl_vat_minor": o["price_incl_vat_minor"],
                            "lead_time_days": o["lead_time_days"], "stock_state": o["stock_state"], "best": o["eligible"]}
                           for o in offers),
                          # hidden prices: order must not leak who is cheaper either
                          key=(lambda o: o["seller"]) if hidden else
                          (lambda o: (o["price_incl_vat_minor"] is None, o["price_incl_vat_minor"] or 0)))
            if hidden:
                for o in rows:
                    o["best"] = False
            items.append({"slug": c["slug"], "title": c.get("title_fa") or c.get("title"), "brand": c.get("brand_fa"),
                          "image_url": c.get("image_url"), "category": c.get("category_name_fa"),
                          "summary": _summary(rows), "offers": rows[:MAX_OFFERS]})
        if sort == "sellers":
            items.sort(key=lambda i: -i["summary"]["seller_count"])
        return jsonify({"q": q, "page": page, "total": res.get("total", len(items)),
                        "total_pages": res.get("total_pages", 1), "items": items})
