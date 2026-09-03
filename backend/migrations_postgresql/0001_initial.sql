-- 0001_initial
-- Scope: everything required by Flow 1 (Customer: register -> login -> browse
-- -> product -> cart -> checkout -> order) plus the financial primitives that
-- checkout writes into (payments + double-entry ledger) and the cross-cutting
-- tables (idempotency, audit).
--
-- Money: every monetary column is an INTEGER count of currency minor units.
-- No REAL/FLOAT column exists in this schema by design. Application code
-- converts to decimal.Decimal on read (see app/core/money.py).

-- ---------------------------------------------------------------- identity
CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT    NOT NULL,
    email_normalized TEXT   NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    full_name       TEXT    NOT NULL,
    phone           TEXT,
    role            TEXT    NOT NULL DEFAULT 'customer'
                            CHECK (role IN ('customer','employee','supplier','org_admin','admin')),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at      TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    -- Defence in depth: a bare password can never be persisted in this column.
    CHECK (length(password_hash) >= 40 AND POSITION('$' IN password_hash) > 0)
);

CREATE TABLE addresses (
    id           BIGSERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    recipient    TEXT    NOT NULL,
    phone        TEXT    NOT NULL,
    province     TEXT    NOT NULL,
    city         TEXT    NOT NULL,
    postal_code  TEXT,
    line1        TEXT    NOT NULL,
    is_default   INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    created_at   TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_addresses_user ON addresses(user_id);

-- ----------------------------------------------------------------- catalog
CREATE TABLE categories (
    id         BIGSERIAL PRIMARY KEY,
    slug       TEXT    NOT NULL UNIQUE,
    name_fa    TEXT    NOT NULL,
    parent_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE products (
    id               BIGSERIAL PRIMARY KEY,
    slug             TEXT    NOT NULL UNIQUE,
    sku              TEXT    NOT NULL UNIQUE,
    title_fa         TEXT    NOT NULL,
    description_fa   TEXT    NOT NULL DEFAULT '',
    brand_fa         TEXT    NOT NULL DEFAULT '',
    category_id      INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    base_price_minor INTEGER NOT NULL CHECK (base_price_minor >= 0),
    currency         TEXT    NOT NULL DEFAULT 'IRR',
    image_emoji      TEXT    NOT NULL DEFAULT '📦',
    rating_x10       INTEGER NOT NULL DEFAULT 0 CHECK (rating_x10 BETWEEN 0 AND 50),
    is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at       TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_active ON products(is_active);

CREATE TABLE inventory (
    product_id         INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    quantity_available INTEGER NOT NULL CHECK (quantity_available >= 0),
    quantity_reserved  INTEGER NOT NULL DEFAULT 0 CHECK (quantity_reserved >= 0),
    updated_at         TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

-- -------------------------------------------------------------------- cart
CREATE TABLE carts (
    id         BIGSERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','ordered','abandoned')),
    created_at TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    updated_at TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
-- At most one active cart per user.
CREATE UNIQUE INDEX idx_carts_one_active ON carts(user_id) WHERE status = 'active';

CREATE TABLE cart_items (
    id               BIGSERIAL PRIMARY KEY,
    cart_id          INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id       INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    added_at         TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    UNIQUE (cart_id, product_id)
);
CREATE INDEX idx_cart_items_cart ON cart_items(cart_id);

-- ------------------------------------------------------------------ orders
CREATE TABLE orders (
    id                    BIGSERIAL PRIMARY KEY,
    order_number          TEXT    NOT NULL UNIQUE,
    user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status                TEXT    NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','paid','fulfilling','delivered','cancelled','refunded')),
    subtotal_minor        INTEGER NOT NULL CHECK (subtotal_minor >= 0),
    shipping_fee_minor    INTEGER NOT NULL DEFAULT 0 CHECK (shipping_fee_minor >= 0),
    total_minor           INTEGER NOT NULL CHECK (total_minor >= 0),
    currency              TEXT    NOT NULL DEFAULT 'IRR',
    recipient_name        TEXT    NOT NULL,
    recipient_phone       TEXT    NOT NULL,
    shipping_province     TEXT    NOT NULL,
    shipping_city         TEXT    NOT NULL,
    shipping_line1        TEXT    NOT NULL,
    shipping_postal_code  TEXT,
    placed_at             TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    CHECK (total_minor = subtotal_minor + shipping_fee_minor)
);
CREATE INDEX idx_orders_user ON orders(user_id, placed_at DESC);

CREATE TABLE order_items (
    id               BIGSERIAL PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id       INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    -- Snapshot: an order line must not change when the catalog changes.
    title_fa         TEXT    NOT NULL,
    sku              TEXT    NOT NULL,
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    line_total_minor INTEGER NOT NULL CHECK (line_total_minor >= 0),
    CHECK (line_total_minor = unit_price_minor * quantity)
);
CREATE INDEX idx_order_items_order ON order_items(order_id);

-- ---------------------------------------------------------------- payments
CREATE TABLE payments (
    id            BIGSERIAL PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    provider      TEXT    NOT NULL,
    provider_ref  TEXT    NOT NULL,
    method        TEXT    NOT NULL DEFAULT 'card' CHECK (method IN ('card','cash','credit','split')),
    amount_minor  INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency      TEXT    NOT NULL DEFAULT 'IRR',
    status        TEXT    NOT NULL CHECK (status IN ('authorized','captured','failed','refunded')),
    created_at    TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    UNIQUE (provider, provider_ref)
);
CREATE INDEX idx_payments_order ON payments(order_id);

-- ------------------------------------------------------- double-entry ledger
CREATE TABLE ledger_accounts (
    id       BIGSERIAL PRIMARY KEY,
    code     TEXT    NOT NULL UNIQUE,
    name_fa  TEXT    NOT NULL,
    type     TEXT    NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense')),
    currency TEXT    NOT NULL DEFAULT 'IRR'
);

CREATE TABLE ledger_transactions (
    id          BIGSERIAL PRIMARY KEY,
    reference   TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);

CREATE TABLE ledger_entries (
    id             BIGSERIAL PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES ledger_transactions(id) ON DELETE RESTRICT,
    account_id     INTEGER NOT NULL REFERENCES ledger_accounts(id) ON DELETE RESTRICT,
    direction      TEXT    NOT NULL CHECK (direction IN ('debit','credit')),
    amount_minor   INTEGER NOT NULL CHECK (amount_minor > 0),
    currency       TEXT    NOT NULL DEFAULT 'IRR',
    created_at     TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_ledger_entries_tx ON ledger_entries(transaction_id);
CREATE INDEX idx_ledger_entries_account ON ledger_entries(account_id);

-- The ledger is append-only. These triggers make mutation impossible at the
-- storage layer, not merely discouraged in application code.
CREATE OR REPLACE FUNCTION ledger_entries_no_update_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger_entries is append-only: UPDATE is forbidden' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_entries_no_update
BEFORE UPDATE ON ledger_entries
FOR EACH ROW EXECUTE PROCEDURE ledger_entries_no_update_fn();

CREATE OR REPLACE FUNCTION ledger_entries_no_delete_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger_entries is append-only: DELETE is forbidden' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_entries_no_delete
BEFORE DELETE ON ledger_entries
FOR EACH ROW EXECUTE PROCEDURE ledger_entries_no_delete_fn();

CREATE OR REPLACE FUNCTION ledger_transactions_no_update_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger_transactions is append-only: UPDATE is forbidden' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_transactions_no_update
BEFORE UPDATE ON ledger_transactions
FOR EACH ROW EXECUTE PROCEDURE ledger_transactions_no_update_fn();

CREATE OR REPLACE FUNCTION ledger_transactions_no_delete_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger_transactions is append-only: DELETE is forbidden' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_transactions_no_delete
BEFORE DELETE ON ledger_transactions
FOR EACH ROW EXECUTE PROCEDURE ledger_transactions_no_delete_fn();

-- ------------------------------------------------------------- idempotency
CREATE TABLE idempotency_keys (
    id            BIGSERIAL PRIMARY KEY,
    key           TEXT    NOT NULL,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint      TEXT    NOT NULL,
    request_hash  TEXT    NOT NULL,
    status_code   INTEGER NOT NULL,
    response_json TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    UNIQUE (key, user_id, endpoint)
);

-- -------------------------------------------------------------- audit trail
CREATE TABLE audit_logs (
    id            BIGSERIAL PRIMARY KEY,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action        TEXT    NOT NULL,
    entity_type   TEXT    NOT NULL,
    entity_id     TEXT,
    metadata_json TEXT    NOT NULL DEFAULT '{}',
    ip_address    TEXT,
    created_at    TEXT    NOT NULL DEFAULT TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
);
CREATE INDEX idx_audit_actor ON audit_logs(actor_user_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_logs(action, created_at DESC);

CREATE OR REPLACE FUNCTION audit_logs_no_update_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: UPDATE is forbidden' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_no_update
BEFORE UPDATE ON audit_logs
FOR EACH ROW EXECUTE PROCEDURE audit_logs_no_update_fn();

CREATE OR REPLACE FUNCTION audit_logs_no_delete_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: DELETE is forbidden' USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_no_delete
BEFORE DELETE ON audit_logs
FOR EACH ROW EXECUTE PROCEDURE audit_logs_no_delete_fn();
