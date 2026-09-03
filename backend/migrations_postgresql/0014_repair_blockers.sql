-- 0014_repair_blockers
-- Additive repairs for Phase 6 blockers.
-- PURELY ADDITIVE: ALTER TABLE ADD COLUMN only.
-- Migrator wraps in BEGIN;...COMMIT; automatically.

-- Add idempotency_key to exceptions for finance dedup
ALTER TABLE exceptions ADD COLUMN idempotency_key TEXT;
-- Add missing_document_type for three-way match
ALTER TABLE three_way_matches ADD COLUMN line_discrepancy_json TEXT NOT NULL DEFAULT '[]';
