"""Phase 2 — cashier engine, partner discounts, buy box, multi-seller basket, recurring lists."""
from __future__ import annotations

import datetime as dt
import unittest
import uuid

from tests.base import AppTestCase
from app.api.v1 import cashier as cashier_api
from app.services import cashier_service as cashier
from app.services import recurring_service

NOW = dt.datetime.now(dt.timezone.utc)
STAMP = NOW.strftime("%Y-%m-%d %H:%M:%S")


def line(**kw):
    base = {"product_id": 1, "offer_id": 1, "supplier_id": 10, "seller_kind": "shop", "category_id": 1, "quantity": 2,
            "base_unit_minor": 1_000_000, "tier_unit_minor": None, "contract_unit_minor": None,
            "cost_unit_minor": None, "commission_bps": 900, "partner_discounts": []}
    base.update(kw)
    return base


def partner(pct, funded="partner", **kw):
    return {"id": kw.get("id", 1), "title_fa": "تخفیف", "partner_supplier_id": kw.get("partner_supplier_id"),
            "partner_name": "گیفت‌آسان", "percent_bps": pct, "max_discount_minor": kw.get("max"),
            "funded_by": funded, "coupon_code": None}


def ctx(**kw):
    c = {"user_id": 1, "organization_id": None, "channel": "retail", "redeem_coins": 0, "coin_balance": 0,
         "coupon_codes": (), "credit_available_minor": 0, "recurring": False}
    c.update(kw)
    return c


RULES = {k: dict(v, rule_key=k) for k, v in cashier.DEFAULT_RULES.items()}


class PureEngineTest(unittest.TestCase):
    def test_stacking_order_and_caps(self):
        q = cashier.compute([line(tier_unit_minor=950_000, contract_unit_minor=900_000, cost_unit_minor=500_000,
                                  partner_discounts=[partner(2000)])],
                            ctx(organization_id=5, channel="organization", redeem_coins=100, coin_balance=1000,
                                credit_available_minor=1_000_000), RULES)
        l = q["lines"][0]
        self.assertEqual((l["unit_price_minor"], l["price_source"]), (900_000, "contract"))  # no stacking with tier
        self.assertEqual(l["partner_discount_minor"], 270_000)  # 20% requested, capped to 15% of 1.8M
        self.assertEqual(l["line_after_discounts_minor"], 1_530_000)
        self.assertEqual(q["totals"]["coins_used"], 30)  # 20% of 1.53M = 306k → 30 coins
        self.assertEqual(l["payable_minor"], 1_230_000)
        self.assertEqual([a["step"] for a in l["adjustments"]], ["price_selection", "partner_discount", "coins"])
        self.assertEqual(l["commission_minor"], 162_000)
        self.assertEqual(l["seller_share_minor"], 1_638_000)
        self.assertEqual((l["partner_funded_minor"], l["platform_funded_minor"]), (270_000, 300_000))
        self.assertEqual(q["partner_receivables"][0]["amount_minor"], 270_000)
        self.assertEqual((q["totals"]["credit_minor"], q["totals"]["cash_minor"]), (1_000_000, 230_000))

    def test_price_selection_modes(self):
        l = line(tier_unit_minor=850_000, contract_unit_minor=900_000)
        self.assertEqual(cashier.compute([l], ctx(), RULES)["lines"][0]["unit_price_minor"], 850_000)
        rules = {**RULES, "price_selection": {**RULES["price_selection"], "mode": "contract_first"}}
        self.assertEqual(cashier.compute([l], ctx(), rules)["lines"][0]["unit_price_minor"], 900_000)

    def test_seller_net_floor_guard(self):
        # No cost disclosed: floor = 2M - 9% = 1.82M; 10% partner (200k) is clipped to 180k.
        l = cashier.compute([line(partner_discounts=[partner(1000)])], ctx(redeem_coins=50, coin_balance=50), RULES)
        l0 = l["lines"][0]
        self.assertEqual(l0["line_after_discounts_minor"], 1_820_000)
        self.assertEqual(l0["adjustments"][0]["capped_by"], "seller_net_floor")
        self.assertEqual(l["totals"]["coins_used"], 0)  # no headroom left above the floor
        self.assertGreaterEqual(l0["payable_minor"], l0["seller_net_floor_minor"])

    def test_own_partner_promo_is_seller_funded(self):
        l = cashier.compute([line(cost_unit_minor=0, partner_discounts=[partner(1000, partner_supplier_id=10)])],
                            ctx(), RULES)["lines"][0]
        self.assertEqual(l["seller_funded_minor"], 200_000)
        self.assertEqual(l["seller_share_minor"], 2_000_000 - 180_000 - 200_000)

    def test_recurring_discount_tiers(self):
        four = cashier.compute([line(product_id=i, cost_unit_minor=0) for i in range(4)], ctx(recurring=True), RULES)
        five = cashier.compute([line(product_id=i, cost_unit_minor=0) for i in range(5)], ctx(recurring=True), RULES)
        self.assertEqual(four["recurring_rule"], "recurring_discount")
        self.assertEqual(four["lines"][0]["line_after_discounts_minor"], 1_900_000)
        self.assertEqual(five["recurring_rule"], "recurring_discount_bulk")
        self.assertEqual(five["lines"][0]["line_after_discounts_minor"], 1_800_000)
        self.assertEqual(cashier.compute([line()], ctx(), RULES)["recurring_rule"], None)


class CashierDbTest(AppTestCase):
    def setUp(self):
        super().setUp()
        if "cashier" not in self.app.blueprints:
            self.app.register_blueprint(cashier_api.bp)
        made = []
        with self.db.write_transaction() as conn:
            cat = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()[0]
            for n in (1, 2):
                slug = f"p2-test-{n}-{uuid.uuid4().hex[:6]}"
                pid = conn.execute("INSERT INTO products (slug, sku, title_fa, category_id, base_price_minor) "
                                   "VALUES (?,?,?,?,1)", (slug, slug, f"کالای تست {n}", cat)).lastrowid
                made.append({"id": pid, "slug": slug, "category_id": cat})
        self.p1, self.p2 = made

    def seller(self, kind="shop", health="good"):
        with self.db.write_transaction() as conn:
            sid = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, seller_kind, health_status) "
                "VALUES (?,?,?, 'active', ?, ?)", ("فروشنده", f"غرفه {kind}", uuid.uuid4().hex[:11], kind, health)).lastrowid
            conn.execute("INSERT INTO supplier_locations (supplier_id, province, city, status) VALUES (?, 'تهران', 'تهران', 'active')",
                         (sid,))
        return sid

    def offer(self, sid, pid, price, cost=None, stock=50, fresh=True):
        with self.db.write_transaction() as conn:
            loc = conn.execute("SELECT id FROM supplier_locations WHERE supplier_id=?", (sid,)).fetchone()[0]
            return conn.execute(
                "INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, selling_price_minor, cost_price_minor,"
                " stock_quantity, last_price_confirmed_at, last_inventory_confirmed_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, sid, loc, price, cost, stock, STAMP if fresh else None, STAMP if fresh else None)).lastrowid

    def test_buy_box_selection(self):
        pid = self.p1["id"]
        self.offer(self.seller(health="suspended"), pid, 500_000)
        self.offer(self.seller(health="at_risk"), pid, 800_000)
        self.offer(self.seller(), pid, 400_000, fresh=False)
        shop = self.offer(self.seller(), pid, 1_000_000)
        brand = self.offer(self.seller("brand"), pid, 1_000_000)
        with self.db.read_transaction() as conn:
            box = cashier.buy_box(conn, pid)
        self.assertEqual(box["winner"]["offer_id"], brand)  # good beats at_risk; brand wins the price tie
        reasons = {o["offer_id"]: o["reasons"] for o in box["offers"]}
        self.assertTrue(any("seller_suspended" in r for r in reasons.values()))
        self.assertTrue(any("price_unconfirmed" in r for r in reasons.values()))
        self.assertEqual(reasons[shop], [])
        r = self.client.get(f"/api/v1/storefront/products/{self.p1['slug']}/offers")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["winner"]["offer_id"], brand)
        self.assertNotIn("cost_price_minor", r.get_json()["offers"][0])

    def test_multi_seller_basket_split_and_partner_discount(self):
        a, b = self.seller("shop"), self.seller("brand")
        self.offer(a, self.p1["id"], 1_000_000)
        self.offer(b, self.p2["id"], 2_000_000)
        admin = self.admin_headers()
        r = self.client.post("/api/v1/admin/partner-discounts", headers=admin, json={
            "title_fa": "هدیهٔ گیفت‌آسان", "partner_name": "گیفت‌آسان", "scope": "seller", "seller_supplier_id": b,
            "percent_bps": 500, "funded_by": "partner"})
        self.assertEqual(r.status_code, 201, r.get_json())
        r = self.client.post("/api/v1/cashier/basket", json={"items": [
            {"slug": self.p1["slug"], "quantity": 1}, {"product_id": self.p2["id"], "quantity": 1}]})
        self.assertEqual(r.status_code, 200, r.get_json())
        q = r.get_json()["quote"]
        self.assertEqual(q["seller_count"], 2)
        by = {s["supplier_id"]: s for s in q["sellers"]}
        self.assertEqual(by[a]["commission_minor"], 90_000)    # shop 9%
        self.assertEqual(by[b]["commission_minor"], 240_000)   # brand 12%
        self.assertEqual(by[b]["partner_funded_minor"], 100_000)
        self.assertEqual(by[b]["seller_share_minor"], 1_760_000)
        self.assertEqual(q["totals"]["payable_minor"], 2_900_000)

    def test_admin_rules_and_recurring_flow(self):
        admin = self.admin_headers()
        r = self.client.patch("/api/v1/admin/cashier-rules/partner_discount", headers=admin, json={"step_order": 70})
        self.assertEqual(r.status_code, 422)
        r = self.client.patch("/api/v1/admin/cashier-rules/coins", headers=admin, json={"cap_bps": 1000})
        self.assertEqual(r.get_json()["rule"]["cap_bps"], 1000)
        self.assertEqual(self.client.get("/api/v1/admin/cashier-rules").status_code, 401)

        self.offer(self.seller(), self.p1["id"], 1_000_000, cost=0)
        _, headers = self.new_customer()
        r = self.client.post("/api/v1/me/recurring", headers=headers, json={
            "title": "خرید هفتگی رستوران", "frequency": "weekly", "items": [{"product_id": self.p1["id"], "quantity": 3}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        lid = r.get_json()["list"]["id"]
        with self.db.write_transaction() as conn:
            done = recurring_service.run_due(conn)
            again = recurring_service.run_due(conn)
        self.assertEqual((done["quoted"], again["quoted"]), (1, 0))
        self.assertEqual(done["runs"][0]["payable_minor"], 2_850_000)  # 3M − 5% recurring
        runs = self.client.get(f"/api/v1/me/recurring/{lid}/runs", headers=headers).get_json()["items"]
        self.assertEqual(runs[0]["status"], "quoted")
        r = self.client.post(f"/api/v1/me/recurring/{lid}/pause", headers=headers)
        self.assertEqual(r.get_json()["list"]["status"], "paused")
        self.assertEqual(r.get_json()["list"]["next_run_on"],
                         (NOW.date() + dt.timedelta(days=7)).isoformat())

    def test_quote_reports_unavailable_and_rejects_foreign_org(self):
        org = self.create_organization()
        _, headers = self.new_customer()
        r = self.client.post("/api/v1/cashier/quote", headers=headers,
                             json={"items": [{"product_id": self.p1["id"]}], "organization_id": org["id"]})
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/api/v1/cashier/quote", json={"items": [{"product_id": self.p1["id"], "quantity": 1}]})
        self.assertEqual(r.get_json()["quote"]["unavailable"][0]["reasons"], ["no_offer"])


if __name__ == "__main__":
    unittest.main()
