ALTER TABLE product_families ADD COLUMN grouping_key TEXT;
CREATE UNIQUE INDEX idx_family_grouping_key ON product_families(grouping_key) WHERE grouping_key IS NOT NULL AND provenance='real';
