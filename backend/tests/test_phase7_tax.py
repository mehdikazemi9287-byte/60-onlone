"""Phase 7 — Tax Foundation tests.

Tests:
  - tax_categories seeded from migration (STANDARD, ZERO, EXEMPT, etc.)
  - rate lookup at effective_date (historical reproducibility)
  - calculate_line_tax: correct integer arithmetic (floor)
  - org exemption: rate → 0 when exempt
  - MockTaxAdapter: calculate_tax, submit_invoice, get_submission_status
  - MoadianTaxAdapter: raises NOT IMPLEMENTED
  - TaxAdapter registry: MOCK → MockTaxAdapter, unknown → ValidationError
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.adapters.tax.mock import MockTaxAdapter
from app.adapters.tax.base import TaxLineInput, TaxAdapterError
from app.adapters.tax.moadian import MoadianTaxAdapter
from app.adapters.tax.registry import get_tax_adapter, list_tax_systems


class TestTaxService(AppTestCase):
    """Tests backed by a real migrated database with seeded tax data."""

    def test_seeded_categories_present(self):
        with self.app.app_context():
            from app.services.tax_service import get_tax_categories
            cats = get_tax_categories()
            codes = {c["code"] for c in cats}
            for expected in ("STANDARD", "ZERO", "EXEMPT"):
                self.assertIn(expected, codes)

    def test_get_rate_standard_10pct_current(self):
        """Standard Iranian VAT rate is 10% (1000 bps) from 2024-03-20 — migration 0019."""
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate = get_rate_bps("STANDARD", effective_date="2026-01-01")
            self.assertEqual(rate, 1000, "STANDARD rate must be 1000 bps (10%) after migration 0019")

    def test_get_rate_standard_9pct_historical(self):
        """Historical Iranian VAT rate is 9% (900 bps) before 2024-03-20."""
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate = get_rate_bps("STANDARD", effective_date="2024-01-15")
            self.assertEqual(rate, 900, "STANDARD rate before 2024-03-20 must be 900 bps (9%)")

    def test_get_rate_zero_is_0(self):
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate = get_rate_bps("ZERO", effective_date="2026-01-01")
            self.assertEqual(rate, 0)

    def test_get_rate_exempt_is_0(self):
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate = get_rate_bps("EXEMPT", effective_date="2026-01-01")
            self.assertEqual(rate, 0)

    def test_calculate_tax_integer_arithmetic(self):
        """Tax calculation uses floor division — no floats. Rate is 10% after migration 0019."""
        with self.app.app_context():
            from app.services.tax_service import calculate_line_tax
            # 1000000 * 10% = 100000 exactly (migration 0019 raised STANDARD to 1000 bps)
            result = calculate_line_tax(
                subtotal_minor=1_000_000,
                tax_category_code="STANDARD",
                effective_date="2026-01-01",
            )
            self.assertEqual(result["tax_minor"], 100_000)
            self.assertEqual(result["total_minor"], 1_100_000)
            self.assertEqual(result["rate_bps"], 1000)

    def test_calculate_tax_floor_rounding(self):
        """Fractional rial is floored, not rounded. Rate is 10% after migration 0019."""
        with self.app.app_context():
            from app.services.tax_service import calculate_line_tax
            # 1001 * 1000 / 10000 = 100.1 → floor = 100
            result = calculate_line_tax(
                subtotal_minor=1001,
                tax_category_code="STANDARD",
                effective_date="2026-01-01",
            )
            self.assertEqual(result["tax_minor"], 100)

    def test_calculate_tax_exempt_zero(self):
        """EXEMPT category → 0 tax."""
        with self.app.app_context():
            from app.services.tax_service import calculate_line_tax
            result = calculate_line_tax(
                subtotal_minor=500_000,
                tax_category_code="EXEMPT",
                effective_date="2026-01-01",
            )
            self.assertEqual(result["tax_minor"], 0)
            self.assertEqual(result["total_minor"], 500_000)

    def test_historical_reproducibility(self):
        """Rate is looked up for the given date, not today.
        After migration 0019: 2024-03-20+ returns 1000 bps; pre-2024-03-20 returns 900 bps.
        """
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            # Add a hypothetical future rate change to verify date-gating
            from app.services.tax_service import create_tax_rate
            create_tax_rate(
                tax_category_code="STANDARD",
                rate_bps=1100,
                effective_from="2027-01-01",
            )
            # 2026: should return 1000 (migration 0019 row, effective 2024-03-20)
            rate_2026 = get_rate_bps("STANDARD", effective_date="2026-06-01")
            self.assertEqual(rate_2026, 1000, "2026 rate must be 1000 bps (10%)")
            # 2024-01-15: should return 900 (migration 0018 seeded row, effective_from 2024-01-01,
            # effective_until 2024-03-19 after migration 0019 — seeded data starts 2024-01-01)
            rate_historical = get_rate_bps("STANDARD", effective_date="2024-01-15")
            self.assertEqual(rate_historical, 900, "2024-01-15 rate must be 900 bps (9%)")

    def test_create_and_retrieve_tax_category(self):
        with self.app.app_context():
            from app.services.tax_service import create_tax_category, get_tax_category
            cat = create_tax_category(
                code="TEST_LUXURY",
                name_fa="لوازم لوکس",
                name_en="Luxury Goods",
            )
            retrieved = get_tax_category("TEST_LUXURY")
            self.assertEqual(retrieved["code"], "TEST_LUXURY")

    def test_duplicate_category_code_raises(self):
        with self.app.app_context():
            from app.services.tax_service import create_tax_category
            from app.core.errors import ValidationError
            create_tax_category(code="DUP_TEST", name_fa="تست تکرار")
            with self.assertRaises(ValidationError):
                create_tax_category(code="DUP_TEST", name_fa="تکرار")


class TestMockTaxAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = MockTaxAdapter()

    def test_calculate_tax_standard(self):
        lines = [TaxLineInput("محصول A", quantity=2, unit_price_minor=500_000,
                              tax_category_code="STANDARD")]
        result = self.adapter.calculate_tax(lines, effective_date="2026-01-01")
        self.assertEqual(result.subtotal_minor, 1_000_000)
        self.assertEqual(result.rate_bps, 900)
        self.assertEqual(result.tax_minor, 90_000)
        self.assertEqual(result.total_minor, 1_090_000)

    def test_calculate_tax_zero(self):
        lines = [TaxLineInput("محصول B", quantity=1, unit_price_minor=200_000,
                              tax_category_code="ZERO")]
        result = self.adapter.calculate_tax(lines, effective_date="2026-01-01")
        self.assertEqual(result.tax_minor, 0)
        self.assertEqual(result.total_minor, 200_000)

    def test_submit_invoice_returns_ref(self):
        lines = [TaxLineInput("محصول C", quantity=1, unit_price_minor=100_000)]
        calc = self.adapter.calculate_tax(lines, effective_date="2026-01-01")
        result = self.adapter.submit_invoice(calc)
        self.assertTrue(result["acknowledged"])
        self.assertIn("MOCK-TAX-", result["external_ref"])

    def test_get_submission_status_accepted(self):
        lines = [TaxLineInput("محصول D", quantity=1, unit_price_minor=50_000)]
        calc = self.adapter.calculate_tax(lines, effective_date="2026-01-01")
        submitted = self.adapter.submit_invoice(calc)
        ref = submitted["external_ref"]
        status = self.adapter.get_submission_status(ref)
        self.assertEqual(status["status"], "accepted")

    def test_get_submission_status_not_found(self):
        status = self.adapter.get_submission_status("NONEXISTENT")
        self.assertEqual(status["status"], "not_found")

    def test_empty_lines_raises(self):
        with self.assertRaises(TaxAdapterError):
            self.adapter.calculate_tax([], effective_date="2026-01-01")

    def test_health_check(self):
        result = self.adapter.health_check()
        self.assertTrue(result["healthy"])

    def test_submission_count_increments(self):
        lines = [TaxLineInput("محصول E", quantity=1, unit_price_minor=100_000)]
        calc = self.adapter.calculate_tax(lines, effective_date="2026-01-01")
        self.adapter.submit_invoice(calc)
        self.adapter.submit_invoice(calc)
        self.assertEqual(self.adapter.submission_count, 2)


class TestMoadianNotImplemented(unittest.TestCase):

    def test_health_check_unhealthy(self):
        adapter = MoadianTaxAdapter()
        self.assertFalse(adapter.health_check()["healthy"])

    def test_calculate_raises(self):
        adapter = MoadianTaxAdapter()
        with self.assertRaises(TaxAdapterError) as ctx:
            adapter.calculate_tax([], effective_date="2026-01-01")
        self.assertEqual(ctx.exception.code, "not_implemented")

    def test_submit_raises(self):
        adapter = MoadianTaxAdapter()
        with self.assertRaises(TaxAdapterError):
            adapter.submit_invoice(None)

    def test_capabilities_empty_supported(self):
        adapter = MoadianTaxAdapter()
        caps = adapter.capabilities()
        self.assertEqual(caps["implementation_status"], "not_implemented")
        self.assertEqual(caps["supported"], [])


class TestTaxAdapterRegistry(unittest.TestCase):

    def test_mock_returns_mock_adapter(self):
        adapter = get_tax_adapter("MOCK")
        self.assertIsInstance(adapter, MockTaxAdapter)

    def test_moadian_returns_moadian_adapter(self):
        adapter = get_tax_adapter("MOADIAN")
        self.assertIsInstance(adapter, MoadianTaxAdapter)

    def test_unknown_raises(self):
        from app.core.errors import ValidationError
        with self.assertRaises(ValidationError):
            get_tax_adapter("NONEXISTENT_SYSTEM")

    def test_list_systems_includes_expected(self):
        systems = list_tax_systems()
        system_names = [s["system"] for s in systems]
        self.assertIn("MOCK", system_names)
        self.assertIn("MOADIAN", system_names)


if __name__ == "__main__":
    unittest.main()
