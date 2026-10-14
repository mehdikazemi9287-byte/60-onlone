-- Additive current source reference. Existing audit history is retained, no guessed backfill.
ALTER TABLE direct_product_profiles ADD COLUMN source_reference TEXT;
-- Stable resolution of real pre/post-edit commerce SKU codes. No synthetic codes or prices.
CREATE TABLE product_code_aliases (
 code TEXT PRIMARY KEY,
 product_id INTEGER NOT NULL REFERENCES products(id),
 created_at TEXT NOT NULL
);
