-- 0013_finance_automation
--
-- Phase 6 Final: Invoice capture, three-way matching, reconciliation.
--
-- PURELY ADDITIVE (CREATE TABLE IF NOT EXISTS only).
-- The migrator wraps this in BEGIN;...COMMIT; automatically.
--
-- NOTE: procurement_orders table is created here as a lightweight
-- alias/extension point for three-way match. fulfillment_orders
-- already exists from migration 0003.

-- procurement_orders: lightweight table for three-way match
-- (purchase_orders from 0005 tracks org-level procurement;
--  this tracks supplier-facing purchase orders for 3-way match)
CREATE TABLE IF NOT EXISTS procurement_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    reference_number TEXT NOT NULL,
    order_date TEXT NOT NULL,
    total_minor INTEGER NOT NULL DEFAULT 0 CHECK (total_minor >= 0),
    currency TEXT NOT NULL DEFAULT 'IRR',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN (
        'open','received','partial','closed','cancelled'
    )),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_po_supplier ON procurement_orders(supplier_id, status);

CREATE TABLE IF NOT EXISTS supplier_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    connector_account_id INTEGER REFERENCES connector_accounts(id),
    invoice_number TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    subtotal_minor INTEGER NOT NULL DEFAULT 0 CHECK (subtotal_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    total_minor INTEGER NOT NULL DEFAULT 0 CHECK (total_minor >= 0),
    currency TEXT NOT NULL DEFAULT 'IRR',
    status TEXT NOT NULL DEFAULT 'captured' CHECK (status IN (
        'captured','validated','matched','matched_with_tolerance',
        'mismatch','duplicate','rejected'
    )),
    source_type TEXT NOT NULL DEFAULT 'manual' CHECK (source_type IN (
        'manual','ocr_scan','electronic','api','import'
    )),
    raw_json TEXT NOT NULL DEFAULT '{}',
    dedup_hash TEXT,
    is_duplicate INTEGER NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0,1)),
    duplicate_of_id INTEGER REFERENCES supplier_invoices(id),
    match_status TEXT CHECK (match_status IN (
        'matched','within_tolerance','mismatch','missing_document'
    )),
    exception_id INTEGER REFERENCES exceptions(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    -- No UNIQUE on (supplier_id, invoice_number, invoice_date):
    -- duplicate invoices are stored with is_duplicate=1 and duplicate_of_id.
    -- Deduplication is enforced at service level via detect_duplicate().
);
CREATE INDEX IF NOT EXISTS idx_si_supplier ON supplier_invoices(supplier_id, status);
CREATE INDEX IF NOT EXISTS idx_si_dedup ON supplier_invoices(dedup_hash);

CREATE TABLE IF NOT EXISTS supplier_invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES supplier_invoices(id),
    line_number INTEGER NOT NULL,
    external_code TEXT,
    barcode TEXT,
    product_name TEXT,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price_minor INTEGER NOT NULL DEFAULT 0 CHECK (unit_price_minor >= 0),
    line_total_minor INTEGER NOT NULL DEFAULT 0 CHECK (line_total_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    product_id INTEGER REFERENCES products(id),
    offer_id INTEGER REFERENCES seller_offers(id),
    match_status TEXT CHECK (match_status IN ('matched','unmatched','ambiguous')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sil_invoice ON supplier_invoice_lines(invoice_id);

CREATE TABLE IF NOT EXISTS three_way_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    procurement_order_id INTEGER REFERENCES procurement_orders(id),
    invoice_id INTEGER REFERENCES supplier_invoices(id),
    fulfillment_order_id INTEGER REFERENCES fulfillment_orders(id),
    result TEXT NOT NULL DEFAULT 'pending' CHECK (result IN (
        'pending','matched','within_tolerance','mismatch','missing_document'
    )),
    discrepancy_json TEXT NOT NULL DEFAULT '{}',
    tolerance_bps INTEGER NOT NULL DEFAULT 100,
    exception_id INTEGER REFERENCES exceptions(id),
    checked_by INTEGER REFERENCES users(id),
    checked_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_twm_supplier ON three_way_matches(supplier_id, result);
CREATE INDEX IF NOT EXISTS idx_twm_invoice ON three_way_matches(invoice_id);

CREATE TABLE IF NOT EXISTS reconciliation_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_ref TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN ('psp_statement','bank_statement','manual')),
    supplier_id INTEGER REFERENCES suppliers(id),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    unmatched_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','completed','failed')),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_rb_status ON reconciliation_batches(status);

CREATE TABLE IF NOT EXISTS reconciliation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES reconciliation_batches(id),
    external_ref TEXT NOT NULL,
    transaction_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'IRR',
    description TEXT,
    settlement_batch_id INTEGER REFERENCES settlement_batches(id),
    payment_id INTEGER REFERENCES payments(id),
    status TEXT NOT NULL DEFAULT 'unmatched' CHECK (status IN ('matched','unmatched','partial','disputed')),
    match_confidence_bps INTEGER NOT NULL DEFAULT 0 CHECK (match_confidence_bps BETWEEN 0 AND 10000),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_ri_batch ON reconciliation_items(batch_id, status);
