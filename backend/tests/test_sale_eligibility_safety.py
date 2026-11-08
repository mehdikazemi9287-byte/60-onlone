from tests.base import AppTestCase

class SaleEligibilitySafetyTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["TEST_SALES_OVERRIDE"] = False
        self.token, self.headers = self.new_customer()
        self.product_row = self.db.query_one("SELECT id, base_price_minor FROM products WHERE slug = ?", ("appliance-kettle-2l",))

    def test_catalog_suppresses_unconfirmed_price_inventory_and_reviews(self):
        p = self.client.get("/api/v1/products/appliance-kettle-2l").get_json()["product"]
        self.assertIsNone(p["price"])
        self.assertIsNone(p["price_minor"])
        self.assertIsNone(p["quantity_available"])
        self.assertIsNone(p["rating"])
        self.assertFalse(p["in_stock"])
        self.assertFalse(p["purchasable"])

    def test_direct_cart_add_is_rejected(self):
        r = self.client.post("/api/v1/cart/items", json={"product_id": self.product_row["id"], "quantity": 1}, headers=self.headers)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error"]["code"], "product_sale_unverified")

    def _insert_legacy_cart(self):
        user_id = self.db.query_one("SELECT id FROM users ORDER BY id DESC LIMIT 1")["id"]
        with self.db.write_transaction() as conn:
            cart_id = conn.execute("INSERT INTO carts (user_id,status) VALUES (?, 'active')", (user_id,)).lastrowid
            conn.execute("INSERT INTO cart_items (cart_id,product_id,quantity,unit_price_minor) VALUES (?,?,?,?)", (cart_id,self.product_row["id"],1,self.product_row["base_price_minor"]))

    def test_existing_cart_quote_and_checkout_are_rejected_without_order(self):
        self._insert_legacy_cart()
        before = self.db.query_one("SELECT COUNT(*) n FROM orders")["n"]
        quote = self.client.post("/api/v1/checkout/quote", headers=self.headers)
        self.assertEqual(quote.status_code, 409)
        self.assertEqual(quote.get_json()["error"]["code"], "product_sale_unverified")
        place = self.checkout(self.headers, key="unverified-existing-cart")
        self.assertEqual(place.status_code, 409)
        self.assertEqual(place.get_json()["error"]["code"], "product_sale_unverified")
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], before)
