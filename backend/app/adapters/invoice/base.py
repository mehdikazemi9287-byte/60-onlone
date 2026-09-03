"""InvoiceCaptureAdapter ABC.

Every invoice capture source (OCR scan, electronic invoice, API, manual)
must implement this interface.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
Real OCR engines (Abbyy, Google Document AI, etc.) are NOT implemented.
Only the mock OCR adapter is functional.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class InvoiceCaptureAdapter(ABC):
    """Abstract base for invoice capture adapters."""

    adapter_key: str = "base"

    @abstractmethod
    def capture(self, raw_input: bytes | dict) -> dict:
        """
        Extract structured invoice data from raw input (bytes for OCR, dict for API).

        Returns:
        {
          "invoice_number": str,
          "invoice_date": str (ISO date),
          "supplier_name": str | None,
          "subtotal_minor": int,
          "tax_minor": int,
          "total_minor": int,
          "currency": str,
          "lines": [
            {
              "line_number": int,
              "external_code": str | None,
              "barcode": str | None,
              "product_name": str | None,
              "quantity": int,
              "unit_price_minor": int,
              "line_total_minor": int,
              "tax_minor": int,
            }
          ],
          "raw_json": dict,  # original extracted data
          "confidence_bps": int,  # 0-10000
        }
        """
        ...

    @abstractmethod
    def health_check(self) -> dict:
        """Return {"healthy": bool, "message": str, "latency_ms": int|None}"""
        ...
