"""Tiered Vambi price alerts: each level sees and is alerted only about its OWN price.

All products, sellers and prices below are SYNTHETIC test fixtures (labelled «آزمایشی») created in a throwaway
SQLite database per test; nothing here is business data. SMS go to the in-process console sender only.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

from tests.base import AppTestCase
from app.adapters.sms import ConsoleSms
from app.services import price_alert_service as svc
from app.services.consumer_rights_service import gross, standard_vat_bps

RETAIL = 1_000_000          # synthetic net prices (rial)
ORG_GENERAL = 900_000       # general organization tier at 10+
ORG_A_CONTRACT = 700_000    # organization A's own contract tier at 10+
ENV_KEYS = ("STOREFRONT_PRICE_VISIBILITY", "PRICE_ALERT_DAILY_SMS_PARTS_CAP", "PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP",
            "PRICE_ALERT_USER_DAILY_SMS", "PRICE_ALERT_JOB_BUDGET_S")


class PriceAlertFixtures(AppTestCase):
    """Synthetic fixtures and helpers only (no tests)."""

    def setUp(self):
        super().setUp()
        os.environ.pop("STOREFRONT_PRICE_VISIBILITY", None)
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        ConsoleSms.texts.clear()
        # 06:05 UTC = 09:35 Tehran: outside SMS quiet hours, whatever the wall clock says
        self.now = dt.datetime.now(dt.timezone.utc).replace(hour=6, minute=5, second=0, microsecond=0)
        self.stamp = self.now.strftime("%Y-%m-%d %H:%M:%S")
        self.pid, self.slug = self.make_product()
        self.s1 = self.make_seller("آزمایشی-۱")
        self.offer1 = self.make_offer(self.s1["supplier_id"], self.pid, RETAIL)
        self.org_a = self.create_organization(name="سازمان آزمایشی الف")
        self.org_b = self.create_organization(name="سازمان آزمایشی ب")
        self.add_tier(self.offer1, ORG_GENERAL, None)
        self.add_tier(self.offer1, ORG_A_CONTRACT, self.org_a["id"])
        with self.db.read_transaction() as conn:
            self.vat = standard_vat_bps(conn)

    def tearDown(self):
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        ConsoleSms.texts.clear()
        super().tearDown()

    # ── synthetic fixtures ──────────────────────────────────────────────────
    def make_product(self):
        slug = f"pa-test-{uuid.uuid4().hex[:8]}"
        with self.db.write_transaction() as conn:
            cat = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()[0]
            pid = conn.execute("INSERT INTO products (slug, sku, title_fa, category_id, base_price_minor) VALUES (?,?,?,?,1)",
                               (slug, slug, "کالای آزمایشی هشدار قیمت", cat)).lastrowid
        return int(pid), slug

    def make_seller(self, name):
        sup = self.create_test_supplier()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE suppliers SET display_name=? WHERE id=?", (f"غرفه {name}", sup["supplier_id"]))
        return sup

    def make_offer(self, supplier_id, pid, price, stock=50):
        with self.db.write_transaction() as conn:
            loc = conn.execute("SELECT id FROM supplier_locations WHERE supplier_id=?", (supplier_id,)).fetchone()[0]
            return int(conn.execute(
                "INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, selling_price_minor, stock_quantity,"
                " last_price_confirmed_at, last_inventory_confirmed_at, status) VALUES (?,?,?,?,?,?,?, 'active')",
                (pid, supplier_id, loc, price, stock, self.stamp, self.stamp)).lastrowid)

    def add_tier(self, offer_id, price, org_id, min_qty=10):
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO offer_price_tiers (offer_id, channel, organization_id, min_qty, unit_price_minor, confirmed_at)"
                         " VALUES (?, 'organization', ?, ?, ?, ?)", (offer_id, org_id, min_qty, price, self.stamp))

    def set_price(self, offer_id, price=None, stock=None):
        with self.db.write_transaction() as conn:
            if price is not None:
                conn.execute("UPDATE seller_offers SET selling_price_minor=? WHERE id=?", (price, offer_id))
            if stock is not None:
                conn.execute("UPDATE seller_offers SET stock_quantity=? WHERE id=?", (stock, offer_id))

    def set_tier(self, offer_id, org_id, price):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE offer_price_tiers SET unit_price_minor=? WHERE offer_id=? AND organization_id IS ?",
                         (price, offer_id, org_id))

    def verify_phone(self, headers):
        uid = self.client.get("/api/v1/auth/me", headers=headers).get_json()["user"]["id"]
        phone = "0912" + str(uuid.uuid4().int)[:7]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET phone_verified=? WHERE id=?", (phone, uid))
        return uid, phone

    def org_buyer(self, org):
        headers, _ = self.make_org_admin(org["id"])
        return headers

    def tick(self, hours=0, sender=None, **kw):
        return svc.run(self.db, now=self.now + dt.timedelta(hours=hours), sender=sender or ConsoleSms(), **kw)

    def watch(self, headers, expect=201, **body):
        r = self.client.post("/api/v1/me/price-watches", json={"slug": self.slug, **body}, headers=headers)
        self.assertEqual(r.status_code, expect, r.get_json())
        return r.get_json()

    def notes(self, headers, kind="price_alert"):
        return [n for n in self.client.get("/api/v1/me/notifications", headers=headers).get_json()["items"] if n["kind"] == kind]

    def g(self, net):
        return gross(net, self.vat)

    @staticmethod
    def fa_toman(minor):
        return svc.toman(minor)

    def assert_no_price(self, blob, *nets):
        text = json.dumps(blob, ensure_ascii=False) if not isinstance(blob, str) else blob
        for net in nets:
            for v in {net, self.g(net)}:
                self.assertNotIn(str(v), text)
                self.assertNotIn(self.fa_toman(v).split(" ")[0], text)


class PriceAlertsTest(PriceAlertFixtures):
    # ── level detection ─────────────────────────────────────────────────────
    def test_level_auto_detection(self):
        _, consumer = self.new_customer()
        self.assertEqual(self.client.get("/api/v1/me/price-watches/level", headers=consumer).get_json()["level"], "consumer")
        admin_a, _ = self.make_org_admin(self.org_a["id"])
        emp = self.add_employee(self.org_a["id"], admin_a)
        self.assertEqual(self.client.get("/api/v1/me/price-watches/level", headers=emp["headers"]).get_json()["level"], "employee")
        self.assertEqual(self.client.get("/api/v1/me/price-watches/level", headers=admin_a).get_json()["level"], "org_buyer")
        shop_org = self.create_organization(name="فروشگاه آزمایشی")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organizations SET buyer_kind='retailer' WHERE id=?", (shop_org["id"],))
        shop = self.org_buyer(shop_org)
        lv = self.client.get("/api/v1/me/price-watches/level", headers=shop).get_json()
        self.assertEqual((lv["level"], lv["organization_id"]), ("shop", shop_org["id"]))
        # the client cannot pick a level, and cannot claim someone else's organization
        w = self.watch(shop, level="consumer")["watch"]
        self.assertEqual(w["level"], "shop")
        r = self.client.post("/api/v1/me/price-watches", json={"slug": self.slug, "organization_id": self.org_b["id"]}, headers=shop)
        self.assertEqual(r.status_code, 404)
        # sellers get automatic alerts in the seller panel instead of buyer watches
        r = self.client.post("/api/v1/me/price-watches", json={"slug": self.slug}, headers=self.s1["headers"])
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "seller_alerts_automatic"))
        # alert types of another level are refused
        r = self.client.post("/api/v1/me/price-watches", json={"slug": self.slug, "alert_types": ["new_tier"]}, headers=consumer)
        self.assertEqual(r.status_code, 422)

    # ── no level sees another level's price ─────────────────────────────────
    def test_levels_see_only_their_own_price(self):
        _, consumer = self.new_customer()
        a, b = self.org_buyer(self.org_a), self.org_buyer(self.org_b)
        wc = self.watch(consumer)["watch"]
        wa = self.watch(a, quantity=10)["watch"]
        wb = self.watch(b, quantity=10)["watch"]
        self.assertEqual(wc["current"]["price_minor"], self.g(RETAIL))
        self.assertEqual(wa["current"]["price_minor"], self.g(ORG_A_CONTRACT))
        self.assertEqual(wb["current"]["price_minor"], self.g(ORG_GENERAL))
        self.assert_no_price(self.client.get("/api/v1/me/price-watches", headers=consumer).get_json(), ORG_GENERAL, ORG_A_CONTRACT)
        self.assert_no_price(self.client.get("/api/v1/me/price-watches", headers=b).get_json(), ORG_A_CONTRACT)
        # history: org B never reads org A's contract history, and each sees only its own series
        self.tick()
        hb = self.client.get(f"/api/v1/me/price-watches/{wb['id']}/history", headers=b).get_json()
        self.assertTrue(hb["points"])
        self.assertEqual({p["price_minor"] for p in hb["points"]}, {self.g(ORG_GENERAL)})
        self.assert_no_price(hb, ORG_A_CONTRACT)
        hc = self.client.get(f"/api/v1/me/price-watches/{wc['id']}/history", headers=consumer).get_json()
        self.assert_no_price(hc, ORG_GENERAL, ORG_A_CONTRACT)
        self.assertEqual(self.client.get(f"/api/v1/me/price-watches/{wa['id']}/history", headers=b).status_code, 404)

    def test_price_drops_alert_only_the_level_that_changed(self):
        _, consumer = self.new_customer()
        a, b = self.org_buyer(self.org_a), self.org_buyer(self.org_b)
        self.verify_phone(consumer); self.verify_phone(a); self.verify_phone(b)
        self.watch(consumer, target_price_minor=self.g(RETAIL) - 1)
        self.watch(a, quantity=10)
        self.watch(b, quantity=10)
        self.tick()  # baseline: nothing fires on the first look
        self.assertEqual(self.notes(a) + self.notes(b) + self.notes(consumer), [])
        self.set_tier(self.offer1, self.org_a["id"], 650_000)   # only org A's contract price drops
        self.tick(hours=1)
        na = self.notes(a)
        self.assertEqual(len(na), 1)
        self.assert_no_price(na, 650_000, ORG_A_CONTRACT, ORG_GENERAL)   # org bodies never carry a price (B7)
        self.assertEqual(na[0]["link"], "/me/price-alerts")
        self.assertEqual(self.notes(b), [])
        self.assertEqual(self.notes(consumer), [])
        sms_a = [t for _, t in ConsoleSms.texts]
        self.assertEqual(len(sms_a), 1)
        self.assert_no_price(sms_a[0], 650_000, ORG_A_CONTRACT, ORG_GENERAL, RETAIL)  # SMS carry no prices at all
        # retail drop reaches the consumer only; the consumer text never contains organization prices
        self.set_price(self.offer1, price=950_000)
        self.tick(hours=2)
        nc = self.notes(consumer)
        self.assertEqual(len(nc), 1)
        self.assertIn("ارزان شد", nc[0]["title"])
        self.assert_no_price(nc, 650_000, ORG_GENERAL, ORG_A_CONTRACT)
        self.assertEqual(len(self.notes(b)), 0)

    # ── sellers: "no longer best offer", competitor hidden ─────────────────
    def test_seller_alert_hides_competitor_price(self):
        s2 = self.make_seller("رقیب")
        o2 = self.make_offer(s2["supplier_id"], self.pid, 1_100_000)
        self.verify_phone(self.s1["headers"])
        self.tick()
        self.set_price(o2, price=880_000)
        self.tick(hours=1)
        n = self.notes(self.s1["headers"], kind="price_alert_seller")
        self.assertEqual(len(n), 2)  # lost at both levels it sells in (offer channel 'both')
        self.assertTrue(all("بهترین پیشنهاد" in x["title"] for x in n))
        self.assertEqual(sorted("خرده‌فروشی" in x["body"] for x in n), [False, True])
        self.assert_no_price(n, 880_000)
        self.assertNotIn("رقیب", json.dumps(n, ensure_ascii=False))
        panel = self.client.get("/api/v1/supplier/price-alerts", headers=self.s1["headers"]).get_json()
        self.assert_no_price(panel, 880_000)
        self.assertNotIn("رقیب", json.dumps(panel, ensure_ascii=False))
        retail = [i for i in panel["items"] if i["level"] == "retail"][0]
        self.assertFalse(retail["is_best"])
        self.assertEqual(retail["own_price_minor"], RETAIL)
        self.assertTrue(panel["recent"])
        self.assertEqual(len(ConsoleSms.texts), 1)
        self.assert_no_price(ConsoleSms.texts[0][1], 880_000, RETAIL)
        # the winner is not alerted; a non-seller cannot open the seller panel
        self.assertEqual(self.notes(s2["headers"], kind="price_alert_seller"), [])
        _, consumer = self.new_customer()
        self.assertEqual(self.client.get("/api/v1/supplier/price-alerts", headers=consumer).status_code, 403)

    # ── idempotency, caps, digest ───────────────────────────────────────────
    def test_rerun_same_hour_sends_nothing_twice(self):
        _, consumer = self.new_customer()
        self.verify_phone(consumer)
        self.watch(consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.tick(hours=1)
        before = (len(self.notes(consumer)), len(ConsoleSms.texts))
        self.assertEqual(before, (1, 1))
        # rerun in the same hour, even with the watch state rolled back to force a second detection
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE price_watches SET state_json=?", (json.dumps({"price": self.g(RETAIL), "in_stock": True, "sellers": []}),))
        self.tick(hours=1)
        self.assertEqual((len(self.notes(consumer)), len(ConsoleSms.texts)), before)

    def test_daily_per_item_cap_and_digest(self):
        _, consumer = self.new_customer()
        self.verify_phone(consumer)
        pid2, slug2 = self.make_product()
        o2 = self.make_offer(self.s1["supplier_id"], pid2, 2_000_000)
        self.watch(consumer)
        self.client.post("/api/v1/me/price-watches", json={"slug": slug2}, headers=consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.set_price(o2, price=1_900_000)
        self.tick(hours=1)
        self.assertEqual(len(self.notes(consumer)), 2)
        self.assertEqual(len(ConsoleSms.texts), 1)               # two alerts → ONE digest SMS
        self.assertEqual(ConsoleSms.texts[0][1].count("ارزان شد"), 2)
        self.set_price(self.offer1, price=800_000)              # same item, same day, next hour
        self.tick(hours=2)
        self.assertEqual(len(self.notes(consumer)), 3)          # in-site always
        self.assertEqual(len(ConsoleSms.texts), 1)              # but no second SMS for that item today
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT sms_status FROM price_alert_events ORDER BY id DESC LIMIT 1").fetchone()[0],
                             "skipped_item")

    def test_global_daily_sms_cap(self):
        os.environ["PRICE_ALERT_DAILY_SMS_PARTS_CAP"] = "3"  # one digest is 2 billed UCS-2 parts
        users = []
        for _ in range(2):
            _, h = self.new_customer()
            self.verify_phone(h)
            self.watch(h)
            users.append(h)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.tick(hours=1)
        self.assertEqual(sum(len(self.notes(h)) for h in users), 2)
        self.assertEqual(len(ConsoleSms.texts), 1)
        with self.db.read_transaction() as conn:
            statuses = sorted(r[0] for r in conn.execute("SELECT sms_status FROM price_alert_events"))
        self.assertEqual(statuses, ["sent", "skipped_cap"])
        with self.db.read_transaction() as conn:
            self.assertLessEqual(conn.execute("SELECT SUM(parts) FROM price_alert_sms WHERE status='sent'").fetchone()[0], 3)

    def test_no_sms_without_verified_phone(self):
        _, consumer = self.new_customer()
        self.watch(consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.tick(hours=1)
        self.assertEqual(len(self.notes(consumer)), 1)
        self.assertEqual(ConsoleSms.texts, [])

    # ── level-specific alerts ───────────────────────────────────────────────
    def test_back_in_stock_and_shop_new_tier(self):
        shop_org = self.create_organization(name="فروشگاه آزمایشی")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organizations SET buyer_kind='retailer' WHERE id=?", (shop_org["id"],))
        shop = self.org_buyer(shop_org)
        _, consumer = self.new_customer()
        self.set_price(self.offer1, stock=0)
        self.watch(consumer)
        self.watch(shop, quantity=10)
        self.tick()
        self.set_price(self.offer1, stock=40)
        self.add_tier(self.offer1, 850_000, None, min_qty=50)
        self.tick(hours=1)
        self.assertEqual([n["title"].split("» ")[1] for n in self.notes(consumer)], ["موجود شد"])
        shop_titles = sorted(n["title"].split("» ")[1] for n in self.notes(shop))
        self.assertEqual(shop_titles, sorted(["موجود شد", "پلهٔ تخفیف تعدادی جدید"]))
        self.assert_no_price(self.notes(shop), ORG_A_CONTRACT)

    def test_org_new_seller_and_contract_expiry(self):
        a = self.org_buyer(self.org_a)
        self.watch(a, quantity=10)
        self.tick()
        s2 = self.make_seller("تازه")
        self.make_offer(s2["supplier_id"], self.pid, 1_050_000)
        soon = (self.now + dt.timedelta(days=3)).date().isoformat()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET valid_until=? WHERE id=?", (soon, self.offer1))
        self.tick(hours=1)
        kinds = sorted(n["title"].split("» ")[1] for n in self.notes(a))
        self.assertEqual(kinds, sorted(["فروشندهٔ تازه", "پایان قیمت قراردادی"]))
        self.tick(hours=2)  # expiry warned once only
        self.assertEqual(len(self.notes(a)), 2)
        # org B has no contract on this offer: no expiry alert for B
        b = self.org_buyer(self.org_b)
        self.watch(b, quantity=10)
        self.tick(hours=3)
        self.assertEqual(self.notes(b), [])

    def test_employee_welfare_basket_alert(self):
        admin_a, _ = self.make_org_admin(self.org_a["id"])
        emp = self.add_employee(self.org_a["id"], admin_a)
        w = self.watch(emp["headers"])["watch"]
        self.assertEqual(w["level"], "employee")
        self.assertIn("welfare_added", w["alert_types"])
        self.assertEqual(w["current"]["price_minor"], self.g(RETAIL))  # employees follow retail, not org price
        self.tick()
        fmt = "%Y-%m-%d %H:%M:%S"
        with self.db.write_transaction() as conn:
            plan = conn.execute(
                "INSERT INTO welfare_plans (reference, organization_id, title, plan_type, per_employee_cap_minor, starts_at,"
                " expires_at, all_members, status, idempotency_key) VALUES (?,?,?, 'product', 1000000, ?, ?, 1, 'active', ?)",
                (uuid.uuid4().hex, self.org_a["id"], "طرح آزمایشی", (self.now - dt.timedelta(days=1)).strftime(fmt),
                 (self.now + dt.timedelta(days=30)).strftime(fmt), uuid.uuid4().hex)).lastrowid
            conn.execute("INSERT INTO welfare_plan_targets (plan_id, product_id) VALUES (?,?)", (plan, self.pid))
        self.tick(hours=1)
        self.assertEqual([n["title"].split("» ")[1] for n in self.notes(emp["headers"])], ["به سبد رفاهی اضافه شد"])

    # ── ownership, visibility, level change ─────────────────────────────────
    def test_ownership(self):
        _, owner = self.new_customer()
        _, other = self.new_customer()
        wid = self.watch(owner)["watch"]["id"]
        self.assertEqual(self.client.patch(f"/api/v1/me/price-watches/{wid}", json={"active": False}, headers=other).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/me/price-watches/{wid}", headers=other).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/me/price-watches/{wid}/history", headers=other).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/me/price-watches", headers=other).get_json()["items"], [])
        self.assertEqual(self.client.get("/api/v1/me/price-watches").status_code, 401)
        r = self.client.patch(f"/api/v1/me/price-watches/{wid}", json={"target_price_minor": 500_000}, headers=owner)
        self.assertEqual(r.get_json()["watch"]["target_price_minor"], 500_000)
        self.assertEqual(self.watch(owner, expect=200)["watch"]["id"], wid)  # same product → same watch
        self.assertEqual(self.client.delete(f"/api/v1/me/price-watches/{wid}", headers=owner).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me/price-watches", headers=owner).get_json()["items"], [])

    def test_price_visibility_respected(self):
        os.environ["STOREFRONT_PRICE_VISIBILITY"] = "organizations"
        _, consumer = self.new_customer()
        r = self.client.post("/api/v1/me/price-watches", json={"slug": self.slug, "target_price_minor": 1000}, headers=consumer)
        self.assertEqual(r.status_code, 403)
        w = self.watch(consumer)["watch"]
        self.assertEqual(w["alert_types"], ["back_in_stock"])
        self.assertIsNone(w["current"]["price_minor"])
        self.assertEqual(self.client.get(f"/api/v1/me/price-watches/{w['id']}/history", headers=consumer).status_code, 403)
        self.assert_no_price(self.client.get("/api/v1/me/price-watches", headers=consumer).get_json(), RETAIL)
        # an organization buyer may still see their own price in this mode
        a = self.org_buyer(self.org_a)
        self.assertEqual(self.watch(a, quantity=10)["watch"]["current"]["price_minor"], self.g(ORG_A_CONTRACT))
        self.tick()
        with self.db.write_transaction() as conn:   # even a forced price-target watch stays silent while prices are hidden
            conn.execute("UPDATE price_watches SET alert_types='price_target,back_in_stock' WHERE level='consumer'")
        self.set_price(self.offer1, price=500_000)
        self.tick(hours=1)
        self.assertEqual(self.notes(consumer), [])

    def test_former_member_loses_org_price(self):
        admin_a, member = self.make_org_admin(self.org_a["id"])
        w = self.watch(admin_a, quantity=10)["watch"]
        self.assertEqual(w["current"]["price_minor"], self.g(ORG_A_CONTRACT))
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organization_memberships SET status='inactive' WHERE id=?", (member["id"],))
        listed = self.client.get("/api/v1/me/price-watches", headers=admin_a).get_json()
        self.assertTrue(listed["items"][0]["current"]["level_changed"])
        self.assert_no_price(listed, ORG_A_CONTRACT)
        self.assertEqual(self.client.get(f"/api/v1/me/price-watches/{w['id']}/history", headers=admin_a).status_code, 409)
        self.tick()
        listed = self.client.get("/api/v1/me/price-watches", headers=admin_a).get_json()["items"][0]
        self.assertEqual((listed["level"], listed["organization_id"]), ("consumer", None))
        self.assertEqual(listed["current"]["price_minor"], self.g(RETAIL))


class FailingSms(ConsoleSms):
    """Synthetic provider that always fails (no network)."""
    calls = 0

    def send_text(self, phone, text):
        FailingSms.calls += 1
        raise RuntimeError("synthetic provider outage")


class PriceAlertsReviewTest(PriceAlertFixtures):
    """Review fixes B1–B8 (runs on the same synthetic fixtures)."""

    # B1 — re-POST only reactivates; fields change only when sent
    def test_repost_keeps_settings_and_status_lookup(self):
        _, consumer = self.new_customer()
        w = self.watch(consumer, target_price_minor=900_000, alert_types=["back_in_stock"], sms_enabled=False)["watch"]
        self.client.patch(f"/api/v1/me/price-watches/{w['id']}", json={"active": False}, headers=consumer)
        again = self.watch(consumer, expect=200)["watch"]
        self.assertEqual((again["id"], again["active"], again["target_price_minor"], again["alert_types"], again["sms_enabled"]),
                         (w["id"], True, 900_000, ["back_in_stock"], False))
        again = self.watch(consumer, expect=200, target_price_minor=800_000)["watch"]
        self.assertEqual((again["target_price_minor"], again["alert_types"]), (800_000, ["back_in_stock"]))
        a = self.org_buyer(self.org_a)
        wa = self.watch(a, quantity=24)["watch"]
        self.assertEqual(self.watch(a, expect=200)["watch"]["quantity"], 24)
        self.assertEqual(wa["allowed_alert_types"], ["price_drop", "new_seller", "contract_expiring"])
        self.assertEqual(wa["alert_fa"]["price_drop"], "کاهش قیمت")
        found = self.client.get(f"/api/v1/me/price-watches?product={self.slug}", headers=consumer).get_json()["items"]
        self.assertEqual([x["id"] for x in found], [w["id"]])
        self.assertEqual(self.client.get("/api/v1/me/price-watches?product=no-such-slug", headers=consumer).get_json()["items"], [])

    # B5 — watch limit and digest reservation are race-safe (ON CONFLICT, not 500)
    def test_limit_and_reservation_conflicts(self):
        _, consumer = self.new_customer()
        self.watch(consumer)
        pid2, slug2 = self.make_product()
        old = svc.MAX_WATCHES
        svc.MAX_WATCHES = 1
        try:
            r = self.client.post("/api/v1/me/price-watches", json={"slug": slug2}, headers=consumer)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "price_watch_limit"))
        finally:
            svc.MAX_WATCHES = old
        uid, _ = self.verify_phone(consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        with self.db.write_transaction() as conn:  # an overlapping run already reserved this user's digest for the hour
            conn.execute("INSERT INTO price_alert_sms (user_id, run_hour, day, item_count, status, created_at) VALUES (?,?,?,1,'sent',?)",
                         (uid, svc._hour(self.now + dt.timedelta(hours=1)), "2000-01-01", "x"))
        self.tick(hours=1)
        self.assertEqual(ConsoleSms.texts, [])
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT sms_status FROM price_alert_events").fetchone()[0], "pending")
        self.tick(hours=2)  # next hour: sent once
        self.assertEqual(len(ConsoleSms.texts), 1)

    # B2 — bounded job: consecutive provider failures and the time budget
    def test_provider_failures_and_budget_leave_rest_pending(self):
        heads = []
        for _ in range(5):
            _, h = self.new_customer()
            self.verify_phone(h)
            self.watch(h)
            heads.append(h)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        FailingSms.calls = 0
        r = self.tick(hours=1, sender=FailingSms())
        self.assertEqual((FailingSms.calls, r["sms"]["failed"], r["sms"]["deferred"]), (3, 3, 2))
        with self.db.read_transaction() as conn:
            statuses = sorted(x[0] for x in conn.execute("SELECT sms_status FROM price_alert_events"))
        self.assertEqual(statuses, ["failed"] * 3 + ["pending"] * 2)
        r = self.tick(hours=2, budget_s=0)  # no time left: nothing is checked or sent, all stays pending
        self.assertEqual((r["watches"]["checked"], r["sms"]["sent"]), (0, 0))
        self.assertGreater(r["watches"]["deferred"], 0)
        r = self.tick(hours=3)
        self.assertEqual(r["sms"]["sent"], 2)

    # B3 — per-user daily digests, seller budget, seller SMS opt-out
    def test_user_daily_limit_and_seller_sms_controls(self):
        os.environ["PRICE_ALERT_USER_DAILY_SMS"] = "1"
        _, consumer = self.new_customer()
        self.verify_phone(consumer)
        pid2, slug2 = self.make_product()
        o2 = self.make_offer(self.s1["supplier_id"], pid2, 2_000_000)
        self.watch(consumer)
        self.client.post("/api/v1/me/price-watches", json={"slug": slug2}, headers=consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.tick(hours=1)
        self.set_price(o2, price=1_900_000)
        self.tick(hours=2)
        self.assertEqual(len(self.notes(consumer)), 2)
        self.assertEqual(len(ConsoleSms.texts), 1)   # second digest of the day refused by the per-user limit
        # seller: separate budget, and an opt-out that keeps in-site alerts
        ConsoleSms.texts.clear()
        os.environ["PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP"] = "0"
        s2 = self.make_seller("رقیب")
        o3 = self.make_offer(s2["supplier_id"], self.pid, 1_500_000)
        self.verify_phone(self.s1["headers"])
        self.tick(hours=3)
        self.set_price(o3, price=500_000)
        self.tick(hours=4)
        self.assertEqual(len(self.notes(self.s1["headers"], kind="price_alert_seller")), 2)
        self.assertEqual(ConsoleSms.texts, [])  # seller budget 0 → no seller SMS, buyers unaffected by it
        r = self.client.patch("/api/v1/supplier/price-alerts/settings", json={"sms_enabled": False}, headers=self.s1["headers"])
        self.assertEqual(r.get_json(), {"sms_enabled": False})
        self.assertFalse(self.client.get("/api/v1/supplier/price-alerts", headers=self.s1["headers"]).get_json()["sms_enabled"])
        _, buyer = self.new_customer()
        self.assertEqual(self.client.patch("/api/v1/supplier/price-alerts/settings", json={"sms_enabled": False},
                                           headers=buyer).status_code, 403)
        os.environ.pop("PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP")
        self.set_price(o3, price=1_600_000)   # s1 best again …
        self.tick(hours=5)
        self.set_price(o3, price=400_000)     # … and beaten again: in-site yes, SMS no (opted out)
        self.tick(hours=6)
        self.assertEqual(len(self.notes(self.s1["headers"], kind="price_alert_seller")), 4)
        self.assertEqual(ConsoleSms.texts, [])
        self.assertTrue(all("نیستید" in n["title"] for n in self.notes(self.s1["headers"], kind="price_alert_seller")))

    # B4 — one failing item never aborts the run
    def test_bad_row_is_skipped_not_fatal(self):
        _, consumer = self.new_customer()
        pid2, slug2 = self.make_product()
        o2 = self.make_offer(self.s1["supplier_id"], pid2, 2_000_000)
        self.watch(consumer)
        self.client.post("/api/v1/me/price-watches", json={"slug": slug2}, headers=consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.set_price(o2, price=1_900_000)
        real = svc.observe

        def broken(conn, **kw):
            if kw["product_id"] == self.pid:
                raise RuntimeError("synthetic bad row")
            return real(conn, **kw)
        svc.observe = broken
        try:
            r = self.tick(hours=1)
        finally:
            svc.observe = real
        self.assertEqual(r["watches"]["errors"], 1)
        self.assertEqual([n["link"] for n in self.notes(consumer)], [f"/products/{slug2}"])

    # B6 — seller-written titles are sanitized before SMS
    def test_sms_title_sanitized(self):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET title_fa=? WHERE id=?",
                         ("آزمایشی تماس 09121234567 @shop https://x.example.ir/a www.y.com", self.pid))
        _, consumer = self.new_customer()
        self.verify_phone(consumer)
        self.watch(consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        self.tick(hours=1)
        text = ConsoleSms.texts[0][1]
        for bad in ("0912", "@", "http", "www", "example"):
            self.assertNotIn(bad, text)
        self.assertEqual(svc.sms_safe("  کالا   ۱۲۳۴۵۶  تست "), "کالا تست")
        self.assertEqual(svc.sms_parts("a" * 160), 1)
        self.assertEqual((svc.sms_parts("س" * 70), svc.sms_parts("س" * 71), svc.sms_parts("س" * 135)), (1, 2, 3))

    # B8 — quiet hours and retention
    def test_quiet_hours_and_cleanup(self):
        _, consumer = self.new_customer()
        self.verify_phone(consumer)
        self.watch(consumer)
        self.tick()
        self.set_price(self.offer1, price=900_000)
        r = self.tick(hours=14)          # 20:05 UTC = 23:35 Tehran
        self.assertEqual(len(self.notes(consumer)), 1)   # in-site immediately
        self.assertEqual((ConsoleSms.texts, r["sms"]["held"]), ([], 1))
        self.tick(hours=20)              # 02:05 UTC = 05:35 Tehran: still quiet
        self.assertEqual(ConsoleSms.texts, [])
        self.tick(hours=23)              # 05:05 UTC = 08:35 Tehran: sent
        self.assertEqual(len(ConsoleSms.texts), 1)
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO price_history_daily (product_id, scope, organization_key, quantity, day, updated_at)"
                         " VALUES (?, 'retail', 0, 1, '2000-01-01', 'x')", (self.pid,))
            conn.execute("UPDATE price_alert_events SET created_at='2000-01-01T00:00:00Z'")
        r = self.tick(hours=24)
        self.assertGreaterEqual(r["cleanup"]["history"], 1)
        self.assertGreaterEqual(r["cleanup"]["events"], 1)
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM price_history_daily WHERE day='2000-01-01'").fetchone()[0], 0)
