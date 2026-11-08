-- Last state seen by the partner-webhook bridge, so order.status_changed / offer.stock_low fire on change only.
CREATE TABLE IF NOT EXISTS partner_bridge_state (
    kind   TEXT NOT NULL CHECK (kind IN ('order', 'fulfillment', 'stock')),
    ref_id INTEGER NOT NULL,
    value  TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
-- Baseline existing rows: deploying this must not replay history as a burst of events.
INSERT INTO partner_bridge_state (kind, ref_id, value) SELECT 'order', id, status FROM orders;
INSERT INTO partner_bridge_state (kind, ref_id, value) SELECT 'fulfillment', id, status FROM fulfillment_orders;
INSERT INTO partner_bridge_state (kind, ref_id, value)
    SELECT 'stock', id, CASE WHEN stock_quantity <= 3 THEN 'low' ELSE 'ok' END FROM seller_offers;
