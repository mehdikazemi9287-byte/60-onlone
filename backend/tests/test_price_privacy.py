"""Closed ecosystem: price visibility modes, redaction scope, price-filter guard, aggregator crawler block."""
from __future__ import annotations

import os
from unittest import mock

from tests.base import AppTestCase

LIST = "/api/v1/storefront/products?group=sku"


def _prices(obj):
    """All non-null price values anywhere in a JSON body."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k != "price_hidden" and ("price" in k or k.endswith("_minor")) and not isinstance(v, (dict, list)) and v is not None:
                out.append((k, v))
            else:
                out += _prices(v)
    elif isinstance(obj, list):
        for x in obj:
            out += _prices(x)
    return out


class PricePrivacyTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["COMMERCE_TEST_MODE"] = True
        self.addCleanup(self.app.config.__setitem__, "COMMERCE_TEST_MODE", None)
        self.p = self.product("office-paper-a4-carton")

    def test_public_mode_unchanged(self):
        d = self.client.get(f"/api/v1/products/{self.p['slug']}").get_json()
        self.assertNotIn("price_hidden", d)

    @mock.patch.dict(os.environ, {"STOREFRONT_PRICE_VISIBILITY": "organizations"})
    def test_organizations_mode(self):
        url = f"/api/v1/products/{self.p['slug']}"
        anon = self.client.get(url).get_json()
        self.assertTrue(anon["price_hidden"])
        self.assertEqual(_prices(anon), [])
        self.assertEqual(self.client.get(LIST + "&min_price=1").status_code, 403)
        self.assertEqual(self.client.get(LIST + "&sort=price_asc").status_code, 403)
        _, cust = self.new_customer()  # signed in but not in an organization
        self.assertTrue(self.client.get(url, headers=cust).get_json()["price_hidden"])
        # no buying blind: cart and checkout are closed to viewers who may not see prices
        for method, path in (("get", "/api/v1/cart"), ("post", "/api/v1/cart/items"), ("post", "/api/v1/checkout/quote")):
            r = getattr(self.client, method)(path, json={}, headers=cust)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (403, "price_members_only"), path)
        # cashier quotes are catalog too: any method is redacted
        q = self.client.post("/api/v1/cashier/quote", json={"items": [{"product_id": self.p["id"], "quantity": 1}]})
        self.assertEqual(_prices(q.get_json() or {}), [], q.get_json())
        admin = self.client.get(url, headers=self.admin_headers()).get_json()
        self.assertNotIn("price_hidden", admin)
        self.assertTrue(_prices(admin))
        sup = self.create_test_supplier()
        self.assertNotIn("price_hidden", self.client.get(url, headers=sup["headers"]).get_json())

    @mock.patch.dict(os.environ, {"STOREFRONT_PRICE_VISIBILITY": "members"})
    def test_members_mode(self):
        url = f"/api/v1/products/{self.p['slug']}"
        self.assertTrue(self.client.get(url).get_json()["price_hidden"])
        _, cust = self.new_customer()
        self.assertNotIn("price_hidden", self.client.get(url, headers=cust).get_json())

    @mock.patch.dict(os.environ, {"STOREFRONT_PRICE_VISIBILITY": "bogus"})
    def test_unknown_mode_fails_closed(self):
        self.assertTrue(self.client.get(f"/api/v1/products/{self.p['slug']}").get_json()["price_hidden"])

    def test_aggregator_crawlers_blocked(self):
        for ua in ("TorobBot/1.0", "Mozilla/5.0 (compatible; EmallsCrawler)", "basalam-spider"):
            r = self.client.get(LIST, headers={"User-Agent": ua})
            self.assertEqual(r.status_code, 403, ua)
        self.assertEqual(self.client.get(LIST, headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"}).status_code, 200)
