"""خرید دوره‌ای در پرداخت: confirm a quoted run → cart = list → subscription discount at checkout."""
from __future__ import annotations

import datetime as dt

from app.services import recurring_service as rs
from tests.base import AppTestCase


class RecurringCheckoutTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["COMMERCE_TEST_MODE"] = True
        self.addCleanup(self.app.config.__setitem__, "COMMERCE_TEST_MODE", None)
        _, self.h = self.new_customer()
        self.p = self.product("office-paper-a4-carton")
        self.set_stock(self.p["id"], 50)
        today = dt.datetime.now(dt.timezone.utc).date()
        r = self.client.post("/api/v1/me/recurring", headers=self.h, json={
            "title": "کاغذ ماهانهٔ دفتر", "frequency": "monthly", "start_on": today.isoformat(),
            "items": [{"product_id": self.p["id"], "quantity": 2}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.list_id = r.get_json()["list"]["id"]
        with self.db.write_transaction() as conn:
            done = rs.run_due(conn, today=today)
        self.run_id = next(x["run_id"] for x in done["runs"] if x["list_id"] == self.list_id)
        with self.db.write_transaction() as conn:  # the seeded legacy product has no marketplace offer for the cashier
            conn.execute("UPDATE recurring_runs SET status='quoted', error=NULL WHERE id=?", (self.run_id,))

    def to_cart(self):
        return self.client.post(f"/api/v1/me/recurring/{self.list_id}/runs/{self.run_id}/to-cart", headers=self.h)

    def test_confirm_and_pay_with_discount(self):
        self.add_to_cart(self.h, self.p["id"], 7)  # anything already in the cart is replaced
        r = self.to_cart()
        self.assertEqual(r.status_code, 200, r.get_json())
        q = self.quote(self.h)
        gross = q["cart"]["gross_subtotal_minor"]
        self.assertEqual(q["recurring_discount_minor"], gross * 500 // 10_000)
        self.assertEqual(q["cart"]["subtotal_minor"], gross - q["recurring_discount_minor"])
        c = self.checkout(self.h)
        self.assertEqual(c.status_code, 201, c.get_json())
        order = c.get_json()["order"]
        self.assertEqual(order["recurring_discount_minor"], gross * 500 // 10_000)
        with self.db.read_transaction() as conn:
            run = conn.execute("SELECT status, order_id FROM recurring_runs WHERE id=?", (self.run_id,)).fetchone()
        self.assertEqual((run["status"], run["order_id"]), ("confirmed", order["id"]))
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)
        self.assertEqual(self.to_cart().status_code, 409)  # a confirmed run can't be used twice

    def test_changed_cart_loses_discount(self):
        self.to_cart()
        self.client.patch(f"/api/v1/cart/items/{self.p['id']}", json={"quantity": 3}, headers=self.h)
        self.add_to_cart(self.h, self.p["id"], 1)
        self.assertEqual(self.quote(self.h)["recurring_discount_minor"], 0)

    def test_stale_or_foreign_run(self):
        _, other = self.new_customer()
        self.assertEqual(self.client.post(f"/api/v1/me/recurring/{self.list_id}/runs/{self.run_id}/to-cart",
                                          headers=other).status_code, 409)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE recurring_runs SET scheduled_for='2000-01-01' WHERE id=?", (self.run_id,))
        self.assertEqual(self.to_cart().status_code, 409)
