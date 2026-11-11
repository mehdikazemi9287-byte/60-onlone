"""وامبی: one exact product, every in-ecosystem seller side by side; price privacy applies."""
from __future__ import annotations

import os
from unittest import mock

from app.services import marketplace_offer_service as offers
from tests.test_phase6_catalog_schema import Phase6Base


class VambiTest(Phase6Base):
    def setUp(self):
        super().setUp()
        self.app.config["STOREFRONT_SALES_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "STOREFRONT_SALES_ENABLED", None)
        self.m = self.master("supermarket--oil--liquid")
        for price in (1_200_000, 1_000_000):
            sup = self.create_test_supplier()
            with self.db.write_transaction() as conn:
                offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"],
                              data={"product_id": self.m["product_id"], "selling_price_minor": price, "stock_quantity": 5,
                                    "supplier_location_id": sup["location_id"]})
                conn.execute("UPDATE suppliers SET provenance='real' WHERE id=?", (sup["supplier_id"],))
                conn.execute("UPDATE seller_offers SET provenance='real', pricing_mode='fixed', channel='retail', "
                             "last_price_confirmed_at=datetime('now'), last_inventory_confirmed_at=datetime('now') "
                             "WHERE supplier_id=?", (sup["supplier_id"],))

    def test_compare_sellers(self):
        r = self.client.get("/api/v1/vambi/search?q=روغن")
        self.assertEqual(r.status_code, 200, r.get_json())
        item = next(i for i in r.get_json()["items"] if i["summary"]["seller_count"] == 2)
        prices = [o["price_incl_vat_minor"] for o in item["offers"]]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(item["summary"]["min_price_minor"], prices[0])
        self.assertLess(item["summary"]["min_price_minor"], item["summary"]["max_price_minor"])
        self.assertEqual(self.client.get("/api/v1/vambi/search?sort=bogus").status_code, 422)

    @mock.patch.dict(os.environ, {"STOREFRONT_PRICE_VISIBILITY": "organizations"})
    def test_prices_hidden_for_outsiders(self):
        d = self.client.get("/api/v1/vambi/search?q=روغن").get_json()
        self.assertTrue(d["price_hidden"])
        for i in d["items"]:
            self.assertIsNone(i["summary"]["min_price_minor"])
            self.assertTrue(all(o["price_incl_vat_minor"] is None for o in i["offers"]))
        self.assertEqual(self.client.get("/api/v1/vambi/search?sort=price_asc").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/vambi/search", headers={"User-Agent": "TorobBot"}).status_code, 403)

    def _slug(self):
        r = self.client.get("/api/v1/vambi/search?q=روغن").get_json()
        return next(i["slug"] for i in r["items"] if i["summary"]["seller_count"] == 2)

    def test_product_page_lists_every_seller_cheapest_first(self):
        d = self.client.get(f"/api/v1/vambi/products/{self._slug()}").get_json()
        self.assertEqual(d["summary"]["seller_count"], 2)
        prices = [o["price_incl_vat_minor"] for o in d["offers"]]
        self.assertEqual(prices, sorted(prices))
        self.assertNotIn("cta", d)  # comparison only: no cart fields
        self.assertEqual(self.client.get("/api/v1/vambi/products/no-such-thing").status_code, 404)

    @mock.patch.dict(os.environ, {"STOREFRONT_PRICE_VISIBILITY": "organizations"})
    def test_product_page_hides_prices_and_order(self):
        with mock.patch.dict(os.environ, {"STOREFRONT_PRICE_VISIBILITY": "public"}):
            slug = self._slug()
        d = self.client.get(f"/api/v1/vambi/products/{slug}").get_json()
        self.assertTrue(d["price_hidden"])
        self.assertTrue(all(o["price_incl_vat_minor"] is None and not o["best"] for o in d["offers"]))
        self.assertEqual([o["seller"] for o in d["offers"]], sorted(o["seller"] for o in d["offers"]))
