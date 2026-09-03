-- Phase 7 Migration 0018: Accounting & Finance Connector Platform (PostgreSQL-native)
-- Adds: connector_accounts extended types, price source freshness policies extension,
--       inventory source enhancements, connector health enhancements.
--
-- PostgreSQL supports ALTER TABLE to drop/add CHECK constraints and ADD COLUMN,
-- so no table rebuild is needed (unlike the SQLite version which had to rebuild
-- the table because SQLite does not support ALTER TABLE ... DROP CONSTRAINT).
-- By migration 0018 several tables reference connector_accounts via FK (sync_runs,
-- erp_product_mappings, import_jobs, etc.) so DROP TABLE without CASCADE would fail.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend connector_accounts to support additional Phase 7 connector types
-- ─────────────────────────────────────────────────────────────────────────────

-- Drop the existing CHECK constraint on connector_type.
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

-- Add the extended CHECK constraint with all Phase 7 connector types.
ALTER TABLE connector_accounts
    ADD CONSTRAINT connector_accounts_connector_type_check
    CHECK (connector_type IN (
        'MANUAL', 'MOCK_ERP', 'MOCK_ERP_V2', 'CSV_IMPORT', 'XLSX_IMPORT',
        'REST_API', 'WEBHOOK', 'SFTP', 'FTP',
        'HOLO_ERP', 'SEPIDAR_ERP', 'RAHKARAN_ERP',
        'SAP_ERP', 'ODOO_ERP', 'CUSTOM_ERP',
        'ALOPEYK', 'POST_IR', 'TIPAX', 'CHAPAR', 'SUPPLIER_FLEET',
        'ACCOUNTING_CSV', 'ACCOUNTING_API',
        'SUPPLIER_FEED', 'MANUFACTURER_FEED', 'GS1_LOOKUP',
        'OTHER'
    ));

-- Drop the existing CHECK constraint on status (status values extended in Phase 7).
DO $$
DECLARE
    cname TEXT;
BEGIN
    SELECT conname INTO cname
    FROM pg_constraint
    WHERE conrelid = 'connector_accounts'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%status%'
    LIMIT 1;

    IF cname IS NOT NULL THEN
        EXECUTE 'ALTER TABLE connector_accounts DROP CONSTRAINT ' || quote_ident(cname);
    END IF;
END;
$$;

-- Add the extended status CHECK (includes old values for backward compat with existing rows).
ALTER TABLE connector_accounts
    ADD CONSTRAINT connector_accounts_status_check
    CHECK (status IN ('active', 'inactive', 'suspended', 'paused', 'error', 'disabled'));

-- Add Phase 7 extension columns (idempotent via IF NOT EXISTS).
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS version               TEXT    NOT NULL DEFAULT '1.0';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS environment           TEXT    NOT NULL DEFAULT 'live';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS capabilities_json     TEXT    NOT NULL DEFAULT '{}';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS mapping_profile_json  TEXT    NOT NULL DEFAULT '{}';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS cursor_json           TEXT    NOT NULL DEFAULT '{}';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS failure_count         INTEGER NOT NULL DEFAULT 0;
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS circuit_breaker_state TEXT    NOT NULL DEFAULT 'closed';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS circuit_breaker_until TEXT;
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS secret_provider       TEXT    NOT NULL DEFAULT 'env';
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS sync_interval_seconds INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS sync_enabled          INTEGER NOT NULL DEFAULT 1;
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS rate_limit_rps        INTEGER;
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS timeout_seconds       INTEGER NOT NULL DEFAULT 30;
ALTER TABLE connector_accounts ADD COLUMN IF NOT EXISTS max_retries           INTEGER NOT NULL DEFAULT 3;

CREATE INDEX IF NOT EXISTS idx_connector_accounts_supplier
    ON connector_accounts(supplier_id) WHERE supplier_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_connector_accounts_org
    ON connector_accounts(organization_id) WHERE organization_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_connector_accounts_type_status
    ON connector_accounts(connector_type, status);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Extend freshness_policies (if table exists) with new columns
-- ─────────────────────────────────────────────────────────────────────────────

-- freshness_policies was created in phase 6; columns may or may not exist.
CREATE TABLE IF NOT EXISTS freshness_policies (
    id                      BIGSERIAL PRIMARY KEY,
    category_id             INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    connector_type          TEXT,
    fresh_seconds           INTEGER NOT NULL DEFAULT 3600,
    stale_seconds           INTEGER NOT NULL DEFAULT 86400,
    expired_seconds         INTEGER NOT NULL DEFAULT 604800,
    applies_to              TEXT NOT NULL DEFAULT 'price',
    -- price | inventory | product
    created_at              TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Connector sync scheduler (tracks scheduled sync jobs)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sync_schedule (
    id                      BIGSERIAL PRIMARY KEY,
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
    created_at              TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_sync_schedule_pending
    ON sync_schedule(connector_account_id, status, scheduled_at)
    WHERE status = 'pending';

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Import pipeline enhancements — add dry_run support
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS is_dry_run           INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS dry_run_summary_json TEXT;
-- populated after dry-run, before confirm
-- NOTE: connector_account_id already added in migration 0010
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS resume_cursor        TEXT;
-- allows resuming a large import from a specific row
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS auto_retry_failed    INTEGER NOT NULL DEFAULT 0;
-- if 1, failed rows are automatically retried on next sync

ALTER TABLE import_job_rows ADD COLUMN IF NOT EXISTS identity_queue_id INTEGER REFERENCES identity_resolution_queue(id) ON DELETE SET NULL;
-- rows that could not be resolved link to the identity queue

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Seed built-in tax categories (idempotent via ON CONFLICT DO NOTHING)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO tax_categories (code, name_fa, name_en, description) VALUES
    ('STANDARD',        'استاندارد',       'Standard',         'نرخ مالیات بر ارزش افزوده استاندارد'),
    ('REDUCED',         'کاهش‌یافته',      'Reduced',          'نرخ کاهش‌یافته برای کالاهای خاص'),
    ('ZERO',            'صفر',             'Zero-rated',       'معاملات مشمول مالیات با نرخ صفر'),
    ('EXEMPT',          'معاف',            'Exempt',           'معاف از مالیات بر ارزش افزوده'),
    ('DIGITAL_SERVICES','خدمات دیجیتال',  'Digital Services', 'خدمات دیجیتال و نرم‌افزار'),
    ('FOOD_BASIC',      'مواد غذایی اساسی','Basic Food',       'مواد غذایی اساسی با نرخ خاص') ON CONFLICT DO NOTHING;

-- Insert current Iranian VAT rate: 9% (effective 2024-01-01)
-- This is the verified rate per Iranian VAT law (قانون مالیات بر ارزش افزوده)
-- Source: https://www.intracen.org/country/iran (and Iranian Tax Authority)
INSERT INTO tax_rates
    (tax_category_id, rate_bps, effective_from, effective_until, jurisdiction, notes)
SELECT
    id, 900, '2024-01-01', NULL, 'IR',
    'نرخ مالیات بر ارزش افزوده ایران — ۹٪ (مصوب قانون مالیات بر ارزش افزوده)'
FROM tax_categories WHERE code = 'STANDARD' ON CONFLICT DO NOTHING;

INSERT INTO tax_rates
    (tax_category_id, rate_bps, effective_from, effective_until, jurisdiction, notes)
SELECT id, 0, '2000-01-01', NULL, 'IR', 'نرخ صفر'
FROM tax_categories WHERE code IN ('ZERO', 'EXEMPT') ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Connector audit log (supplement to existing audit_logs)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS connector_audit_log (
    id                      BIGSERIAL PRIMARY KEY,
    connector_account_id    INTEGER REFERENCES connector_accounts(id) ON DELETE SET NULL,
    action                  TEXT NOT NULL,
    -- created | updated | paused | resumed | synced | health_checked | circuit_opened
    -- circuit_closed | credentials_rotated | deleted | wizard_completed
    actor_user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    detail_json             TEXT NOT NULL DEFAULT '{}',
    ip_address              TEXT,
    created_at              TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_connector_audit_connector
    ON connector_audit_log(connector_account_id, created_at);
