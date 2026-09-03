"""Accounting Connector Adapter — Abstract Base.

Defines the normalized interface that all accounting system connectors must
implement. This interface is system-agnostic: it works equally for
Sepidar, Rahkaran, Holo, SAP, Odoo, or a CSV export.

CRITICAL RULE:
  60online's internal ledger (ledger_entries / ledger_transactions) remains
  the SOURCE OF TRUTH for all financial invariants.
  External accounting systems are INTEGRATIONS — they receive exports and
  provide reconciliation data. They do NOT override internal ledger entries.

REAL PROVIDER INTEGRATIONS — NOT IMPLEMENTED:
  Sepidar, Rahkaran, Holo, SAP, Odoo adapters are not yet implemented.
  See their stub files for documentation references.

ACCOUNTING ADAPTER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Document types (normalized)
# ─────────────────────────────────────────────────────────────────────────────

class AccountingDocumentType(str, enum.Enum):
    SALES_INVOICE    = "sales_invoice"
    PURCHASE_INVOICE = "purchase_invoice"
    CREDIT_NOTE      = "credit_note"
    DEBIT_NOTE       = "debit_note"
    PAYMENT          = "payment"
    RECEIPT          = "receipt"
    SETTLEMENT       = "settlement"
    JOURNAL_ENTRY    = "journal_entry"
    OTHER            = "other"


# ─────────────────────────────────────────────────────────────────────────────
# Normalized accounting document
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AccountingDocument:
    """Vendor-neutral accounting document.

    All monetary values are integer minor units (IRR, exponent 0 in this
    deployment). No floats. No percentage calculations.
    """
    doc_type: AccountingDocumentType
    doc_number: str
    doc_date: str               # YYYY-MM-DD
    currency: str = "IRR"
    subtotal_minor: int = 0     # before tax
    tax_minor: int = 0
    total_minor: int = 0        # must equal subtotal_minor + tax_minor

    # Party information
    counterparty_name: str = ""
    counterparty_national_id: str = ""
    counterparty_tax_id: str = ""

    # Line items (optional; may be empty for payment docs)
    lines: list["AccountingLine"] = field(default_factory=list)

    # 60online internal links
    order_id: int | None = None
    fulfillment_order_id: int | None = None
    supplier_id: int | None = None
    organization_id: int | None = None

    # External system reference
    external_doc_id: str = ""
    external_doc_number: str = ""

    # Extra vendor-specific fields (safe to pass through, not executed)
    metadata: dict = field(default_factory=dict)


@dataclass
class AccountingLine:
    """One line item in an accounting document."""
    description: str
    quantity: int = 1           # integer quantity
    unit_price_minor: int = 0
    line_total_minor: int = 0
    tax_minor: int = 0
    tax_category_code: str = ""
    product_code: str = ""
    external_line_id: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Accounting adapter error
# ─────────────────────────────────────────────────────────────────────────────

class AccountingAdapterError(Exception):
    def __init__(self, message: str, code: str = "unknown", *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# ─────────────────────────────────────────────────────────────────────────────
# Abstract accounting adapter
# ─────────────────────────────────────────────────────────────────────────────

class AccountingAdapter:
    """Abstract accounting system connector — contract version 1.0.

    Design rules:
    1. All methods raise AccountingAdapterError on failure.
    2. 60online's ledger is authoritative. Adapters export / reconcile; they
       do NOT override internal financial records.
    3. Credentials MUST NOT be logged or returned.
    4. Default: REJECT (fail-closed) for all methods.
    """

    adapter_name: str = "base"
    implementation_status: str = "not_implemented"
    # not_implemented | simulator | verified | production

    # ── Introspection ─────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": f"{self.adapter_name}: سلامت‌سنجی پیاده‌سازی نشده",
            "latency_ms": None,
        }

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
        }

    # ── Export operations (60online → accounting system) ─────────────────────

    def export_invoice(self, doc: AccountingDocument) -> dict:
        """Export a sales/purchase invoice to the accounting system.

        Returns: {acknowledged: bool, external_doc_id: str|None, message: str}
        """
        raise AccountingAdapterError(
            f"{self.adapter_name}: export_invoice پیاده‌سازی نشده",
            code="not_implemented",
        )

    def export_payment(self, doc: AccountingDocument) -> dict:
        """Export a payment/receipt document."""
        raise AccountingAdapterError(
            f"{self.adapter_name}: export_payment پیاده‌سازی نشده",
            code="not_implemented",
        )

    def export_settlement(self, doc: AccountingDocument) -> dict:
        """Export a supplier settlement batch."""
        raise AccountingAdapterError(
            f"{self.adapter_name}: export_settlement پیاده‌سازی نشده",
            code="not_implemented",
        )

    # ── Import / reconciliation operations (accounting system → 60online) ────

    def pull_invoices(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        since: str | None = None,  # ISO-8601 datetime
    ) -> list[AccountingDocument]:
        """Pull invoices from the accounting system for reconciliation."""
        raise AccountingAdapterError(
            f"{self.adapter_name}: pull_invoices پیاده‌سازی نشده",
            code="not_implemented",
        )

    def pull_payments(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        since: str | None = None,
    ) -> list[AccountingDocument]:
        """Pull payments from the accounting system for reconciliation."""
        raise AccountingAdapterError(
            f"{self.adapter_name}: pull_payments پیاده‌سازی نشده",
            code="not_implemented",
        )

    # ── Customer / supplier master ────────────────────────────────────────────

    def upsert_customer(self, customer_data: dict) -> dict:
        """Create or update a customer record in the accounting system."""
        raise AccountingAdapterError(
            f"{self.adapter_name}: upsert_customer پیاده‌سازی نشده",
            code="not_implemented",
        )

    def upsert_supplier(self, supplier_data: dict) -> dict:
        """Create or update a supplier record in the accounting system."""
        raise AccountingAdapterError(
            f"{self.adapter_name}: upsert_supplier پیاده‌سازی نشده",
            code="not_implemented",
        )
