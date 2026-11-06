-- Affiliate payouts: verified Sheba, admin payout batches (bank CSV), paid/failed per payout.
ALTER TABLE affiliates ADD COLUMN sheba_holder TEXT;
ALTER TABLE affiliates ADD COLUMN sheba_verified_at TEXT;
ALTER TABLE affiliates ADD COLUMN sheba_updated_at TEXT;

CREATE TABLE IF NOT EXISTS affiliate_payout_batches (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    reference          TEXT NOT NULL UNIQUE,
    status             TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'exported', 'closed')),
    total_minor        INTEGER NOT NULL DEFAULT 0 CHECK (total_minor >= 0),
    payout_count       INTEGER NOT NULL DEFAULT 0,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at         TEXT NOT NULL,
    exported_at        TEXT
);

CREATE TABLE IF NOT EXISTS affiliate_payouts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id       INTEGER NOT NULL REFERENCES affiliate_payout_batches(id),
    affiliate_id   INTEGER NOT NULL REFERENCES affiliates(id),
    reference      TEXT NOT NULL UNIQUE,
    amount_minor   INTEGER NOT NULL CHECK (amount_minor > 0),
    sheba          TEXT NOT NULL,
    holder         TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'failed')),
    bank_reference TEXT,
    failure_reason TEXT,
    created_at     TEXT NOT NULL,
    settled_at     TEXT
);
-- At most one unsettled payout per affiliate.
CREATE UNIQUE INDEX IF NOT EXISTS ux_affiliate_payouts_open ON affiliate_payouts(affiliate_id) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS ix_affiliate_payouts_batch ON affiliate_payouts(batch_id);

ALTER TABLE affiliate_earnings ADD COLUMN payout_id INTEGER REFERENCES affiliate_payouts(id);
CREATE INDEX IF NOT EXISTS ix_affiliate_earnings_payout ON affiliate_earnings(payout_id);
