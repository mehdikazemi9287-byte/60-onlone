-- Migration 0027: Supplier Marketplace Foundation (Phase 2) + Offer/Pricing
-- Engine data layer (Phase 3).
--
-- IMPORTANT CONTEXT: this repo already has a mature, tested supplier/offer
-- architecture predating this migration (suppliers, supplier_locations,
-- seller_offers, product_identifiers, identity_resolution_queue,
-- fulfillment_engine.route() as a deterministic best-offer/buy-box selector,
-- supplier_ledger_service for real delivered-order settlement). This
-- migration is purely additive and fills the specific remaining gaps:
--   1. A finer supplier onboarding lifecycle with an audit trail, layered on
--      top of (not replacing) the existing `suppliers.status` operational
--      column that all existing fulfillment/checkout code already depends on.
--   2. Offer price-history (prepare-only, per explicit instruction not to
--      build UI for it yet).
--   3. A `replacement_product_id` prep column for unavailable-product
--      alternatives — nullable, never auto-populated by any code in this
--      migration or the services added alongside it; only a real admin
--      action can ever set it.
--   4. A dedicated staging table for supplier bulk-catalog-import rows, kept
--      deliberately separate from the pre-existing connector/ERP auto-create
--      pipeline (product_resolution_service.py's resolve_product(), which
--      CAN auto-create a placeholder canonical product on no-match — that
--      pre-existing behavior is untouched here, but the NEW supplier-facing
--      bulk import built alongside this migration never calls it; it reuses
--      only the non-creating product_identity_service.resolve_identifier()
--      pipeline and queues unmatched rows via queue_for_review()).
--
-- All DDL is additive: ALTER TABLE ADD COLUMN / CREATE TABLE IF NOT EXISTS.
-- No existing column, table, or row is altered in meaning or dropped.

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Supplier onboarding lifecycle (additive, layered on `status`)
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE suppliers ADD COLUMN onboarding_stage TEXT NOT NULL DEFAULT 'draft'
    CHECK (onboarding_stage IN (
        'draft', 'submitted', 'under_review', 'approved', 'rejected'
    ));

-- Backfill: every supplier that already exists in production predates this
-- lifecycle and already has an operational `status` — mark their onboarding
-- as already-approved so no existing supplier/offer/fulfillment behavior
-- changes as a result of this migration.
UPDATE suppliers SET onboarding_stage = 'approved' WHERE status IN ('active', 'suspended', 'inactive');
UPDATE suppliers SET onboarding_stage = 'submitted' WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS supplier_onboarding_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id      INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    from_stage       TEXT NOT NULL,
    to_stage         TEXT NOT NULL,
    actor_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_supplier_onboarding_events_supplier
    ON supplier_onboarding_events(supplier_id, created_at);

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Offer price history (prepare-only architecture, no UI this pass)
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS offer_price_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id            INTEGER NOT NULL REFERENCES seller_offers(id) ON DELETE CASCADE,
    old_price_minor     INTEGER,
    new_price_minor     INTEGER NOT NULL CHECK (new_price_minor >= 0),
    changed_by_supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    changed_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_offer_price_history_offer
    ON offer_price_history(offer_id, changed_at);

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Replacement/alternative-product prep (never auto-populated)
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE products ADD COLUMN replacement_product_id INTEGER
    REFERENCES products(id) ON DELETE SET NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Supplier bulk-catalog-import staging (strict no-fabrication pathway)
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS supplier_catalog_import_batches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    submitted_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    total_rows          INTEGER NOT NULL DEFAULT 0,
    matched_count        INTEGER NOT NULL DEFAULT 0,
    queued_count         INTEGER NOT NULL DEFAULT 0,
    rejected_count       INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS supplier_catalog_import_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id            INTEGER NOT NULL REFERENCES supplier_catalog_import_batches(id) ON DELETE CASCADE,
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    raw_row_json        TEXT NOT NULL,
    match_status        TEXT NOT NULL CHECK (match_status IN (
                             'matched', 'duplicate_sku', 'unresolved', 'rejected'
                         )),
    matched_product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    created_offer_id    INTEGER REFERENCES seller_offers(id) ON DELETE SET NULL,
    resolution_queue_id INTEGER REFERENCES identity_resolution_queue(id) ON DELETE SET NULL,
    error_message       TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_supplier_catalog_import_rows_batch
    ON supplier_catalog_import_rows(batch_id);
CREATE INDEX IF NOT EXISTS idx_supplier_catalog_import_rows_supplier
    ON supplier_catalog_import_rows(supplier_id, match_status);
