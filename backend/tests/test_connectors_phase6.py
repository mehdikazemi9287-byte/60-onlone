"""Unit tests for the connector adapter registry and MockErpConnector (Phase 6).

These tests exercise only the adapter classes and registry — no database access
is needed, so they inherit from unittest.TestCase rather than AppTestCase.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import ValidationError
from app.adapters.connectors.registry import get_adapter
from app.adapters.connectors.mock_erp import MockErpConnector


class MockErpConnectorTest(unittest.TestCase):
    """Tests that verify MockErpConnector behaviour directly."""

    def test_mock_erp_health_check(self):
        """MockErpConnector().health_check() reports healthy=True."""
        adapter = MockErpConnector()
        result  = adapter.health_check()

        self.assertIn("healthy", result)
        self.assertTrue(result["healthy"])

    def test_mock_erp_pull_products_full(self):
        """Default 'products' dataset returns exactly 20 products."""
        adapter  = MockErpConnector(dataset="products")
        products = adapter.pull_products(limit=100, offset=0)

        self.assertEqual(len(products), 20)
        for p in products:
            self.assertIn("code",           p)
            self.assertIn("name",           p)
            self.assertIn("price_minor",    p)
            self.assertIn("stock_quantity", p)
            # price_minor must be an integer (no floats)
            self.assertIsInstance(p["price_minor"],    int)
            self.assertIsInstance(p["stock_quantity"], int)

    def test_mock_erp_pull_products_minimal(self):
        """'minimal' dataset returns exactly 3 products."""
        adapter  = MockErpConnector(dataset="minimal")
        products = adapter.pull_products(limit=100, offset=0)

        self.assertEqual(len(products), 3)

    def test_mock_erp_pull_products_empty(self):
        """'empty' dataset returns an empty list."""
        adapter  = MockErpConnector(dataset="empty")
        products = adapter.pull_products(limit=100, offset=0)

        self.assertEqual(products, [])

    def test_mock_erp_resolve_by_barcode(self):
        """resolve_product with identifier_type='barcode' and the known barcode returns a product."""
        adapter = MockErpConnector(dataset="products")
        result  = adapter.resolve_product(
            identifier_type="barcode",
            identifier_value="6260001000010",   # ERP-001 barcode
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "ERP-001")
        self.assertIsInstance(result["price_minor"], int)

    def test_mock_erp_resolve_not_found(self):
        """resolve_product with unknown barcode returns None."""
        adapter = MockErpConnector(dataset="products")
        result  = adapter.resolve_product(
            identifier_type="barcode",
            identifier_value="0000000000000",   # unknown
        )

        self.assertIsNone(result)

    def test_mock_erp_pull_inventory_returns_codes(self):
        """pull_inventory returns a list with 'code' and 'stock_quantity' fields."""
        adapter   = MockErpConnector(dataset="minimal")
        inventory = adapter.pull_inventory()

        self.assertEqual(len(inventory), 3)
        for item in inventory:
            self.assertIn("code",           item)
            self.assertIn("stock_quantity", item)


class AdapterRegistryTest(unittest.TestCase):
    """Tests for get_adapter() factory behaviour."""

    def test_get_adapter_manual_returns_healthy(self):
        """get_adapter('MANUAL').health_check() returns healthy=True."""
        adapter = get_adapter("MANUAL")
        result  = adapter.health_check()

        self.assertTrue(result["healthy"])

    def test_get_adapter_mock_erp_returns_healthy(self):
        """get_adapter('MOCK_ERP') returns a healthy MockErpConnector."""
        adapter = get_adapter("MOCK_ERP")
        result  = adapter.health_check()

        self.assertTrue(result["healthy"])

    def test_get_adapter_not_yet_implemented_unhealthy(self):
        """get_adapter('HOLO_ERP').health_check() returns healthy=False (not implemented)."""
        adapter = get_adapter("HOLO_ERP")
        result  = adapter.health_check()

        self.assertFalse(result["healthy"])
        self.assertIn("message", result)

    def test_get_adapter_unknown_raises_validation_error(self):
        """get_adapter with an unrecognised type raises ValidationError."""
        with self.assertRaises(ValidationError):
            get_adapter("UNKNOWN_XYZ")

    def test_get_adapter_mock_erp_config_dataset(self):
        """get_adapter('MOCK_ERP', config={'mock_erp_dataset': 'minimal'}) returns 3 products."""
        adapter  = get_adapter("MOCK_ERP", config={"mock_erp_dataset": "minimal"})
        products = adapter.pull_products(limit=100, offset=0)

        self.assertEqual(len(products), 3)

    def test_get_adapter_holo_erp_pull_inventory_raises_not_implemented(self):
        """_NotYetImplementedAdapter.pull_inventory() raises NotImplementedError or ConnectorError."""
        from app.adapters.connectors.base import ConnectorError
        adapter = get_adapter("HOLO_ERP")

        with self.assertRaises((NotImplementedError, ConnectorError)):
            adapter.pull_inventory()


if __name__ == "__main__":
    unittest.main()
