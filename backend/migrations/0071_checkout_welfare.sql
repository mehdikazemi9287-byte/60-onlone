-- Welfare wallet at checkout. The welfare share is part of cash_minor (total = credit + cash still holds) but is
-- owed by the employee's organization, not charged to the card: card amount = cash_minor - welfare_minor.
ALTER TABLE payment_intents ADD COLUMN welfare_minor INTEGER NOT NULL DEFAULT 0 CHECK (welfare_minor >= 0);
ALTER TABLE payment_intents ADD COLUMN welfare_membership_id INTEGER REFERENCES organization_memberships(id);
ALTER TABLE orders ADD COLUMN welfare_minor INTEGER NOT NULL DEFAULT 0 CHECK (welfare_minor >= 0);
