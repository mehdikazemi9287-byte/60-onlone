"""وامبی (Vambi): جستجو و مقایسهٔ قیمت درون اکوسیستم شصت آنلاین.

  GET  /api/v1/vambi/search?q=&category=&page=&sort=relevance|price_asc|sellers
  GET  /api/v1/vambi/products/<slug>   one product, every seller side by side (Vambi product page)
  POST /api/v1/vambi/click      one «مشاهده و خرید» click → today's counter (204; nothing about the visitor is stored)
A first-page search with a query or category adds one to today's search counter: a number only — no query text,
no user id, no IP (vambi_launch_service.bump).
Each result is one exact product (SKU) with every in-ecosystem seller's offer side by side: VAT-inclusive price,
lead time, stock and city. Only marketplace sellers/shops — nothing outside the ecosystem is crawled or shown, and
nothing is fed out. Price visibility follows STOREFRONT_PRICE_VISIBILITY (this path is a public catalog surface).
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.api.v1.marketplace import _viewer_orgs
from app.core.deps import client_ip, get_db
from app.core.errors import ValidationError
from app.core.rate_limiter import InMemoryRateLimiter
from app.services import storefront_service as store
from app.services import vambi_launch_service as launch

bp = Blueprint("vambi", __name__, url_prefix="/api/v1/vambi")
PAGE_SIZE = 12
MAX_OFFERS = 8
# Click counting is a vanity number: cap one address at 30 counted clicks a minute (in memory only, never stored).
_CLICKS = InMemoryRateLimiter(30, 60)


def _summary(offers: list[dict]) -> dict:
    priced = [o["price_incl_vat_minor"] for o in offers if o.get("price_incl_vat_minor")]
    leads = [o["lead_time_days"] for o in offers if o.get("lead_time_days") is not None]
    return {"seller_count": len({o["seller"] for o in offers}), "min_price_minor": min(priced) if priced else None,
            "max_price_minor": max(priced) if priced else None, "fastest_lead_days": min(leads) if leads else None,
            "in_stock_count": sum(1 for o in offers if o.get("stock_state") == "in_stock")}


def _rows(offers: list[dict]) -> list[dict]:
    hidden = getattr(g, "price_hidden", False)
    rows = sorted(({"seller": o["seller"], "city": o["seller_city"], "price_incl_vat_minor": o["price_incl_vat_minor"],
                    "lead_time_days": o["lead_time_days"], "stock_state": o["stock_state"], "best": o["eligible"]}
                   for o in offers),
                  # hidden prices: order must not leak who is cheaper either
                  key=(lambda o: (o["seller"], o["city"] or "", o["lead_time_days"] or 0, o["stock_state"])) if hidden else
                  (lambda o: (o["price_incl_vat_minor"] is None, o["price_incl_vat_minor"] or 0)))
    if hidden:
        for o in rows:
            o["best"] = False
    return rows


@bp.get("/products/<slug>")
def product(slug: str):
    """Vambi product page: identity, breadcrumbs and every in-ecosystem seller. Nothing else from the store page
    (cart, list prices, related) so Vambi stays a comparison surface; price privacy applies as on search."""
    with get_db().read_transaction() as conn:
        d = store.product(conn, slug[:200], viewer_org_ids=_viewer_orgs())
        rows = _rows(d["offers"])
    p = d["product"]
    return jsonify({"slug": p["slug"], "title": p["title_fa"], "brand": p["brand_fa"], "description": p["description_fa"],
                    "images": (p["images"] or [])[:6], "specs": p["specs"][:20],
                    "category": d["breadcrumbs"][-1]["name_fa"] if d["breadcrumbs"] else None,
                    "breadcrumbs": [b["name_fa"] for b in d["breadcrumbs"]],
                    "summary": _summary(rows), "offers": rows})


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
    if page == 1 and (q or request.args.get("category")):
        launch.bump_safely(get_db(), "search")
    with get_db().read_transaction() as conn:
        res = store.search(conn, q=q or None, category=request.args.get("category") or None, group="sku",
                           sort="price_asc" if sort == "price_asc" else "relevance", page=page, page_size=PAGE_SIZE)
        items = []
        for c in res["items"]:
            rows = _rows(store.offers_for(conn, c["id"], viewer_org_ids=orgs))
            items.append({"slug": c["slug"], "title": c.get("title_fa") or c.get("title"), "brand": c.get("brand_fa"),
                          "image_url": c.get("image_url"), "category": c.get("category_name_fa"),
                          "summary": _summary(rows), "offers": rows[:MAX_OFFERS]})
        if sort == "sellers":
            items.sort(key=lambda i: -i["summary"]["seller_count"])
        return jsonify({"q": q, "page": page, "total": res.get("total", len(items)),
                        "total_pages": res.get("total_pages", 1), "items": items})


@bp.post("/click")
def click():
    if _CLICKS.is_allowed(client_ip() or "-"):
        launch.bump_safely(get_db(), "buy_click")
    return "", 204
