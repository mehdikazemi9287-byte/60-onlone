-- PostgreSQL twin of migrations/0083_price_alert_sms_lifecycle.sql (hand-written: PostgreSQL changes CHECK
-- constraints in place, no table rebuild). Data-preserving.

DO $$
DECLARE
    cname TEXT;
BEGIN
    FOR cname IN SELECT conname FROM pg_constraint
                 WHERE conrelid = 'price_alert_events'::regclass AND contype = 'c'
                   AND pg_get_constraintdef(oid) LIKE '%sms_status%'
    LOOP
        EXECUTE 'ALTER TABLE price_alert_events DROP CONSTRAINT ' || quote_ident(cname);
    END LOOP;
    FOR cname IN SELECT conname FROM pg_constraint
                 WHERE conrelid = 'price_alert_sms'::regclass AND contype = 'c'
                   AND pg_get_constraintdef(oid) LIKE '%status%'
    LOOP
        EXECUTE 'ALTER TABLE price_alert_sms DROP CONSTRAINT ' || quote_ident(cname);
    END LOOP;
END;
$$;

ALTER TABLE price_alert_events ADD CONSTRAINT price_alert_events_sms_status_check
    CHECK (sms_status IN ('none', 'pending', 'reserved', 'sent', 'failed', 'unknown', 'canceled',
                          'skipped_item', 'skipped_cap', 'unavailable'));
ALTER TABLE price_alert_events ADD COLUMN IF NOT EXISTS sms_reason TEXT;
CREATE INDEX IF NOT EXISTS ix_price_alert_events_watch ON price_alert_events(watch_id, sms_status);
CREATE INDEX IF NOT EXISTS ix_price_alert_events_sms ON price_alert_events(sms_id);

ALTER TABLE price_alert_sms ADD CONSTRAINT price_alert_sms_status_check
    CHECK (status IN ('reserved', 'sending', 'sent', 'failed', 'unknown'));
ALTER TABLE price_alert_sms ADD COLUMN IF NOT EXISTS attempt_at TEXT;
ALTER TABLE price_alert_sms ADD COLUMN IF NOT EXISTS provider_ref TEXT;
ALTER TABLE price_alert_sms ADD COLUMN IF NOT EXISTS finished_at TEXT;
