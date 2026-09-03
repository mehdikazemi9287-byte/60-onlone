"""Phase 7 — Universal Integration Gateway tests.

Tests:
  - ConnectorAdapter v2 contract (capabilities, cursor, error codes)
  - CsvConnector (parse, load, pull_products, pull_prices, pull_inventory)
  - MockErpConnector still works after v2 refactor
  - Registry: known types, unknown type raises ValidationError
  - NOT IMPLEMENTED stubs raise ConnectorError(NOT_IMPLEMENTED)
"""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.connectors.base import (
    ConnectorAdapter,
    ConnectorError,
    ConnectorErrorCode,
    SyncCursor,
    CapabilityDeclaration,
    CAPABILITY_PULL_PRODUCTS,
    CAPABILITY_PULL_PRICES,
    CAPABILITY_PULL_INVENTORY,
    CAPABILITY_HEALTH_CHECK,
)
from app.adapters.connectors.csv_connector import CsvConnector, parse_csv_feed
from app.adapters.connectors.registry import get_adapter, list_connector_types
from app.core.errors import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# ConnectorAdapter base contract
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorAdapterBase(unittest.TestCase):

    def test_base_adapter_raises_not_implemented(self):
        adapter = ConnectorAdapter()
        with self.assertRaises(ConnectorError) as ctx:
            adapter.pull_products()
        self.assertEqual(ctx.exception.code, ConnectorErrorCode.NOT_IMPLEMENTED)

    def test_base_health_check_returns_unhealthy(self):
        adapter = ConnectorAdapter()
        result = adapter.health_check()
        self.assertFalse(result["healthy"])

    def test_sync_cursor_serialization(self):
        cursor = SyncCursor(product="tok_abc", price="tok_xyz")
        json_str = cursor.to_json()
        restored = SyncCursor.from_json(json_str)
        self.assertEqual(restored.product, "tok_abc")
        self.assertEqual(restored.price, "tok_xyz")
        self.assertIsNone(restored.inventory)

    def test_sync_cursor_from_none(self):
        cursor = SyncCursor.from_json(None)
        self.assertIsNone(cursor.product)

    def test_connector_error_retryable(self):
        err = ConnectorError("timeout", code=ConnectorErrorCode.TIMEOUT, retryable=True)
        self.assertTrue(err.retryable)
        self.assertEqual(err.code, ConnectorErrorCode.TIMEOUT)

    def test_connector_error_not_retryable_by_default(self):
        err = ConnectorError("bad input", code=ConnectorErrorCode.VALIDATION_ERROR)
        self.assertFalse(err.retryable)


# ─────────────────────────────────────────────────────────────────────────────
# CSV connector
# ─────────────────────────────────────────────────────────────────────────────

class TestCsvConnector(unittest.TestCase):

    def _make_products_csv(self) -> str:
        lines = [
            "code,name,price_minor,stock_quantity,unit",
            "SKU-001,محصول اول,100000,50,عدد",
            "SKU-002,محصول دوم,200000,30,جعبه",
            "SKU-003,محصول سوم,0,0,",   # minimal row
        ]
        return "\n".join(lines)

    def _make_prices_csv(self) -> str:
        return "code,price_minor\nSKU-001,150000\nSKU-002,250000\n"

    def _make_inventory_csv(self) -> str:
        return "code,stock_quantity\nSKU-001,99\nSKU-002,10\n"

    def test_load_products_csv(self):
        connector = CsvConnector(config={"feed_type": "products"})
        result = connector.load_content(self._make_products_csv())
        self.assertEqual(result["rows_loaded"], 3)
        self.assertEqual(len(result["errors"]), 0)

    def test_pull_products(self):
        connector = CsvConnector(config={"feed_type": "products"})
        connector.load_content(self._make_products_csv())
        products, cursor = connector.pull_products(limit=10)
        codes = [p["code"] for p in products]
        self.assertIn("SKU-001", codes)
        self.assertIn("SKU-002", codes)
        self.assertIsNone(cursor)

    def test_pull_products_pagination(self):
        connector = CsvConnector(config={"feed_type": "products"})
        connector.load_content(self._make_products_csv())
        page1, _ = connector.pull_products(limit=2, offset=0)
        page2, _ = connector.pull_products(limit=2, offset=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 1)

    def test_pull_prices(self):
        connector = CsvConnector(config={"feed_type": "prices"})
        connector.load_content(self._make_prices_csv())
        prices, _ = connector.pull_prices()
        self.assertEqual(len(prices), 2)
        price_map = {p["code"]: p["price_minor"] for p in prices}
        self.assertEqual(price_map["SKU-001"], 150000)
        self.assertEqual(price_map["SKU-002"], 250000)

    def test_pull_inventory(self):
        connector = CsvConnector(config={"feed_type": "inventory"})
        connector.load_content(self._make_inventory_csv())
        inv, _ = connector.pull_inventory()
        self.assertEqual(len(inv), 2)
        inv_map = {i["code"]: i["stock_quantity"] for i in inv}
        self.assertEqual(inv_map["SKU-001"], 99)

    def test_pull_inventory_filter_by_code(self):
        connector = CsvConnector(config={"feed_type": "inventory"})
        connector.load_content(self._make_inventory_csv())
        inv, _ = connector.pull_inventory(product_codes=["SKU-001"])
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["code"], "SKU-001")

    def test_csv_injection_sanitised(self):
        csv_data = "code,name,price_minor,stock_quantity\n=EVIL(),safe name,100,1\n"
        connector = CsvConnector(config={"feed_type": "products"})
        connector.load_content(csv_data)
        products, _ = connector.pull_products()
        # The =EVIL() code should be sanitised with leading apostrophe
        self.assertTrue(products[0]["code"].startswith("'") or products[0]["code"] == "")

    def test_semicolon_delimited_csv(self):
        csv_data = "code;name;price_minor;stock_quantity\nSKU-A;نام;50000;10\n"
        rows, errors = parse_csv_feed(csv_data, expected_columns={"code", "name"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 0)

    def test_tab_delimited_csv(self):
        csv_data = "code\tname\tprice_minor\tstock_quantity\nSKU-B\tنام\t60000\t5\n"
        rows, errors = parse_csv_feed(csv_data, expected_columns={"code", "name"})
        self.assertEqual(len(rows), 1)

    def test_missing_required_column_raises(self):
        csv_data = "only_name,price_minor\nfoo,100\n"
        from app.adapters.connectors.base import ConnectorError
        with self.assertRaises(ConnectorError) as ctx:
            parse_csv_feed(csv_data, expected_columns={"code", "name"})
        self.assertIn("code", str(ctx.exception))

    def test_resolve_product_by_code(self):
        connector = CsvConnector(config={"feed_type": "products"})
        connector.load_content(self._make_products_csv())
        result = connector.resolve_product(identifier_type="code", identifier_value="SKU-001")
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "SKU-001")

    def test_resolve_product_not_found(self):
        connector = CsvConnector(config={"feed_type": "products"})
        connector.load_content(self._make_products_csv())
        result = connector.resolve_product(identifier_type="code", identifier_value="NOTEXIST")
        self.assertIsNone(result)

    def test_capabilities(self):
        connector = CsvConnector()
        caps = connector.capabilities()
        self.assertIn(CAPABILITY_PULL_PRODUCTS, caps.supported)
        self.assertIn(CAPABILITY_PULL_PRICES, caps.supported)
        self.assertIn(CAPABILITY_PULL_INVENTORY, caps.supported)
        self.assertEqual(caps.transport, "FILE")

    def test_health_check_always_healthy(self):
        connector = CsvConnector()
        result = connector.health_check()
        self.assertTrue(result["healthy"])


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorRegistry(unittest.TestCase):

    def test_manual_adapter(self):
        adapter = get_adapter("MANUAL")
        health = adapter.health_check()
        self.assertTrue(health["healthy"])

    def test_csv_import_adapter(self):
        adapter = get_adapter("CSV_IMPORT")
        self.assertIsInstance(adapter, CsvConnector)

    def test_mock_erp_adapter(self):
        adapter = get_adapter("MOCK_ERP")
        health = adapter.health_check()
        self.assertTrue(health["healthy"])

    def test_unknown_type_raises(self):
        with self.assertRaises(ValidationError):
            get_adapter("ABSOLUTELY_UNKNOWN_TYPE_XYZ")

    def test_not_implemented_stubs_raise(self):
        for stub_type in ["SEPIDAR_ERP", "HOLO_ERP", "ALOPEYK", "POST_IR", "TIPAX", "CHAPAR"]:
            adapter = get_adapter(stub_type)
            self.assertFalse(adapter.health_check()["healthy"],
                             f"{stub_type} should report unhealthy")
            with self.assertRaises(ConnectorError) as ctx:
                adapter.pull_products()
            self.assertEqual(ctx.exception.code, ConnectorErrorCode.NOT_IMPLEMENTED)

    def test_list_connector_types(self):
        types = list_connector_types()
        type_strs = [t["type"] for t in types]
        self.assertIn("MANUAL", type_strs)
        self.assertIn("CSV_IMPORT", type_strs)
        self.assertIn("SEPIDAR_ERP", type_strs)

    def test_capability_declaration_to_dict(self):
        adapter = get_adapter("CSV_IMPORT")
        caps = adapter.capabilities()
        self.assertIsInstance(caps, CapabilityDeclaration)
        d = caps.to_dict()
        self.assertIn("connector_type", d)
        self.assertIn("supported", d)


if __name__ == "__main__":
    unittest.main()
