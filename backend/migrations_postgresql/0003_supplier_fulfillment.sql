-- 0003_supplier_fulfillment
--
-- Phase 3: Supplier Network + Local Smart Fulfillment + Distributed Virtual Store
--
-- Adds the entire supplier/fulfillment domain on top of the existing Phase 1+2
-- schema. This migration is PURELY ADDITIVE. No existing table is dropped,
-- renamed or has a column removed. Every Flow 1 and Flow 2 row keeps working.
--
-- Money: integer minor units throughout. No REAL/FLOAT column.
-- Geographic routing: city/province-based for MVP. Columns exist for
-- lat/lon so coordinate-based routing can be layered in later without a
-- schema change.

-- ================================================================ SUPPLIERS
CREATE TABLE suppliers (
    id                   BIGSERIAL PRIMARY KEY,
    legal_name           TEXT    NOT NULL,
    display_name         TEXT    NOT NULL,
    -- شناسه ملی (10-digit for individuals) or company registration number
    national_id          TEXT    NOT NULL UNIQUE,
    supplier_type        TEXT    NOT NULL DEFAULT 'retailer'
                                 CHECK (supplier_type IN (
                                     'retailer','wholesaler','producer',
                                     'distributor','local_shop')),
    status               TEXT    NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','active','suspended','inactive')),
    phone                TEXT,
    email                TEXT,
    -- Settlement/billing info (snapshot; actual settlement is a later phase)
    bank_name            TEXT,
    bank_account         TEXT,
    sheba                TEXT,
    -- Platform rating (0–50, displayed as x/5 stars, like products)
    rating_x10           INTEGER NOT NULL DEFAULT 0 CHECK (rating_x10 BETWEEN 0 AND 50),
    -- Supplier-level user login (optional; set by admin when portal access is needed)
    user_id              INTEGER REFERENCES users(id) ON DELETE SET NULL,
    notes                TEXT,
    created_at           TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at           TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_suppliers_status  ON suppliers(status);
CREATE INDEX idx_suppliers_type    ON suppliers(supplier_type);
CREATE INDEX idx_suppliers_user    ON suppliers(user_id);

-- =========================================================== SUPPLIER LOCATIONS
CREATE TABLE supplier_locations (
    id                     BIGSERIAL PRIMARY KEY,
    supplier_id            INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    province               TEXT    NOT NULL,
    city                   TEXT    NOT NULL,
    district               TEXT,
    address                TEXT,
    -- Optional; kept NULL until geospatial routing is added
    latitude               TEXT,
    longitude              TEXT,
    status                 TEXT    NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('active','inactive')),
    -- Delivery capabilities (each independently toggleable)
    can_pickup             INTEGER NOT NULL DEFAULT 0 CHECK (can_pickup IN (0,1)),
    can_local_delivery     INTEGER NOT NULL DEFAULT 0 CHECK (can_local_delivery IN (0,1)),
    can_intercity_shipping INTEGER NOT NULL DEFAULT 0 CHECK (can_intercity_shipping IN (0,1)),
    -- Approximate radius in km for local-delivery (informational for MVP)
    service_radius_km      INTEGER,
    -- Operating schedule (free-form JSON; e.g. {"sat-wed":"09:00-21:00","thu":"09:00-18:00"})
    operating_hours_json   TEXT,
    -- Average preparation time in minutes
    prep_time_minutes      INTEGER NOT NULL DEFAULT 60,
    created_at             TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at             TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_supplier_locations_supplier ON supplier_locations(supplier_id);
CREATE INDEX idx_supplier_locations_city     ON supplier_locations(province, city);
CREATE INDEX idx_supplier_locations_status   ON supplier_locations(status);

-- ================================================================ FULFILLMENT POLICIES
-- Attached to products (or categories). Backend is authoritative; frontend never
-- chooses a policy. Policies influence the routing engine's candidate filter.
CREATE TABLE fulfillment_policies (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT    NOT NULL UNIQUE,   -- e.g. 'LOCAL_ONLY'
    label_fa        TEXT    NOT NULL,          -- e.g. 'فقط محلی'
    description_fa  TEXT    NOT NULL DEFAULT '',
    -- Controls routing: local_only | local_preferred | national_shipping | pickup_only
    policy_type     TEXT    NOT NULL
                            CHECK (policy_type IN (
                                'LOCAL_ONLY','LOCAL_PREFERRED',
                                'NATIONAL_SHIPPING','PICKUP_ONLY')),
    -- Maximum transit provinces; NULL means no restriction
    max_provinces   INTEGER,
    is_default      INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    created_at      TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
-- At most one default policy
CREATE UNIQUE INDEX idx_fulfillment_policies_default ON fulfillment_policies(is_default) WHERE is_default = 1;

-- Link products to a fulfillment policy (nullable → falls back to category → then DEFAULT policy)
ALTER TABLE products ADD COLUMN fulfillment_policy_id INTEGER REFERENCES fulfillment_policies(id);

-- ================================================================ SELLER OFFERS
-- A SellerOffer joins a canonical product to a supplier location.
-- Many suppliers may offer the same product; the routing engine selects the best.
CREATE TABLE seller_offers (
    id                      BIGSERIAL PRIMARY KEY,
    product_id              INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    supplier_location_id    INTEGER NOT NULL REFERENCES supplier_locations(id) ON DELETE RESTRICT,
    -- Supplier's own internal SKU (may differ from canonical SKU)
    supplier_sku            TEXT,
    -- Selling price charged to the customer (authoritative; NOT from browser)
    selling_price_minor     INTEGER NOT NULL CHECK (selling_price_minor >= 0),
    -- Cost price (what platform pays supplier). May be NULL if not disclosed.
    cost_price_minor        INTEGER          CHECK (cost_price_minor IS NULL OR cost_price_minor >= 0),
    -- Gross supplier payable snapshot (FOUNDATION ONLY; not settled yet)
    -- This is snapshotted per fulfillment order line, not stored here.
    -- stock
    stock_quantity          INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    -- stock reserved (race-safe via BEGIN IMMEDIATE, same pattern as inventory)
    stock_reserved          INTEGER NOT NULL DEFAULT 0 CHECK (stock_reserved >= 0),
    status                  TEXT    NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active','inactive','out_of_stock')),
    min_order_quantity      INTEGER NOT NULL DEFAULT 1,
    -- Which fulfillment modes this offer supports
    fulfillment_type        TEXT    NOT NULL DEFAULT 'delivery'
                                    CHECK (fulfillment_type IN ('delivery','pickup','both')),
    -- Average preparation time for this specific offer (overrides location default when set)
    prep_time_minutes       INTEGER,
    -- Estimated shipping days for intercity (informational)
    shipping_days           INTEGER,
    created_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at              TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    -- One active offer per product per supplier location
    UNIQUE (product_id, supplier_id, supplier_location_id)
);
CREATE INDEX idx_seller_offers_product    ON seller_offers(product_id);
CREATE INDEX idx_seller_offers_supplier   ON seller_offers(supplier_id);
CREATE INDEX idx_seller_offers_location   ON seller_offers(supplier_location_id);
CREATE INDEX idx_seller_offers_status     ON seller_offers(status);

-- ================================================================ FULFILLMENT ORDERS
-- Created after a customer Order is paid. One customer Order may generate
-- N FulfillmentOrders (one per supplier). The customer Order total is immutable.
CREATE TABLE fulfillment_orders (
    id                    BIGSERIAL PRIMARY KEY,
    -- Source customer order
    order_id              INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    -- Assigned supplier
    supplier_id           INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    supplier_location_id  INTEGER NOT NULL REFERENCES supplier_locations(id) ON DELETE RESTRICT,
    -- Fulfillment state machine
    status                TEXT    NOT NULL DEFAULT 'pending_assignment'
                                  CHECK (status IN (
                                      'pending_assignment','assigned','accepted',
                                      'preparing','ready','dispatched',
                                      'delivered','rejected','cancelled','failed')),
    -- Routing metadata (immutable snapshot; never recomputed)
    routing_score         INTEGER,       -- higher is better
    routing_reason_json   TEXT,          -- JSON: {"geo":30,"price":20,...,"total":50}
    routing_candidates_json TEXT,        -- JSON array of candidates considered
    fulfillment_type      TEXT    NOT NULL DEFAULT 'delivery'
                                  CHECK (fulfillment_type IN ('delivery','pickup','both')),
    -- Supplier-facing financial snapshot (FOUNDATION ONLY — not settled)
    gross_payable_minor   INTEGER NOT NULL DEFAULT 0,
    -- Timestamps / SLA
    promised_prep_at      TEXT,           -- estimated ready time
    accepted_at           TEXT,
    prepared_at           TEXT,
    dispatched_at         TEXT,
    delivered_at          TEXT,
    -- Rejection / cancellation
    rejection_reason      TEXT,
    cancellation_reason   TEXT,
    -- Rerouting history (JSON array of routing_event objects)
    routing_history_json  TEXT    NOT NULL DEFAULT '[]',
    notes                 TEXT,
    created_at            TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at            TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_fulfillment_orders_order    ON fulfillment_orders(order_id);
CREATE INDEX idx_fulfillment_orders_supplier ON fulfillment_orders(supplier_id);
CREATE INDEX idx_fulfillment_orders_status   ON fulfillment_orders(status);

-- ================================================================ FULFILLMENT ORDER ITEMS
-- Each row tracks one product line within a fulfillment order.
-- Immutable financial snapshot: selling price and cost price at order time.
CREATE TABLE fulfillment_order_items (
    id                     BIGSERIAL PRIMARY KEY,
    fulfillment_order_id   INTEGER NOT NULL REFERENCES fulfillment_orders(id) ON DELETE CASCADE,
    order_item_id          INTEGER NOT NULL REFERENCES order_items(id) ON DELETE RESTRICT,
    seller_offer_id        INTEGER NOT NULL REFERENCES seller_offers(id) ON DELETE RESTRICT,
    product_id             INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    title_fa               TEXT    NOT NULL,
    quantity               INTEGER NOT NULL CHECK (quantity > 0),
    -- Snapshot of prices at order time (never recomputed from current offer price)
    selling_price_minor    INTEGER NOT NULL CHECK (selling_price_minor >= 0),
    cost_price_minor       INTEGER          CHECK (cost_price_minor IS NULL OR cost_price_minor >= 0),
    line_selling_minor     INTEGER NOT NULL CHECK (line_selling_minor >= 0),
    line_cost_minor        INTEGER          CHECK (line_cost_minor IS NULL OR line_cost_minor >= 0),
    created_at             TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    -- One fulfillment item per order_item (no item may be split or doubled)
    UNIQUE (fulfillment_order_id, order_item_id)
);
CREATE INDEX idx_foi_fulfillment_order ON fulfillment_order_items(fulfillment_order_id);
CREATE INDEX idx_foi_order_item        ON fulfillment_order_items(order_item_id);

-- ================================================================ ROUTING AUDIT
-- Immutable audit trail for every routing decision. Append-only; never overwritten.
CREATE TABLE routing_audit (
    id                   BIGSERIAL PRIMARY KEY,
    fulfillment_order_id INTEGER NOT NULL REFERENCES fulfillment_orders(id) ON DELETE CASCADE,
    event_type           TEXT    NOT NULL
                                 CHECK (event_type IN (
                                     'initial_routing','reroute','rejection',
                                     'fallback','manual_override','exception')),
    -- The selected supplier/location (NULL if no valid candidate was found)
    selected_supplier_id          INTEGER REFERENCES suppliers(id),
    selected_supplier_location_id INTEGER REFERENCES supplier_locations(id),
    -- JSON array of all candidates with scores and reasons
    candidates_json      TEXT    NOT NULL DEFAULT '[]',
    -- Reason this routing event happened
    reason               TEXT    NOT NULL DEFAULT '',
    actor_type           TEXT    NOT NULL DEFAULT 'system'
                                 CHECK (actor_type IN ('system','supplier','admin','cron')),
    actor_user_id        INTEGER REFERENCES users(id),
    created_at           TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_routing_audit_fo ON routing_audit(fulfillment_order_id);

-- ================================================================ FULFILLMENT STATE LOG
-- Every state transition is recorded. Append-only.
CREATE TABLE fulfillment_state_log (
    id                   BIGSERIAL PRIMARY KEY,
    fulfillment_order_id INTEGER NOT NULL REFERENCES fulfillment_orders(id) ON DELETE CASCADE,
    from_status          TEXT,
    to_status            TEXT    NOT NULL,
    actor_type           TEXT    NOT NULL DEFAULT 'system'
                                 CHECK (actor_type IN ('system','supplier','admin','customer','cron')),
    actor_user_id        INTEGER REFERENCES users(id),
    reason               TEXT,
    created_at           TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_fsl_fo ON fulfillment_state_log(fulfillment_order_id);

-- ================================================================ SEED: FULFILLMENT POLICIES
-- Inserted as part of the migration so they exist before any offers are created.
INSERT INTO fulfillment_policies (name, label_fa, description_fa, policy_type, is_default) VALUES
    ('LOCAL_ONLY',         'فقط محلی',            'این محصول باید از تأمین‌کننده همشهری تحویل گرفته شود.',        'LOCAL_ONLY',         0),
    ('LOCAL_PREFERRED',    'ترجیحاً محلی',         'ترجیح به تأمین‌کننده همشهری؛ در صورت نبود، ملی.',              'LOCAL_PREFERRED',    0),
    ('NATIONAL_SHIPPING',  'ارسال سراسری',         'هر تأمین‌کننده فعالی می‌تواند این کالا را ارسال کند.',         'NATIONAL_SHIPPING',  0),
    ('PICKUP_ONLY',        'تحویل حضوری',          'مشتری باید حضوری از انبار تأمین‌کننده تحویل بگیرد.',           'PICKUP_ONLY',        0),
    ('NATIONAL_DEFAULT',   'پیش‌فرض سیستم',        'خط‌مشی پیش‌فرض سیستم — ارسال سراسری.',                       'NATIONAL_SHIPPING',  1);
