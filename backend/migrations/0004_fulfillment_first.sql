-- 0004_fulfillment_first
--
-- Phase 3 Repair: Fulfillment-First Checkout Architecture
--
-- Changes:
--   1. routing_exceptions — proper table for unroutable items (FK to orders, not
--      to fulfillment_orders which may not exist when routing fails pre-payment).
--   2. payment_intents.fulfillment_plan_json — stores the pre-payment routing
--      plan so _complete_attempt can create FOs from it and _fail_attempt can
--      release the reserved supplier stock.
--
-- Both additions are purely additive; no existing row or column is touched.

-- ================================================================ ROUTING EXCEPTIONS
-- Records items that could not be routed to any supplier.
-- Tied to the customer ORDER (which always exists) and optionally to the
-- order item.  Never uses a fake fulfillment_order FK.
CREATE TABLE IF NOT EXISTS routing_exceptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    order_item_id   INTEGER          REFERENCES order_items(id) ON DELETE SET NULL,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    policy_type     TEXT    NOT NULL DEFAULT '',
    reason          TEXT    NOT NULL DEFAULT '',
    candidates_json TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_routing_exceptions_order ON routing_exceptions(order_id);

-- ================================================================ PAYMENT INTENTS
-- Add fulfillment plan column; NULL for pre-Phase-3 rows.
ALTER TABLE payment_intents ADD COLUMN fulfillment_plan_json TEXT;
