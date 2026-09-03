from __future__ import annotations

import sys
import threading
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import ApiError, OutOfStockError  # noqa: E402
from app.services import checkout_service, ledger_service  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class CheckoutTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.token, self.headers = self.new_customer()
        self.kettle = self.product("appliance-kettle-2l")  # 11,900,000 / stock 60

    def add(self, product_id: int, quantity: int, headers=None):
        return self.client.post(
            "/api/v1/cart/items",
            json={"product_id": product_id, "quantity": quantity},
            headers=headers or self.headers,
        )

    # ---------------------------------------------------------------- happy
    def test_end_to_end_customer_flow(self):
        """Register -> Login -> Browse -> Product -> Cart -> Checkout -> Order."""
        email, password, register = self.register("e2e@example.com")
        self.assertEqual(register.status_code, 201)

        token = self.login(email, password)
        headers = {"Authorization": f"Bearer {token}"}

        listing = self.client.get("/api/v1/products?category=appliance").get_json()
        self.assertGreater(listing["total"], 0)

        product = self.client.get(
            f"/api/v1/products/{listing['items'][0]['slug']}"
        ).get_json()["product"]

        self.assertEqual(self.add(product["id"], 2, headers).status_code, 201)

        cart = self.client.get("/api/v1/cart", headers=headers).get_json()
        self.assertEqual(cart["item_count"], 2)

        response = self.checkout(headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        order = response.get_json()["order"]
        self.assertEqual(order["status"], "paid")
        self.assertTrue(order["order_number"].startswith("ORD-"))
        # total_minor is now VAT-inclusive: subtotal + shipping + tax
        self.assertEqual(
            order["total_minor"],
            order["subtotal_minor"] + order["shipping_fee_minor"] + order["tax_minor"],
        )
        self.assertEqual(order["payment"]["status"], "captured")

        orders = self.client.get("/api/v1/orders", headers=headers).get_json()
        self.assertEqual(orders["total"], 1)
        self.assertEqual(orders["items"][0]["order_number"], order["order_number"])

        detail = self.client.get(
            f"/api/v1/orders/{order['order_number']}", headers=headers
        ).get_json()["order"]
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(detail["items"][0]["quantity"], 2)

    def test_stock_is_decremented_by_the_order(self):
        before = self.product("appliance-kettle-2l")["quantity_available"]
        self.add(self.kettle["id"], 3)
        self.assertEqual(self.checkout(self.headers).status_code, 201)
        after = self.product("appliance-kettle-2l")["quantity_available"]
        self.assertEqual(after, before - 3)

    def test_cart_is_emptied_after_checkout(self):
        self.add(self.kettle["id"], 1)
        self.checkout(self.headers)
        cart = self.client.get("/api/v1/cart", headers=self.headers).get_json()
        self.assertEqual(cart["items"], [])

    def test_order_items_snapshot_the_price(self):
        self.add(self.kettle["id"], 1)
        order = self.checkout(self.headers).get_json()["order"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = 1 WHERE id = ?", (self.kettle["id"],))
        detail = self.client.get(
            f"/api/v1/orders/{order['order_number']}", headers=self.headers
        ).get_json()["order"]
        self.assertEqual(detail["items"][0]["unit_price_minor"], 11_900_000)

    # --------------------------------------------------------- idempotency
    def test_replaying_the_idempotency_key_returns_the_same_order(self):
        self.add(self.kettle["id"], 1)
        key = uuid.uuid4().hex
        first = self.checkout(self.headers, key=key)
        second = self.checkout(self.headers, key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            first.get_json()["order"]["order_number"], second.get_json()["order"]["order_number"]
        )
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 1)

    def test_replay_does_not_double_charge_or_double_decrement(self):
        before = self.product("appliance-kettle-2l")["quantity_available"]
        self.add(self.kettle["id"], 2)
        key = uuid.uuid4().hex
        self.checkout(self.headers, key=key)
        self.checkout(self.headers, key=key)
        self.assertEqual(self.product("appliance-kettle-2l")["quantity_available"], before - 2)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM payments")["n"], 1)
        with self.db.read_transaction() as conn:
            debits, credits = ledger_service.trial_balance(conn)
        self.assertEqual(debits, credits)
        # 2 kettles × 11,900,000 = 23,800,000 subtotal + 0 shipping + 2,380,000 VAT (10%)
        self.assertEqual(debits, 26_180_000)

    def test_same_key_with_a_different_body_is_a_conflict(self):
        self.add(self.kettle["id"], 1)
        key = uuid.uuid4().hex
        self.checkout(self.headers, key=key)
        other_address = {**self.DEFAULT_ADDRESS, "city": "شیراز"}
        response = self.checkout(self.headers, key=key, address=other_address)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "idempotency_key_reuse")

    def test_missing_idempotency_key_is_rejected(self):
        self.add(self.kettle["id"], 1)
        response = self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": self.DEFAULT_ADDRESS},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "idempotency_key_required")

    def test_the_same_key_from_a_different_user_is_independent(self):
        self.add(self.kettle["id"], 1)
        key = "shared-key"
        self.assertEqual(self.checkout(self.headers, key=key).status_code, 201)
        _, other = self.new_customer()
        self.add(self.kettle["id"], 1, other)
        self.assertEqual(self.checkout(other, key=key).status_code, 201)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 2)

    # ------------------------------------------------------------- ledger
    def test_checkout_posts_a_balanced_double_entry_transaction(self):
        self.add(self.kettle["id"], 1)  # 11,900,000 + 350,000 shipping
        order = self.checkout(self.headers).get_json()["order"]
        with self.db.read_transaction() as conn:
            entries = ledger_service.entries_for_reference(conn, f"order:{order['order_number']}")
            debits, credits = ledger_service.trial_balance(conn)
        self.assertEqual(debits, credits)
        self.assertEqual(debits, order["total_minor"])
        self.assertEqual(len(entries), 4)  # PSP debit + sales credit + shipping credit + VAT payable credit
        by_direction = {e["direction"] for e in entries}
        self.assertEqual(by_direction, {"debit", "credit"})

    def test_ledger_has_no_shipping_entry_when_shipping_is_free(self):
        self.add(self.kettle["id"], 2)  # over the free-shipping threshold
        order = self.checkout(self.headers).get_json()["order"]
        self.assertEqual(order["shipping_fee_minor"], 0)
        with self.db.read_transaction() as conn:
            entries = ledger_service.entries_for_reference(conn, f"order:{order['order_number']}")
        self.assertEqual(len(entries), 3)  # PSP debit + sales credit + VAT payable credit (no shipping entry)

    def test_psp_account_balance_matches_the_sum_of_orders(self):
        self.add(self.kettle["id"], 1)
        first = self.checkout(self.headers).get_json()["order"]
        _, other = self.new_customer()
        self.add(self.kettle["id"], 3, other)
        second = self.checkout(other).get_json()["order"]
        with self.db.read_transaction() as conn:
            balance = ledger_service.account_balance_minor(conn, ledger_service.ACCOUNT_PSP_CLEARING)
        self.assertEqual(balance, first["total_minor"] + second["total_minor"])

    # ------------------------------------------------------------ failures
    def test_empty_cart_cannot_be_checked_out(self):
        response = self.checkout(self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "cart_empty")

    def test_incomplete_address_is_rejected(self):
        self.add(self.kettle["id"], 1)
        response = self.checkout(self.headers, address={"recipient_name": "الف"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("city", response.get_json()["error"]["details"])

    def test_declined_payment_rolls_back_everything(self):
        """The mock PSP declines when total_minor % 100 == 13.

        Price chosen so that: price + tax(10%) + shipping(350,000) ends in ...13.
        price=20_000_012 → tax=2_000_001 → total=22_350_013 → %100==13 ✓
        """
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE products SET base_price_minor = ? WHERE id = ?",
                (20_000_012, self.kettle["id"]),
            )
        before_stock = self.product("appliance-kettle-2l")["quantity_available"]
        self.add(self.kettle["id"], 1)
        response = self.checkout(self.headers)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.get_json()["error"]["code"], "payment_failed")

        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 0)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM payments")["n"], 0)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM ledger_entries")["n"], 0)
        self.assertEqual(self.product("appliance-kettle-2l")["quantity_available"], before_stock)
        # the cart survives so the customer can retry
        self.assertEqual(
            self.client.get("/api/v1/cart", headers=self.headers).get_json()["item_count"], 1
        )

    def test_checkout_requires_authentication(self):
        response = self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": self.DEFAULT_ADDRESS},
            headers={"Idempotency-Key": "x"},
        )
        self.assertEqual(response.status_code, 401)

    def test_stock_removed_after_the_item_entered_the_cart(self):
        self.add(self.kettle["id"], 5)
        self.set_stock(self.kettle["id"], 2)
        response = self.checkout(self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "out_of_stock")
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 0)

    def test_partial_stock_failure_rolls_back_earlier_decrements(self):
        paper = self.product("office-paper-a4-carton")
        self.add(paper["id"], 2)
        self.add(self.kettle["id"], 2)
        self.set_stock(self.kettle["id"], 1)  # second line will fail
        paper_before = self.product("office-paper-a4-carton")["quantity_available"]
        self.assertEqual(self.checkout(self.headers).status_code, 409)
        self.assertEqual(
            self.product("office-paper-a4-carton")["quantity_available"], paper_before
        )

    # ------------------------------------------------------------ ownership
    def test_a_user_cannot_read_another_users_order(self):
        self.add(self.kettle["id"], 1)
        order = self.checkout(self.headers).get_json()["order"]
        _, other = self.new_customer()
        response = self.client.get(f"/api/v1/orders/{order['order_number']}", headers=other)
        self.assertEqual(response.status_code, 404)

    def test_order_list_only_shows_your_own_orders(self):
        self.add(self.kettle["id"], 1)
        self.checkout(self.headers)
        _, other = self.new_customer()
        self.assertEqual(
            self.client.get("/api/v1/orders", headers=other).get_json()["total"], 0
        )

    # ---------------------------------------------------------------- audit
    def test_order_placement_is_audited(self):
        self.add(self.kettle["id"], 1)
        order = self.checkout(self.headers).get_json()["order"]
        row = self.db.query_one(
            "SELECT metadata_json FROM audit_logs WHERE action = 'order.placed'"
        )
        self.assertIsNotNone(row)
        self.assertIn(order["order_number"], row["metadata_json"])


class CheckoutRaceConditionTest(AppTestCase):
    """Two buyers, one unit left. Exactly one order must exist afterwards."""

    def test_concurrent_checkout_of_the_last_unit(self):
        product = self.product("appliance-kettle-2l")
        self.set_stock(product["id"], 1)

        buyers = []
        for _ in range(2):
            _, headers = self.new_customer()
            self.client.post(
                "/api/v1/cart/items",
                json={"product_id": product["id"], "quantity": 1},
                headers=headers,
            )
            token = headers["Authorization"].split()[1]
            user = self.db.query_one(
                "SELECT id, email FROM users ORDER BY id DESC LIMIT 1"
            )
            buyers.append((int(user["id"]), user["email"]))

        results: list[object] = []
        barrier = threading.Barrier(len(buyers))

        def attempt(user_id: int, email: str) -> None:
            barrier.wait()
            try:
                status, body = checkout_service.checkout(
                    self.db,
                    user_id=user_id,
                    user_email=email,
                    address=self.DEFAULT_ADDRESS,
                    idempotency_key=uuid.uuid4().hex,
                    payment_provider_name="mock",
                )
                results.append(status)
            except ApiError as exc:
                results.append(exc)
            finally:
                self.db.close()

        threads = [threading.Thread(target=attempt, args=b) for b in buyers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = [r for r in results if r == 201]
        failures = [r for r in results if isinstance(r, OutOfStockError)]
        self.assertEqual(len(successes), 1, f"expected exactly one winner, got {results}")
        self.assertEqual(len(failures), 1, f"expected exactly one loser, got {results}")

        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 1)
        stock = self.db.query_one(
            "SELECT quantity_available q FROM inventory WHERE product_id = ?", (product["id"],)
        )["q"]
        self.assertEqual(stock, 0)
        with self.db.read_transaction() as conn:
            debits, credits = ledger_service.trial_balance(conn)
        self.assertEqual(debits, credits)


if __name__ == "__main__":
    unittest.main()
