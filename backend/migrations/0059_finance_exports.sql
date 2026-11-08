-- Phase 5B — درگاه‌های مخصوص نرم‌افزارهای مالی (financial exports + Moadian e-invoices).
--
-- finance_account_mappings : stable account keys (revenue, vat_payable, ...) → the
--                            code used inside each accounting package. connector
--                            'DEFAULT' is the fallback for every connector.
-- finance_export_jobs      : one rendered export file per (params, content hash);
--                            re-running the same params returns the same row.
-- moadian_fiscal_ids       : fiscal-memory id (شناسه یکتای حافظه مالیاتی) per issuer.
-- moadian_documents        : one built Moadian invoice per source document, with
--                            its taxid, payload and submission status/reference.
--
-- PURELY ADDITIVE. Money is INTEGER minor units (Rial). Timestamps are written by
-- the services as UTC 'YYYY-MM-DD HH:MM:SS'.

CREATE TABLE IF NOT EXISTS finance_account_mappings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    connector       TEXT    NOT NULL,
    account_key     TEXT    NOT NULL,
    account_code    TEXT    NOT NULL,
    account_name    TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE (connector, account_key)
);

INSERT INTO finance_account_mappings (connector, account_key, account_code, account_name, created_at, updated_at) VALUES
    ('DEFAULT', 'bank',               '1101', 'بانک',                         '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'receivable',         '1301', 'حساب‌های دریافتنی',            '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'credit_receivable',  '1302', 'دریافتنی اعتباری سازمان‌ها',   '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'vat_receivable',     '1401', 'مالیات بر ارزش افزوده خرید',   '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'seller_payable',     '2101', 'بدهی به فروشندگان',            '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'payable',            '2102', 'حساب‌های پرداختنی',            '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'credit_payable',     '2103', 'بدهی اعتباری',                 '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'vat_payable',        '2201', 'مالیات بر ارزش افزوده فروش',   '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'revenue',            '4101', 'درآمد فروش',                   '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'commission_income',  '4102', 'درآمد کارمزد',                 '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'purchases',          '5101', 'خرید کالا و خدمات',            '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    ('DEFAULT', 'commission_expense', '5102', 'هزینه کارمزد',                 '2026-01-01 00:00:00', '2026-01-01 00:00:00');

CREATE TABLE IF NOT EXISTS finance_export_jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT    NOT NULL UNIQUE,
    entity_type         TEXT    NOT NULL CHECK (entity_type IN ('platform', 'seller', 'organization')),
    entity_id           INTEGER,
    connector           TEXT    NOT NULL,
    period_start        TEXT    NOT NULL,
    period_end          TEXT    NOT NULL,
    params_hash         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'ready' CHECK (status IN ('ready', 'failed')),
    document_count      INTEGER NOT NULL DEFAULT 0,
    file_name           TEXT    NOT NULL,
    content_type        TEXT    NOT NULL,
    content             TEXT    NOT NULL,
    content_sha256      TEXT    NOT NULL,
    created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TEXT    NOT NULL,
    UNIQUE (params_hash, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_finance_export_jobs_entity
    ON finance_export_jobs (entity_type, entity_id, id);

CREATE TABLE IF NOT EXISTS moadian_fiscal_ids (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_key          TEXT    NOT NULL UNIQUE,
    fiscal_memory_id    TEXT    NOT NULL,
    economic_code       TEXT    NOT NULL DEFAULT '',
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS moadian_documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ref          TEXT    NOT NULL UNIQUE,
    doc_type            TEXT    NOT NULL,
    issuer_type         TEXT    NOT NULL CHECK (issuer_type IN ('platform', 'seller')),
    issuer_supplier_id  INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    issuer_key          TEXT    NOT NULL,
    serial              INTEGER NOT NULL,
    taxid               TEXT    NOT NULL UNIQUE,
    inty                INTEGER NOT NULL CHECK (inty IN (1, 2, 3)),
    tbill_minor         INTEGER NOT NULL,
    payload_json        TEXT    NOT NULL,
    payload_sha256      TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'built'
                                CHECK (status IN ('built', 'submitted', 'accepted', 'rejected')),
    submission_reference TEXT,
    submission_error    TEXT,
    submitted_at        TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    UNIQUE (issuer_key, serial)
);
CREATE INDEX IF NOT EXISTS idx_moadian_documents_issuer
    ON moadian_documents (issuer_type, issuer_supplier_id, id);
