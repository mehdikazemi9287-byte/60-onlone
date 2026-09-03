-- 0012_exceptions
--
-- Phase 6 Final: Exception inbox and connector health log.
--
-- PURELY ADDITIVE (CREATE TABLE IF NOT EXISTS only).
-- The migrator wraps this in BEGIN;...COMMIT; automatically.

CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_type TEXT NOT NULL CHECK (exception_type IN (
        'unknown_product','identifier_conflict','ambiguous_match',
        'suspicious_price_jump','invalid_stock','stale_source',
        'connector_outage','invoice_mismatch','duplicate_invoice',
        'reconciliation_mismatch','malformed_data','three_way_mismatch',
        'credential_warning','other'
    )),
    severity TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high','critical')),
    supplier_id INTEGER REFERENCES suppliers(id),
    connector_account_id INTEGER REFERENCES connector_accounts(id),
    sync_run_id INTEGER REFERENCES sync_runs(id),
    title TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','assigned','resolved','ignored','retrying')),
    assigned_to INTEGER REFERENCES users(id),
    resolved_by INTEGER REFERENCES users(id),
    resolved_at TEXT,
    resolution_notes TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_retry_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_exc_type ON exceptions(exception_type, status);
CREATE INDEX IF NOT EXISTS idx_exc_supplier ON exceptions(supplier_id, status);
CREATE INDEX IF NOT EXISTS idx_exc_status ON exceptions(status, created_at DESC);

CREATE TABLE IF NOT EXISTS connector_health_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_account_id INTEGER NOT NULL REFERENCES connector_accounts(id),
    status TEXT NOT NULL CHECK (status IN ('healthy','unhealthy','degraded','timeout','auth_failed')),
    latency_ms INTEGER,
    error_message TEXT,
    checked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_chl_connector ON connector_health_log(connector_account_id, checked_at DESC);
