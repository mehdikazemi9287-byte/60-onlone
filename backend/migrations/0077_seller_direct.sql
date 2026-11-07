-- "Bring your own customer" (the Faire Direct lesson): a seller invites a buyer it already serves offline; once the
-- buyer claims the invite, the seller pays 0% commission on that buyer's orders from it. Only buyers who never
-- bought from that seller on the platform can be claimed — the platform's own customers stay commissionable.
CREATE TABLE IF NOT EXISTS seller_direct_invites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    code            TEXT    NOT NULL UNIQUE,
    note            TEXT,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL,
    expires_at      TEXT    NOT NULL,
    claimed_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    claimed_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_seller_direct_invites_supplier ON seller_direct_invites(supplier_id, created_at);

CREATE TABLE IF NOT EXISTS seller_direct_customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invite_id       INTEGER REFERENCES seller_direct_invites(id) ON DELETE SET NULL,
    linked_at       TEXT    NOT NULL,
    UNIQUE (supplier_id, user_id)
);
