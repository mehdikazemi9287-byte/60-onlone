-- Access administration, payment-policy lifecycle and data provenance.
-- No business values are created here: policies stay absent until a reviewer approves one.

-- Provenance: every supplier / organization is explicitly real, demo or test.
ALTER TABLE suppliers ADD COLUMN provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test'));
ALTER TABLE organizations ADD COLUMN provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test'));
-- Deterministic reclassification of rows created by backend/scripts/seed.py (fixed seed national ids).
UPDATE suppliers SET provenance = 'demo'
 WHERE national_id IN ('20101000001','20101000002','20101000003','20101000004','20101000005',
                       '20101000006','20101000007','20101000008','20101000009','20101000010','20101000099');
UPDATE suppliers SET notes = 'DEMO/SEED — sample data, not a real supplier'
 WHERE provenance = 'demo' AND (notes IS NULL OR notes NOT LIKE 'DEMO%');
UPDATE organizations SET provenance = 'demo' WHERE national_id = '10101234567' AND legal_name LIKE '%نمونه%';

-- Supplier operational users (replaces the single suppliers.user_id link; that column stays as legacy primary).
CREATE TABLE supplier_users (
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'operator')),
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (supplier_id, user_id)
);
CREATE INDEX idx_supplier_users_user ON supplier_users(user_id, status);
INSERT INTO supplier_users (supplier_id, user_id, role, status)
    SELECT id, user_id, 'owner', 'active' FROM suppliers WHERE user_id IS NOT NULL;

-- Append-only audit of every access change made through the admin console.
CREATE TABLE role_assignment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK (scope IN ('organization_member', 'operations_grant', 'supplier_user')),
    organization_id INTEGER REFERENCES organizations(id),
    supplier_id INTEGER REFERENCES suppliers(id),
    subject_user_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL CHECK (action IN ('grant', 'revoke', 'change')),
    before_json TEXT,
    after_json TEXT,
    reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 3 AND 1000),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TRIGGER role_assignment_events_no_update BEFORE UPDATE ON role_assignment_events
BEGIN SELECT RAISE(ABORT, 'access audit is append only'); END;
CREATE TRIGGER role_assignment_events_no_delete BEFORE DELETE ON role_assignment_events
BEGIN SELECT RAISE(ABORT, 'access audit is append only'); END;

-- Payment policy lifecycle: draft → in_review → approved (→ scheduled/active/superseded, derived) | rejected | withdrawn.
-- Approval writes the immutable customer_payment_policies row that finance enforces.
CREATE TABLE payment_policy_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    version TEXT NOT NULL CHECK (length(trim(version)) BETWEEN 1 AND 40),
    environment TEXT NOT NULL CHECK (environment IN ('test', 'production')),
    contract_reference TEXT,
    rules_json TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_review', 'approved', 'rejected', 'withdrawn')),
    proposed_by INTEGER NOT NULL REFERENCES users(id),
    submitted_at TEXT,
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    review_note TEXT,
    policy_id INTEGER UNIQUE REFERENCES customer_payment_policies(id),
    row_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (reviewed_by IS NULL OR reviewed_by <> proposed_by),
    UNIQUE (organization_id, version)
);
CREATE TABLE payment_policy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER NOT NULL REFERENCES payment_policy_drafts(id),
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    action TEXT NOT NULL CHECK (action IN ('created', 'edited', 'submitted', 'approved', 'rejected', 'withdrawn')),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    note TEXT,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TRIGGER payment_policy_events_no_update BEFORE UPDATE ON payment_policy_events
BEGIN SELECT RAISE(ABORT, 'policy audit is append only'); END;
CREATE TRIGGER payment_policy_events_no_delete BEFORE DELETE ON payment_policy_events
BEGIN SELECT RAISE(ABORT, 'policy audit is append only'); END;

-- Plans above a policy's dual-approval threshold need two distinct finance approvers.
CREATE TABLE procurement_plan_approvals (
    plan_id INTEGER NOT NULL REFERENCES procurement_payment_plans(id),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    round INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (plan_id, actor_user_id, round)
);
CREATE TRIGGER procurement_plan_approvals_no_update BEFORE UPDATE ON procurement_plan_approvals
BEGIN SELECT RAISE(ABORT, 'approvals are append only'); END;
CREATE TRIGGER procurement_plan_approvals_no_delete BEFORE DELETE ON procurement_plan_approvals
BEGIN SELECT RAISE(ABORT, 'approvals are append only'); END;
