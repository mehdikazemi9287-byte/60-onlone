-- Phase 4 — اعتبار و سوپراپ (credit platform).
--
-- Samar model: the ORGANIZATION (or a funder institution / bank) funds the credit and
-- signs a contract; every Saturday a statement of the week's usage is issued, due in
-- 7 days; an overdue statement freezes the organization's credit automatically.
-- The platform never lends its own capital. Also: employee welfare plans, installment
-- agreements + debt sales, seller advances, and the group-platform account link.
--
-- PURELY ADDITIVE. Money is INTEGER minor units (Rial). Timestamps written by the
-- services are UTC 'YYYY-MM-DD HH:MM:SS'. Financial history tables are append-only
-- (triggers); projection tables only allow their status columns to change.

-- ================================================================ credit contracts
CREATE TABLE IF NOT EXISTS credit_contracts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT    NOT NULL UNIQUE,
    organization_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    -- Who funds the credit: the organization itself, a partner institution, or a bank.
    funder_type         TEXT    NOT NULL DEFAULT 'org'
                                CHECK (funder_type IN ('org', 'institution', 'bank')),
    funder_name         TEXT,
    funder_reference    TEXT,
    contract_number     TEXT,
    limit_minor         INTEGER NOT NULL CHECK (limit_minor > 0),
    currency            TEXT    NOT NULL DEFAULT 'IRR',
    cycle               TEXT    NOT NULL DEFAULT 'weekly' CHECK (cycle IN ('weekly')),
    -- Python weekday numbering (Mon=0 … Sat=5, Sun=6); Saturday is the Iranian week start.
    statement_weekday   INTEGER NOT NULL DEFAULT 5 CHECK (statement_weekday BETWEEN 0 AND 6),
    due_days            INTEGER NOT NULL DEFAULT 7 CHECK (due_days BETWEEN 0 AND 90),
    status              TEXT    NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'frozen', 'closed')),
    freeze_reason       TEXT    CHECK (freeze_reason IS NULL OR freeze_reason IN ('overdue', 'manual')),
    starts_at           TEXT    NOT NULL,
    signed_at           TEXT,
    signed_by_name      TEXT,
    idempotency_key     TEXT    NOT NULL UNIQUE,
    created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    closed_at           TEXT
);
CREATE INDEX IF NOT EXISTS ix_credit_contracts_org ON credit_contracts(organization_id, status);
-- At most one live (active or frozen) contract per organization.
CREATE UNIQUE INDEX IF NOT EXISTS ux_credit_contracts_live_org
    ON credit_contracts(organization_id) WHERE status IN ('active', 'frozen');

CREATE TRIGGER IF NOT EXISTS credit_contracts_no_delete
BEFORE DELETE ON credit_contracts
BEGIN
    SELECT RAISE(ABORT, 'credit_contracts cannot be deleted; close the contract instead');
END;

CREATE TRIGGER IF NOT EXISTS credit_contracts_terms_immutable
BEFORE UPDATE OF organization_id, funder_type, limit_minor, cycle, statement_weekday, due_days, starts_at, reference, idempotency_key ON credit_contracts
BEGIN
    SELECT RAISE(ABORT, 'credit contract terms are immutable; sign a new contract');
END;

-- Storage-level freeze: while an organization's contract is frozen, no new credit
-- reservation can be held for it, whatever code path tries.
CREATE TRIGGER IF NOT EXISTS credit_reservations_block_frozen
BEFORE INSERT ON credit_reservations
WHEN EXISTS (SELECT 1 FROM credit_contracts c
             WHERE c.organization_id = NEW.organization_id AND c.status = 'frozen')
BEGIN
    SELECT RAISE(ABORT, 'credit_frozen: organization credit contract is frozen');
END;

-- Append-only freeze/unfreeze/close history.
CREATE TABLE IF NOT EXISTS credit_contract_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id     INTEGER NOT NULL REFERENCES credit_contracts(id) ON DELETE RESTRICT,
    event_type      TEXT    NOT NULL CHECK (event_type IN ('created', 'frozen', 'unfrozen', 'closed')),
    reason          TEXT,
    actor_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_credit_contract_events ON credit_contract_events(contract_id, id);

CREATE TRIGGER IF NOT EXISTS credit_contract_events_no_update
BEFORE UPDATE ON credit_contract_events
BEGIN
    SELECT RAISE(ABORT, 'credit_contract_events is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS credit_contract_events_no_delete
BEFORE DELETE ON credit_contract_events
BEGIN
    SELECT RAISE(ABORT, 'credit_contract_events is append-only: DELETE is forbidden');
END;

-- Payments received from the funder against the contract balance (recorded, not moved).
CREATE TABLE IF NOT EXISTS credit_contract_payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT    NOT NULL UNIQUE,
    contract_id         INTEGER NOT NULL REFERENCES credit_contracts(id) ON DELETE RESTRICT,
    amount_minor        INTEGER NOT NULL CHECK (amount_minor > 0),
    received_at         TEXT    NOT NULL,
    external_reference  TEXT,
    note                TEXT,
    idempotency_key     TEXT    NOT NULL UNIQUE,
    actor_user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_credit_contract_payments ON credit_contract_payments(contract_id, received_at);

CREATE TRIGGER IF NOT EXISTS credit_contract_payments_no_update
BEFORE UPDATE ON credit_contract_payments
BEGIN
    SELECT RAISE(ABORT, 'credit_contract_payments is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS credit_contract_payments_no_delete
BEFORE DELETE ON credit_contract_payments
BEGIN
    SELECT RAISE(ABORT, 'credit_contract_payments is append-only: DELETE is forbidden');
END;

-- Weekly statement. closing = opening + usage - payments (usage folded from
-- credit_ledger_entries captures). Amounts immutable; only status/paid_at change.
CREATE TABLE IF NOT EXISTS credit_statements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT    NOT NULL UNIQUE,
    contract_id         INTEGER NOT NULL REFERENCES credit_contracts(id) ON DELETE RESTRICT,
    organization_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    period_start        TEXT    NOT NULL,
    period_end          TEXT    NOT NULL,
    opening_minor       INTEGER NOT NULL,
    usage_minor         INTEGER NOT NULL,  -- net of capture reversals; may be negative
    payments_minor      INTEGER NOT NULL CHECK (payments_minor >= 0),
    closing_minor       INTEGER NOT NULL,
    due_at              TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid', 'overdue')),
    paid_at             TEXT,
    issued_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (period_end > period_start),
    CHECK (closing_minor = opening_minor + usage_minor - payments_minor),
    UNIQUE (contract_id, period_start)
);
CREATE INDEX IF NOT EXISTS ix_credit_statements_org ON credit_statements(organization_id, period_start);
CREATE INDEX IF NOT EXISTS ix_credit_statements_status ON credit_statements(status, due_at);

CREATE TRIGGER IF NOT EXISTS credit_statements_amounts_immutable
BEFORE UPDATE OF contract_id, organization_id, period_start, period_end, opening_minor, usage_minor, payments_minor, closing_minor, due_at, reference ON credit_statements
BEGIN
    SELECT RAISE(ABORT, 'credit_statements amounts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS credit_statements_no_delete
BEFORE DELETE ON credit_statements
BEGIN
    SELECT RAISE(ABORT, 'credit_statements cannot be deleted');
END;

-- ================================================================ welfare wallet
CREATE TABLE IF NOT EXISTS welfare_plans (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    reference               TEXT    NOT NULL UNIQUE,
    organization_id         INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    title                   TEXT    NOT NULL,
    plan_type               TEXT    NOT NULL CHECK (plan_type IN ('free', 'category', 'product')),
    per_employee_cap_minor  INTEGER NOT NULL CHECK (per_employee_cap_minor > 0),
    starts_at               TEXT    NOT NULL,
    expires_at              TEXT    NOT NULL,
    -- 1 = every active member of the organization; 0 = only welfare_plan_members.
    all_members             INTEGER NOT NULL DEFAULT 1 CHECK (all_members IN (0, 1)),
    status                  TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    idempotency_key         TEXT    NOT NULL UNIQUE,
    created_by_user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (expires_at > starts_at)
);
CREATE INDEX IF NOT EXISTS ix_welfare_plans_org ON welfare_plans(organization_id, status);

CREATE TABLE IF NOT EXISTS welfare_plan_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES welfare_plans(id) ON DELETE CASCADE,
    category_slug   TEXT,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    CHECK ((category_slug IS NULL) <> (product_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_welfare_targets_plan ON welfare_plan_targets(plan_id);

CREATE TABLE IF NOT EXISTS welfare_plan_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES welfare_plans(id) ON DELETE CASCADE,
    membership_id   INTEGER NOT NULL REFERENCES organization_memberships(id) ON DELETE CASCADE,
    cap_minor       INTEGER CHECK (cap_minor IS NULL OR cap_minor > 0),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (plan_id, membership_id)
);

-- spend (+) uses the cap; reversal (+) gives it back. remaining = cap - spend + reversal.
CREATE TABLE IF NOT EXISTS welfare_ledger_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES welfare_plans(id) ON DELETE RESTRICT,
    membership_id   INTEGER NOT NULL REFERENCES organization_memberships(id) ON DELETE RESTRICT,
    entry_type      TEXT    NOT NULL CHECK (entry_type IN ('spend', 'reversal')),
    amount_minor    INTEGER NOT NULL CHECK (amount_minor > 0),
    order_id        INTEGER REFERENCES orders(id) ON DELETE RESTRICT,
    idempotency_key TEXT    NOT NULL,
    note            TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (idempotency_key, plan_id)
);
CREATE INDEX IF NOT EXISTS ix_welfare_ledger_member ON welfare_ledger_entries(membership_id, plan_id);

CREATE TRIGGER IF NOT EXISTS welfare_ledger_no_update
BEFORE UPDATE ON welfare_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'welfare_ledger_entries is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS welfare_ledger_no_delete
BEFORE DELETE ON welfare_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'welfare_ledger_entries is append-only: DELETE is forbidden');
END;

-- ================================================================ installments
CREATE TABLE IF NOT EXISTS installment_plans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT    NOT NULL UNIQUE,
    title_fa            TEXT    NOT NULL,
    months              INTEGER NOT NULL CHECK (months IN (3, 6, 12, 18)),
    -- Fee per installment, in basis points of the financed amount (300 = 3%).
    fee_bps             INTEGER NOT NULL CHECK (fee_bps BETWEEN 0 AND 2000),
    down_payment_bps    INTEGER NOT NULL DEFAULT 0 CHECK (down_payment_bps BETWEEN 0 AND 9000),
    late_grace_days     INTEGER NOT NULL DEFAULT 3 CHECK (late_grace_days BETWEEN 0 AND 60),
    status              TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO installment_plans (code, title_fa, months, fee_bps, down_payment_bps) VALUES
    ('m3', 'سه‌ماهه', 3, 300, 2500),
    ('m6', 'شش‌ماهه', 6, 300, 2000),
    ('m12', 'دوازده‌ماهه', 12, 300, 1500),
    ('m18', 'هجده‌ماهه', 18, 300, 1000);

CREATE TABLE IF NOT EXISTS installment_agreements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT    NOT NULL UNIQUE,
    order_id            INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    plan_id             INTEGER NOT NULL REFERENCES installment_plans(id) ON DELETE RESTRICT,
    supplier_id         INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    months              INTEGER NOT NULL,
    fee_bps             INTEGER NOT NULL,
    down_payment_bps    INTEGER NOT NULL,
    principal_minor     INTEGER NOT NULL CHECK (principal_minor > 0),
    down_payment_minor  INTEGER NOT NULL CHECK (down_payment_minor >= 0),
    financed_minor      INTEGER NOT NULL CHECK (financed_minor >= 0),
    fee_total_minor     INTEGER NOT NULL CHECK (fee_total_minor >= 0),
    total_payable_minor INTEGER NOT NULL,
    -- Who holds the receivable: the seller (default), the platform after a debt sale,
    -- or a funder institution. The platform does not lend at origination.
    creditor_kind       TEXT    NOT NULL DEFAULT 'seller'
                                CHECK (creditor_kind IN ('seller', 'platform', 'institution')),
    status              TEXT    NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'completed', 'defaulted', 'cancelled')),
    idempotency_key     TEXT    NOT NULL UNIQUE,
    created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (principal_minor = down_payment_minor + financed_minor),
    CHECK (total_payable_minor = principal_minor + fee_total_minor)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_installment_agreements_order
    ON installment_agreements(order_id) WHERE status <> 'cancelled';
CREATE INDEX IF NOT EXISTS ix_installment_agreements_user ON installment_agreements(user_id, id);

CREATE TRIGGER IF NOT EXISTS installment_agreements_terms_immutable
BEFORE UPDATE OF order_id, user_id, plan_id, months, fee_bps, down_payment_bps, principal_minor, down_payment_minor, financed_minor, fee_total_minor, total_payable_minor ON installment_agreements
BEGIN
    SELECT RAISE(ABORT, 'installment agreement amounts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS installment_agreements_no_delete
BEFORE DELETE ON installment_agreements
BEGIN
    SELECT RAISE(ABORT, 'installment_agreements cannot be deleted');
END;

-- seq 0 = down payment (when > 0); 1..months = monthly installments.
CREATE TABLE IF NOT EXISTS installment_schedules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    agreement_id        INTEGER NOT NULL REFERENCES installment_agreements(id) ON DELETE RESTRICT,
    seq                 INTEGER NOT NULL CHECK (seq >= 0),
    due_at              TEXT    NOT NULL,
    principal_minor     INTEGER NOT NULL CHECK (principal_minor >= 0),
    fee_minor           INTEGER NOT NULL CHECK (fee_minor >= 0),
    amount_minor        INTEGER NOT NULL CHECK (amount_minor > 0),
    status              TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'late')),
    is_late             INTEGER NOT NULL DEFAULT 0 CHECK (is_late IN (0, 1)),
    paid_at             TEXT,
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (amount_minor = principal_minor + fee_minor),
    UNIQUE (agreement_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_installment_schedules_due ON installment_schedules(status, due_at);

CREATE TRIGGER IF NOT EXISTS installment_schedules_amounts_immutable
BEFORE UPDATE OF agreement_id, seq, due_at, principal_minor, fee_minor, amount_minor ON installment_schedules
BEGIN
    SELECT RAISE(ABORT, 'installment schedule amounts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS installment_schedules_no_delete
BEFORE DELETE ON installment_schedules
BEGIN
    SELECT RAISE(ABORT, 'installment_schedules cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS installment_payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT    NOT NULL UNIQUE,
    schedule_id         INTEGER NOT NULL REFERENCES installment_schedules(id) ON DELETE RESTRICT,
    agreement_id        INTEGER NOT NULL REFERENCES installment_agreements(id) ON DELETE RESTRICT,
    amount_minor        INTEGER NOT NULL CHECK (amount_minor > 0),
    paid_at             TEXT    NOT NULL,
    external_reference  TEXT,
    idempotency_key     TEXT    NOT NULL UNIQUE,
    actor_user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_installment_payments_schedule ON installment_payments(schedule_id);

CREATE TRIGGER IF NOT EXISTS installment_payments_no_update
BEFORE UPDATE ON installment_payments
BEGIN
    SELECT RAISE(ABORT, 'installment_payments is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS installment_payments_no_delete
BEFORE DELETE ON installment_payments
BEGIN
    SELECT RAISE(ABORT, 'installment_payments is append-only: DELETE is forbidden');
END;

-- Seller sells the remaining receivable of an agreement to the platform at a discount.
CREATE TABLE IF NOT EXISTS debt_sales (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    reference               TEXT    NOT NULL UNIQUE,
    agreement_id            INTEGER NOT NULL UNIQUE REFERENCES installment_agreements(id) ON DELETE RESTRICT,
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    remaining_minor         INTEGER NOT NULL CHECK (remaining_minor > 0),
    discount_bps            INTEGER NOT NULL CHECK (discount_bps BETWEEN 0 AND 5000),
    discount_minor          INTEGER NOT NULL CHECK (discount_minor >= 0),
    purchase_price_minor    INTEGER NOT NULL CHECK (purchase_price_minor > 0),
    ledger_reference        TEXT    NOT NULL,
    idempotency_key         TEXT    NOT NULL UNIQUE,
    actor_user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (remaining_minor = purchase_price_minor + discount_minor)
);

CREATE TRIGGER IF NOT EXISTS debt_sales_no_update
BEFORE UPDATE ON debt_sales
BEGIN
    SELECT RAISE(ABORT, 'debt_sales is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS debt_sales_no_delete
BEFORE DELETE ON debt_sales
BEGIN
    SELECT RAISE(ABORT, 'debt_sales is append-only: DELETE is forbidden');
END;

-- ================================================================ seller advances
-- grant (+) creates the obligation; recovery (+) nets it out at settlement.
-- outstanding(supplier) = SUM(grant) - SUM(recovery).
CREATE TABLE IF NOT EXISTS seller_advance_entries (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    reference               TEXT    NOT NULL UNIQUE,
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    entry_type              TEXT    NOT NULL CHECK (entry_type IN ('grant', 'recovery')),
    amount_minor            INTEGER NOT NULL CHECK (amount_minor > 0),
    -- grant only: the eligible delivered-unsettled net and the rate it was capped at.
    basis_net_minor         INTEGER,
    rate_bps                INTEGER CHECK (rate_bps IS NULL OR rate_bps BETWEEN 0 AND 9000),
    settlement_reference    TEXT,
    ledger_reference        TEXT    NOT NULL,
    idempotency_key         TEXT    NOT NULL UNIQUE,
    actor_user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_seller_advance_supplier ON seller_advance_entries(supplier_id, id);

CREATE TRIGGER IF NOT EXISTS seller_advance_entries_no_update
BEFORE UPDATE ON seller_advance_entries
BEGIN
    SELECT RAISE(ABORT, 'seller_advance_entries is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS seller_advance_entries_no_delete
BEFORE DELETE ON seller_advance_entries
BEGIN
    SELECT RAISE(ABORT, 'seller_advance_entries is append-only: DELETE is forbidden');
END;

-- ================================================================ group platform
-- One group-wide identity per user across 60Online, KarenSeir, Giftasan, Shadshahr, Padvira.
CREATE TABLE IF NOT EXISTS group_accounts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                 INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
    group_uid               TEXT    NOT NULL UNIQUE,
    linked_businesses_json  TEXT    NOT NULL DEFAULT '["60online"]',
    provider                TEXT    NOT NULL DEFAULT 'local',
    status                  TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ================================================================ ledger accounts
INSERT OR IGNORE INTO ledger_accounts (code, name_fa, type) VALUES
    ('1030', 'مطالبات اقساطی خریداری‌شده از فروشندگان', 'asset'),
    ('1040', 'پیش‌پرداخت به فروشندگان', 'asset'),
    ('2030', 'بدهی بابت خرید دین به فروشندگان', 'liability'),
    ('2035', 'درآمد تنزیل خرید دین (تحقق‌نیافته)', 'liability'),
    ('2040', 'پیش‌پرداخت فروشندگان در انتظار پرداخت', 'liability'),
    ('2050', 'حساب‌های پرداختنی فروشندگان (تهاتر تسویه)', 'liability');
