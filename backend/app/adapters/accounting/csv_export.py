"""CSV Accounting Export Adapter.

Exports 60online accounting documents to CSV format compatible with
common Iranian accounting software (Sepidar, Rahkaran, Holo, etc.).

Note: This adapter generates CSV OUTPUT only — it does not call any
external API. The CSV is returned as a string for the caller to save
or transmit.

CSV injection protection: all values are sanitised before output.
"""
from __future__ import annotations

import csv
import io
import unicodedata

from app.adapters.accounting.base import (
    AccountingAdapter,
    AccountingAdapterError,
    AccountingDocument,
    AccountingDocumentType,
)


def _safe_cell(value) -> str:
    """Sanitise a cell value to prevent CSV injection."""
    s = unicodedata.normalize("NFC", str(value or "").strip())
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return s


class CsvAccountingExportAdapter(AccountingAdapter):
    """Export accounting documents as CSV files.

    Config keys:
        format   : 'standard' | 'sepidar_compatible' | 'rahkaran_compatible'
        delimiter: ',' | ';' | '\t'
        encoding : 'utf-8' | 'windows-1256'
    """

    adapter_name = "ACCOUNTING_CSV"
    implementation_status = "simulator"

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.format = cfg.get("format", "standard")
        self.delimiter = cfg.get("delimiter", ",")
        self.encoding = cfg.get("encoding", "utf-8")
        self._exported_docs: list[dict] = []

    def capabilities(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "implementation_status": self.implementation_status,
            "supported": ["export_invoice", "export_payment", "export_settlement"],
            "formats": ["standard", "sepidar_compatible", "rahkaran_compatible"],
        }

    def health_check(self) -> dict:
        return {
            "healthy": True,
            "message": f"CSV accounting export — format: {self.format}",
            "latency_ms": 0,
        }

    def export_invoice(self, doc: AccountingDocument) -> dict:
        """Export invoice to CSV string. Returns CSV in result."""
        csv_str = self._generate_invoice_csv(doc)
        self._exported_docs.append({"type": "invoice", "number": doc.doc_number})
        return {
            "acknowledged": True,
            "external_doc_id": None,
            "message": f"CSV خروجی آماده است ({len(doc.lines)} ردیف)",
            "csv_content": csv_str,
            "filename": f"invoice_{doc.doc_number}_{doc.doc_date}.csv",
        }

    def export_payment(self, doc: AccountingDocument) -> dict:
        csv_str = self._generate_payment_csv(doc)
        return {
            "acknowledged": True,
            "external_doc_id": None,
            "message": "CSV پرداخت آماده است",
            "csv_content": csv_str,
            "filename": f"payment_{doc.doc_number}_{doc.doc_date}.csv",
        }

    def export_settlement(self, doc: AccountingDocument) -> dict:
        csv_str = self._generate_settlement_csv(doc)
        return {
            "acknowledged": True,
            "external_doc_id": None,
            "message": "CSV تسویه آماده است",
            "csv_content": csv_str,
            "filename": f"settlement_{doc.doc_number}_{doc.doc_date}.csv",
        }

    # ── CSV generators ────────────────────────────────────────────────────────

    def _generate_invoice_csv(self, doc: AccountingDocument) -> str:
        out = io.StringIO()
        w = csv.writer(out, delimiter=self.delimiter)

        if self.format == "sepidar_compatible":
            # Sepidar-like field order (hypothetical — NOT verified official format)
            # IMPORTANT: This is a generic CSV, NOT a verified Sepidar API call.
            w.writerow(["شماره سند", "تاریخ", "نوع", "طرف حساب",
                        "جمع کل", "مالیات", "ارز"])
            w.writerow([
                _safe_cell(doc.doc_number), _safe_cell(doc.doc_date),
                _safe_cell(doc.doc_type), _safe_cell(doc.counterparty_name),
                _safe_cell(doc.total_minor), _safe_cell(doc.tax_minor),
                _safe_cell(doc.currency),
            ])
            if doc.lines:
                w.writerow([])
                w.writerow(["شرح", "تعداد", "قیمت واحد", "جمع ردیف", "مالیات ردیف"])
                for ln in doc.lines:
                    w.writerow([
                        _safe_cell(ln.description), _safe_cell(ln.quantity),
                        _safe_cell(ln.unit_price_minor), _safe_cell(ln.line_total_minor),
                        _safe_cell(ln.tax_minor),
                    ])
        else:
            # Standard format
            w.writerow(["doc_number", "doc_date", "doc_type", "counterparty_name",
                        "counterparty_national_id", "subtotal_minor", "tax_minor",
                        "total_minor", "currency", "order_id"])
            w.writerow([
                _safe_cell(doc.doc_number), _safe_cell(doc.doc_date),
                _safe_cell(doc.doc_type), _safe_cell(doc.counterparty_name),
                _safe_cell(doc.counterparty_national_id),
                _safe_cell(doc.subtotal_minor), _safe_cell(doc.tax_minor),
                _safe_cell(doc.total_minor), _safe_cell(doc.currency),
                _safe_cell(doc.order_id or ""),
            ])
            if doc.lines:
                w.writerow([])
                w.writerow(["description", "quantity", "unit_price_minor",
                            "line_total_minor", "tax_minor", "tax_category_code", "product_code"])
                for ln in doc.lines:
                    w.writerow([
                        _safe_cell(ln.description), _safe_cell(ln.quantity),
                        _safe_cell(ln.unit_price_minor), _safe_cell(ln.line_total_minor),
                        _safe_cell(ln.tax_minor), _safe_cell(ln.tax_category_code),
                        _safe_cell(ln.product_code),
                    ])

        return out.getvalue()

    def _generate_payment_csv(self, doc: AccountingDocument) -> str:
        out = io.StringIO()
        w = csv.writer(out, delimiter=self.delimiter)
        w.writerow(["doc_number", "doc_date", "doc_type", "total_minor", "currency",
                    "counterparty_name", "order_id"])
        w.writerow([
            _safe_cell(doc.doc_number), _safe_cell(doc.doc_date),
            _safe_cell(doc.doc_type), _safe_cell(doc.total_minor),
            _safe_cell(doc.currency), _safe_cell(doc.counterparty_name),
            _safe_cell(doc.order_id or ""),
        ])
        return out.getvalue()

    def _generate_settlement_csv(self, doc: AccountingDocument) -> str:
        out = io.StringIO()
        w = csv.writer(out, delimiter=self.delimiter)
        w.writerow(["doc_number", "doc_date", "supplier_id", "total_minor",
                    "currency", "counterparty_name"])
        w.writerow([
            _safe_cell(doc.doc_number), _safe_cell(doc.doc_date),
            _safe_cell(doc.supplier_id or ""), _safe_cell(doc.total_minor),
            _safe_cell(doc.currency), _safe_cell(doc.counterparty_name),
        ])
        return out.getvalue()
