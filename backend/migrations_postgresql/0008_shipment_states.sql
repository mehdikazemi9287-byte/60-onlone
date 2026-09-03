-- 0008_shipment_states (PostgreSQL-native)
--
-- Extend shipments.status CHECK to include 'out_for_delivery' and 'returned'.
--
-- PostgreSQL supports ALTER TABLE to drop/add CHECK constraints, so no
-- table rebuild is needed (unlike the SQLite version which had to use PRAGMA).
--
-- PURELY ADDITIVE: no existing status value is removed.

-- Drop the existing status CHECK constraint (auto-named by PostgreSQL).
DO $$
DECLARE
    cname TEXT;
BEGIN
    SELECT conname INTO cname
    FROM pg_constraint
    WHERE conrelid = 'shipments'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%status%'
    LIMIT 1;

    IF cname IS NOT NULL THEN
        EXECUTE 'ALTER TABLE shipments DROP CONSTRAINT ' || quote_ident(cname);
    END IF;
END;
$$;

-- Add the extended CHECK constraint (drop first if it exists from a prior run).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'shipments'::regclass
          AND conname = 'shipments_status_check'
    ) THEN
        ALTER TABLE shipments DROP CONSTRAINT shipments_status_check;
    END IF;
END;
$$;
ALTER TABLE shipments
    ADD CONSTRAINT shipments_status_check
    CHECK (status IN (
        'planned','booking','booked',
        'in_transit','out_for_delivery','delivered',
        'failed','booking_failed','returned'
    ));

-- Ensure all indexes exist (idempotent via IF NOT EXISTS).
CREATE INDEX IF NOT EXISTS idx_shipments_fo       ON shipments(fulfillment_order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_provider ON shipments(provider_code, external_shipment_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tracking_code);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_ikey ON shipments(booking_idempotency_key);
