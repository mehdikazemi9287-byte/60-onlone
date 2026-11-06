"""Customer-facing marketplace catalog: taxonomy, typed search, product (family/variant) detail, offers.

Only REAL products, offers and sellers are shown (TEST as well in isolated COMMERCE_TEST_MODE);
DEMO rows never reach a customer. Prices exist only where a verified offer exists — otherwise the
product is shown with a quote/purchase-request call to action, never a guessed price.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

from app.core.errors import NotFoundError, ValidationError
from app.services import sale_eligibility as se
from app.services import product_channel_policy as policy
from app.services import text_norm as tn

MAX_PAGE_SIZE = 48
_CACHE: dict = {}
_LOCK = threading.Lock()


def _prov_sql() -> str:
    return ",".join(f"'{p}'" for p in se.allowed_provenance())


def _json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


@dataclass
class Sku:
    id: int
    slug: str
    sku: str | None
    title: str
    brand: str | None
    variant_id: int
    family_id: int | None
    family_slug: str | None
    family_title: str
    category_id: int | None
    label: str | None
    attributes: dict
    images: list
    description: str
    specs: dict
    provenance: str
    created: str
    supply_channel: str = "both"
    search: dict = field(default_factory=dict)


def _signature(conn) -> tuple:
    return tuple(conn.execute(
        """SELECT (SELECT COUNT(*)||':'||COALESCE(MAX(id),0) FROM products),
                  (SELECT COALESCE(MAX(updated_at),'') FROM master_products),
                  (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),'') FROM product_families),
                  (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),'') FROM seller_offers),
                  (SELECT COUNT(*) FROM categories), (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),'') FROM catalog_publications WHERE is_visible=1), (SELECT COUNT(*) FROM supplier_users)""").fetchone()) + se.allowed_provenance()


def _load(conn) -> dict:
    sig = _signature(conn)
    with _LOCK:
        if _CACHE.get("sig") == sig:
            return _CACHE["data"]
    cats = {r["id"]: dict(r) for r in conn.execute("SELECT id, slug, name_fa, parent_id, level, sort_order FROM categories")}
    prov = _prov_sql()
    skus: list[Sku] = []
    for r in conn.execute(f"""
            SELECT p.id, p.slug, p.sku, p.provenance, p.created_at, p.category_id AS legacy_cat,
                   m.id AS vid, m.canonical_name_fa, m.brand, m.variant_label, m.attributes_json, m.image_urls_json,
                   m.description_fa, m.specifications_json, m.product_type,
                   f.id AS fid, f.slug AS fslug, f.title_fa AS ftitle, f.category_id AS fcat,dp.supply_channel AS policy_channel
            FROM products p JOIN master_products m ON m.id = p.master_product_id
            LEFT JOIN product_families f ON f.id = m.family_id
            LEFT JOIN direct_product_profiles dp ON dp.master_product_id=m.id
            WHERE p.is_active = 1 AND m.status='active' AND p.provenance IN ({prov}) AND m.provenance IN ({prov})
              AND (f.id IS NULL OR f.provenance IN ({prov}))"""):
        skus.append(Sku(
            id=r["id"], slug=r["slug"], sku=r["sku"], title=r["canonical_name_fa"], brand=tn.canonical_brand(r["brand"]),
            variant_id=r["vid"], family_id=r["fid"], family_slug=r["fslug"], family_title=r["ftitle"] or r["canonical_name_fa"],
            category_id=r["fcat"] or r["legacy_cat"], label=r["variant_label"], attributes=_json(r["attributes_json"], {}),
            images=[u for u in _json(r["image_urls_json"], []) if isinstance(u, str)], description=r["description_fa"] or "",
            specs=_json(r["specifications_json"], {}), provenance=r["provenance"], created=r["created_at"] or "",supply_channel=r["policy_channel"] or "both"))
    # Published inquiry-only masters have no invented commerce product/offer.
    for r in conn.execute(f"""SELECT m.*,cp.slug,c.id AS catalog_category_id,dp.supply_channel AS policy_channel,
                    COALESCE(dp.sku,(SELECT i.identifier_value FROM product_identifiers_legacy i WHERE i.master_product_id=m.id AND i.identifier_type='SUPPLIER_SKU' AND i.is_active=1 ORDER BY i.id LIMIT 1)) AS source_sku
             FROM catalog_publications cp JOIN master_products m ON m.id=cp.master_product_id LEFT JOIN direct_product_profiles dp ON dp.master_product_id=m.id
             LEFT JOIN categories c ON c.slug=cp.category_slug
             WHERE cp.is_visible=1 AND m.status='active' AND m.provenance IN ({prov})
               AND NOT EXISTS (SELECT 1 FROM products p WHERE p.master_product_id=m.id AND p.is_active=1)"""):
        # Keep raw provenance out of UI specifications; no guessed attributes.
        unit_specs = {k:v for k,v in {'unit':r['unit'],'package_quantity':r['package_quantity'],'net_quantity':r['net_quantity']}.items() if v is not None}
        sources = _json(r['specifications_json'],{}).get('pdf_catalog',{}).get('sources',[])
        if sources and sources[0].get('supplier'):
            unit_specs['تأمین‌کننده منبع'] = sources[0]['supplier']
        skus.append(Sku(id=-int(r['id']),slug=r['slug'],sku=r['source_sku'],title=r['canonical_name_fa'],brand=tn.canonical_brand(r['brand']) if r['brand'] else None,variant_id=r['id'],family_id=None,family_slug=None,family_title=r['canonical_name_fa'],category_id=r['catalog_category_id'],label=r['variant'],attributes={k:v for k,v in {'variant':r['variant'],'size':r['size_label'],'net_quantity':r['net_quantity']}.items() if v is not None},images=[u for u in _json(r['image_urls_json'],[]) if isinstance(u,str)],description=r['description_fa'] or '',specs=unit_specs,provenance=r['provenance'],created=r['created_at'] or '',supply_channel=r['policy_channel'] or 'both'))
    sellers: dict[int, set] = {}
    for r in conn.execute(f"""SELECT so.product_id, s.display_name FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                              WHERE so.status='active' AND s.status='active' AND so.provenance IN ({prov}) AND s.provenance IN ({prov}) AND {policy.offer_sql('so.product_id','so.channel')}"""):
        sellers.setdefault(r["product_id"], set()).add(r["display_name"])
    for s in skus:
        path = category_path(cats, s.category_id)
        s.search = {
            "title": tn.normalize(s.title), "title_c": tn.compact(s.title), "fam": tn.normalize(s.family_title),
            "brand": tn.normalize(s.brand) + " " + " ".join(k for k, v in tn.BRAND_ALIASES.items() if v == s.brand), "cat": " ".join(tn.normalize(c["name_fa"]) for c in path),
            "sku": tn.normalize(s.sku), "variant": tn.normalize(s.label or ""), "source_supplier": tn.normalize(s.specs.get("تأمین‌کننده منبع")),
            "attrs": " ".join(tn.normalize(str(v)) for v in s.attributes.values()),
            "seller": " ".join(tn.normalize(x) for x in sellers.get(s.id, ())),
            "path_ids": {c["id"] for c in path}, "path_slugs": {c["slug"] for c in path},
        }
        s.search["words"] = set(" ".join(v for k, v in s.search.items() if isinstance(v, str)).split())
    index: dict[str, set] = {}
    for s in skus:
        for w in s.search["words"]:
            index.setdefault(w, set()).add(s.id)
    data = {"cats": cats, "skus": skus, "by_slug": {s.slug: s for s in skus}, "by_id": {s.id: s for s in skus},
            "index": index, "vocab": sorted(index)}
    with _LOCK:
        _CACHE.update(sig=sig, data=data)
    return data


def category_path(cats: dict, cat_id) -> list[dict]:
    out, seen = [], set()
    while cat_id and cat_id in cats and cat_id not in seen:
        seen.add(cat_id)
        out.append(cats[cat_id])
        cat_id = cats[cat_id]["parent_id"]
    return list(reversed(out))


# ── Offers ──

def _gross(net, vat_bps):
    from app.services.consumer_rights_service import gross
    return gross(net, vat_bps)


def offers_for(conn, sku_id: int, *, viewer_org_ids: tuple = ()) -> list[dict]:
    from app.services import consumer_rights_service as _crs
    vat_bps = _crs.standard_vat_bps(conn)
    prov = _prov_sql()
    rows = conn.execute(f"""
        SELECT so.*, s.display_name AS seller, s.provenance AS seller_provenance, sl.city AS seller_city,
               (so.stock_quantity - so.stock_reserved) AS available,
               datetime(so.last_price_confirmed_at) >= datetime('now','-24 hours') AS price_fresh,
               datetime(so.last_inventory_confirmed_at) >= datetime('now','-24 hours') AS stock_fresh
        FROM seller_offers so JOIN suppliers s ON s.id = so.supplier_id
        LEFT JOIN supplier_locations sl ON sl.id = so.supplier_location_id
        WHERE so.product_id = ? AND so.status = 'active' AND s.status = 'active'
          AND so.provenance IN ({prov}) AND s.provenance IN ({prov}) AND {policy.offer_sql('so.product_id','so.channel')}
          AND (so.valid_until IS NULL OR so.valid_until >= date('now'))
        ORDER BY so.selling_price_minor, so.id""", (sku_id,)).fetchall()
    eligible = se.eligible_offer_conn(conn, sku_id)
    out = []
    for o in rows:
        scope=policy.effective(conn,sku_id,o["channel"])
        if scope is None:continue
        priced = o["pricing_mode"] in ("fixed", "bulk") and bool(o["price_fresh"]) and o["selling_price_minor"] > 0
        stock_state = "unknown" if not o["stock_fresh"] else ("in_stock" if o["available"] > 0 else "out_of_stock")
        if o["pricing_mode"] == "out_of_stock":
            stock_state = "out_of_stock"
        tiers = {"retail": [], "organization": []}
        for t in conn.execute("""SELECT channel, organization_id, min_qty, max_qty, unit_price_minor FROM offer_price_tiers
                                 WHERE offer_id=? AND datetime(confirmed_at) >= datetime('now','-24 hours') ORDER BY channel, min_qty""", (o["id"],)):
            if t["channel"] not in policy.channels(scope):continue
            if t["channel"] == "organization" and t["organization_id"] and t["organization_id"] not in viewer_org_ids:
                continue
            if t["channel"] == "organization" and not viewer_org_ids:
                continue
            tiers[t["channel"]].append({"min_qty": t["min_qty"], "max_qty": t["max_qty"], "unit_price_minor": t["unit_price_minor"],
                                        "contract": bool(t["organization_id"])})
        out.append({
            "offer_id": o["id"], "seller": o["seller"], "seller_city": o["seller_city"], "pricing_mode": o["pricing_mode"],
            "channel": scope, "declared_channel":o["channel"], "allowed_channels":list(policy.channels(scope)), "price_minor": o["selling_price_minor"] if priced else None, "price_confirmed": priced,
            "stock_state": stock_state, "available": o["available"] if o["stock_fresh"] else None,
            "min_order_quantity": o["min_order_quantity"] or 1, "max_order_quantity": o["max_order_quantity"],
            "lead_time_days": o["lead_time_days"], "valid_until": o["valid_until"], "tiers": tiers,
            "provenance": o["provenance"], "eligible": bool(eligible and eligible["id"] == o["id"]),
            "list_price_minor": o["selling_price_minor"] if (o["pricing_mode"] in ("fixed", "bulk") and o["selling_price_minor"] > 0
                                                             and o["last_price_confirmed_at"]) else None,
            "list_price_at": o["last_price_confirmed_at"],
            # Consumer law: the shown price must include VAT; price_minor stays the net used by checkout.
            "price_incl_vat_minor": _crs.gross(o["selling_price_minor"] if priced else None, vat_bps),
            "vat_bps": vat_bps,
        })
    return out


def availability_map(conn, sku_ids) -> dict[int, tuple[str, int | None]]:
    """Availability of many SKUs in two queries (same eligibility rule as sale_eligibility)."""
    ids = list(sku_ids)
    if not ids:
        return {}
    out = {i: ("no_offer", None) for i in ids}
    prov = _prov_sql()
    for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"""SELECT DISTINCT so.product_id FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                                  WHERE so.product_id IN ({marks}) AND so.status='active' AND s.status='active'
                                    AND so.provenance IN ({prov}) AND s.provenance IN ({prov}) AND {policy.offer_sql('so.product_id','so.channel')}""", chunk):
            out[r[0]] = ("quote", None)
        if se.sales_enabled() or se._test_override_enabled():
            sql = se._sql().replace("WHERE so.product_id = ?", f"WHERE so.product_id IN ({marks})") \
                .replace("ORDER BY so.selling_price_minor ASC, so.id ASC\nLIMIT 1", "")
            for r in conn.execute(f"SELECT product_id, MIN(selling_price_minor) FROM ({sql.replace('SELECT so.id,', 'SELECT so.product_id, so.id,', 1)}) GROUP BY product_id", chunk):
                out[r[0]] = ("purchasable", int(r[1]))
    return out


def list_price_map(conn, sku_ids) -> dict[int, dict]:
    """Latest known supplier/list price per SKU (with its confirmation date), independent of the 24-hour
    retail freshness rule. It is never a sale price: carts and orders use only eligible (live) offers.
    org_only = every listed offer is on the organization channel (bulk/B2B)."""
    ids = list(sku_ids)
    out: dict[int, dict] = {}
    prov = _prov_sql()
    for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"""SELECT so.product_id, MIN(so.selling_price_minor) AS price, MAX(so.last_price_confirmed_at) AS at,
                                         MIN((so.channel = 'organization') OR EXISTS(SELECT 1 FROM products lp JOIN direct_product_profiles ld ON ld.master_product_id=lp.master_product_id WHERE lp.id=so.product_id AND ld.supply_channel='organization')) AS org_only
                                  FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                                  WHERE so.product_id IN ({marks}) AND so.status='active' AND s.status='active'
                                    AND so.provenance IN ({prov}) AND s.provenance IN ({prov}) AND {policy.offer_sql('so.product_id','so.channel')}
                                    AND so.pricing_mode IN ('fixed','bulk') AND so.selling_price_minor > 0
                                    AND so.last_price_confirmed_at IS NOT NULL
                                    AND (so.valid_until IS NULL OR so.valid_until >= date('now'))
                                  GROUP BY so.product_id""", chunk):
            out[r[0]] = {"price": int(r[1]), "at": r[2], "org_only": bool(r[3])}
    return out


def _availability(conn, sku_id: int) -> tuple[str, int | None]:
    offer = se.eligible_offer_conn(conn, sku_id)
    if offer is not None and offer["id"]:
        return "purchasable", int(offer["selling_price_minor"])
    prov = _prov_sql()
    has = conn.execute(f"""SELECT so.pricing_mode FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                           WHERE so.product_id=? AND so.status='active' AND s.status='active'
                             AND so.provenance IN ({prov}) AND s.provenance IN ({prov}) AND {policy.offer_sql('so.product_id','so.channel')} LIMIT 1""", (sku_id,)).fetchone()
    return ("quote" if has else "no_offer"), None


def _card(conn, group: list[Sku], cats: dict, avail: dict | None = None, lists: dict | None = None) -> dict:
    rep = min(group, key=lambda s: s.id)
    avail = avail if avail is not None else availability_map(conn, [s.id for s in group])
    lists = lists if lists is not None else list_price_map(conn, [s.id for s in group])
    known = [lists[s.id] for s in group if s.id in lists]
    states = [(s, *avail[s.id]) for s in group]
    prices = [p for _, st, p in states if p is not None]
    purchasable = any(st == "purchasable" for _, st, _ in states)
    path = category_path(cats, rep.category_id)
    image = next((s.images[0] for s in sorted(group, key=lambda s: s.id) if s.images), None)
    return {
        "kind": "product", "id": rep.id, "slug": rep.slug, "sku": rep.sku, "master_product_id": rep.variant_id,
        "title_fa": rep.family_title if len(group) > 1 else rep.title, "brand_fa": rep.brand,
        # category_slug keeps its original meaning (the category-level node); leaf_slug is the deepest type.
        "category_slug": next((c["slug"] for c in path if c["level"] == "category"), path[-1]["slug"] if path else None),
        "category_name_fa": path[-1]["name_fa"] if path else None, "leaf_slug": path[-1]["slug"] if path else None,
        "category_path": [{"slug": c["slug"], "name_fa": c["name_fa"]} for c in path],
        "family_slug": rep.family_slug, "variant_count": len(group),
        "variant_labels": [s.label for s in sorted(group, key=lambda s: (s.attributes.get("weight_g") or s.attributes.get("volume_ml") or 0, s.id)) if s.label],
        "price_minor": min(prices) if prices else None, "price_from": len(prices) > 1, "currency": "IRR",
        "image_url": image, "image_emoji": None, "rating": None,
        "in_stock": purchasable, "purchasable": purchasable, "quantity_available": None,
        "availability": "purchasable" if purchasable else ("quote" if any(st == "quote" for _, st, _ in states) else "no_offer"),
        "inquiry_only": not purchasable, "price_status": "verified" if prices else "pending",
        "provenance": rep.provenance,
        # Latest known supplier/list price — informational, not a sale price (see list_price_map).
        "list_price_minor": min(k["price"] for k in known) if known else None,
        "list_price_at": max(k["at"] for k in known) if known else None,
        "org_only": all(s.supply_channel=="organization" for s in group),
        "allowed_channels":sorted({ch for item in group for ch in policy.channels(item.supply_channel)}),
        "supply_channel":rep.supply_channel,
    }


def _score(s: Sku, q_tokens: list[str], q_compact: str) -> int:
    d = s.search
    score = 0
    if q_compact and q_compact in d["title_c"]:
        score += 12
        if d["title_c"].startswith(q_compact):
            score += 4  # the query is the product's head noun («برنج …»), not a modifier («غذای کودک … برنج»)
    for t in q_tokens:
        best = 0
        if t in d["title"].split() or t in d["fam"].split():
            best = 5
        elif any(w.startswith(t) for w in d["title"].split()) and len(t) >= 2:
            best = 3
        if t in d["brand"].split() or (d["brand"] and t == d["brand"].replace(" ", "")):
            best = max(best, 5)
        if t == d["sku"] or t in d["sku"].split() or (len(t) >= 4 and t in d["sku"]):
            best = max(best, 8)
        if t in d["cat"].split():
            best = max(best, 3)
        if t in d["variant"].split() or t in d["attrs"].split():
            best = max(best, 2)
        if t in d["seller"].split():
            best = max(best, 1)
        if not best and len(t) >= 4 and any(len(w) >= 4 and tn.edit_distance_le1(t, w) for w in d["words"]):
            best = 1  # tolerate one typo
        if not best:
            return 0
        score += best
    return score


def search(conn, *, q=None, category=None, brand=None, availability=None, sort="relevance", page=1, page_size=24,
           group: str = "family", size=None, min_price=None, max_price=None) -> dict:
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValidationError("صفحه‌بندی نامعتبر است")
    if sort not in ("relevance", "newest", "price_asc", "price_desc", "name"):
        raise ValidationError("مرتب‌سازی نامعتبر است")
    data = _load(conn)
    q_tokens, q_compact = tn.tokens(q), tn.compact(q)
    hits: list[tuple[int, Sku]] = []
    pool = data["skus"]
    if q_tokens:
        pool = [data["by_id"][i] for i in sorted(_candidates(data, q_tokens))]
    size_pool = []
    for s in pool:
        if category and category not in s.search["path_slugs"]:
            continue
        size_pool.append(s)
        if size and tn.normalize(s.label or "") != tn.normalize(size):
            continue
        if brand and tn.normalize(tn.canonical_brand(brand)) != tn.normalize(s.brand):
            continue
        score = _score(s, q_tokens, q_compact) if q_tokens else 1
        if score:
            hits.append((score, s))
    groups: dict = {}
    for score, s in hits:
        g = groups.setdefault(s.family_id if group == "family" and s.family_id else f"s{s.id}", {"score": 0, "skus": []})
        g["score"] = max(g["score"], score)
        g["skus"].append(s)
    cards = []
    all_ids = [s.id for g in groups.values() for s in g["skus"]]
    avail, lists = availability_map(conn, all_ids), list_price_map(conn, all_ids)
    for g in groups.values():
        c = _card(conn, g["skus"], data["cats"], avail, lists)
        c["_score"], c["_created"] = g["score"], max(s.created for s in g["skus"])
        cards.append(c)
    if availability == "purchasable":
        cards = [c for c in cards if c["purchasable"]]
    priced = [c["price_minor"] for c in cards if c["price_minor"]]
    if min_price is not None or max_price is not None:
        # Only real, currently valid prices can match a price range; unpriced items never appear "cheap".
        cards = [c for c in cards if c["price_minor"] and (min_price is None or c["price_minor"] >= min_price)
                 and (max_price is None or c["price_minor"] <= max_price)]
    facets = {
        "sizes": _count([s.label for s in size_pool if s.label and (not q_tokens or _score(s, q_tokens, q_compact))]),
        "price_range": {"min": min(priced), "max": max(priced)} if priced else None,
        "brands": _count([c["brand_fa"] for c in cards if c["brand_fa"]]),
        "categories": _count([(p["slug"], p["name_fa"]) for c in cards for p in c["category_path"]]),
        "availability": _count([c["availability"] for c in cards]),
    }
    # Merchandising order for browsing and for equal relevance: buyable, then photographed, then priced, then retail.
    merch = lambda c: (c["purchasable"], bool(c["image_url"]), c["price_minor"] is not None or c["list_price_minor"] is not None,
                       not c["org_only"])
    key = {
        "relevance": (lambda c: (-c["_score"], *(not m for m in merch(c)), -c["id"])) if q_tokens
        else (lambda c: (merch(c), c["_created"], c["id"])),
        "newest": lambda c: (c["_created"], c["id"]),
        "price_asc": lambda c: (c["price_minor"] is None, c["price_minor"] or 0, c["id"]),
        "price_desc": lambda c: (c["price_minor"] is None, -(c["price_minor"] or 0), c["id"]),
        "name": lambda c: (tn.normalize(c["title_fa"]), c["id"]),
    }[sort]
    cards.sort(key=key, reverse=(sort == "newest" or (sort == "relevance" and not q_tokens)))
    total = len(cards)
    items = cards[(page - 1) * page_size: page * page_size]
    for c in items:
        c.pop("_score"), c.pop("_created")
    packs = []
    if q_tokens:
        from app.services import pack_service
        packs = pack_service.search(conn, q_tokens)[:4]
    return {"items": items, "packs": packs, "facets": facets, "page": page, "page_size": page_size, "total": total,
            "total_pages": (total + page_size - 1) // page_size, "query": q or "", "normalized_query": " ".join(q_tokens)}


def _candidates(data: dict, q_tokens: list[str]) -> set:
    """SKUs that can match every query token: exact word, prefix, or one-edit typo via the vocabulary."""
    import bisect
    vocab, index = data["vocab"], data["index"]
    result = None
    for t in q_tokens:
        ids = set(index.get(t, ()))
        i = bisect.bisect_left(vocab, t)
        while i < len(vocab) and vocab[i].startswith(t):
            ids |= index[vocab[i]]
            i += 1
        if len(t) >= 4:
            for w in vocab:
                if abs(len(w) - len(t)) <= 1 and len(w) >= 4 and tn.edit_distance_le1(t, w):
                    ids |= index[w]
        # compact title matches such as «نیمه جامد» vs «نیمهجامد» are checked by _score over the union below
        result = ids if result is None else (result & ids if (result & ids) else result | ids)
    return result or set()


def _count(values) -> list[dict]:
    counts: dict = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    out = []
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        out.append({"slug": k[0], "name_fa": k[1], "count": n} if isinstance(k, tuple) else {"value": k, "count": n})
    return out


def taxonomy(conn) -> list[dict]:
    data = _load(conn)
    counts: dict[int, set] = {}
    for s in data["skus"]:
        for cid in s.search["path_ids"]:
            counts.setdefault(cid, set()).add(s.family_id or f"s{s.id}")
    nodes = {cid: {"id": c["id"], "slug": c["slug"], "name_fa": c["name_fa"], "level": c["level"],
                   "product_count": len(counts.get(cid, ())), "children": []}
             for cid, c in data["cats"].items() if counts.get(cid)}
    roots = []
    for cid, node in sorted(nodes.items(), key=lambda kv: (data["cats"][kv[0]]["sort_order"], kv[0])):
        parent = data["cats"][cid]["parent_id"]
        (nodes[parent]["children"] if parent in nodes else roots).append(node)
    return roots


def brands(conn) -> list[dict]:
    data = _load(conn)
    out: dict = {}
    for s in data["skus"]:
        if s.brand:
            b = out.setdefault(s.brand, {"name": s.brand, "families": set(), "image_url": None})
            b["families"].add(s.family_id or s.id)
            b["image_url"] = b["image_url"] or (s.images[0] if s.images else None)
    return sorted(({"name": b["name"], "product_count": len(b["families"]), "image_url": b["image_url"]} for b in out.values()),
                  key=lambda b: -b["product_count"])


def product(conn, slug: str, *, viewer_org_ids: tuple = ()) -> dict:
    data = _load(conn)
    s = data["by_slug"].get(slug) or next((x for x in data["skus"] if x.family_slug == slug), None)
    if s is None:
        raise NotFoundError("محصول یافت نشد", code="product_not_found")
    family = sorted([x for x in data["skus"] if s.family_id and x.family_id == s.family_id] or [s],
                    key=lambda x: (x.attributes.get("weight_g") or x.attributes.get("volume_ml") or x.attributes.get("screen_inch") or 0, x.id))
    path = category_path(data["cats"], s.category_id)
    variants = []
    for v in family:
        state, price = _availability(conn, v.id)
        variants.append({"sku_id": v.id, "slug": v.slug, "sku": v.sku, "label": v.label, "title_fa": v.title,
                         "attributes": v.attributes, "image_url": v.images[0] if v.images else None,
                         "availability": state, "price_minor": price, "selected": v.id == s.id,"supply_channel":v.supply_channel,"allowed_channels":list(policy.channels(v.supply_channel))})
    offers = offers_for(conn, s.id, viewer_org_ids=viewer_org_ids)
    state, price = _availability(conn, s.id)
    lp = list_price_map(conn, [s.id]).get(s.id)
    if state == "purchasable":
        cta, blocker = "add_to_cart", None
    else:
        cta = "request_quote"
        blocker = "no_verified_offer" if state == "no_offer" else "offer_needs_quote"
    # Alternatives = same leaf type AND compatible unit (weight↔weight, volume↔volume); everything else nearby is "related".
    leaf = path[-1]["id"] if path else None
    kind = lambda x: "w" if x.attributes.get("weight_g") else "v" if x.attributes.get("volume_ml") else "o"
    same_leaf = [x for x in data["skus"] if leaf and x.category_id == leaf and x.family_id != s.family_id and x.id != s.id]
    alternatives = [x for x in same_leaf if kind(x) == kind(s)] if len(path) >= 3 else []
    parent = path[-2]["id"] if len(path) >= 2 else None
    related = [x for x in data["skus"] if parent and parent in x.search["path_ids"] and x.family_id != s.family_id
               and x.id != s.id and x not in alternatives]
    def cards(rows):
        groups: dict = {}
        for x in rows:
            groups.setdefault(x.family_id or f"s{x.id}", []).append(x)
        return [_card(conn, g, data["cats"]) for g in list(groups.values())[:8]]
    specs = [{"label": k, "value": v} for k, v in (s.specs.items() if isinstance(s.specs, dict) else [])]
    return {
        "product": {"sku_id": s.id, "slug": s.slug, "sku": s.sku, "title_fa": s.title, "family_title_fa": s.family_title,
                    "family_slug": s.family_slug, "brand_fa": s.brand, "description_fa": s.description, "images": s.images,
                    "variant_label": s.label, "attributes": s.attributes, "specs": specs, "provenance": s.provenance,
                    "master_product_id": s.variant_id, "supply_channel":s.supply_channel,"allowed_channels":list(policy.channels(s.supply_channel)), "unit": s.specs.get("unit"), "package_quantity": s.specs.get("package_quantity")},
        "breadcrumbs": [{"slug": c["slug"], "name_fa": c["name_fa"], "level": c["level"]} for c in path],
        "variants": variants, "offers": offers, "availability": state, "price_minor": price,
        # Shown price includes VAT (consumer law); price_minor stays net for cart/checkout math.
        "price_incl_vat_minor": _gross(price, offers[0]["vat_bps"] if offers else 0),
        "vat_bps": offers[0]["vat_bps"] if offers else 0,
        "cta": cta, "sale_blocker": blocker, "sales_enabled": se.sales_enabled(),
        "list_price_minor": lp["price"] if lp else None, "list_price_at": lp["at"] if lp else None,
        "org_only": s.supply_channel=="organization", "supply_channel":s.supply_channel,"allowed_channels":list(policy.channels(s.supply_channel)),
        "related": cards(related), "alternatives": cards(alternatives),
    }
