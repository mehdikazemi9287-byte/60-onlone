-- Phase 1 — seller shops (غرفه): self-registration, shop page, per-seller commission,
-- escrow hold before settlement, and seller account health.
-- Existing admin-created suppliers keep seller_kind='supplier' and behave exactly as before.

ALTER TABLE suppliers ADD COLUMN seller_kind TEXT NOT NULL DEFAULT 'supplier'
    CHECK (seller_kind IN ('supplier', 'shop', 'brand', 'partner'));
ALTER TABLE suppliers ADD COLUMN shop_slug TEXT;
ALTER TABLE suppliers ADD COLUMN shop_title TEXT;
ALTER TABLE suppliers ADD COLUMN shop_bio TEXT;
ALTER TABLE suppliers ADD COLUMN shop_logo_url TEXT;
ALTER TABLE suppliers ADD COLUMN shop_province TEXT;
ALTER TABLE suppliers ADD COLUMN shop_city TEXT;
-- NULL = use commission_rules. 5000 bps (50%) is a hard ceiling against typos.
ALTER TABLE suppliers ADD COLUMN commission_rate_bps INTEGER
    CHECK (commission_rate_bps IS NULL OR commission_rate_bps BETWEEN 0 AND 5000);
ALTER TABLE suppliers ADD COLUMN terms_version TEXT;
ALTER TABLE suppliers ADD COLUMN terms_accepted_at TEXT;
-- good | at_risk | suspended — recomputed from seller_health_snapshots.
ALTER TABLE suppliers ADD COLUMN health_status TEXT NOT NULL DEFAULT 'good'
    CHECK (health_status IN ('good', 'at_risk', 'suspended'));
CREATE UNIQUE INDEX IF NOT EXISTS ux_suppliers_shop_slug ON suppliers(shop_slug);

-- Commission resolution, most specific first:
--   suppliers.commission_rate_bps → rule(kind, category, channel) → rule(kind, NULL, channel)
--   → rule(NULL, NULL, channel) → 1000 bps.
CREATE TABLE IF NOT EXISTS commission_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_kind  TEXT CHECK (seller_kind IS NULL OR seller_kind IN ('supplier', 'shop', 'brand', 'partner')),
    category_id  INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    channel      TEXT NOT NULL DEFAULT 'any' CHECK (channel IN ('any', 'retail', 'organization')),
    rate_bps     INTEGER NOT NULL CHECK (rate_bps BETWEEN 0 AND 5000),
    note         TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_commission_rules_lookup ON commission_rules(seller_kind, category_id, channel);

-- Defaults from the roadmap (adjustable by admin): shops like Basalam's upper bound,
-- brands pay more for the brand zone, organization/wholesale sales pay less.
INSERT INTO commission_rules (seller_kind, category_id, channel, rate_bps, note) VALUES
    ('supplier', NULL, 'any', 1000, 'پیش‌فرض تأمین‌کننده (همان ۱۰٪ قبلی)'),
    ('shop', NULL, 'any', 900, 'غرفه‌دار؛ هم‌سطح سقف باسلام'),
    ('brand', NULL, 'any', 1200, 'برند رسمی؛ در عوض محوطهٔ برندها و کمپین'),
    ('partner', NULL, 'any', 600, 'شریک گروه'),
    (NULL, NULL, 'organization', 500, 'فروش سازمانی و عمده');

-- Escrow: a payable becomes settleable only after available_at (delivery + hold days),
-- the A-to-z style window in which the buyer can still open a problem.
ALTER TABLE supplier_payable_entries ADD COLUMN commission_rate_bps INTEGER;
ALTER TABLE supplier_payable_entries ADD COLUMN commission_minor INTEGER;
ALTER TABLE supplier_payable_entries ADD COLUMN available_at TEXT;
ALTER TABLE supplier_payable_entries ADD COLUMN channel TEXT;

-- Account health (Amazon-style targets): defect < 1%, cancel < 2.5%, late < 4%.
CREATE TABLE IF NOT EXISTS seller_health_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id        INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    window_days        INTEGER NOT NULL,
    orders_count       INTEGER NOT NULL DEFAULT 0,
    defect_count       INTEGER NOT NULL DEFAULT 0,
    cancel_count       INTEGER NOT NULL DEFAULT 0,
    late_count         INTEGER NOT NULL DEFAULT 0,
    defect_bps         INTEGER NOT NULL DEFAULT 0,
    cancel_bps         INTEGER NOT NULL DEFAULT 0,
    late_bps           INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL CHECK (status IN ('good', 'at_risk', 'suspended')),
    computed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_seller_health_supplier ON seller_health_snapshots(supplier_id, id);
