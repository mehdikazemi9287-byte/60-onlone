"""Tax/VAT Adapter — Abstract Base.

Defines the normalized interface for tax system connectors.
Covers:
  - Tax category / rate resolution
  - Invoice-level tax calculation
  - Moadian (Iranian e-invoicing API) submission
  - Historical reproducibility — rate always resolved at effective date

CRITICAL RULE:
  60online's internal tax_categories and tax_rates tables are the SOURCE OF TRUTH.
  External tax systems are INTEGRATIONS — they receive submissions.
  They do NOT override internal tax configuration.

TAX ADAPTER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Tax document types
# ─────────────────────────────────────────────────────────────────────────────

class TaxDocumentType(str, enum.Enum):
    SALES_INVOICE    = "sales_invoice"
    PURCHASE_INVOICE = "purchase_invoice"
    CREDIT_NOTE      = "credit_note"
    DEBIT_NOTE       = "debit_note"


# ─────────────────────────────────────────────────────────────────────────────
# Tax resolution request / response
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TaxLineInput:
    """Input line for tax calculation."""
    description: str
    quantity: int
    unit_price_minor: int          # before tax, integer minor units
    tax_category_code: str = "STANDARD"
    product_code: str = ""


@dataclass
class TaxLineResult:
    """Calculated tax for one line."""
    description: str
    quantity: int
    unit_price_minor: int
    line_subtotal_minor: int       # quantity × unit_price_minor
    tax_rate_bps: int              # basis points (e.g. 900 = 9%)
    tax_category_code: str
    tax_minor: int                 # floor(line_subtotal_minor × rate_bps / 10000)
    line_total_minor: int          # subtotal + tax


@dataclass
class TaxCalculationResult:
    """Full tax calculation result for a document."""
    tax_category_code: str
    rate_bps: int
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    lines: list[TaxLineResult] = field(default_factory=list)
    jurisdiction: str = "IR"
    effective_date: str = ""       # YYYY-MM-DD used for rate lookup


# ─────────────────────────────────────────────────────────────────────────────
# Error
# ─────────────────────────────────────────────────────────────────────────────

class TaxAdapterError(Exception):
    def __init__(self, message: str, code: str = "unknown", *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# ─────────────────────────────────────────────────────────────────────────────
# Abstract tax adapter
# ─────────────────────────────────────────────────────────────────────────────

class TaxAdapter:
    """Abstract tax system connector — contract version 1.0.

    Design rules:
    1. All methods raise TaxAdapterError on failure.
    2. 60online's ledger is authoritative; adapters submit/report only.
    3. Rate lookup MUST use the effective_date to ensure historical reproducibility.
    4. Credentials MUST NOT be logged or returned.
    """

    adapter_name: str = "base"
    implementation_status: str = "not_implemented"

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": f"{self.adapter_name}: health_check not implemented",
            "latency_ms": None,
        }

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
        }

    def calculate_tax(
        self,
        lines: list[TaxLineInput],
        *,
        effective_date: str,          # YYYY-MM-DD
        jurisdiction: str = "IR",
    ) -> TaxCalculationResult:
        """Calculate tax for a list of line items.

        Uses rates effective on effective_date — never current date, to ensure
        historical reproducibility for already-issued invoices.
        """
        raise TaxAdapterError(
            f"{self.adapter_name}: calculate_tax not implemented",
            code="not_implemented",
        )

    def submit_invoice(self, tax_result: TaxCalculationResult, *, metadata: dict | None = None) -> dict:
        """Submit a tax invoice to the external tax system (e.g. Moadian).

        Returns: {acknowledged: bool, external_ref: str|None, message: str}
        """
        raise TaxAdapterError(
            f"{self.adapter_name}: submit_invoice not implemented",
            code="not_implemented",
        )

    def get_submission_status(self, external_ref: str) -> dict:
        """Poll submission status from external tax system."""
        raise TaxAdapterError(
            f"{self.adapter_name}: get_submission_status not implemented",
            code="not_implemented",
        )
