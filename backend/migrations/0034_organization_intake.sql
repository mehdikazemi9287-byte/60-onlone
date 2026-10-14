-- Source-only SQLite candidate. Reconcile migrations 0029-0033 before release.
-- Intake metadata only: creates no orders, reservations, or financial events.
ALTER TABLE purchase_requests ADD COLUMN substitution_policy TEXT NOT NULL
    DEFAULT 'require_approval' CHECK (substitution_policy IN ('disallow', 'require_approval'));
ALTER TABLE purchase_requests ADD COLUMN destinations_json TEXT NOT NULL DEFAULT '[]';
