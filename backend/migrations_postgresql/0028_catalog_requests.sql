CREATE TABLE catalog_publications (
 master_product_id INTEGER PRIMARY KEY REFERENCES master_products(id),
 slug TEXT NOT NULL UNIQUE,
 category_slug TEXT NOT NULL REFERENCES categories(slug),
 verified_price_minor INTEGER CHECK (verified_price_minor IS NULL OR verified_price_minor > 0),
 currency TEXT NOT NULL DEFAULT 'IRR',
 is_visible INTEGER NOT NULL DEFAULT 1 CHECK (is_visible IN (0,1)),
 is_purchasable INTEGER NOT NULL DEFAULT 0 CHECK (is_purchasable=0),
 price_status TEXT NOT NULL DEFAULT 'pending' CHECK (price_status IN ('verified','pending')),
 publication_reason TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX catalog_publications_category ON catalog_publications(category_slug,is_visible);
CREATE TABLE customer_requests (
 id SERIAL PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 organization_id INTEGER REFERENCES organizations(id),
 kind TEXT NOT NULL CHECK(kind IN ('price','procurement','support')),
 subject TEXT NOT NULL,
 message TEXT NOT NULL,
 items_json TEXT NOT NULL DEFAULT '[]',
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','reviewing','answered','closed')),
 response TEXT,
 idempotency_key TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(user_id,idempotency_key)
);
CREATE INDEX customer_requests_owner ON customer_requests(user_id,id);
CREATE TABLE customer_request_events (
 id SERIAL PRIMARY KEY,
 request_id INTEGER NOT NULL REFERENCES customer_requests(id),
 actor_user_id INTEGER NOT NULL REFERENCES users(id),
 status TEXT NOT NULL,
 message TEXT NOT NULL,
 created_at TEXT NOT NULL
);
