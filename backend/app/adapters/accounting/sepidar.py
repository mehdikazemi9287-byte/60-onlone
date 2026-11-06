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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5B — Sepidar import file (Excel/CSV) from the canonical finance export.
# No API: Sepidar is fed through its "ورود اطلاعات از اکسل" import screens.
# Column titles follow the common Sepidar import template; verify per customer.
# ─────────────────────────────────────────────────────────────────────────────

from app.adapters.accounting.finance_formats import (  # noqa: E402
    FinanceExportFormatter,
    jalali,
    voucher_rows,
)


class SepidarFinanceFormatter(FinanceExportFormatter):
    connector = "SEPIDAR"
    label = "سپیدار — فایل اکسل ورود سند/فاکتور"
    layouts = ("vouchers", "invoices")

    VOUCHER_HEADER = ["ردیف", "شماره سند", "تاریخ سند", "شرح سند", "کد حساب", "کد تفصیلی",
                      "شرح ردیف", "بدهکار", "بستانکار", "شماره مرجع"]
    INVOICE_HEADER = ["شماره فاکتور", "تاریخ فاکتور", "کد طرف حساب", "نام طرف حساب", "شناسه ملی",
                      "کد کالا/خدمت", "شرح کالا/خدمت", "تعداد", "فی", "مبلغ", "تخفیف",
                      "مالیات و عوارض", "مبلغ کل"]

    def render(self, export: dict) -> dict:
        if self.layout == "invoices":
            rows = [[d["doc_number"], jalali(d["doc_date"]), d["counterparty"]["code"],
                     d["counterparty"]["name"], d["counterparty"]["national_id"], ln["code"],
                     ln["description"], ln["quantity"], ln["unit_price_minor"], ln["gross_minor"],
                     ln["discount_minor"], ln["vat_minor"], ln["total_minor"]]
                    for d in export["documents"] if d["lines"] for ln in d["lines"]]
            return self._csv(export, self.INVOICE_HEADER, rows, "invoices")
        numbers = {d["doc_number"]: n for n, d in enumerate(export["documents"], start=1)}
        rows = [[i, numbers[d["doc_number"]], jalali(d["doc_date"]), d["description"], v["account_code"],
                 v["detail_code"], v["description"], v["debit_minor"], v["credit_minor"], d["doc_number"]]
                for d, i, v in voucher_rows(export)]
        return self._csv(export, self.VOUCHER_HEADER, rows, "vouchers")
