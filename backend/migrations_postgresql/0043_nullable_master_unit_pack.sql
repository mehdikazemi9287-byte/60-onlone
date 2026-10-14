ALTER TABLE master_products ALTER COLUMN unit DROP NOT NULL;
ALTER TABLE master_products ALTER COLUMN unit DROP DEFAULT;
ALTER TABLE master_products ALTER COLUMN package_quantity DROP NOT NULL;
ALTER TABLE master_products ALTER COLUMN package_quantity DROP DEFAULT;
