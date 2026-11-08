-- Phase 5C: logistics standards — product package data, carrier rate shopping,
-- multi-seller shipment orchestration, normalized tracking, return shipments.
-- Money: integer Rial. Weight: grams. Dimensions: millimetres.

-- ================================================================ PRODUCT LOGISTICS SPECS
-- One row per product (scope_key 'p:<product_id>') or per seller offer
-- (scope_key 'o:<seller_offer_id>'); an offer row overrides the product row.
CREATE TABLE product_logistics_specs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key            TEXT    NOT NULL UNIQUE,
    product_id           INTEGER NOT NULL REFERENCES products(id),
    seller_offer_id      INTEGER REFERENCES seller_offers(id),
    length_mm            INTEGER NOT NULL CHECK (length_mm > 0),
    width_mm             INTEGER NOT NULL CHECK (width_mm > 0),
    height_mm            INTEGER NOT NULL CHECK (height_mm > 0),
    gross_weight_g       INTEGER NOT NULL CHECK (gross_weight_g > 0),
    is_fragile           INTEGER NOT NULL DEFAULT 0 CHECK (is_fragile IN (0,1)),
    is_perishable        INTEGER NOT NULL DEFAULT 0 CHECK (is_perishable IN (0,1)),
    requires_cold_chain  INTEGER NOT NULL DEFAULT 0 CHECK (requires_cold_chain IN (0,1)),
    hazmat_class         TEXT,
    hs_code              TEXT,
    iran_code            TEXT,
    gtin                 TEXT,
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_pls_product ON product_logistics_specs(product_id);
CREATE INDEX idx_pls_gtin ON product_logistics_specs(gtin);

-- ================================================================ CARRIERS (rate shopping)
CREATE TABLE logistics_carriers (
    provider_code     TEXT    PRIMARY KEY,
    name_fa           TEXT    NOT NULL,
    is_enabled        INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    has_live_api      INTEGER NOT NULL DEFAULT 0 CHECK (has_live_api IN (0,1)),
    same_city_only    INTEGER NOT NULL DEFAULT 0 CHECK (same_city_only IN (0,1)),
    capabilities      TEXT    NOT NULL DEFAULT '',
    tracking_prefix   TEXT    NOT NULL DEFAULT 'SO',
    status_map_json   TEXT    NOT NULL DEFAULT '{}',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE carrier_tariffs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_code           TEXT    NOT NULL REFERENCES logistics_carriers(provider_code),
    service_level           TEXT    NOT NULL CHECK (service_level IN ('same_day','express','economy')),
    name_fa                 TEXT    NOT NULL,
    base_minor              INTEGER NOT NULL DEFAULT 0 CHECK (base_minor >= 0),
    per_kg_minor            INTEGER NOT NULL DEFAULT 0 CHECK (per_kg_minor >= 0),
    weight_step_g           INTEGER NOT NULL DEFAULT 1000 CHECK (weight_step_g > 0),
    volumetric_divisor      INTEGER NOT NULL DEFAULT 5000 CHECK (volumetric_divisor > 0),
    max_weight_g            INTEGER,
    remote_surcharge_minor  INTEGER NOT NULL DEFAULT 0 CHECK (remote_surcharge_minor >= 0),
    fragile_surcharge_minor INTEGER NOT NULL DEFAULT 0 CHECK (fragile_surcharge_minor >= 0),
    cod_fee_bps             INTEGER NOT NULL DEFAULT 0 CHECK (cod_fee_bps >= 0),
    cod_min_fee_minor       INTEGER NOT NULL DEFAULT 0 CHECK (cod_min_fee_minor >= 0),
    insurance_bps           INTEGER NOT NULL DEFAULT 0 CHECK (insurance_bps >= 0),
    markup_bps              INTEGER NOT NULL DEFAULT 0 CHECK (markup_bps >= 0),
    supports_cod            INTEGER NOT NULL DEFAULT 1 CHECK (supports_cod IN (0,1)),
    transit_days_min        INTEGER NOT NULL DEFAULT 1 CHECK (transit_days_min >= 0),
    transit_days_max        INTEGER NOT NULL DEFAULT 3 CHECK (transit_days_max >= transit_days_min),
    is_active               INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_carrier_tariffs_provider ON carrier_tariffs(provider_code, is_active);

-- Zone matrix by province. '*' = any province; destination '=' = same province as origin.
-- NULL overrides fall back to the tariff defaults.
CREATE TABLE carrier_tariff_zones (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tariff_id           INTEGER NOT NULL REFERENCES carrier_tariffs(id),
    origin_province     TEXT    NOT NULL,
    destination_province TEXT   NOT NULL,
    base_minor          INTEGER CHECK (base_minor IS NULL OR base_minor >= 0),
    per_kg_minor        INTEGER CHECK (per_kg_minor IS NULL OR per_kg_minor >= 0),
    transit_days_min    INTEGER,
    transit_days_max    INTEGER,
    UNIQUE (tariff_id, origin_province, destination_province)
);

CREATE TABLE logistics_remote_areas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    province    TEXT    NOT NULL,
    city        TEXT    NOT NULL DEFAULT '*',
    UNIQUE (province, city)
);

CREATE TABLE shipping_quotes (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_group            TEXT    NOT NULL,
    fulfillment_order_id   INTEGER REFERENCES fulfillment_orders(id),
    provider_code          TEXT    NOT NULL,
    tariff_id              INTEGER REFERENCES carrier_tariffs(id),
    service_level          TEXT    NOT NULL,
    source                 TEXT    NOT NULL CHECK (source IN ('live','tariff')),
    origin_province        TEXT    NOT NULL,
    origin_city            TEXT    NOT NULL,
    destination_province   TEXT    NOT NULL,
    destination_city       TEXT    NOT NULL,
    actual_weight_g        INTEGER NOT NULL,
    volumetric_weight_g    INTEGER NOT NULL,
    billable_weight_g      INTEGER NOT NULL,
    cost_minor             INTEGER NOT NULL CHECK (cost_minor >= 0),
    price_minor            INTEGER NOT NULL CHECK (price_minor >= 0),
    cod                    INTEGER NOT NULL DEFAULT 0 CHECK (cod IN (0,1)),
    insurance_value_minor  INTEGER NOT NULL DEFAULT 0,
    eta_days_min           INTEGER NOT NULL,
    eta_days_max           INTEGER NOT NULL,
    breakdown_json         TEXT    NOT NULL DEFAULT '{}',
    is_selected            INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0,1)),
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_shipping_quotes_group ON shipping_quotes(quote_group);
CREATE INDEX idx_shipping_quotes_fo ON shipping_quotes(fulfillment_order_id);

-- Chosen quote persisted on the (phase-5) shipment plan.
ALTER TABLE shipment_plans ADD COLUMN selected_quote_id INTEGER REFERENCES shipping_quotes(id);
ALTER TABLE shipment_plans ADD COLUMN selected_quote_price_minor INTEGER;

-- ================================================================ SHIPMENTS v2 (per seller FO)
CREATE TABLE logistics_shipments (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key        TEXT    NOT NULL UNIQUE,
    direction              TEXT    NOT NULL DEFAULT 'forward' CHECK (direction IN ('forward','return')),
    fulfillment_order_id   INTEGER NOT NULL REFERENCES fulfillment_orders(id),
    order_id               INTEGER NOT NULL REFERENCES orders(id),
    supplier_id            INTEGER NOT NULL REFERENCES suppliers(id),
    return_request_id      INTEGER REFERENCES order_return_requests(id),
    provider_code          TEXT    NOT NULL,
    service_level          TEXT    NOT NULL,
    quote_id               INTEGER REFERENCES shipping_quotes(id),
    tracking_number        TEXT    NOT NULL UNIQUE,
    status                 TEXT    NOT NULL DEFAULT 'created'
                           CHECK (status IN ('created','picked_up','in_transit','out_for_delivery','delivered','failed','returned')),
    label_json             TEXT    NOT NULL DEFAULT '{}',
    cod_amount_minor       INTEGER NOT NULL DEFAULT 0 CHECK (cod_amount_minor >= 0),
    insurance_value_minor  INTEGER NOT NULL DEFAULT 0 CHECK (insurance_value_minor >= 0),
    pickup_requested_at    TEXT,
    pickup_window_start    TEXT,
    pickup_window_end      TEXT,
    ship_by_at             TEXT,
    deliver_by_at          TEXT,
    delivered_at           TEXT,
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_lship_fo ON logistics_shipments(fulfillment_order_id);
CREATE INDEX idx_lship_order ON logistics_shipments(order_id);
CREATE INDEX idx_lship_supplier ON logistics_shipments(supplier_id);

CREATE TABLE logistics_tracking_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id        INTEGER NOT NULL REFERENCES logistics_shipments(id),
    provider_code      TEXT    NOT NULL,
    provider_event_id  TEXT    NOT NULL,
    raw_status         TEXT    NOT NULL,
    status             TEXT    NOT NULL,
    occurred_at        TEXT    NOT NULL,
    location           TEXT    NOT NULL DEFAULT '',
    applied            INTEGER NOT NULL DEFAULT 1 CHECK (applied IN (0,1)),
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (provider_code, provider_event_id)
);
CREATE INDEX idx_ltrack_shipment ON logistics_tracking_events(shipment_id);

-- ================================================================ SAMPLE DEFAULT TARIFFS
-- Illustrative starting values only (not official carrier price lists);
-- operations replace them via /api/v1/admin/carriers/tariffs.
INSERT INTO logistics_carriers (provider_code, name_fa, same_city_only, capabilities, tracking_prefix) VALUES
    ('tipax',   'تیپاکس',      0, 'intercity,cod,fragile', 'TPX'),
    ('chapar',  'چاپار',       0, 'intercity,cod,fragile,cold_chain', 'CHP'),
    ('post',    'پست پیشتاز',  0, 'intercity,cod,remote', 'PST'),
    ('alopeyk', 'الوپیک',      1, 'local,cod,fragile,cold_chain', 'ALP');

INSERT INTO carrier_tariffs (provider_code, service_level, name_fa, base_minor, per_kg_minor, remote_surcharge_minor,
                             fragile_surcharge_minor, cod_fee_bps, cod_min_fee_minor, insurance_bps, transit_days_min, transit_days_max) VALUES
    ('tipax',   'express', 'تیپاکس اکسپرس', 900000, 150000, 300000, 200000, 100, 100000, 30, 1, 2),
    ('chapar',  'express', 'چاپار اکسپرس',  850000, 160000, 350000, 150000, 100, 100000, 30, 1, 3),
    ('post',    'express', 'پست پیشتاز',    600000, 120000, 0,      300000, 150, 80000,  50, 2, 4),
    ('post',    'economy', 'پست سفارشی',    400000, 90000,  0,      300000, 150, 80000,  50, 4, 7),
    ('alopeyk', 'same_day','الوپیک درون‌شهری', 700000, 50000, 0,    0,      0,   0,      0,  0, 0);

INSERT INTO carrier_tariff_zones (tariff_id, origin_province, destination_province, base_minor, per_kg_minor, transit_days_min, transit_days_max)
    SELECT id, '*', '=', base_minor * 70 / 100, per_kg_minor * 80 / 100, 0, 1 FROM carrier_tariffs WHERE provider_code IN ('tipax','chapar');
INSERT INTO carrier_tariff_zones (tariff_id, origin_province, destination_province, base_minor, per_kg_minor, transit_days_min, transit_days_max)
    SELECT id, '*', '=', base_minor * 80 / 100, NULL, 1, transit_days_max - 1 FROM carrier_tariffs WHERE provider_code = 'post';
