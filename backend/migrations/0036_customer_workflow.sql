-- Additive customer workflow; no existing supplier PO or financial rows changed.
CREATE TABLE customer_workflows (
 case_id INTEGER PRIMARY KEY REFERENCES organization_operations_cases(id),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
 next_action TEXT NOT NULL DEFAULT '', due_at TEXT, blocked_reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_payment_policies (
 id INTEGER PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id),
 version TEXT NOT NULL, contract_reference TEXT NOT NULL,
 rules_json TEXT NOT NULL, approved_by INTEGER NOT NULL REFERENCES users(id),
 proposed_by INTEGER NOT NULL REFERENCES users(id),
 environment TEXT NOT NULL CHECK(environment IN ('test','production')),
 CHECK(approved_by<>proposed_by), UNIQUE(organization_id,version)
);
CREATE TABLE customer_quotes (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES customer_workflows(case_id),
 revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, expires_at TEXT NOT NULL,
 policy_id INTEGER REFERENCES customer_payment_policies(id),
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(case_id,revision)
);
CREATE TABLE customer_quote_decisions (
 quote_id INTEGER PRIMARY KEY REFERENCES customer_quotes(id), actor_user_id INTEGER NOT NULL REFERENCES users(id),
 decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')), reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_orders (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL UNIQUE REFERENCES customer_workflows(case_id),
 quote_id INTEGER NOT NULL UNIQUE REFERENCES customer_quote_decisions(quote_id),
 status TEXT NOT NULL CHECK(status IN ('awaiting_payment','preparing','dispatched','received','closed','cancelled')),
 payment_method TEXT, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_workflow_events (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES customer_workflows(case_id),
 actor_user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('internal','customer')),
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_quantity_events (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES customer_orders(id),
 destination_index INTEGER NOT NULL CHECK(destination_index>=0), item_index INTEGER NOT NULL CHECK(item_index>=0),
 kind TEXT NOT NULL CHECK(kind IN ('dispatch','receipt','return','return_resolved')),
 quantity INTEGER NOT NULL CHECK(quantity>0), actor_user_id INTEGER NOT NULL REFERENCES users(id),
 reference TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_payment_proposals (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES customer_orders(id),
 kind TEXT NOT NULL CHECK(kind IN ('collection','refund')), amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 reference TEXT NOT NULL, proposer INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_payment_events (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES customer_orders(id),
 proposal_id INTEGER UNIQUE REFERENCES customer_payment_proposals(id),
 kind TEXT NOT NULL CHECK(kind IN ('method_selected','received_instrument','reserved','consumed','released','collected','refunded','settled')),
 amount_minor INTEGER NOT NULL CHECK(amount_minor>=0), actor_user_id INTEGER NOT NULL REFERENCES users(id),
 reference TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE customer_workflow_idempotency (
 case_id INTEGER NOT NULL REFERENCES customer_workflows(case_id), actor_user_id INTEGER NOT NULL REFERENCES users(id),
 key TEXT NOT NULL, payload_hash TEXT NOT NULL, response_json TEXT NOT NULL,
 PRIMARY KEY(case_id,actor_user_id,key)
);
CREATE INDEX customer_event_case ON customer_workflow_events(case_id,id);
CREATE TRIGGER customer_payment_policies_no_update BEFORE UPDATE ON customer_payment_policies BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_payment_policies_no_delete BEFORE DELETE ON customer_payment_policies BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_quotes_no_update BEFORE UPDATE ON customer_quotes BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_quotes_no_delete BEFORE DELETE ON customer_quotes BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_quote_decisions_no_update BEFORE UPDATE ON customer_quote_decisions BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_quote_decisions_no_delete BEFORE DELETE ON customer_quote_decisions BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_workflow_events_no_update BEFORE UPDATE ON customer_workflow_events BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_workflow_events_no_delete BEFORE DELETE ON customer_workflow_events BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_quantity_events_no_update BEFORE UPDATE ON customer_quantity_events BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_quantity_events_no_delete BEFORE DELETE ON customer_quantity_events BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_payment_proposals_no_update BEFORE UPDATE ON customer_payment_proposals BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_payment_proposals_no_delete BEFORE DELETE ON customer_payment_proposals BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_payment_events_no_update BEFORE UPDATE ON customer_payment_events BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
CREATE TRIGGER customer_payment_events_no_delete BEFORE DELETE ON customer_payment_events BEGIN SELECT RAISE(ABORT,'immutable workflow record'); END;
