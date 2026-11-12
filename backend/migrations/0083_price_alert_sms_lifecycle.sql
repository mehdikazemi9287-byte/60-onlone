-- 0083 price alert SMS lifecycle (audit 2026-11-10: SO-02, SO-03, N3). Data-preserving; no row is removed.
--
-- price_alert_events.sms_status gains 'reserved' (picked for a digest, not yet sent), 'unknown' (provider outcome
-- not known: never retried blindly) and 'canceled' (watch paused/deleted or SMS turned off before dispatch);
-- sms_reason records why. price_alert_sms.status gains 'reserved' and 'unknown'; attempt_at / provider_ref /
-- finished_at record the provider call. SQLite cannot change a CHECK constraint in place, so both tables are
-- rebuilt in one transaction (same pattern as 0021); nothing references them by foreign key.

COMMIT;
PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE price_alert_events_v83 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    watch_id    INTEGER REFERENCES price_watches(id) ON DELETE SET NULL,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    level       TEXT    NOT NULL,
    alert_type  TEXT    NOT NULL,
    dedupe_key  TEXT    NOT NULL UNIQUE,
    sms_text    TEXT    NOT NULL,
    sms_status  TEXT    NOT NULL DEFAULT 'none'
                CHECK (sms_status IN ('none', 'pending', 'reserved', 'sent', 'failed', 'unknown', 'canceled',
                                      'skipped_item', 'skipped_cap', 'unavailable')),
    sms_id      INTEGER,
    created_at  TEXT    NOT NULL,
    day         TEXT    NOT NULL,
    sms_reason  TEXT
);
INSERT INTO price_alert_events_v83 (id, user_id, product_id, watch_id, supplier_id, level, alert_type, dedupe_key,
                                    sms_text, sms_status, sms_id, created_at, day)
SELECT id, user_id, product_id, watch_id, supplier_id, level, alert_type, dedupe_key,
       sms_text, sms_status, sms_id, created_at, day FROM price_alert_events;
DROP TABLE price_alert_events;
ALTER TABLE price_alert_events_v83 RENAME TO price_alert_events;
CREATE INDEX IF NOT EXISTS ix_price_alert_events_user ON price_alert_events(user_id, sms_status, day);
CREATE INDEX IF NOT EXISTS ix_price_alert_events_supplier ON price_alert_events(supplier_id, created_at);
CREATE INDEX IF NOT EXISTS ix_price_alert_events_watch ON price_alert_events(watch_id, sms_status);
CREATE INDEX IF NOT EXISTS ix_price_alert_events_sms ON price_alert_events(sms_id);

CREATE TABLE price_alert_sms_v83 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_hour     TEXT    NOT NULL,
    day          TEXT    NOT NULL,
    item_count   INTEGER NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('reserved', 'sending', 'sent', 'failed', 'unknown')),
    created_at   TEXT    NOT NULL,
    parts        INTEGER NOT NULL DEFAULT 1,
    kind         TEXT    NOT NULL DEFAULT 'buyer',
    attempt_at   TEXT,
    provider_ref TEXT,
    finished_at  TEXT,
    UNIQUE (user_id, run_hour)
);
INSERT INTO price_alert_sms_v83 (id, user_id, run_hour, day, item_count, status, created_at, parts, kind)
SELECT id, user_id, run_hour, day, item_count, status, created_at, parts, kind FROM price_alert_sms;
DROP TABLE price_alert_sms;
ALTER TABLE price_alert_sms_v83 RENAME TO price_alert_sms;
CREATE INDEX IF NOT EXISTS ix_price_alert_sms_day ON price_alert_sms(day, status);
CREATE INDEX IF NOT EXISTS ix_price_alert_sms_user_day ON price_alert_sms(user_id, day, kind);

COMMIT;
PRAGMA foreign_keys = ON;
BEGIN;
