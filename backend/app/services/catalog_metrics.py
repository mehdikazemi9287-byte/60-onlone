"""Exact catalog/marketplace counts straight from the database (used for baselines and the admin view)."""
from __future__ import annotations

from app.services import pack_service

FRESH = "datetime({c}) >= datetime('now','-24 hours')"


def metrics(conn) -> dict:
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    real_offer = """FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id JOIN products p ON p.id=so.product_id
                    WHERE so.provenance='real' AND s.provenance='real' AND s.status='active' AND so.status='active'
                      AND p.provenance='real' AND p.is_active=1"""
    # Non-empty taxonomy nodes: every ancestor of a category that holds a visible REAL product family (linear walk).
    cats = {r["id"]: (r["parent_id"], r["level"]) for r in conn.execute("SELECT id, parent_id, level FROM categories")}
    nonempty: set = set()
    for (cid,) in conn.execute("""SELECT DISTINCT f.category_id FROM product_families f JOIN master_products m ON m.family_id=f.id
                                  JOIN products p ON p.master_product_id=m.id WHERE p.is_active=1 AND p.provenance='real'"""):
        while cid in cats and cid not in nonempty:
            nonempty.add(cid)
            cid = cats[cid][0]
    levels: dict = {}
    for cid in nonempty:
        levels[cats[cid][1]] = levels.get(cats[cid][1], 0) + 1
    depth = max([i + 1 for i, lv in enumerate(["department", "category", "subcategory", "product_type"]) if levels.get(lv)] or [0])
    published = conn.execute("SELECT id, kind FROM packs WHERE status='published'").fetchall()
    sets = {p["id"]: {r[0] for r in conn.execute("SELECT master_product_id FROM pack_items WHERE pack_id=?", (p["id"],))} for p in published}
    ids = list(sets)
    max_sim = max([pack_service.similarity(sets[a], sets[b]) for i, a in enumerate(ids) for b in ids[i + 1:]] or [0])
    return {
        "master_products": {"total": q("SELECT COUNT(*) FROM master_products"),
                            "real": q("SELECT COUNT(*) FROM master_products WHERE provenance='real'"),
                            "demo": q("SELECT COUNT(*) FROM master_products WHERE provenance='demo'"),
                            "test": q("SELECT COUNT(*) FROM master_products WHERE provenance='test'")},
        "active_products": q("""SELECT COUNT(DISTINCT m.id) FROM master_products m JOIN products p ON p.master_product_id=m.id
                                WHERE m.provenance='real' AND p.provenance='real' AND p.is_active=1"""),
        "storefront_skus": {"real_visible": q("SELECT COUNT(*) FROM products WHERE provenance='real' AND is_active=1"),
                            "real_hidden": q("SELECT COUNT(*) FROM products WHERE provenance='real' AND is_active=0"),
                            "demo": q("SELECT COUNT(*) FROM products WHERE provenance='demo'"),
                            "test": q("SELECT COUNT(*) FROM products WHERE provenance='test'")},
        "variants": {"families": q("SELECT COUNT(*) FROM product_families WHERE provenance='real'"),
                     "variants_in_families": q("SELECT COUNT(*) FROM master_products WHERE provenance='real' AND family_id IS NOT NULL"),
                     "multi_variant_families": q("""SELECT COUNT(*) FROM (SELECT family_id FROM master_products WHERE provenance='real'
                                                   AND family_id IS NOT NULL GROUP BY family_id HAVING COUNT(*)>1)"""),
                     "variants_in_multi_families": q("""SELECT COUNT(*) FROM master_products WHERE provenance='real' AND family_id IN
                                                       (SELECT family_id FROM master_products GROUP BY family_id HAVING COUNT(*)>1)""")},
        "seller_offers": {r[0]: r[1] for r in conn.execute("SELECT provenance, COUNT(*) FROM seller_offers GROUP BY 1")},
        "priced_skus": q(f"SELECT COUNT(DISTINCT so.product_id) {real_offer} AND so.pricing_mode IN ('fixed','bulk') AND so.selling_price_minor>0 AND {FRESH.format(c='so.last_price_confirmed_at')}"),
        "in_stock_skus": q(f"SELECT COUNT(DISTINCT so.product_id) {real_offer} AND so.stock_quantity-so.stock_reserved>0 AND {FRESH.format(c='so.last_inventory_confirmed_at')}"),
        "purchasable_skus": _purchasable(conn),
        "categories": {"by_level_nonempty": levels, "depth": depth,
                       "total_rows": {r[0]: r[1] for r in conn.execute("SELECT level, COUNT(*) FROM categories GROUP BY 1")}},
        "brands": q("""SELECT COUNT(DISTINCT m.brand) FROM master_products m JOIN products p ON p.master_product_id=m.id
                       WHERE m.provenance='real' AND p.is_active=1 AND m.brand IS NOT NULL"""),
        "packs": {"published": len(published), "draft": q("SELECT COUNT(*) FROM packs WHERE status='draft'"),
                  "kinds": sorted({p["kind"] for p in published}), "max_pairwise_overlap": round(max_sim, 2)},
        "suppliers": {r[0]: r[1] for r in conn.execute("SELECT provenance, COUNT(*) FROM suppliers GROUP BY 1")},
        "organizations": {r[0]: r[1] for r in conn.execute("SELECT provenance, COUNT(*) FROM organizations GROUP BY 1")},
    }


def _purchasable(conn) -> int:
    from app.services import sale_eligibility as se
    ids = [r[0] for r in conn.execute("SELECT id FROM products WHERE provenance='real' AND is_active=1")]
    return sum(1 for i in ids if (o := se.eligible_offer_conn(conn, i)) is not None and o["id"] and o["provenance"] == "real")
