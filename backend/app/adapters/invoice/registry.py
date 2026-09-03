"""Invoice capture adapter registry.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
Only mock_ocr is functional in this build.
"""
from __future__ import annotations

from app.adapters.invoice.base import InvoiceCaptureAdapter
from app.adapters.invoice.mock_ocr import MockOcrAdapter


class _NotYetImplementedInvoice(InvoiceCaptureAdapter):
    """Placeholder for invoice adapters not yet implemented."""

    def __init__(self, key: str):
        self.adapter_key = key

    def capture(self, raw_input: bytes | dict) -> dict:
        raise NotImplementedError(f"آداپتور فاکتور '{self.adapter_key}' پیاده‌سازی نشده")

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": f"آداپتور '{self.adapter_key}' هنوز پیاده‌سازی نشده — REAL PROVIDER: NOT IMPLEMENTED",
            "latency_ms": None,
        }


INVOICE_ADAPTERS: dict[str, InvoiceCaptureAdapter] = {
    "mock_ocr": MockOcrAdapter(),
    "abbyy_ocr": _NotYetImplementedInvoice("abbyy_ocr"),
    "google_doc_ai": _NotYetImplementedInvoice("google_doc_ai"),
    "electronic": _NotYetImplementedInvoice("electronic"),
}


def get_invoice_adapter(adapter_key: str) -> InvoiceCaptureAdapter | None:
    """Return an invoice capture adapter by key, or None if unknown."""
    return INVOICE_ADAPTERS.get(adapter_key)
