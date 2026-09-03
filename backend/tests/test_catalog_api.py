from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.migrator import discover  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class CatalogTest(AppTestCase):
    def test_health(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "ok")
        # Pinned to the migration head rather than a literal, so adding a
        # migration does not require editing a Flow 1 test.
        self.assertEqual(body["schema_version"], discover()[-1][0])

    def test_categories_are_public_and_seeded(self):
        response = self.client.get("/api/v1/categories")
        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        self.assertEqual(len(items), 5)
        self.assertIn("laptop", [c["slug"] for c in items])
        self.assertTrue(all(c["product_count"] >= 0 for c in items))

    def test_product_listing_is_public_and_paginated(self):
        response = self.client.get("/api/v1/products?page=1&page_size=5")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(len(body["items"]), 5)
        self.assertEqual(body["total"], 14)
        self.assertEqual(body["total_pages"], 3)

    def test_second_page_returns_different_products(self):
        first = self.client.get("/api/v1/products?page=1&page_size=5").get_json()["items"]
        second = self.client.get("/api/v1/products?page=2&page_size=5").get_json()["items"]
        self.assertEqual(set(), {p["id"] for p in first} & {p["id"] for p in second})

    def test_prices_are_strings_not_json_floats(self):
        item = self.client.get("/api/v1/products").get_json()["items"][0]
        self.assertIsInstance(item["price"], str)
        self.assertIsInstance(item["price_minor"], int)
        self.assertNotIn(".", item["price"])

    def test_search_by_persian_title(self):
        body = self.client.get("/api/v1/products?q=لپ‌تاپ").get_json()
        self.assertGreaterEqual(body["total"], 3)
        self.assertTrue(all("لپ‌تاپ" in p["title_fa"] for p in body["items"]))

    def test_search_by_brand(self):
        body = self.client.get("/api/v1/products?q=سامسونگ").get_json()
        self.assertEqual(body["total"], 2)

    def test_search_by_sku(self):
        body = self.client.get("/api/v1/products?q=LP-ASUS-VB15").get_json()
        self.assertEqual(body["total"], 1)

    def test_search_with_no_hits(self):
        body = self.client.get("/api/v1/products?q=zzzzznotfound").get_json()
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["items"], [])

    def test_like_wildcards_are_escaped(self):
        """A literal % must not match everything."""
        body = self.client.get("/api/v1/products?q=%").get_json()
        self.assertEqual(body["total"], 0)

    def test_filter_by_category(self):
        body = self.client.get("/api/v1/products?category=mobile").get_json()
        self.assertEqual(body["total"], 3)
        self.assertTrue(all(p["category_slug"] == "mobile" for p in body["items"]))

    def test_sort_by_price_ascending(self):
        items = self.client.get("/api/v1/products?sort=price_asc&page_size=48").get_json()["items"]
        prices = [p["price_minor"] for p in items]
        self.assertEqual(prices, sorted(prices))

    def test_sort_by_price_descending(self):
        items = self.client.get("/api/v1/products?sort=price_desc&page_size=48").get_json()["items"]
        prices = [p["price_minor"] for p in items]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_invalid_sort_rejected(self):
        response = self.client.get("/api/v1/products?sort=drop_table")
        self.assertEqual(response.status_code, 422)

    def test_invalid_pagination_rejected(self):
        self.assertEqual(self.client.get("/api/v1/products?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/products?page_size=999").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/products?page=abc").status_code, 422)

    def test_product_detail(self):
        product = self.product("laptop-asus-vivobook-15")
        self.assertEqual(product["sku"], "LP-ASUS-VB15")
        self.assertEqual(product["price"], "289000000")
        self.assertTrue(product["in_stock"])
        self.assertIn("description_fa", product)

    def test_product_detail_404(self):
        response = self.client.get("/api/v1/products/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "product_not_found")

    def test_inactive_product_is_hidden(self):
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET is_active = 0 WHERE slug = 'mobile-samsung-a55'")
        self.assertEqual(self.client.get("/api/v1/products/mobile-samsung-a55").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/products").get_json()["total"], 13)

    def test_out_of_stock_flag(self):
        product = self.product("mobile-samsung-a55")
        self.set_stock(product["id"], 0)
        self.assertFalse(self.product("mobile-samsung-a55")["in_stock"])

    def test_unknown_route_returns_json_404(self):
        response = self.client.get("/api/v1/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "not_found")

    # -------------------------------------------------- real image wiring
    def test_product_with_no_master_link_has_null_image_url(self):
        product = self.product("laptop-asus-vivobook-15")
        self.assertIsNone(product.get("image_url"))
        self.assertIn("image_emoji", product)

    def test_product_image_url_resolves_from_linked_master_product(self):
        product = self.product("laptop-asus-vivobook-15")
        with self.db.write_transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO master_products (public_product_id, canonical_name_fa, category, image_urls_json)
                VALUES ('test-uuid-image', 'تست تصویر', 'laptop', '["https://example.com/real.jpg"]')""",
            )
            master_id = cursor.lastrowid
            conn.execute(
                "UPDATE products SET master_product_id = ? WHERE id = ?",
                (master_id, product["id"]),
            )
        linked = self.client.get(f"/api/v1/products/{product['slug']}").get_json()["product"]
        self.assertEqual(linked["image_url"], "https://example.com/real.jpg")

    def test_product_image_url_null_when_master_has_no_images(self):
        product = self.product("laptop-asus-vivobook-15")
        with self.db.write_transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO master_products (public_product_id, canonical_name_fa, category, image_urls_json)
                VALUES ('test-uuid-noimg', 'تست بدون تصویر', 'laptop', '[]')""",
            )
            master_id = cursor.lastrowid
            conn.execute(
                "UPDATE products SET master_product_id = ? WHERE id = ?",
                (master_id, product["id"]),
            )
        linked = self.client.get(f"/api/v1/products/{product['slug']}").get_json()["product"]
        self.assertIsNone(linked["image_url"])

    def test_listing_also_carries_real_image_url(self):
        product = self.product("laptop-asus-vivobook-15")
        with self.db.write_transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO master_products (public_product_id, canonical_name_fa, category, image_urls_json)
                VALUES ('test-uuid-listing', 'تست فهرست', 'laptop', '["https://example.com/list.jpg"]')""",
            )
            master_id = cursor.lastrowid
            conn.execute(
                "UPDATE products SET master_product_id = ? WHERE id = ?",
                (master_id, product["id"]),
            )
        listing = self.client.get("/api/v1/products?sort=newest&page_size=48").get_json()
        item = next(i for i in listing["items"] if i["id"] == product["id"])
        self.assertEqual(item["image_url"], "https://example.com/list.jpg")


if __name__ == "__main__":
    unittest.main()
