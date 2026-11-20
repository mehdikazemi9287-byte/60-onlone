-- 0084: one active cart per user AND shopping mode (owner decision 2026-11-19: «شخصی | پرسنل سازمان | سازمانی و عمده»).
-- ADDITIVE for data: no row is deleted or rewritten. Every existing cart becomes the user's 'personal' cart
-- through the column default, which is exactly what it was for the user (personal is the default mode).
-- The old unique index (one active cart per user) is replaced by one active cart per (user, mode); no data is lost.
ALTER TABLE carts ADD COLUMN shopping_mode TEXT NOT NULL DEFAULT 'personal'
    CHECK (shopping_mode IN ('personal','staff','org'));

DROP INDEX IF EXISTS idx_carts_one_active;
CREATE UNIQUE INDEX IF NOT EXISTS idx_carts_one_active_mode ON carts(user_id, shopping_mode) WHERE status = 'active';

-- Which mode's cart a payment attempt / order came from. NULL = created before this migration (personal).
ALTER TABLE payment_intents ADD COLUMN shopping_mode TEXT
    CHECK (shopping_mode IS NULL OR shopping_mode IN ('personal','staff','org'));
ALTER TABLE orders ADD COLUMN shopping_mode TEXT
    CHECK (shopping_mode IS NULL OR shopping_mode IN ('personal','staff','org'));
