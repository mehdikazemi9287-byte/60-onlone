"""فید محصولات برای موتورهای مقایسهٔ قیمت و بازارها.

Torob Product API v3 (pull): Torob POSTs one of three bodies and we answer in `torob_api_v3` shape.
  {"page": N, "sort": "date_added_desc"|"date_updated_desc"}   → page mode, 100 per page
  {"sort": "product_id_desc", "cursor": "<opaque>"?}           → cursor mode (next_cursor)
  {"page_urls": [...]} | {"page_uniques": [...]}               → direct lookup (≤ 100)
Only what a shopper could buy here is "available": a live, priced, eligible offer. The price is the
VAT-inclusive buy-box price (what the product page shows), converted to TOROB_PRICE_UNIT (default toman).

Basalam: per-seller export of their own offers with the mapped Basalam category, for bulk upload.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from app.core.errors import ValidationError
from app.services import catalog_schema_service as cs
from app.services import consumer_rights_service as crs
from app.services import storefront_service as sf

PAGE_SIZE = 100
SORTS = ("date_added_desc", "date_updated_desc", "product_id_desc")
API_VERSION = "torob_api_v3"


def price_divisor() -> int:
    unit = (os.environ.get("TOROB_PRICE_UNIT") or "toman").strip().lower()
    if unit not in ("toman", "rial"):
        raise ValidationError("TOROB_PRICE_UNIT باید toman یا rial باشد")
    return 10 if unit == "toman" else 1


def _abs(base: str, url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith(("https://", "http://")) else f"{base}/{url.lstrip('/')}"


def _iso(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).replace(" ", "T")[:19]
    return s + "Z" if len(s) == 19 else s


def _catalog(conn) -> tuple[list, dict]:
    data = sf._load(conn)
    skus = [s for s in data["skus"] if s.id > 0 and s.slug]
    return skus, data["cats"]


def _items(conn, skus: list, cats: dict, base: str) -> list[dict]:
    if not skus:
        return []
    ids = [s.id for s in skus]
    avail = sf.availability_map(conn, ids)
    lists = sf.list_price_map(conn, ids)
    vat = crs.standard_vat_bps(conn)
    div = price_divisor()
    torob_names = {r["category_id"]: r["external_name"] for r in conn.execute(
        "SELECT category_id, external_name FROM category_external_mappings WHERE source='torob' AND external_name IS NOT NULL")}
    out = []
    for s in skus:
        state, net = avail.get(s.id, ("no_offer", None))
        buyable = state == "purchasable" and net is not None and net > 0
        price = (crs.gross(net, vat) // div) if buyable else 0
        path = sf.category_path(cats, s.category_id)
        spec = {}
        for g in cs.spec_groups(conn, s.variant_id, s.category_id) if s.variant_id else []:
            for it in g["items"]:
                spec[it["label_fa"]] = it["value_fa"]
        if s.brand and "برند" not in spec:
            spec["برند"] = s.brand
        lp = lists.get(s.id) or {}
        out.append({
            "page_unique": str(s.id),
            "page_url": f"{base}/products/{s.slug}",
            "title": s.title,
            "subtitle": s.label or "",
            "current_price": int(price),
            "old_price": None,
            "availability": bool(buyable),
            "category_name": torob_names.get(s.category_id) or (path[-1]["name_fa"] if path else ""),
            "image_links": [u for u in (_abs(base, x) for x in s.images[:10]) if u],
            "spec": spec,
            "short_desc": (s.description or "")[:500],
            "date_added": _iso(s.created),
            "date_updated": _iso(max(filter(None, [s.created, lp.get("at")]), default=None)),
        })
    return out


def _slug_from_url(url, host: str) -> str | None:
    if not isinstance(url, str) or len(url) > 2000:
        return None
    parts = urlsplit(url)
    if parts.netloc and parts.netloc.lower() != host:
        return None
    segs = [p for p in parts.path.split("/") if p]
    return segs[1] if len(segs) == 2 and segs[0] == "products" else None


def torob_products(conn, body: dict, *, base_url: str) -> dict:
    """Answer one Torob Product API v3 request. Raises ValidationError (→ 400) on a malformed body."""
    if not isinstance(body, dict):
        raise ValidationError("بدنهٔ درخواست باید JSON object باشد")
    base = base_url.rstrip("/")
    host = urlsplit(base).netloc.lower()
    skus, cats = _catalog(conn)
    if "page_urls" in body or "page_uniques" in body:
        key = "page_urls" if "page_urls" in body else "page_uniques"
        vals = body.get(key)
        if not isinstance(vals, list) or not 1 <= len(vals) <= PAGE_SIZE:
            raise ValidationError(f"{key} باید فهرستی با ۱ تا ۱۰۰ مقدار باشد")
        if key == "page_urls":
            slugs = {x for x in (_slug_from_url(u, host) for u in vals) if x}
            hit = [s for s in skus if s.slug in slugs]
        else:
            wanted = {str(v) for v in vals if isinstance(v, (str, int)) and len(str(v)) <= 64}
            hit = [s for s in skus if str(s.id) in wanted]
        return {"api_version": API_VERSION, "products": _items(conn, hit, cats, base)}
    sort = body.get("sort", "date_added_desc")
    if sort not in SORTS:
        raise ValidationError("sort نامعتبر است", details={"allowed": list(SORTS)})
    if sort == "product_id_desc" and "page" not in body:
        cur = body.get("cursor")
        if cur is not None and (not isinstance(cur, str) or not cur.isdigit() or len(cur) > 18):
            raise ValidationError("cursor نامعتبر است")
        ordered = sorted(skus, key=lambda s: -s.id)
        if cur is not None:
            ordered = [s for s in ordered if s.id < int(cur)]
        chunk = ordered[:PAGE_SIZE]
        nxt = str(chunk[-1].id) if len(ordered) > PAGE_SIZE else None
        return {"api_version": API_VERSION, "products": _items(conn, chunk, cats, base), "next_cursor": nxt}
    page = body.get("page", 1)
    if type(page) is not int or page < 1 or page > 100_000:
        raise ValidationError("page باید عدد صحیح مثبت باشد")
    if sort == "date_updated_desc":
        lists = sf.list_price_map(conn, [s.id for s in skus])
        key = lambda s: (max(filter(None, [s.created, (lists.get(s.id) or {}).get("at")]), default=""), s.id)  # noqa: E731
    elif sort == "product_id_desc":
        key = lambda s: (s.id,)  # noqa: E731
    else:
        key = lambda s: (s.created or "", s.id)  # noqa: E731
    ordered = sorted(skus, key=key, reverse=True)
    total = len(ordered)
    max_pages = max(1, -(-total // PAGE_SIZE))
    chunk = ordered[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    return {"api_version": API_VERSION, "current_page": page, "total": total, "max_pages": max_pages,
            "products": _items(conn, chunk, cats, base)}


def basalam_export(conn, supplier_id: int, *, base_url: str) -> dict:
    """A seller's own active offers in Basalam upload shape (prices in rial, VAT-inclusive). Unmapped categories are flagged."""
    vat = crs.standard_vat_bps(conn)
    mapping = {r["category_id"]: (r["external_code"], r["external_name"]) for r in conn.execute(
        "SELECT category_id, external_code, external_name FROM category_external_mappings WHERE source='basalam'")}
    _, cats = _catalog(conn)
    rows = conn.execute(
        """SELECT o.id AS offer_id, o.selling_price_minor, o.stock_quantity, o.stock_reserved, o.lead_time_days, o.pricing_mode,
                  p.id AS product_id, p.slug, p.sku, p.category_id, m.id AS master_id, m.canonical_name_fa, m.brand,
                  m.description_fa, m.image_urls_json
           FROM seller_offers o JOIN products p ON p.id=o.product_id LEFT JOIN master_products m ON m.id=p.master_product_id
           WHERE o.supplier_id=? AND o.status IN ('active','out_of_stock') ORDER BY o.id LIMIT 5000""", (supplier_id,)).fetchall()
    import json as _json
    items, unmapped = [], set()
    for r in rows:
        values = cs.get_values(conn, r["master_id"]) if r["master_id"] else {}
        cat = None
        for c in reversed(sf.category_path(cats, r["category_id"])):
            if c["id"] in mapping and mapping[c["id"]][0]:
                cat = mapping[c["id"]]
                break
        if cat is None:
            unmapped.add(r["category_id"])
        try:
            imgs = [u for u in _json.loads(r["image_urls_json"] or "[]") if isinstance(u, str)][:10]
        except ValueError:
            imgs = []
        priced = r["pricing_mode"] in ("fixed", "bulk") and r["selling_price_minor"] > 0
        items.append({
            "sku": r["sku"] or f"60-{r['product_id']}", "name": r["canonical_name_fa"], "brand": r["brand"],
            "category_id": cat[0] if cat else None, "category_name": cat[1] if cat else None,
            "price_rial": crs.gross(r["selling_price_minor"], vat) if priced else None,
            "stock": max(0, int(r["stock_quantity"] or 0) - int(r["stock_reserved"] or 0)),
            "preparation_days": int(r["lead_time_days"] or 1),
            "weight_g": values.get("weight_g"), "description": (r["description_fa"] or "")[:5000],
            "photos": [u for u in (_abs(base_url.rstrip("/"), x) for x in imgs) if u],
            "source_url": f"{base_url.rstrip('/')}/products/{r['slug']}" if r["slug"] else None,
        })
    return {"format": "basalam_bulk_v1", "count": len(items), "items": items,
            "warnings": [{"code": "category_unmapped", "category_id": c} for c in sorted(x for x in unmapped if x is not None)]}
