-- 0024_vat_in_total
--
-- Phase 8 v6: Integrate VAT into the authoritative money equation.
--
-- BEFORE (v5): total_minor = subtotal_minor + shipping_fee_minor
--              tax_minor was informational only — NOT collected
--
-- AFTER  (v6): total_minor = subtotal_minor + shipping_fee_minor + tax_minor
--              total_minor = credit_minor + cash_minor
--              VAT is collected as part of every order payment.
--
-- Changes:
--   orders         — new CHECK, add taxable_base_minor, tax_rate_bps columns
--   payment_intents — add tax_minor, taxable_base_minor, tax_rate_bps columns;
--                     update CHECK to include tax_minor
--   ledger_accounts — add account 2010 (VAT Payable liability)
--
-- SQLite cannot ALTER CHECK constraints, so both tables are rebuilt.
-- FK enforcement is temporarily disabled during the rebuild using the
-- COMMIT / PRAGMA / BEGIN pattern, which moves the PRAGMA outside the
-- enclosing transaction where it becomes effective.
--
-- Historical rows are handled safely:
--   Existing orders have tax_minor = 0 (set by migration 0023), so
--   total_minor = subtotal_minor + shipping_fee_minor + 0 = old total. ✓
--   New payment_intents rows get DEFAULT 0 for old intents (none exist
--   in production at migration time; test suite clears between runs).

-- ── Step out of the migrator wrapper BEGIN so PRAGMA takes effect ────────────
COMMIT;
PRAGMA foreign_keys = OFF;
BEGIN;

-- ────────────────────────────────────────────────────────────────────────────
-- Rebuild payment_intents with updated CHECK and three new tax columns
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE payment_intents_v2 (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    reference            TEXT    NOT NULL UNIQUE,
    user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    idempotency_key      TEXT    NOT NULL,
    request_hash         TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','authorized','captured','failed','cancelled')),
    currency             TEXT    NOT NULL DEFAULT 'IRR',
    subtotal_minor       INTEGER NOT NULL CHECK (subtotal_minor >= 0),
    shipping_fee_minor   INTEGER NOT NULL DEFAULT 0 CHECK (shipping_fee_minor >= 0),
    -- VAT fields (new in 0024)
    tax_minor            INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    taxable_base_minor   INTEGER NOT NULL DEFAULT 0 CHECK (taxable_base_minor >= 0),
    tax_rate_bps         INTEGER NOT NULL DEFAULT 0 CHECK (tax_rate_bps >= 0),
    total_minor          INTEGER NOT NULL CHECK (total_minor >= 0),
    credit_minor         INTEGER NOT NULL DEFAULT 0 CHECK (credit_minor >= 0),
    cash_minor           INTEGER NOT NULL DEFAULT 0 CHECK (cash_minor >= 0),
    organization_id      INTEGER REFERENCES organizations(id) ON DELETE RESTRICT,
    allocation_id        INTEGER REFERENCES credit_allocations(id) ON DELETE RESTRICT,
    provider             TEXT,
    provider_ref         TEXT,
    failure_reason       TEXT,
    order_id             INTEGER REFERENCES orders(id) ON DELETE RESTRICT,
    recipient_name       TEXT    NOT NULL,
    recipient_phone      TEXT    NOT NULL,
    shipping_province    TEXT    NOT NULL,
    shipping_city        TEXT    NOT NULL,
    shipping_line1       TEXT    NOT NULL,
    shipping_postal_code TEXT,
    fulfillment_plan_json TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Updated: total now includes tax
    CHECK (total_minor = subtotal_minor + shipping_fee_minor + tax_minor),
    CHECK (total_minor = credit_minor + cash_minor),
    CHECK (credit_minor = 0 OR (organization_id IS NOT NULL AND allocation_id IS NOT NULL))
);

INSERT INTO payment_intents_v2
    (id, reference, user_id, idempotency_key, request_hash, status, currency,
     subtotal_minor, shipping_fee_minor,
     tax_minor, taxable_base_minor, tax_rate_bps,
     total_minor, credit_minor, cash_minor,
     organization_id, allocation_id,
     provider, provider_ref, failure_reason, order_id,
     recipient_name, recipient_phone,
     shipping_province, shipping_city, shipping_line1, shipping_postal_code,
     fulfillment_plan_json, created_at, updated_at)
SELECT
    id, reference, user_id, idempotency_key, request_hash, status, currency,
    subtotal_minor, shipping_fee_minor,
    0            AS tax_minor,
    subtotal_minor AS taxable_base_minor,
    0            AS tax_rate_bps,
    total_minor, credit_minor, cash_minor,
    organization_id, allocation_id,
    provider, provider_ref, failure_reason, order_id,
    recipient_name, recipient_phone,
    shipping_province, shipping_city, shipping_line1, shipping_postal_code,
    fulfillment_plan_json, created_at, updated_at
FROM payment_intents;

DROP TABLE payment_intents;
ALTER TABLE payment_intents_v2 RENAME TO payment_intents;

CREATE INDEX idx_intents_user   ON payment_intents(user_id, id DESC);
CREATE INDEX idx_intents_status ON payment_intents(status, created_at);
CREATE UNIQUE INDEX idx_intents_idem ON payment_intents(user_id, idempotency_key);

-- ────────────────────────────────────────────────────────────────────────────
-- Rebuild orders with updated CHECK and two new columns
-- (tax_minor already exists from migration 0023)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE orders_v2 (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number         TEXT    NOT NULL UNIQUE,
    user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status               TEXT    NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','paid','fulfilling','delivered','cancelled','refunded')),
    subtotal_minor       INTEGER NOT NULL CHECK (subtotal_minor >= 0),
    shipping_fee_minor   INTEGER NOT NULL DEFAULT 0 CHECK (shipping_fee_minor >= 0),
    tax_minor            INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    -- New in 0024: snapshot the taxable base and effective rate for audit
    taxable_base_minor   INTEGER NOT NULL DEFAULT 0 CHECK (taxable_base_minor >= 0),
    tax_rate_bps         INTEGER NOT NULL DEFAULT 0 CHECK (tax_rate_bps >= 0),
    total_minor          INTEGER NOT NULL CHECK (total_minor >= 0),
    currency             TEXT    NOT NULL DEFAULT 'IRR',
    recipient_name       TEXT    NOT NULL,
    recipient_phone      TEXT    NOT NULL,
    shipping_province    TEXT    NOT NULL,
    shipping_city        TEXT    NOT NULL,
    shipping_line1       TEXT    NOT NULL,
    shipping_postal_code TEXT,
    placed_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Phase 2 additions (nullable / defaulted)
    organization_id      INTEGER REFERENCES organizations(id),
    credit_minor         INTEGER NOT NULL DEFAULT 0,
    cash_minor           INTEGER NOT NULL DEFAULT 0,
    payment_intent_id    INTEGER REFERENCES payment_intents(id),
    -- Updated constraint: total = sub + ship + tax
    CHECK (total_minor = subtotal_minor + shipping_fee_minor + tax_minor)
);

INSERT INTO orders_v2
    (id, order_number, user_id, status,
     subtotal_minor, shipping_fee_minor, tax_minor,
     taxable_base_minor, tax_rate_bps,
     total_minor, currency,
     recipient_name, recipient_phone,
     shipping_province, shipping_city, shipping_line1, shipping_postal_code,
     placed_at,
     organization_id, credit_minor, cash_minor, payment_intent_id)
SELECT
    id, order_number, user_id, status,
    subtotal_minor, shipping_fee_minor, tax_minor,
    subtotal_minor AS taxable_base_minor,
    0              AS tax_rate_bps,
    total_minor, currency,
    recipient_name, recipient_phone,
    shipping_province, shipping_city, shipping_line1, shipping_postal_code,
    placed_at,
    organization_id, credit_minor, cash_minor, payment_intent_id
FROM orders;

DROP TABLE orders;
ALTER TABLE orders_v2 RENAME TO orders;

CREATE INDEX idx_orders_user         ON orders(user_id, placed_at DESC);
CREATE INDEX idx_orders_organization ON orders(organization_id, placed_at DESC);

COMMIT;

-- ── Re-enable FK enforcement and open a clean transaction for the migrator ───
PRAGMA foreign_keys = ON;
BEGIN;

-- ── Add VAT payable liability account (idempotent) ───────────────────────────
INSERT OR IGNORE INTO ledger_accounts (code, name_fa, type)
    VALUES ('2010', 'مالیات بر ارزش افزوده پرداختنی', 'liability');
