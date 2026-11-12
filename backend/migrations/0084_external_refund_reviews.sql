-- 0084 external refund review queue (review 2026-11-12: SO-4). Additive only.
-- A refund made in the VandaPay panel does not adjust the shop order/ledger automatically yet. Until that
-- compensation flow exists every refund.* webhook opens ONE review item (unique per provider event) owned by
-- finance with a deadline, so the mismatch is visible and tracked instead of only logged. Stock is never
-- released automatically because money came back.
CREATE TABLE IF NOT EXISTS external_refund_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    provider_intent_ref TEXT NOT NULL,
    payment_intent_id INTEGER,
    provider_status TEXT,
    amount_minor INTEGER,
    owner_role TEXT NOT NULL DEFAULT 'finance',
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    resolution_note TEXT,
    resolved_by INTEGER,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (provider, event_id)
);
CREATE INDEX IF NOT EXISTS idx_external_refund_reviews_open ON external_refund_reviews(status, due_at);
