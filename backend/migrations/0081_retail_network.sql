-- Retail network (شبکهٔ فروشگاه‌های زنجیره‌ای و طرف قرارداد): chains, their sectors, their branches in every
-- province, and per-chain / per-branch contract status. Only branches whose own status AND whose chain's status
-- are 'active' (and whose provenance is 'real') are shown publicly; everything else is visible in the admin panel only.
--
-- Branch rows are business data: they must come from a real source (the chain's own file or the contract) and
-- record it in data_source + source_reference. Nothing here is seeded except the reference lists below.
--
-- A branch may later be linked to a platform supplier location (supplier_location_id) so the existing in-person
-- pickup code and the org-pack allocation engine can serve employees from their nearest contracted branch.

-- 31 provinces. center_lat/center_lng = approximate coordinates of the provincial capital, used only to place
-- the coverage bubble on the overview map; they are not a boundary and not an address.
CREATE TABLE IF NOT EXISTS network_provinces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT    NOT NULL UNIQUE,
    name_fa         TEXT    NOT NULL UNIQUE,
    capital_fa      TEXT    NOT NULL,
    center_lat      REAL    NOT NULL,
    center_lng      REAL    NOT NULL,
    official_code   TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

-- Cities/counties are added when a branch in them is imported (or by admin); official_code is filled only
-- from an authoritative list, never guessed.
CREATE TABLE IF NOT EXISTS network_cities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    province_id     INTEGER NOT NULL REFERENCES network_provinces(id) ON DELETE CASCADE,
    name_fa         TEXT    NOT NULL,
    official_code   TEXT,
    created_at      TEXT    NOT NULL,
    UNIQUE (province_id, name_fa)
);

CREATE TABLE IF NOT EXISTS chain_sectors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT    NOT NULL UNIQUE,
    name_fa         TEXT    NOT NULL UNIQUE,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS retail_chains (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                TEXT    NOT NULL UNIQUE,
    name_fa             TEXT    NOT NULL,
    brand_name          TEXT,
    website             TEXT,
    contract_status     TEXT    NOT NULL DEFAULT 'prospect'
                                CHECK (contract_status IN ('prospect', 'negotiating', 'active', 'paused', 'ended')),
    contract_signed_on  TEXT,
    contract_reference  TEXT,
    owner_user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    supplier_id         INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    provenance          TEXT    NOT NULL DEFAULT 'real' CHECK (provenance IN ('real', 'test')),
    notes               TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_retail_chains_status ON retail_chains(contract_status);

CREATE TABLE IF NOT EXISTS retail_chain_sectors (
    chain_id        INTEGER NOT NULL REFERENCES retail_chains(id) ON DELETE CASCADE,
    sector_id       INTEGER NOT NULL REFERENCES chain_sectors(id) ON DELETE CASCADE,
    PRIMARY KEY (chain_id, sector_id)
);

CREATE TABLE IF NOT EXISTS chain_branches (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id              INTEGER NOT NULL REFERENCES retail_chains(id) ON DELETE CASCADE,
    branch_code           TEXT,
    title                 TEXT,
    province_id           INTEGER NOT NULL REFERENCES network_provinces(id),
    city_id               INTEGER REFERENCES network_cities(id) ON DELETE SET NULL,
    district              TEXT,
    address               TEXT,
    latitude              REAL,
    longitude             REAL,
    phone                 TEXT,
    contract_status       TEXT    NOT NULL DEFAULT 'prospect'
                                  CHECK (contract_status IN ('prospect', 'negotiating', 'active', 'paused', 'ended')),
    supplier_location_id  INTEGER REFERENCES supplier_locations(id) ON DELETE SET NULL,
    data_source           TEXT    NOT NULL CHECK (data_source IN ('chain_file', 'contract', 'chain_website', 'field_visit')),
    source_reference      TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    UNIQUE (chain_id, branch_code)
);
CREATE INDEX IF NOT EXISTS ix_chain_branches_chain ON chain_branches(chain_id, contract_status);
CREATE INDEX IF NOT EXISTS ix_chain_branches_province ON chain_branches(province_id, contract_status);

INSERT INTO network_provinces (slug, name_fa, capital_fa, center_lat, center_lng, sort_order) VALUES
    ('east-azerbaijan', 'آذربایجان شرقی', 'تبریز', 38.08, 46.29, 1),
    ('west-azerbaijan', 'آذربایجان غربی', 'ارومیه', 37.55, 45.07, 2),
    ('ardabil', 'اردبیل', 'اردبیل', 38.25, 48.30, 3),
    ('isfahan', 'اصفهان', 'اصفهان', 32.65, 51.67, 4),
    ('alborz', 'البرز', 'کرج', 35.84, 50.94, 5),
    ('ilam', 'ایلام', 'ایلام', 33.64, 46.42, 6),
    ('bushehr', 'بوشهر', 'بوشهر', 28.97, 50.84, 7),
    ('tehran', 'تهران', 'تهران', 35.69, 51.39, 8),
    ('chaharmahal-bakhtiari', 'چهارمحال و بختیاری', 'شهرکرد', 32.33, 50.86, 9),
    ('south-khorasan', 'خراسان جنوبی', 'بیرجند', 32.87, 59.22, 10),
    ('razavi-khorasan', 'خراسان رضوی', 'مشهد', 36.30, 59.61, 11),
    ('north-khorasan', 'خراسان شمالی', 'بجنورد', 37.47, 57.33, 12),
    ('khuzestan', 'خوزستان', 'اهواز', 31.32, 48.67, 13),
    ('zanjan', 'زنجان', 'زنجان', 36.68, 48.49, 14),
    ('semnan', 'سمنان', 'سمنان', 35.57, 53.40, 15),
    ('sistan-baluchestan', 'سیستان و بلوچستان', 'زاهدان', 29.50, 60.86, 16),
    ('fars', 'فارس', 'شیراز', 29.59, 52.58, 17),
    ('qazvin', 'قزوین', 'قزوین', 36.27, 50.00, 18),
    ('qom', 'قم', 'قم', 34.64, 50.88, 19),
    ('kurdistan', 'کردستان', 'سنندج', 35.31, 47.00, 20),
    ('kerman', 'کرمان', 'کرمان', 30.28, 57.08, 21),
    ('kermanshah', 'کرمانشاه', 'کرمانشاه', 34.31, 47.07, 22),
    ('kohgiluyeh-boyer-ahmad', 'کهگیلویه و بویراحمد', 'یاسوج', 30.67, 51.59, 23),
    ('golestan', 'گلستان', 'گرگان', 36.84, 54.43, 24),
    ('gilan', 'گیلان', 'رشت', 37.28, 49.58, 25),
    ('lorestan', 'لرستان', 'خرم‌آباد', 33.49, 48.36, 26),
    ('mazandaran', 'مازندران', 'ساری', 36.56, 53.06, 27),
    ('markazi', 'مرکزی', 'اراک', 34.09, 49.69, 28),
    ('hormozgan', 'هرمزگان', 'بندرعباس', 27.18, 56.27, 29),
    ('hamadan', 'همدان', 'همدان', 34.80, 48.51, 30),
    ('yazd', 'یزد', 'یزد', 31.90, 54.37, 31);

-- Starting sectors named by the business; more are added from the admin panel.
INSERT INTO chain_sectors (slug, name_fa, sort_order, created_at) VALUES
    ('fmcg', 'کالاهای تندمصرف (سوپرمارکت)', 1, '2026-11-09T00:00:00.000Z'),
    ('nuts-dried-fruit', 'آجیل و خشکبار', 2, '2026-11-09T00:00:00.000Z'),
    ('carpet', 'فرش', 3, '2026-11-09T00:00:00.000Z'),
    ('moquette', 'موکت', 4, '2026-11-09T00:00:00.000Z'),
    ('stone', 'سنگ', 5, '2026-11-09T00:00:00.000Z'),
    ('home-appliances', 'لوازم خانگی', 6, '2026-11-09T00:00:00.000Z');
