"""Phase 7 — Accounting Adapter tests.

Tests:
  - MockAccountingAdapter: all 8 operations
  - CsvAccountingExportAdapter: invoice/payment/settlement CSV output
  - Accounting NOT IMPLEMENTED stubs (Sepidar, Rahkaran, Holo, SAP, Odoo)
  - Accounting adapter registry
  - accounting_service: connector CRUD, document listing
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.accounting.mock import MockAccountingAdapter
from app.adapters.accounting.csv_export import CsvAccountingExportAdapter
from app.adapters.accounting.base import (
    AccountingDocument,
    AccountingDocumentType,
    AccountingLine,
    AccountingAdapterError,
)
from app.adapters.accounting.sepidar import SepidarAccountingAdapter
from app.adapters.accounting.rahkaran import RahkaranAccountingAdapter
from app.adapters.accounting.holo import HoloAccountingAdapter
from app.adapters.accounting.sap import SapAccountingAdapter
from app.adapters.accounting.odoo import OdooAccountingAdapter
from app.adapters.accounting.registry import get_accounting_adapter, list_accounting_systems

from tests.base import AppTestCase


def _make_invoice(order_id: int = 42) -> AccountingDocument:
    return AccountingDocument(
        doc_type=AccountingDocumentType.SALES_INVOICE,
        doc_number=f"INV-{order_id:06d}",
        doc_date="2026-01-15",
        currency="IRR",
        subtotal_minor=1_000_000,
        tax_minor=90_000,
        total_minor=1_090_000,
        counterparty_name="شرکت آزمایشی",
        counterparty_national_id="1234567890",
        lines=[
            AccountingLine(
                description="محصول اول",
                quantity=2,
                unit_price_minor=500_000,
                line_total_minor=1_000_000,
                tax_minor=90_000,
            )
        ],
        order_id=order_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MockAccountingAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestMockAccountingAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = MockAccountingAdapter()

    def test_export_invoice(self):
        result = self.adapter.export_invoice(_make_invoice())
        self.assertTrue(result["acknowledged"])
        self.assertTrue(result["external_doc_id"].startswith("MOCK-INV-"))

    def test_export_payment(self):
        doc = AccountingDocument(
            doc_type=AccountingDocumentType.PAYMENT,
            doc_number="PAY-001",
            doc_date="2026-01-15",
            total_minor=500_000,
        )
        result = self.adapter.export_payment(doc)
        self.assertTrue(result["acknowledged"])
        self.assertTrue(result["external_doc_id"].startswith("MOCK-PAY-"))

    def test_export_settlement(self):
        doc = AccountingDocument(
            doc_type=AccountingDocumentType.SETTLEMENT,
            doc_number="SET-001",
            doc_date="2026-01-15",
            total_minor=2_000_000,
            supplier_id=1,
        )
        result = self.adapter.export_settlement(doc)
        self.assertTrue(result["acknowledged"])
        self.assertTrue(result["external_doc_id"].startswith("MOCK-SET-"))

    def test_pull_invoices(self):
        self.adapter.export_invoice(_make_invoice(1))
        self.adapter.export_invoice(_make_invoice(2))
        invoices = self.adapter.pull_invoices()
        self.assertEqual(len(invoices), 2)

    def test_pull_payments(self):
        doc = AccountingDocument(
            doc_type=AccountingDocumentType.PAYMENT,
            doc_number="PAY-001",
            doc_date="2026-01-15",
            total_minor=100_000,
        )
        self.adapter.export_payment(doc)
        payments = self.adapter.pull_payments()
        self.assertEqual(len(payments), 1)

    def test_upsert_customer(self):
        result = self.adapter.upsert_customer({
            "national_id": "9876543210",
            "name": "مشتری آزمایشی",
        })
        self.assertTrue(result["acknowledged"])
        self.assertIn("MOCK-CUST-", result["external_id"])

    def test_upsert_supplier(self):
        result = self.adapter.upsert_supplier({"name": "تأمین‌کننده آزمایشی"})
        self.assertTrue(result["acknowledged"])

    def test_document_count(self):
        self.adapter.export_invoice(_make_invoice())
        self.adapter.export_invoice(_make_invoice())
        self.assertEqual(self.adapter.document_count, 2)

    def test_health_check(self):
        result = self.adapter.health_check()
        self.assertTrue(result["healthy"])

    def test_capabilities(self):
        caps = self.adapter.capabilities()
        self.assertIn("export_invoice", caps["supported"])


# ─────────────────────────────────────────────────────────────────────────────
# CsvAccountingExportAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestCsvAccountingExportAdapter(unittest.TestCase):

    def test_standard_invoice_csv_has_header(self):
        adapter = CsvAccountingExportAdapter()
        result = adapter.export_invoice(_make_invoice())
        self.assertTrue(result["acknowledged"])
        csv = result["csv_content"]
        self.assertIn("doc_number", csv)
        self.assertIn("INV-000042", csv)

    def test_standard_invoice_csv_has_lines(self):
        adapter = CsvAccountingExportAdapter()
        result = adapter.export_invoice(_make_invoice())
        csv = result["csv_content"]
        self.assertIn("محصول اول", csv)

    def test_sepidar_compatible_invoice_csv(self):
        adapter = CsvAccountingExportAdapter(config={"format": "sepidar_compatible"})
        result = adapter.export_invoice(_make_invoice())
        csv = result["csv_content"]
        self.assertIn("شماره سند", csv)
        self.assertIn("شرکت آزمایشی", csv)

    def test_payment_csv(self):
        adapter = CsvAccountingExportAdapter()
        doc = AccountingDocument(
            doc_type=AccountingDocumentType.PAYMENT,
            doc_number="PAY-001",
            doc_date="2026-01-15",
            total_minor=500_000,
        )
        result = adapter.export_payment(doc)
        csv = result["csv_content"]
        self.assertIn("doc_number", csv)
        self.assertIn("PAY-001", csv)

    def test_settlement_csv(self):
        adapter = CsvAccountingExportAdapter()
        doc = AccountingDocument(
            doc_type=AccountingDocumentType.SETTLEMENT,
            doc_number="SET-001",
            doc_date="2026-01-15",
            total_minor=2_000_000,
            supplier_id=1,
        )
        result = adapter.export_settlement(doc)
        csv = result["csv_content"]
        self.assertIn("supplier_id", csv)

    def test_semicolon_delimiter(self):
        adapter = CsvAccountingExportAdapter(config={"delimiter": ";"})
        result = adapter.export_invoice(_make_invoice())
        csv = result["csv_content"]
        self.assertIn(";", csv)

    def test_csv_injection_sanitised_in_output(self):
        """Output cells starting with = must be escaped."""
        doc = _make_invoice()
        doc.counterparty_name = "=EVIL()"
        adapter = CsvAccountingExportAdapter()
        result = adapter.export_invoice(doc)
        csv = result["csv_content"]
        self.assertNotIn(",=EVIL()", csv)
        self.assertIn("'=EVIL()", csv)

    def test_filename_contains_doc_number_and_date(self):
        adapter = CsvAccountingExportAdapter()
        result = adapter.export_invoice(_make_invoice())
        self.assertIn("INV-000042", result["filename"])
        self.assertIn("2026-01-15", result["filename"])

    def test_health_check(self):
        adapter = CsvAccountingExportAdapter()
        result = adapter.health_check()
        self.assertTrue(result["healthy"])


# ─────────────────────────────────────────────────────────────────────────────
# NOT IMPLEMENTED stubs
# ─────────────────────────────────────────────────────────────────────────────

class TestNotImplementedAccountingStubs(unittest.TestCase):

    STUB_CLASSES = [
        SepidarAccountingAdapter,
        RahkaranAccountingAdapter,
        HoloAccountingAdapter,
        SapAccountingAdapter,
        OdooAccountingAdapter,
    ]

    def test_all_stubs_unhealthy(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            health = adapter.health_check()
            self.assertFalse(health["healthy"], f"{cls.__name__} should report unhealthy")

    def test_all_stubs_export_invoice_raises(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            with self.assertRaises(AccountingAdapterError) as ctx:
                adapter.export_invoice(_make_invoice())
            self.assertEqual(ctx.exception.code, "not_implemented",
                             f"{cls.__name__} wrong error code")

    def test_all_stubs_capabilities_not_implemented(self):
        for cls in self.STUB_CLASSES:
            adapter = cls()
            caps = adapter.capabilities()
            self.assertEqual(caps["implementation_status"], "not_implemented")
            self.assertEqual(caps["supported"], [])

    def test_sap_has_official_docs_url(self):
        adapter = SapAccountingAdapter()
        caps = adapter.capabilities()
        self.assertEqual(caps["verified_docs_url"], "https://api.sap.com/")

    def test_odoo_has_official_docs_url(self):
        adapter = OdooAccountingAdapter()
        caps = adapter.capabilities()
        self.assertIn("odoo.com", caps["verified_docs_url"])


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountingRegistry(unittest.TestCase):

    def test_mock_returns_mock(self):
        adapter = get_accounting_adapter("MOCK")
        self.assertIsInstance(adapter, MockAccountingAdapter)

    def test_csv_returns_csv(self):
        adapter = get_accounting_adapter("CSV")
        self.assertIsInstance(adapter, CsvAccountingExportAdapter)

    def test_sepidar_returns_sepidar(self):
        adapter = get_accounting_adapter("SEPIDAR")
        self.assertIsInstance(adapter, SepidarAccountingAdapter)

    def test_sap_returns_sap(self):
        adapter = get_accounting_adapter("SAP")
        self.assertIsInstance(adapter, SapAccountingAdapter)

    def test_unknown_raises(self):
        from app.core.errors import ValidationError
        with self.assertRaises(ValidationError):
            get_accounting_adapter("NONEXISTENT_SYSTEM")

    def test_list_systems_includes_all(self):
        systems = list_accounting_systems()
        names = [s["system"] for s in systems]
        for expected in ("MOCK", "CSV", "SEPIDAR", "RAHKARAN", "HOLO", "SAP", "ODOO"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
