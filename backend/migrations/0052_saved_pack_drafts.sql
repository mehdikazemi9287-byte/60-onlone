-- Private/account or organization-scoped drafts; no catalogue/price/stock backfill.
CREATE TABLE saved_pack_drafts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 created_by INTEGER NOT NULL REFERENCES users(id),
 organization_id INTEGER REFERENCES organizations(id),
 title TEXT NOT NULL,
 draft_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','archived')),
 row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),
 request_key TEXT NOT NULL,
 request_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(created_by,request_key)
);
CREATE INDEX saved_pack_scope ON saved_pack_drafts(created_by,organization_id,status);
