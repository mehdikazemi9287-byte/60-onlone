"""Mock Accounting Adapter — deterministic, in-memory, for testing.

Simulates a full accounting system without any external API calls.
All data is stored in-memory per instance. Deterministic.
"""
from __future__ import annotations

import json
from typing import Any

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingDocument,
    AccountingDocumentType,
    AccountingLine,
)


class MockAccountingAdapter(AccountingAdapter):
    """In-memory accounting adapter for testing and demonstration."""

    adapter_name = "MOCK"
    implementation_status = "simulator"

    def __init__(self):
        self._documents: list[dict] = []
        self._customers: dict[str, dict] = {}
        self._suppliers: dict[str, dict] = {}
        self._next_doc_id = 1000

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [
                "export_invoice", "export_payment", "export_settlement",
                "pull_invoices", "pull_payments",
                "upsert_customer", "upsert_supplier",
            ],
        }

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": f"MOCK accounting adapter — {len(self._documents)} سند ذخیره‌شده",
            "latency_ms": 0,
        }

    def export_invoice(self, doc: AccountingDocument) -> dict:
        ext_id = f"MOCK-INV-{self._next_doc_id:06d}"
        self._next_doc_id += 1
        self._documents.append({
            "external_doc_id": ext_id,
            "doc_type": doc.doc_type,
            "doc_number": doc.doc_number,
            "doc_date": doc.doc_date,
            "total_minor": doc.total_minor,
            "tax_minor": doc.tax_minor,
            "currency": doc.currency,
            "order_id": doc.order_id,
        })
        return {"acknowledged": True, "external_doc_id": ext_id, "message": "سند در سیستم mock ثبت شد"}

    def export_payment(self, doc: AccountingDocument) -> dict:
        ext_id = f"MOCK-PAY-{self._next_doc_id:06d}"
        self._next_doc_id += 1
        self._documents.append({
            "external_doc_id": ext_id,
            "doc_type": "payment",
            "doc_number": doc.doc_number,
            "total_minor": doc.total_minor,
            "currency": doc.currency,
        })
        return {"acknowledged": True, "external_doc_id": ext_id, "message": "پرداخت در سیستم mock ثبت شد"}

    def export_settlement(self, doc: AccountingDocument) -> dict:
        ext_id = f"MOCK-SET-{self._next_doc_id:06d}"
        self._next_doc_id += 1
        self._documents.append({
            "external_doc_id": ext_id,
            "doc_type": "settlement",
            "total_minor": doc.total_minor,
            "currency": doc.currency,
            "supplier_id": doc.supplier_id,
        })
        return {"acknowledged": True, "external_doc_id": ext_id, "message": "تسویه در سیستم mock ثبت شد"}

    def pull_invoices(self, *, limit=100, offset=0, since=None) -> list[AccountingDocument]:
        inv_docs = [d for d in self._documents if "INV" in d.get("external_doc_id", "")]
        page = inv_docs[offset: offset + limit]
        return [
            AccountingDocument(
                doc_type=AccountingDocumentType.SALES_INVOICE,
                doc_number=d["doc_number"],
                doc_date="2026-01-01",
                total_minor=d["total_minor"],
                currency=d["currency"],
                external_doc_id=d["external_doc_id"],
            )
            for d in page
        ]

    def pull_payments(self, *, limit=100, offset=0, since=None) -> list[AccountingDocument]:
        pay_docs = [d for d in self._documents if "PAY" in d.get("external_doc_id", "")]
        page = pay_docs[offset: offset + limit]
        return [
            AccountingDocument(
                doc_type=AccountingDocumentType.PAYMENT,
                doc_number=d.get("doc_number", ""),
                doc_date="2026-01-01",
                total_minor=d["total_minor"],
                currency=d["currency"],
                external_doc_id=d["external_doc_id"],
            )
            for d in page
        ]

    def upsert_customer(self, customer_data: dict) -> dict:
        key = customer_data.get("national_id") or customer_data.get("email", "")
        self._customers[key] = customer_data
        return {"acknowledged": True, "external_id": f"MOCK-CUST-{key}"}

    def upsert_supplier(self, supplier_data: dict) -> dict:
        key = supplier_data.get("national_id") or supplier_data.get("name", "")
        self._suppliers[key] = supplier_data
        return {"acknowledged": True, "external_id": f"MOCK-SUP-{key}"}

    @property
    def document_count(self) -> int:
        return len(self._documents)
