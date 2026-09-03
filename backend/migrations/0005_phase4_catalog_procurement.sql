-- 0005_phase4_catalog_procurement
--
-- Phase 4: Universal Product Catalog + Organizational Procurement
--
-- PURELY ADDITIVE. No existing table is dropped or renamed.
-- No existing column is removed. All Phase 1-3 rows remain valid.
--
-- Money: integer minor units throughout. No REAL/FLOAT.
-- Timestamps: UTC ISO-8601 TEXT.

-- ================================================================ MASTER PRODUCTS
-- Canonical product definition. One real-world product = one master_product row.
-- Phase 1-3 `products` rows gain a nullable master_product_id FK so they can be
-- linked to canonical entries incrementally without breaking existing data.

CREATE TABLE IF NOT EXISTS master_products (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    public_product_id       TEXT    NOT NULL UNIQUE,   -- UUID assigned at creation
    canonical_name_fa       TEXT    NOT NULL,           -- Persian canonical name
    canonical_name_en       TEXT,
    brand                   TEXT,
    manufacturer            TEXT,
    category                TEXT,
    subcategory             TEXT,
    product_type            TEXT,
    model                   TEXT,
    variant                 TEXT,
    size_label              TEXT,                       -- "1.5L", "A4", "XL"
    unit                    TEXT    NOT NULL DEFAULT 'عدد',
    package_quantity        INTEGER NOT NULL DEFAULT 1 CHECK (package_quantity > 0),
    net_quantity            TEXT,                       -- "1500ml", "500g"
    description_fa          TEXT,
    specifications_json     TEXT    NOT NULL DEFAULT '{}',
    image_urls_json         TEXT    NOT NULL DEFAULT '[]',
    country_of_origin       TEXT,
    -- Tax metadata (basis points; 900 bps = 9%)
    tax_category            TEXT    NOT NULL DEFAULT 'standard',
    vat_applicable          INTEGER NOT NULL DEFAULT 1 CHECK (vat_applicable IN (0,1)),
    vat_rate_bps            INTEGER NOT NULL DEFAULT 900 CHECK (vat_rate_bps >= 0),
    tax_classification      TEXT,
    invoice_description_fa  TEXT,
    status                  TEXT    NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('draft','active','discontinued','merged')),
    merged_into_id          INTEGER REFERENCES master_products(id),
    created_by_user_id      INTEGER REFERENCES users(id),
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_mp_status        ON master_products(status);
CREATE INDEX IF NOT EXISTS idx_mp_brand         ON master_products(brand);
CREATE INDEX IF NOT EXISTS idx_mp_category      ON master_products(category, subcategory);
CREATE INDEX IF NOT EXISTS idx_mp_public_id     ON master_products(public_product_id);

-- Link existing products table to master catalog (additive)
ALTER TABLE products ADD COLUMN master_product_id INTEGER REFERENCES master_products(id);
CREATE INDEX IF NOT EXISTS idx_products_master  ON products(master_product_id);

-- ================================================================ PRODUCT IDENTIFIERS
-- Many-to-one: one master_product can have many identifiers of different types.
-- Supplier-scoped identifiers (supplier SKU) carry supplier_id.
-- Org-scoped identifiers (ERP code) carry organization_id.

CREATE TABLE IF NOT EXISTS product_identifiers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    master_product_id   INTEGER NOT NULL REFERENCES master_products(id) ON DELETE CASCADE,
    identifier_type     TEXT    NOT NULL CHECK (identifier_type IN (
                            'INTERNAL','GTIN','EAN','UPC','ISBN',
                            'BARCODE','QR','RFID',
                            'MFR_SKU','SUPPLIER_SKU','ERP_CODE',
                            'ACCOUNTING_CODE','WAREHOUSE_CODE',
                            'LEGACY_CODE','CUSTOMS_CODE','TAX_CODE','OTHER'
                        )),
    identifier_value    TEXT    NOT NULL,
    issuer              TEXT,                   -- brand / supplier name / ERP system name
    supplier_id         INTEGER REFERENCES suppliers(id),
    organization_id     INTEGER REFERENCES organizations(id),
    metadata_json       TEXT    NOT NULL DEFAULT '{}',
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
-- Uniqueness enforced via partial indexes (SQLite does not support expressions in UNIQUE)
CREATE UNIQUE INDEX IF NOT EXISTS idx_pi_global_unique ON product_identifiers
    (identifier_type, identifier_value) WHERE supplier_id IS NULL AND organization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pi_supplier_unique ON product_identifiers
    (identifier_type, identifier_value, supplier_id) WHERE supplier_id IS NOT NULL AND organization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pi_org_unique ON product_identifiers
    (identifier_type, identifier_value, organization_id) WHERE supplier_id IS NULL AND organization_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pi_both_unique ON product_identifiers
    (identifier_type, identifier_value, supplier_id, organization_id) WHERE supplier_id IS NOT NULL AND organization_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pi_product       ON product_identifiers(master_product_id);
CREATE INDEX IF NOT EXISTS idx_pi_type_value    ON product_identifiers(identifier_type, identifier_value);
CREATE INDEX IF NOT EXISTS idx_pi_supplier      ON product_identifiers(supplier_id);

-- ================================================================ EXTERNAL PRODUCT MAPPINGS
-- When a connector imports an unknown identifier, it goes here — NOT into master_products.
-- Admin can later map → existing master, create → new master, or reject.

CREATE TABLE IF NOT EXISTS external_product_mappings (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    external_identifier_type    TEXT    NOT NULL,
    external_identifier_value   TEXT    NOT NULL,
    external_description        TEXT,
    external_metadata_json      TEXT    NOT NULL DEFAULT '{}',
    source_connector_account_id INTEGER REFERENCES connector_accounts(id),
    supplier_id                 INTEGER REFERENCES suppliers(id),
    organization_id             INTEGER REFERENCES organizations(id),
    -- Set once resolved; NULL = still unresolved
    master_product_id           INTEGER REFERENCES master_products(id),
    status                      TEXT    NOT NULL DEFAULT 'unresolved'
                                        CHECK (status IN (
                                            'unresolved','mapped','rejected',
                                            'pending_review','new_product_created'
                                        )),
    reviewed_by_user_id         INTEGER REFERENCES users(id),
    reviewed_at                 TEXT,
    notes                       TEXT,
    created_at                  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_epm_status        ON external_product_mappings(status);
CREATE INDEX IF NOT EXISTS idx_epm_supplier     ON external_product_mappings(supplier_id);
CREATE INDEX IF NOT EXISTS idx_epm_type_value   ON external_product_mappings(external_identifier_type, external_identifier_value);

-- ================================================================ CONNECTOR ACCOUNTS
-- ERP/supplier connector configurations.
-- NEVER store plaintext credentials here — only a credential_ref.

CREATE TABLE IF NOT EXISTS connector_accounts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL,
    connector_type          TEXT    NOT NULL CHECK (connector_type IN (
                                'MANUAL','CSV_IMPORT','REST_API','WEBHOOK','SFTP',
                                'HOLO_ERP','SEPIDAR_ERP','RAHKARAN_ERP',
                                'CUSTOM_ERP','OTHER'
                            )),
    supplier_id             INTEGER REFERENCES suppliers(id),
    organization_id         INTEGER REFERENCES organizations(id),
    credential_ref          TEXT,       -- Reference key to external secret store (NOT plaintext)
    config_json             TEXT    NOT NULL DEFAULT '{}',   -- Non-secret config
    status                  TEXT    NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active','inactive','error','suspended')),
    last_sync_at            TEXT,
    last_successful_sync_at TEXT,
    last_error              TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_ca_supplier  ON connector_accounts(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ca_status    ON connector_accounts(status);

-- ================================================================ SYNC JOBS + RUNS

CREATE TABLE IF NOT EXISTS sync_jobs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_account_id    INTEGER NOT NULL REFERENCES connector_accounts(id) ON DELETE CASCADE,
    job_type                TEXT    NOT NULL CHECK (job_type IN (
                                'products','prices','inventory','orders','full'
                            )),
    schedule_cron           TEXT,
    is_enabled              INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_job_id             INTEGER REFERENCES sync_jobs(id),
    connector_account_id    INTEGER NOT NULL REFERENCES connector_accounts(id),
    job_type                TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'running'
                                    CHECK (status IN ('running','completed','failed','cancelled')),
    started_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at            TEXT,
    records_processed       INTEGER NOT NULL DEFAULT 0,
    records_succeeded       INTEGER NOT NULL DEFAULT 0,
    records_failed          INTEGER NOT NULL DEFAULT 0,
    error_log_json          TEXT    NOT NULL DEFAULT '[]',
    triggered_by            TEXT    NOT NULL DEFAULT 'manual'
                                    CHECK (triggered_by IN ('schedule','manual','webhook'))
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_connector ON sync_runs(connector_account_id, started_at DESC);

-- ================================================================ FRESHNESS POLICIES
-- Price/inventory staleness rules per offer.

CREATE TABLE IF NOT EXISTS freshness_policies (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL UNIQUE,
    description             TEXT,
    price_ttl_seconds       INTEGER,        -- NULL = never stale
    inventory_ttl_seconds   INTEGER,
    stale_action            TEXT    NOT NULL DEFAULT 'warn'
                                    CHECK (stale_action IN ('allow','warn','block_checkout','block_all')),
    expired_action          TEXT    NOT NULL DEFAULT 'block_checkout'
                                    CHECK (expired_action IN ('allow','warn','block_checkout','block_all')),
    is_default              INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fp_default ON freshness_policies(is_default) WHERE is_default = 1;

-- Seed default freshness policies
INSERT OR IGNORE INTO freshness_policies (name, description, price_ttl_seconds, inventory_ttl_seconds, stale_action, expired_action, is_default)
VALUES
    ('ALWAYS_FRESH',  'Manual/static offers — never considered stale', NULL, NULL, 'allow', 'allow', 1),
    ('DAILY',         'Price/stock refreshed daily (86400s)',           86400, 86400, 'warn', 'block_checkout', 0),
    ('HOURLY',        'Volatile items — hourly refresh required',       3600,  3600,  'warn', 'block_checkout', 0),
    ('REALTIME',      'Mobile/electronics — 15-min TTL',                900,   900,  'block_checkout', 'block_checkout', 0);

-- Add freshness columns to seller_offers (additive)
ALTER TABLE seller_offers ADD COLUMN freshness_policy_id INTEGER REFERENCES freshness_policies(id);
ALTER TABLE seller_offers ADD COLUMN last_price_confirmed_at    TEXT;
ALTER TABLE seller_offers ADD COLUMN last_inventory_confirmed_at TEXT;

-- ================================================================ PROCUREMENT ROLES
-- Additive column on organization_memberships.
-- Values: NULL (no special procurement role), 'requester', 'approver', 'procurement_officer'
ALTER TABLE organization_memberships ADD COLUMN procurement_role TEXT
    CHECK (procurement_role IS NULL OR procurement_role IN (
        'requester','approver','procurement_officer'
    ));

-- ================================================================ PURCHASE REQUESTS

CREATE TABLE IF NOT EXISTS purchase_requests (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id         INTEGER NOT NULL REFERENCES organizations(id),
    requester_user_id       INTEGER NOT NULL REFERENCES users(id),
    requester_membership_id INTEGER REFERENCES organization_memberships(id),
    request_number          TEXT    NOT NULL UNIQUE,   -- PR-YYYYMMDD-NNNN
    title                   TEXT    NOT NULL,
    description             TEXT,
    status                  TEXT    NOT NULL DEFAULT 'draft'
                                    CHECK (status IN (
                                        'draft','submitted','under_review',
                                        'approved','rejected','sourcing',
                                        'quoted','awarded','cancelled','completed'
                                    )),
    needed_by_date          TEXT,       -- ISO date YYYY-MM-DD
    delivery_province       TEXT,
    delivery_city           TEXT,
    delivery_address        TEXT,
    budget_minor            INTEGER,    -- NULL = unknown
    cost_center             TEXT,
    project_code            TEXT,
    urgency                 TEXT    NOT NULL DEFAULT 'normal'
                                    CHECK (urgency IN ('low','normal','high','urgent')),
    notes                   TEXT,
    submitted_at            TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_pr_org       ON purchase_requests(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_pr_requester ON purchase_requests(requester_user_id);

CREATE TABLE IF NOT EXISTS purchase_request_items (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_request_id     INTEGER NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    master_product_id       INTEGER REFERENCES master_products(id),  -- nullable for free-text
    free_text_description   TEXT,   -- used when product not in catalog
    quantity                INTEGER NOT NULL CHECK (quantity > 0),
    unit                    TEXT,
    estimated_unit_price_minor INTEGER,
    notes                   TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_pri_pr ON purchase_request_items(purchase_request_id);

-- ================================================================ PROCUREMENT APPROVALS

CREATE TABLE IF NOT EXISTS procurement_approvals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_request_id     INTEGER NOT NULL REFERENCES purchase_requests(id),
    approver_user_id        INTEGER NOT NULL REFERENCES users(id),
    approver_membership_id  INTEGER REFERENCES organization_memberships(id),
    action                  TEXT    NOT NULL CHECK (action IN ('approve','reject','request_changes')),
    reason                  TEXT,
    level                   INTEGER NOT NULL DEFAULT 1,   -- reserved for multi-level
    approved_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_pa_pr ON procurement_approvals(purchase_request_id);

-- ================================================================ RFQS

CREATE TABLE IF NOT EXISTS rfqs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id         INTEGER NOT NULL REFERENCES organizations(id),
    purchase_request_id     INTEGER NOT NULL REFERENCES purchase_requests(id),
    created_by_user_id      INTEGER NOT NULL REFERENCES users(id),
    rfq_number              TEXT    NOT NULL UNIQUE,   -- RFQ-YYYYMMDD-NNNN
    title                   TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft','open','closed','awarded','cancelled')),
    deadline_at             TEXT,
    notes                   TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_rfq_org ON rfqs(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_rfq_pr  ON rfqs(purchase_request_id);

CREATE TABLE IF NOT EXISTS rfq_items (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    rfq_id                      INTEGER NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
    purchase_request_item_id    INTEGER REFERENCES purchase_request_items(id),
    master_product_id           INTEGER REFERENCES master_products(id),
    free_text_description       TEXT,
    quantity_requested          INTEGER NOT NULL CHECK (quantity_requested > 0),
    unit                        TEXT,
    notes                       TEXT
);
CREATE INDEX IF NOT EXISTS idx_rfq_items_rfq ON rfq_items(rfq_id);

CREATE TABLE IF NOT EXISTS rfq_suppliers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rfq_id      INTEGER NOT NULL REFERENCES rfqs(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    invited_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    status      TEXT    NOT NULL DEFAULT 'invited'
                        CHECK (status IN ('invited','viewed','responded','declined','awarded')),
    UNIQUE (rfq_id, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_rfqs_supplier ON rfq_suppliers(supplier_id, status);

-- ================================================================ SUPPLIER QUOTES

CREATE TABLE IF NOT EXISTS supplier_quotes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rfq_id              INTEGER NOT NULL REFERENCES rfqs(id),
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id),
    rfq_supplier_id     INTEGER NOT NULL REFERENCES rfq_suppliers(id),
    quote_number        TEXT    NOT NULL UNIQUE,
    status              TEXT    NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft','submitted','awarded','rejected','expired')),
    -- Aggregated financials (snapshot; immutable after submission)
    total_items_minor       INTEGER NOT NULL DEFAULT 0,
    shipping_cost_minor     INTEGER NOT NULL DEFAULT 0,
    discount_minor          INTEGER NOT NULL DEFAULT 0,
    vat_amount_minor        INTEGER NOT NULL DEFAULT 0,
    grand_total_minor       INTEGER NOT NULL DEFAULT 0,
    payment_terms           TEXT,
    delivery_lead_days      INTEGER,
    validity_days           INTEGER,
    notes                   TEXT,
    submitted_at            TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (rfq_id, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_sq_rfq      ON supplier_quotes(rfq_id, status);
CREATE INDEX IF NOT EXISTS idx_sq_supplier ON supplier_quotes(supplier_id);

CREATE TABLE IF NOT EXISTS supplier_quote_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_quote_id   INTEGER NOT NULL REFERENCES supplier_quotes(id) ON DELETE CASCADE,
    rfq_item_id         INTEGER NOT NULL REFERENCES rfq_items(id),
    unit_price_minor    INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    quantity_available  INTEGER NOT NULL CHECK (quantity_available >= 0),
    vat_rate_bps        INTEGER NOT NULL DEFAULT 900 CHECK (vat_rate_bps >= 0),
    vat_amount_minor    INTEGER NOT NULL DEFAULT 0,
    discount_minor      INTEGER NOT NULL DEFAULT 0,
    -- SNAPSHOT: computed at submission time
    total_minor         INTEGER NOT NULL CHECK (total_minor >= 0),
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_sqi_quote ON supplier_quote_items(supplier_quote_id);

-- ================================================================ PURCHASE ORDERS

CREATE TABLE IF NOT EXISTS purchase_orders (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id             INTEGER NOT NULL REFERENCES organizations(id),
    purchase_request_id         INTEGER NOT NULL REFERENCES purchase_requests(id),
    rfq_id                      INTEGER NOT NULL REFERENCES rfqs(id),
    awarded_supplier_quote_id   INTEGER NOT NULL REFERENCES supplier_quotes(id),
    created_by_user_id          INTEGER NOT NULL REFERENCES users(id),
    po_number                   TEXT    NOT NULL UNIQUE,
    status                      TEXT    NOT NULL DEFAULT 'draft'
                                        CHECK (status IN (
                                            'draft','confirmed','sent',
                                            'partially_received','received','cancelled'
                                        )),
    award_reason                TEXT,
    -- IMMUTABLE FINANCIAL SNAPSHOTS (prices at time of award — never change)
    total_items_minor_snapshot      INTEGER NOT NULL,
    shipping_cost_minor_snapshot    INTEGER NOT NULL DEFAULT 0,
    discount_minor_snapshot         INTEGER NOT NULL DEFAULT 0,
    vat_amount_minor_snapshot       INTEGER NOT NULL DEFAULT 0,
    grand_total_minor_snapshot      INTEGER NOT NULL,
    payment_terms_snapshot          TEXT,
    delivery_lead_days_snapshot     INTEGER,
    -- Delivery
    delivery_province       TEXT,
    delivery_city           TEXT,
    delivery_address        TEXT,
    needed_by_date          TEXT,
    confirmed_at            TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_po_org ON purchase_orders(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_po_pr  ON purchase_orders(purchase_request_id);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id           INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    rfq_item_id                 INTEGER NOT NULL REFERENCES rfq_items(id),
    supplier_id                 INTEGER NOT NULL REFERENCES suppliers(id),
    supplier_quote_item_id      INTEGER NOT NULL REFERENCES supplier_quote_items(id),
    master_product_id           INTEGER REFERENCES master_products(id),
    free_text_description       TEXT,
    quantity                    INTEGER NOT NULL CHECK (quantity > 0),
    unit                        TEXT,
    -- IMMUTABLE PRICE SNAPSHOTS
    unit_price_minor_snapshot   INTEGER NOT NULL,
    vat_rate_bps_snapshot       INTEGER NOT NULL,
    vat_amount_minor_snapshot   INTEGER NOT NULL,
    discount_minor_snapshot     INTEGER NOT NULL DEFAULT 0,
    total_minor_snapshot        INTEGER NOT NULL,
    created_at                  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_poi_po ON purchase_order_items(purchase_order_id);

-- ================================================================ PROCUREMENT AUDIT LOG
-- Append-only. Never UPDATE or DELETE rows here.

CREATE TABLE IF NOT EXISTS procurement_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    actor_user_id   INTEGER REFERENCES users(id),
    event_type      TEXT    NOT NULL CHECK (event_type IN (
                        'pr_created','pr_submitted','pr_approved','pr_rejected',
                        'pr_cancelled','rfq_created','rfq_opened','rfq_closed',
                        'rfq_cancelled','supplier_invited','supplier_responded',
                        'supplier_declined','quote_submitted','quote_awarded',
                        'quote_rejected','po_created','po_confirmed','po_cancelled',
                        'approval_granted','approval_rejected'
                    )),
    entity_type     TEXT    NOT NULL,   -- 'purchase_request','rfq','supplier_quote','purchase_order'
    entity_id       INTEGER NOT NULL,
    details_json    TEXT    NOT NULL DEFAULT '{}',
    occurred_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_pal_org    ON procurement_audit_log(organization_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_pal_entity ON procurement_audit_log(entity_type, entity_id);
