"""Tests for supplier payable ledger (BLOCKER 6)."""
from __future__ import annotations

import unittest

from tests.base import AppTestCase
from app.services import supplier_ledger_service
from app.core.errors import ConflictError, NotFoundError, ValidationError


class SupplierLedgerTest(AppTestCase):
    """Tests for record_sale_payable and query helpers."""

    def _setup_delivered_fo(self):
        """Create a real delivered FO using the API flow."""
        _, headers = self.new_customer()
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 5)
        self.add_to_cart(headers, product["id"], 1)
        resp = self.checkout(headers)
        self.assertEqual(resp.status_code, 201, resp.get_json())

        # Find the FO
        with self.db.read_transaction() as conn:
            fo = conn.execute(
                "SELECT fo.* FROM fulfillment_orders fo "
                "JOIN orders o ON o.id = fo.order_id "
                "ORDER BY fo.id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(fo)
            return dict(fo)

    def test_record_sale_payable_requires_delivered(self):
        """Cannot record payable for non-delivered FO."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        with self.db.write_transaction() as conn:
            with self.assertRaises(ConflictError) as ctx:
                supplier_ledger_service.record_sale_payable(
                    conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
                )
        self.assertEqual(ctx.exception.code, "fo_not_delivered")

    def test_record_sale_payable_on_delivered_fo(self):
        """Payable is recorded when FO is delivered."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        # Mark FO as delivered via direct DB update (simulating carrier webhook)
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,)
            )
            entry = supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )

        self.assertEqual(entry["supplier_id"], supplier_id)
        self.assertEqual(entry["fulfillment_order_id"], fo_id)
        self.assertEqual(entry["entry_type"], "sale_payable")
        self.assertEqual(entry["status"], "unbatched")
        self.assertGreater(entry["gross_minor"], 0)

    def test_record_sale_payable_idempotent(self):
        """Calling record_sale_payable twice returns the same entry."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            entry1 = supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )
            entry2 = supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )

        self.assertEqual(entry1["id"], entry2["id"])

    def test_record_sale_payable_supplier_mismatch(self):
        """Cannot record payable for wrong supplier."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            with self.assertRaises(ConflictError) as ctx:
                supplier_ledger_service.record_sale_payable(
                    conn, fulfillment_order_id=fo_id, supplier_id=99999
                )
        self.assertEqual(ctx.exception.code, "supplier_mismatch")

    def test_record_sale_payable_fo_not_found(self):
        """Non-existent FO raises NotFoundError."""
        with self.db.write_transaction() as conn:
            with self.assertRaises(NotFoundError):
                supplier_ledger_service.record_sale_payable(
                    conn, fulfillment_order_id=99999, supplier_id=1
                )

    def test_gross_computed_from_immutable_snapshot(self):
        """Gross uses FO item snapshot, not current offer prices."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        # Get FO items gross
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT SUM(COALESCE(line_cost_minor, line_selling_minor)) AS g "
                "FROM fulfillment_order_items WHERE fulfillment_order_id=?",
                (fo_id,),
            ).fetchone()
            expected_gross = int(row["g"] or 0)

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            entry = supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )
        self.assertEqual(entry["gross_minor"], expected_gross)

    def test_get_unbatched_payables(self):
        """Unbatched payables query returns correct entries."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )

        with self.db.read_transaction() as conn:
            entries = supplier_ledger_service.get_unbatched_payables(conn, supplier_id)

        self.assertTrue(any(e["fulfillment_order_id"] == fo_id for e in entries))

    def test_payable_summary(self):
        """Summary correctly aggregates unbatched entries."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            entry = supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )

        with self.db.read_transaction() as conn:
            summary = supplier_ledger_service.get_supplier_payable_summary(conn, supplier_id)

        self.assertGreaterEqual(summary["unbatched_minor"], entry["gross_minor"])
        self.assertGreaterEqual(summary["total_gross_minor"], entry["gross_minor"])

    def test_payable_api_admin_can_list(self):
        """Admin can list payables for a supplier."""
        fo = self._setup_delivered_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            supplier_ledger_service.record_sale_payable(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )

        admin_h = self.admin_headers()
        resp = self.client.get(
            f"/api/v1/admin/suppliers/{supplier_id}/payables", headers=admin_h
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("payables", data)

    def test_payable_api_supplier_sees_own(self):
        """Supplier can list their own payables."""
        import uuid
        supplier_email = "supplier.tehran@60online.ir"
        supplier_token = self.login(supplier_email, "Sup!Tehran1")
        supplier_h = {"Authorization": f"Bearer {supplier_token}"}

        resp = self.client.get("/api/v1/supplier/payables", headers=supplier_h)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("payables", data)

    def test_payable_api_customer_gets_403(self):
        """Customer cannot access supplier payable endpoints."""
        _, headers = self.new_customer()
        resp = self.client.get("/api/v1/supplier/payables", headers=headers)
        # Seller access is membership-based (marketplace shop owners keep role customer):
        # a customer with no shop is refused with supplier_not_linked and sees no data.
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["error"]["code"], "supplier_not_linked")


class DeliveryPayableAtomicTest(AppTestCase):
    """BLOCKER 3 — delivery+payable must be atomic (same transaction)."""

    def _checkout_fo(self):
        """Create a checkout and return the resulting FO dict."""
        _, headers = self.new_customer()
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 5)
        self.add_to_cart(headers, product["id"], 1)
        resp = self.checkout(headers)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        with self.db.read_transaction() as conn:
            fo = conn.execute(
                "SELECT fo.* FROM fulfillment_orders fo "
                "JOIN orders o ON o.id = fo.order_id "
                "ORDER BY fo.id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(fo)
            return dict(fo)

    def test_delivery_rolls_back_when_payable_fails(self):
        """If record_sale_payable raises, the FO must NOT be committed as delivered.

        BLOCKER 3 requirement: delivery transition and payable creation are in the
        same DB write transaction.  An exception in payable creation propagates and
        rolls back both mutations.
        """
        fo = self._checkout_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        # Advance FO to 'ready' (required by supplier_mark_delivered) via direct DB
        # This is the only direct DB manipulation allowed — it sets up the precondition.
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE fulfillment_orders SET status='ready' WHERE id=?", (fo_id,)
            )

        # Patch record_sale_payable to always raise inside the write transaction
        from app.services import fulfillment_service
        import unittest.mock as mock

        class _ForcedPayableError(Exception):
            pass

        with mock.patch(
            "app.services.supplier_ledger_service.record_sale_payable",
            side_effect=_ForcedPayableError("injected payable failure"),
        ):
            with self.assertRaises(_ForcedPayableError):
                with self.db.write_transaction() as conn:
                    fulfillment_service.supplier_mark_delivered(
                        conn,
                        fulfillment_order_id=fo_id,
                        supplier_id=supplier_id,
                    )

        # The FO must still be 'ready' — delivered transition was rolled back
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT status FROM fulfillment_orders WHERE id=?", (fo_id,)
            ).fetchone()
        self.assertEqual(
            row["status"], "ready",
            "BLOCKER 3: FO must NOT be committed as delivered when payable fails"
        )

        # No payable entry must exist
        with self.db.read_transaction() as conn:
            entry_row = conn.execute(
                "SELECT id FROM supplier_payable_entries "
                "WHERE idempotency_key=?",
                (f"fulfillment:{fo_id}:sale-payable",),
            ).fetchone()
        self.assertIsNone(
            entry_row,
            "BLOCKER 3: No payable entry must be persisted when delivery is rolled back"
        )

    def test_delivery_payable_committed_together_on_success(self):
        """Both delivered status and payable are committed in the same transaction."""
        fo = self._checkout_fo()
        fo_id = fo["id"]
        supplier_id = fo["supplier_id"]

        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE fulfillment_orders SET status='ready' WHERE id=?", (fo_id,)
            )

        from app.services import fulfillment_service
        with self.db.write_transaction() as conn:
            fulfillment_service.supplier_mark_delivered(
                conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
            )

        with self.db.read_transaction() as conn:
            fo_row = conn.execute(
                "SELECT status FROM fulfillment_orders WHERE id=?", (fo_id,)
            ).fetchone()
            payable = conn.execute(
                "SELECT id FROM supplier_payable_entries "
                "WHERE idempotency_key=?",
                (f"fulfillment:{fo_id}:sale-payable",),
            ).fetchone()

        self.assertEqual(fo_row["status"], "delivered", "FO must be delivered on success")
        self.assertIsNotNone(payable, "Payable must be created on success")


if __name__ == "__main__":
    unittest.main()
