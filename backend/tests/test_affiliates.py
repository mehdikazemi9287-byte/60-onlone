"""همکاری در فروش: referral attribution, platform/seller split, caps, holds and reversal."""
from __future__ import annotations

import datetime as dt

from app.services import affiliate_service as aff
from app.services import supplier_ledger_service
from tests.base import AppTestCase

UTC = dt.timezone.utc


class AffiliateTest(AppTestCase):
    def _uid(self, headers):
        return self.client.get("/api/v1/auth/me", headers=headers).get_json()["user"]["id"]

    def _referred_delivery(self, *, bonus_bps=0, self_ref=False, later_bonus_bps=None, qty=1):
        aff_token, aff_headers = self.new_customer()
        code = self.client.post("/api/v1/me/affiliate", json={"code": "Karen2026", "accept_terms": True}, headers=aff_headers).get_json()["affiliate"]["code"]
        buyer_headers = aff_headers if self_ref else self.new_customer()[1]
        self.client.post("/api/v1/me/referral", json={"code": code}, headers=buyer_headers)
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 10)
        with self.db.write_transaction() as conn:  # bonus in force when the order is placed
            conn.execute("UPDATE suppliers SET affiliate_bonus_bps=?", (bonus_bps,))
        self.add_to_cart(buyer_headers, product["id"], qty)
        self.assertEqual(self.checkout(buyer_headers).status_code, 201)
        with self.db.write_transaction() as conn:
            fo = conn.execute("SELECT * FROM fulfillment_orders ORDER BY id DESC LIMIT 1").fetchone()
            if later_bonus_bps is not None:  # seller changes the bonus after the sale
                conn.execute("UPDATE suppliers SET affiliate_bonus_bps=? WHERE id=?", (later_bonus_bps, fo["supplier_id"]))
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo["id"],))
            entry = supplier_ledger_service.record_sale_payable(conn, fulfillment_order_id=fo["id"], supplier_id=fo["supplier_id"])
        return aff_headers, entry, fo

    def test_platform_base_rate_and_dashboard(self):
        h, entry, fo = self._referred_delivery()
        with self.db.read_transaction() as conn:
            e = conn.execute("SELECT * FROM affiliate_earnings").fetchone()
        self.assertEqual(e["seller_paid_minor"], 0)
        self.assertGreater(e["platform_paid_minor"], 0)
        self.assertLessEqual(e["platform_paid_minor"], entry["commission_minor"])  # never more than platform earns
        d = self.client.get("/api/v1/me/affiliate", headers=h).get_json()
        self.assertEqual(d["code"], "Karen2026")
        # Waits for the buyer's withdrawal window even when the seller has no escrow date.
        self.assertEqual(d["items"][0]["state"], "pending")
        later = dt.datetime.now(UTC) + dt.timedelta(days=8)
        with self.db.read_transaction() as conn:
            self.assertEqual(aff.dashboard(conn, user_id=self._uid(h), now=later)["items"][0]["state"], "available")
        self.assertNotIn("buyer", str(d["items"][0]))

    def test_seller_bonus_comes_out_of_seller_share(self):
        _, entry, fo = self._referred_delivery(bonus_bps=500)
        with self.db.read_transaction() as conn:
            e = conn.execute("SELECT * FROM affiliate_earnings").fetchone()
            stored = conn.execute("SELECT commission_minor FROM supplier_payable_entries WHERE id=?", (entry["id"],)).fetchone()[0]
        self.assertEqual(e["seller_paid_minor"], e["gross_minor"] * 500 // 10_000)
        self.assertEqual(stored, entry["commission_minor"])  # returned entry reflects the raised commission
        from app.services import seller_shop_service
        with self.db.read_transaction() as conn:
            base = seller_shop_service.commission_for_fulfillment(conn, fo["id"])["commission_minor"]
        self.assertEqual(entry["commission_minor"], base + e["seller_paid_minor"])

    def test_self_referral_earns_nothing(self):
        self._referred_delivery(self_ref=True)
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM affiliate_earnings").fetchone()[0], 0)

    def test_open_return_holds_and_code_rules(self):
        h, entry, fo = self._referred_delivery()
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO order_return_requests (order_id, user_id, items_json, reason, status) "
                         "SELECT o.id, o.user_id, json_array(json_object('product_id', i.product_id, 'quantity', 1)), 'خراب بود', 'requested' "
                         "FROM orders o JOIN fulfillment_order_items i ON i.fulfillment_order_id=? WHERE o.id=?", (fo["id"], fo["order_id"]))
        self.assertEqual(self.client.get("/api/v1/me/affiliate", headers=h).get_json()["items"][0]["state"], "on_hold")
        _, other = self.new_customer()
        self.assertEqual(self.client.post("/api/v1/me/affiliate", json={"code": "zz2026"}, headers=other).get_json()["error"]["code"], "terms_required")
        self.assertEqual(self.client.post("/api/v1/me/affiliate", json={"code": "karen2026", "accept_terms": True}, headers=other).status_code, 409)
        self.assertEqual(self.client.post("/api/v1/me/affiliate", json={"code": "bad code!", "accept_terms": True}, headers=other).status_code, 422)

    def _return(self, fo, status, qty=1, product_id=None):
        import json
        with self.db.write_transaction() as conn:
            pid = product_id or conn.execute("SELECT product_id FROM fulfillment_order_items WHERE fulfillment_order_id=?",
                                             (fo["id"],)).fetchone()[0]
            conn.execute("INSERT INTO order_return_requests (order_id, user_id, items_json, reason, status) "
                         "SELECT id, user_id, ?, 'خراب بود', ? FROM orders WHERE id=?",
                         (json.dumps([{"product_id": pid, "quantity": qty}]), status, fo["order_id"]))

    def test_bonus_is_snapshotted_at_order_time(self):
        _, entry, fo = self._referred_delivery(bonus_bps=500, later_bonus_bps=2000)
        with self.db.read_transaction() as conn:
            e = conn.execute("SELECT * FROM affiliate_earnings").fetchone()
            snap = conn.execute("SELECT affiliate_bonus_bps FROM fulfillment_orders WHERE id=?", (fo["id"],)).fetchone()[0]
        self.assertEqual(snap, 500)
        self.assertEqual(e["seller_paid_minor"], e["gross_minor"] * 500 // 10_000)

    def test_partial_refund_reverses_in_proportion_and_persists(self):
        h, entry, fo = self._referred_delivery(qty=2)
        self._return(fo, "refunded", qty=1)
        item = self.client.get("/api/v1/me/affiliate", headers=h).get_json()["items"][0]
        with self.db.read_transaction() as conn:
            e = conn.execute("SELECT * FROM affiliate_earnings").fetchone()
        total = e["platform_paid_minor"] + e["seller_paid_minor"]
        self.assertEqual(e["reversed_minor"], total // 2)
        self.assertEqual(e["status"], "pending")
        self.assertEqual(item["amount_minor"], total - total // 2)
        self.assertTrue(item["reference"].startswith("AF-"))
        self.assertNotIn("order_id", item)

    def test_full_refund_marks_reversed(self):
        h, entry, fo = self._referred_delivery()
        self._return(fo, "refunded", qty=1)
        item = self.client.get("/api/v1/me/affiliate", headers=h).get_json()["items"][0]
        self.assertEqual((item["state"], item["amount_minor"]), ("reversed", 0))
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT status FROM affiliate_earnings").fetchone()[0], "reversed")

    def test_return_of_other_products_does_not_touch_earning(self):
        h, entry, fo = self._referred_delivery()
        other = self.product("office-paper-a4-carton")["id"] + 99999
        self._return(fo, "requested", product_id=other)
        self._return(fo, "refunded", product_id=other)
        item = self.client.get("/api/v1/me/affiliate", headers=h).get_json()["items"][0]
        self.assertEqual(item["state"], "pending")
        self.assertGreater(item["amount_minor"], 0)
