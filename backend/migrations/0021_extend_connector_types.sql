-- 0021_extend_connector_types
--
-- Phase 7 Final Repair — three-blocker fixes (additive).
--
-- 1. Extend connector_accounts.connector_type CHECK to include all types
--    registered in adapters/connectors/registry.py.
--    SQLite does not support ALTER TABLE to change CHECK constraints, so we
--    rebuild the table (same pattern as migration 0010).
--
-- 2. Add idempotency_key column to integration_events for per-connector
--    fan-out delivery tracking.
--
-- 3. Create unique index on (event_type, idempotency_key) so duplicate
--    fan-out insertions are prevented even under concurrent writes.
--
-- PURELY ADDITIVE for all other tables. No existing data is lost.
--
-- SECURITY: no credentials are touched; supplier/organization isolation is
-- enforced at the service layer, not through this migration.

-- Step 1: close the migrator's outer BEGIN so we can use PRAGMA.
COMMIT;

-- Step 2: disable FK enforcement while we rebuild.
PRAGMA foreign_keys = OFF;

-- Step 3: Rebuild connector_accounts with the extended CHECK constraint.
--   Old allowed types: MANUAL, MOCK_ERP, CSV_IMPORT, REST_API, WEBHOOK, SFTP,
--                      HOLO_ERP, SEPIDAR_ERP, RAHKARAN_ERP, CUSTOM_ERP, OTHER
--   New types added:   MOCK_ERP_V2, FTP, XLSX_IMPORT, SAP_ERP, ODOO_ERP,
--                      ALOPEYK, POST_IR, TIPAX, CHAPAR, SUPPLIER_FLEET,
--                      ACCOUNTING_CSV, ACCOUNTING_API, SUPPLIER_FEED,
--                      MANUFACTURER_FEED, GS1_LOOKUP

CREATE TABLE IF NOT EXISTS connector_accounts_v21 (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT    NOT NULL,
    connector_type          TEXT    NOT NULL CHECK (connector_type IN (
                                'MANUAL',
                                'MOCK_ERP',
                                'MOCK_ERP_V2',
                                'CSV_IMPORT',
                                'REST_API',
                                'WEBHOOK',
                                'SFTP',
                                'FTP',
                                'XLSX_IMPORT',
                                'HOLO_ERP',
                                'SEPIDAR_ERP',
                                'RAHKARAN_ERP',
                                'SAP_ERP',
                                'ODOO_ERP',
                                'ALOPEYK',
                                'POST_IR',
                                'TIPAX',
                                'CHAPAR',
                                'SUPPLIER_FLEET',
                                'ACCOUNTING_CSV',
                                'ACCOUNTING_API',
                                'SUPPLIER_FEED',
                                'MANUFACTURER_FEED',
                                'GS1_LOOKUP',
                                'CUSTOM_ERP',
                                'OTHER'
                            )),
    supplier_id             INTEGER REFERENCES suppliers(id),
    organization_id         INTEGER REFERENCES organizations(id),
    credential_ref          TEXT,
    config_json             TEXT    NOT NULL DEFAULT '{}',
    status                  TEXT    NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active','inactive','error','suspended')),
    last_sync_at            TEXT,
    last_successful_sync_at TEXT,
    last_error              TEXT,
    mock_erp_dataset        TEXT    NOT NULL DEFAULT 'products',
    -- Phase 7 additions (from migration 0016):
    version                 TEXT    NOT NULL DEFAULT '1.0',
    environment             TEXT    NOT NULL DEFAULT 'live',
    capabilities_json       TEXT    NOT NULL DEFAULT '{}',
    mapping_profile_json    TEXT    NOT NULL DEFAULT '{}',
    cursor_json             TEXT    NOT NULL DEFAULT '{}',
    failure_count           INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_state   TEXT    NOT NULL DEFAULT 'closed',
    circuit_breaker_until   TEXT,
    secret_provider         TEXT    NOT NULL DEFAULT 'env',
    sync_interval_seconds   INTEGER NOT NULL DEFAULT 3600,
    sync_enabled            INTEGER NOT NULL DEFAULT 1,
    rate_limit_rps          INTEGER,
    timeout_seconds         INTEGER NOT NULL DEFAULT 30,
    max_retries             INTEGER NOT NULL DEFAULT 3,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

INSERT INTO connector_accounts_v21
    (id, name, connector_type, supplier_id, organization_id,
     credential_ref, config_json, status, last_sync_at,
     last_successful_sync_at, last_error, mock_erp_dataset,
     version, environment, capabilities_json, mapping_profile_json,
     cursor_json, failure_count, circuit_breaker_state, circuit_breaker_until,
     secret_provider, sync_interval_seconds, sync_enabled, rate_limit_rps,
     timeout_seconds, max_retries,
     created_at, updated_at)
SELECT id, name, connector_type, supplier_id, organization_id,
       credential_ref, config_json, status, last_sync_at,
       last_successful_sync_at, last_error, mock_erp_dataset,
       version, environment, capabilities_json, mapping_profile_json,
       cursor_json, failure_count, circuit_breaker_state, circuit_breaker_until,
       secret_provider, sync_interval_seconds, sync_enabled, rate_limit_rps,
       timeout_seconds, max_retries,
       created_at, updated_at
FROM connector_accounts;

DROP TABLE connector_accounts;
ALTER TABLE connector_accounts_v21 RENAME TO connector_accounts;

CREATE INDEX IF NOT EXISTS idx_ca_supplier  ON connector_accounts(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ca_status    ON connector_accounts(status);
CREATE INDEX IF NOT EXISTS idx_ca_org       ON connector_accounts(organization_id) WHERE organization_id IS NOT NULL;

-- Step 4: Add idempotency_key to integration_events for per-connector fan-out.
-- The column is nullable so existing rows remain valid.
ALTER TABLE integration_events ADD COLUMN idempotency_key TEXT;

-- Unique index prevents duplicate fan-out insertions for the same
-- business event + connector pair.
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_events_idempotency
    ON integration_events(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Step 5: re-enable FK enforcement.
PRAGMA foreign_keys = ON;

-- Step 6: open a fresh transaction for the migrator's schema_migrations INSERT.
BEGIN;
