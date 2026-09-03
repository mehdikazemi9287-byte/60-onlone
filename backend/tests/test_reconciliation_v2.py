"""Reconciliation v2 tests — multi-signal matching (Blocker 7)."""
import unittest
from tests.base import AppTestCase
from app.services import reconciliation_service


class ReconciliationV2Test(AppTestCase):

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
                ("recon_admin_v2@test.com", "recon_admin_v2@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "Recon Admin", "admin", 1),
            )
            self.admin_id = int(cur.lastrowid)

    def _make_payment(self, conn, provider_ref: str, amount: int) -> int:
        cur = conn.execute(
            "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
            (f"buyer_rv2_{provider_ref}@test.com", f"buyer_rv2_{provider_ref}@test.com",
             "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
             "خریدار", "customer", 1),
        )
        buyer_id = int(cur.lastrowid)
        cur = conn.execute(
            """INSERT INTO orders
               (order_number, user_id, status, subtotal_minor, shipping_fee_minor, total_minor,
                currency, recipient_name, recipient_phone, shipping_province, shipping_city,
                shipping_line1, shipping_postal_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"ORD-RV2-{provider_ref}", buyer_id, "paid", amount, 0, amount, "IRR",
             "Test Buyer", "09120000000", "Tehran", "Tehran", "Test Street", "1234567890"),
        )
        order_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO payments (order_id, provider, provider_ref, method, amount_minor, currency, status) VALUES (?,?,?,?,?,?,?)",
            (order_id, "zarinpal", provider_ref, "card", amount, "IRR", "captured"),
        )
        return order_id

    def test_unique_ref_match_beats_amount(self):
        """external_ref == provider_ref → matched at 10000 bps, even if other amounts match."""
        with self.db.write_transaction() as conn:
            self._make_payment(conn, "ZRN-RV2-UNIQUE", 8888000)
            self._make_payment(conn, "ZRN-RV2-OTHER", 8888000)  # Same amount, different ref

            batch = reconciliation_service.create_batch(
                conn, batch_ref="B-RV2-REF-001", source_type="psp_statement",
                period_start="2026-01-01", period_end="2026-01-31",
                created_by=self.admin_id,
            )
            reconciliation_service.import_items(
                conn, batch["id"],
                [{"external_ref": "ZRN-RV2-UNIQUE", "transaction_date": "2026-01-10",
                  "amount_minor": 8888000}],
            )
            result = reconciliation_service.run_matching(conn, batch_id=batch["id"])
            item = conn.execute(
                "SELECT * FROM reconciliation_items WHERE batch_id=?", (batch["id"],)
            ).fetchone()

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(int(item["match_confidence_bps"]), 10000,
                         "Unique ref match must have confidence=10000")

    def test_two_same_amount_payments_causes_ambiguous(self):
        """Two payments with same amount → item stays unmatched/partial → exception created."""
        with self.db.write_transaction() as conn:
            self._make_payment(conn, "ZRN-RV2-DUPE-A", 7777000)
            self._make_payment(conn, "ZRN-RV2-DUPE-B", 7777000)

            batch = reconciliation_service.create_batch(
                conn, batch_ref="B-RV2-AMB-002", source_type="psp_statement",
                period_start="2026-02-01", period_end="2026-02-28",
                created_by=self.admin_id,
            )
            reconciliation_service.import_items(
                conn, batch["id"],
                [{"external_ref": "NO-KNOWN-RV2-REF", "transaction_date": "2026-02-05",
                  "amount_minor": 7777000}],
            )
            result = reconciliation_service.run_matching(conn, batch_id=batch["id"])

        self.assertEqual(result["matched_count"], 0,
                         "Must not auto-match ambiguous amount")
        self.assertGreater(result["ambiguous_count"], 0)

    def test_single_amount_payment_matched_at_lower_confidence(self):
        """Single payment with matching amount → matched at confidence=7000."""
        with self.db.write_transaction() as conn:
            self._make_payment(conn, "ZRN-RV2-SINGLE-001", 3333000)
            batch = reconciliation_service.create_batch(
                conn, batch_ref="B-RV2-SINGLE-003", source_type="psp_statement",
                period_start="2026-03-01", period_end="2026-03-31",
                created_by=self.admin_id,
            )
            reconciliation_service.import_items(
                conn, batch["id"],
                [{"external_ref": "RV2-UNKNOWN-REF-SINGLE", "transaction_date": "2026-03-01",
                  "amount_minor": 3333000}],
            )
            result = reconciliation_service.run_matching(conn, batch_id=batch["id"])
            item = conn.execute(
                "SELECT * FROM reconciliation_items WHERE batch_id=?", (batch["id"],)
            ).fetchone()

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(int(item["match_confidence_bps"]), 7000)

    def test_no_match_stays_unmatched(self):
        """Item with no matching ref or amount stays unmatched."""
        with self.db.write_transaction() as conn:
            batch = reconciliation_service.create_batch(
                conn, batch_ref="B-RV2-NONE-004", source_type="psp_statement",
                period_start="2026-04-01", period_end="2026-04-30",
                created_by=self.admin_id,
            )
            reconciliation_service.import_items(
                conn, batch["id"],
                [{"external_ref": "RV2-NO-MATCH-REF", "transaction_date": "2026-04-01",
                  "amount_minor": 1234567}],
            )
            result = reconciliation_service.run_matching(conn, batch_id=batch["id"])

        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["unmatched_count"], 1)


if __name__ == "__main__":
    unittest.main()
