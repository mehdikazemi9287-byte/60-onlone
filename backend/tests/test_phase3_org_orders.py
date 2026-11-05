"""Phase 3 — organization orders, approval rules, guided buying, brand zone, pre-orders."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.errors import ConflictError
from app.services import brand_service, org_order_service as svc
from app.services import procurement_service as pr_svc
from tests.base import AppTestCase

SLUG = "office-paper-a4-carton"
PRICE = 1_000_000


class Phase3Base(AppTestCase):
    def setUp(self):
        super().setUp()
        if "org_brands" not in self.app.blueprints:
            from app.api.v1.org_brands import bp
            self.app.register_blueprint(bp)
        self.org, self.org_admin_h, self.admin, self.employee = self.org_fixture(credit_minor=50_000_000)
        self.org_id = self.org["id"]
        with self.db.read_transaction() as c:
            self.emp_uid = c.execute("SELECT user_id FROM organization_memberships WHERE id=?",
                                     (self.employee["id"],)).fetchone()[0]
        self.supplier_id, self.offer_id = self._seller("brand", stock=10)

    def _seller(self, kind, stock, nat=None):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.write_transaction() as c:
            sid = c.execute("INSERT INTO suppliers (legal_name, display_name, national_id, status, seller_kind) "
                            "VALUES ('برند تست','برند تست',?, 'active', ?)",
                            (nat or str(uuid.uuid4().int)[:10], kind)).lastrowid
            lid = c.execute("INSERT INTO supplier_locations (supplier_id, province, city, status, can_local_delivery,"
                            " can_intercity_shipping) VALUES (?, 'تهران', 'تهران', 'active', 1, 1)", (sid,)).lastrowid
            pid = c.execute("SELECT id FROM products WHERE slug=?", (SLUG,)).fetchone()[0]
            oid = c.execute("INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, selling_price_minor,"
                            " stock_quantity, status, channel, last_price_confirmed_at, last_inventory_confirmed_at)"
                            " VALUES (?,?,?,?,?, 'active', 'both', ?, ?)",
                            (pid, sid, lid, PRICE, stock, now, now)).lastrowid
        return sid, oid

    def _approved_pr(self, qty=3, destinations=None, est=2 * PRICE):
        with self.db.write_transaction() as c:
            pr = pr_svc.create_purchase_request(
                c, organization_id=self.org_id, requester_user_id=self.emp_uid, title="کاغذ اداری",
                items=[{"free_text_description": "کاغذ A4", "quantity": qty, "unit": "کارتن",
                        "estimated_unit_price_minor": est}],  # approved amount must cover tax + shipping
                delivery_province="تهران", delivery_city="تهران", delivery_address="خیابان آزادی ۱",
                destinations=destinations)
            pr_svc.submit_purchase_request(c, pr["id"], actor_user_id=self.emp_uid, organization_id=self.org_id)
            pr_svc.approve_purchase_request(c, pr["id"], actor_user_id=self.admin["user_id"],
                                            organization_id=self.org_id, action="approve")
            item = c.execute("SELECT id FROM purchase_request_items WHERE purchase_request_id=?", (pr["id"],)).fetchone()[0]
        return pr["id"], item

    def _body(self, pr_id, item_id, **extra):
        return {"purchase_request_id": pr_id, "lines": [{"purchase_request_item_id": item_id, "offer_id": self.offer_id}],
                "recipient": {"name": "واحد تدارکات", "phone": "02112345678"}, **extra}

    def _convert(self, body, key="k1"):
        return self.client.post(f"/api/v1/orgs/{self.org_id}/orders", json=body,
                                headers={**self.org_admin_h, "Idempotency-Key": key})

    def _stock(self):
        with self.db.read_transaction() as c:
            return c.execute("SELECT stock_reserved FROM seller_offers WHERE id=?", (self.offer_id,)).fetchone()[0]

    def _available_credit(self):
        from app.services.credit_service import allocation_state
        with self.db.read_transaction() as c:
            return allocation_state(c, self.employee["allocation"]["id"])["available_minor"]


class OrgOrderTests(Phase3Base):
    def test_conversion_reserves_stock_deducts_credit_and_replays(self):
        pr_id, item = self._approved_pr(qty=3)
        before = self._available_credit()
        r = self._convert(self._body(pr_id, item, po_reference="PO-1405-77"))
        self.assertEqual(r.status_code, 201, r.get_json())
        order = r.get_json()["order"]
        self.assertEqual(order["status"], "paid")
        self.assertEqual(order["total_minor"], order["subtotal_minor"] + order["shipping_fee_minor"] + order["tax_minor"])
        self.assertEqual(order["credit_minor"], order["total_minor"])
        self.assertEqual(self._stock(), 3)
        self.assertEqual(before - self._available_credit(), order["total_minor"])
        self.assertEqual(len(order["fulfillment_orders"]), 1)
        self.assertEqual(sum(a["quantity"] for a in order["allocations"]), 3)
        self.assertEqual(self.trial_balance()[0], self.trial_balance()[1])
        # PO reference reaches the invoice
        inv = self.client.get(f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/invoice", headers=self.org_admin_h)
        self.assertEqual(inv.get_json()["invoice"]["po_reference"], "PO-1405-77")
        # idempotent replay: same order, nothing reserved twice
        again = self._convert(self._body(pr_id, item, po_reference="PO-1405-77"))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["order"]["id"], order["id"])
        self.assertEqual(self._stock(), 3)
        self.assertEqual(self._convert(self._body(pr_id, item), key="k1").status_code, 409)  # key reuse, other body
        # statement
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        st = self.client.get(f"/api/v1/orgs/{self.org_id}/statement?month={month}", headers=self.org_admin_h).get_json()
        self.assertEqual(st["totals"]["orders_count"], 1)
        self.assertEqual(st["orders"][0]["po_reference"], "PO-1405-77")

    def test_insufficient_credit_writes_nothing(self):
        pr_id, item = self._approved_pr(qty=60)  # 60M > 50M credit
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET stock_quantity=100 WHERE id=?", (self.offer_id,))
        before = self._available_credit()
        r = self._convert(self._body(pr_id, item))
        self.assertEqual(r.status_code, 409, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"] if "error" in r.get_json() else r.get_json()["code"],
                         "insufficient_credit")
        self.assertEqual(self._stock(), 0)
        self.assertEqual(self._available_credit(), before)
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_sources").fetchone()[0], 0)

    def test_multi_destination_and_prepayment(self):
        dest = [{"province": "تهران", "city": "تهران", "address": "انبار مرکزی", "label": "مرکزی",
                 "recipient_name": "علی", "recipient_phone": "09120000000",
                 "allocations": [{"item_index": 0, "quantity": 2}]},
                {"province": "اصفهان", "city": "اصفهان", "address": "شعبه", "label": "شعبه",
                 "allocations": [{"item_index": 0, "quantity": 1}]}]
        pr_id, item = self._approved_pr(qty=4, destinations=dest)
        with self.db.write_transaction() as c:
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"payment_method": "prepayment", "prepayment_bps": 3000})
        order = self._convert(self._body(pr_id, item)).get_json()["order"]
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["cash_minor"], order["total_minor"] * 3000 // 10000)
        self.assertEqual(order["fulfillment_orders"], [])
        self.assertEqual(sorted((a["destination_index"], a["quantity"]) for a in order["allocations"]
                                if a["destination_index"] is not None), [(0, 2), (1, 1)])
        self.assertEqual(sum(a["quantity"] for a in order["allocations"]), 4)
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/confirm-payment",
                             json={"reference": "BANK-1"}, headers=self.org_admin_h)
        self.assertEqual(r.get_json()["order"]["status"], "paid")
        self.assertEqual(len(r.get_json()["order"]["fulfillment_orders"]), 1)

    def test_auto_approve_under_threshold_and_multilevel_above(self):
        with self.db.write_transaction() as c:
            svc.create_rule(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                            data={"name": "خرد", "max_total_minor": 5_000_000, "decision": "auto_approve"})
            svc.create_rule(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                            data={"name": "کلان", "min_total_minor": 5_000_000, "decision": "require_approvals",
                                  "required_approvals": 2})
            small = pr_svc.create_purchase_request(c, organization_id=self.org_id, requester_user_id=self.emp_uid,
                                                   title="خرد", items=[{"free_text_description": "x", "quantity": 2,
                                                                        "estimated_unit_price_minor": PRICE}])
            big = pr_svc.create_purchase_request(c, organization_id=self.org_id, requester_user_id=self.emp_uid,
                                                 title="کلان", items=[{"free_text_description": "y", "quantity": 9,
                                                                       "estimated_unit_price_minor": PRICE}])
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/purchase-requests/{small['id']}/submit-with-rules",
                             headers=self.employee["headers"]).get_json()
        self.assertEqual((r["decision"], r["purchase_request"]["status"]), ("auto_approved", "approved"))
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/purchase-requests/{big['id']}/submit-with-rules",
                             headers=self.employee["headers"]).get_json()
        self.assertEqual((r["decision"], r["purchase_request"]["status"]), ("requires_approvals", "submitted"))
        url = f"/api/v1/orgs/{self.org_id}/purchase-requests/{big['id']}/rule-approvals"
        self.assertEqual(self.client.post(url, json={"action": "approve"}, headers=self.employee["headers"]).status_code, 403)
        s1 = self.client.post(url, json={"action": "approve"}, headers=self.org_admin_h).get_json()
        self.assertEqual(s1["purchase_request"]["status"], "under_review")
        self.assertEqual(self.client.post(url, json={"action": "approve"}, headers=self.org_admin_h).status_code, 409)
        second, _ = self.make_org_admin(self.org_id)
        s2 = self.client.post(url, json={"action": "approve"}, headers=second).get_json()
        self.assertEqual(s2["purchase_request"]["status"], "approved")

    def test_preferred_seller_enforced(self):
        other, _ = self._seller("supplier", stock=5)
        with self.db.write_transaction() as c:
            svc.add_preferred(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                              data={"supplier_id": other})
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"guided_buying": "warn"})
        pr_id, item = self._approved_pr(qty=1)
        with self.db.write_transaction() as c:
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"guided_buying": "enforce"})
        r = self._convert(self._body(pr_id, item))
        self.assertEqual(r.status_code, 409)
        self.assertIn("preferred_seller_required", str(r.get_json()))
        self.assertEqual(self._stock(), 0)
        with self.db.write_transaction() as c:
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"guided_buying": "warn"})
        r = self._convert(self._body(pr_id, item), key="k2")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["order"]["warnings"][0]["code"], "not_preferred_seller")


class BrandTests(Phase3Base):
    def _reg(self):
        with self.db.write_transaction() as c:
            return brand_service.submit_registration(
                c, supplier_id=self.supplier_id, user_id=self.admin["user_id"],
                data={"brand_name": "کاغذ پارس", "trademark_number": "TM-12345", "document_url": "https://x.ir/tm.pdf"})

    def test_badge_only_after_verification(self):
        reg = self._reg()
        self.assertEqual(self.client.get("/api/v1/brands").get_json()["items"], [])
        self.assertEqual(self.client.get(f"/api/v1/brands/{self.supplier_id}").status_code, 404)
        admin = AppTestCase.admin_headers(self)
        r = self.client.post(f"/api/v1/admin/brand-registrations/{reg['id']}/review",
                             json={"decision": "verified"}, headers=admin)
        self.assertEqual(r.status_code, 200, r.get_json())
        items = self.client.get("/api/v1/brands").get_json()["items"]
        self.assertEqual([(b["id"], b["official"]) for b in items], [(self.supplier_id, True)])
        page = self.client.get(f"/api/v1/brands/{self.supplier_id}").get_json()
        self.assertEqual(page["products"][0]["offer_id"], self.offer_id)

    def test_non_brand_cannot_register(self):
        sid, _ = self._seller("shop", stock=1)
        with self.db.write_transaction() as c, self.assertRaises(Exception):
            brand_service.submit_registration(c, supplier_id=sid, user_id=self.admin["user_id"],
                                              data={"brand_name": "a", "trademark_number": "b",
                                                    "document_url": "https://x"})

    def test_preorder_deposit_without_stock_then_convert(self):
        now = datetime.now(timezone.utc)
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET stock_quantity=0 WHERE id=?", (self.offer_id,))
            brand_service.set_window(c, supplier_id=self.supplier_id, user_id=self.admin["user_id"],
                                     offer_id=self.offer_id,
                                     data={"starts_at": (now - timedelta(hours=1)).isoformat(),
                                           "ends_at": (now + timedelta(days=7)).isoformat(),
                                           "expected_ship_date": (now + timedelta(days=30)).date().isoformat(),
                                           "deposit_bps": 2000, "unit_price_minor": 900_000, "max_quantity": 5})
        _, buyer = self.new_customer()
        body = {"offer_id": self.offer_id, "quantity": 2, "shipping_address": self.DEFAULT_ADDRESS}
        r = self.client.post("/api/v1/preorders", json=body, headers={**buyer, "Idempotency-Key": "p1"})
        self.assertEqual(r.status_code, 201, r.get_json())
        pre = r.get_json()["preorder"]
        self.assertEqual((pre["total_minor"], pre["deposit_minor"], pre["status"]), (1_800_000, 360_000, "deposit_due"))
        self.assertEqual(self._stock(), 0)  # no reservation for a pre-order
        self.assertEqual(self.client.post("/api/v1/preorders", json=body,
                                          headers={**buyer, "Idempotency-Key": "p1"}).status_code, 200)
        with self.db.write_transaction() as c, self.assertRaises(ConflictError):
            brand_service.create_preorder(c, user_id=1, data={**body, "quantity": 4}, idempotency_key="p2")
        admin = AppTestCase.admin_headers(self)
        self.assertEqual(self.client.post(f"/api/v1/admin/preorders/{pre['id']}/convert", headers=admin).status_code, 409)
        self.client.post(f"/api/v1/admin/preorders/{pre['id']}/deposit", json={"reference": "D1"}, headers=admin)
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET stock_quantity=5 WHERE id=?", (self.offer_id,))
        r = self.client.post(f"/api/v1/admin/preorders/{pre['id']}/convert", headers=admin)
        self.assertEqual(r.status_code, 200, r.get_json())
        order = r.get_json()["order"]
        self.assertEqual(order["source"]["cash_due_minor"], order["total_minor"] - 360_000)
        self.assertEqual(self._stock(), 2)
        r = self.client.post(f"/api/v1/admin/preorders/{pre['id']}/balance", json={"reference": "B1"}, headers=admin)
        self.assertEqual(r.get_json()["order"]["status"], "paid")
