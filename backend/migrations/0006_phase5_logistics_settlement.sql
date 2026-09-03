-- 0006_phase5_logistics_settlement
--
-- Phase 5: Logistics + Supplier Settlement
--
-- PURELY ADDITIVE. No existing table is dropped or renamed. No existing
-- column is removed. All Phase 1–4 rows remain valid.
--
-- Money: integer minor units throughout. No REAL/FLOAT/DOUBLE.
-- Timestamps: UTC ISO-8601 TEXT.

-- ================================================================ CARRIER CONFIGS
-- Per-carrier, per-geography configuration for logistics providers.
-- provider_code distinguishes mock vs future real providers (alopeyk, post, tipax).
-- A NULL province/city means the carrier covers all of Iran (national).

CREATE TABLE IF NOT EXISTS carrier_configs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_code   TEXT    NOT NULL CHECK (provider_code IN ('mock','alopeyk','post','tipax','local_courier')),
    name_fa         TEXT    NOT NULL,
    province        TEXT,                          -- NULL = national
    city            TEXT,                          -- NULL = all cities in province
    -- Comma-separated: local,intercity,cold_chain
    capabilities    TEXT    NOT NULL DEFAULT 'local',
    cost_minor      INTEGER NOT NULL DEFAULT 0,    -- flat quote cost for this carrier
    currency        TEXT    NOT NULL DEFAULT 'IRR',
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    config_json     TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_cc_provider  ON carrier_configs(provider_code, is_active);
CREATE INDEX IF NOT EXISTS idx_cc_province  ON carrier_configs(province, city);

-- ================================================================ SHIPMENT PLANS
-- One plan per fulfillment order. Created automatically after payment succeeds.
-- The plan selects the best carrier from available quotes.

CREATE TABLE IF NOT EXISTS shipment_plans (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fulfillment_order_id    INTEGER NOT NULL UNIQUE REFERENCES fulfillment_orders(id),
    status                  TEXT    NOT NULL DEFAULT 'planned'
                                    CHECK (status IN ('planned','quote_selected','booking_initiated','booked','failed','logistics_not_required')),
    selected_carrier_config_id INTEGER REFERENCES carrier_configs(id),
    failure_reason          TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sp_fo ON shipment_plans(fulfillment_order_id);

-- ================================================================ SHIPMENT PLAN QUOTES
-- Eligible carrier quotes collected for a given fulfillment order.

CREATE TABLE IF NOT EXISTS shipment_plan_quotes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_plan_id    INTEGER NOT NULL REFERENCES shipment_plans(id),
    carrier_config_id   INTEGER NOT NULL REFERENCES carrier_configs(id),
    cost_minor          INTEGER NOT NULL DEFAULT 0,
    capabilities        TEXT    NOT NULL DEFAULT 'local',
    is_selected         INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0,1)),
    quote_metadata_json TEXT    NOT NULL DEFAULT '{}',
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_spq_plan ON shipment_plan_quotes(shipment_plan_id);

-- ================================================================ SHIPMENTS
-- Actual carrier booking. Two-phase: Phase A sets status='booking' and
-- persists booking_idempotency_key. External call happens outside any DB
-- transaction. Phase B finalises status to 'booked' or 'booking_failed'.
--
-- The booking_idempotency_key is IMMUTABLE once set and is passed to the
-- carrier on every attempt. Retries never generate a new key.

CREATE TABLE IF NOT EXISTS shipments (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fulfillment_order_id    INTEGER NOT NULL REFERENCES fulfillment_orders(id),
    shipment_plan_id        INTEGER REFERENCES shipment_plans(id),
    carrier_config_id       INTEGER NOT NULL REFERENCES carrier_configs(id),
    provider_code           TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'planned'
                                    CHECK (status IN (
                                        'planned','booking','booked',
                                        'in_transit','delivered','failed','booking_failed'
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
CREATE INDEX IF NOT EXISTS idx_shipments_fo       ON shipments(fulfillment_order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_provider ON shipments(provider_code, external_shipment_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tracking_code);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shipments_ikey ON shipments(booking_idempotency_key);

-- ================================================================ SHIPMENT BOOKING LOG
-- Append-only audit trail for every booking attempt phase.

CREATE TABLE IF NOT EXISTS shipment_booking_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id         INTEGER NOT NULL REFERENCES shipments(id),
    phase               TEXT    NOT NULL CHECK (phase IN ('phase_a','external','phase_b')),
    outcome             TEXT    NOT NULL,          -- 'success', 'failure', 'pending'
    external_shipment_id TEXT,
    tracking_code       TEXT,
    error_detail        TEXT,
    attempted_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sbl_shipment ON shipment_booking_log(shipment_id);

-- ================================================================ WEBHOOK EVENTS
-- Deduplication + raw payload audit for inbound carrier webhooks.
-- Uniqueness on (provider_code, provider_event_id) enforces exactly-once processing.
-- Unknown provider_code or missing provider_event_id must be rejected before insert.

CREATE TABLE IF NOT EXISTS webhook_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_code       TEXT    NOT NULL,
    provider_event_id   TEXT    NOT NULL,
    shipment_id         INTEGER REFERENCES shipments(id),
    raw_payload         TEXT    NOT NULL,          -- full body retained for VERIFIED events
    outcome             TEXT    NOT NULL DEFAULT 'accepted'
                                CHECK (outcome IN ('accepted','rejected','duplicate','error')),
    processed_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (provider_code, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_we_provider  ON webhook_events(provider_code, processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_we_shipment  ON webhook_events(shipment_id);

-- ================================================================ SHIPMENT STATE PROGRESSION
-- Defines which shipment statuses are terminal and which can progress.
-- Enforced in application code; this comment documents the DAG:
--
--  planned → booking → booked → in_transit → delivered
--                   ↘ booking_failed
--  planned → failed          (logistics planning failed)

-- ================================================================ SUPPLIER PAYABLE ENTRIES
-- Append-only ledger of amounts owed to suppliers.
-- Entry is created ONLY when the ACTUAL FulfillmentOrder reaches DELIVERED.
-- The gross basis is SUM(COALESCE(line_cost_minor, line_selling_minor)) from
-- the immutable fulfillment_order_items snapshot at delivery time.
-- NEVER read current seller_offer prices.
--
-- Rounding policy (BLOCKER 5):
--   commission_minor = (gross_minor * commission_rate_bps) // 10_000
--   Integer floor division. No floats.

CREATE TABLE IF NOT EXISTS supplier_payable_entries (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id),
    fulfillment_order_id    INTEGER NOT NULL REFERENCES fulfillment_orders(id),
    entry_type              TEXT    NOT NULL DEFAULT 'sale_payable'
                                    CHECK (entry_type IN ('sale_payable')),
    gross_minor             INTEGER NOT NULL CHECK (gross_minor > 0),
    -- Deterministic key: 'fulfillment:{fo_id}:sale-payable'
    idempotency_key         TEXT    NOT NULL UNIQUE,
    -- unbatched → batched → settled
    status                  TEXT    NOT NULL DEFAULT 'unbatched'
                                    CHECK (status IN ('unbatched','batched','settled')),
    settlement_batch_id     INTEGER REFERENCES settlement_batches(id),
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_spe_supplier ON supplier_payable_entries(supplier_id, status);
CREATE INDEX IF NOT EXISTS idx_spe_fo       ON supplier_payable_entries(fulfillment_order_id);

-- ================================================================ SETTLEMENT BATCHES
-- Groups unbatched supplier_payable_entries for payment.
-- idempotency_key ensures same request returns same batch.
-- commission and shipping_charge are computed at batch creation time using
-- integer arithmetic only (no floats).

CREATE TABLE IF NOT EXISTS settlement_batches (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id),
    idempotency_key         TEXT    NOT NULL UNIQUE,
    status                  TEXT    NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending','processing','completed','failed')),
    -- Financial summary (integer minor units; computed at creation, IMMUTABLE)
    commission_rate_bps     INTEGER NOT NULL DEFAULT 1000 CHECK (commission_rate_bps >= 0),
    gross_minor             INTEGER NOT NULL DEFAULT 0,
    commission_minor        INTEGER NOT NULL DEFAULT 0,
    shipping_charge_minor   INTEGER NOT NULL DEFAULT 0,
    net_minor               INTEGER NOT NULL DEFAULT 0,
    items_count             INTEGER NOT NULL DEFAULT 0,
    payment_reference       TEXT,
    external_reference      TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sb_supplier ON settlement_batches(supplier_id, status);

-- ================================================================ SETTLEMENT BATCH ITEMS
-- Links a payable entry to exactly ONE settlement batch.
-- UNIQUE(supplier_payable_entry_id) prevents the same entry entering two batches.

CREATE TABLE IF NOT EXISTS settlement_batch_items (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_batch_id         INTEGER NOT NULL REFERENCES settlement_batches(id),
    supplier_payable_entry_id   INTEGER NOT NULL REFERENCES supplier_payable_entries(id),
    gross_minor                 INTEGER NOT NULL,   -- snapshot at batch creation
    created_at                  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (supplier_payable_entry_id)              -- one entry → one batch only
);
CREATE INDEX IF NOT EXISTS idx_sbi_batch ON settlement_batch_items(settlement_batch_id);

-- ================================================================ SETTLEMENT PAYMENTS
-- Append-only. Exactly ONE row per completed settlement batch.
-- Never UPDATE or DELETE rows here.
-- net_minor is the actual payout = gross - commission - shipping_charge.
-- The idempotency of completion is enforced by UNIQUE(settlement_batch_id).

CREATE TABLE IF NOT EXISTS settlement_payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_batch_id INTEGER NOT NULL UNIQUE REFERENCES settlement_batches(id),
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id),
    net_minor           INTEGER NOT NULL CHECK (net_minor > 0),
    payment_reference   TEXT,
    external_reference  TEXT,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_spmt_supplier ON settlement_payments(supplier_id);

-- ================================================================ SEED CARRIER CONFIGS
-- Mock carriers for testing and demo. REAL providers NOT implemented.

INSERT OR IGNORE INTO carrier_configs
    (provider_code, name_fa, province, city, capabilities, cost_minor, is_active)
VALUES
    -- National mock carrier (covers all of Iran, intercity)
    ('mock', 'پیک ملی (شبیه‌ساز)', NULL,        NULL,    'local,intercity', 150000, 1),
    -- Tehran local mock
    ('mock', 'پیک محلی تهران (شبیه‌ساز)',   'تهران',  NULL,    'local',           50000,  1),
    -- Isfahan local mock (supports cold-chain for perishables)
    ('mock', 'پیک سرد اصفهان (شبیه‌ساز)',   'اصفهان', NULL,    'local,cold_chain', 70000, 1),
    -- Isfahan local mock (standard)
    ('mock', 'پیک محلی اصفهان (شبیه‌ساز)',  'اصفهان', NULL,    'local',            50000, 1),
    -- National intercity (A4 paper etc.)
    ('mock', 'پست سراسری (شبیه‌ساز)',       NULL,        NULL,    'local,intercity', 120000, 1);
