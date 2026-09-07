from tests.base import AppTestCase
from app.services.master_catalog_service import create_master_product


class CatalogPublicationsTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.before = self.client.get("/api/v1/products").get_json()["total"]
        self.ids = []
        with self.db.write_transaction() as conn:
            for i in range(3):
                master = create_master_product(
                    conn, canonical_name_fa="هویت آزمایشی " + str(i), category="office"
                )
                self.ids.append(master["id"])
                conn.execute(
                    "INSERT INTO catalog_publications(master_product_id,slug,category_slug,currency,is_visible,is_purchasable,price_status,publication_reason,created_at,updated_at) VALUES (?,?,?,'IRR',1,0,'pending','unit_test',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    (master["id"], "unit-publication-" + str(i), "office"),
                )
            conn.execute(
                "UPDATE products SET master_product_id=? WHERE id=(SELECT MIN(id) FROM products)",
                (self.ids[0],),
            )

    def test_duplicate_master_excluded_and_all_pages_reachable(self):
        rows = []
        first = self.client.get("/api/v1/products?page_size=3").get_json()
        self.assertEqual(first["total"], self.before + 2)
        for page in range(1, first["total_pages"] + 1):
            response = self.client.get("/api/v1/products?page_size=3&page=" + str(page))
            self.assertEqual(response.status_code, 200)
            rows.extend(response.get_json()["items"])
        self.assertEqual(len(rows), first["total"])
        self.assertEqual(len(set(p["slug"] for p in rows)), len(rows))
        self.assertEqual(sum(p["master_product_id"] == self.ids[0] for p in rows), 1)
        self.assertTrue(all(p["price_minor"] is None and not p["purchasable"] for p in rows))

    def test_category_counts_and_sort_with_null_prices(self):
        categories = self.client.get("/api/v1/categories").get_json()["items"]
        self.assertEqual(sum(c["product_count"] for c in categories), self.before + 2)
        for sort in ("price_asc", "price_desc", "rating"):
            response = self.client.get("/api/v1/products?category=office&sort=" + sort)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertTrue(
                all(p["category_slug"] == "office" for p in response.get_json()["items"])
            )
