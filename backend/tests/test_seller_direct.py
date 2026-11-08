"""Bring your own customer: invite, claim, 0% commission only on that seller's sales to that buyer."""
from __future__ import annotations

import uuid

from app.services import seller_shop_service as shops
from tests.base import AppTestCase


class SellerDirectTest(AppTestCase):
    def _order(self, user_id: int, supplier: dict, amount: int = 1_000_000) -> int:
        offer = self.create_test_product_with_offer(supplier["supplier_id"], supplier["location_id"])
        with self.db.write_transaction() as conn:
            oid = conn.execute(
                "INSERT INTO orders (order_number, user_id, status, subtotal_minor, shipping_fee_minor, tax_minor, "
                "total_minor, recipient_name, recipient_phone, shipping_province, shipping_city, shipping_line1) "
                "VALUES (?,?, 'paid', ?, 0, 0, ?, 'x', '0912', 'تهران', 'تهران', 'x')",
                (f"O-{uuid.uuid4().hex[:8]}", user_id, amount, amount)).lastrowid
            fo = conn.execute("INSERT INTO fulfillment_orders (order_id, supplier_id, supplier_location_id) VALUES (?,?,?)",
                              (oid, supplier["supplier_id"], supplier["location_id"])).lastrowid
            pid = offer["product_id"]
            oi = conn.execute("INSERT INTO order_items (order_id, product_id, title_fa, sku, unit_price_minor, quantity, "
                              "line_total_minor) VALUES (?,?, 'x', 'x', ?, 1, ?)", (oid, pid, amount, amount)).lastrowid
            conn.execute("INSERT INTO fulfillment_order_items (fulfillment_order_id, order_item_id, seller_offer_id, product_id, "
                         "title_fa, quantity, selling_price_minor, line_selling_minor) VALUES (?,?,?,?, 'x', 1, ?, ?)",
                         (fo, oi, offer["offer_id"], pid, amount, amount))
            return int(fo)

    def _uid(self, headers: dict) -> int:
        return self.client.get("/api/v1/auth/me", headers=headers).get_json()["user"]["id"]

    def test_invite_claim_and_zero_commission(self):
        sup, other = self.create_test_supplier(), self.create_test_supplier()
        _, buyer = self.new_customer()
        r = self.client.post("/api/v1/supplier/direct-invites", json={"note": "مشتری قدیمی"}, headers=sup["headers"])
        self.assertEqual(r.status_code, 201, r.get_json())
        code = r.get_json()["code"]
        self.assertEqual(self.client.get(f"/api/v1/direct-invites/{code}").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/me/direct-invites/{code}/claim", headers=sup["headers"]).get_json()
                         ["error"]["code"], "self_invite")
        self.assertEqual(self.client.post(f"/api/v1/me/direct-invites/{code}/claim", headers=buyer).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/me/direct-invites/{code}/claim", headers=buyer).status_code, 404)
        uid = self._uid(buyer)
        with self.db.read_transaction() as conn:
            mine = shops.commission_for_fulfillment(conn, self._order(uid, sup))
            theirs = shops.commission_for_fulfillment(conn, self._order(uid, other))
        self.assertEqual((mine["channel"], mine["commission_minor"]), ("direct", 0))
        self.assertGreater(theirs["commission_minor"], 0)   # other sellers' sales to this buyer still pay
        self.assertEqual(self.client.get("/api/v1/supplier/direct-customers", headers=sup["headers"]).get_json()
                         ["items"][0]["orders"], 1)

    def test_existing_platform_customer_cannot_be_claimed(self):
        sup = self.create_test_supplier()
        _, buyer = self.new_customer()
        self._order(self._uid(buyer), sup)
        code = self.client.post("/api/v1/supplier/direct-invites", json={}, headers=sup["headers"]).get_json()["code"]
        r = self.client.post(f"/api/v1/me/direct-invites/{code}/claim", headers=buyer)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "existing_platform_customer"))
        _, nobody = self.new_customer()
        self.assertEqual(self.client.post("/api/v1/supplier/direct-invites", json={}, headers=nobody).status_code, 403)
