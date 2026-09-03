"""Tests for settlement batches (BLOCKERS 7, 8, 9)."""
from __future__ import annotations

import unittest

from tests.base import AppTestCase
from app.services import supplier_ledger_service, settlement_service
from app.core.errors import ConflictError, NotFoundError, ValidationError


def _make_delivered_payable(tc: AppTestCase):
    """Helper: checkout → deliver FO → record payable. Returns (supplier_id, entry)."""
    _, headers = tc.new_customer()
    product = tc.product("office-paper-a4-carton")
    tc.set_stock(product["id"], 10)
    tc.add_to_cart(headers, product["id"], 1)
    resp = tc.checkout(headers)
    assert resp.status_code == 201

    with tc.db.read_transaction() as conn:
        fo = conn.execute(
            "SELECT fo.* FROM fulfillment_orders fo "
            "JOIN orders o ON o.id = fo.order_id ORDER BY fo.id DESC LIMIT 1"
        ).fetchone()
    fo_id = fo["id"]
    supplier_id = fo["supplier_id"]

    with tc.db.write_transaction() as conn:
        conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
        entry = supplier_ledger_service.record_sale_payable(
            conn, fulfillment_order_id=fo_id, supplier_id=supplier_id
        )
    return supplier_id, entry


class SettlementBatchTest(AppTestCase):
    """Tests for BLOCKERS 7, 8, 9."""

    # ------------------------------------------------------------------
    # BLOCKER 7 — idempotent batch creation
    # ------------------------------------------------------------------

    def test_create_batch_basic(self):
        """Can create a settlement batch for an unbatched payable."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="idem-test-001",
            )
        self.assertEqual(batch["status"], "pending")
        self.assertEqual(batch["gross_minor"], entry["gross_minor"])
        self.assertIn("commission_minor", batch)
        self.assertIn("net_minor", batch)

    def test_create_batch_idempotent(self):
        """Same idempotency_key returns the same batch (BLOCKER 7)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            b1 = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="idem-test-idempotent",
            )
        with self.db.write_transaction() as conn:
            b2 = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="idem-test-idempotent",
            )
        self.assertEqual(b1["id"], b2["id"])

    def test_create_batch_double_batching_rejected(self):
        """Entry already in a batch raises ConflictError (BLOCKER 7 — never swallowed)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="first-batch",
            )
        with self.db.write_transaction() as conn:
            with self.assertRaises(ConflictError) as ctx:
                settlement_service.create_settlement_batch(
                    conn,
                    supplier_id=supplier_id,
                    payable_entry_ids=[entry["id"]],
                    idempotency_key="second-batch",
                )
        self.assertEqual(ctx.exception.code, "entry_already_batched")

    def test_create_batch_idempotency_key_required(self):
        """Empty idempotency_key raises ValidationError."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError):
                settlement_service.create_settlement_batch(
                    conn,
                    supplier_id=supplier_id,
                    payable_entry_ids=[entry["id"]],
                    idempotency_key="",
                )

    def test_create_batch_empty_entries_rejected(self):
        """Empty payable_entry_ids raises ValidationError."""
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError):
                settlement_service.create_settlement_batch(
                    conn,
                    supplier_id=1,
                    payable_entry_ids=[],
                    idempotency_key="nonempty",
                )

    def test_create_batch_integer_commission(self):
        """Commission is computed as integer floor division — no floats (BLOCKER 5)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="int-math-test",
                commission_rate_bps=1000,
            )
        gross = batch["gross_minor"]
        expected_commission = (gross * 1000) // 10_000
        self.assertEqual(batch["commission_minor"], expected_commission)
        self.assertEqual(batch["net_minor"], gross - expected_commission)
        # Verify all are ints
        self.assertIsInstance(batch["commission_minor"], int)
        self.assertIsInstance(batch["net_minor"], int)

    def test_commission_rate_bps_must_be_int(self):
        """Float commission_rate_bps raises ValidationError (BLOCKER 5)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError):
                settlement_service.create_settlement_batch(
                    conn,
                    supplier_id=supplier_id,
                    payable_entry_ids=[entry["id"]],
                    idempotency_key="float-test",
                    commission_rate_bps=10.5,  # float — should be rejected
                )

    # ------------------------------------------------------------------
    # BLOCKER 9 — shipping payer
    # ------------------------------------------------------------------

    def test_shipping_payer_customer_no_deduction(self):
        """When shipping_payer='customer', supplier net is not reduced (BLOCKER 9)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="ship-cust",
                commission_rate_bps=0,
                shipping_charge_minor=50_000,
                shipping_payer="customer",
            )
        # net_minor == gross_minor (no commission, no shipping deduction)
        self.assertEqual(batch["net_minor"], batch["gross_minor"])

    def test_shipping_payer_supplier_deducted(self):
        """When shipping_payer='supplier', shipping is deducted from net (BLOCKER 9)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="ship-sup",
                commission_rate_bps=0,
                shipping_charge_minor=50_000,
                shipping_payer="supplier",
            )
        self.assertEqual(
            batch["net_minor"],
            batch["gross_minor"] - 50_000
        )

    def test_shipping_payer_platform_no_deduction(self):
        """When shipping_payer='platform', supplier net is unaffected (BLOCKER 9)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="ship-plat",
                commission_rate_bps=0,
                shipping_charge_minor=50_000,
                shipping_payer="platform",
            )
        self.assertEqual(batch["net_minor"], batch["gross_minor"])

    def test_invalid_shipping_payer_rejected(self):
        """Invalid shipping_payer raises ValidationError."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError):
                settlement_service.create_settlement_batch(
                    conn,
                    supplier_id=supplier_id,
                    payable_entry_ids=[entry["id"]],
                    idempotency_key="bad-payer",
                    shipping_payer="banana",
                )

    # ------------------------------------------------------------------
    # BLOCKER 8 — append-only settlement payment
    # ------------------------------------------------------------------

    def test_complete_batch_creates_payment(self):
        """Completing a batch appends exactly one payment (BLOCKER 8)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="complete-test",
            )
        batch_id = batch["id"]
        with self.db.write_transaction() as conn:
            result = settlement_service.complete_settlement_batch(
                conn, batch_id=batch_id, payment_reference="TXN-001"
            )
        self.assertEqual(result["batch"]["status"], "completed")
        self.assertIsNotNone(result["payment"])
        self.assertEqual(result["payment"]["net_minor"], batch["net_minor"])

    def test_complete_batch_idempotent(self):
        """Completing a batch twice returns the same payment (idempotent)."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="complete-idem",
            )
        batch_id = batch["id"]
        with self.db.write_transaction() as conn:
            r1 = settlement_service.complete_settlement_batch(conn, batch_id=batch_id)
        with self.db.write_transaction() as conn:
            r2 = settlement_service.complete_settlement_batch(conn, batch_id=batch_id)
        self.assertEqual(r1["payment"]["id"], r2["payment"]["id"])

    def test_complete_batch_marks_entries_settled(self):
        """After completion, payable entries move to 'settled' status."""
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            batch = settlement_service.create_settlement_batch(
                conn,
                supplier_id=supplier_id,
                payable_entry_ids=[entry["id"]],
                idempotency_key="settled-test",
            )
        batch_id = batch["id"]
        with self.db.write_transaction() as conn:
            settlement_service.complete_settlement_batch(conn, batch_id=batch_id)

        with self.db.read_transaction() as conn:
            e = conn.execute(
                "SELECT status FROM supplier_payable_entries WHERE id=?", (entry["id"],)
            ).fetchone()
        self.assertEqual(e["status"], "settled")

    def test_complete_nonexistent_batch(self):
        """Completing a non-existent batch raises NotFoundError."""
        with self.db.write_transaction() as conn:
            with self.assertRaises(NotFoundError):
                settlement_service.complete_settlement_batch(conn, batch_id=99999)

    # ------------------------------------------------------------------
    # API surface
    # ------------------------------------------------------------------

    def test_admin_api_create_batch(self):
        """Admin can create settlement batch via API."""
        supplier_id, entry = _make_delivered_payable(self)
        admin_h = self.admin_headers()
        import uuid
        resp = self.client.post(
            "/api/v1/admin/settlement-batches",
            json={
                "supplier_id": supplier_id,
                "payable_entry_ids": [entry["id"]],
                "idempotency_key": uuid.uuid4().hex,
                "commission_rate_bps": 1000,
            },
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        data = resp.get_json()
        self.assertIn("batch", data)

    def test_admin_api_complete_batch(self):
        """Admin can complete a settlement batch via API."""
        supplier_id, entry = _make_delivered_payable(self)
        admin_h = self.admin_headers()
        import uuid
        resp = self.client.post(
            "/api/v1/admin/settlement-batches",
            json={
                "supplier_id": supplier_id,
                "payable_entry_ids": [entry["id"]],
                "idempotency_key": uuid.uuid4().hex,
            },
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201)
        batch_id = resp.get_json()["batch"]["id"]

        resp2 = self.client.post(
            f"/api/v1/admin/settlement-batches/{batch_id}/complete",
            json={"payment_reference": "TXN-789"},
            headers=admin_h,
        )
        self.assertEqual(resp2.status_code, 200, resp2.get_json())
        result = resp2.get_json()
        self.assertEqual(result["batch"]["status"], "completed")
        self.assertIsNotNone(result["payment"])

    def test_admin_api_list_batches(self):
        """Admin can list settlement batches."""
        admin_h = self.admin_headers()
        resp = self.client.get("/api/v1/admin/settlement-batches", headers=admin_h)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("batches", resp.get_json())

    def test_customer_cannot_access_settlement(self):
        """Customers cannot access settlement admin endpoints."""
        _, customer_h = self.new_customer()
        resp = self.client.get("/api/v1/admin/settlement-batches", headers=customer_h)
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
