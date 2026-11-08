CREATE TABLE cms_pages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 slug TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('page','article','homepage')),
 draft_revision_id INTEGER,
 published_revision_id INTEGER,
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE cms_revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 page_id INTEGER NOT NULL REFERENCES cms_pages(id),
 content_json TEXT NOT NULL,
 content_hash TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 source_revision_id INTEGER REFERENCES cms_revisions(id)
);
CREATE INDEX cms_revisions_page ON cms_revisions(page_id,id);
CREATE TABLE cms_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 page_id INTEGER NOT NULL REFERENCES cms_pages(id),
 revision_id INTEGER NOT NULL REFERENCES cms_revisions(id),
 actor_user_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE TRIGGER cms_revisions_no_update BEFORE UPDATE ON cms_revisions BEGIN SELECT RAISE(ABORT,'immutable history'); END;
CREATE TRIGGER cms_revisions_no_delete BEFORE DELETE ON cms_revisions BEGIN SELECT RAISE(ABORT,'immutable history'); END;

CREATE TRIGGER cms_events_no_update BEFORE UPDATE ON cms_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
CREATE TRIGGER cms_events_no_delete BEFORE DELETE ON cms_events BEGIN SELECT RAISE(ABORT,'immutable history'); END;
