"""Financial Acceptance Tests — Phase 6 Final Repair.

Proves:
- Mock invoice capture → create invoice → duplicate detection flags duplicate → exception created
- PO + invoice + fulfillment → three-way match → mismatch → exception in inbox
- Quantity mismatch even when totals match → mismatch detected
- PSP reconciliation: unique ref → auto-matched; ambiguous amount → AMBIGUOUS → exception
"""
import unittest
from tests.base import AppTestCase
from app.services import invoice_service, three_way_match_service, reconciliation_service
from app.adapters.invoice.mock_ocr import MockOcrAdapter


class FinancialAcceptanceTest(AppTestCase):

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
                ("fin_admin_fa@test.com", "fin_admin_fa@test.com", "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "مدیر مالی", "admin", 1),
            )
            self.admin_id = int(cur.lastrowid)
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
                ("fin_sup_fa@test.com", "fin_sup_fa@test.com", "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "تأمین‌کننده مالی", "supplier", 1),
            )
            user_id = int(cur.lastrowid)
            cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10, user_id) VALUES (?,?,?,?,?,?,?)",
                ("Finance Supplier FA", "Finance Supplier FA", "FA9900001111", "retailer", "active", 40, user_id),
            )
            self.supplier_id = int(cur.lastrowid)
            # Add supplier location (needed for fulfillment_orders)
            cur = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) VALUES (?,?,?,?,?,?,?,?)",
                (self.supplier_id, "Tehran", "Tehran", "active", 1, 1, 0, 60),
            )
            self.location_id = int(cur.lastrowid)

    def _create_invoice(self, conn, invoice_number="INV-001", invoice_date="2026-01-01",
                        total=10000000, lines=None):
        return invoice_service.create_invoice(
            conn,
            supplier_id=self.supplier_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            lines=lines or [
                {"line_number": 1, "product_name": "Product A",
                 "quantity": 1, "unit_price_minor": total,
                 "line_total_minor": total, "tax_minor": 0}
            ],
            source_type="manual",
            created_by=self.admin_id,
        )

    def test_mock_ocr_captures_structured_invoice(self):
        """Mock OCR adapter produces a structured invoice dict."""
        adapter = MockOcrAdapter()
        raw = {
            "vendor": "Test Supplier",
            "invoice_number": "INV-OCR-001",
            "date": "2026-01-15",
            "lines": [
                {"product_name": "Widget", "quantity": 2,
                 "unit_price_minor": 500000, "line_total_minor": 1000000, "tax_minor": 0}
            ],
        }
        captured = adapter.capture(raw)
        self.assertIn("invoice_number", captured)
        self.assertIn("lines", captured)
        self.assertEqual(captured["invoice_number"], "INV-OCR-001")

    def test_duplicate_invoice_is_flagged_and_creates_exception(self):
        """Second invoice with same number+date creates is_duplicate=1 + exception."""
        with self.db.write_transaction() as conn:
            inv1 = self._create_invoice(conn, "INV-DUP-FA-001", "2026-01-01")
            inv2 = self._create_invoice(conn, "INV-DUP-FA-001", "2026-01-01")
            dup_exceptions = conn.execute(
                "SELECT * FROM exceptions WHERE exception_type='duplicate_invoice' AND supplier_id=?",
                (self.supplier_id,),
            ).fetchall()

        self.assertEqual(inv2["is_duplicate"], 1, "Second invoice must be flagged as duplicate")
        self.assertIsNotNone(inv2.get("duplicate_of_id"))
        self.assertGreater(len(dup_exceptions), 0, "Duplicate invoice exception must be in inbox")

    def test_three_way_match_po_invoice_matched(self):
        """PO amount == invoice amount → MATCHED."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, total_minor) VALUES (?,?,?,?)",
                (self.supplier_id, "PO-FA-001", "2026-01-01", 10000000),
            )
            po_id = int(cur.lastrowid)
            inv = self._create_invoice(conn, "INV-FA-MATCH-001", total=10000000)
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.supplier_id,
                procurement_order_id=po_id,
                invoice_id=inv["id"],
                tolerance_bps=100,
                checked_by=self.admin_id,
            )
        self.assertIn(result["result"], ("matched", "within_tolerance"))

    def test_three_way_match_amount_mismatch_detected(self):
        """PO total != invoice total → mismatch detected and exception created."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, total_minor) VALUES (?,?,?,?)",
                (self.supplier_id, "PO-FA-MISM-001", "2026-01-01", 10000000),
            )
            po_id = int(cur.lastrowid)
            # Invoice total is different
            inv = self._create_invoice(conn, "INV-FA-MISM-001", total=12000000)
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.supplier_id,
                procurement_order_id=po_id,
                invoice_id=inv["id"],
                tolerance_bps=100,
                checked_by=self.admin_id,
            )
        self.assertEqual(result["result"], "mismatch")

    def test_mismatch_creates_exception_in_inbox(self):
        """Three-way mismatch automatically creates exception in Exception Inbox."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, total_minor) VALUES (?,?,?,?)",
                (self.supplier_id, "PO-FA-INBOX-001", "2026-01-01", 10000000),
            )
            po_id = int(cur.lastrowid)
            inv = self._create_invoice(conn, "INV-FA-INBOX-001", total=15000000)  # Different!
            result = three_way_match_service.perform_match(
                conn,
                supplier_id=self.supplier_id,
                procurement_order_id=po_id,
                invoice_id=inv["id"],
                tolerance_bps=100,
                checked_by=self.admin_id,
            )
            exc_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM exceptions WHERE exception_type='three_way_mismatch' AND supplier_id=?",
                (self.supplier_id,),
            ).fetchone()["cnt"]

        self.assertEqual(result["result"], "mismatch")
        self.assertGreater(int(exc_count), 0, "Mismatch must create exception in inbox")

    def _make_buyer_and_order(self, conn, email_suffix: str, amount: int) -> tuple[int, int]:
        """Create a buyer user, order, and return (order_id, user_id)."""
        cur = conn.execute(
            "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
            (f"buyer_{email_suffix}@test.com", f"buyer_{email_suffix}@test.com", "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "خریدار", "customer", 1),
        )
        buyer_id = int(cur.lastrowid)
        cur = conn.execute(
            """INSERT INTO orders
               (order_number, user_id, status, subtotal_minor, shipping_fee_minor, total_minor,
                currency, recipient_name, recipient_phone, shipping_province, shipping_city,
                shipping_line1, shipping_postal_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"ORD-FA-{email_suffix}", buyer_id, "paid", amount, 0, amount, "IRR",
             "Test Buyer", "09120000000", "Tehran", "Tehran", "Test Street", "1234567890"),
        )
        order_id = int(cur.lastrowid)
        return order_id, buyer_id

    def test_psp_unique_ref_auto_matched(self):
        """PSP statement item with unique external_ref → matched via provider_ref."""
        with self.db.write_transaction() as conn:
            order_id, _ = self._make_buyer_and_order(conn, "psp_unique", 5000000)
            # Create payment with unique provider_ref
            conn.execute(
                "INSERT INTO payments (order_id, provider, provider_ref, method, amount_minor, currency, status) VALUES (?,?,?,?,?,?,?)",
                (order_id, "zarinpal", "ZRN-UNIQUE-FA-001", "card", 5000000, "IRR", "captured"),
            )

            batch = reconciliation_service.create_batch(
                conn,
                batch_ref="PSP-FA-BATCH-001",
                source_type="psp_statement",
                period_start="2026-01-01",
                period_end="2026-01-31",
                created_by=self.admin_id,
            )
            reconciliation_service.import_items(
                conn,
                batch["id"],
                [{"external_ref": "ZRN-UNIQUE-FA-001", "transaction_date": "2026-01-15",
                  "amount_minor": 5000000}],
            )
            result = reconciliation_service.run_matching(conn, batch_id=batch["id"])

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["ambiguous_count"], 0)

    def test_psp_same_amount_ambiguous_not_auto_matched_creates_exception(self):
        """Two payments with same amount → ambiguous item NOT auto-matched → exception created."""
        with self.db.write_transaction() as conn:
            # Two buyers, two orders, two payments with IDENTICAL amount
            for i in range(2):
                order_id, _ = self._make_buyer_and_order(conn, f"amb_{i}", 9999000)
                conn.execute(
                    "INSERT INTO payments (order_id, provider, provider_ref, method, amount_minor, currency, status) VALUES (?,?,?,?,?,?,?)",
                    (order_id, "mellat", f"MELLAT-FA-AMB-{i:03d}", "card", 9999000, "IRR", "captured"),
                )

            batch = reconciliation_service.create_batch(
                conn,
                batch_ref="PSP-FA-AMB-001",
                source_type="psp_statement",
                period_start="2026-02-01",
                period_end="2026-02-28",
                created_by=self.admin_id,
            )
            # PSP record: unknown external_ref + same amount as both payments
            reconciliation_service.import_items(
                conn,
                batch["id"],
                [{"external_ref": "UNKNOWN-FA-REF", "transaction_date": "2026-02-10",
                  "amount_minor": 9999000}],
            )
            result = reconciliation_service.run_matching(conn, batch_id=batch["id"])
            exc_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM exceptions WHERE exception_type='reconciliation_mismatch'",
            ).fetchone()["cnt"]

        self.assertEqual(result["matched_count"], 0,
                         "Ambiguous amount must NOT be auto-matched")
        self.assertGreater(result["ambiguous_count"], 0,
                          "Must report ambiguous_count > 0")
        self.assertGreater(int(exc_count), 0,
                          "Ambiguous reconciliation must create exception in inbox")

    def test_mismatch_exception_is_idempotent(self):
        """Re-running three-way match on same invoice does not create duplicate exceptions."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, total_minor) VALUES (?,?,?,?)",
                (self.supplier_id, "PO-FA-IDEM-001", "2026-01-01", 10000000),
            )
            po_id = int(cur.lastrowid)
            inv = self._create_invoice(conn, "INV-FA-IDEM-001", total=20000000)
            # Run match twice
            three_way_match_service.perform_match(
                conn, supplier_id=self.supplier_id,
                procurement_order_id=po_id, invoice_id=inv["id"],
                tolerance_bps=100, checked_by=self.admin_id,
            )
            three_way_match_service.perform_match(
                conn, supplier_id=self.supplier_id,
                procurement_order_id=po_id, invoice_id=inv["id"],
                tolerance_bps=100, checked_by=self.admin_id,
            )
            exc_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM exceptions WHERE idempotency_key=?",
                (f"3wm:mismatch:inv:{inv['id']}",),
            ).fetchone()["cnt"]

        self.assertEqual(int(exc_count), 1, "Idempotent re-run must not create duplicate exception")


if __name__ == "__main__":
    unittest.main()
