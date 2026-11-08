-- Graduated credit (the Faire / Udaan lesson): a new buyer — typically a contracted shop — starts at a fraction of
-- the signed limit and earns the next step with every two on-time paid statements; a late or overdue statement drops
-- it back to the start. The signed limit itself stays immutable; only the share usable today moves.
ALTER TABLE credit_contracts ADD COLUMN ramp_enabled INTEGER NOT NULL DEFAULT 0 CHECK (ramp_enabled IN (0, 1));
ALTER TABLE credit_contracts ADD COLUMN ramp_start_pct INTEGER NOT NULL DEFAULT 25 CHECK (ramp_start_pct IN (25, 50, 75, 100));
