"""Mock ERP connector adapter — deterministic, full-featured.

This adapter provides a realistic simulation of an ERP system for testing
and demonstration purposes. It returns DETERMINISTIC data — no randomness,
no external network calls, no file I/O.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
Do NOT fabricate real APIs for Holo/Sepidar/Rahkaran/etc.
This mock is for testing only.

The mock ERP maintains an in-memory catalogue of products with prices and
inventory levels. The dataset is controlled by the `dataset` constructor
argument:
  "products" — full catalogue (20 products, varied prices/stock)
  "minimal"  — 3 products (for small test cases)
  "empty"    — no products (tests empty-sync handling)
"""
from __future__ import annotations

import datetime
from typing import Any

from app.adapters.connectors.base import ConnectorAdapter


# ── Mock product data ──────────────────────────────────────────────────────────

_MOCK_PRODUCTS_FULL: list[dict] = [
    {"code": "ERP-001", "name": "کاغذ A4 رامه",         "unit": "بسته", "price_minor": 850000,   "currency": "IRR", "stock_quantity": 200, "barcode": "6260001000010", "sku": "PAPER-A4-500"},
    {"code": "ERP-002", "name": "لپ‌تاپ ایسوس X515",    "unit": "دستگاه","price_minor": 28000000, "currency": "IRR", "stock_quantity": 15,  "barcode": "6260001000027", "sku": "LAPTOP-X515"},
    {"code": "ERP-003", "name": "گوشی سامسونگ A52",     "unit": "دستگاه","price_minor": 15000000, "currency": "IRR", "stock_quantity": 30,  "barcode": "6260001000034", "sku": "PHONE-A52"},
    {"code": "ERP-004", "name": "مداد مشکی فابر",       "unit": "جعبه", "price_minor": 120000,   "currency": "IRR", "stock_quantity": 500, "barcode": "6260001000041", "sku": "PENCIL-FABER-12"},
    {"code": "ERP-005", "name": "خودکار بیک کریستال",   "unit": "جعبه", "price_minor": 90000,    "currency": "IRR", "stock_quantity": 750, "barcode": "6260001000058", "sku": "PEN-BIC-10"},
    {"code": "ERP-006", "name": "پرینتر اچ‌پی لیزری",  "unit": "دستگاه","price_minor": 12000000, "currency": "IRR", "stock_quantity": 8,   "barcode": "6260001000065", "sku": "PRINTER-HP-1102W"},
    {"code": "ERP-007", "name": "تونر اچ‌پی ۸۵A",       "unit": "عدد",  "price_minor": 2500000,  "currency": "IRR", "stock_quantity": 40,  "barcode": "6260001000072", "sku": "TONER-HP-85A"},
    {"code": "ERP-008", "name": "مانیتور ال‌جی 24inch", "unit": "دستگاه","price_minor": 9500000,  "currency": "IRR", "stock_quantity": 12,  "barcode": "6260001000089", "sku": "MON-LG-24"},
    {"code": "ERP-009", "name": "کیبورد لاجیتک K120",   "unit": "دستگاه","price_minor": 750000,   "currency": "IRR", "stock_quantity": 60,  "barcode": "6260001000096", "sku": "KB-LOGI-K120"},
    {"code": "ERP-010", "name": "موس لاجیتک M100",      "unit": "دستگاه","price_minor": 500000,   "currency": "IRR", "stock_quantity": 80,  "barcode": "6260001000102", "sku": "MOUSE-LOGI-M100"},
    {"code": "ERP-011", "name": "فلش سندیسک 32GB",      "unit": "عدد",  "price_minor": 450000,   "currency": "IRR", "stock_quantity": 150, "barcode": "6260001000119", "sku": "USB-SD-32"},
    {"code": "ERP-012", "name": "هارد اکسترنال وسترن 1TB","unit":"دستگاه","price_minor":6500000,  "currency": "IRR", "stock_quantity": 20,  "barcode": "6260001000126", "sku": "HDD-WD-1TB"},
    {"code": "ERP-013", "name": "تبلت سامسونگ A7",      "unit": "دستگاه","price_minor": 18000000, "currency": "IRR", "stock_quantity": 10,  "barcode": "6260001000133", "sku": "TAB-SAM-A7"},
    {"code": "ERP-014", "name": "هدفون سونی WH-1000XM4","unit": "دستگاه","price_minor": 25000000, "currency": "IRR", "stock_quantity": 7,   "barcode": "6260001000140", "sku": "HP-SONY-WH1000"},
    {"code": "ERP-015", "name": "کابل شارژ USB-C 1M",   "unit": "عدد",  "price_minor": 150000,   "currency": "IRR", "stock_quantity": 300, "barcode": "6260001000157", "sku": "CABLE-USBC-1M"},
    {"code": "ERP-016", "name": "پاوربانک انکر 20000",  "unit": "عدد",  "price_minor": 3500000,  "currency": "IRR", "stock_quantity": 25,  "barcode": "6260001000164", "sku": "PB-ANKER-20K"},
    {"code": "ERP-017", "name": "ماوس پد گیمینگ SteelSeries","unit":"عدد","price_minor":1200000,  "currency": "IRR", "stock_quantity": 45,  "barcode": "6260001000171", "sku": "MP-SS-XL"},
    {"code": "ERP-018", "name": "وب‌کم لاجیتک C920",    "unit": "دستگاه","price_minor": 4500000,  "currency": "IRR", "stock_quantity": 18,  "barcode": "6260001000188", "sku": "CAM-LOGI-C920"},
    {"code": "ERP-019", "name": "اسپیکر JBL Flip 5",    "unit": "دستگاه","price_minor": 5500000,  "currency": "IRR", "stock_quantity": 22,  "barcode": "6260001000195", "sku": "SPK-JBL-FLIP5"},
    {"code": "ERP-020", "name": "روتر TP-Link Archer",  "unit": "دستگاه","price_minor": 3200000,  "currency": "IRR", "stock_quantity": 35,  "barcode": "6260001000201", "sku": "ROUTER-TP-AC10"},
]

_MOCK_PRODUCTS_MINIMAL: list[dict] = [
    {"code": "ERP-001", "name": "کاغذ A4 رامه",       "unit": "بسته", "price_minor": 850000,  "currency": "IRR", "stock_quantity": 200, "barcode": "6260001000010", "sku": "PAPER-A4-500"},
    {"code": "ERP-002", "name": "لپ‌تاپ ایسوس X515",  "unit": "دستگاه","price_minor": 28000000,"currency": "IRR", "stock_quantity": 15,  "barcode": "6260001000027", "sku": "LAPTOP-X515"},
    {"code": "ERP-003", "name": "گوشی سامسونگ A52",   "unit": "دستگاه","price_minor": 15000000,"currency": "IRR", "stock_quantity": 30,  "barcode": "6260001000034", "sku": "PHONE-A52"},
]

_MOCK_PRODUCTS_EMPTY: list[dict] = []

_DATASETS = {
    "products": _MOCK_PRODUCTS_FULL,
    "minimal": _MOCK_PRODUCTS_MINIMAL,
    "empty": _MOCK_PRODUCTS_EMPTY,
}

_SYNC_TIMESTAMP = "2026-08-08T10:00:00.000Z"


class MockErpConnector(ConnectorAdapter):
    """
    Deterministic mock ERP adapter.
    Returns static data — no external calls, no randomness.
    """

    adapter_name = "MOCK_ERP"

    def __init__(self, dataset: str = "products"):
        self._dataset = dataset
        self._products: list[dict] = list(_DATASETS.get(dataset, _MOCK_PRODUCTS_FULL))

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": f"MOCK_ERP — آماده (مجموعه: {self._dataset}, {len(self._products)} محصول)",
            "latency_ms": 0,
        }

    def pull_products(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        page = self._products[offset: offset + limit]
        return [self._format_product(p) for p in page]

    def pull_prices(self, *, product_codes: list[str] | None = None) -> list[dict]:
        products = self._products
        if product_codes:
            codes_set = set(product_codes)
            products = [p for p in products if p["code"] in codes_set]
        return [
            {
                "code": p["code"],
                "price_minor": p["price_minor"],
                "currency": p["currency"],
                "updated_at": _SYNC_TIMESTAMP,
            }
            for p in products
        ]

    def pull_inventory(self, *, product_codes: list[str] | None = None) -> list[dict]:
        products = self._products
        if product_codes:
            codes_set = set(product_codes)
            products = [p for p in products if p["code"] in codes_set]
        return [
            {
                "code": p["code"],
                "stock_quantity": p["stock_quantity"],
                "location_id": "warehouse_1",
                "updated_at": _SYNC_TIMESTAMP,
            }
            for p in products
        ]

    def push_order(self, order_data: dict) -> dict:
        # Mock acknowledgement — always succeeds for valid data
        if not order_data.get("order_id"):
            return {"acknowledged": False, "external_ref": None, "message": "شناسه سفارش الزامی است"}
        return {
            "acknowledged": True,
            "external_ref": f"MOCK-PO-{order_data['order_id']}",
            "message": "سفارش با موفقیت در سیستم mock ثبت شد",
        }

    def resolve_product(self, *, identifier_type: str, identifier_value: str) -> dict | None:
        """Look up a product by barcode, SKU, or ERP code."""
        field_map = {
            "barcode": "barcode",
            "sku": "sku",
            "erp_code": "code",
        }
        field = field_map.get(identifier_type)
        if not field:
            return None
        for p in self._products:
            if p.get(field) == identifier_value:
                return self._format_product(p)
        return None

    def _format_product(self, p: dict) -> dict:
        return {
            "code": p["code"],
            "name": p["name"],
            "unit": p.get("unit", "عدد"),
            "price_minor": p["price_minor"],
            "currency": p["currency"],
            "stock_quantity": p["stock_quantity"],
            "barcode": p.get("barcode"),
            "sku": p.get("sku"),
            "synced_at": _SYNC_TIMESTAMP,
        }
