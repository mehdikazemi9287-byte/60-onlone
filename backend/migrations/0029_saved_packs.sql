CREATE TABLE saved_packs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL,
 kind TEXT NOT NULL DEFAULT 'custom' CHECK(kind IN ('custom','essentials','gift','seasonal','organization')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX saved_packs_owner ON saved_packs(user_id, id);
CREATE TABLE saved_pack_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pack_id INTEGER NOT NULL REFERENCES saved_packs(id),
 product_id INTEGER NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity >= 1 AND quantity <= 999),
 added_at TEXT NOT NULL,
 UNIQUE(pack_id, product_id)
);
CREATE INDEX saved_pack_items_pack ON saved_pack_items(pack_id);
