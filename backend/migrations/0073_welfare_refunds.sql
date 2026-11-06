-- Refunds give the welfare share back to the employee's welfare wallet (in proportion); the bank refunds the rest.
ALTER TABLE order_return_requests ADD COLUMN welfare_restored_minor INTEGER NOT NULL DEFAULT 0 CHECK (welfare_restored_minor >= 0);
