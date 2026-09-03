"""Accounting Adapter Registry — Phase 7.

Maps accounting_system strings to adapter classes. Returns a ready-to-use
AccountingAdapter instance.

ACCOUNTING ADAPTER CONTRACT VERSION: 1.0

REAL PROVIDER INTEGRATIONS — NOT IMPLEMENTED:
  Sepidar, Rahkaran, Holo, SAP, Odoo adapters are explicitly marked NOT IMPLEMENTED.
  No endpoints fabricated. No API calls made.

SECURITY:
  - credential_ref is passed through but NEVER logged or stored plaintext.
  - Adapters run in caller's thread; no secrets are shared across tenants.
"""
from __future__ import annotations

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingAdapterError,
)
from app.adapters.accounting.csv_export import CsvAccountingExportAdapter
from app.adapters.accounting.mock import MockAccountingAdapter
from app.adapters.accounting.sepidar import SepidarAccountingAdapter
from app.adapters.accounting.rahkaran import RahkaranAccountingAdapter
from app.adapters.accounting.holo import HoloAccountingAdapter
from app.adapters.accounting.sap import SapAccountingAdapter
from app.adapters.accounting.odoo import OdooAccountingAdapter
from app.core.errors import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[AccountingAdapter]] = {
    "MOCK": MockAccountingAdapter,
    "CSV": CsvAccountingExportAdapter,
    "ACCOUNTING_CSV": CsvAccountingExportAdapter,
    "SEPIDAR": SepidarAccountingAdapter,
    "RAHKARAN": RahkaranAccountingAdapter,
    "HOLO": HoloAccountingAdapter,
    "SAP": SapAccountingAdapter,
    "ODOO": OdooAccountingAdapter,
}


def get_accounting_adapter(
    accounting_system: str,
    *,
    config: dict | None = None,
) -> AccountingAdapter:
    """Return an AccountingAdapter for the given accounting_system string.

    Args:
        accounting_system: Identifier string (e.g. 'MOCK', 'CSV', 'SEPIDAR').
        config: Optional configuration dict passed to the adapter constructor.

    Raises:
        ValidationError: Unknown accounting_system.
    """
    key = accounting_system.upper().strip()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ValidationError(
            f"سیستم حسابداری '{accounting_system}' ناشناخته است. "
            f"گزینه‌های معتبر: {', '.join(sorted(_REGISTRY))}"
        )

    # MOCK adapter takes no config; CSV adapter takes config dict
    if cls is MockAccountingAdapter:
        return cls()
    return cls(config=config)


def list_accounting_systems() -> list[dict]:
    """Return metadata for all registered accounting systems."""
    return [
        {
            "system": "MOCK",
            "label": "آزمایشی (Mock)",
            "implementation_status": "simulator",
            "description": "سیستم حسابداری درون‌حافظه برای تست — بدون API واقعی",
            "verified_docs_url": None,
        },
        {
            "system": "CSV",
            "label": "خروجی CSV",
            "implementation_status": "simulator",
            "description": "خروجی CSV قابل وارد کردن به نرم‌افزارهای حسابداری",
            "verified_docs_url": None,
        },
        {
            "system": "SEPIDAR",
            "label": "سپیدار ERP",
            "implementation_status": "not_implemented",
            "description": "سپیدار ERP — REAL PROVIDER: NOT IMPLEMENTED",
            "verified_docs_url": None,
        },
        {
            "system": "RAHKARAN",
            "label": "راهکاران ERP",
            "implementation_status": "not_implemented",
            "description": "راهکاران ERP — REAL PROVIDER: NOT IMPLEMENTED",
            "verified_docs_url": None,
        },
        {
            "system": "HOLO",
            "label": "هلو ERP",
            "implementation_status": "not_implemented",
            "description": "هلو ERP — REAL PROVIDER: NOT IMPLEMENTED",
            "verified_docs_url": None,
        },
        {
            "system": "SAP",
            "label": "SAP ERP",
            "implementation_status": "not_implemented",
            "description": "SAP ERP — REAL PROVIDER: NOT IMPLEMENTED",
            "verified_docs_url": "https://api.sap.com/",
        },
        {
            "system": "ODOO",
            "label": "Odoo ERP",
            "implementation_status": "not_implemented",
            "description": "Odoo ERP — REAL PROVIDER: NOT IMPLEMENTED",
            "verified_docs_url": "https://www.odoo.com/documentation/17.0/developer/reference/external_api.html",
        },
    ]
