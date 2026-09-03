"""Column Recognition Service.

Maps raw CSV/XLSX column headers to canonical field names using
alias dictionaries. Supports Persian and English headers.
"""
from __future__ import annotations

COLUMN_ALIASES: dict[str, list[str]] = {
    "barcode": [
        "barcode", "barkod", "bar_code", "باركد", "بارکد", "کد بارکد",
        "EAN", "GTIN", "UPC", "گتین",
    ],
    "sku": [
        "sku", "SKU", "کد کالا", "کد محصول", "شناسه کالا",
        "supplier_sku", "کد تأمین‌کننده",
    ],
    "erp_code": [
        "erp_code", "کد ERP", "کد سیستم", "product_code",
        "کد خارجی", "code",
    ],
    "name_fa": [
        "name_fa", "نام", "نام فارسی", "عنوان", "محصول", "کالا",
        "title_fa", "product_name", "name",
    ],
    "price_minor": [
        "price", "price_minor", "قیمت", "بها", "selling_price",
        "قیمت فروش", "unit_price_minor",
    ],
    "stock_quantity": [
        "stock", "quantity", "موجودی", "تعداد", "stock_quantity",
        "qty",
    ],
    "brand_fa": [
        "brand", "برند", "brand_fa", "مارک",
    ],
    "category": [
        "category", "دسته‌بندی", "گروه", "طبقه", "category_fa",
    ],
    "description_fa": [
        "description", "توضیحات", "description_fa", "شرح",
    ],
}


def _normalize(s: str) -> str:
    """Normalize a string for comparison: strip, lowercase, remove extra spaces."""
    return s.strip().lower().replace("‌", "").replace("  ", " ")


def recognize_columns(headers: list[str]) -> dict[str, str]:
    """
    Map raw CSV/XLSX headers to canonical field names.

    Args:
        headers: List of raw column header strings

    Returns:
        {raw_header: canonical_field_name}
        Only includes headers that were successfully recognized.
    """
    result: dict[str, str] = {}

    # Build lookup: normalized_alias → canonical
    alias_map: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_map[_normalize(alias)] = canonical

    for header in headers:
        normalized = _normalize(header)
        if normalized in alias_map:
            canonical = alias_map[normalized]
            result[header] = canonical

    return result


def suggest_column_map(headers: list[str]) -> dict[str, str | None]:
    """
    Suggest a column mapping for all headers.

    Returns:
        {raw_header: canonical_field_name | None}
        All headers are included, with None for unrecognized ones.
    """
    recognized = recognize_columns(headers)
    return {h: recognized.get(h) for h in headers}


def build_column_map_json(headers: list[str]) -> dict:
    """
    Build a column_map_json suitable for saving to import_column_templates.

    Returns:
        {"canonical_field": "raw_header"} for recognized columns
    """
    recognized = recognize_columns(headers)
    # Invert: canonical → raw_header (first match wins)
    result: dict[str, str] = {}
    for raw_header, canonical in recognized.items():
        if canonical not in result:
            result[canonical] = raw_header
    return result
