-- Administrative review markers only; no image/price/stock or product backfill.
CREATE TABLE catalog_image_reviews (
 master_product_id INTEGER PRIMARY KEY REFERENCES master_products(id),
 outcome TEXT NOT NULL CHECK(outcome IN ('needs_review','no_verified_source')),
 checked_reference TEXT NOT NULL,
 reason TEXT NOT NULL,
 row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),
 reviewed_by INTEGER NOT NULL REFERENCES users(id),
 reviewed_at TEXT NOT NULL
);
