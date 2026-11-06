-- Phase 6 review fixes: seller bonus snapshot at order time, persisted affiliate reversals, attribute proposals.
ALTER TABLE fulfillment_orders ADD COLUMN affiliate_bonus_bps INTEGER;
ALTER TABLE affiliate_earnings ADD COLUMN reversed_minor INTEGER NOT NULL DEFAULT 0 CHECK (reversed_minor >= 0);
ALTER TABLE affiliate_earnings ADD COLUMN reference TEXT;
CREATE TABLE IF NOT EXISTS product_attribute_proposals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    master_product_id INTEGER NOT NULL REFERENCES master_products(id),
    attribute_id      INTEGER NOT NULL REFERENCES attribute_definitions(id),
    supplier_id       INTEGER NOT NULL REFERENCES suppliers(id),
    raw_value         TEXT NOT NULL CHECK (length(raw_value) <= 2000),
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_attr_proposals_master ON product_attribute_proposals(master_product_id, status);
