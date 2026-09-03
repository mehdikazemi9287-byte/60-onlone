from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase  # noqa: E402


class CartTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.token, self.headers = self.new_customer()
        self.paper = self.product("office-paper-a4-carton")  # 14,500,000 / stock 120
        self.kettle = self.product("appliance-kettle-2l")    # 11,900,000 / stock 60

    def add(self, product_id: int, quantity: int):
        return self.client.post(
            "/api/v1/cart/items",
            json={"product_id": product_id, "quantity": quantity},
            headers=self.headers,
        )

    # -- auth ---------------------------------------------------------------
    def test_cart_requires_authentication(self):
        self.assertEqual(self.client.get("/api/v1/cart").status_code, 401)
        self.assertEqual(
            self.client.post("/api/v1/cart/items", json={"product_id": 1, "quantity": 1}).status_code,
            401,
        )

    # -- happy path ---------------------------------------------------------
    def test_new_cart_is_empty(self):
        body = self.client.get("/api/v1/cart", headers=self.headers).get_json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["subtotal_minor"], 0)
        self.assertEqual(body["shipping_fee_minor"], 0)
        self.assertEqual(body["total_minor"], 0)

    def test_add_item(self):
        response = self.add(self.paper["id"], 2)
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["quantity"], 2)
        self.assertEqual(body["subtotal_minor"], 29_000_000)

    def test_cart_includes_recovered_master_product_image(self):
        image_url = "https://cdn.example.test/products/paper.jpg"
        with self.db.write_transaction() as conn:
            master_id = conn.execute(
                "INSERT INTO master_products (public_product_id, canonical_name_fa, image_urls_json) VALUES (?,?,?)",
                ("cart-image-test", "کاغذ تست", f'["{image_url}"]'),
            ).lastrowid
            conn.execute(
                "UPDATE products SET master_product_id = ? WHERE id = ?",
                (master_id, self.paper["id"]),
            )

        body = self.add(self.paper["id"], 1).get_json()
        self.assertEqual(body["items"][0]["image_url"], image_url)

    def test_totals_are_exact_integers(self):
        self.add(self.paper["id"], 3)
        self.add(self.kettle["id"], 2)
        body = self.client.get("/api/v1/cart", headers=self.headers).get_json()
        expected = 14_500_000 * 3 + 11_900_000 * 2
        self.assertEqual(body["subtotal_minor"], expected)
        self.assertEqual(body["subtotal"], str(expected))
        self.assertEqual(body["item_count"], 5)

    def test_adding_the_same_product_accumulates(self):
        self.add(self.paper["id"], 2)
        body = self.add(self.paper["id"], 3).get_json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["quantity"], 5)

    def test_shipping_is_charged_below_the_threshold_and_free_above(self):
        self.add(self.kettle["id"], 1)  # 11,900,000 < 20,000,000
        body = self.client.get("/api/v1/cart", headers=self.headers).get_json()
        self.assertEqual(body["shipping_fee_minor"], 350_000)
        self.assertEqual(body["total_minor"], 11_900_000 + 350_000)

        self.add(self.kettle["id"], 1)  # 23,800,000 >= threshold
        body = self.client.get("/api/v1/cart", headers=self.headers).get_json()
        self.assertEqual(body["shipping_fee_minor"], 0)
        self.assertEqual(body["total_minor"], 23_800_000)

    def test_update_quantity(self):
        self.add(self.paper["id"], 2)
        response = self.client.patch(
            f"/api/v1/cart/items/{self.paper['id']}", json={"quantity": 7}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["quantity"], 7)

    def test_setting_quantity_to_zero_removes_the_line(self):
        self.add(self.paper["id"], 2)
        body = self.client.patch(
            f"/api/v1/cart/items/{self.paper['id']}", json={"quantity": 0}, headers=self.headers
        ).get_json()
        self.assertEqual(body["items"], [])

    def test_delete_item(self):
        self.add(self.paper["id"], 2)
        body = self.client.delete(
            f"/api/v1/cart/items/{self.paper['id']}", headers=self.headers
        ).get_json()
        self.assertEqual(body["items"], [])

    def test_clear_cart(self):
        self.add(self.paper["id"], 2)
        self.add(self.kettle["id"], 1)
        body = self.client.delete("/api/v1/cart", headers=self.headers).get_json()
        self.assertEqual(body["items"], [])

    # -- validation ---------------------------------------------------------
    def test_zero_or_negative_quantity_rejected_on_add(self):
        self.assertEqual(self.add(self.paper["id"], 0).status_code, 422)
        self.assertEqual(self.add(self.paper["id"], -3).status_code, 422)

    def test_non_integer_quantity_rejected(self):
        response = self.client.post(
            "/api/v1/cart/items",
            json={"product_id": self.paper["id"], "quantity": "2"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_product_rejected(self):
        self.assertEqual(self.add(999_999, 1).status_code, 404)

    def test_line_quantity_cap(self):
        response = self.add(self.paper["id"], 21)
        self.assertEqual(response.status_code, 422)

    def test_cannot_add_more_than_available_stock(self):
        low = self.product("laptop-hp-probook-450")  # stock 4
        response = self.add(low["id"], 5)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "out_of_stock")
        self.assertEqual(response.get_json()["error"]["details"]["available"], 4)

    def test_accumulated_quantity_also_respects_stock(self):
        low = self.product("laptop-hp-probook-450")  # stock 4
        self.assertEqual(self.add(low["id"], 3).status_code, 201)
        self.assertEqual(self.add(low["id"], 2).status_code, 409)

    def test_updating_a_line_not_in_the_cart_is_404(self):
        response = self.client.patch(
            f"/api/v1/cart/items/{self.paper['id']}", json={"quantity": 2}, headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    # -- isolation ----------------------------------------------------------
    def test_carts_are_isolated_between_users(self):
        self.add(self.paper["id"], 2)
        _, other_headers = self.new_customer()
        other = self.client.get("/api/v1/cart", headers=other_headers).get_json()
        self.assertEqual(other["items"], [])

    def test_price_comes_from_the_catalog_not_the_client(self):
        self.client.post(
            "/api/v1/cart/items",
            json={"product_id": self.paper["id"], "quantity": 1, "unit_price_minor": 1},
            headers=self.headers,
        )
        body = self.client.get("/api/v1/cart", headers=self.headers).get_json()
        self.assertEqual(body["items"][0]["unit_price_minor"], 14_500_000)

    def test_only_one_active_cart_per_user(self):
        self.add(self.paper["id"], 1)
        self.add(self.kettle["id"], 1)
        count = self.db.query_one("SELECT COUNT(*) n FROM carts WHERE status = 'active'")["n"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
