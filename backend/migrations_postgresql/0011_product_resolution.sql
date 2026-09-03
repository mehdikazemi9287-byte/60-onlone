-- 0011_product_resolution
--
-- Phase 6 Final: Product resolution tracking, field provenance,
-- knowledge source registry, import column templates.
--
-- PURELY ADDITIVE (CREATE TABLE IF NOT EXISTS only).
-- The migrator wraps this in BEGIN;...COMMIT; automatically.
-- No COMMIT/FK-OFF/BEGIN pattern needed.

-- product_resolution_attempts: tracks each resolution attempt
CREATE TABLE IF NOT EXISTS resolution_attempts (
    id BIGSERIAL PRIMARY KEY,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT '',
    connector_account_id INTEGER REFERENCES connector_accounts(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    sync_run_id INTEGER REFERENCES sync_runs(id),
    -- MATCHED, NEW_CANONICAL, AMBIGUOUS, CONFLICT, REJECTED
    result TEXT NOT NULL CHECK (result IN ('matched','new_canonical','ambiguous','conflict','rejected')),
    canonical_product_id INTEGER REFERENCES products(id),
    offer_id INTEGER REFERENCES seller_offers(id),
    confidence_bps INTEGER NOT NULL DEFAULT 0 CHECK (confidence_bps BETWEEN 0 AND 10000),
    resolution_method TEXT NOT NULL DEFAULT 'unknown',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX IF NOT EXISTS idx_ra_supplier ON resolution_attempts(supplier_id, result);
CREATE INDEX IF NOT EXISTS idx_ra_identifier ON resolution_attempts(identifier_type, identifier_value);
CREATE INDEX IF NOT EXISTS idx_ra_sync ON resolution_attempts(sync_run_id);

-- field_provenance: per-field source tracking
CREATE TABLE IF NOT EXISTS field_provenance (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    field_value TEXT,
    source_type TEXT NOT NULL,
    source_id TEXT,
    external_ref TEXT,
    confidence_bps INTEGER NOT NULL DEFAULT 10000 CHECK (confidence_bps BETWEEN 0 AND 10000),
    retrieved_at TEXT NOT NULL,
    last_verified_at TEXT,
    attribution TEXT,
    created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    UNIQUE (entity_type, entity_id, field_name, source_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_fp_entity ON field_provenance(entity_type, entity_id);

-- knowledge_sources: product knowledge source registry
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'mock_catalogue','manufacturer_feed','distributor_feed',
        'gs1_member','marketplace','other'
    )),
    adapter_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

-- import_column_templates: learned mapping templates per supplier
CREATE TABLE IF NOT EXISTS import_column_templates (
    id BIGSERIAL PRIMARY KEY,
    connector_account_id INTEGER REFERENCES connector_accounts(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    template_name TEXT NOT NULL,
    column_map_json TEXT NOT NULL DEFAULT '{}',
    confirmed_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX IF NOT EXISTS idx_ict_supplier ON import_column_templates(supplier_id);
