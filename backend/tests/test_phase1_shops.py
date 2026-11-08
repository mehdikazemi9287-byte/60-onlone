"""Phase 1 — seller shops: registration, review, shop page, commission, escrow, health."""
from __future__ import annotations

import datetime as dt
import uuid

from app.core.errors import ConflictError
from app.services import seller_shop_service as shops
from app.services import settlement_service
from tests.base import AppTestCase
from tests.test_settlement import _make_delivered_payable

VALID_NID = "0499370899"            # passes the 10-digit checksum
VALID_SHEBA = "IR062960000000100324200001"


def _application(**over):
    d = {"seller_kind": "shop", "legal_name": "کارگاه آزمون", "shop_title": "غرفه آزمون",
         "shop_slug": f"t{uuid.uuid4().hex[:8]}", "national_id": VALID_NID, "mobile": "09121234567",
         "province": "تهران", "city": "تهران", "sheba": VALID_SHEBA, "accept_terms": True}
    d.update(over)
    return d


class ValidatorsTest(AppTestCase):
    seed_data = False

    def test_national_id_and_sheba(self):
        self.assertTrue(shops.valid_national_id(VALID_NID))
        self.assertFalse(shops.valid_national_id("0499370898"))
        self.assertFalse(shops.valid_national_id("1111111111"))
        self.assertTrue(shops.valid_national_id("10101234567"))
        self.assertTrue(shops.valid_sheba(VALID_SHEBA))
        self.assertFalse(shops.valid_sheba("IR062960000000100324200002"))
        self.assertFalse(shops.valid_sheba("DE062960000000100324200001"))


class ShopFlowTest(AppTestCase):
    def apply(self, headers, **over):
        return self.client.post("/api/v1/sellers/apply", json=_application(**over), headers=headers)

    def test_register_review_and_public_page(self):
        _, seller = self.new_customer()
        r = self.apply(seller, shop_slug="karen-crafts")
        self.assertEqual(r.status_code, 201, r.get_json())
        shop = r.get_json()["shop"]
        self.assertEqual(shop["onboarding_stage"], "submitted")
        self.assertEqual(shop["commission_rate_bps"], 900)
        # Not public until approved.
        self.assertEqual(self.client.get("/api/v1/shops/karen-crafts").status_code, 404)
        # Second shop for the same account is refused.
        self.assertEqual(self.apply(seller, shop_slug="other-one", national_id="10101234567").status_code, 409)

        admin = self.admin_headers()
        apps = self.client.get("/api/v1/admin/shop-applications", headers=admin).get_json()["items"]
        self.assertIn(shop["id"], [a["id"] for a in apps])
        bad = self.client.post(f"/api/v1/admin/shop-applications/{shop['id']}/review",
                               json={"decision": "reject"}, headers=admin)
        self.assertEqual(bad.status_code, 422)  # rejection needs a reason
        ok = self.client.post(f"/api/v1/admin/shop-applications/{shop['id']}/review",
                              json={"decision": "approve"}, headers=admin)
        self.assertEqual(ok.status_code, 200, ok.get_json())
        page = self.client.get("/api/v1/shops/karen-crafts")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.get_json()["shop"]["title"], "غرفه آزمون")
        self.assertNotIn("sheba_on_file", page.get_json()["shop"])  # private fields stay private
        self.assertIn("karen-crafts", [s["slug"] for s in self.client.get("/api/v1/shops").get_json()["items"]])

        # An approved shop owner keeps role customer but can use the seller portal.
        self.assertEqual(self.client.get("/api/v1/supplier/offers", headers=seller).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/supplier/payables", headers=seller).status_code, 200)
        mine = self.client.get("/api/v1/supplier/shop", headers=seller).get_json()
        self.assertEqual(mine["balance"]["ready_minor"], 0)
        upd = self.client.put("/api/v1/supplier/shop", json={"shop_bio": "دست‌ساز"}, headers=seller)
        sheba = self.client.put("/api/v1/supplier/shop", json={"sheba": "IR820540102680020817909002"}, headers=seller)
        self.assertEqual(sheba.status_code, 200, sheba.get_json())
        self.assertTrue(sheba.get_json()["shop"]["payout_hold"])  # payouts wait for admin re-verification
        sid = sheba.get_json()["shop"]["id"]
        ok = self.client.post(f"/api/v1/admin/shops/{sid}/verify-payout", headers=admin)
        self.assertFalse(ok.get_json()["shop"]["payout_hold"])
        self.assertEqual(upd.get_json()["shop"]["bio"], "دست‌ساز")
        self.assertEqual(self.client.put("/api/v1/supplier/shop", json={"commission_rate_bps": 0},
                                         headers=seller).status_code, 422)

    def test_validation(self):
        _, seller = self.new_customer()
        for over in ({"accept_terms": False}, {"national_id": "123"}, {"sheba": "IR00"},
                     {"mobile": "0912"}, {"shop_slug": "Admin"}, {"seller_kind": "supplier"}, {"x": 1}):
            with self.subTest(over=over):
                self.assertEqual(self.apply(seller, **over).status_code, 422)


class CommissionAndEscrowTest(AppTestCase):
    def test_rules_and_overrides(self):
        _, sid_entry = None, None
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            self.assertEqual(shops.resolve_commission_bps(conn, supplier_id=supplier_id, category_id=None,
                                                          channel="retail"), 1000)
            self.assertEqual(shops.resolve_commission_bps(conn, supplier_id=supplier_id, category_id=None,
                                                          channel="organization"), 1000)  # contract rate kept
            conn.execute("UPDATE suppliers SET seller_kind='shop' WHERE id=?", (supplier_id,))
            self.assertEqual(shops.resolve_commission_bps(conn, supplier_id=supplier_id, category_id=None,
                                                          channel="organization"), 500)
            conn.execute("UPDATE suppliers SET seller_kind='brand' WHERE id=?", (supplier_id,))
            self.assertEqual(shops.resolve_commission_bps(conn, supplier_id=supplier_id, category_id=None,
                                                          channel="retail"), 1200)
            conn.execute("UPDATE suppliers SET commission_rate_bps=300 WHERE id=?", (supplier_id,))
            self.assertEqual(shops.resolve_commission_bps(conn, supplier_id=supplier_id, category_id=None,
                                                          channel="retail"), 300)
        # The contracted supplier's payable has a commission snapshot and no escrow hold.
        self.assertEqual(entry["commission_minor"], entry["gross_minor"] * 1000 // 10_000)
        self.assertIsNone(entry["available_at"])

    def test_snapshot_commission_used_and_escrow_enforced(self):
        supplier_id, entry = _make_delivered_payable(self)
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE supplier_payable_entries SET commission_minor=?, available_at=? WHERE id=?",
                         (123, future, entry["id"]))
            with self.assertRaises(ConflictError) as e:
                settlement_service.create_settlement_batch(conn, supplier_id=supplier_id,
                                                           payable_entry_ids=[entry["id"]], idempotency_key="k1")
            self.assertEqual(e.exception.code, "payable_on_hold")
            b = shops.balance(conn, supplier_id=supplier_id)
            self.assertEqual(b["held_minor"], entry["gross_minor"] - 123)
            conn.execute("UPDATE supplier_payable_entries SET available_at=NULL WHERE id=?", (entry["id"],))
            conn.execute("UPDATE suppliers SET health_status='suspended' WHERE id=?", (supplier_id,))
            with self.assertRaises(ConflictError) as e:
                settlement_service.create_settlement_batch(conn, supplier_id=supplier_id,
                                                           payable_entry_ids=[entry["id"]], idempotency_key="k2")
            self.assertEqual(e.exception.code, "seller_suspended")
            conn.execute("UPDATE suppliers SET health_status='good' WHERE id=?", (supplier_id,))
            batch = settlement_service.create_settlement_batch(conn, supplier_id=supplier_id,
                                                               payable_entry_ids=[entry["id"]], idempotency_key="k3")
        self.assertEqual(batch["commission_minor"], 123)
        self.assertEqual(batch["net_minor"], entry["gross_minor"] - 123)


class HealthTest(AppTestCase):
    def test_thresholds(self):
        supplier_id, _ = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            fo = dict(conn.execute("SELECT * FROM fulfillment_orders WHERE supplier_id=? ORDER BY id DESC LIMIT 1",
                                   (supplier_id,)).fetchone())
            self.assertEqual(shops.compute_health(conn, supplier_id=supplier_id)["status"], "good")  # too few orders
            cols = [k for k in fo if k != "id"]
            for i in range(11):  # 12 orders, 1 rejected (8.3% cancel ≥ 5%) → suspended
                vals = {**fo, "status": "rejected" if i == 0 else "delivered"}
                conn.execute(f"INSERT INTO fulfillment_orders ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                             [vals[c] for c in cols])
            h = shops.compute_health(conn, supplier_id=supplier_id)
            self.assertEqual(h["orders"], 12)
            self.assertEqual(h["cancel_bps"], 833)
            self.assertEqual(h["status"], "suspended")
            self.assertEqual(conn.execute("SELECT health_status FROM suppliers WHERE id=?",
                                          (supplier_id,)).fetchone()[0], "suspended")


class WebhookEmittersTest(AppTestCase):
    def test_settlement_completed_event_emitted_once(self):
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            b = settlement_service.create_settlement_batch(conn, supplier_id=supplier_id,
                                                           payable_entry_ids=[entry["id"]], idempotency_key="wh1")
            settlement_service.complete_settlement_batch(conn, batch_id=b["id"])
            settlement_service.complete_settlement_batch(conn, batch_id=b["id"])  # idempotent replay
            rows = conn.execute("SELECT event_key FROM partner_webhook_events WHERE event_type='settlement.completed'"
                                ).fetchall()
        self.assertEqual([r[0] for r in rows], [f"settlement.completed:{b['id']}"])
