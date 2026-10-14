-- Marketplace catalog: Product (family) → Variant (master_products) → SKU (products) → Offer (seller_offers)
-- → price tiers. Taxonomy levels, provenance on every commercial row, and editorial packs.
-- Additive only; family/taxonomy rows are derived from real data by catalog_structure_service.

CREATE TABLE product_families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title_fa TEXT NOT NULL,
    brand TEXT,
    category_id INTEGER REFERENCES categories(id),
    provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'draft', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Variants: master_products rows grouped into a family with explicit attributes.
ALTER TABLE master_products ADD COLUMN provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test'));
ALTER TABLE master_products ADD COLUMN family_id INTEGER REFERENCES product_families(id);
ALTER TABLE master_products ADD COLUMN variant_label TEXT;
ALTER TABLE master_products ADD COLUMN attributes_json TEXT;
-- Brandless placeholder concepts (no brand, no source, no image) are not real catalog items.
UPDATE master_products SET provenance = 'demo' WHERE brand IS NULL OR trim(brand) = '';
CREATE INDEX idx_master_products_family ON master_products(family_id);

-- SKUs: storefront products rows; one per sellable variant.
ALTER TABLE products ADD COLUMN provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test'));
UPDATE products SET provenance = 'demo'
 WHERE master_product_id IS NULL OR master_product_id IN (SELECT id FROM master_products WHERE provenance <> 'real');

-- Taxonomy: Department → Category → Subcategory → Product type (categories.parent_id already exists).
ALTER TABLE categories ADD COLUMN level TEXT NOT NULL DEFAULT 'category'
    CHECK (level IN ('department', 'category', 'subcategory', 'product_type'));

-- Offers: marketplace-grade attributes. Provenance follows the supplier.
ALTER TABLE seller_offers ADD COLUMN provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test'));
ALTER TABLE seller_offers ADD COLUMN pricing_mode TEXT NOT NULL DEFAULT 'fixed'
    CHECK (pricing_mode IN ('fixed', 'bulk', 'contract', 'rfq_only', 'out_of_stock', 'unavailable'));
ALTER TABLE seller_offers ADD COLUMN channel TEXT NOT NULL DEFAULT 'both' CHECK (channel IN ('retail', 'organization', 'both'));
ALTER TABLE seller_offers ADD COLUMN max_order_quantity INTEGER CHECK (max_order_quantity IS NULL OR max_order_quantity >= 1);
ALTER TABLE seller_offers ADD COLUMN lead_time_days INTEGER CHECK (lead_time_days IS NULL OR lead_time_days >= 0);
ALTER TABLE seller_offers ADD COLUMN valid_until TEXT;
ALTER TABLE seller_offers ADD COLUMN source_reference TEXT;
UPDATE seller_offers SET provenance = (SELECT s.provenance FROM suppliers s WHERE s.id = seller_offers.supplier_id);

-- Quantity price tiers, per offer and channel (retail / organization, optionally one organization's contract).
CREATE TABLE offer_price_tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER NOT NULL REFERENCES seller_offers(id),
    channel TEXT NOT NULL CHECK (channel IN ('retail', 'organization')),
    organization_id INTEGER REFERENCES organizations(id),
    min_qty INTEGER NOT NULL CHECK (min_qty >= 1),
    max_qty INTEGER CHECK (max_qty IS NULL OR max_qty >= min_qty),
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor > 0),
    confirmed_at TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_offer_price_tiers_offer ON offer_price_tiers(offer_id, channel);

-- Append-only audit of offer changes (price, stock, tiers, mode).
CREATE TABLE offer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER NOT NULL REFERENCES seller_offers(id),
    actor_user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TRIGGER offer_events_no_update BEFORE UPDATE ON offer_events BEGIN SELECT RAISE(ABORT, 'offer audit is append only'); END;
CREATE TRIGGER offer_events_no_delete BEFORE DELETE ON offer_events BEGIN SELECT RAISE(ABORT, 'offer audit is append only'); END;

-- Packs: merchandising built from real catalog variants. Never a product of their own.
CREATE TABLE packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title_fa TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('livelihood', 'occasion', 'theme', 'organizational', 'custom')),
    tier TEXT CHECK (tier IN ('economy', 'standard', 'complete', 'premium', 'executive')),
    occasion TEXT,
    audience TEXT NOT NULL CHECK (audience IN ('household', 'organization', 'employee_gift', 'office')),
    purpose_fa TEXT NOT NULL,
    household_size INTEGER CHECK (household_size IS NULL OR household_size >= 1),
    target_budget_minor INTEGER CHECK (target_budget_minor IS NULL OR target_budget_minor > 0),
    min_order_qty INTEGER NOT NULL DEFAULT 1 CHECK (min_order_qty >= 1),
    lead_time_days INTEGER,
    substitution_policy TEXT NOT NULL DEFAULT 'same_type' CHECK (substitution_policy IN ('none', 'same_type', 'same_type_and_size', 'ask')),
    customizable INTEGER NOT NULL DEFAULT 1 CHECK (customizable IN (0, 1)),
    packaging_fa TEXT,
    description_fa TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    provenance TEXT NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'demo', 'test')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE pack_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id INTEGER NOT NULL REFERENCES packs(id),
    master_product_id INTEGER NOT NULL REFERENCES master_products(id),
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0, 1)),
    substitution_group TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (pack_id, master_product_id)
);
CREATE INDEX idx_pack_items_pack ON pack_items(pack_id);

-- Cart lines are bound to the verified offer they were priced from.
ALTER TABLE cart_items ADD COLUMN offer_id INTEGER REFERENCES seller_offers(id);

-- One supplier-access rule for every endpoint: active supplier_users (owners and operators), plus the
-- legacy suppliers.user_id owner link unless that pair was explicitly managed in supplier_users.
CREATE VIEW supplier_access AS
    SELECT su.user_id, su.supplier_id, su.role FROM supplier_users su WHERE su.status = 'active'
    UNION
    SELECT s.user_id, s.id, 'owner' FROM suppliers s
    WHERE s.user_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM supplier_users x WHERE x.supplier_id = s.id AND x.user_id = s.user_id);

-- Delivery evidence and order documents (files stored content-addressed next to the database).
CREATE TABLE procurement_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    destination_index INTEGER,
    kind TEXT NOT NULL CHECK (kind IN ('delivery_evidence', 'waybill', 'supplier_invoice', 'other')),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
    sha256 TEXT NOT NULL,
    note TEXT,
    uploaded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    uploader_side TEXT NOT NULL CHECK (uploader_side IN ('supplier', 'buyer')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_procurement_documents_po ON procurement_documents(purchase_order_id);
CREATE TRIGGER procurement_documents_no_update BEFORE UPDATE ON procurement_documents BEGIN SELECT RAISE(ABORT, 'documents are append only'); END;
CREATE TRIGGER procurement_documents_no_delete BEFORE DELETE ON procurement_documents BEGIN SELECT RAISE(ABORT, 'documents are append only'); END;
