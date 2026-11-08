CREATE TABLE admin_store_settings (
 id INTEGER PRIMARY KEY CHECK(id=1),
 value_json TEXT NOT NULL,
 row_version INTEGER NOT NULL DEFAULT 1,
 updated_by INTEGER NOT NULL REFERENCES users(id),
 updated_at TEXT NOT NULL
);
CREATE TABLE admin_setting_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 actor_user_id INTEGER NOT NULL REFERENCES users(id),
 before_json TEXT NOT NULL,
 after_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE organization_contracts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 organization_id INTEGER NOT NULL REFERENCES organizations(id),
 title TEXT NOT NULL,
 contract_reference TEXT NOT NULL,
 start_date TEXT,
 end_date TEXT,
 notes TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','recorded','expired','archived')),
 row_version INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX organization_contracts_org ON organization_contracts(organization_id,status);
CREATE TABLE organization_contract_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 contract_id INTEGER NOT NULL REFERENCES organization_contracts(id),
 actor_user_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE TRIGGER admin_setting_events_no_update BEFORE UPDATE ON admin_setting_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
CREATE TRIGGER admin_setting_events_no_delete BEFORE DELETE ON admin_setting_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;

CREATE TRIGGER organization_contract_events_no_update BEFORE UPDATE ON organization_contract_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
CREATE TRIGGER organization_contract_events_no_delete BEFORE DELETE ON organization_contract_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
