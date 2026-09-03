-- Migration 0020: Add VAT breakdown columns to supplier_quotes
--
-- ROOT CAUSE OF THE BUG THIS MIGRATION SUPPORTS:
--   Before this migration, rfq_service.submit_supplier_quote() stored:
--     grand_total_minor = items_total + shipping_cost        <- NO VAT
--   And purchase_order_service.create_purchase_order() computed:
--     grand_total = items_total + shipping_cost + items_vat  <- items VAT only, no shipping VAT
--   Result: Quote grand_total != PO grand_total whenever shipping VAT > 0.
--
--   The per-line VAT was always stored correctly in supplier_quote_items.vat_amount_minor,
--   but it was never aggregated into the quote-level total, and shipping VAT was
--   computed in rfq_service but then silently discarded.
--
-- THIS MIGRATION:
--   1. Adds shipping_vat_minor   — VAT on the shipping cost (new column)
--   2. Adds shipping_vat_rate_bps — the bps rate used for shipping VAT (audit trail, new column)
--   NOTE: vat_amount_minor already exists from migration 0005 for line-item VAT.
--   Backfills vat_amount_minor from existing quote_items (items VAT is recoverable).
--   shipping_vat_minor = 0 for all pre-existing rows because shipping VAT was
--   computed but discarded at submission time — the correct historical value IS zero.
--
-- EXISTING grand_total_minor IS NOT CHANGED:
--   Existing quote rows are financial history.  Their grand_total_minor was wrong
--   (missing VAT) but changing it retrospectively would be worse.  A corrective
--   memo must be issued for any affected quotes if needed.
--   Only quotes created AFTER this migration will have correct grand_total_minor.
--
-- IDEMPOTENCY:
--   The schema_migrations tracking table ensures this file is applied exactly once.
--   The UPDATE backfill is re-run safe: it only touches rows where vat_amount_minor = 0.

-- 1. Add VAT breakdown columns (runs once; migrator.py ensures no duplicate run)
--    NOTE: vat_amount_minor was already present from migration 0005 (for line-item VAT).
--    We only add the two shipping-VAT columns that did not previously exist.
ALTER TABLE supplier_quotes ADD COLUMN shipping_vat_minor   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE supplier_quotes ADD COLUMN shipping_vat_rate_bps INTEGER NOT NULL DEFAULT 0;

-- 2. Backfill total items VAT from existing quote_items
--    shipping_vat_minor stays 0 for existing rows (see note above)
--    This UPDATE is re-run safe: the vat_amount_minor = 0 guard skips already-filled rows
UPDATE supplier_quotes
SET vat_amount_minor = COALESCE((
    SELECT SUM(sqi.vat_amount_minor)
    FROM supplier_quote_items sqi
    WHERE sqi.supplier_quote_id = supplier_quotes.id
), 0)
WHERE vat_amount_minor = 0;
