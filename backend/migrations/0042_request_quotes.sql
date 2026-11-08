-- Personal inquiry quotes: versioned, time-limited offers answering a customer request. Accepting a valid
-- quote creates ONE order in 'pending' (awaiting payment); no payment, credit or reservation happens here.
CREATE TABLE customer_request_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES customer_requests(id),
    version INTEGER NOT NULL CHECK (version >= 1),
    lines_json TEXT NOT NULL,
    subtotal_minor INTEGER NOT NULL CHECK (subtotal_minor > 0),
    shipping_minor INTEGER NOT NULL DEFAULT 0 CHECK (shipping_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    total_minor INTEGER NOT NULL CHECK (total_minor > 0),
    note TEXT,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'accepted', 'superseded', 'withdrawn')),
    order_id INTEGER UNIQUE REFERENCES orders(id),
    created_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    accepted_at TEXT,
    UNIQUE (request_id, version)
);
