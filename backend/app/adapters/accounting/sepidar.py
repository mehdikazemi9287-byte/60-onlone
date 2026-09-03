"""Sepidar ERP Accounting Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: Not publicly available — requires vendor agreement
  with Sepidar (Pasargad Software Group).
Sandbox availability: Not confirmed without vendor agreement.
Authentication method: Not publicly documented.
Verified endpoints: None — no public API specification available.
Rate limits / webhook rules: Not documented publicly.

This file defines the interface the Sepidar adapter WILL implement once
official documentation and credentials are obtained. All methods raise
AccountingAdapterError(code='not_implemented').

DO NOT fabricate endpoints, tokens, or response shapes for Sepidar.

References (for implementer):
  - https://www.sepidar.ir/ (vendor homepage — no public API docs)
  - Contact: Sepidar technical support / partner programme
"""
from __future__ import annotations

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingAdapterError,
    AccountingDocument,
)


class SepidarAccountingAdapter(AccountingAdapter):
    """Sepidar ERP connector — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No API calls are made. No endpoints are fabricated.
    All methods raise AccountingAdapterError(code='not_implemented').
    """

    adapter_name = "SEPIDAR"
    implementation_status = "not_implemented"

    def __init__(self, config: dict | None = None):
        # config is accepted but ignored — no live integration
        self._config = config or {}

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
            "notes": (
                "سپیدار ERP — REAL PROVIDER: NOT IMPLEMENTED. "
                "مستندات رسمی API نیاز به قرارداد فروشنده دارد. "
                "هیچ endpoint‌ای ساخته‌پردازی نشده."
            ),
            "verified_docs_url": None,
        }

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": (
                "سپیدار ERP هنوز پیاده‌سازی نشده. "
                "REAL PROVIDER: NOT IMPLEMENTED."
            ),
            "latency_ms": None,
        }

    def export_invoice(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "SEPIDAR: export_invoice — REAL PROVIDER: NOT IMPLEMENTED. "
            "مستندات رسمی API سپیدار در دسترس عموم نیست.",
            code="not_implemented",
        )

    def export_payment(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "SEPIDAR: export_payment — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def export_settlement(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "SEPIDAR: export_settlement — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_invoices(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "SEPIDAR: pull_invoices — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_payments(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "SEPIDAR: pull_payments — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_customer(self, customer_data: dict) -> dict:
        raise AccountingAdapterError(
            "SEPIDAR: upsert_customer — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_supplier(self, supplier_data: dict) -> dict:
        raise AccountingAdapterError(
            "SEPIDAR: upsert_supplier — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )
