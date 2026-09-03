"""Mock product knowledge catalogue.

Deterministic mock that returns product data for EAN barcodes in range 626XXXXXXXXXX.
Matches the barcode format used by MockErpV2 (626{i:010d}).

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
This mock is for testing only.
"""
from __future__ import annotations

from app.adapters.knowledge.base import ProductKnowledgeSource

_CATEGORIES_FA = [
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


def _barcode_to_index(barcode: str) -> int | None:
    """Parse a 626XXXXXXXXXX barcode to a product index 0-9999."""
    if not barcode or len(barcode) != 13:
        return None
    if not barcode.startswith("626"):
        return None
    try:
        idx = int(barcode[3:])
    except ValueError:
        return None
    if 0 <= idx <= 9999:
        return idx
    return None


def _make_product(idx: int) -> dict:
    """Generate deterministic product data from index."""
    cat_idx = idx // 200
    cat_name = _CATEGORIES_FA[cat_idx % len(_CATEGORIES_FA)]
    within_cat = idx % 200
    barcode = f"626{idx:010d}"
    name_fa = f"{cat_name} — مدل {within_cat + 1}"
    price_minor = (1000 + (idx % 100) * 1000) * 1000  # 1M-100M Rials, INTEGER
    stock = idx % 150

    return {
        "barcode": barcode,
        "sku": f"MC-{idx:05d}",
        "name_fa": name_fa,
        "brand_fa": f"برند {cat_idx + 1}",
        "category_hint": cat_name,
        "price_minor": price_minor,
        "stock": stock,
        "source": "mock_catalogue",
        "confidence_bps": 9000,
    }


class MockCatalogueKnowledgeSource(ProductKnowledgeSource):
    """
    Deterministic mock product knowledge source.
    Covers EAN barcodes 6260000000000 - 6260000009999.
    """

    adapter_key = "mock_catalogue"

    def lookup_by_identifier(self, identifier_type: str, identifier_value: str) -> dict | None:
        if identifier_type == "barcode":
            idx = _barcode_to_index(identifier_value)
            if idx is not None:
                return _make_product(idx)
        elif identifier_type == "sku" and identifier_value.startswith("MC-"):
            try:
                idx = int(identifier_value[3:])
            except ValueError:
                return None
            if 0 <= idx <= 9999:
                return _make_product(idx)
        return None

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": "mock_catalogue — آماده (10000 محصول در پوشش)",
            "latency_ms": 0,
        }

    def capabilities(self) -> list[str]:
        return ["lookup_by_identifier", "barcode_lookup", "sku_lookup"]
