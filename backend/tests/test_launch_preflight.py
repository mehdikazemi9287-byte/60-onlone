"""Day-zero preflight: catches demo accounts, draft legal texts, test flags; passes a clean production config."""
from __future__ import annotations

import os
import tempfile
from unittest import mock

from scripts import launch_preflight as lp
from tests.base import AppTestCase


class PreflightTest(AppTestCase):
    def test_db_checks_flag_seed_and_drafts(self):
        rows = {k: (lvl, msg) for lvl, k, msg in lp.db_checks(self.db)}
        self.assertEqual(rows["migrations"][0], lp.OK)
        self.assertEqual(rows["seed_accounts"][0], lp.BLOCKER)          # test DB is seeded with demo users
        self.assertIn("admin@60online.ir", rows["seed_accounts"][1])
        self.assertEqual(rows["legal_documents"][0], lp.BLOCKER)        # drafts carry a zero hash
        for key in ("admin", "vat", "sellers", "catalog", "tariffs", "organizations", "payout_hold"):
            self.assertIn(key, rows)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET is_active=0 WHERE email_normalized LIKE '%@60online.ir' OR email_normalized LIKE '%@parsco.ir'")
        rows = {k: lvl for lvl, k, _ in lp.db_checks(self.db)}
        self.assertEqual(rows["seed_accounts"], lp.OK)

    def test_config_checks(self):
        d = tempfile.mkdtemp()
        good = {"APP_ENV": "production", "PUBLIC_BASE_URL": "https://60online.ir", "CORS_ORIGINS": "https://60online.ir",
                "SECRET_KEY": "k" * 64, "PAYMENT_PROVIDER": "sepehr", "SEPEHR_TERMINAL_ID": "123",
                "STOREFRONT_SALES_ENABLED": "1", "LEGAL_REQUIRE_BUYER_TERMS": "1", "SMS_PROVIDER": "kavenegar",
                "KAVENEGAR_API_KEY": "x", "KAVENEGAR_TEMPLATE": "t", "KAVENEGAR_SENDER": "1000", "RATE_LIMIT_PER_MINUTE": "120",
                "MEDIA_ROOT": d, "DOCUMENT_STORAGE_DIR": d, "STOREFRONT_PRICE_VISIBILITY": "organizations",
                "TRUSTED_PROXY_HOPS": "1", "OTP_DAILY_SMS_CAP": "3000"}
        with mock.patch.dict(os.environ, good, clear=True):
            self.assertEqual([r for r in lp.config_checks() if r[0] != lp.OK], [])
        with mock.patch.dict(os.environ, {**good, "COMMERCE_TEST_MODE": "1", "CORS_ORIGINS": "http://localhost:3000"}, clear=True):
            bad = {k for lvl, k, _ in lp.config_checks() if lvl == lp.BLOCKER}
        self.assertEqual(bad, {"COMMERCE_TEST_MODE", "CORS_ORIGINS"})
        no_sms = {k: v for k, v in good.items() if k != "SMS_PROVIDER"}  # audit N1: console is refused on servers
        with mock.patch.dict(os.environ, no_sms, clear=True):
            self.assertIn("SMS_PROVIDER", {k for lvl, k, _ in lp.config_checks() if lvl == lp.BLOCKER})
