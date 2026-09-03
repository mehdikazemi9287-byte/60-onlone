-- 0021_extend_connector_types (PostgreSQL-native)
--
-- Phase 7 Final Repair — three-blocker fixes (additive).
--
-- 1. Extend connector_accounts.connector_type CHECK to include all types
--    registered in adapters/connectors/registry.py.
--    PostgreSQL supports DROP CONSTRAINT + ADD CONSTRAINT, so no table rebuild needed.
--
-- 2. Add idempotency_key column to integration_events for per-connector
--    fan-out delivery tracking.
--
-- 3. Create unique index on idempotency_key so duplicate fan-out insertions
--    are prevented even under concurrent writes.
--
-- PURELY ADDITIVE for all other tables. No existing data is lost.

-- Step 1: Drop the existing CHECK constraint on connector_type.
-- PostgreSQL auto-names inline column CHECK constraints as <table>_<column>_check.
-- We use a DO block to find and drop it by name regardless of how it was auto-named.
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

-- Step 2: Add the extended CHECK constraint with all registered types.
ALTER TABLE connector_accounts
    ADD CONSTRAINT connector_accounts_connector_type_check
    CHECK (connector_type IN (
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
    ));

-- Ensure indexes exist (idempotent)
CREATE INDEX IF NOT EXISTS idx_ca_supplier  ON connector_accounts(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ca_status    ON connector_accounts(status);
CREATE INDEX IF NOT EXISTS idx_ca_org       ON connector_accounts(organization_id) WHERE organization_id IS NOT NULL;

-- Step 3: Add idempotency_key to integration_events for per-connector fan-out.
-- Column is nullable so existing rows remain valid.
ALTER TABLE integration_events ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

-- Unique index prevents duplicate fan-out insertions for the same
-- business event + connector pair.
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_events_idempotency
    ON integration_events(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
