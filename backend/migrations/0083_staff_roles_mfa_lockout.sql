-- 0083: scoped staff roles, admin second factor (TOTP), per-account login lockout, settlement two-person control.
-- ADDITIVE ONLY: new tables and new nullable columns. Nothing is dropped, renamed or rewritten.
--
-- Super-admin mapping: super-admin is the existing users.role = 'admin'. Every admin account that exists
-- when this migration runs therefore keeps full access unchanged; no row is needed or written for them.
-- staff_role_assignments only ever ADDS narrower access for non-admin accounts.

CREATE TABLE IF NOT EXISTS staff_role_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    role        TEXT    NOT NULL CHECK (role IN ('finance','support','catalog','marketing','content','logistics')),
    granted_by  INTEGER REFERENCES users(id),
    granted_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    reason      TEXT,
    revoked_by  INTEGER REFERENCES users(id),
    revoked_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_staff_role_active ON staff_role_assignments(user_id, role) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_staff_role_user ON staff_role_assignments(user_id);

-- TOTP second factor. secret_enc is encrypted at rest (Fernet, key derived from SECRET_KEY); never returned
-- after enrollment. last_used_step blocks code replay; failed_attempts/locked_until throttle guessing.
CREATE TABLE IF NOT EXISTS admin_mfa (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id),
    secret_enc       TEXT    NOT NULL,
    status           TEXT    NOT NULL CHECK (status IN ('pending','active')),
    last_used_step   INTEGER NOT NULL DEFAULT 0,
    failed_attempts  INTEGER NOT NULL DEFAULT 0,
    locked_until     INTEGER,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    activated_at     TEXT
);

-- One-time recovery codes: only a SHA-256 hash is stored; used_at is set once by an atomic UPDATE.
CREATE TABLE IF NOT EXISTS admin_mfa_recovery_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    code_hash   TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    used_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_admin_mfa_recovery_user ON admin_mfa_recovery_codes(user_id);

-- Per-account password-login lockout (epoch seconds).
CREATE TABLE IF NOT EXISTS login_lockouts (
    user_id         INTEGER PRIMARY KEY REFERENCES users(id),
    failed_count    INTEGER NOT NULL DEFAULT 0,
    lock_level      INTEGER NOT NULL DEFAULT 0,
    locked_until    INTEGER,
    last_failed_at  INTEGER
);

-- Two-person control: who created a settlement batch and who completed it. NULL on batches created before 0083.
ALTER TABLE settlement_batches ADD COLUMN created_by_user_id INTEGER REFERENCES users(id);
ALTER TABLE settlement_batches ADD COLUMN completed_by_user_id INTEGER REFERENCES users(id);
