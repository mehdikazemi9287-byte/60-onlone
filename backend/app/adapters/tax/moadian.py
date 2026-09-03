"""Moadian (مودیان) Iranian e-Invoicing Tax Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation:
  https://www.tax.gov.ir/ — Iran National Tax Administration (سازمان امور مالیاتی)
  Moadian system (سامانه مودیان) is Iran's mandatory e-invoicing system.
  Technical specification published by INTA:
  https://www.tax.gov.ir/index.aspx?siteid=1&pageid=4741 (subject to change)
Sandbox availability:
  Test environment available to registered taxpayers via INTA portal.
  Registration requires a valid national tax ID (کد اقتصادی).
Authentication method:
  RSA key pair issued by INTA. Private key signs requests.
  Bearer token from authentication endpoint.
  Documented in Moadian technical specification v1.x.
Verified endpoints:
  - POST /api/self-tsp/sync/putInvoice — submit invoice batch (documented)
  - GET  /api/self-tsp/sync/getToken  — obtain access token (documented)
  NOTE: Path structure sourced from published INTA technical specification.
        Implementation requires registered Moadian account + RSA key.
Rate limits: Batch processing; limits documented in Moadian spec.
Webhook rules: Push model — INTA sends confirmation callbacks.

Required config keys (for future implementation):
  base_url       : https://tp.tax.gov.ir (or test environment URL)
  company_economic_code: کد اقتصادی
  credential_ref : reference key for RSA private key in secret store

TAX ADAPTER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

from app.adapters.tax.base import (
    TaxAdapter,
    TaxAdapterError,
    TaxCalculationResult,
    TaxLineInput,
)


class MoadianTaxAdapter(TaxAdapter):
    """Moadian (سامانه مودیان) Iranian e-invoicing adapter — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    Official docs: https://www.tax.gov.ir/
    No API calls are made. No endpoints are fabricated beyond what INTA docs confirm.
    RSA signature logic NOT implemented — requires registered Moadian account.
    """

    adapter_name = "MOADIAN"
    implementation_status = "not_implemented"

    OFFICIAL_DOCS_URL = "https://www.tax.gov.ir/"
    DOCS_VERSION = "Moadian Technical Specification v1.x (published by INTA)"
    AUTH_METHOD = "RSA key pair (issued by INTA) + bearer token"

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._base_url = cfg.get("base_url", "https://tp.tax.gov.ir")
        self._company_economic_code = cfg.get("company_economic_code", "")
        self._credential_ref = cfg.get("credential_ref", "")  # never logged

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": [],
            "notes": (
                "سامانه مودیان (ایران) — REAL PROVIDER: NOT IMPLEMENTED. "
                f"مستندات رسمی: {self.OFFICIAL_DOCS_URL}. "
                "نیاز به کد اقتصادی و کلید RSA صادر شده توسط سازمان امور مالیاتی."
            ),
            "verified_docs_url": self.OFFICIAL_DOCS_URL,
            "auth_method": self.AUTH_METHOD,
        }

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": (
                "سامانه مودیان هنوز پیاده‌سازی نشده. "
                "REAL PROVIDER: NOT IMPLEMENTED. "
                f"مستندات: {self.OFFICIAL_DOCS_URL}"
            ),
            "latency_ms": None,
        }

    def calculate_tax(
        self,
        lines: list[TaxLineInput],
        *,
        effective_date: str,
        jurisdiction: str = "IR",
    ) -> "TaxCalculationResult":
        raise TaxAdapterError(
            "MOADIAN: calculate_tax — REAL PROVIDER: NOT IMPLEMENTED. "
            f"مستندات: {self.OFFICIAL_DOCS_URL}",
            code="not_implemented",
        )

    def submit_invoice(self, tax_result: "TaxCalculationResult", *, metadata: dict | None = None) -> dict:
        raise TaxAdapterError(
            "MOADIAN: submit_invoice — REAL PROVIDER: NOT IMPLEMENTED. "
            "نیاز به ثبت‌نام در سامانه مودیان و کلید RSA دارد.",
            code="not_implemented",
        )

    def get_submission_status(self, external_ref: str) -> dict:
        raise TaxAdapterError(
            "MOADIAN: get_submission_status — REAL PROVIDER: NOT IMPLEMENTED.",
            code="not_implemented",
        )
