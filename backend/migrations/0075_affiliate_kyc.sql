-- Affiliate payee KYC and programme terms: payouts go only to a sheba whose owner's national code we hold and the
-- admin checked (bank sheba inquiry returns the owner); joining records acceptance of the affiliate terms version.
ALTER TABLE affiliates ADD COLUMN payee_national_id TEXT;
ALTER TABLE affiliates ADD COLUMN terms_version TEXT;
ALTER TABLE affiliates ADD COLUMN terms_accepted_at TEXT;
