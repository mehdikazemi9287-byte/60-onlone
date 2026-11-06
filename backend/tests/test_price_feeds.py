"""Torob Product API v3 feed (EdDSA token, three request modes) and the seller Basalam export."""
from __future__ import annotations

import os
import time
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import marketplace_offer_service as offers
from tests.base import AppTestCase
from tests.test_phase6_catalog_schema import Phase6Base

URL = "/api/v1/feeds/torob/v3/products"


class TorobFeedTest(Phase6Base):
    def setUp(self):
        super().setUp()
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.env = mock.patch.dict(os.environ, {"TOROB_PUBLIC_KEY": pub, "TOROB_AUD": "60online.ir", "TOROB_PRICE_UNIT": "toman"})
        self.env.start()
        self.addCleanup(self.env.stop)
        sup = self.create_test_supplier()
        m = self.master("supermarket--oil--liquid")
        with self.db.write_transaction() as conn:
            offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"],
                          data={"product_id": m["product_id"], "selling_price_minor": 1_000_000, "stock_quantity": 5,
                                "supplier_location_id": sup["location_id"]})
            conn.execute("UPDATE suppliers SET provenance='real' WHERE id=?", (sup["supplier_id"],))
            conn.execute("UPDATE seller_offers SET provenance='real', pricing_mode='fixed', channel='retail', "
                         "last_price_confirmed_at=datetime('now'), last_inventory_confirmed_at=datetime('now') WHERE product_id=?",
                         (m["product_id"],))
            slug = conn.execute("SELECT slug FROM products WHERE id=?", (m["product_id"],)).fetchone()[0]
        self.p = {"id": m["product_id"], "slug": slug}
        prev = self.app.config.get("STOREFRONT_SALES_ENABLED")
        self.app.config["STOREFRONT_SALES_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "STOREFRONT_SALES_ENABLED", prev)

    def set_stock(self, pid, qty):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET stock_quantity=?, stock_reserved=0 WHERE product_id=?", (qty, pid))

    def tok(self, aud="60online.ir", exp=60, key=None):
        return jwt.encode({"aud": aud, "exp": int(time.time()) + exp, "nbf": int(time.time()) - 5}, key or self.key, algorithm="EdDSA")

    def post(self, body, token=None, version="1"):
        h = {"X-Torob-Token": token if token is not None else self.tok(), "X-Torob-Token-Version": version}
        return self.client.post(URL, json=body, headers=h)

    def test_auth(self):
        self.assertEqual(self.post({"page": 1}, token="").status_code, 401)
        self.assertEqual(self.post({"page": 1}, version="2").status_code, 401)
        self.assertEqual(self.post({"page": 1}, token=self.tok(aud="evil.ir")).status_code, 401)
        self.assertEqual(self.post({"page": 1}, token=self.tok(exp=-120)).status_code, 401)
        self.assertEqual(self.post({"page": 1}, token=self.tok(key=Ed25519PrivateKey.generate())).status_code, 401)
        hs = jwt.encode({"aud": "60online.ir", "exp": int(time.time()) + 60}, "x" * 32, algorithm="HS256")
        self.assertEqual(self.post({"page": 1}, token=hs).status_code, 401)  # no algorithm confusion
        with mock.patch.dict(os.environ, {"TOROB_PUBLIC_KEY": ""}):
            self.assertEqual(self.post({"page": 1}).status_code, 503)

    def test_page_mode_and_product_shape(self):
        r = self.post({"page": 1, "sort": "date_added_desc"})
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertEqual(d["api_version"], "torob_api_v3")
        self.assertEqual(d["current_page"], 1)
        self.assertGreaterEqual(d["total"], 1)
        self.assertLessEqual(len(d["products"]), 100)
        item = next(x for x in d["products"] if x["page_unique"] == str(self.p["id"]))
        for k in ("page_unique", "page_url", "title", "current_price", "availability", "image_links", "spec", "date_added"):
            self.assertIn(k, item)
        self.assertTrue(item["availability"])
        self.assertGreater(item["current_price"], 0)
        self.assertTrue(item["page_url"].endswith(f"/products/{self.p['slug']}"))
        empty = self.post({"page": d["max_pages"] + 1}).get_json()
        self.assertEqual(empty["products"], [])
        for bad in ({"page": 0}, {"page": "1"}, {"sort": "price"}, {"page_urls": []}, {"page_uniques": list(range(101))},
                    {"sort": "product_id_desc", "cursor": "abc"}):
            self.assertEqual(self.post(bad).status_code, 400, bad)

    def test_price_is_vat_inclusive_and_unit(self):
        from app.services import consumer_rights_service as crs
        from app.services import storefront_service as sf
        with self.db.read_transaction() as conn:
            net = sf.availability_map(conn, [self.p["id"]])[self.p["id"]][1]
            gross = crs.gross(net, crs.standard_vat_bps(conn))
        toman = self.post({"page_uniques": [str(self.p["id"])]}).get_json()["products"][0]["current_price"]
        self.assertEqual(toman, gross // 10)
        with mock.patch.dict(os.environ, {"TOROB_PRICE_UNIT": "rial"}):
            self.assertEqual(self.post({"page_uniques": [str(self.p["id"])]}).get_json()["products"][0]["current_price"], gross)

    def test_lookup_and_cursor(self):
        mine = self.post({"page_uniques": [str(self.p["id"])]}).get_json()["products"][0]["page_url"]
        by_url = self.post({"page_urls": [mine, "https://other.ir/products/" + self.p["slug"]]}).get_json()
        self.assertEqual([x["page_unique"] for x in by_url["products"]], [str(self.p["id"])])
        self.set_stock(self.p["id"], 0)
        out = self.post({"page_uniques": [str(self.p["id"])]}).get_json()["products"][0]
        self.assertEqual((out["availability"], out["current_price"]), (False, 0))
        seen, cur = [], None
        for _ in range(100):
            body = {"sort": "product_id_desc", **({"cursor": cur} if cur else {})}
            d = self.post(body).get_json()
            seen += [int(x["page_unique"]) for x in d["products"]]
            cur = d["next_cursor"]
            if not cur:
                break
        self.assertEqual(seen, sorted(seen, reverse=True))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), self.post({"page": 1}).get_json()["total"])


class BasalamExportTest(AppTestCase):
    def test_seller_export_own_offers_only(self):
        sup = self.create_test_supplier()
        self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"], stock=7)
        other = self.create_test_supplier()
        self.create_test_product_with_offer(other["supplier_id"], other["location_id"], stock=3)
        d = self.client.get("/api/v1/supplier/feeds/basalam", headers=sup["headers"]).get_json()
        self.assertEqual(d["format"], "basalam_bulk_v1")
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["items"][0]["stock"], 7)
        self.assertTrue(d["warnings"])  # category not mapped to Basalam yet
        csv_r = self.client.get("/api/v1/supplier/feeds/basalam?format=csv", headers=sup["headers"])
        self.assertEqual(csv_r.status_code, 200)
        self.assertIn("price_rial", csv_r.get_data(as_text=True))
        _, cust = self.new_customer()
        self.assertEqual(self.client.get("/api/v1/supplier/feeds/basalam", headers=cust).status_code, 403)
