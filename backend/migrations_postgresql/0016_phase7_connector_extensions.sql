-- Phase 7 Migration 0016: Universal Integration Gateway extensions
-- Adds: connector account enhancements, integration events outbox,
--       tax foundation tables, circuit breaker state, accounting connector accounts.
-- All DDL is additive / backward-compatible with Phase 6 data.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Extend connector_accounts
-- SQLite allows ADD COLUMN with a DEFAULT but not inline CHECK on new columns.
-- Enforcement is done at the service layer.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE connector_accounts ADD COLUMN version TEXT NOT NULL DEFAULT '1.0';
ALTER TABLE connector_accounts ADD COLUMN environment TEXT NOT NULL DEFAULT 'live';
-- environment values: sandbox | live | test  (enforced in service layer)

ALTER TABLE connector_accounts ADD COLUMN capabilities_json TEXT NOT NULL DEFAULT '{}';
-- declared capabilities: list of supported operations

ALTER TABLE connector_accounts ADD COLUMN mapping_profile_json TEXT NOT NULL DEFAULT '{}';
-- field rename, unit conversion, category mapping, SKU mapping rules

ALTER TABLE connector_accounts ADD COLUMN cursor_json TEXT NOT NULL DEFAULT '{}';
-- incremental sync cursor: {"product": "...", "price": "...", "inventory": "..."}

ALTER TABLE connector_accounts ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE connector_accounts ADD COLUMN circuit_breaker_state TEXT NOT NULL DEFAULT 'closed';
-- circuit_breaker_state: closed | open | half_open  (enforced in service layer)
ALTER TABLE connector_accounts ADD COLUMN circuit_breaker_until TEXT;
-- ISO-8601 timestamp when the circuit re-closes (NULL when closed)

ALTER TABLE connector_accounts ADD COLUMN secret_provider TEXT NOT NULL DEFAULT 'env';
-- secret_provider: env | vault | ssm | plaintext_test_only

ALTER TABLE connector_accounts ADD COLUMN sync_interval_seconds INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE connector_accounts ADD COLUMN sync_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE connector_accounts ADD COLUMN rate_limit_rps INTEGER;
-- requests per second cap (NULL = unlimited / adapter-defined)

ALTER TABLE connector_accounts ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 30;
ALTER TABLE connector_accounts ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 3;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Integration Events — outbox / inbox pattern
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS integration_events (
    id               BIGSERIAL PRIMARY KEY,
    event_type       TEXT NOT NULL,
    -- e.g. PRODUCT_UPDATED, PRICE_UPDATED, STOCK_UPDATED, ORDER_CREATED, ...
    direction        TEXT NOT NULL DEFAULT 'outbound',
    -- outbound = 60online → external | inbound = external → 60online

    -- Source / target context
    connector_account_id INTEGER REFERENCES connector_accounts(id) ON DELETE SET NULL,
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    organization_id  INTEGER REFERENCES organizations(id) ON DELETE SET NULL,

    -- Payload
    payload_json     TEXT NOT NULL DEFAULT '{}',
    -- External idempotency
    external_event_id TEXT,
    -- stable ID from the external system (for inbound dedup)

    -- Lifecycle
    status           TEXT NOT NULL DEFAULT 'pending',
    -- pending | processing | delivered | failed | dead_letter | replayed

    attempt_count    INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  TEXT,
    last_error       TEXT,
    delivered_at     TEXT,
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_integration_events_status
    ON integration_events(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_integration_events_external_id
    ON integration_events(external_event_id) WHERE external_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_integration_events_connector
    ON integration_events(connector_account_id, event_type, status);
CREATE INDEX IF NOT EXISTS idx_integration_events_type
    ON integration_events(event_type, status, created_at);

-- Prevent duplicate inbound events from same external source
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_events_external
    ON integration_events(connector_account_id, external_event_id)
    WHERE external_event_id IS NOT NULL AND direction = 'inbound';

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Event consumers (inbox delivery tracking per subscriber)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS event_consumers (
    id               BIGSERIAL PRIMARY KEY,
    event_id         INTEGER NOT NULL REFERENCES integration_events(id) ON DELETE CASCADE,
    consumer_name    TEXT NOT NULL,
    -- e.g. 'stock_updater', 'price_sync', 'erp_push'
    status           TEXT NOT NULL DEFAULT 'pending',
    -- pending | processing | consumed | failed
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    consumed_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_event_consumers
    ON event_consumers(event_id, consumer_name);
CREATE INDEX IF NOT EXISTS idx_event_consumers_pending
    ON event_consumers(status, event_id) WHERE status IN ('pending', 'failed');

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Tax foundation
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tax_categories (
    id               BIGSERIAL PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    -- e.g. STANDARD, REDUCED, ZERO, EXEMPT, DIGITAL_SERVICES
    name_fa          TEXT NOT NULL,
    name_en          TEXT NOT NULL,
    description      TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE TABLE IF NOT EXISTS tax_rates (
    id               BIGSERIAL PRIMARY KEY,
    tax_category_id  INTEGER NOT NULL REFERENCES tax_categories(id),
    rate_bps         INTEGER NOT NULL,
    -- basis points: 900 = 9%, 0 = 0%, 10000 = 100%
    -- CHECK enforced in service layer: 0 <= rate_bps <= 10000
    effective_from   TEXT NOT NULL,
    -- ISO-8601 date (YYYY-MM-DD) when this rate takes effect
    effective_until  TEXT,
    -- NULL means current rate
    jurisdiction     TEXT NOT NULL DEFAULT 'IR',
    -- ISO 3166-1 alpha-2 country code; subdivision in jurisdiction_detail
    jurisdiction_detail TEXT,
    -- e.g. 'IR-THR' for Tehran province
    notes            TEXT,
    created_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_tax_rates_category_date
    ON tax_rates(tax_category_id, effective_from, effective_until);

-- Ensure no overlapping rates for same category + jurisdiction
CREATE TABLE IF NOT EXISTS tax_product_assignments (
    id               BIGSERIAL PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    tax_category_id  INTEGER NOT NULL REFERENCES tax_categories(id),
    effective_from   TEXT NOT NULL DEFAULT '2000-01-01',
    effective_until  TEXT,
    assigned_by      INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    UNIQUE(product_id, effective_from)
);

CREATE TABLE IF NOT EXISTS tax_org_exemptions (
    id               BIGSERIAL PRIMARY KEY,
    organization_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tax_category_id  INTEGER NOT NULL REFERENCES tax_categories(id),
    exemption_ref    TEXT,
    -- official exemption certificate reference number
    effective_from   TEXT NOT NULL,
    effective_until  TEXT,
    created_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Accounting connector accounts
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS accounting_connector_accounts (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    accounting_system TEXT NOT NULL,
    -- MOCK | CSV_EXPORT | SEPIDAR | RAHKARAN | HOLO | SAP | ODOO | CUSTOM | OTHER
    -- NOT IMPLEMENTED marker stored in implementation_status
    implementation_status TEXT NOT NULL DEFAULT 'not_implemented',
    -- not_implemented | simulator | verified | production

    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    organization_id  INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    -- Exactly one of supplier_id or organization_id must be set (enforced in service)

    credential_ref   TEXT,
    -- NEVER store plaintext credentials — this is a reference key only
    config_json      TEXT NOT NULL DEFAULT '{}',
    version          TEXT NOT NULL DEFAULT '1.0',
    environment      TEXT NOT NULL DEFAULT 'live',
    -- sandbox | live | test

    capabilities_json TEXT NOT NULL DEFAULT '{}',
    -- declared capabilities: export_invoices, import_invoices, export_payments, etc.

    status           TEXT NOT NULL DEFAULT 'active',
    -- active | paused | error | disabled
    last_export_at   TEXT,
    last_import_at   TEXT,
    last_error       TEXT,
    failure_count    INTEGER NOT NULL DEFAULT 0,

    official_docs_url  TEXT,
    docs_version       TEXT,
    docs_date          TEXT,
    sandbox_available  INTEGER NOT NULL DEFAULT 0,
    auth_method        TEXT,

    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_accounting_connectors_supplier
    ON accounting_connector_accounts(supplier_id) WHERE supplier_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_accounting_connectors_org
    ON accounting_connector_accounts(organization_id) WHERE organization_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Accounting documents (normalized, system-agnostic)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS accounting_documents (
    id               BIGSERIAL PRIMARY KEY,
    connector_account_id INTEGER REFERENCES accounting_connector_accounts(id) ON DELETE SET NULL,
    document_type    TEXT NOT NULL,
    -- sales_invoice | purchase_invoice | credit_note | payment | settlement | other
    direction        TEXT NOT NULL DEFAULT 'outbound',
    -- outbound = export to ERP | inbound = import from ERP

    -- 60online internal links
    order_id         INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    fulfillment_order_id INTEGER REFERENCES fulfillment_orders(id) ON DELETE SET NULL,
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    organization_id  INTEGER REFERENCES organizations(id) ON DELETE SET NULL,

    -- External system reference
    external_doc_id  TEXT,
    external_doc_number TEXT,

    -- Content
    total_minor      INTEGER NOT NULL DEFAULT 0,
    tax_minor        INTEGER NOT NULL DEFAULT 0,
    currency         TEXT NOT NULL DEFAULT 'IRR',
    document_date    TEXT,
    document_json    TEXT NOT NULL DEFAULT '{}',
    -- normalized document structure

    -- Lifecycle
    status           TEXT NOT NULL DEFAULT 'pending',
    -- pending | exported | imported | reconciled | error | rejected
    reconciled_at    TEXT,
    error_message    TEXT,

    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_accounting_docs_connector
    ON accounting_documents(connector_account_id, status);
CREATE INDEX IF NOT EXISTS idx_accounting_docs_order
    ON accounting_documents(order_id) WHERE order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_accounting_docs_external
    ON accounting_documents(connector_account_id, external_doc_id)
    WHERE external_doc_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Carrier adapter accounts (extends existing carrier_configs)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS carrier_adapter_accounts (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    provider_code    TEXT NOT NULL,
    -- MOCK | ALOPEYK | POST_IR | TIPAX | CHAPAR | SUPPLIER_FLEET | MANUAL | OTHER
    implementation_status TEXT NOT NULL DEFAULT 'not_implemented',
    -- not_implemented | simulator | verified | production

    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    -- NULL = platform-level carrier

    credential_ref   TEXT,
    config_json      TEXT NOT NULL DEFAULT '{}',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    -- quote | create_shipment | cancel_shipment | get_tracking | webhook

    environment      TEXT NOT NULL DEFAULT 'live',
    status           TEXT NOT NULL DEFAULT 'active',
    failure_count    INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_state TEXT NOT NULL DEFAULT 'closed',
    circuit_breaker_until TEXT,
    last_used_at     TEXT,
    last_error       TEXT,

    official_docs_url  TEXT,
    docs_version       TEXT,
    docs_date          TEXT,
    sandbox_available  INTEGER NOT NULL DEFAULT 0,
    auth_method        TEXT,

    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_carrier_adapter_accounts_provider
    ON carrier_adapter_accounts(provider_code, status);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Connector mapping templates (reusable field maps for onboarding wizard)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS connector_mapping_templates (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    connector_type   TEXT NOT NULL,
    -- matches connector_accounts.connector_type
    template_json    TEXT NOT NULL DEFAULT '{}',
    -- field rename, unit conversion, category mapping, SKU mapping rules
    is_builtin       INTEGER NOT NULL DEFAULT 0,
    -- 1 = shipped with 60online, 0 = user-defined
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE CASCADE,
    -- NULL = global template
    created_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. Connector onboarding wizard sessions
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS connector_wizard_sessions (
    id               BIGSERIAL PRIMARY KEY,
    session_token    TEXT NOT NULL UNIQUE,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    supplier_id      INTEGER REFERENCES suppliers(id) ON DELETE CASCADE,
    connector_type   TEXT,
    current_step     TEXT NOT NULL DEFAULT 'choose_system',
    -- choose_system | enter_connection | test_connection | discover_fields
    -- map_fields | preview | dry_run | activate
    step_data_json   TEXT NOT NULL DEFAULT '{}',
    -- accumulated wizard state across steps
    status           TEXT NOT NULL DEFAULT 'in_progress',
    -- in_progress | completed | abandoned
    connector_account_id INTEGER REFERENCES connector_accounts(id),
    -- set when wizard completes and account is created
    expires_at       TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at       TEXT NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE INDEX IF NOT EXISTS idx_wizard_sessions_user
    ON connector_wizard_sessions(user_id, status);
