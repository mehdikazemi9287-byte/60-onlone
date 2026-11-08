-- PostgreSQL-only fix (no-op on SQLite, where 0045's table rebuild already replaced the check).
-- On PostgreSQL the pre-tax CHECK (total = subtotal + shipping) survived next to the VAT-aware one, so any order
-- with VAT failed. The twin in migrations_postgresql/ drops it by definition.
SELECT 1;
