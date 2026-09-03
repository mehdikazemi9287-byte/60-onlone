"""Connector certification tests — Phase 6 Final.

Verifies that connectors adhering to the contract pass certification.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.connectors.base import ConnectorAdapter
from app.adapters.connectors.mock_erp import MockErpConnector
from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector, ConnectorOutageError, TOTAL_PRODUCTS
from app.adapters.connectors import registry as conn_registry


class MockErpV2CertificationTest(unittest.TestCase):
    """MockErpV2 must pass all certification checks."""

    def setUp(self):
        self.adapter = MockErpV2Connector()

    def test_adapter_is_connector_adapter_subclass(self):
        self.assertIsInstance(self.adapter, ConnectorAdapter)

    def test_health_check_returns_healthy(self):
        health = self.adapter.health_check()
        self.assertIn("healthy", health)
        self.assertIn("message", health)
        self.assertIn("latency_ms", health)
        self.assertTrue(health["healthy"])

    def test_pull_products_returns_paginated_dict(self):
        result = self.adapter.pull_products(limit=10, offset=0)
        self.assertIsInstance(result, dict)
        self.assertIn("items", result)
        self.assertIn("total", result)
        self.assertEqual(result["total"], TOTAL_PRODUCTS)
        self.assertEqual(len(result["items"]), 10)

    def test_pull_products_pagination(self):
        page1 = self.adapter.pull_products(limit=100, offset=0)
        page2 = self.adapter.pull_products(limit=100, offset=100)
        codes1 = {p["code"] for p in page1["items"]}
        codes2 = {p["code"] for p in page2["items"]}
        self.assertEqual(len(codes1 & codes2), 0)  # No overlap

    def test_total_products_correct(self):
        result = self.adapter.pull_products(limit=1, offset=0)
        self.assertEqual(result["total"], 10000)

    def test_products_have_required_fields(self):
        result = self.adapter.pull_products(limit=5, offset=0)
        required = {"code", "name_fa", "price_minor", "stock_quantity", "barcode"}
        for item in result["items"]:
            missing = required - set(item.keys())
            self.assertEqual(missing, set(), f"Missing fields: {missing}")

    def test_price_is_integer_not_float(self):
        result = self.adapter.pull_products(limit=50, offset=0)
        for item in result["items"]:
            self.assertIsInstance(item["price_minor"], int,
                                 f"price_minor must be int: {item}")
            self.assertNotIsInstance(item["price_minor"], float)

    def test_outage_isolated_does_not_crash_core(self):
        """Outage should raise ConnectorOutageError, not crash Python."""
        bad_adapter = MockErpV2Connector(config={"simulate_outage": True})
        with self.assertRaises(ConnectorOutageError):
            bad_adapter.pull_products(limit=1, offset=0)
        # Core code must survive this
        health = bad_adapter.health_check()
        self.assertFalse(health["healthy"])

    def test_malformed_response_isolated(self):
        """Malformed row is returned but pipeline should handle it gracefully."""
        malformed_adapter = MockErpV2Connector(config={"inject_malformed": True})
        result = malformed_adapter.pull_products(limit=5, offset=0)
        items = result["items"]
        self.assertEqual(len(items), 5)
        # First item is malformed
        first = items[0]
        self.assertEqual(first.get("code"), "MALFORMED")

    def test_pagination_supported(self):
        """Adapter must support limit+offset pagination correctly."""
        all_codes = set()
        for offset in range(0, 1000, 100):
            page = self.adapter.pull_products(limit=100, offset=offset)
            for item in page["items"]:
                self.assertNotIn(item["code"], all_codes, "Duplicate product in pagination")
                all_codes.add(item["code"])
        self.assertEqual(len(all_codes), 1000)

    def test_credential_not_leaked(self):
        """Config with credentials must not be returned by health_check."""
        sensitive_adapter = MockErpV2Connector(config={
            "api_key": "SECRET_KEY_MUST_NOT_LEAK",
            "password": "SUPER_SECRET_PASSWORD",
        })
        health = sensitive_adapter.health_check()
        health_str = str(health)
        self.assertNotIn("SECRET_KEY_MUST_NOT_LEAK", health_str)
        self.assertNotIn("SUPER_SECRET_PASSWORD", health_str)

    def test_resolve_product_by_barcode(self):
        product = self.adapter.resolve_product(
            identifier_type="barcode", identifier_value="6260000000000"
        )
        self.assertIsNotNone(product)
        self.assertEqual(product["barcode"], "6260000000000")
        self.assertIsInstance(product["price_minor"], int)

    def test_resolve_product_not_found(self):
        product = self.adapter.resolve_product(
            identifier_type="barcode", identifier_value="0000000000000"
        )
        self.assertIsNone(product)

    def test_pull_products_all_generator(self):
        """pull_products_all() must be a generator yielding all 10K products."""
        gen = self.adapter.pull_products_all()
        import types
        self.assertIsInstance(gen, types.GeneratorType)
        count = sum(1 for _ in gen)
        self.assertEqual(count, TOTAL_PRODUCTS)


class NotImplementedAdapterCertificationTest(unittest.TestCase):
    """NOT_IMPLEMENTED adapters must fail gracefully."""

    def test_not_implemented_adapter_fails_gracefully(self):
        adapter = conn_registry.get_adapter("HOLO_ERP")
        health = adapter.health_check()
        self.assertFalse(health["healthy"])
        self.assertIn("NOT IMPLEMENTED", health["message"])

    def test_not_implemented_pull_products_raises(self):
        from app.adapters.connectors.base import ConnectorError
        adapter = conn_registry.get_adapter("SEPIDAR_ERP")
        with self.assertRaises((NotImplementedError, ConnectorError)):
            adapter.pull_products(limit=1, offset=0)

    def test_unknown_connector_type_raises_validation_error(self):
        from app.core.errors import ValidationError
        with self.assertRaises(ValidationError):
            conn_registry.get_adapter("UNKNOWN_XYZ_ERP")


class MockErpV1CertificationTest(unittest.TestCase):
    """Original MockErpConnector must still pass basic certification."""

    def test_mock_erp_v1_health_check(self):
        adapter = MockErpConnector(dataset="products")
        health = adapter.health_check()
        self.assertTrue(health["healthy"])

    def test_mock_erp_v1_pull_products(self):
        adapter = MockErpConnector(dataset="products")
        products = adapter.pull_products(limit=5, offset=0)
        self.assertIsInstance(products, list)
        self.assertLessEqual(len(products), 5)

    def test_registry_returns_v2_for_large_dataset(self):
        adapter = conn_registry.get_adapter("MOCK_ERP", config={"dataset": "large"})
        self.assertIsInstance(adapter, MockErpV2Connector)

    def test_registry_returns_v1_for_products_dataset(self):
        adapter = conn_registry.get_adapter("MOCK_ERP", config={"mock_erp_dataset": "products"})
        self.assertIsInstance(adapter, MockErpConnector)


if __name__ == "__main__":
    unittest.main()
