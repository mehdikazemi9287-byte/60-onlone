-- Drop the pre-tax total CHECKs left behind on PostgreSQL (orders, payment_intents). The VAT-aware
-- *_total_check (total = subtotal + shipping + tax) stays. Matched by definition, not name, to be safe.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT conrelid::regclass::text AS tbl, conname
    FROM pg_constraint
    WHERE contype = 'c'
      AND conrelid IN ('orders'::regclass, 'payment_intents'::regclass)
      AND regexp_replace(pg_get_constraintdef(oid), '\s', '', 'g') = 'CHECK((total_minor=(subtotal_minor+shipping_fee_minor)))'
  LOOP
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', r.tbl, r.conname);
  END LOOP;
END $$;
