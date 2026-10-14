-- Preserve destination allocation for new orders; historical rows remain untouched/null.
ALTER TABLE purchase_orders ADD COLUMN destinations_json_snapshot TEXT;
