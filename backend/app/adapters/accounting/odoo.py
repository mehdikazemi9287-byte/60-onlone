"""Odoo ERP Accounting Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation:
  https://www.odoo.com/documentation/17.0/developer/reference/external_api.html
  Odoo External API uses XML-RPC (and JSON-RPC in newer versions).
  Version documented: Odoo 17.0 (LTS as of 2024).
Sandbox availability: Odoo SaaS trial available at https://www.odoo.com/trial
  Self-hosted Community edition installable (open-source, LGPL).
Authentication method:
  XML-RPC: xmlrpc.client — /web/xmlrpc/2/common (authenticate), /web/xmlrpc/2/object (model calls)
  JSON-RPC: POST /web/dataset/call_kw
  Credentials: url, db, username, password (API key supported in v14+).
Verified endpoints (from official docs — NOT fabricated):
  - /web/xmlrpc/2/common → authenticate() — returns uid
  - /web/xmlrpc/2/object → execute_kw(db, uid, password, model, method, args, kwargs)
  - model 'account.move' — invoice CRUD
  - model 'account.payment' — payment records
  - model 'res.partner' — customer/supplier master
  NOTE: Path structure is verified against official Odoo 17.0 docs.
Rate limits: Odoo SaaS applies rate limits; self-hosted has no default limit.
Webhook rules: Odoo supports webhooks via 'Automated Actions' (v16+).

Config keys accepted by this adapter (for future implementation):
  base_url      : https://<odoo-instance>
  db            : Odoo database name
  credential_ref: reference key for username + API-key/password in secret store

ACCOUNTING ADAPTER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingAdapterError,
    AccountingDocument,
)


class OdooAccountingAdapter(AccountingAdapter):
    """Odoo ERP XML-RPC/JSON-RPC connector — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    Official docs verified at:
      https://www.odoo.com/documentation/17.0/developer/reference/external_api.html
    No API calls are made in this version.
    No endpoints are fabricated beyond what official documentation confirms.
    """

    adapter_name = "ODOO"
    implementation_status = "not_implemented"

    OFFICIAL_DOCS_URL = (
        "https://www.odoo.com/documentation/17.0/developer/reference/external_api.html"
    )
    DOCS_VERSION = "Odoo 17.0"
    AUTH_METHOD = "XML-RPC uid (xmlrpc.client) or JSON-RPC session"

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._base_url = cfg.get("base_url", "")
        self._db = cfg.get("db", "")
        self._credential_ref = cfg.get("credential_ref", "")  # never logged

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
            "notes": (
                "Odoo ERP — REAL PROVIDER: NOT IMPLEMENTED. "
                f"مستندات رسمی: {self.OFFICIAL_DOCS_URL}. "
                "نیاز به Odoo instance و API key دارد."
            ),
            "verified_docs_url": self.OFFICIAL_DOCS_URL,
            "auth_method": self.AUTH_METHOD,
        }

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": (
                "Odoo ERP هنوز پیاده‌سازی نشده. "
                "REAL PROVIDER: NOT IMPLEMENTED. "
                f"مستندات: {self.OFFICIAL_DOCS_URL}"
            ),
            "latency_ms": None,
        }

    def export_invoice(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "ODOO: export_invoice — REAL PROVIDER: NOT IMPLEMENTED. "
            f"مستندات: {self.OFFICIAL_DOCS_URL}",
            code="not_implemented",
        )

    def export_payment(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "ODOO: export_payment — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def export_settlement(self, doc: AccountingDocument) -> dict:
        raise AccountingAdapterError(
            "ODOO: export_settlement — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_invoices(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "ODOO: pull_invoices — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def pull_payments(self, *, limit=100, offset=0, since=None):
        raise AccountingAdapterError(
            "ODOO: pull_payments — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_customer(self, customer_data: dict) -> dict:
        raise AccountingAdapterError(
            "ODOO: upsert_customer — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )

    def upsert_supplier(self, supplier_data: dict) -> dict:
        raise AccountingAdapterError(
            "ODOO: upsert_supplier — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )
