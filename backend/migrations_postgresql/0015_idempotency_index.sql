-- Migration 0015: DB-level idempotency protection for financial exceptions.
--
-- Adds a partial UNIQUE INDEX on exceptions(idempotency_key) where the key
-- is not null.  This prevents concurrent exception creation from producing
-- duplicate rows for the same logical financial event even if the application-
-- layer check-before-insert races.
--
-- Purely additive — no ALTER of existing columns, no DROP, no data loss.
-- Safe to apply to a populated Phase-5 / Phase-6 database.

CREATE UNIQUE INDEX IF NOT EXISTS idx_exceptions_idempotency_key
    ON exceptions (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
