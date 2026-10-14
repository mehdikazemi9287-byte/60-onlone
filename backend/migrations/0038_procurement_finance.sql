-- Procurement finance on the purchase-order chain. Additive only.
-- Every row carries the environment of the approved organization payment policy
-- it was created under ('test' or 'production'); without a policy nothing can be created.

CREATE TABLE procurement_payment_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL UNIQUE REFERENCES purchase_orders(id),
    policy_id INTEGER NOT NULL REFERENCES customer_payment_policies(id),
    environment TEXT NOT NULL CHECK (environment IN ('test', 'production')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
    total_minor INTEGER NOT NULL CHECK (total_minor >= 0),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id),
    decided_by_user_id INTEGER REFERENCES users(id),
    decision_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    submitted_at TEXT,
    decided_at TEXT
);

CREATE TABLE procurement_payment_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES procurement_payment_plans(id),
    method TEXT NOT NULL CHECK (method IN ('cash', 'cheque', 'credit', 'bill')),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    due_date TEXT,
    reference TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'received', 'cleared', 'bounced', 'cancelled')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_payment_parts_plan ON procurement_payment_parts(plan_id);

CREATE TABLE procurement_supplier_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL UNIQUE REFERENCES purchase_orders(id),
    environment TEXT NOT NULL CHECK (environment IN ('test', 'production')),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    reference TEXT NOT NULL CHECK (length(trim(reference)) BETWEEN 1 AND 200),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Append-only finance ledger (audit trail of every money-related state change).
CREATE TABLE procurement_finance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    plan_id INTEGER REFERENCES procurement_payment_plans(id),
    part_id INTEGER REFERENCES procurement_payment_parts(id),
    environment TEXT NOT NULL CHECK (environment IN ('test', 'production')),
    kind TEXT NOT NULL CHECK (kind IN ('plan_created', 'plan_submitted', 'plan_approved', 'plan_rejected',
        'part_received', 'part_cleared', 'part_bounced', 'refund_recorded', 'settlement_recorded')),
    amount_minor INTEGER NOT NULL DEFAULT 0,
    actor_user_id INTEGER REFERENCES users(id),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_finance_events_po ON procurement_finance_events(purchase_order_id, id);
CREATE TRIGGER procurement_finance_events_no_update BEFORE UPDATE ON procurement_finance_events
BEGIN SELECT RAISE(ABORT, 'procurement_finance_events is append-only'); END;
CREATE TRIGGER procurement_finance_events_no_delete BEFORE DELETE ON procurement_finance_events
BEGIN SELECT RAISE(ABORT, 'procurement_finance_events is append-only'); END;
