-- Phase 7 Migration 0018: Accounting & Finance Connector Platform
-- Adds: connector_accounts extended types, price source freshness policies extension,
--       inventory source enhancements, connector health enhancements.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend connector_accounts to support additional Phase 7 connector types
--    by rebuilding with expanded CHECK constraint.
-- ─────────────────────────────────────────────────────────────────────────────

PRAGMA foreign_keys = OFF;

CREATE TABLE connector_accounts_p7 (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    connector_type          TEXT NOT NULL CHECK(connector_type IN (
        'MANUAL', 'MOCK_ERP', 'MOCK_ERP_V2', 'CSV_IMPORT', 'XLSX_IMPORT',
        'REST_API', 'WEBHOOK', 'SFTP', 'FTP',
        'HOLO_ERP', 'SEPIDAR_ERP', 'RAHKARAN_ERP',
        'SAP_ERP', 'ODOO_ERP', 'CUSTOM_ERP',
        'ALOPEYK', 'POST_IR', 'TIPAX', 'CHAPAR', 'SUPPLIER_FLEET',
        'ACCOUNTING_CSV', 'ACCOUNTING_API',
        'SUPPLIER_FEED', 'MANUFACTURER_FEED', 'GS1_LOOKUP',
        'OTHER'
    )),
    supplier_id             INTEGER REFERENCES suppliers(id) ON DELETE CASCADE,
    organization_id         INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    credential_ref          TEXT,
    config_json             TEXT NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active', 'paused', 'error', 'disabled')),
    last_sync_at            TEXT,
    last_successful_sync_at TEXT,
    last_error              TEXT,
    mock_erp_dataset        TEXT NOT NULL DEFAULT 'products',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Phase 7 extensions (migrated from ALTER TABLE adds in 0016)
    version                 TEXT NOT NULL DEFAULT '1.0',
    environment             TEXT NOT NULL DEFAULT 'live',
    capabilities_json       TEXT NOT NULL DEFAULT '{}',
    mapping_profile_json    TEXT NOT NULL DEFAULT '{}',
    cursor_json             TEXT NOT NULL DEFAULT '{}',
    failure_count           INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_state   TEXT NOT NULL DEFAULT 'closed',
    circuit_breaker_until   TEXT,
    secret_provider         TEXT NOT NULL DEFAULT 'env',
    sync_interval_seconds   INTEGER NOT NULL DEFAULT 3600,
    sync_enabled            INTEGER NOT NULL DEFAULT 1,
    rate_limit_rps          INTEGER,
    timeout_seconds         INTEGER NOT NULL DEFAULT 30,
    max_retries             INTEGER NOT NULL DEFAULT 3
);

INSERT OR IGNORE INTO connector_accounts_p7
    (id, name, connector_type, supplier_id, organization_id, credential_ref,
     config_json, status, last_sync_at, last_successful_sync_at, last_error,
     mock_erp_dataset, created_at, updated_at,
     version, environment, capabilities_json, mapping_profile_json,
     cursor_json, failure_count, circuit_breaker_state, circuit_breaker_until,
     secret_provider, sync_interval_seconds, sync_enabled, rate_limit_rps,
     timeout_seconds, max_retries)
SELECT
    id, name, connector_type, supplier_id, organization_id, credential_ref,
    config_json, status, last_sync_at, last_successful_sync_at, last_error,
    mock_erp_dataset, created_at, updated_at,
    COALESCE(version, '1.0'),
    COALESCE(environment, 'live'),
    COALESCE(capabilities_json, '{}'),
    COALESCE(mapping_profile_json, '{}'),
    COALESCE(cursor_json, '{}'),
    COALESCE(failure_count, 0),
    COALESCE(circuit_breaker_state, 'closed'),
    circuit_breaker_until,
    COALESCE(secret_provider, 'env'),
    COALESCE(sync_interval_seconds, 3600),
    COALESCE(sync_enabled, 1),
    rate_limit_rps,
    COALESCE(timeout_seconds, 30),
    COALESCE(max_retries, 3)
FROM connector_accounts;

DROP TABLE connector_accounts;
ALTER TABLE connector_accounts_p7 RENAME TO connector_accounts;

CREATE INDEX IF NOT EXISTS idx_connector_accounts_supplier
    ON connector_accounts(supplier_id) WHERE supplier_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_connector_accounts_org
    ON connector_accounts(organization_id) WHERE organization_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_connector_accounts_type_status
    ON connector_accounts(connector_type, status);

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Extend freshness_policies (if table exists) with new columns
-- ─────────────────────────────────────────────────────────────────────────────

-- Add stale/expired thresholds if not present
-- (freshness_policies was created in phase 6; columns may or may not exist)
CREATE TABLE IF NOT EXISTS freshness_policies (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id             INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    connector_type          TEXT,
    fresh_seconds           INTEGER NOT NULL DEFAULT 3600,
    stale_seconds           INTEGER NOT NULL DEFAULT 86400,
    expired_seconds         INTEGER NOT NULL DEFAULT 604800,
    applies_to              TEXT NOT NULL DEFAULT 'price',
    -- price | inventory | product
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Connector sync scheduler (tracks scheduled sync jobs)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sync_schedule (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_account_id    INTEGER NOT NULL REFERENCES connector_accounts(id) ON DELETE CASCADE,
    sync_type               TEXT NOT NULL DEFAULT 'full',
    -- full | incremental | price_only | inventory_only
    scheduled_at            TEXT NOT NULL,
    started_at              TEXT,
    completed_at            TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    -- pending | running | completed | failed | skipped
    sync_run_id             INTEGER REFERENCES sync_runs(id) ON DELETE SET NULL,
    triggered_by            TEXT NOT NULL DEFAULT 'schedule',
    -- schedule | manual | webhook | event
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_sync_schedule_pending
    ON sync_schedule(connector_account_id, status, scheduled_at)
    WHERE status = 'pending';

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Import pipeline enhancements — add dry_run support
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE import_jobs ADD COLUMN is_dry_run INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_jobs ADD COLUMN dry_run_summary_json TEXT;
-- populated after dry-run, before confirm
-- NOTE: connector_account_id already added in migration 0010
ALTER TABLE import_jobs ADD COLUMN resume_cursor TEXT;
-- allows resuming a large import from a specific row
ALTER TABLE import_jobs ADD COLUMN auto_retry_failed INTEGER NOT NULL DEFAULT 0;
-- if 1, failed rows are automatically retried on next sync

ALTER TABLE import_job_rows ADD COLUMN identity_queue_id INTEGER REFERENCES identity_resolution_queue(id) ON DELETE SET NULL;
-- rows that could not be resolved link to the identity queue

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Seed built-in tax categories (idempotent via INSERT OR IGNORE)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO tax_categories (code, name_fa, name_en, description) VALUES
    ('STANDARD',        'استاندارد',       'Standard',         'نرخ مالیات بر ارزش افزوده استاندارد'),
    ('REDUCED',         'کاهش‌یافته',      'Reduced',          'نرخ کاهش‌یافته برای کالاهای خاص'),
    ('ZERO',            'صفر',             'Zero-rated',       'معاملات مشمول مالیات با نرخ صفر'),
    ('EXEMPT',          'معاف',            'Exempt',           'معاف از مالیات بر ارزش افزوده'),
    ('DIGITAL_SERVICES','خدمات دیجیتال',  'Digital Services', 'خدمات دیجیتال و نرم‌افزار'),
    ('FOOD_BASIC',      'مواد غذایی اساسی','Basic Food',       'مواد غذایی اساسی با نرخ خاص');

-- Insert current Iranian VAT rate: 9% (effective 2024-01-01)
-- This is the verified rate per Iranian VAT law (قانون مالیات بر ارزش افزوده)
-- Source: https://www.intracen.org/country/iran (and Iranian Tax Authority)
INSERT OR IGNORE INTO tax_rates
    (tax_category_id, rate_bps, effective_from, effective_until, jurisdiction, notes)
SELECT
    id, 900, '2024-01-01', NULL, 'IR',
    'نرخ مالیات بر ارزش افزوده ایران — ۹٪ (مصوب قانون مالیات بر ارزش افزوده)'
FROM tax_categories WHERE code = 'STANDARD';

INSERT OR IGNORE INTO tax_rates
    (tax_category_id, rate_bps, effective_from, effective_until, jurisdiction, notes)
SELECT id, 0, '2000-01-01', NULL, 'IR', 'نرخ صفر'
FROM tax_categories WHERE code IN ('ZERO', 'EXEMPT');

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Connector audit log (supplement to existing audit_logs)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS connector_audit_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_account_id    INTEGER REFERENCES connector_accounts(id) ON DELETE SET NULL,
    action                  TEXT NOT NULL,
    -- created | updated | paused | resumed | synced | health_checked | circuit_opened
    -- circuit_closed | credentials_rotated | deleted | wizard_completed
    actor_user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    detail_json             TEXT NOT NULL DEFAULT '{}',
    ip_address              TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_connector_audit_connector
    ON connector_audit_log(connector_account_id, created_at);
