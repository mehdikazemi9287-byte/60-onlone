-- 0008_shipment_states
--
-- Extend shipments.status CHECK to include 'out_for_delivery' and 'returned'.
--
-- SQLite does not support ALTER TABLE to modify CHECK constraints.
-- Standard SQLite table-rebuild pattern:
--   1. Create new table with corrected constraint.
--   2. Copy all existing rows (all existing values pass the new CHECK).
--   3. Drop old table (drops its associated indices too).
--   4. Rename new table to the canonical name.
--   5. Recreate all indices.
--
-- PURELY ADDITIVE: no existing status value is removed; no column is
-- dropped or renamed; all Phase 1–7 rows remain valid after this migration.
-- Foreign-key references from shipment_booking_log and webhook_events are
-- resolved by table name at DML time, so they automatically follow the rename.
--
-- POPULATED-DATABASE SAFETY — why this migration closes and re-opens the
-- migrator's transaction:
--
-- db.py sets PRAGMA foreign_keys = ON on every production connection.
-- That pragma CANNOT be changed inside an open transaction (the set is a
-- silent no-op while in_transaction=True).  The migrator (migrator.py) wraps
-- every migration SQL in "BEGIN; {sql} INSERT...; COMMIT;", so our SQL runs
-- INSIDE a transaction.  Under foreign_keys = ON, "DROP TABLE shipments"
-- raises "FOREIGN KEY constraint failed" because shipment_booking_log and
-- webhook_events have NOT NULL FK columns that reference shipments.id, and
-- rows exist in those tables on a populated production database.
--
-- PRAGMA defer_foreign_keys = ON does NOT help here: SQLite defers DML-level
-- FK checks but does NOT defer the table-existence check triggered by DROP
-- TABLE — empirically verified.
--
-- The correct fix is to temporarily disable FK enforcement for the DDL
-- rebuild.  PRAGMA foreign_keys = OFF only takes effect OUTSIDE a
-- transaction.  To accomplish this within the migrator's script:
--
--   1. Issue COMMIT to close the migrator's outer BEGIN (empty txn — valid).
--   2. Set PRAGMA foreign_keys = OFF (now outside any txn — effective).
--   3. Run the table rebuild in autocommit mode (each DDL is atomic).
--   4. Set PRAGMA foreign_keys = ON (still outside any txn — effective).
--   5. Issue BEGIN to open a new transaction for the migrator's bookkeeping
--      INSERT INTO schema_migrations, which the migrator appends after our SQL.
--
-- The migrator then appends:
--   INSERT INTO schema_migrations (...) VALUES (...);
--   COMMIT;
--
-- This keeps the schema_migrations row inside a transaction even though the
-- DDL itself ran in autocommit mode.  If the INSERT fails the transaction is
-- rolled back and the migration appears unapplied; the operator can retry and
-- the CREATE TABLE IF NOT EXISTS guard prevents a duplicate-table error.

-- Step 1: close the migrator's outer BEGIN (safe — empty transaction).
COMMIT;

-- Step 2: disable FK enforcement while outside any transaction.
PRAGMA foreign_keys = OFF;

-- Step 3: table rebuild (autocommit; each statement is independently atomic).
CREATE TABLE IF NOT EXISTS shipments_new (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fulfillment_order_id    INTEGER NOT NULL REFERENCES fulfillment_orders(id),
    shipment_plan_id        INTEGER REFERENCES shipment_plans(id),
    carrier_config_id       INTEGER NOT NULL REFERENCES carrier_configs(id),
    provider_code           TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'planned'
                                    CHECK (status IN (
                                        'planned','booking','booked',
                                        'in_transit','out_for_delivery','delivered',
                                        'failed','booking_failed','returned'
                                    )),
    -- Stable idempotency key generated in Phase A; never regenerated on retry
    booking_idempotency_key TEXT    NOT NULL UNIQUE,
    external_shipment_id    TEXT,
    tracking_code           TEXT,
    -- Who pays the shipping cost: customer, organization, platform, or supplier
    shipping_payer          TEXT    NOT NULL DEFAULT 'customer'
                                    CHECK (shipping_payer IN ('customer','organization','platform','supplier')),
    cost_minor              INTEGER NOT NULL DEFAULT 0,
    currency                TEXT    NOT NULL DEFAULT 'IRR',
    booked_at               TEXT,
    delivered_at            TEXT,
    failure_reason          TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

INSERT INTO shipments_new SELECT * FROM shipments;
DROP TABLE shipments;
ALTER TABLE shipments_new RENAME TO shipments;

CREATE INDEX IF NOT EXISTS idx_shipments_fo       ON shipments(fulfillment_order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_provider ON shipments(provider_code, external_shipment_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tracking_code);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_ikey ON shipments(booking_idempotency_key);

-- Step 4: re-enable FK enforcement (still outside any transaction).
PRAGMA foreign_keys = ON;

-- Step 5: open a fresh transaction so the migrator's schema_migrations INSERT
-- (appended by migrator.py after this SQL) runs atomically.
BEGIN;
