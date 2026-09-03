-- Migration 0019: VAT rate correction — STANDARD category to 10% (1000 bps)
--
-- BACKGROUND:
--   Migration 0018 seeded the STANDARD tax category at 900 bps (9%) with
--   effective_from='2024-01-01' and effective_until=NULL.  That is wrong on
--   two counts:
--     1. Iran's standard VAT rate was raised from 9% to 10% starting with
--        the 1403 (2024-03-20) fiscal year per public announcements from the
--        Iranian National Tax Administration (INTA).
--     2. The 900 bps row was left open-ended (effective_until NULL), which
--        would keep returning a stale 9% for any effective_date queried today.
--
--   This migration does NOT edit the 900 bps row's rate or effective_from —
--   that would rewrite history.  It closes the open end and adds a new
--   separately-dated row for the 10% rate.
--
-- SOURCING NOTE:
--   effective_from ('2024-03-20', Iranian fiscal year 1403 start) and the
--   legal_basis text below are based on public INTA announcement coverage at
--   the time this migration was written, NOT a direct citation of the official
--   circular (بخشنامه) number.  Confirm the exact circular number and effective
--   date with an Iranian tax accountant, then UPDATE legal_basis and source_url
--   on the inserted row (add a new dated row if the confirmed date differs).
--
-- IDEMPOTENCY:
--   The schema_migrations tracking table (managed by migrator.py) ensures this
--   file is applied exactly once.  The INSERT ... WHERE NOT EXISTS guard below
--   is extra safety if the 10% row was somehow inserted manually.

-- 1. Add audit-trail columns for legal/source provenance
ALTER TABLE tax_rates ADD COLUMN legal_basis TEXT;
ALTER TABLE tax_rates ADD COLUMN source_url TEXT;

-- 2. Close the previously open-ended 9% STANDARD row (preserve history)
UPDATE tax_rates
SET
    effective_until = '2024-03-19',
    legal_basis     = COALESCE(legal_basis,
        'نرخ ۹٪ مالیات بر ارزش افزوده (پیش از بودجه ۱۴۰۳) — نیازمند تأیید حسابدار'),
    source_url      = COALESCE(source_url, 'https://www.tax.gov.ir/')
WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code = 'STANDARD')
  AND rate_bps         = 900
  AND effective_until  IS NULL;

-- 3. Insert the current 10% STANDARD rate (safe to repeat: WHERE NOT EXISTS guard)
INSERT INTO tax_rates
    (tax_category_id, rate_bps, effective_from, effective_until,
     jurisdiction, notes, legal_basis, source_url)
SELECT
    id,
    1000,
    '2024-03-20',
    NULL,
    'IR',
    'نرخ استاندارد مالیات بر ارزش افزوده ایران — ۱۰٪ — تاریخ اثر و شماره بخشنامه رسمی نیازمند تأیید حسابدار است.',
    'افزایش نرخ مالیات بر ارزش افزوده به ۱۰٪ — بودجه سال ۱۴۰۳ کل کشور (منبع: اطلاعیه سازمان امور مالیاتی کشور — نیازمند تأیید شماره بخشنامه رسمی)',
    'https://www.tax.gov.ir/'
FROM tax_categories
WHERE code = 'STANDARD'
  AND NOT EXISTS (
      SELECT 1 FROM tax_rates tr2
      WHERE tr2.tax_category_id = tax_categories.id
        AND tr2.rate_bps        = 1000
        AND tr2.effective_from  = '2024-03-20'
  );
