-- 0084 external refund review queue (review 2026-11-12: SO-4). Additive only. See the SQLite file for the rationale.
CREATE TABLE IF NOT EXISTS external_refund_reviews (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    provider_intent_ref TEXT NOT NULL,
    payment_intent_id BIGINT,
    provider_status TEXT,
    amount_minor BIGINT,
    owner_role TEXT NOT NULL DEFAULT 'finance',
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    resolution_note TEXT,
    resolved_by BIGINT,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
    UNIQUE (provider, event_id)
);
CREATE INDEX IF NOT EXISTS idx_external_refund_reviews_open ON external_refund_reviews(status, due_at);
