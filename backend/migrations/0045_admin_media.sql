CREATE TABLE media_assets (
 id TEXT PRIMARY KEY,
 checksum TEXT NOT NULL UNIQUE,
 original_checksum TEXT NOT NULL,
 filename TEXT NOT NULL,
 original_name TEXT NOT NULL,
 mime_type TEXT NOT NULL,
 width INTEGER NOT NULL,
 height INTEGER NOT NULL,
 size_bytes INTEGER NOT NULL,
 alt_text TEXT NOT NULL,
 source_reference TEXT NOT NULL,
 thumbnail_data_uri TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'private' CHECK(status IN ('private','public','archived')),
 row_version INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE media_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 asset_id TEXT NOT NULL REFERENCES media_assets(id),
 actor_user_id INTEGER NOT NULL REFERENCES users(id),
 master_product_id INTEGER REFERENCES master_products(id),
 action TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE TRIGGER media_events_no_update BEFORE UPDATE ON media_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
CREATE TRIGGER media_events_no_delete BEFORE DELETE ON media_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
