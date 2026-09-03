-- 0010_connectors_import (PostgreSQL-native)
--
-- Phase 6: ERP Product Mapping + Sync Run Items + CSV Import Jobs
-- + Extend connector_accounts with MOCK_ERP type and mock_erp_dataset column
--
-- PostgreSQL supports ALTER TABLE to drop/add CHECK constraints and ADD COLUMN,
-- so no table rebuild is needed (unlike the SQLite version which had to rebuild
-- the table because SQLite does not support ALTER TABLE ... DROP CONSTRAINT).
--
-- PURELY ADDITIVE for all NEW tables (erp_product_mappings, sync_run_items,
-- import_jobs, import_job_rows). No existing data is destroyed.
--
-- SECURITY NOTES:
--   credential_ref in connector_accounts stores a reference key ONLY.
--   Credentials are NEVER stored in plain text in the database.
--   The API layer must strip credential_ref from all read responses.
--
-- SUPPLIER ISOLATION:
--   erp_product_mappings are scoped to connector_account → supplier.
--   import_jobs carry an explicit supplier_id for double enforcement.
--
-- CSV IMPORT LIFECYCLE:
--   pending → parsing → (validation_failed | previewing) →
--   confirmed → applying → (completed | completed_with_errors | failed)
--   Never mutate catalogue directly on upload before validation/confirmation.

-- ================================================================ connector_accounts

-- Step 1: Drop the existing CHECK constraint on connector_type.
DO $$
DECLARE
    cname TEXT;
BEGIN
    SELECT conname INTO cname
    FROM pg_constraint
    WHERE conrelid = 'connector_accounts'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%connector_type%'
    LIMIT 1;

    IF cname IS NOT NULL THEN
        EXECUTE 'ALTER TABLE connector_accounts DROP CONSTRAINT ' || quote_ident(cname);
    END IF;
END;
$$;

-- Step 2: Add the extended CHECK constraint that includes MOCK_ERP.
ALTER TABLE connector_accounts
    ADD CONSTRAINT connector_accounts_connector_type_check
    CHECK (connector_type IN (
        'MANUAL','MOCK_ERP','CSV_IMPORT','REST_API','WEBHOOK','SFTP',
        'HOLO_ERP','SEPIDAR_ERP','RAHKARAN_ERP',
        'CUSTOM_ERP','OTHER'
    ));

-- Step 3: Add the mock_erp_dataset column (idempotent — IF NOT EXISTS).
ALTER TABLE connector_accounts
    ADD COLUMN IF NOT EXISTS mock_erp_dataset TEXT NOT NULL DEFAULT 'products';

-- Ensure indexes exist (idempotent).
CREATE INDEX IF NOT EXISTS idx_ca_supplier  ON connector_accounts(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ca_status    ON connector_accounts(status);

-- ================================================================ ERP PRODUCT MAPPINGS

CREATE TABLE IF NOT EXISTS erp_product_mappings (
    id                      BIGSERIAL PRIMARY KEY,
    connector_account_id    INTEGER NOT NULL REFERENCES connector_accounts(id),
    -- External code as returned by the ERP / connector adapter
    erp_product_code        TEXT    NOT NULL,
    -- Resolved local product (NULL while pending or rejected)
    product_id              INTEGER REFERENCES products(id),
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id),
    -- Match confidence in basis points (0–10000). 10000 = 100% confident.
    -- Stored as INTEGER (no REAL/FLOAT allowed in this schema).
    confidence_score_bps    INTEGER NOT NULL DEFAULT 10000 CHECK (confidence_score_bps BETWEEN 0 AND 10000),
    -- manual | barcode | sku | fuzzy_name
    match_method            TEXT    NOT NULL DEFAULT 'manual'
                            CHECK (match_method IN ('manual','barcode','sku','fuzzy_name')),
    -- active | pending_review | rejected
    status                  TEXT    NOT NULL DEFAULT 'pending_review'
                            CHECK (status IN ('active','pending_review','rejected')),
    reviewed_by             INTEGER REFERENCES users(id),
    reviewed_at             TEXT,
    created_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    -- One ERP code per connector maps to at most one local product
    UNIQUE (connector_account_id, erp_product_code)
);

CREATE INDEX IF NOT EXISTS idx_epm_connector  ON erp_product_mappings(connector_account_id);
CREATE INDEX IF NOT EXISTS idx_epm_product    ON erp_product_mappings(product_id);
CREATE INDEX IF NOT EXISTS idx_epm_status     ON erp_product_mappings(status);
CREATE INDEX IF NOT EXISTS idx_epm_supplier   ON erp_product_mappings(supplier_id);

-- ================================================================ SYNC RUN ITEMS

CREATE TABLE IF NOT EXISTS sync_run_items (
    id              BIGSERIAL PRIMARY KEY,
    sync_run_id     INTEGER NOT NULL REFERENCES sync_runs(id),
    -- The external product/SKU code from the connector payload
    external_code   TEXT    NOT NULL,
    -- Resolved local product (NULL if unmapped or conflict)
    product_id      INTEGER REFERENCES products(id),
    offer_id        INTEGER REFERENCES seller_offers(id),
    -- mapped | unmapped | conflict | skipped | error
    status          TEXT    NOT NULL DEFAULT 'unmapped'
                    CHECK (status IN ('mapped','unmapped','conflict','skipped','error')),
    -- Human-readable description of what the sync engine did
    action_taken    TEXT,
    -- Error message if status='error'
    error_msg       TEXT,
    created_at      TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_sri_run     ON sync_run_items(sync_run_id);
CREATE INDEX IF NOT EXISTS idx_sri_product ON sync_run_items(product_id);
CREATE INDEX IF NOT EXISTS idx_sri_status  ON sync_run_items(status);

-- ================================================================ IMPORT JOBS

CREATE TABLE IF NOT EXISTS import_jobs (
    id                      BIGSERIAL PRIMARY KEY,
    -- Optional — NULL for manual/offline imports not tied to a connector
    connector_account_id    INTEGER REFERENCES connector_accounts(id),
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id),
    filename                TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN (
                                'pending','parsing','validation_failed',
                                'previewing','confirmed','applying',
                                'completed','completed_with_errors','failed'
                            )),
    total_rows              INTEGER NOT NULL DEFAULT 0,
    valid_rows              INTEGER NOT NULL DEFAULT 0,
    error_rows              INTEGER NOT NULL DEFAULT 0,
    -- JSON array of column→field mapping used during this job
    column_mapping_json     TEXT    NOT NULL DEFAULT '{}',
    -- JSON preview of first 20 valid rows (populated after parsing)
    preview_json            TEXT,
    -- Error/warning summary (populated after parsing/validation)
    error_summary_json      TEXT    NOT NULL DEFAULT '[]',
    created_by              INTEGER NOT NULL REFERENCES users(id),
    created_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_ij_supplier  ON import_jobs(supplier_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ij_status    ON import_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ij_connector ON import_jobs(connector_account_id);

-- ================================================================ IMPORT JOB ROWS

CREATE TABLE IF NOT EXISTS import_job_rows (
    id                      BIGSERIAL PRIMARY KEY,
    import_job_id           INTEGER NOT NULL REFERENCES import_jobs(id),
    row_number              INTEGER NOT NULL,
    -- Raw parsed JSON representation of this CSV row
    raw_json                TEXT    NOT NULL DEFAULT '{}',
    -- valid | invalid | applied | skipped | conflict
    status                  TEXT    NOT NULL DEFAULT 'valid'
                            CHECK (status IN ('valid','invalid','applied','skipped','conflict')),
    -- JSON array of validation error messages (empty if valid)
    validation_errors_json  TEXT    NOT NULL DEFAULT '[]',
    -- Resolved product_id after matching (NULL if unmatched)
    product_id              INTEGER REFERENCES products(id),
    -- Resolved offer_id (NULL if not yet applied)
    offer_id                INTEGER REFERENCES seller_offers(id),
    created_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_ijr_job    ON import_job_rows(import_job_id, row_number);
CREATE INDEX IF NOT EXISTS idx_ijr_status ON import_job_rows(import_job_id, status);
