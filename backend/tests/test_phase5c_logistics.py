"""Phase 5C — rate shopping, multi-seller shipments, tracking, SLA, returns, API."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from app.adapters.logistics import registry
from app.api.v1.logistics_v2 import bp as logistics_v2_bp
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import fulfillment_service as fs
from app.services import product_standards_service as pss
from app.services import shipment_orchestrator as so
from app.services import shipping_rate_service as srs
from tests.base import AppTestCase

TEH = {"province": "تهران", "city": "تهران"}
ISF = {"province": "اصفهان", "city": "اصفهان"}
BOX = {"length_mm": 400, "width_mm": 300, "height_mm": 200, "gross_weight_g": 2000}  # volumetric 4800 g


class RateShoppingTest(AppTestCase):
    def test_volumetric_zone_and_remote_tariff(self):
        with self.db.write_transaction() as conn:
            tid = srs.create_tariff(conn, {
                "provider_code": "tipax", "service_level": "economy", "name_fa": "آزمایشی",
                "base_minor": 100_000, "per_kg_minor": 10_000, "weight_step_g": 500,
                "remote_surcharge_minor": 7_000, "cod_fee_bps": 100, "cod_min_fee_minor": 5_000,
                "insurance_bps": 50, "transit_days_min": 2, "transit_days_max": 4,
                "zones": [{"origin_province": "تهران", "destination_province": "اصفهان",
                           "base_minor": 120_000, "transit_days_min": 1, "transit_days_max": 2}]})["id"]
            t = conn.execute("SELECT * FROM carrier_tariffs WHERE id=?", (tid,)).fetchone()
            q = srs.price_tariff(conn, t, TEH, ISF, srs.resolve_parcels(conn, [BOX]))
            self.assertEqual(q["billable_weight_g"], 5000)            # 4800 rounded to 500 g step
            self.assertEqual(q["cost_minor"], 120_000 + 50_000)        # zone base + 5 kg
            self.assertEqual((q["eta_days_min"], q["eta_days_max"]), (1, 2))
            q2 = srs.price_tariff(conn, t, TEH, {"province": "فارس", "city": "شیراز"},
                                  srs.resolve_parcels(conn, [BOX]))
            self.assertEqual(q2["cost_minor"], 150_000)                # default base (no zone)
            conn.execute("INSERT INTO logistics_remote_areas (province, city) VALUES ('فارس', '*')")
            q3 = srs.price_tariff(conn, t, TEH, {"province": "فارس", "city": "شیراز"},
                                  srs.resolve_parcels(conn, [BOX]), cod_value_minor=1_000_000,
                                  insurance_value_minor=2_000_000)
            self.assertEqual(q3["breakdown"]["remote_minor"], 7_000)
            self.assertEqual(q3["breakdown"]["cod_fee_minor"], 10_000)
            self.assertEqual(q3["breakdown"]["insurance_minor"], 10_000)

    def test_cheapest_fastest_same_city_and_live_fallback(self):
        with self.db.write_transaction() as conn:
            inter = srs.quote_shipping(conn, TEH, ISF, [BOX])
            self.assertNotIn("alopeyk", {o["provider_code"] for o in inter["options"]})
            prices = [o["price_minor"] for o in inter["options"]]
            self.assertEqual(prices, sorted(prices))
            fast = srs.quote_shipping(conn, TEH, ISF, [BOX], strategy="fastest")
            self.assertEqual(fast["selected"]["eta_days_max"], min(o["eta_days_max"] for o in fast["options"]))
            local = srs.quote_shipping(conn, TEH, TEH, [BOX], service_levels=["same_day"])
            self.assertEqual(local["selected"]["provider_code"], "alopeyk")
            cold = srs.quote_shipping(conn, TEH, ISF, [{**BOX, "requires_cold_chain": True}])
            self.assertEqual({o["provider_code"] for o in cold["options"]}, {"chapar"})
            conn.execute("UPDATE logistics_carriers SET has_live_api=1 WHERE provider_code='tipax'")
            calls = []
            live = srs.quote_shipping(conn, TEH, ISF, [BOX], live_quoter=lambda p, r: calls.append(p) or [
                {"service_level": "express", "cost_minor": 1, "eta_days_min": 1, "eta_days_max": 1}])
            self.assertEqual((live["selected"]["source"], calls), ("live", ["tipax"]))

            def boom(p, r):
                raise TimeoutError
            fb = srs.quote_shipping(conn, TEH, ISF, [BOX], live_quoter=boom)
            self.assertTrue(all(o["source"] == "tariff" for o in fb["options"]))
            with self.assertRaises(ValidationError):
                srs.quote_shipping(conn, TEH, ISF, [])


class ShipmentFlowTest(AppTestCase):
    def setUp(self):
        super().setUp()
        if logistics_v2_bp.name not in self.app.blueprints:  # registered by app/main.py
            self.app.register_blueprint(logistics_v2_bp)

    def _fo(self, sup=None):
        sup = sup or self.create_test_supplier(province="تهران", city="تهران")
        prod = self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"])
        with self.db.write_transaction() as conn:
            pss.upsert_spec(conn, product_id=prod["product_id"], data={**BOX, "gtin": "4006381333931"})
        _, cust = self.new_customer()
        self.add_to_cart(cust, prod["product_id"], 1)
        r = self.checkout(cust, address={**self.DEFAULT_ADDRESS, "province": "اصفهان", "city": "اصفهان"})
        self.assertEqual(r.status_code, 201, r.get_json())
        with self.db.write_transaction() as conn:
            fo = conn.execute("SELECT * FROM fulfillment_orders WHERE supplier_id=? ORDER BY id DESC",
                              (sup["supplier_id"],)).fetchone()
            conn.execute("UPDATE fulfillment_orders SET promised_prep_at=NULL WHERE id=?", (fo["id"],))
            fs.supplier_accept(conn, fulfillment_order_id=fo["id"], supplier_id=sup["supplier_id"])
        return sup, int(fo["id"]), int(fo["order_id"]), cust, prod

    def test_label_tracking_delivery_and_idempotency(self):
        sup, fo_id, order_id, cust, _ = self._fo()
        other = self.create_test_supplier()
        r = self.client.post("/api/v1/supplier/shipments", json={"fulfillment_order_id": fo_id},
                             headers=other["headers"])
        self.assertEqual(r.status_code, 404)                           # not own FO
        r = self.client.post("/api/v1/supplier/shipments", headers=sup["headers"], json={
            "fulfillment_order_id": fo_id,
            "pickup": {"window_start": "2026-11-08T08:00:00Z", "window_end": "2026-11-08T12:00:00Z"}})
        self.assertEqual(r.status_code, 201, r.get_json())
        s = r.get_json()["shipment"]
        self.assertEqual(s["label"]["barcode"]["data"], s["tracking_number"])
        self.assertTrue(s["pickup_requested_at"])
        r2 = self.client.post("/api/v1/supplier/shipments", json={"fulfillment_order_id": fo_id},
                              headers=sup["headers"])
        self.assertEqual(r2.get_json()["shipment"]["id"], s["id"])   # idempotent
        with self.db.write_transaction() as conn:
            fo = conn.execute("SELECT promised_prep_at FROM fulfillment_orders WHERE id=?", (fo_id,)).fetchone()
            self.assertEqual(fo["promised_prep_at"], s["ship_by_at"])
            plan = conn.execute("SELECT selected_quote_id FROM shipment_plans WHERE fulfillment_order_id=?",
                                (fo_id,)).fetchone()
            self.assertEqual(plan["selected_quote_id"], s["quote_id"])
            fs.supplier_start_preparing(conn, fulfillment_order_id=fo_id, supplier_id=sup["supplier_id"])
            fs.supplier_mark_ready(conn, fulfillment_order_id=fo_id, supplier_id=sup["supplier_id"])
            carrier = s["provider_code"]
            inv: dict = {}
            for k, v in registry.get_tracking_status_map(carrier).items():
                inv[v] = k if k != v else inv.get(v, k)  # prefer real carrier codes
            handler = registry.get_tracking_event_handler()
            res = handler(conn, carrier, {"tracking_number": s["tracking_number"], "status": inv["picked_up"],
                                          "event_id": "e1"})
            self.assertTrue(res["applied"])
            self.assertEqual(conn.execute("SELECT status FROM fulfillment_orders WHERE id=?",
                                          (fo_id,)).fetchone()["status"], "dispatched")
            dup = handler(conn, carrier, {"tracking_number": s["tracking_number"], "status": inv["picked_up"],
                                          "event_id": "e1"})
            self.assertTrue(dup["duplicate"])
            handler(conn, carrier, {"tracking_number": s["tracking_number"], "status": inv["delivered"],
                                    "event_id": "e2"})
            handler(conn, carrier, {"tracking_number": s["tracking_number"], "status": inv["delivered"],
                                    "event_id": "e3"})                      # replay w/ new id: no-op
            stale = handler(conn, carrier, {"tracking_number": s["tracking_number"],
                                            "status": inv["in_transit"], "event_id": "e4"})
            self.assertFalse(stale["applied"])                         # no regression after delivered
            self.assertEqual(conn.execute("SELECT status FROM fulfillment_orders WHERE id=?",
                                          (fo_id,)).fetchone()["status"], "delivered")
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM supplier_payable_entries WHERE "
                                          "fulfillment_order_id=?", (fo_id,)).fetchone()["c"] > 0, True)
            with self.assertRaises(ValidationError):
                handler(conn, carrier, {"tracking_number": s["tracking_number"], "status": "ZZZ"})
        t = self.client.get(f"/api/v1/me/orders/{order_id}/tracking", headers=cust)
        self.assertEqual(t.get_json()["shipments"][0]["status"], "delivered")
        _, stranger = self.new_customer()
        self.assertEqual(self.client.get(f"/api/v1/me/orders/{order_id}/tracking",
                                         headers=stranger).status_code, 404)

    def test_return_shipment_and_sla_business_days(self):
        sup, fo_id, order_id, cust, prod = self._fo()
        with self.db.write_transaction() as conn:
            s = so.create_shipment_for_fo(conn, fo_id, supplier_id=sup["supplier_id"])
            with self.assertRaises(NotFoundError):
                so.create_shipment_for_fo(conn, fo_id, supplier_id=sup["supplier_id"] + 999)
            user_id = conn.execute("SELECT user_id FROM orders WHERE id=?", (order_id,)).fetchone()["user_id"]
            rid = conn.execute(
                "INSERT INTO order_return_requests (order_id, user_id, items_json, reason, status) "
                "VALUES (?,?,?,?, 'requested')",
                (order_id, user_id, json.dumps([{"product_id": prod["product_id"], "quantity": 1}]), "خراب است"),
            ).lastrowid
            with self.assertRaises(ConflictError):
                so.create_return_shipments(conn, rid)
            conn.execute("UPDATE order_return_requests SET status='approved' WHERE id=?", (rid,))
            conn.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo_id,))
            rets = so.create_return_shipments(conn, rid)
            self.assertEqual(len(rets), 1)
            self.assertEqual(rets[0]["direction"], "return")
            self.assertEqual(rets[0]["label"]["receiver"]["province"], "تهران")
            self.assertEqual(so.create_return_shipments(conn, rid)[0]["id"], rets[0]["id"])
            self.assertNotEqual(rets[0]["tracking_number"], s["tracking_number"])
        thu = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)            # Thursday
        self.assertEqual(so.add_business_days(thu, 1).weekday(), 5)    # skips Friday → Saturday

    def test_api_quote_public_and_admin_tariffs(self):
        r = self.client.post("/api/v1/shipping/quote", json={"origin": TEH, "destination": ISF, "parcels": [BOX]})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertNotIn("cost_minor", r.get_json()["selected"])
        self.assertNotIn("breakdown", r.get_json()["options"][0])
        _, cust = self.new_customer()
        self.assertEqual(self.client.get("/api/v1/admin/carriers/tariffs", headers=cust).status_code, 403)
        admin = self.admin_headers()
        c = self.client.post("/api/v1/admin/carriers/tariffs", headers=admin, json={
            "provider_code": "post", "service_level": "economy", "name_fa": "پست ارزان", "base_minor": 1})
        self.assertEqual(c.status_code, 201, c.get_json())
        tid = c.get_json()["tariff"]["id"]
        u = self.client.put(f"/api/v1/admin/carriers/tariffs/{tid}", headers=admin, json={"per_kg_minor": 2})
        self.assertEqual(u.get_json()["tariff"]["per_kg_minor"], 2)
        bad = self.client.put(f"/api/v1/admin/carriers/tariffs/{tid}", headers=admin, json={"base_minor": -1})
        self.assertEqual(bad.status_code, 422)
        d = self.client.delete(f"/api/v1/admin/carriers/tariffs/{tid}", headers=admin)
        self.assertEqual(d.get_json()["tariff"]["is_active"], 0)


if __name__ == "__main__":
    unittest.main()
