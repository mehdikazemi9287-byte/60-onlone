"""Connector Certification Harness tests — Blocker 9."""
import unittest
from tests.base import AppTestCase
from app.adapters.connectors.certification_harness import ConnectorCertificationHarness, CertificationFailure
from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector


class CertificationHarnessTest(AppTestCase):

    def setUp(self):
        super().setUp()
        self.adapter = MockErpV2Connector(config={})
        self.harness = ConnectorCertificationHarness(self.adapter)

    def test_run_all_passes_for_mock_erp_v2(self):
        """MockErpV2 must pass all certification checks."""
        result = self.harness.run_all()
        self.assertTrue(result["passed"],
                        f"Certification failed: {result['failures']}")
        self.assertEqual(result["failed_count"], 0)

    def test_capabilities_check_passes(self):
        """check_capabilities must pass for MockErpV2."""
        result = self.harness.check_capabilities()
        self.assertEqual(result["status"], "passed")

    def test_schema_check_catches_float_price(self):
        """schema check must catch float price_minor."""
        class FloatPriceAdapter:
            def pull_products(self, limit=10, offset=0):
                return {"items": [{"code": "X", "price_minor": 1.5}], "total": 1}
            def capabilities(self):
                return {"connector_type": "test"}
            def health_check(self):
                return {"healthy": True, "message": "ok", "latency_ms": 0}

        h = ConnectorCertificationHarness(FloatPriceAdapter())
        with self.assertRaises(CertificationFailure):
            h.check_schema()

    def test_pagination_check_passes(self):
        """Pagination check: page 1 and page 2 return different items."""
        result = self.harness.check_pagination()
        self.assertEqual(result["status"], "passed")

    def test_idempotency_check_passes(self):
        """Same request returns same items."""
        result = self.harness.check_idempotency()
        self.assertEqual(result["status"], "passed")

    def test_health_check_passes(self):
        """health_check() returns dict with healthy=True."""
        result = self.harness.check_health()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["healthy"])

    def test_generator_interface_passes(self):
        """pull_products_all() yields items."""
        result = self.harness.check_generator_interface()
        self.assertIn(result["status"], ("passed", "skipped"))

    def test_credential_redaction_passes(self):
        """capabilities() must not expose secrets."""
        result = self.harness.check_credential_redaction()
        self.assertEqual(result["status"], "passed")

    def test_harness_is_reusable_with_different_adapters(self):
        """Harness must work with any adapter, not just MockErpV2."""
        # Create a minimal valid adapter with proper pagination support
        class MinimalAdapter:
            _products = [{"code": f"A{i:03d}", "price_minor": 100000 + i} for i in range(20)]

            def pull_products(self, limit=10, offset=0):
                page = self._products[offset:offset + limit]
                return {"items": page, "total": len(self._products)}

            def capabilities(self):
                return {"connector_type": "minimal"}

            def health_check(self):
                return {"healthy": True, "message": "ok", "latency_ms": 0}

        h = ConnectorCertificationHarness(MinimalAdapter())
        result = h.run_all()
        # Should pass most checks (may skip generator)
        self.assertEqual(result["failed_count"], 0,
                         f"Minimal adapter failed: {result['failures']}")


if __name__ == "__main__":
    unittest.main()
