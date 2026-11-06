-- 0058_partner_api
--
-- Phase 5A: partner web services (وب‌سرویس دادن و گرفتن).
--   * partner_api_clients / partner_api_keys  — API-key auth for partners.
--     Only the SHA-256 hash of a key secret is stored; plaintext is shown once.
--   * HMAC signing secrets (inbound + webhook) are NEVER stored: they are
--     derived on the server as HMAC(server_secret, salt). Only the random salt
--     and a short fingerprint live in the database.
--   * webhook_subscriptions / partner_webhook_events / webhook_deliveries /
--     webhook_delivery_attempts — signed outbound webhooks with retry + log.
--   * partner_inbound_messages — raw inbound payload log with idempotency.

CREATE TABLE IF NOT EXISTS partner_api_clients (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT    NOT NULL,
    owner_type             TEXT    NOT NULL DEFAULT 'supplier'
                                   CHECK (owner_type IN ('platform', 'user', 'organization', 'supplier')),
    owner_user_id          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    organization_id        INTEGER REFERENCES organizations(id) ON DELETE RESTRICT,
    supplier_id            INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    scopes_json            TEXT    NOT NULL DEFAULT '[]',
    status                 TEXT    NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('active', 'suspended', 'revoked')),
    rate_limit_per_minute  INTEGER NOT NULL DEFAULT 60
                                   CHECK (rate_limit_per_minute BETWEEN 1 AND 6000),
    signing_salt           TEXT,
    signing_fingerprint    TEXT,
    created_by_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at             TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT    NOT NULL DEFAULT (datetime('now')),
    revoked_at             TEXT,
    last_used_at           TEXT,
    CHECK (owner_type <> 'organization' OR organization_id IS NOT NULL),
    CHECK (owner_type <> 'supplier' OR supplier_id IS NOT NULL),
    CHECK (owner_type <> 'user' OR owner_user_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_partner_clients_org ON partner_api_clients(organization_id);
CREATE INDEX IF NOT EXISTS ix_partner_clients_supplier ON partner_api_clients(supplier_id);

CREATE TABLE IF NOT EXISTS partner_api_keys (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER NOT NULL REFERENCES partner_api_clients(id) ON DELETE CASCADE,
    prefix              TEXT    NOT NULL UNIQUE,
    secret_hash         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    rotated_from_id     INTEGER REFERENCES partner_api_keys(id) ON DELETE SET NULL,
    created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    revoked_at          TEXT,
    last_used_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_partner_keys_client ON partner_api_keys(client_id, status);

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id            INTEGER NOT NULL REFERENCES partner_api_clients(id) ON DELETE CASCADE,
    url                  TEXT    NOT NULL,
    event_types_json     TEXT    NOT NULL DEFAULT '[]',
    secret_salt          TEXT    NOT NULL,
    secret_fingerprint   TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'disabled')),
    allow_custom_port    INTEGER NOT NULL DEFAULT 0 CHECK (allow_custom_port IN (0, 1)),
    created_by_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_webhook_subs_client ON webhook_subscriptions(client_id, status);

CREATE TABLE IF NOT EXISTS partner_webhook_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type       TEXT    NOT NULL,
    event_key        TEXT    NOT NULL UNIQUE,
    audience_json    TEXT    NOT NULL DEFAULT '{}',
    payload_json     TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id   INTEGER NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    event_id          INTEGER NOT NULL REFERENCES partner_webhook_events(id) ON DELETE CASCADE,
    status            TEXT    NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'delivered', 'dead_letter')),
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    next_attempt_at   TEXT,
    last_status_code  INTEGER,
    last_error        TEXT,
    delivered_at      TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (subscription_id, event_id)
);
CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_due ON webhook_deliveries(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS webhook_delivery_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id   INTEGER NOT NULL REFERENCES webhook_deliveries(id) ON DELETE CASCADE,
    attempt_no    INTEGER NOT NULL,
    status_code   INTEGER,
    error         TEXT,
    duration_ms   INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_webhook_attempts_delivery ON webhook_delivery_attempts(delivery_id, id);

CREATE TABLE IF NOT EXISTS partner_inbound_messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id         INTEGER NOT NULL REFERENCES partner_api_clients(id) ON DELETE CASCADE,
    source            TEXT    NOT NULL,
    idempotency_key   TEXT    NOT NULL,
    payload_hash      TEXT    NOT NULL,
    payload_raw       TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'received'
                              CHECK (status IN ('received', 'processed', 'failed')),
    result_json       TEXT,
    error             TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    processed_at      TEXT,
    UNIQUE (client_id, source, idempotency_key)
);

CREATE TABLE IF NOT EXISTS partner_bridge_cursors (
    name      TEXT    PRIMARY KEY,
    last_id   INTEGER NOT NULL DEFAULT 0
);
