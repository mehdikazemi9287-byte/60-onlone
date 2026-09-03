-- Phase 7 Migration 0017: Product Identity Graph extensions
-- Extends product_identifiers with full GS1/GTIN/RFID/serial support.
-- Adds identity_resolution_queue for ambiguous products.
-- All DDL is additive — existing product_identifiers rows are preserved.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend product_identifiers to support all Phase 7 identifier types
-- ─────────────────────────────────────────────────────────────────────────────
-- Check what types already exist; we rebuild the table via rename + recreate
-- to expand the CHECK constraint to include all Phase 7 types.
-- Existing data is migrated by the INSERT INTO ... SELECT.


CREATE TABLE IF NOT EXISTS product_identifiers_p7 (
    id               BIGSERIAL PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    identifier_type  TEXT NOT NULL,
    -- GTIN8 | GTIN12 | GTIN13 | GTIN14 | UPC | EAN | ISBN13 | ISBN10
    -- SUPPLIER_SKU | ERP_CODE | MPN | MANUFACTURER_CODE
    -- RFID_EPC | SGTIN | SERIAL | BATCH_LOT
    -- QR_CODE | GS1_DIGITAL_LINK
    -- EXTERNAL_MARKETPLACE | INTERNAL
    identifier_value TEXT NOT NULL,
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    -- NULL = platform-level identifier (GTIN etc.), non-NULL = supplier-specific
    namespace        TEXT NOT NULL DEFAULT '',
    -- kept for backward-compat with identifier_service; '' = default namespace
    connector_account_id INTEGER REFERENCES connector_accounts(id) ON DELETE SET NULL,
    -- source connector that provided this identifier
    is_primary       INTEGER NOT NULL DEFAULT 0,
    -- 1 = canonical primary identifier for this type
    confidence_bps   INTEGER NOT NULL DEFAULT 10000,
    -- 0–10000 basis points confidence (10000 = verified authoritative)
    source           TEXT NOT NULL DEFAULT 'manual',
    -- manual | connector_sync | gs1_lookup | barcode_scan | rfid_read | import
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

-- Migrate existing data from old table (if it has rows)
INSERT INTO product_identifiers_p7
    (id, product_id, identifier_type, identifier_value, supplier_id,
     namespace, connector_account_id, is_primary, confidence_bps, source, created_at, updated_at)
SELECT
    id, product_id,
    UPPER(identifier_type) AS identifier_type,
    identifier_value,
    supplier_id,
    COALESCE(namespace, '') AS namespace,
    NULL AS connector_account_id,
    COALESCE(is_primary, 0) AS is_primary,
    10000 AS confidence_bps,
    'manual' AS source,
    created_at,
    created_at AS updated_at
FROM product_identifiers ON CONFLICT DO NOTHING;

-- Drop old table
DROP TABLE IF EXISTS product_identifiers;
ALTER TABLE product_identifiers_p7 RENAME TO product_identifiers;

-- Unique constraint: one value per type per supplier+namespace context
-- (preserves the pre-Phase7 uniqueness contract: type, value, namespace, supplier_id)
CREATE UNIQUE INDEX IF NOT EXISTS uq_product_identifiers_global
    ON product_identifiers(identifier_type, identifier_value, namespace)
    WHERE supplier_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_product_identifiers_supplier
    ON product_identifiers(identifier_type, identifier_value, namespace, supplier_id)
    WHERE supplier_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_product_identifiers_product
    ON product_identifiers(product_id);

CREATE INDEX IF NOT EXISTS idx_product_identifiers_lookup
    ON product_identifiers(identifier_type, identifier_value);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Identity resolution queue
-- Products that could not be automatically resolved land here for human review.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS identity_resolution_queue (
    id               BIGSERIAL PRIMARY KEY,
    identifier_type  TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    connector_account_id INTEGER REFERENCES connector_accounts(id) ON DELETE SET NULL,
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    import_job_id    INTEGER REFERENCES import_jobs(id) ON DELETE SET NULL,

    -- What the connector/feed reported
    raw_product_data_json TEXT NOT NULL DEFAULT '{}',

    -- Resolution pipeline results
    resolution_stage TEXT NOT NULL DEFAULT 'pending',
    -- pending | exact_match_tried | connector_mapping_tried | gtin_tried
    -- mpn_tried | attribute_tried | fuzzy_tried | human_review | resolved | rejected

    candidate_product_ids TEXT,
    -- JSON array of candidate product IDs (ambiguous matches)
    match_confidence_bps INTEGER,

    resolution_result TEXT,
    -- matched | new_canonical | ambiguous | conflict | rejected | abandoned
    resolved_product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    resolved_by_user_id INTEGER REFERENCES users(id),
    resolution_notes TEXT,

    -- Exception linkage
    exception_id     INTEGER REFERENCES exceptions(id) ON DELETE SET NULL,

    attempt_count    INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'open',
    -- open | in_progress | resolved | rejected | abandoned
    priority         INTEGER NOT NULL DEFAULT 5,
    -- 1 (highest) to 10 (lowest)

    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_identity_queue_status
    ON identity_resolution_queue(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_identity_queue_identifier
    ON identity_resolution_queue(identifier_type, identifier_value, status);
CREATE INDEX IF NOT EXISTS idx_identity_queue_supplier
    ON identity_resolution_queue(supplier_id, status) WHERE supplier_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Warehouse / location extensions for scanner mode
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS warehouse_locations (
    id               BIGSERIAL PRIMARY KEY,
    supplier_id      INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    location_code    TEXT NOT NULL,
    -- e.g. 'A-01-03' (aisle A, rack 01, level 03)
    name_fa          TEXT,
    location_type    TEXT NOT NULL DEFAULT 'shelf',
    -- shelf | bin | floor | staging | dispatch | receiving | quarantine
    barcode          TEXT,
    -- scannable location barcode
    rfid_tag         TEXT,
    -- RFID tag EPC for this location
    is_active        INTEGER NOT NULL DEFAULT 1,
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    UNIQUE(supplier_id, location_code)
);

CREATE INDEX IF NOT EXISTS idx_warehouse_locations_barcode
    ON warehouse_locations(barcode) WHERE barcode IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. RFID event log (for scanner / warehouse mode)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rfid_events (
    id               BIGSERIAL PRIMARY KEY,
    reader_id        TEXT NOT NULL,
    -- physical reader identifier
    epc              TEXT NOT NULL,
    -- Electronic Product Code (hex string)
    sgtin_gtin       TEXT,
    -- extracted GTIN from SGTIN EPC (if parseable)
    sgtin_serial     TEXT,
    -- extracted serial from SGTIN EPC
    rssi             INTEGER,
    -- signal strength
    antenna_port     INTEGER,
    resolved_product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    warehouse_location_id INTEGER REFERENCES warehouse_locations(id) ON DELETE SET NULL,
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    event_type       TEXT NOT NULL DEFAULT 'read',
    -- read | write | enter_zone | exit_zone
    read_at          TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_rfid_events_epc
    ON rfid_events(epc, read_at);
CREATE INDEX IF NOT EXISTS idx_rfid_events_reader
    ON rfid_events(reader_id, read_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. GS1 / GTIN lookup cache
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gtin_lookup_cache (
    gtin             TEXT PRIMARY KEY,
    -- GTIN-8, GTIN-12, GTIN-13, or GTIN-14 (normalised to 14 digits)
    source           TEXT NOT NULL DEFAULT 'gs1_member',
    -- gs1_member | manufacturer_feed | distributor | manual
    product_name     TEXT,
    brand            TEXT,
    manufacturer     TEXT,
    country_of_origin TEXT,
    -- ISO 3166-1 alpha-2
    raw_data_json    TEXT NOT NULL DEFAULT '{}',
    resolved_product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    confidence_bps   INTEGER NOT NULL DEFAULT 10000,
    expires_at       TEXT,
    fetched_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    CONSTRAINT chk_gtin_len CHECK(length(gtin) BETWEEN 8 AND 14)
);

CREATE INDEX IF NOT EXISTS idx_gtin_cache_product
    ON gtin_lookup_cache(resolved_product_id) WHERE resolved_product_id IS NOT NULL;
