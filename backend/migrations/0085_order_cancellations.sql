-- 0085: customer cancellation of a retail order before shipment, and the refunds it owes.
-- ADDITIVE ONLY: two new tables, one append-only trigger pair and one new ledger account. Nothing is dropped.
--
-- order_cancellations: exactly one row per cancelled order (UNIQUE order_id makes a double cancel a no-op).
-- Every amount is the exact integer IRR value that was given back, read from the source ledgers.
CREATE TABLE IF NOT EXISTS order_cancellations (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id                  INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    user_id                   INTEGER NOT NULL REFERENCES users(id),
    reason                    TEXT,
    total_minor               INTEGER NOT NULL CHECK (total_minor >= 0),
    card_refund_minor         INTEGER NOT NULL DEFAULT 0 CHECK (card_refund_minor >= 0),
    credit_restored_minor     INTEGER NOT NULL DEFAULT 0 CHECK (credit_restored_minor >= 0),
    welfare_restored_minor    INTEGER NOT NULL DEFAULT 0 CHECK (welfare_restored_minor >= 0),
    coins_restored            INTEGER NOT NULL DEFAULT 0 CHECK (coins_restored >= 0),
    coins_clawed_back         INTEGER NOT NULL DEFAULT 0 CHECK (coins_clawed_back >= 0),
    coins_clawback_shortfall  INTEGER NOT NULL DEFAULT 0 CHECK (coins_clawback_shortfall >= 0),
    fulfillment_orders_json   TEXT    NOT NULL DEFAULT '[]',
    ledger_reference          TEXT,
    created_at                TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_order_cancellations_user ON order_cancellations(user_id);

CREATE TRIGGER IF NOT EXISTS order_cancellations_no_update
BEFORE UPDATE ON order_cancellations
BEGIN
    SELECT RAISE(ABORT, 'order_cancellations is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS order_cancellations_no_delete
BEFORE DELETE ON order_cancellations
BEGIN
    SELECT RAISE(ABORT, 'order_cancellations is append-only: DELETE is forbidden');
END;

-- order_refunds: money 60Online owes back to the customer's card/gateway. No gateway is called automatically:
-- the row waits as 'pending_finance' until finance pays it and records the bank/gateway reference.
CREATE TABLE IF NOT EXISTS order_refunds (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id          INTEGER NOT NULL REFERENCES orders(id),
    cancellation_id   INTEGER REFERENCES order_cancellations(id),
    kind              TEXT    NOT NULL CHECK (kind IN ('customer_cancellation')),
    amount_minor      INTEGER NOT NULL CHECK (amount_minor > 0),
    currency          TEXT    NOT NULL DEFAULT 'IRR',
    payment_provider  TEXT,
    payment_ref       TEXT,
    status            TEXT    NOT NULL DEFAULT 'pending_finance' CHECK (status IN ('pending_finance','paid')),
    bank_reference    TEXT,
    paid_by_user_id   INTEGER REFERENCES users(id),
    paid_at           TEXT,
    idempotency_key   TEXT    NOT NULL UNIQUE,
    version           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_order_refunds_status ON order_refunds(status, id);
CREATE INDEX IF NOT EXISTS ix_order_refunds_order ON order_refunds(order_id);

-- Liability: card/gateway money owed back to customers for cancelled orders, until finance pays it.
INSERT OR IGNORE INTO ledger_accounts (code, name_fa, type) VALUES
    ('2060', 'بازپرداختنی به مشتریان (لغو سفارش)', 'liability');
