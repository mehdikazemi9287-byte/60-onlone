"""Tax Adapter Registry — Phase 7.

Maps tax_system strings to adapter classes.

TAX ADAPTER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

from app.adapters.tax.base import TaxAdapter
from app.adapters.tax.mock import MockTaxAdapter
from app.adapters.tax.moadian import MoadianTaxAdapter
from app.core.errors import ValidationError


_REGISTRY: dict[str, type[TaxAdapter]] = {
    "MOCK": MockTaxAdapter,
    "MOCK_TAX": MockTaxAdapter,
    "MOADIAN": MoadianTaxAdapter,
}


def get_tax_adapter(
    tax_system: str,
    *,
    config: dict | None = None,
) -> TaxAdapter:
    """Return a TaxAdapter for the given tax_system string.

    Raises:
        ValidationError: Unknown tax_system.
    """
    key = tax_system.upper().strip()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ValidationError(
            f"سیستم مالیاتی '{tax_system}' ناشناخته است. "
            f"گزینه‌های معتبر: {', '.join(sorted(_REGISTRY))}"
        )
    if cls is MockTaxAdapter:
        return cls()
    return cls(config=config)


def list_tax_systems() -> list[dict]:
    """Return metadata for all registered tax systems."""
    return [
        {
            "system": "MOCK",
            "label": "آزمایشی (Mock)",
            "implementation_status": "simulator",
            "description": "سیستم مالیاتی درون‌حافظه برای تست",
            "verified_docs_url": None,
        },
        {
            "system": "MOADIAN",
            "label": "سامانه مودیان",
            "implementation_status": "not_implemented",
            "description": "سامانه مودیان ایران — REAL PROVIDER: NOT IMPLEMENTED",
            "verified_docs_url": "https://www.tax.gov.ir/",
        },
    ]
