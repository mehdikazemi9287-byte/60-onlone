-- Migration 0022: JWT revocation table
-- Stores revoked token JTIs so that logout and role-change invalidation work
-- even before the token's natural expiry.

CREATE TABLE IF NOT EXISTS revoked_tokens (
    id         BIGSERIAL PRIMARY KEY,
    jti        TEXT    NOT NULL,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    revoked_at TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    expires_at TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_revoked_tokens_jti       ON revoked_tokens(jti);
CREATE        INDEX IF NOT EXISTS ix_revoked_tokens_user_id   ON revoked_tokens(user_id);
CREATE        INDEX IF NOT EXISTS ix_revoked_tokens_expires_at ON revoked_tokens(expires_at);
