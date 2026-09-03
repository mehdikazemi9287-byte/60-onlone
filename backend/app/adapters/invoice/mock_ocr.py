"""Mock OCR invoice capture adapter.

Deterministic mock that extracts structured data from a simple dict
representing an invoice scan. No real OCR, no external calls.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
"""
from __future__ import annotations

from app.adapters.invoice.base import InvoiceCaptureAdapter


class MockOcrAdapter(InvoiceCaptureAdapter):
    """
    Deterministic mock OCR invoice adapter.

    Accepts a dict with pre-structured invoice data (simulating what a
    real OCR engine would extract). Returns the same structure normalized.

    For bytes input, returns a fixed demo invoice.
    """

    adapter_key = "mock_ocr"

    def capture(self, raw_input: bytes | dict) -> dict:
        if isinstance(raw_input, bytes):
            return self._demo_invoice(raw_input)
        return self._normalize(raw_input)

    def _normalize(self, data: dict) -> dict:
        """Normalize a dict representing extracted invoice data."""
        lines = []
        for i, line in enumerate(data.get("lines", []), start=1):
            qty = int(line.get("quantity", 1))
            unit_price = int(line.get("unit_price_minor", 0))
            line_total = int(line.get("line_total_minor", qty * unit_price))
            tax = int(line.get("tax_minor", 0))
            lines.append({
                "line_number": i,
                "external_code": line.get("external_code"),
                "barcode": line.get("barcode"),
                "product_name": line.get("product_name"),
                "quantity": qty,
                "unit_price_minor": unit_price,
                "line_total_minor": line_total,
                "tax_minor": tax,
            })

        subtotal = int(data.get("subtotal_minor", sum(l["line_total_minor"] for l in lines)))
        tax = int(data.get("tax_minor", 0))
        total = int(data.get("total_minor", subtotal + tax))

        return {
            "invoice_number": str(data.get("invoice_number", "MOCK-INV-001")),
            "invoice_date": str(data.get("invoice_date", "2026-08-08")),
            "supplier_name": data.get("supplier_name"),
            "subtotal_minor": subtotal,
            "tax_minor": tax,
            "total_minor": total,
            "currency": str(data.get("currency", "IRR")),
            "lines": lines,
            "raw_json": data,
            "confidence_bps": int(data.get("confidence_bps", 9500)),
        }

    def _demo_invoice(self, raw_bytes: bytes) -> dict:
        """Return a fixed demo invoice for bytes input (simulating OCR scan)."""
        # Deterministic demo invoice with 3 lines
        lines = [
            {
                "line_number": 1,
                "external_code": "ERP-00001",
                "barcode": "6260000000001",
                "product_name": "لبنیات — مدل 2",
                "quantity": 10,
                "unit_price_minor": 2000000,
                "line_total_minor": 20000000,
                "tax_minor": 2000000,
            },
            {
                "line_number": 2,
                "external_code": "ERP-00002",
                "barcode": "6260000000002",
                "product_name": "نوشیدنی — مدل 3",
                "quantity": 5,
                "unit_price_minor": 1500000,
                "line_total_minor": 7500000,
                "tax_minor": 750000,
            },
            {
                "line_number": 3,
                "external_code": None,
                "barcode": None,
                "product_name": "محصول ناشناس",
                "quantity": 2,
                "unit_price_minor": 500000,
                "line_total_minor": 1000000,
                "tax_minor": 100000,
            },
        ]
        subtotal = sum(l["line_total_minor"] for l in lines)
        tax = sum(l["tax_minor"] for l in lines)
        total = subtotal + tax
        return {
            "invoice_number": f"MOCK-OCR-{len(raw_bytes):06d}",
            "invoice_date": "2026-08-08",
            "supplier_name": "تأمین‌کننده نمونه",
            "subtotal_minor": subtotal,
            "tax_minor": tax,
            "total_minor": total,
            "currency": "IRR",
            "lines": lines,
            "raw_json": {"bytes_length": len(raw_bytes), "source": "mock_ocr"},
            "confidence_bps": 8500,
        }

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": "mock_ocr — آماده (شبیه‌سازی OCR)",
            "latency_ms": 0,
        }
