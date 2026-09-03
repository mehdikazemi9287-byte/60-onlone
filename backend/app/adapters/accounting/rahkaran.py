"""Rahkaran (Hamkaran) ERP Accounting Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: Not publicly available.
  Rahkaran (also branded Hamkaran System) requires direct vendor engagement.
Sandbox availability: Not confirmed.
Authentication method: Not publicly documented.
Verified endpoints: None.
Rate limits / webhook rules: Not documented publicly.

References (for implementer):
  - https://www.hamkaransys.com/ (vendor homepage)
  - https://www.rahkaran.com/ (alternate branding)
  - Contact vendor technical department for API access agreement.
"""
from __future__ import annotations

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingAdapterError,
    AccountingDocument,
)


class RahkaranAccountingAdapter(AccountingAdapter):
    """Rahkaran/Hamkaran ERP connector — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No API calls are made. No endpoints are fabricated.
    """

    adapter_name = "RAHKARAN"
    implementation_status = "not_implemented"

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
            "notes": (
                "راهکاران ERP — REAL PROVIDER: NOT IMPLEMENTED. "
                "مستندات رسمی API در دسترس عموم نیست."
            ),
            "verified_docs_url": None,
        }

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": (
                "راهکاران ERP هنوز پیاده‌سازی نشده. "
                "REAL PROVIDER: NOT IMPLEMENTED."
            ),
            "latency_ms": None,
        }

    def export_invoice(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "RAHKARAN: export_invoice — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def export_payment(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "RAHKARAN: export_payment — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def export_settlement(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "RAHKARAN: export_settlement — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_invoices(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "RAHKARAN: pull_invoices — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_payments(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "RAHKARAN: pull_payments — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_customer(self, customer_data: dict) -> dict:
        raise AccountingAdapterError(
            "RAHKARAN: upsert_customer — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_supplier(self, supplier_data: dict) -> dict:
        raise AccountingAdapterError(
            "RAHKARAN: upsert_supplier — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )
