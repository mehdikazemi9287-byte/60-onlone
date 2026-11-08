-- In-person (مراجعهٔ حضوری): store pickup with a one-time code, walk-in stores/showrooms on a
-- public store locator, and visit appointments (e.g. organization buyers seeing samples).

ALTER TABLE supplier_locations ADD COLUMN accepts_walk_in INTEGER NOT NULL DEFAULT 0 CHECK (accepts_walk_in IN (0, 1));
ALTER TABLE supplier_locations ADD COLUMN accepts_appointments INTEGER NOT NULL DEFAULT 0 CHECK (accepts_appointments IN (0, 1));
ALTER TABLE supplier_locations ADD COLUMN public_title TEXT;
ALTER TABLE supplier_locations ADD COLUMN public_phone TEXT;

-- Buyer switched a seller part of the order to "collect in store".
CREATE TABLE IF NOT EXISTS pickup_handoffs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    fulfillment_order_id INTEGER NOT NULL UNIQUE REFERENCES fulfillment_orders(id) ON DELETE CASCADE,
    location_id          INTEGER NOT NULL REFERENCES supplier_locations(id),
    code_sha256          TEXT NOT NULL CHECK (length(code_sha256) = 64),
    code_last2           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'collected', 'cancelled')),
    attempts             INTEGER NOT NULL DEFAULT 0,
    expires_at           TEXT NOT NULL,
    collected_at         TEXT,
    collected_by_user_id INTEGER REFERENCES users(id),
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS visit_appointments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    location_id   INTEGER NOT NULL REFERENCES supplier_locations(id),
    starts_at     TEXT NOT NULL,
    duration_min  INTEGER NOT NULL DEFAULT 30 CHECK (duration_min BETWEEN 15 AND 180),
    purpose       TEXT NOT NULL CHECK (purpose IN ('showroom', 'consultation', 'samples', 'pickup', 'other')),
    note          TEXT,
    organization_id INTEGER REFERENCES organizations(id),
    status        TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'confirmed', 'declined', 'cancelled', 'done')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_visit_appointments_location ON visit_appointments(location_id, starts_at);
CREATE INDEX IF NOT EXISTS ix_visit_appointments_user ON visit_appointments(user_id, id);
