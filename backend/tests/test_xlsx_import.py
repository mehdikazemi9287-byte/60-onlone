"""Tests for xlsx_import_service and column_recognition_service — Phase 6 Final."""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import column_recognition_service as crs
from app.core.errors import ValidationError


class ColumnRecognitionTest(unittest.TestCase):

    def test_recognize_english_headers(self):
        headers = ["barcode", "sku", "name_fa", "price", "stock"]
        result = crs.recognize_columns(headers)
        self.assertEqual(result["barcode"], "barcode")
        self.assertEqual(result["sku"], "sku")
        self.assertEqual(result["name_fa"], "name_fa")
        self.assertEqual(result["price"], "price_minor")
        self.assertEqual(result["stock"], "stock_quantity")

    def test_recognize_persian_headers(self):
        headers = ["بارکد", "کد کالا", "نام", "قیمت", "موجودی"]
        result = crs.recognize_columns(headers)
        self.assertEqual(result["بارکد"], "barcode")
        self.assertEqual(result["کد کالا"], "sku")
        self.assertEqual(result["نام"], "name_fa")
        self.assertEqual(result["قیمت"], "price_minor")
        self.assertEqual(result["موجودی"], "stock_quantity")

    def test_recognize_mixed_headers(self):
        headers = ["EAN", "SKU", "نام فارسی", "selling_price", "تعداد"]
        result = crs.recognize_columns(headers)
        self.assertEqual(result["EAN"], "barcode")
        self.assertEqual(result["SKU"], "sku")
        self.assertEqual(result["نام فارسی"], "name_fa")
        self.assertEqual(result["selling_price"], "price_minor")
        self.assertEqual(result["تعداد"], "stock_quantity")

    def test_unrecognized_headers_not_in_result(self):
        headers = ["unknown_col", "barcode", "xyz"]
        result = crs.recognize_columns(headers)
        self.assertNotIn("unknown_col", result)
        self.assertNotIn("xyz", result)
        self.assertIn("barcode", result)

    def test_suggest_column_map_includes_all_headers(self):
        headers = ["barcode", "unknown_col", "قیمت"]
        result = crs.suggest_column_map(headers)
        self.assertIn("barcode", result)
        self.assertIn("unknown_col", result)
        self.assertIsNone(result["unknown_col"])
        self.assertEqual(result["قیمت"], "price_minor")

    def test_build_column_map_json(self):
        headers = ["بارکد", "نام", "قیمت"]
        result = crs.build_column_map_json(headers)
        self.assertIn("barcode", result)
        self.assertIn("name_fa", result)
        self.assertIn("price_minor", result)


def _make_xlsx(rows: list[list]) -> bytes:
    """Create a simple XLSX file in memory."""
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except ImportError:
        return None


class XlsxImportTest(unittest.TestCase):

    def setUp(self):
        try:
            import openpyxl  # noqa
            self.has_openpyxl = True
        except ImportError:
            self.has_openpyxl = False

    def _skip_if_no_openpyxl(self):
        if not self.has_openpyxl:
            self.skipTest("openpyxl not installed")

    def test_parse_xlsx_basic(self):
        self._skip_if_no_openpyxl()
        from app.services.xlsx_import_service import parse_xlsx

        xlsx_bytes = _make_xlsx([
            ["barcode", "name_fa", "price_minor", "stock_quantity"],
            ["6260000000001", "محصول ۱", 1000000, 10],
            ["6260000000002", "محصول ۲", 2000000, 20],
        ])

        column_map = {
            "barcode": "barcode",
            "name_fa": "name_fa",
            "price_minor": "price_minor",
            "stock_quantity": "stock_quantity",
        }
        result = parse_xlsx(xlsx_bytes, column_map)

        self.assertEqual(result["total_rows"], 2)
        self.assertEqual(result["valid_rows"], 2)
        self.assertEqual(result["error_rows"], 0)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["barcode"], "6260000000001")
        self.assertEqual(result["rows"][0]["price_minor"], 1000000)
        self.assertIsInstance(result["rows"][0]["price_minor"], int)

    def test_parse_xlsx_persian_headers(self):
        self._skip_if_no_openpyxl()
        from app.services.xlsx_import_service import parse_xlsx

        # Use Persian headers, map them manually
        xlsx_bytes = _make_xlsx([
            ["بارکد", "نام", "قیمت", "موجودی"],
            ["6260000000001", "محصول فارسی", 3000000, 5],
        ])
        # Map Persian column names to canonical
        column_map = {
            "barcode": "بارکد",
            "name_fa": "نام",
            "price_minor": "قیمت",
            "stock_quantity": "موجودی",
        }
        result = parse_xlsx(xlsx_bytes, column_map)
        self.assertEqual(result["total_rows"], 1)
        self.assertEqual(result["valid_rows"], 1)
        self.assertIsInstance(result["rows"][0]["price_minor"], int)

    def test_parse_xlsx_rejects_float_price(self):
        self._skip_if_no_openpyxl()
        from app.services.xlsx_import_service import parse_xlsx

        xlsx_bytes = _make_xlsx([
            ["barcode", "price_minor"],
            ["6260000000001", 1500000.5],  # Float — must be rejected
        ])
        column_map = {
            "barcode": "barcode",
            "price_minor": "price_minor",
        }
        result = parse_xlsx(xlsx_bytes, column_map)
        # Should have an error row for float price
        self.assertGreater(result["error_rows"], 0)
        self.assertGreater(len(result["errors"]), 0)

    def test_parse_xlsx_empty_file(self):
        self._skip_if_no_openpyxl()
        from app.services.xlsx_import_service import parse_xlsx

        xlsx_bytes = _make_xlsx([["barcode", "name_fa"]])  # Header only
        result = parse_xlsx(xlsx_bytes, {"barcode": "barcode", "name_fa": "name_fa"})
        self.assertEqual(result["total_rows"], 0)
        self.assertEqual(result["valid_rows"], 0)

    def test_xlsx_column_recognition_integration(self):
        self._skip_if_no_openpyxl()
        from app.services.xlsx_import_service import parse_xlsx

        # Create XLSX with EAN header (recognized as barcode)
        xlsx_bytes = _make_xlsx([
            ["EAN", "product_name", "price"],
            ["6260000000001", "محصول تست", 5000000],
        ])
        # First recognize columns
        headers = ["EAN", "product_name", "price"]
        recognized = crs.recognize_columns(headers)
        # Build reverse map: canonical → raw_header
        col_map = {v: k for k, v in recognized.items()}

        result = parse_xlsx(xlsx_bytes, col_map)
        self.assertEqual(result["total_rows"], 1)


if __name__ == "__main__":
    unittest.main()
