-- OTP (SMS one-time code) login. users.phone stays free text; phone_verified holds the normalized number
-- once its owner proved it with a code, and is the only number OTP login trusts.
ALTER TABLE users ADD COLUMN phone_verified TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone_verified ON users(phone_verified) WHERE phone_verified IS NOT NULL;
CREATE TABLE IF NOT EXISTS otp_challenges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT NOT NULL,
    purpose     TEXT NOT NULL CHECK (purpose IN ('login', 'link')),
    user_id     INTEGER REFERENCES users(id),
    code_hash   TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    ip_address  TEXT,
    expires_at  TEXT NOT NULL,
    consumed_at TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_otp_phone ON otp_challenges(phone, created_at);
CREATE INDEX IF NOT EXISTS ix_otp_ip ON otp_challenges(ip_address, created_at);
