-- Commerce operations: pack administration audit, stock alerts + notifications, retail returns,
-- employee benefit programs. Additive only.

CREATE TABLE pack_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id INTEGER NOT NULL REFERENCES packs(id),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL CHECK (action IN ('created', 'updated', 'published', 'archived', 'unpublished')),
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TRIGGER pack_events_no_update BEFORE UPDATE ON pack_events BEGIN SELECT RAISE(ABORT, 'pack audit is append only'); END;
CREATE TRIGGER pack_events_no_delete BEFORE DELETE ON pack_events BEGIN SELECT RAISE(ABORT, 'pack audit is append only'); END;

CREATE TABLE stock_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'notified', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    notified_at TEXT,
    UNIQUE (user_id, product_id)
);
CREATE INDEX idx_stock_alerts_product ON stock_alerts(product_id, status);

CREATE TABLE user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    read_at TEXT
);
CREATE INDEX idx_user_notifications_user ON user_notifications(user_id, id);

-- Retail returns: requested → approved | rejected → received → refund_pending → refunded (refund is a record
-- of what finance paid back with its bank reference; this system moves no money).
CREATE TABLE order_return_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    items_json TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 3 AND 2000),
    status TEXT NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'approved', 'rejected', 'received', 'refund_pending', 'refunded', 'cancelled')),
    refund_amount_minor INTEGER CHECK (refund_amount_minor IS NULL OR refund_amount_minor > 0),
    refund_reference TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_order_returns_order ON order_return_requests(order_id);
CREATE TABLE order_return_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id INTEGER NOT NULL REFERENCES order_return_requests(id),
    actor_user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TRIGGER order_return_events_no_update BEFORE UPDATE ON order_return_events BEGIN SELECT RAISE(ABORT, 'return audit is append only'); END;
CREATE TRIGGER order_return_events_no_delete BEFORE DELETE ON order_return_events BEGIN SELECT RAISE(ABORT, 'return audit is append only'); END;

-- Employee benefits: HR offers a fixed pack, a choice between packs, or credit (existing credit allocations).
CREATE TABLE benefit_programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 3 AND 200),
    mode TEXT NOT NULL CHECK (mode IN ('fixed_pack', 'pack_choice', 'credit')),
    pack_ids_json TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    closes_at TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'open', 'closed')),
    purchase_request_id INTEGER REFERENCES purchase_requests(id),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE benefit_selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES benefit_programs(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    pack_id INTEGER REFERENCES packs(id),
    status TEXT NOT NULL DEFAULT 'selected' CHECK (status IN ('selected', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (program_id, user_id)
);

-- Offer provenance always follows its supplier, whatever code path inserted it (API, CSV import, bulk import).
CREATE TRIGGER seller_offers_provenance_insert AFTER INSERT ON seller_offers
BEGIN UPDATE seller_offers SET provenance = (SELECT provenance FROM suppliers WHERE id = NEW.supplier_id) WHERE id = NEW.id; END;
CREATE TRIGGER seller_offers_provenance_supplier AFTER UPDATE OF supplier_id, provenance ON seller_offers
WHEN NEW.provenance IS NOT (SELECT provenance FROM suppliers WHERE id = NEW.supplier_id)
BEGIN UPDATE seller_offers SET provenance = (SELECT provenance FROM suppliers WHERE id = NEW.supplier_id) WHERE id = NEW.id; END;
CREATE TRIGGER suppliers_provenance_offers AFTER UPDATE OF provenance ON suppliers
BEGIN UPDATE seller_offers SET provenance = NEW.provenance WHERE supplier_id = NEW.id; END;
