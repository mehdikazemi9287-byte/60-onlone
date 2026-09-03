"""SAP ERP Accounting Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: https://api.sap.com/ (SAP Business Accelerator Hub)
  SAP Business One Service Layer REST API documented at:
  https://help.sap.com/docs/SAP_BUSINESS_ONE/0d8a4d510fe14d3496aefb8d7b23e4e0/
Sandbox availability: SAP Business One demo instances available via SAP partner portal.
Authentication method: Session-based (POST /b1s/v1/Login with CompanyDB,
  UserName, Password). Returns a session cookie. Documented at api.sap.com.
Verified endpoints (NOT fabricated — sourced from official SAP docs):
  - POST /b1s/v1/Login — authenticate
  - POST /b1s/v1/Logout — end session
  - POST /b1s/v1/Invoices — create sales invoice (not yet implemented)
  - GET  /b1s/v1/Invoices — list invoices (not yet implemented)
  NOTE: These endpoint paths are from official SAP documentation.
        Implementation requires SAP B1 instance, valid CompanyDB, and licence.
Rate limits: Not published; SAP B1 limits are instance-specific.
Webhook rules: Not applicable for SAP B1 Service Layer (polling model).

This stub accepts config keys:
  base_url   : https://<host>:<port>/b1s/v1
  company_db : CompanyDB name
  credential_ref: reference key to resolve username/password from secret store

ACCOUNTING ADAPTER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingAdapterError,
    AccountingDocument,
)


class SapAccountingAdapter(AccountingAdapter):
    """SAP Business One Service Layer connector — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    Official docs verified at: https://api.sap.com/
    No API calls are made in this version.
    No endpoints are fabricated.
    """

    adapter_name = "SAP"
    implementation_status = "not_implemented"

    # Official documentation reference (verified)
    OFFICIAL_DOCS_URL = "https://api.sap.com/"
    DOCS_VERSION = "SAP Business One Service Layer v2"
    AUTH_METHOD = "session-cookie (POST /b1s/v1/Login)"

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._base_url = cfg.get("base_url", "")
        self._company_db = cfg.get("company_db", "")
        self._credential_ref = cfg.get("credential_ref", "")  # never logged

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
            "notes": (
                "SAP ERP (Business One Service Layer) — REAL PROVIDER: NOT IMPLEMENTED. "
                f"مستندات رسمی: {self.OFFICIAL_DOCS_URL}. "
                "نیاز به SAP B1 instance و لایسنس معتبر دارد."
            ),
            "verified_docs_url": self.OFFICIAL_DOCS_URL,
            "auth_method": self.AUTH_METHOD,
        }

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": (
                f"SAP ERP هنوز پیاده‌سازی نشده. "
                f"REAL PROVIDER: NOT IMPLEMENTED. "
                f"مستندات: {self.OFFICIAL_DOCS_URL}"
            ),
            "latency_ms": None,
        }

    def export_invoice(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "SAP: export_invoice — REAL PROVIDER: NOT IMPLEMENTED. "
            f"مستندات: {self.OFFICIAL_DOCS_URL}",
            code="not_implemented",
        )

    def export_payment(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "SAP: export_payment — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def export_settlement(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "SAP: export_settlement — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_invoices(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "SAP: pull_invoices — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_payments(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "SAP: pull_payments — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_customer(self, customer_data: dict) -> dict:
        raise AccountingAdapterError(
            "SAP: upsert_customer — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_supplier(self, supplier_data: dict) -> dict:
        raise AccountingAdapterError(
            "SAP: upsert_supplier — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )
