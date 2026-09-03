-- 0023_bigint_money_columns (PostgreSQL-native)
--
-- IRR amounts frequently exceed the PostgreSQL INTEGER range (max ~2.1 billion).
-- This migration promotes every money/amount column from INTEGER to BIGINT so
-- that values like credit_limit_minor=5_000_000_000 (5 billion IRR) can be
-- stored without overflow.
--
-- SQLite stores all integers as up to 8-byte values natively, so this mismatch
-- only manifests on PostgreSQL.  BIGINT in PostgreSQL is 8-byte signed, matching
-- SQLite's storage model and supporting up to ~9.2 × 10^18.
--
-- PURELY ADDITIVE: no data is lost, no CHECK constraints are altered.

ALTER TABLE accounting_documents ALTER COLUMN tax_minor TYPE BIGINT;
ALTER TABLE accounting_documents ALTER COLUMN total_minor TYPE BIGINT;
ALTER TABLE carrier_configs ALTER COLUMN cost_minor TYPE BIGINT;
ALTER TABLE cart_items ALTER COLUMN unit_price_minor TYPE BIGINT;
ALTER TABLE credit_allocations ALTER COLUMN allocated_minor TYPE BIGINT;
ALTER TABLE credit_allocations ALTER COLUMN per_transaction_limit_minor TYPE BIGINT;
ALTER TABLE credit_allocations ALTER COLUMN period_limit_minor TYPE BIGINT;
ALTER TABLE credit_ledger_entries ALTER COLUMN amount_minor TYPE BIGINT;
ALTER TABLE credit_reservations ALTER COLUMN amount_minor TYPE BIGINT;
ALTER TABLE fulfillment_order_items ALTER COLUMN cost_price_minor TYPE BIGINT;
ALTER TABLE fulfillment_order_items ALTER COLUMN line_cost_minor TYPE BIGINT;
ALTER TABLE fulfillment_order_items ALTER COLUMN line_selling_minor TYPE BIGINT;
ALTER TABLE fulfillment_order_items ALTER COLUMN selling_price_minor TYPE BIGINT;
ALTER TABLE fulfillment_orders ALTER COLUMN gross_payable_minor TYPE BIGINT;
ALTER TABLE ledger_entries ALTER COLUMN amount_minor TYPE BIGINT;
ALTER TABLE order_items ALTER COLUMN line_total_minor TYPE BIGINT;
ALTER TABLE order_items ALTER COLUMN unit_price_minor TYPE BIGINT;
ALTER TABLE orders ALTER COLUMN cash_minor TYPE BIGINT;
ALTER TABLE orders ALTER COLUMN credit_minor TYPE BIGINT;
ALTER TABLE orders ALTER COLUMN shipping_fee_minor TYPE BIGINT;
ALTER TABLE orders ALTER COLUMN subtotal_minor TYPE BIGINT;
ALTER TABLE orders ALTER COLUMN total_minor TYPE BIGINT;
ALTER TABLE organizations ALTER COLUMN credit_limit_minor TYPE BIGINT;
ALTER TABLE payment_intent_items ALTER COLUMN line_total_minor TYPE BIGINT;
ALTER TABLE payment_intent_items ALTER COLUMN unit_price_minor TYPE BIGINT;
ALTER TABLE payment_intents ALTER COLUMN cash_minor TYPE BIGINT;
ALTER TABLE payment_intents ALTER COLUMN credit_minor TYPE BIGINT;
ALTER TABLE payment_intents ALTER COLUMN shipping_fee_minor TYPE BIGINT;
ALTER TABLE payment_intents ALTER COLUMN subtotal_minor TYPE BIGINT;
ALTER TABLE payment_intents ALTER COLUMN total_minor TYPE BIGINT;
ALTER TABLE payments ALTER COLUMN amount_minor TYPE BIGINT;
ALTER TABLE price_source_entries ALTER COLUMN price_minor TYPE BIGINT;
ALTER TABLE procurement_orders ALTER COLUMN total_minor TYPE BIGINT;
ALTER TABLE products ALTER COLUMN base_price_minor TYPE BIGINT;
ALTER TABLE purchase_order_items ALTER COLUMN discount_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_order_items ALTER COLUMN total_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_order_items ALTER COLUMN unit_price_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_order_items ALTER COLUMN vat_amount_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_orders ALTER COLUMN discount_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_orders ALTER COLUMN grand_total_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_orders ALTER COLUMN shipping_cost_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_orders ALTER COLUMN total_items_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_orders ALTER COLUMN vat_amount_minor_snapshot TYPE BIGINT;
ALTER TABLE purchase_request_items ALTER COLUMN estimated_unit_price_minor TYPE BIGINT;
ALTER TABLE purchase_requests ALTER COLUMN budget_minor TYPE BIGINT;
ALTER TABLE reconciliation_items ALTER COLUMN amount_minor TYPE BIGINT;
ALTER TABLE seller_offers ALTER COLUMN cost_price_minor TYPE BIGINT;
ALTER TABLE seller_offers ALTER COLUMN selling_price_minor TYPE BIGINT;
ALTER TABLE settlement_batch_items ALTER COLUMN gross_minor TYPE BIGINT;
ALTER TABLE settlement_batches ALTER COLUMN commission_minor TYPE BIGINT;
ALTER TABLE settlement_batches ALTER COLUMN gross_minor TYPE BIGINT;
ALTER TABLE settlement_batches ALTER COLUMN net_minor TYPE BIGINT;
ALTER TABLE settlement_batches ALTER COLUMN shipping_charge_minor TYPE BIGINT;
ALTER TABLE settlement_payments ALTER COLUMN net_minor TYPE BIGINT;
ALTER TABLE shipment_plan_quotes ALTER COLUMN cost_minor TYPE BIGINT;
ALTER TABLE shipments ALTER COLUMN cost_minor TYPE BIGINT;
ALTER TABLE supplier_invoice_lines ALTER COLUMN line_total_minor TYPE BIGINT;
ALTER TABLE supplier_invoice_lines ALTER COLUMN tax_minor TYPE BIGINT;
ALTER TABLE supplier_invoice_lines ALTER COLUMN unit_price_minor TYPE BIGINT;
ALTER TABLE supplier_invoices ALTER COLUMN subtotal_minor TYPE BIGINT;
ALTER TABLE supplier_invoices ALTER COLUMN tax_minor TYPE BIGINT;
ALTER TABLE supplier_invoices ALTER COLUMN total_minor TYPE BIGINT;
ALTER TABLE supplier_payable_entries ALTER COLUMN gross_minor TYPE BIGINT;
ALTER TABLE supplier_quote_items ALTER COLUMN discount_minor TYPE BIGINT;
ALTER TABLE supplier_quote_items ALTER COLUMN total_minor TYPE BIGINT;
ALTER TABLE supplier_quote_items ALTER COLUMN unit_price_minor TYPE BIGINT;
ALTER TABLE supplier_quote_items ALTER COLUMN vat_amount_minor TYPE BIGINT;
ALTER TABLE supplier_quotes ALTER COLUMN discount_minor TYPE BIGINT;
ALTER TABLE supplier_quotes ALTER COLUMN grand_total_minor TYPE BIGINT;
ALTER TABLE supplier_quotes ALTER COLUMN shipping_cost_minor TYPE BIGINT;
ALTER TABLE supplier_quotes ALTER COLUMN shipping_vat_minor TYPE BIGINT;
ALTER TABLE supplier_quotes ALTER COLUMN total_items_minor TYPE BIGINT;
ALTER TABLE supplier_quotes ALTER COLUMN vat_amount_minor TYPE BIGINT;
