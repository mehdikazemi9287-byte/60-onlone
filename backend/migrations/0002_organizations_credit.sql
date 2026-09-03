-- 0002_organizations_credit
--
-- Phase 2: Organizations, employee membership, employer-funded credit,
-- credit ledger, credit reservations, and the payment-intent state machine
-- that makes split payment safe without assuming the PSP call is atomic with
-- the database.
--
-- This migration is PURELY ADDITIVE. It creates new tables and adds two
-- nullable/defaulted columns to existing ones. No Phase 1 table is dropped,
-- renamed, or has a column removed, so every Flow 1 row and query keeps
-- working unchanged.
--
-- Money: as in 0001, every monetary column is an INTEGER count of currency
-- minor units. There is no REAL/FLOAT column in this schema.
--
-- Balances: deliberately absent. `available_credit`, `reserved` and `consumed`
-- are DERIVED by folding credit_ledger_entries (see app/services/credit_service.py).
-- Storing them would let a balance drift away from its ledger, which is the
-- failure mode 0001 already designed against for the financial ledger.

-- ------------------------------------------------------------ organizations
CREATE TABLE organizations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    legal_name         TEXT    NOT NULL,
    display_name       TEXT    NOT NULL,
    -- Iranian شناسه ملی اشخاص حقوقی / company registration identifier.
    national_id        TEXT    NOT NULL UNIQUE,
    status             TEXT    NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending','active','suspended','inactive')),
    -- How credit is funded. Only 'employer_funded' is implemented in Phase 2;
    -- the other values exist so the column does not need widening later.
    credit_policy      TEXT    NOT NULL DEFAULT 'employer_funded'
                               CHECK (credit_policy IN ('employer_funded','platform_funded','external_provider','none')),
    -- Ceiling on the total the organization may have allocated at once.
    credit_limit_minor INTEGER NOT NULL DEFAULT 0 CHECK (credit_limit_minor >= 0),
    currency           TEXT    NOT NULL DEFAULT 'IRR',
    billing_email      TEXT,
    billing_phone      TEXT,
    billing_address    TEXT,
    economic_code      TEXT,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organizations_status ON organizations(status);

-- ------------------------------------------------- organization memberships
-- A user may be a plain retail customer (no row here), or belong to one or
-- more organizations (one row each). The UNIQUE constraint allows multiple
-- organizations per user while forbidding a duplicate membership.
CREATE TABLE organization_memberships (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT    NOT NULL DEFAULT 'employee'
                            CHECK (role IN ('employee','organization_admin','procurement_agent','organization_finance')),
    status          TEXT    NOT NULL DEFAULT 'active'
                            CHECK (status IN ('invited','active','inactive')),
    employee_code   TEXT,
    department      TEXT,
    invited_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (organization_id, user_id)
);
CREATE INDEX idx_memberships_user ON organization_memberships(user_id, status);
CREATE INDEX idx_memberships_org ON organization_memberships(organization_id, status);
CREATE UNIQUE INDEX idx_memberships_employee_code
    ON organization_memberships(organization_id, employee_code)
    WHERE employee_code IS NOT NULL;

-- -------------------------------------------------------- credit allocations
-- One grant of purchasing credit from an organization to one of its members.
-- allocated/available/reserved/consumed: only `allocated_minor` is stored, and
-- only because it is the immutable face value of the grant. The other three
-- are folded from credit_ledger_entries.
CREATE TABLE credit_allocations (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    reference                 TEXT    NOT NULL UNIQUE,
    organization_id           INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    membership_id             INTEGER NOT NULL REFERENCES organization_memberships(id) ON DELETE RESTRICT,
    user_id                   INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    allocated_minor           INTEGER NOT NULL CHECK (allocated_minor > 0),
    currency                  TEXT    NOT NULL DEFAULT 'IRR',
    valid_from                TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at                TEXT,
    status                    TEXT    NOT NULL DEFAULT 'active'
                                      CHECK (status IN ('active','revoked','expired')),
    -- Optional restriction to a set of category slugs, stored as a JSON array.
    -- NULL means "no category restriction".
    category_slugs_json       TEXT,
    -- Optional caps. NULL means "no cap".
    per_transaction_limit_minor INTEGER CHECK (per_transaction_limit_minor IS NULL OR per_transaction_limit_minor > 0),
    period_limit_minor          INTEGER CHECK (period_limit_minor IS NULL OR period_limit_minor > 0),
    note                      TEXT,
    -- Which funding source backs this allocation. Phase 2 implements
    -- 'organization' only; the CreditProvider port (app/adapters/credit) is
    -- how a bank / leasing / fintech source plugs in later.
    funding_source            TEXT    NOT NULL DEFAULT 'organization'
                                      CHECK (funding_source IN ('organization','platform','external')),
    created_by_user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at                TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at                TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (expires_at IS NULL OR expires_at > valid_from),
    -- An employee must never fund themselves. Enforced in the service layer
    -- too, but a storage-level guard cannot be bypassed by a new code path.
    CHECK (created_by_user_id <> user_id)
);
CREATE INDEX idx_allocations_user ON credit_allocations(user_id, status);
CREATE INDEX idx_allocations_org ON credit_allocations(organization_id, status);
CREATE INDEX idx_allocations_membership ON credit_allocations(membership_id);

-- ------------------------------------------------------- credit ledger
-- Append-only movement log. This IS the credit balance; nothing else is.
--
--   allocation  (+) increases allocated
--   adjustment  (±) changes allocated
--   reservation (+) available -> reserved
--   release     (+) reserved  -> available
--   capture     (+) reserved  -> consumed
--
-- available = allocated - reserved_outstanding - consumed
--   allocated            = SUM(allocation) + SUM(adjustment)
--   reserved_outstanding = SUM(reservation) - SUM(release) - SUM(capture)
--   consumed             = SUM(capture)
CREATE TABLE credit_ledger_entries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    reference         TEXT    NOT NULL,
    allocation_id     INTEGER NOT NULL REFERENCES credit_allocations(id) ON DELETE RESTRICT,
    organization_id   INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    entry_type        TEXT    NOT NULL
                              CHECK (entry_type IN ('allocation','reservation','release','capture','adjustment')),
    amount_minor      INTEGER NOT NULL,
    currency          TEXT    NOT NULL DEFAULT 'IRR',
    order_id          INTEGER REFERENCES orders(id) ON DELETE RESTRICT,
    payment_intent_id INTEGER,
    reservation_id    INTEGER,
    actor_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note              TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Only an adjustment may be negative; every other movement is positive and
    -- carries its direction in entry_type.
    CHECK (amount_minor <> 0),
    CHECK (entry_type = 'adjustment' OR amount_minor > 0)
);
CREATE INDEX idx_credit_ledger_allocation ON credit_ledger_entries(allocation_id, id);
CREATE INDEX idx_credit_ledger_user ON credit_ledger_entries(user_id, id DESC);
CREATE INDEX idx_credit_ledger_org ON credit_ledger_entries(organization_id, id DESC);
CREATE INDEX idx_credit_ledger_order ON credit_ledger_entries(order_id);

CREATE TRIGGER credit_ledger_no_update
BEFORE UPDATE ON credit_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'credit_ledger_entries is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER credit_ledger_no_delete
BEFORE DELETE ON credit_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'credit_ledger_entries is append-only: DELETE is forbidden');
END;

-- ----------------------------------------------------- credit reservations
-- The handle a checkout holds so it can later capture or release. State here
-- is a projection of the credit ledger; the ledger remains the source of truth.
CREATE TABLE credit_reservations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    reference         TEXT    NOT NULL UNIQUE,
    allocation_id     INTEGER NOT NULL REFERENCES credit_allocations(id) ON DELETE RESTRICT,
    organization_id   INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    payment_intent_id INTEGER NOT NULL,
    amount_minor      INTEGER NOT NULL CHECK (amount_minor > 0),
    currency          TEXT    NOT NULL DEFAULT 'IRR',
    status            TEXT    NOT NULL DEFAULT 'held'
                              CHECK (status IN ('held','captured','released')),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    settled_at        TEXT
);
-- One checkout attempt holds at most one credit reservation. Making this
-- UNIQUE is what makes reserve() idempotent at the storage layer rather than
-- only in application code.
CREATE UNIQUE INDEX idx_reservations_intent ON credit_reservations(payment_intent_id);
CREATE INDEX idx_reservations_allocation ON credit_reservations(allocation_id, status);

-- --------------------------------------------------------- payment intents
-- One checkout attempt. Created and committed BEFORE the PSP is contacted, so
-- a crash mid-call leaves a durable record to reconcile against instead of an
-- invisible lost charge. See app/services/payment_service.py.
--
-- States: pending -> authorized -> captured
--         pending -> failed
--         pending -> cancelled   (reclaimed after being abandoned)
CREATE TABLE payment_intents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    reference         TEXT    NOT NULL UNIQUE,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    idempotency_key   TEXT    NOT NULL,
    request_hash      TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','authorized','captured','failed','cancelled')),
    currency          TEXT    NOT NULL DEFAULT 'IRR',
    subtotal_minor    INTEGER NOT NULL CHECK (subtotal_minor >= 0),
    shipping_fee_minor INTEGER NOT NULL DEFAULT 0 CHECK (shipping_fee_minor >= 0),
    total_minor       INTEGER NOT NULL CHECK (total_minor >= 0),
    credit_minor      INTEGER NOT NULL DEFAULT 0 CHECK (credit_minor >= 0),
    cash_minor        INTEGER NOT NULL DEFAULT 0 CHECK (cash_minor >= 0),
    organization_id   INTEGER REFERENCES organizations(id) ON DELETE RESTRICT,
    allocation_id     INTEGER REFERENCES credit_allocations(id) ON DELETE RESTRICT,
    provider          TEXT,
    provider_ref      TEXT,
    failure_reason    TEXT,
    order_id          INTEGER REFERENCES orders(id) ON DELETE RESTRICT,
    -- Shipping address is captured at attempt time so the order can be created
    -- in phase two without re-reading anything the client could have changed.
    recipient_name       TEXT NOT NULL,
    recipient_phone      TEXT NOT NULL,
    shipping_province    TEXT NOT NULL,
    shipping_city        TEXT NOT NULL,
    shipping_line1       TEXT NOT NULL,
    shipping_postal_code TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (total_minor = subtotal_minor + shipping_fee_minor),
    CHECK (total_minor = credit_minor + cash_minor),
    -- Credit always implies an organization and an allocation behind it.
    CHECK (credit_minor = 0 OR (organization_id IS NOT NULL AND allocation_id IS NOT NULL))
);
CREATE INDEX idx_intents_user ON payment_intents(user_id, id DESC);
CREATE INDEX idx_intents_status ON payment_intents(status, created_at);
CREATE UNIQUE INDEX idx_intents_idem ON payment_intents(user_id, idempotency_key);

-- Immutable snapshot of what the attempt is buying. Without this, a cart edit
-- between phase one and phase two would silently change what gets shipped.
CREATE TABLE payment_intent_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_intent_id INTEGER NOT NULL REFERENCES payment_intents(id) ON DELETE CASCADE,
    product_id        INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    title_fa          TEXT    NOT NULL,
    sku               TEXT    NOT NULL,
    category_slug     TEXT    NOT NULL,
    unit_price_minor  INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    line_total_minor  INTEGER NOT NULL CHECK (line_total_minor >= 0),
    credit_eligible   INTEGER NOT NULL DEFAULT 0 CHECK (credit_eligible IN (0,1)),
    CHECK (line_total_minor = unit_price_minor * quantity)
);
CREATE INDEX idx_intent_items_intent ON payment_intent_items(payment_intent_id);

-- ---------------------------------------------------- extend Phase 1 tables
-- Additive only: both columns are nullable, so every existing row and every
-- existing INSERT in Flow 1 remains valid.
ALTER TABLE orders ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
ALTER TABLE orders ADD COLUMN credit_minor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN cash_minor INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN payment_intent_id INTEGER REFERENCES payment_intents(id);
CREATE INDEX idx_orders_organization ON orders(organization_id, placed_at DESC);

-- The idempotency table gains a lifecycle so a two-phase command can mark an
-- attempt in-flight before it has a response to store.
ALTER TABLE idempotency_keys ADD COLUMN state TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE idempotency_keys ADD COLUMN payment_intent_id INTEGER;

-- ------------------------------------------------------ new ledger accounts
-- 1020 makes the funding source of a split-payment order visible in the GL:
-- the cash leg lands in PSP clearing, the credit leg becomes a receivable from
-- the employing organization, and the two must add up to the order total.
INSERT INTO ledger_accounts (code, name_fa, type) VALUES
    ('1020', 'مطالبات از سازمان‌ها (اعتبار سازمانی)', 'asset');
