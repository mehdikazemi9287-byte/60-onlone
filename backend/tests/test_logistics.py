"""Tests for logistics service: shipment planning, booking, and FO auth (BLOCKERS 1, 2, 3).

All tests use deterministic fixtures from base.py — no skipTest calls.
"""
from __future__ import annotations

import unittest

from tests.base import AppTestCase
from app.core.errors import ConflictError, NotFoundError, PermissionError_
from app.services import logistics_service


def _create_fo_with_plan(tc: AppTestCase) -> tuple[int, dict, dict]:
    """Create deterministic supplier + product, check out, return (fo_id, customer_h, supplier_info).

    The supplier is created in 'تهران' so a carrier config is guaranteed to exist
    (migration 0006 seeds one for تهران).  The test product is unique so the FO
    is always routed to our test supplier — no seed-data dependency.
    """
    supplier_info = tc.create_test_supplier(province="تهران", city="تهران")
    product_info = tc.create_test_product_with_offer(
        supplier_info["supplier_id"], supplier_info["location_id"],
        logistics_profile="standard",
    )
    _, customer_h = tc.new_customer()
    tc.add_to_cart(customer_h, product_info["product_id"], 1)
    resp = tc.checkout(customer_h)
    tc.assertEqual(resp.status_code, 201, resp.get_json())

    with tc.db.read_transaction() as conn:
        fo = conn.execute(
            "SELECT fo.* FROM fulfillment_orders fo "
            "JOIN orders o ON o.id = fo.order_id ORDER BY fo.id DESC LIMIT 1"
        ).fetchone()
    return fo["id"], customer_h, supplier_info


class ShipmentPlanningTest(AppTestCase):
    """Tests for BLOCKER 1 (post-checkout logistics trigger) and shipment planning."""

    def test_checkout_triggers_shipment_plan(self):
        """After checkout with a deterministic supplier+carrier, a non-failed plan must exist."""
        fo_id, _, _ = _create_fo_with_plan(self)

        with self.db.read_transaction() as conn:
            plan = conn.execute(
                "SELECT * FROM shipment_plans WHERE fulfillment_order_id=?", (fo_id,)
            ).fetchone()
        self.assertIsNotNone(plan, "shipment_plan row should exist after checkout")
        self.assertNotEqual(
            plan["status"], "failed",
            f"plan should not be failed — got status={plan['status']}, "
            f"reason={plan['failure_reason']}",
        )

    def test_ensure_shipment_plan_idempotent(self):
        """Calling ensure_shipment_plan twice does not create duplicate plans."""
        fo_id, _, _ = _create_fo_with_plan(self)

        logistics_service.ensure_shipment_plan(self.db, fo_id)
        logistics_service.ensure_shipment_plan(self.db, fo_id)

        with self.db.read_transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM shipment_plans WHERE fulfillment_order_id=?", (fo_id,)
            ).fetchone()["c"]
        self.assertLessEqual(count, 1)

    def test_ensure_shipment_plan_nonexistent_fo_safe(self):
        """ensure_shipment_plan on non-existent FO does not raise (silent failure)."""
        logistics_service.ensure_shipment_plan(self.db, 99999)

    def test_admin_can_trigger_plan(self):
        """Admin can call plan_shipment endpoint."""
        fo_id, _, _ = _create_fo_with_plan(self)
        admin_h = self.admin_headers()
        resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=admin_h
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())


class BookingTwoPhaseTest(AppTestCase):
    """Tests for BLOCKER 3: two-phase carrier booking."""

    def test_book_shipment_two_phase(self):
        """Booking proceeds through phase A → external → phase B; status='booked'."""
        fo_id, _, _ = _create_fo_with_plan(self)

        admin_h = self.admin_headers()
        resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=admin_h
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        data = resp.get_json()
        self.assertIn("shipment", data)
        shipment = data["shipment"]
        self.assertEqual(shipment["status"], "booked")
        self.assertIsNotNone(shipment["tracking_code"])

    def test_booking_idempotency_key_stable_on_retry(self):
        """Retrying book_shipment uses the SAME idempotency key (BLOCKER 3)."""
        fo_id, _, _ = _create_fo_with_plan(self)

        admin_h = self.admin_headers()
        # First booking
        resp1 = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=admin_h
        )
        self.assertEqual(resp1.status_code, 200)

        with self.db.read_transaction() as conn:
            s1 = conn.execute(
                "SELECT booking_idempotency_key FROM shipments WHERE fulfillment_order_id=?",
                (fo_id,)
            ).fetchone()
        idem_key_1 = s1["booking_idempotency_key"]

        # Second call — idempotent return
        resp2 = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=admin_h
        )
        self.assertEqual(resp2.status_code, 200)

        with self.db.read_transaction() as conn:
            s2 = conn.execute(
                "SELECT booking_idempotency_key FROM shipments WHERE fulfillment_order_id=?",
                (fo_id,)
            ).fetchone()
        # Same idempotency key — never regenerated
        self.assertEqual(idem_key_1, s2["booking_idempotency_key"])

    def test_booking_without_plan_fails(self):
        """Booking a FO with no plan raises ConflictError."""
        fo_id, _, _ = _create_fo_with_plan(self)

        with self.db.read_transaction() as conn:
            plan = conn.execute(
                "SELECT id FROM shipment_plans WHERE fulfillment_order_id=?", (fo_id,)
            ).fetchone()

        # Clear any auto-created plan so we can test the no-plan case
        if plan:
            with self.db.write_transaction() as conn:
                conn.execute(
                    "DELETE FROM shipment_plan_quotes WHERE shipment_plan_id=?", (plan["id"],)
                )
                conn.execute(
                    "DELETE FROM shipment_plans WHERE fulfillment_order_id=?", (fo_id,)
                )

        # book_shipment should raise ConflictError — no plan exists
        with self.assertRaises(ConflictError) as ctx:
            logistics_service.book_shipment(
                self.db, fo_id, user_id=1, user_role="admin"
            )
        self.assertEqual(ctx.exception.code, "no_shipment_plan")


class FulfillmentOrderAuthTest(AppTestCase):
    """Tests for BLOCKER 2: authorization on FO mutations."""

    def test_customer_cannot_plan_shipment(self):
        """Customers get 403 on plan-shipment endpoint (BLOCKER 2)."""
        fo_id, customer_h, _ = _create_fo_with_plan(self)
        resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=customer_h
        )
        self.assertEqual(resp.status_code, 403)

    def test_customer_cannot_book_shipment(self):
        """Customers get 403 on book-shipment endpoint (BLOCKER 2)."""
        fo_id, customer_h, _ = _create_fo_with_plan(self)
        resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=customer_h
        )
        self.assertEqual(resp.status_code, 403)

    def test_customer_can_read_tracking(self):
        """Customers can read tracking for their own FO."""
        fo_id, customer_h, _ = _create_fo_with_plan(self)
        resp = self.client.get(
            f"/api/v1/fulfillment-orders/{fo_id}/tracking", headers=customer_h
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("fulfillment_order_id", data)

    def test_customer_cannot_read_another_customers_tracking(self):
        """Customer cannot read another customer's FO tracking."""
        fo_id, _, _ = _create_fo_with_plan(self)
        _, other_h = self.new_customer()
        resp = self.client.get(
            f"/api/v1/fulfillment-orders/{fo_id}/tracking", headers=other_h
        )
        # Should be 404 (not revealing the FO exists)
        self.assertEqual(resp.status_code, 404)

    def test_admin_can_plan_shipment(self):
        """Admin can plan shipment for any FO (BLOCKER 2)."""
        fo_id, _, _ = _create_fo_with_plan(self)
        admin_h = self.admin_headers()
        resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=admin_h
        )
        self.assertEqual(resp.status_code, 200)

    def test_owning_supplier_can_plan_shipment(self):
        """The supplier that owns a FO can plan its shipment.

        Uses deterministic supplier from create_test_supplier() — no seed dependency,
        no skipTest.
        """
        fo_id, _, supplier_info = _create_fo_with_plan(self)

        # The supplier user logs in with the known test credentials
        supplier_h = supplier_info["headers"]
        resp = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=supplier_h
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())

    def test_other_supplier_cannot_plan_shipment(self):
        """A supplier that doesn't own the FO gets NotFoundError via _check_fo_access."""
        fo_id, _, sup1 = _create_fo_with_plan(self)

        # Create a second test supplier (does not own the FO)
        sup2 = self.create_test_supplier(province="تهران", city="تهران")

        with self.db.read_transaction() as conn:
            with self.assertRaises(NotFoundError):
                logistics_service._check_fo_access(
                    conn, fo_id,
                    user_id=sup2["user_id"],
                    user_role="supplier",
                    supplier_id=sup2["supplier_id"],
                )

    def test_check_fo_access_admin_allowed(self):
        """_check_fo_access allows admin for any FO."""
        fo_id, _, _ = _create_fo_with_plan(self)
        with self.db.read_transaction() as conn:
            fo = logistics_service._check_fo_access(
                conn, fo_id, user_id=1, user_role="admin"
            )
        self.assertIsNotNone(fo)

    def test_check_fo_access_customer_raises_permission_error(self):
        """_check_fo_access raises PermissionError_ for customer role."""
        fo_id, _, _ = _create_fo_with_plan(self)
        with self.db.read_transaction() as conn:
            with self.assertRaises(PermissionError_):
                logistics_service._check_fo_access(
                    conn, fo_id, user_id=1, user_role="customer"
                )

    def test_unauthenticated_cannot_plan(self):
        """Unauthenticated request to plan-shipment gets 401."""
        fo_id, _, _ = _create_fo_with_plan(self)
        resp = self.client.post(f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan")
        self.assertEqual(resp.status_code, 401)

    def test_unauthenticated_cannot_track(self):
        """Unauthenticated request to tracking gets 401."""
        fo_id, _, _ = _create_fo_with_plan(self)
        resp = self.client.get(f"/api/v1/fulfillment-orders/{fo_id}/tracking")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
