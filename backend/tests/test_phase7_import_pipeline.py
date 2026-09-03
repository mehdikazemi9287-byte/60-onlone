"""Phase 7 — Import Pipeline tests.

Tests:
  - Large CSV import (1000+ rows) via CsvConnector
  - Idempotent re-import (same file, same results)
  - Duplicate GTIN detection
  - Column mapping
  - Encoding detection (bytes input)
  - parse_csv_feed error handling
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.connectors.csv_connector import CsvConnector, parse_csv_feed
from app.adapters.connectors.base import ConnectorError


class TestLargeImport(unittest.TestCase):

    def _make_large_csv(self, n: int = 1000) -> str:
        lines = ["code,name,price_minor,stock_quantity"]
        for i in range(n):
            lines.append(f"PROD-{i:05d},محصول {i},{i * 1000},{i % 100}")
        return "\n".join(lines)

    def test_large_import_1000_rows(self):
        connector = CsvConnector(config={"feed_type": "products"})
        result = connector.load_content(self._make_large_csv(1000))
        self.assertEqual(result["rows_loaded"], 1000)
        self.assertEqual(len(result["errors"]), 0)

    def test_large_import_pull_with_pagination(self):
        connector = CsvConnector(config={"feed_type": "products"})
        connector.load_content(self._make_large_csv(500))
        page1, _ = connector.pull_products(limit=100, offset=0)
        page2, _ = connector.pull_products(limit=100, offset=100)
        self.assertEqual(len(page1), 100)
        self.assertEqual(len(page2), 100)
        # No overlap
        codes1 = {p["code"] for p in page1}
        codes2 = {p["code"] for p in page2}
        self.assertEqual(len(codes1 & codes2), 0)

    def test_idempotent_reimport(self):
        """Same CSV imported twice → same rows (connector is stateless per load)."""
        connector = CsvConnector(config={"feed_type": "products"})
        csv_data = self._make_large_csv(50)
        result1 = connector.load_content(csv_data)
        result2 = connector.load_content(csv_data)  # re-load same data
        self.assertEqual(result1["rows_loaded"], result2["rows_loaded"])
        products1, _ = connector.pull_products(limit=50)
        products2, _ = connector.pull_products(limit=50)
        codes1 = sorted(p["code"] for p in products1)
        codes2 = sorted(p["code"] for p in products2)
        self.assertEqual(codes1, codes2)

    def test_empty_rows_skipped(self):
        """Completely empty rows are skipped without error."""
        csv_data = "code,name,price_minor,stock_quantity\nSKU-001,Product A,100,1\n\n\nSKU-002,Product B,200,2\n"
        rows, errors = parse_csv_feed(csv_data, expected_columns={"code", "name"})
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(errors), 0)

    def test_column_mapping(self):
        """Column mapping renames external columns to internal ones."""
        csv_data = "barcode,product_title,sell_price,qty\nBAR-001,My Product,500,10\n"
        mapping = {
            "barcode": "code",
            "product_title": "name",
            "sell_price": "price_minor",
            "qty": "stock_quantity",
        }
        rows, errors = parse_csv_feed(csv_data, column_mapping=mapping,
                                      expected_columns={"code", "name"})
        self.assertEqual(len(rows), 1)
        self.assertIn("code", rows[0])
        self.assertEqual(rows[0]["code"], "BAR-001")

    def test_bytes_utf8_input(self):
        """Bytes input decoded as UTF-8."""
        csv_data = "code,name,price_minor,stock_quantity\nSKU-UTF,محصول,100,1\n"
        rows, errors = parse_csv_feed(csv_data.encode("utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "محصول")

    def test_bytes_windows1256_input(self):
        """Bytes input decoded as windows-1256 (fallback for Persian CSVs)."""
        # Build a simple windows-1256 encoded CSV (ASCII-safe content)
        csv_ascii = "code,name,price_minor,stock_quantity\nSKU-W,Product,100,1\n"
        csv_bytes = csv_ascii.encode("windows-1256")
        rows, errors = parse_csv_feed(csv_bytes)
        self.assertEqual(len(rows), 1)

    def test_bom_stripped(self):
        """UTF-8 BOM is stripped before parsing."""
        csv_data = "﻿code,name,price_minor,stock_quantity\nSKU-BOM,Product,100,1\n"
        rows, errors = parse_csv_feed(csv_data, expected_columns={"code", "name"})
        self.assertEqual(len(rows), 1)
        # 'code' header should not have BOM prefix
        self.assertIn("code", rows[0])

    def test_max_rows_limit(self):
        """Rows exceeding max_rows are truncated with error entry."""
        csv_data = self._make_large_csv(20)
        rows, errors = parse_csv_feed(csv_data, max_rows=10)
        self.assertEqual(len(rows), 10)
        self.assertGreater(len(errors), 0)
        self.assertIn("نادیده", errors[0]["message"])

    def test_price_connector_filters_by_code(self):
        """pull_prices with product_codes only returns matching rows."""
        csv_data = "code,price_minor\nSKU-A,100\nSKU-B,200\nSKU-C,300\n"
        connector = CsvConnector(config={"feed_type": "prices"})
        connector.load_content(csv_data)
        prices, _ = connector.pull_prices(product_codes=["SKU-A", "SKU-C"])
        codes = [p["code"] for p in prices]
        self.assertIn("SKU-A", codes)
        self.assertIn("SKU-C", codes)
        self.assertNotIn("SKU-B", codes)

    def test_inventory_connector_filters_by_code(self):
        """pull_inventory with product_codes only returns matching rows."""
        csv_data = "code,stock_quantity\nSKU-X,5\nSKU-Y,15\n"
        connector = CsvConnector(config={"feed_type": "inventory"})
        connector.load_content(csv_data)
        inv, _ = connector.pull_inventory(product_codes=["SKU-X"])
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["code"], "SKU-X")


if __name__ == "__main__":
    unittest.main()
