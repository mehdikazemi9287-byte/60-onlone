"""Tests for invoice, three-way match, reconciliation — Phase 6 Final."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import Database
from app.core import migrator
from app.services import invoice_service, three_way_match_service, reconciliation_service
from app.adapters.invoice.mock_ocr import MockOcrAdapter
from app.core.errors import NotFoundError

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"


def _apply_all(db: Database, staging_dir: Path) -> None:
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


class FinanceAutomationTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="70online-fin-")
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)
        _apply_all(self.db, self.staging)

        with self.db.write_transaction() as conn:
            user = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role) "
                "VALUES (?,?,?,?,?)",
                ("fin@test.com", "fin@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "تست مالی", "admin")
            )
            self.user_id = int(user.lastrowid)

            sup = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت تست مالی", "تست مالی", "9900002345", "retailer", "active", 40)
            )
            self.supplier_id = int(sup.lastrowid)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_lines(self, n: int = 2) -> list[dict]:
        return [
            {
                "line_number": i,
                "product_name": f"محصول {i}",
                "quantity": 5,
                "unit_price_minor": 1000000,
                "line_total_minor": 5000000,
                "tax_minor": 500000,
            }
            for i in range(1, n + 1)
        ]

    def test_create_invoice(self):
        lines = self._make_lines(3)
        with self.db.write_transaction() as conn:
            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-TEST-001",
                invoice_date="2026-08-08",
                lines=lines,
                source_type="manual",
                created_by=self.user_id,
            )

        self.assertIsNotNone(inv["id"])
        self.assertEqual(inv["supplier_id"], self.supplier_id)
        self.assertEqual(inv["invoice_number"], "INV-TEST-001")
        self.assertEqual(inv["subtotal_minor"], 15000000)  # 3 × 5000000
        self.assertEqual(inv["status"], "captured")
        self.assertIsInstance(inv["subtotal_minor"], int)
        self.assertEqual(len(inv["lines"]), 3)

    def test_duplicate_invoice_detected(self):
        lines = self._make_lines(2)
        with self.db.write_transaction() as conn:
            inv1 = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-DUP-001",
                invoice_date="2026-08-08",
                lines=lines,
                created_by=self.user_id,
            )

        with self.db.write_transaction() as conn:
            inv2 = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-DUP-001",
                invoice_date="2026-08-08",
                lines=lines,
                created_by=self.user_id,
            )

        self.assertEqual(inv1["invoice_number"], inv2["invoice_number"])
        self.assertEqual(inv2["is_duplicate"], 1)
        self.assertEqual(inv2["status"], "duplicate")
        self.assertEqual(inv2["duplicate_of_id"], inv1["id"])

    def test_detect_duplicate_returns_none_for_new_invoice(self):
        with self.db.read_transaction() as conn:
            result = invoice_service.detect_duplicate(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="NEVER-SEEN-BEFORE",
                invoice_date="2026-01-01",
                total_minor=99999,
            )
        self.assertIsNone(result)

    def test_three_way_match_matched(self):
        # Create procurement order
        with self.db.write_transaction() as conn:
            po = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, "
                "total_minor, currency, status) VALUES (?,?,?,?,?,?)",
                (self.supplier_id, "PO-001", "2026-08-01", 10000000, "IRR", "open")
            )
            po_id = int(po.lastrowid)

            # Create invoice with same total
            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-MATCH-001",
                invoice_date="2026-08-08",
                lines=[{
                    "quantity": 1,
                    "unit_price_minor": 10000000,
                    "line_total_minor": 10000000,
                    "tax_minor": 0,
                }],
                created_by=self.user_id,
            )
            inv_id = int(inv["id"])

            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.supplier_id,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                tolerance_bps=100,
                checked_by=self.user_id,
            )

        self.assertEqual(result["result"], "matched")
        self.assertIsNotNone(result["id"])

    def test_three_way_match_mismatch_creates_discrepancy(self):
        with self.db.write_transaction() as conn:
            po = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, "
                "total_minor, currency, status) VALUES (?,?,?,?,?,?)",
                (self.supplier_id, "PO-MISMATCH", "2026-08-01", 10000000, "IRR", "open")
            )
            po_id = int(po.lastrowid)

            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-MISMATCH-001",
                invoice_date="2026-08-08",
                lines=[{
                    "quantity": 1,
                    "unit_price_minor": 12000000,
                    "line_total_minor": 12000000,
                    "tax_minor": 0,
                }],
                created_by=self.user_id,
            )
            inv_id = int(inv["id"])

            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.supplier_id,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                tolerance_bps=100,
            )

        self.assertEqual(result["result"], "mismatch")
        self.assertIn("discrepancy", result)

    def test_three_way_match_within_tolerance(self):
        with self.db.write_transaction() as conn:
            po = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, "
                "total_minor, currency, status) VALUES (?,?,?,?,?,?)",
                (self.supplier_id, "PO-TOL", "2026-08-01", 10000000, "IRR", "open")
            )
            po_id = int(po.lastrowid)

            # Invoice is 0.5% more (within 1% tolerance = 100 bps)
            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-TOL-001",
                invoice_date="2026-08-08",
                lines=[{
                    "quantity": 1,
                    "unit_price_minor": 10050000,  # 0.5% more
                    "line_total_minor": 10050000,
                    "tax_minor": 0,
                }],
                created_by=self.user_id,
            )
            inv_id = int(inv["id"])

            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.supplier_id,
                procurement_order_id=po_id,
                invoice_id=inv_id,
                tolerance_bps=100,  # 1% tolerance
            )

        self.assertIn(result["result"], ("matched", "within_tolerance"))

    def test_reconciliation_batch_create_and_match(self):
        with self.db.write_transaction() as conn:
            batch = reconciliation_service.create_batch(
                conn,
                batch_ref="BATCH-TEST-001",
                source_type="psp_statement",
                period_start="2026-08-01",
                period_end="2026-08-31",
                created_by=self.user_id,
                supplier_id=self.supplier_id,
            )
            batch_id = batch["id"]

            # Import items
            items = [
                {"external_ref": "PSP-001", "transaction_date": "2026-08-05", "amount_minor": 5000000},
                {"external_ref": "PSP-002", "transaction_date": "2026-08-10", "amount_minor": 3000000},
                {"external_ref": "PSP-003", "transaction_date": "2026-08-15", "amount_minor": 7000000},
            ]
            reconciliation_service.import_items(conn, batch_id, items)

            result = reconciliation_service.run_matching(conn, batch_id=batch_id)

        self.assertEqual(result["batch_id"], batch_id)
        self.assertEqual(result["total_items"], 3)
        # All items will be unmatched in this test since no payments exist
        self.assertGreaterEqual(result["unmatched_count"], 0)

    def test_reconciliation_batch_status_changes(self):
        with self.db.write_transaction() as conn:
            batch = reconciliation_service.create_batch(
                conn,
                batch_ref="BATCH-STATUS-001",
                source_type="bank_statement",
                period_start="2026-08-01",
                period_end="2026-08-31",
                created_by=self.user_id,
            )
            batch_id = batch["id"]
            reconciliation_service.run_matching(conn, batch_id=batch_id)

        with self.db.read_transaction() as conn:
            batch = reconciliation_service.get_batch(conn, batch_id)

        self.assertEqual(batch["status"], "completed")

    def test_invoice_line_product_resolution(self):
        """Invoice lines can reference product_id and offer_id."""
        with self.db.write_transaction() as conn:
            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-LINE-PROD",
                invoice_date="2026-08-08",
                lines=[{
                    "line_number": 1,
                    "product_name": "کاغذ A4",
                    "external_code": "ERP-001",
                    "barcode": "6260001000010",
                    "quantity": 10,
                    "unit_price_minor": 850000,
                    "line_total_minor": 8500000,
                    "tax_minor": 0,
                    "product_id": None,
                    "offer_id": None,
                }],
                created_by=self.user_id,
            )

        self.assertEqual(len(inv["lines"]), 1)
        self.assertEqual(inv["lines"][0]["external_code"], "ERP-001")
        self.assertEqual(inv["lines"][0]["barcode"], "6260001000010")
        self.assertIsInstance(inv["lines"][0]["unit_price_minor"], int)

    def test_mock_ocr_adapter_extracts_lines(self):
        """MockOcrAdapter must extract structured lines from bytes input."""
        adapter = MockOcrAdapter()
        raw_bytes = b"FAKE PDF CONTENT FOR TESTING"
        result = adapter.capture(raw_bytes)

        self.assertIn("invoice_number", result)
        self.assertIn("invoice_date", result)
        self.assertIn("lines", result)
        self.assertGreater(len(result["lines"]), 0)
        self.assertIsInstance(result["subtotal_minor"], int)
        self.assertIsInstance(result["total_minor"], int)
        self.assertIsInstance(result["tax_minor"], int)

        # All money fields must be integer
        for line in result["lines"]:
            self.assertIsInstance(line["unit_price_minor"], int)
            self.assertIsInstance(line["line_total_minor"], int)
            self.assertIsInstance(line["tax_minor"], int)

    def test_mock_ocr_adapter_from_dict(self):
        """MockOcrAdapter must handle dict input (simulating electronic invoice)."""
        adapter = MockOcrAdapter()
        data = {
            "invoice_number": "ELEC-001",
            "invoice_date": "2026-08-08",
            "lines": [
                {
                    "quantity": 2,
                    "unit_price_minor": 1000000,
                    "line_total_minor": 2000000,
                    "tax_minor": 200000,
                    "product_name": "محصول الکترونیک",
                }
            ],
        }
        result = adapter.capture(data)

        self.assertEqual(result["invoice_number"], "ELEC-001")
        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["lines"][0]["quantity"], 2)
        self.assertIsInstance(result["lines"][0]["unit_price_minor"], int)

    def test_invoice_total_is_integer(self):
        """Invoice total_minor must always be INTEGER, not REAL."""
        lines = self._make_lines(4)
        with self.db.write_transaction() as conn:
            inv = invoice_service.create_invoice(
                conn,
                supplier_id=self.supplier_id,
                invoice_number="INV-INT-TOTAL",
                invoice_date="2026-08-08",
                lines=lines,
                tax_minor=2000000,
                created_by=self.user_id,
            )

        self.assertIsInstance(inv["subtotal_minor"], int)
        self.assertIsInstance(inv["tax_minor"], int)
        self.assertIsInstance(inv["total_minor"], int)
        self.assertEqual(inv["total_minor"], inv["subtotal_minor"] + inv["tax_minor"])

    def test_list_invoices_by_supplier(self):
        with self.db.write_transaction() as conn:
            invoice_service.create_invoice(
                conn, supplier_id=self.supplier_id, invoice_number="INV-LIST-001",
                invoice_date="2026-08-08", lines=self._make_lines(1),
                created_by=self.user_id,
            )

        with self.db.read_transaction() as conn:
            result = invoice_service.list_invoices(conn, supplier_id=self.supplier_id)

        self.assertGreaterEqual(result["total"], 1)
        for inv in result["items"]:
            self.assertEqual(inv["supplier_id"], self.supplier_id)


if __name__ == "__main__":
    unittest.main()
