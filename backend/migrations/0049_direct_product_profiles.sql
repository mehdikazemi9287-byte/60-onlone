-- Review-source only: editorial intent, no Offer, price, stock or automatic publication.
CREATE TABLE direct_product_profiles (
 master_product_id INTEGER PRIMARY KEY REFERENCES master_products(id),
 sku TEXT NOT NULL UNIQUE,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('supplier','catalog','manual','other')),
 source_supplier_id INTEGER REFERENCES suppliers(id),
 supply_channel TEXT NOT NULL CHECK(supply_channel IN ('retail','organization','both'))
);
