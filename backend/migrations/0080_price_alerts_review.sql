-- Price alerts review fixes: SMS cost control (billed parts, buyer/seller budgets) and the seller SMS opt-out.
ALTER TABLE price_alert_sms ADD COLUMN parts INTEGER NOT NULL DEFAULT 1;
ALTER TABLE price_alert_sms ADD COLUMN kind TEXT NOT NULL DEFAULT 'buyer';
CREATE INDEX IF NOT EXISTS ix_price_alert_sms_user_day ON price_alert_sms(user_id, day, kind);

-- Per-user alert settings. seller_sms = 0: the seller still gets in-site alerts but no SMS.
CREATE TABLE IF NOT EXISTS price_alert_user_prefs (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    seller_sms INTEGER NOT NULL DEFAULT 1 CHECK (seller_sms IN (0, 1)),
    updated_at TEXT    NOT NULL
);
