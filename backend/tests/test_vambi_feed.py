"""فید فقط‌خواندنی وامبی (v2): auth, tier scoping, incremental, pagination, Persian digits, tombstones.

All rows below are synthetic test fixtures (labeled «آزمون»), created only inside the isolated test DB.
"""
from __future__ import annotations

import json
import os
from unittest import mock

from app.services import storefront_service as store
from app.services import vambi_feed_service as feed
from tests.test_phase6_catalog_schema import Phase6Base

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = "/api/v1/feeds/vambi/products"


class VambiFeedTest(Phase6Base):
    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ, {"VAMBI_FEED_TOKEN": TOKEN, "VAMBI_FEED_RATE_PER_MIN": "1000"})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.org_a = self.create_organization(name="سازمان آزمون الف")["id"]
        self.org_b = self.create_organization(name="سازمان آزمون ب")["id"]
        self.m = self.master("supermarket--oil--liquid", name="روغن آزمون فید")
        self.sup = self.create_test_supplier()
        sid, pid = self.sup["supplier_id"], self.m["product_id"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE suppliers SET provenance='real' WHERE id=?", (sid,))
            self.offer = conn.execute(
                """INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, selling_price_minor, cost_price_minor,
                       stock_quantity, status, min_order_quantity, lead_time_days, pricing_mode, channel, provenance,
                       last_price_confirmed_at, last_inventory_confirmed_at)
                   VALUES (?,?,?,1000000,700000,12,'active',1,3,'fixed','both','real',datetime('now'),datetime('now'))""",
                (pid, sid, self.sup["location_id"])).lastrowid
            fresh = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            for ch, org, lo, hi, price, conf in (
                    ("retail", None, 10, None, 900000, fresh),          # public quantity break
                    ("organization", None, 1, 49, 850000, fresh),       # wholesale (any B2B account)
                    ("organization", None, 50, None, 820000, fresh),    # wholesale quantity break
                    ("organization", self.org_a, 1, None, 800000, fresh),  # contract: org A only
                    ("retail", self.org_b, 1, None, 780000, fresh),     # contract on retail channel: org B only
                    ("organization", None, 100, None, 10, "strftime('%Y-%m-%dT%H:%M:%fZ','now','-2 days')")):  # stale
                conn.execute(f"""INSERT INTO offer_price_tiers (offer_id, channel, organization_id, min_qty, max_qty,
                                 unit_price_minor, confirmed_at) VALUES (?,?,?,?,?,?,{conf})""",
                             (self.offer, ch, org, lo, hi, price))

    def get(self, query="", headers=None):
        return self.client.get(URL + query, headers=AUTH if headers is None else headers)

    def item(self, pid=None, query=""):
        r = self.get(query)
        self.assertEqual(r.status_code, 200, r.get_json())
        return next(i for i in r.get_json()["items"] if i["id"] == (pid or self.m["product_id"]))

    # ── auth ──
    def test_auth_required(self):
        self.assertEqual(self.get(headers={}).status_code, 401)
        self.assertEqual(self.get(headers={"Authorization": "Bearer " + "x" * 40}).status_code, 401)
        self.assertEqual(self.get(headers={"Authorization": TOKEN}).status_code, 401)  # no Bearer scheme
        with mock.patch.dict(os.environ, {"VAMBI_FEED_TOKEN": ""}):
            self.assertEqual(self.get().status_code, 404)  # off until configured
        with mock.patch.dict(os.environ, {"VAMBI_FEED_TOKEN": "short"}):
            self.assertEqual(self.get(headers={"Authorization": "Bearer short"}).status_code, 404)  # weak token ignored
        with mock.patch.dict(os.environ, {"VAMBI_FEED_TOKEN": "n" * 40 + "," + TOKEN}):
            self.assertEqual(self.get().status_code, 200)  # rotation: either token works

    def test_rate_limited_per_token(self):
        with mock.patch.dict(os.environ, {"VAMBI_FEED_RATE_PER_MIN": "2"}):
            self.assertEqual(self.get().status_code, 200)
            self.assertEqual(self.get().status_code, 200)
            r = self.get()
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (429, "rate_limit_exceeded"))

    # ── tiers ──
    def test_all_tiers_with_scope_and_vat(self):
        r = self.get()
        body = r.get_json()
        self.assertEqual(body["spec_version"], "v2")
        vat = body["vat_bps"]
        it = self.item()
        self.assertTrue(it["active"])
        [o] = it["offers"]
        self.assertEqual((o["supplier_id"], o["lead_time_days"], o["stock_state"]), (self.sup["supplier_id"], 3, "in_stock"))
        self.assertTrue(o["seller_city"])
        key = repr
        got = sorted(((p["tier"], p["channel"], p.get("org_id"), p["min_qty"], p["max_qty"], p["price_net_minor"])
                      for p in o["prices"]), key=key)
        self.assertEqual(got, sorted([
            ("public", "retail", None, 1, None, 1000000), ("public", "retail", None, 10, None, 900000),
            ("wholesale", "organization", None, 1, None, 1000000), ("wholesale", "organization", None, 1, 49, 850000),
            ("wholesale", "organization", None, 50, None, 820000),
            ("org", "organization", self.org_a, 1, None, 800000), ("org", "retail", self.org_b, 1, None, 780000)], key=key))
        for p in o["prices"]:
            self.assertEqual(p["price_incl_vat_minor"], p["price_net_minor"] + p["price_net_minor"] * vat // 10000)
            self.assertEqual(p["vat_bps"], vat)
            self.assertTrue(p["fresh_until"] > p["confirmed_at"])
            self.assertEqual("org_id" in p, p["tier"] == "org")
        raw = r.get_data(as_text=True)
        for secret in ("cost_price", "700000", "commission", "coupon"):
            self.assertNotIn(secret, raw)

    def test_contract_mode_has_no_public_price(self):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET pricing_mode='contract' WHERE id=?", (self.offer,))
        tiers = {p["tier"] for p in self.item()["offers"][0]["prices"]}
        self.assertEqual(tiers, {"wholesale", "org"})

    def test_retail_only_offer_has_no_b2b_tiers_and_stale_base_is_dropped(self):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET channel='retail', last_price_confirmed_at=datetime('now','-3 days') "
                         "WHERE id=?", (self.offer,))
        prices = self.item()["offers"][0]["prices"]
        # stale base price gone; only fresh retail tiers remain (public break + org B's retail contract)
        self.assertEqual(sorted((p["tier"], p["price_net_minor"]) for p in prices), [("org", 780000), ("public", 900000)])

    def test_rfq_only_offer_has_no_prices(self):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET pricing_mode='rfq_only' WHERE id=?", (self.offer,))
        self.assertEqual(self.item()["offers"][0]["prices"], [])

    def test_storefront_never_shows_contract_tier_to_outsiders(self):
        with self.db.read_transaction() as conn:
            anon = store.offers_for(conn, self.m["product_id"], viewer_org_ids=())
            org_a = store.offers_for(conn, self.m["product_id"], viewer_org_ids=(self.org_a,))
        anon_tiers = [t for o in anon for ts in o["tiers"].values() for t in ts]
        self.assertFalse(any(t["contract"] for t in anon_tiers), anon_tiers)  # was leaking org B's retail contract
        a_prices = sorted(t["unit_price_minor"] for o in org_a for t in o["tiers"]["organization"] if t["contract"])
        self.assertEqual(a_prices, [800000])
        self.assertNotIn(780000, [t["unit_price_minor"] for o in org_a for ts in o["tiers"].values() for t in ts])

    def test_storefront_hides_org_only_offer_price_from_non_members(self):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET channel='organization' WHERE id=?", (self.offer,))
        with self.db.read_transaction() as conn:
            [anon] = store.offers_for(conn, self.m["product_id"], viewer_org_ids=())
            [member] = store.offers_for(conn, self.m["product_id"], viewer_org_ids=(self.org_a,))
        self.assertEqual((anon["price_minor"], anon["price_incl_vat_minor"], anon["list_price_minor"]), (None, None, None))
        self.assertEqual(anon["tiers"], {"retail": [], "organization": []})
        self.assertEqual(member["price_minor"], 1000000)
        # the feed still carries it, scoped as wholesale (Vambi applies the same audience rule)
        tiers = {p["tier"] for p in self.item()["offers"][0]["prices"]}
        self.assertEqual(tiers, {"wholesale", "org"})

    # ── catalogue scope, tombstones ──
    def test_demo_excluded_and_inactive_is_tombstone(self):
        demo = self.master("supermarket--oil--liquid", name="کالای نمایشی آزمون")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET provenance='demo' WHERE id=?", (demo["product_id"],))
            conn.execute("UPDATE products SET is_active=0 WHERE id=?", (self.m["product_id"],))
        items = self.get().get_json()["items"]
        self.assertNotIn(demo["product_id"], [i["id"] for i in items])
        it = self.item()
        self.assertEqual((it["active"], it["offers"]), (False, []))
        self.assertNotIn("title_fa", it)

    # ── incremental + pagination ──
    def test_incremental_since(self):
        other = self.master("supermarket--oil--liquid", name="کالای دوم آزمون")
        with self.db.write_transaction() as conn:
            for pid in (self.m["product_id"], other["product_id"]):
                conn.execute("UPDATE products SET created_at='2026-01-01 00:00:00' WHERE id=?", (pid,))
                conn.execute("UPDATE master_products SET updated_at='2026-01-01 00:00:00' WHERE id=(SELECT master_product_id FROM products WHERE id=?)", (pid,))
                conn.execute("UPDATE product_families SET updated_at='2026-01-01 00:00:00' WHERE id=(SELECT m.family_id FROM products p JOIN master_products m ON m.id=p.master_product_id WHERE p.id=?)", (pid,))
            conn.execute("UPDATE seller_offers SET updated_at='2026-01-01 00:00:00', last_price_confirmed_at='2026-01-01 00:00:00', "
                         "last_inventory_confirmed_at='2026-01-01 00:00:00', created_at='2026-01-01 00:00:00' WHERE id=?", (self.offer,))
            conn.execute("UPDATE offer_price_tiers SET confirmed_at='2026-03-01T10:00:00Z', created_at='2026-03-01T10:00:00Z' "
                         "WHERE offer_id=?", (self.offer,))
        ids = lambda q: [i["id"] for i in self.get(q).get_json()["items"]]
        mine = (self.m["product_id"], other["product_id"])
        self.assertEqual([i for i in ids("?updated_since=2026-02-01T00:00:00Z") if i in mine], [self.m["product_id"]])
        # Persian digits in the timestamp
        self.assertEqual([i for i in ids("?updated_since=۲۰۲۶-۰۲-۰۱T۰۰:۰۰:۰۰Z") if i in mine], [self.m["product_id"]])
        self.assertEqual(sorted(i for i in ids("?updated_since=2025-12-31T00:00:00Z") if i in mine), sorted(mine))
        self.assertEqual(ids("?updated_since=2999-01-01T00:00:00Z"), [])
        self.assertEqual(self.item(query="?updated_since=2026-02-01T00:00:00Z")["updated_at"], "2026-03-01T10:00:00Z")
        r = self.get("?updated_since=yesterday")
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "invalid_updated_since"))

    def test_cursor_pagination_without_duplicates(self):
        for n in range(3):
            self.master("supermarket--oil--liquid", name=f"کالای صفحه‌بندی آزمون {n}")
        with self.db.read_transaction() as conn:
            everything = [pid for _, pid in feed._sorted_keys(conn, None)]
        self.assertGreaterEqual(len(everything), 4)
        size = min(500, max(2, -(-len(everything) // 3)))
        seen, cursor, pages = [], None, 0
        while True:
            fa = str(size).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
            q = f"?limit={fa}" + (f"&cursor={cursor}" if cursor else "")  # Persian digit limit
            body = self.get(q).get_json()
            self.assertLessEqual(len(body["items"]), size)
            seen += [i["id"] for i in body["items"]]
            cursor, pages = body["next_cursor"], pages + 1
            if not cursor:
                break
            self.assertLessEqual(pages, -(-len(everything) // size))
        self.assertEqual(pages, -(-len(everything) // size))
        self.assertGreaterEqual(pages, 2)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(sorted(seen), sorted(everything))
        for bad in ("?limit=0", "?limit=501", "?limit=abc", "?cursor=@@@", "?cursor=" + "eyJhIjoxfQ"):
            self.assertEqual(self.get(bad).status_code, 422, bad)

    def test_parse_helpers(self):
        self.assertEqual(feed.parse_limit("۱۰"), 10)
        self.assertEqual(feed.iso(feed.parse_ts("2026-11-12 10:00:00")), "2026-11-12T10:00:00Z")
        self.assertEqual(feed.iso(feed.parse_ts("2026-11-12T13:30:00+03:30")), "2026-11-12T10:00:00Z")
        c = feed.encode_cursor(feed.parse_ts("2026-11-12T10:00:00Z"), 7)
        self.assertEqual(feed.decode_cursor(c), (feed.parse_ts("2026-11-12T10:00:00Z"), 7))
        self.assertIsNone(feed.parse_ts("not a date"))
        json.dumps(feed.SPEC_VERSION)
