-- 0024_vat_in_total (PostgreSQL-native)
--
-- Phase 8 v6: Integrate VAT into the authoritative money equation.
--
-- BEFORE (v5): total_minor = subtotal_minor + shipping_fee_minor  (tax informational)
-- AFTER  (v6): total_minor = subtotal_minor + shipping_fee_minor + tax_minor
--              total_minor = credit_minor + cash_minor
--
-- PostgreSQL notes:
--   • orders.tax_minor was NOT added by migration 0023 on PG (0023 only promoted
--     existing INTEGER columns to BIGINT). It is added here for the first time.
--   • Anonymous CHECK constraints get system-generated names on PostgreSQL.
--     We locate them dynamically via pg_constraint rather than assuming names.
--   • All new money columns are BIGINT to match the PG schema convention
--     established in migration 0023.

-- ── orders: add new columns ──────────────────────────────────────────────────

ALTER TABLE orders ADD COLUMN tax_minor          BIGINT NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN taxable_base_minor  BIGINT NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN tax_rate_bps        INTEGER NOT NULL DEFAULT 0;

-- Back-fill taxable_base_minor for historical rows (shipping excluded from VAT)
UPDATE orders SET taxable_base_minor = subtotal_minor WHERE taxable_base_minor = 0;

-- Drop the old CHECK (total_minor = subtotal_minor + shipping_fee_minor)
-- located dynamically because PostgreSQL auto-names anonymous constraints.
DO $$
DECLARE
    _cname TEXT;
BEGIN
    SELECT conname INTO _cname
    FROM pg_constraint
    WHERE conrelid = 'orders'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%total_minor = subtotal_minor + shipping_fee_minor%'
      AND pg_get_constraintdef(oid) NOT LIKE '%tax_minor%';
    IF _cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE orders DROP CONSTRAINT %I', _cname);
    END IF;
END;
$$;

-- Add the new constraint (existing rows satisfy it because tax_minor = 0 ⇒ old total holds)
ALTER TABLE orders
    ADD CONSTRAINT orders_total_check
    CHECK (total_minor = subtotal_minor + shipping_fee_minor + tax_minor);

-- ── payment_intents: add new columns ────────────────────────────────────────

ALTER TABLE payment_intents ADD COLUMN tax_minor          BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payment_intents ADD COLUMN taxable_base_minor  BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payment_intents ADD COLUMN tax_rate_bps        INTEGER NOT NULL DEFAULT 0;

-- Back-fill taxable_base_minor for historical rows
UPDATE payment_intents SET taxable_base_minor = subtotal_minor WHERE taxable_base_minor = 0;

-- Drop old CHECK (total_minor = subtotal_minor + shipping_fee_minor) on payment_intents
DO $$
DECLARE
    _cname TEXT;
BEGIN
    SELECT conname INTO _cname
    FROM pg_constraint
    WHERE conrelid = 'payment_intents'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%total_minor = subtotal_minor + shipping_fee_minor%'
      AND pg_get_constraintdef(oid) NOT LIKE '%tax_minor%';
    IF _cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE payment_intents DROP CONSTRAINT %I', _cname);
    END IF;
END;
$$;

-- Add updated constraint
ALTER TABLE payment_intents
    ADD CONSTRAINT payment_intents_total_check
    CHECK (total_minor = subtotal_minor + shipping_fee_minor + tax_minor);

-- ── Add VAT payable liability account (idempotent) ───────────────────────────
INSERT INTO ledger_accounts (code, name_fa, type)
    VALUES ('2010', 'مالیات بر ارزش افزوده پرداختنی', 'liability')
    ON CONFLICT (code) DO NOTHING;
