"""Mock ERP V2 connector — deterministic 10,000-product dataset.

Provides a large-scale ERP simulation for testing zero-touch auto-discovery,
pagination, outage simulation, and malformed-row isolation.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
This mock is for testing only.

Dataset characteristics:
  - TOTAL_PRODUCTS = 10,000
  - 50 Persian categories × 200 products each
  - Deterministic generation from product index
  - Pagination via pull_products(offset, limit)
  - Outage simulation via config['simulate_outage']
  - Malformed row injection via config['inject_malformed']
"""
from __future__ import annotations

from typing import Generator

from app.adapters.connectors.base import ConnectorAdapter

TOTAL_PRODUCTS = 10_000

_CATEGORIES = [
    "مواد غذایی", "لبنیات", "نوشیدنی", "میوه و سبزیجات", "گوشت و مرغ",
    "برنج و حبوبات", "روغن و چربی", "قند و شکر", "کنسرو و ترشی", "ادویه و چاشنی",
    "لوازم خانگی", "لوازم برقی", "تلفن و موبایل", "رایانه و لپ‌تاپ", "دوربین و عکاسی",
    "پوشاک مردانه", "پوشاک زنانه", "پوشاک کودک", "کفش و کتانی", "کیف و کوله",
    "لوازم آرایشی", "بهداشت شخصی", "داروخانه", "ویتامین و مکمل", "لوازم ورزشی",
    "اسباب‌بازی", "کتاب و مجله", "لوازم‌التحریر", "هنر و دستکار", "موسیقی",
    "مبل و دکور", "فرش و پادری", "لوازم آشپزخانه", "ابزار و یراق", "گل و گیاه",
    "خودرو و موتور", "لوازم یدکی", "روغن و فیلتر", "لاستیک و رینگ", "لوازم برقی خودرو",
    "محصولات کشاورزی", "دام و طیور", "آبزیان", "محصولات ارگانیک", "عسل و زنبورداری",
    "صنایع دستی", "سوغات ایرانی", "قهوه و چای", "شیرینی و شکلات", "آجیل و خشکبار",
]

_SYNC_TIMESTAMP = "2026-08-08T10:00:00.000Z"


class ConnectorOutageError(RuntimeError):
    """Raised when the adapter is configured to simulate an outage."""
    pass


def _make_product(i: int) -> dict:
    """Generate a deterministic product dict from index i (0-9999)."""
    cat_idx = i // 200  # 50 categories, 200 products each
    cat_name = _CATEGORIES[cat_idx % len(_CATEGORIES)]
    within_cat = i % 200

    code = f"ERP-{i:05d}"
    barcode = f"626{i:010d}"  # 13 chars total for EAN-13 style
    name_fa = f"{cat_name} — مدل {within_cat + 1}"
    price_minor = (1000 + (i % 100) * 1000) * 1000  # 1M-100M Rials — INTEGER, no float
    stock = i % 150  # 0-149

    return {
        "code": code,
        "name": name_fa,
        "name_fa": name_fa,
        "unit": "عدد",
        "price_minor": price_minor,
        "currency": "IRR",
        "stock_quantity": stock,
        "barcode": barcode,
        "sku": f"AUTO-{i:05d}",
        "category": cat_name,
        "synced_at": _SYNC_TIMESTAMP,
    }


class MockErpV2Connector(ConnectorAdapter):
    """
    Deterministic mock ERP adapter with 10,000 products.

    Supports:
    - Pagination via pull_products(offset, limit)
    - Generator via pull_products_all()
    - Outage simulation via config['simulate_outage']
    - Malformed row injection via config['inject_malformed']
    """

    adapter_name = "MOCK_ERP_V2"

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def capabilities(self) -> dict:
        return {
            "connector_type": "MOCK_ERP_V2",
            "supports_pull_products": True,
            "supports_pull_prices": True,
            "supports_pull_inventory": True,
            "supports_push_order": True,
            "supports_resolve_product": True,
            "supports_generator": True,
            "total_products": TOTAL_PRODUCTS,
        }

    def _check_outage(self) -> None:
        if self._config.get("simulate_outage", False):
            raise ConnectorOutageError("اتصال ERP قطع شده (شبیه‌سازی اختلال)")

    def health_check(self) -> dict:
        if self._config.get("simulate_outage", False):
            return {
                "healthy": False,
                "message": "MOCK_ERP_V2 — اختلال شبیه‌سازی‌شده",
                "latency_ms": None,
            }
        return {
            "healthy": True,
            "message": f"MOCK_ERP_V2 — آماده ({TOTAL_PRODUCTS:,} محصول)",
            "latency_ms": 0,
        }

    def pull_products(self, *, limit: int = 100, offset: int = 0) -> dict:
        """
        Return paginated product page.
        Returns {"items": [...], "total": 10000, "offset": offset, "limit": limit}
        """
        self._check_outage()
        items = []
        end = min(offset + limit, TOTAL_PRODUCTS)
        for i in range(offset, end):
            product = _make_product(i)
            if i == 0 and self._config.get("inject_malformed", False):
                product = {"code": "MALFORMED", "broken": True}  # intentionally bad
            items.append(product)
        return {
            "items": items,
            "total": TOTAL_PRODUCTS,
            "offset": offset,
            "limit": limit,
        }

    def pull_products_all(self) -> Generator[dict, None, None]:
        """
        Generator that yields all 10,000 products one by one.
        Memory-bounded: does not load all into memory at once.
        """
        self._check_outage()
        for i in range(TOTAL_PRODUCTS):
            product = _make_product(i)
            if i == 0 and self._config.get("inject_malformed", False):
                product = {"code": "MALFORMED", "broken": True}
            yield product

    def pull_prices(self, *, product_codes: list[str] | None = None) -> list[dict]:
        self._check_outage()
        if product_codes:
            results = []
            for code in product_codes:
                if code.startswith("ERP-"):
                    try:
                        i = int(code[4:])
                        p = _make_product(i)
                        results.append({
                            "code": code,
                            "price_minor": p["price_minor"],
                            "currency": "IRR",
                            "updated_at": _SYNC_TIMESTAMP,
                        })
                    except (ValueError, IndexError):
                        pass
            return results
        # Return prices for all products in batches (not loaded all at once)
        return [
            {
                "code": f"ERP-{i:05d}",
                "price_minor": (1000 + (i % 100) * 1000) * 1000,
                "currency": "IRR",
                "updated_at": _SYNC_TIMESTAMP,
            }
            for i in range(TOTAL_PRODUCTS)
        ]

    def pull_inventory(self, *, product_codes: list[str] | None = None) -> list[dict]:
        self._check_outage()
        if product_codes:
            results = []
            for code in product_codes:
                if code.startswith("ERP-"):
                    try:
                        i = int(code[4:])
                        results.append({
                            "code": code,
                            "stock_quantity": i % 150,
                            "location_id": "warehouse_main",
                            "updated_at": _SYNC_TIMESTAMP,
                        })
                    except (ValueError, IndexError):
                        pass
            return results
        return [
            {
                "code": f"ERP-{i:05d}",
                "stock_quantity": i % 150,
                "location_id": "warehouse_main",
                "updated_at": _SYNC_TIMESTAMP,
            }
            for i in range(TOTAL_PRODUCTS)
        ]

    def push_order(self, order_data: dict) -> dict:
        self._check_outage()
        if not order_data.get("order_id"):
            return {"acknowledged": False, "external_ref": None, "message": "شناسه سفارش الزامی است"}
        return {
            "acknowledged": True,
            "external_ref": f"MOCK-V2-PO-{order_data['order_id']}",
            "message": "سفارش در MOCK_ERP_V2 ثبت شد",
        }

    def resolve_product(self, *, identifier_type: str, identifier_value: str) -> dict | None:
        self._check_outage()
        if identifier_type == "barcode":
            if identifier_value.startswith("626") and len(identifier_value) == 13:
                try:
                    idx = int(identifier_value[3:])
                    if 0 <= idx < TOTAL_PRODUCTS:
                        return _make_product(idx)
                except ValueError:
                    pass
        elif identifier_type == "erp_code":
            if identifier_value.startswith("ERP-"):
                try:
                    idx = int(identifier_value[4:])
                    if 0 <= idx < TOTAL_PRODUCTS:
                        return _make_product(idx)
                except ValueError:
                    pass
        elif identifier_type == "sku":
            if identifier_value.startswith("AUTO-"):
                try:
                    idx = int(identifier_value[5:])
                    if 0 <= idx < TOTAL_PRODUCTS:
                        return _make_product(idx)
                except ValueError:
                    pass
        return None
