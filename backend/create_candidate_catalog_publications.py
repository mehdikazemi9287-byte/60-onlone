#!/usr/bin/env python3
"""Create the isolated, non-purchasable catalog visibility list."""
import sqlite3
import sys

DB = sys.argv[1]
VISIBLE_IDS = [93, *range(116, 153), *range(168, 183)]
VERIFIED_PRICES = {
    177: (240_000_000, "https://www.technolife.com/product/list/corporategift/هدیه-سازمانی!"),
}

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys=ON")
conn.executescript("""
CREATE TABLE IF NOT EXISTS catalog_publications (
    master_product_id INTEGER PRIMARY KEY REFERENCES master_products(id),
    slug TEXT NOT NULL UNIQUE,
    category_slug TEXT NOT NULL REFERENCES categories(slug),
    verified_price_minor INTEGER CHECK (verified_price_minor IS NULL OR verified_price_minor > 0),
    currency TEXT NOT NULL DEFAULT 'IRR',
    is_visible INTEGER NOT NULL DEFAULT 1 CHECK (is_visible IN (0,1)),
    is_purchasable INTEGER NOT NULL DEFAULT 0 CHECK (is_purchasable = 0),
    price_status TEXT NOT NULL CHECK (price_status IN ('verified','pending')),
    publication_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
""")
for master_id in VISIBLE_IDS:
    row = conn.execute(
        "SELECT public_product_id, category FROM master_products WHERE id=?",
        (master_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"missing master product {master_id}")
    category_ok = conn.execute("SELECT 1 FROM categories WHERE slug=?", (row[1],)).fetchone()
    if category_ok is None:
        raise SystemExit(f"missing category {row[1]!r} for master {master_id}")
    price = VERIFIED_PRICES.get(master_id, (None, None))[0]
    conn.execute(
        """INSERT OR REPLACE INTO catalog_publications
           (master_product_id, slug, category_slug, verified_price_minor,
            currency, is_visible, is_purchasable, price_status, publication_reason)
           VALUES (?, ?, ?, ?, 'IRR', 1, 0, ?, ?)""",
        (master_id, f"catalog-{row[0]}", row[1], price,
         "verified" if price is not None else "pending",
         "verified identity; commerce data incomplete; explicitly non-purchasable"),
    )
    if price is not None:
        source = VERIFIED_PRICES[master_id][1]
        conn.execute(
            """INSERT OR REPLACE INTO field_provenance
               (entity_type, entity_id, field_name, field_value, source_type,
                source_id, external_ref, confidence_bps, retrieved_at,
                last_verified_at, attribution)
               VALUES ('master_product', ?, 'catalog_verified_price_minor', ?,
                       'retailer_verified', 'technolife-current', ?, 10000,
                       '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z',
                       'Exact ASUS VY229HE listing; storefront catalog display only')""",
            (master_id, str(price), source),
        )
conn.commit()

count, unpriced, purchasable = conn.execute(
    "SELECT COUNT(*), SUM(verified_price_minor IS NULL), SUM(is_purchasable) FROM catalog_publications"
).fetchone()
print(f"published={count} unpriced={unpriced} purchasable={purchasable}")
print("integrity=" + conn.execute("PRAGMA integrity_check").fetchone()[0])
