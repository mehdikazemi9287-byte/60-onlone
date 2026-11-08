"""In-person: store locator, collect-in-store code, visit appointments."""
from __future__ import annotations

import datetime as dt

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import in_person_service as svc
from tests.base import AppTestCase

UTC = dt.timezone.utc


class InPersonTest(AppTestCase):
    def _order(self):
        _, headers = self.new_customer()
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 10)
        self.add_to_cart(headers, product["id"], 1)
        self.assertEqual(self.checkout(headers).status_code, 201)
        with self.db.write_transaction() as conn:
            fo = dict(conn.execute("SELECT fo.*, o.user_id FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
                                   "ORDER BY fo.id DESC LIMIT 1").fetchone())
            conn.execute("UPDATE supplier_locations SET can_pickup=1, accepts_appointments=1, accepts_walk_in=1 "
                         "WHERE id=?", (fo["supplier_location_id"],))
            conn.execute("UPDATE fulfillment_orders SET status='accepted' WHERE id=?", (fo["id"],))
        return headers, fo

    def test_pickup_code_flow(self):
        headers, fo = self._order()
        r = self.client.post(f"/api/v1/me/fulfillments/{fo['id']}/pickup", json={"location_id": fo["supplier_location_id"]},
                             headers=headers)
        self.assertEqual(r.status_code, 201, r.get_json())
        code = r.get_json()["pickup_code"]
        self.assertRegex(code, r"^\d{6}$")
        with self.db.write_transaction() as conn:
            self.assertNotEqual(conn.execute("SELECT code_sha256 FROM pickup_handoffs").fetchone()[0], code)  # hashed
            sup = fo["supplier_id"]
            with self.assertRaises(ValidationError):
                svc.confirm_pickup(conn, supplier_id=sup, actor_user_id=1, fulfillment_order_id=fo["id"], code="000000"
                                   if code != "000000" else "111111")
            with self.assertRaises(ConflictError) as e:  # right code, but goods not ready yet
                svc.confirm_pickup(conn, supplier_id=sup, actor_user_id=1, fulfillment_order_id=fo["id"], code=code)
            self.assertEqual(e.exception.code, "pickup_not_ready")
            with self.assertRaises(NotFoundError):  # another seller cannot confirm
                svc.confirm_pickup(conn, supplier_id=sup + 999, actor_user_id=1, fulfillment_order_id=fo["id"], code=code)
            conn.execute("UPDATE fulfillment_orders SET status='ready' WHERE id=?", (fo["id"],))
            out = svc.confirm_pickup(conn, supplier_id=sup, actor_user_id=1, fulfillment_order_id=fo["id"], code=code)
            self.assertEqual(out["status"], "collected")
            self.assertEqual(conn.execute("SELECT status FROM fulfillment_orders WHERE id=?", (fo["id"],)).fetchone()[0],
                             "delivered")

    def test_code_attempts_locked(self):
        headers, fo = self._order()
        with self.db.write_transaction() as conn:
            code = svc.choose_pickup(conn, user_id=fo["user_id"], fulfillment_order_id=fo["id"],
                                     location_id=fo["supplier_location_id"])["pickup_code"]
            conn.execute("UPDATE pickup_handoffs SET attempts=5")
            with self.assertRaises(ConflictError) as e:
                svc.confirm_pickup(conn, supplier_id=fo["supplier_id"], actor_user_id=1, fulfillment_order_id=fo["id"], code=code)
            self.assertEqual(e.exception.code, "pickup_locked")

    def test_other_user_cannot_choose_pickup(self):
        _, fo = self._order()
        _, other = self.new_customer()
        r = self.client.post(f"/api/v1/me/fulfillments/{fo['id']}/pickup", json={"location_id": fo["supplier_location_id"]},
                             headers=other)
        self.assertEqual(r.status_code, 404)

    def test_store_locator_and_visits(self):
        headers, fo = self._order()
        stores = self.client.get("/api/v1/stores").get_json()["items"]
        self.assertIn(fo["supplier_location_id"], [s["id"] for s in stores])
        when = (dt.datetime.now(UTC) + dt.timedelta(days=2)).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {"location_id": fo["supplier_location_id"], "starts_at": when, "purpose": "samples"}
        r = self.client.post("/api/v1/me/visits", json=body, headers=headers)
        self.assertEqual(r.status_code, 201, r.get_json())
        _, other = self.new_customer()
        clash = self.client.post("/api/v1/me/visits", json=body, headers=other)
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.get_json()["error"]["code"], "slot_taken")
        past = {**body, "starts_at": "2020-01-01T10:00:00Z"}
        self.assertEqual(self.client.post("/api/v1/me/visits", json=past, headers=other).status_code, 422)
        vid = r.get_json()["visit"]["id"]
        with self.db.write_transaction() as conn:
            v = svc.seller_decide_visit(conn, supplier_id=fo["supplier_id"], visit_id=vid, decision="confirm")
            self.assertEqual(v["status"], "confirmed")
            listed = svc.seller_visits(conn, supplier_id=fo["supplier_id"])
            self.assertNotIn("phone", listed[0])
        self.assertEqual(self.client.post(f"/api/v1/me/visits/{vid}/cancel", headers=headers).get_json()["visit"]["status"],
                         "cancelled")

    def test_pickup_options_owner_only(self):
        headers, fo = self._order()
        ok = self.client.get(f"/api/v1/me/fulfillments/{fo['id']}/pickup", headers=headers).get_json()
        self.assertTrue(ok["eligible"])
        self.assertEqual(len(ok["locations"]), 1)
        _, other = self.new_customer()
        self.assertEqual(self.client.get(f"/api/v1/me/fulfillments/{fo['id']}/pickup", headers=other).status_code, 404)
