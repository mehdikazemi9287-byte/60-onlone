-- Internal mandates are deliberately empty. Provisioning requires a separately
-- approved staff mandate; customer memberships and platform admin imply none.
CREATE TABLE organization_operations_grants (
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    capability TEXT NOT NULL CHECK (capability IN ('case_manager','case_agent')),
    status TEXT NOT NULL CHECK (status IN ('active','revoked')),
    mandate_reference TEXT NOT NULL CHECK (length(trim(mandate_reference)) BETWEEN 1 AND 500),
    PRIMARY KEY (organization_id, user_id, capability)
);
CREATE TABLE organization_operations_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    purchase_request_id INTEGER NOT NULL UNIQUE REFERENCES purchase_requests(id),
    assignee_user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'unassigned'
      CHECK (status IN ('unassigned','triage','sourcing','waiting_customer','blocked','closed')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_operations_org ON organization_operations_cases(organization_id,id);
CREATE TABLE organization_operations_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES organization_operations_cases(id),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL CHECK (action IN ('create','assign','transition')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 1000),
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
-- No event edit/delete route exists. Database enforcement also prevents edits.
CREATE TRIGGER operations_events_no_update BEFORE UPDATE ON organization_operations_events
BEGIN SELECT RAISE(ABORT, 'operations audit is append only'); END;
CREATE TRIGGER operations_events_no_delete BEFORE DELETE ON organization_operations_events
BEGIN SELECT RAISE(ABORT, 'operations audit is append only'); END;
CREATE TABLE organization_operations_idempotency (
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    case_id INTEGER NOT NULL REFERENCES organization_operations_cases(id),
    response_json TEXT NOT NULL,
    PRIMARY KEY (organization_id,actor_user_id,key)
);
