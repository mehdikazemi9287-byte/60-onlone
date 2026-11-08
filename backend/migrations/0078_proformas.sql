-- Price-held pro-forma (the Digikala Business lesson): an organization's buyer freezes the current cart into a
-- numbered pro-forma for internal approval. It is valid for a few days; at checkout with it, if prices rose since,
-- the order is refused instead of silently charging more than the approved document.
CREATE TABLE IF NOT EXISTS proformas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    number          TEXT    NOT NULL UNIQUE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    snapshot_json   TEXT    NOT NULL,
    total_minor     INTEGER NOT NULL CHECK (total_minor >= 0),
    created_at      TEXT    NOT NULL,
    valid_until     TEXT    NOT NULL,
    used_order_id   INTEGER REFERENCES orders(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_proformas_user ON proformas(user_id, created_at);
