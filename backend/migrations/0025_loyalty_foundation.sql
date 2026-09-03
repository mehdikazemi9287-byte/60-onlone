-- Migration 0025: Loyalty foundation (60Coin)
--
-- BACKGROUND:
--   60Online wants a loyalty/reward layer ("60Coin") that customers earn from
--   purchases and platform activity/campaigns, and can later redeem as a
--   discount. This must be structurally SEPARATE from real-money accounting:
--   it does not touch credit_ledger_entries, ledger_entries, orders.total_minor,
--   or any table the double-entry financial ledger depends on. Coins are not
--   currency and must never be summed into a trial balance.
--
-- DESIGN (mirrors credit_ledger_entries' proven shape):
--   1. No mutable balance column. A user's balance is folded from
--      loyalty_ledger_entries on every read (SUM(amount_coins)), so it cannot
--      drift away from its history — same rule as credit.
--   2. Append-only at the storage layer via trigger. Corrections are posted
--      as a new 'adjustment' entry, never by editing history.
--   3. entry_type encodes direction: 'earn' is always positive, 'redeem' and
--      'expire' are always negative, 'adjustment' may be either (but never 0).
--   4. idempotency_key (nullable, unique when present) lets the same purchase
--      or campaign trigger be replayed safely without double-crediting.
--
-- IDEMPOTENCY: applied exactly once by the schema_migrations table.

CREATE TABLE loyalty_ledger_entries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    reference         TEXT    NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    entry_type        TEXT    NOT NULL
                              CHECK (entry_type IN ('earn','redeem','expire','adjustment')),
    amount_coins      INTEGER NOT NULL,
    source            TEXT    NOT NULL
                              CHECK (source IN ('purchase','campaign','activity','referral',
                                                 'redemption','expiry','manual_adjustment')),
    order_id          INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    idempotency_key   TEXT,
    actor_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note              TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (amount_coins <> 0),
    CHECK (
        (entry_type = 'earn' AND amount_coins > 0)
        OR (entry_type IN ('redeem','expire') AND amount_coins < 0)
        OR entry_type = 'adjustment'
    )
);

CREATE INDEX idx_loyalty_ledger_user ON loyalty_ledger_entries(user_id, id DESC);
CREATE INDEX idx_loyalty_ledger_order ON loyalty_ledger_entries(order_id);
CREATE UNIQUE INDEX idx_loyalty_ledger_idempotency
    ON loyalty_ledger_entries(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TRIGGER loyalty_ledger_no_update
BEFORE UPDATE ON loyalty_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'loyalty_ledger_entries is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER loyalty_ledger_no_delete
BEFORE DELETE ON loyalty_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'loyalty_ledger_entries is append-only: DELETE is forbidden');
END;
