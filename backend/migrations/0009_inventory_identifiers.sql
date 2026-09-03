-- 0009_inventory_identifiers
--
-- Phase 6: Universal Product Identifiers + Inventory/Price Source Model
--
-- SCHEMA MIGRATION NOTE:
--   Migration 0005 created a table also named `product_identifiers` but with
--   a different schema (references master_products, uses master_product_id,
--   issuer, organization_id, metadata_json, is_active columns, and only
--   upper-case identifier_type values like BARCODE/EAN/GTIN/etc.).
--
--   Phase 6 defines a new canonical product_identifiers schema that:
--   - References `products` (not master_products)
--   - Uses the supplier-scoped model (product_id + supplier_id + namespace)
--   - Uses lower-case identifier_type values (barcode/sku/erp_code/isbn/gtin/custom)
--   - Supports is_primary, namespace for disambiguation
--
--   MIGRATION PLAN:
--   - Rename the Phase 4 table to `product_identifiers_legacy`.
--     The master_catalog_service continues to use product_identifiers_legacy.
--   - Create the new `product_identifiers` table (Phase 6 canonical schema).
--   - Drop old indexes explicitly (they referenced product_identifiers).
--   - Recreate indexes for the renamed legacy table.
--   - Create new indexes for the new Phase 6 table.
--
-- PURELY ADDITIVE for all NEW tables. No data is destroyed.
-- Legacy Phase 4 identifier rows are preserved in product_identifiers_legacy.
--
-- Money: integer minor units throughout. No REAL/FLOAT/DOUBLE.
-- Timestamps: UTC ISO-8601 TEXT.
--
-- POPULATED-DATABASE SAFETY:
--   product_identifiers_legacy has an FK to master_products (ON DELETE CASCADE)
--   and to suppliers and organizations. PRAGMA foreign_keys = ON + DROP INDEX
--   on a populated DB may trigger FK checks on the old table.
--   Use the COMMIT/FK-OFF/BEGIN pattern (same as migration 0008).

-- Step 1: close the migrator's outer BEGIN (safe — empty transaction).
COMMIT;

-- Step 2: disable FK enforcement while outside any transaction.
PRAGMA foreign_keys = OFF;

-- Step 3: Drop old indexes on the original product_identifiers table
-- (they will become stale after the rename, so drop before renaming).
DROP INDEX IF EXISTS idx_pi_global_unique;
DROP INDEX IF EXISTS idx_pi_supplier_unique;
DROP INDEX IF EXISTS idx_pi_org_unique;
DROP INDEX IF EXISTS idx_pi_both_unique;
DROP INDEX IF EXISTS idx_pi_product;
DROP INDEX IF EXISTS idx_pi_type_value;
DROP INDEX IF EXISTS idx_pi_supplier;

-- Step 4: Rename existing Phase 4 product_identifiers to legacy table.
ALTER TABLE product_identifiers RENAME TO product_identifiers_legacy;

-- Step 5: Recreate indexes for the legacy table (now named correctly).
CREATE UNIQUE INDEX IF NOT EXISTS idx_pil_global_unique ON product_identifiers_legacy
    (identifier_type, identifier_value) WHERE supplier_id IS NULL AND organization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pil_supplier_unique ON product_identifiers_legacy
    (identifier_type, identifier_value, supplier_id) WHERE supplier_id IS NOT NULL AND organization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pil_org_unique ON product_identifiers_legacy
    (identifier_type, identifier_value, organization_id) WHERE supplier_id IS NULL AND organization_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pil_both_unique ON product_identifiers_legacy
    (identifier_type, identifier_value, supplier_id, organization_id) WHERE supplier_id IS NOT NULL AND organization_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pil_product    ON product_identifiers_legacy(master_product_id);
CREATE INDEX IF NOT EXISTS idx_pil_type_value ON product_identifiers_legacy(identifier_type, identifier_value);
CREATE INDEX IF NOT EXISTS idx_pil_supplier   ON product_identifiers_legacy(supplier_id);

-- ================================================================ PRODUCT IDENTIFIERS (Phase 6)

CREATE TABLE IF NOT EXISTS product_identifiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    -- NULL supplier_id = platform-global identifier (e.g., GTIN from manufacturer)
    supplier_id     INTEGER REFERENCES suppliers(id),
    identifier_type TEXT    NOT NULL
                    CHECK (identifier_type IN (
                        'barcode','sku','erp_code','isbn','gtin','custom'
                    )),
    -- The actual code string, e.g. "6260000123456" for EAN-13
    identifier_value TEXT   NOT NULL,
    -- Namespace disambiguates within identifier_type: ERP system name, org name, etc.
    -- Empty string = default namespace.
    namespace       TEXT    NOT NULL DEFAULT '',
    is_primary      INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    -- A given (type, value, namespace, supplier) combination is globally unique.
    UNIQUE (identifier_type, identifier_value, namespace, supplier_id)
);

CREATE INDEX IF NOT EXISTS idx_pi_product   ON product_identifiers(product_id);
CREATE INDEX IF NOT EXISTS idx_pi_supplier  ON product_identifiers(supplier_id);
CREATE INDEX IF NOT EXISTS idx_pi_type_val  ON product_identifiers(identifier_type, identifier_value);
CREATE INDEX IF NOT EXISTS idx_pi_namespace ON product_identifiers(namespace);

-- ================================================================ IDENTIFIER CONFLICTS

CREATE TABLE IF NOT EXISTS identifier_conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The two products that claim the same identifier
    product_id_a    INTEGER NOT NULL REFERENCES products(id),
    product_id_b    INTEGER NOT NULL REFERENCES products(id),
    identifier_type TEXT    NOT NULL,
    identifier_value TEXT   NOT NULL,
    namespace       TEXT    NOT NULL DEFAULT '',
    -- open | resolved_merge | resolved_keep_both | ignored
    status          TEXT    NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','resolved_merge','resolved_keep_both','ignored')),
    resolved_by     INTEGER REFERENCES users(id),
    resolved_at     TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_ic_status ON identifier_conflicts(status);
CREATE INDEX IF NOT EXISTS idx_ic_type_val ON identifier_conflicts(identifier_type, identifier_value);

-- ================================================================ INVENTORY SOURCES

CREATE TABLE IF NOT EXISTS inventory_sources (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL,
    -- manual | connector | csv_import | erp_sync
    source_type             TEXT    NOT NULL DEFAULT 'manual'
                            CHECK (source_type IN ('manual','connector','csv_import','erp_sync')),
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id),
    -- Higher priority wins. 0 = lowest authority.
    priority                INTEGER NOT NULL DEFAULT 0,
    -- Optional link to a connector account that feeds this source
    connector_account_id    INTEGER REFERENCES connector_accounts(id),
    is_active               INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    -- JSON blob for source-specific config (TTL, field mappings, etc.)
    config_json             TEXT    NOT NULL DEFAULT '{}',
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_inv_src_supplier  ON inventory_sources(supplier_id, is_active);
CREATE INDEX IF NOT EXISTS idx_inv_src_priority  ON inventory_sources(supplier_id, priority DESC);

-- ================================================================ INVENTORY SOURCE STOCK

CREATE TABLE IF NOT EXISTS inventory_source_stock (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_source_id INTEGER NOT NULL REFERENCES inventory_sources(id),
    offer_id            INTEGER NOT NULL REFERENCES seller_offers(id),
    -- Stock quantity as reported by THIS source (>= 0)
    quantity            INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    -- Monotonically-increasing version counter. Out-of-order updates (where
    -- incoming version <= stored version) are silently dropped by the service.
    version             INTEGER NOT NULL DEFAULT 0,
    -- Opaque reference from the external system (e.g., ERP transaction id)
    source_ref          TEXT,
    synced_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (inventory_source_id, offer_id)
);

CREATE INDEX IF NOT EXISTS idx_iss_source  ON inventory_source_stock(inventory_source_id);
CREATE INDEX IF NOT EXISTS idx_iss_offer   ON inventory_source_stock(offer_id);

-- ================================================================ PRICE SOURCES

CREATE TABLE IF NOT EXISTS price_sources (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL,
    source_type             TEXT    NOT NULL DEFAULT 'manual'
                            CHECK (source_type IN ('manual','connector','csv_import','erp_sync')),
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id),
    -- Higher priority wins.
    priority                INTEGER NOT NULL DEFAULT 0,
    connector_account_id    INTEGER REFERENCES connector_accounts(id),
    is_active               INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    config_json             TEXT    NOT NULL DEFAULT '{}',
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_price_src_supplier  ON price_sources(supplier_id, is_active);
CREATE INDEX IF NOT EXISTS idx_price_src_priority  ON price_sources(supplier_id, priority DESC);

-- ================================================================ PRICE SOURCE ENTRIES

CREATE TABLE IF NOT EXISTS price_source_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    price_source_id INTEGER NOT NULL REFERENCES price_sources(id),
    offer_id        INTEGER NOT NULL REFERENCES seller_offers(id),
    -- Price in minor units (e.g., Rials). NO FLOAT.
    price_minor     INTEGER NOT NULL CHECK (price_minor >= 0),
    currency        TEXT    NOT NULL DEFAULT 'IRR',
    version         INTEGER NOT NULL DEFAULT 0,
    source_ref      TEXT,
    synced_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (price_source_id, offer_id)
);

CREATE INDEX IF NOT EXISTS idx_pse_source  ON price_source_entries(price_source_id);
CREATE INDEX IF NOT EXISTS idx_pse_offer   ON price_source_entries(offer_id);

-- Step 4: re-enable FK enforcement (still outside any transaction).
PRAGMA foreign_keys = ON;

-- Step 5: open a fresh transaction so the migrator's schema_migrations INSERT
-- (appended by migrator.py after this SQL) runs atomically.
BEGIN;
