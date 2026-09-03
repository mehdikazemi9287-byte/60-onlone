-- 0007_product_logistics_profiles
--
-- Phase 5 supplement: structured product logistics profiles.
--
-- PURELY ADDITIVE. No existing table is dropped, renamed, or has a column
-- removed.  Existing rows all default to 'standard' (safe for all carriers).
--
-- WHY: The previous logistics_service contained a TODO comment
-- "Future: cold_chain detection from product category".  Inferring serious
-- logistics constraints from human-readable category names is unreliable and
-- unextensible.  This migration adds a first-class logistics profile to the
-- product master record.
--
-- PROFILE VALUES (extensible — add new values without a schema change):
--   standard            Default. Works with any capable carrier.
--   local_only          Must not be shipped intercity (e.g. fresh local produce,
--                       glass, easily-damaged regionally-warehoused goods).
--   perishable          Short shelf life; carrier must have cold_chain capability
--                       OR deliver same-day (max_delivery_hours enforced).
--   cold_chain_required Requires a refrigerated carrier at all times.
--   fragile             Carrier must handle with care (capability: fragile).
--   bulky               Large/heavy item; carrier must support bulky capability.
--
-- CARRIER CAPABILITY MATCHING (enforced in logistics_service):
--   cold_chain_required → carrier capabilities must include 'cold_chain'
--   perishable          → carrier capabilities must include 'cold_chain' OR
--                          carrier must cover same city (local route)
--   local_only          → carrier must NOT be intercity-only; must cover origin city
--   bulky               → carrier capabilities must include 'bulky'
--   fragile             → carrier capabilities must include 'fragile' (or 'standard'
--                          carriers are allowed when no fragile-specific cap exists)
--   standard            → any carrier with matching geographic coverage is eligible

-- ================================================================ PRODUCTS
-- Add logistics_profile column. NULL treated as 'standard' for safety.
ALTER TABLE products ADD COLUMN logistics_profile TEXT NOT NULL DEFAULT 'standard'
    CHECK (logistics_profile IN (
        'standard',
        'local_only',
        'perishable',
        'cold_chain_required',
        'fragile',
        'bulky'
    ));

-- Optional: maximum delivery time in hours (NULL = no constraint).
-- Used for perishable products where cold_chain is unavailable but same-city
-- fast delivery is acceptable.
ALTER TABLE products ADD COLUMN max_delivery_hours INTEGER;

-- ================================================================ CARRIER CONFIGS
-- Extend carrier_configs capabilities to include explicit flags for
-- cold_chain, fragile, and bulky in addition to local/intercity.
-- The capabilities column was already TEXT (comma-separated).
-- New valid capability tokens: cold_chain, fragile, bulky, intercity, local.
-- Existing rows remain valid; 'local' is the legacy default capability.

-- ================================================================ SEED PROFILES
-- Set structured logistics profiles for the demo product catalogue.
-- These are idempotent UPDATEs — safe to re-run.

-- A4 paper / office carton: standard intercity-eligible product.
UPDATE products SET logistics_profile = 'standard'
WHERE slug = 'office-paper-a4-carton';

-- Laptop / electronics: standard but fragile.
UPDATE products SET logistics_profile = 'fragile'
WHERE slug IN ('laptop-business-15', 'laptop-ultrabook', 'laptop-gaming');

-- Mobile phone: standard (small parcel, non-perishable).
UPDATE products SET logistics_profile = 'standard'
WHERE slug IN ('smartphone-midrange', 'smartphone-flagship', 'mobile-budget');

-- Perishable / dairy / fresh foods (if seeded):
UPDATE products SET logistics_profile = 'perishable'
WHERE slug LIKE '%fresh%' OR slug LIKE '%dairy%' OR slug LIKE '%yogurt%';

-- Heavy / bulky items:
UPDATE products SET logistics_profile = 'bulky'
WHERE slug LIKE '%furniture%' OR slug LIKE '%sofa%' OR slug LIKE '%desk%';

-- Cold-chain required (e.g. frozen, pharmaceutical):
UPDATE products SET logistics_profile = 'cold_chain_required'
WHERE slug LIKE '%frozen%' OR slug LIKE '%pharma%' OR slug LIKE '%vaccine%';

-- ================================================================ CARRIER CAPABILITY EXTENSIONS
-- Add cold_chain capability to mock carriers that need it.
-- The capabilities column is TEXT (comma-separated).
-- These are idempotent no-ops if the carrier already has the capability.

-- Tehran local mock carrier: upgrade to include cold_chain so it can handle
-- perishable products (which require cold_chain per BLOCKER 4 profile rules).
UPDATE carrier_configs
SET capabilities = 'local,cold_chain'
WHERE provider_code = 'mock' AND province = 'تهران'
  AND capabilities NOT LIKE '%cold_chain%';

-- Isfahan mock carrier: ensure cold_chain is present (idempotent).
UPDATE carrier_configs
SET capabilities = 'local,cold_chain'
WHERE provider_code = 'mock' AND province = 'اصفهان'
  AND capabilities NOT LIKE '%cold_chain%';
