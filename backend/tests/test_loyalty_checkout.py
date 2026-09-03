"""60Coin earning wired into the real checkout flow.

Covers the checkout <-> loyalty_service.earn() integration added to
checkout_service.checkout(): earn only after a committed purchase, never for
a failed attempt, idempotent per order, isolated from the financial ledger,
and correct across cash / credit-only / split payment methods.

Rate under test: 1,000 Toman merchandise subtotal = 1 60Coin, i.e. 10,000 IRR
minor units per coin (currency_exponent=0, 1 Toman = 10 Rial). See
checkout_service.LOYALTY_EARN_MINOR_PER_COIN.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import checkout_service, ledger_service  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class LoyaltyCheckoutTest(AppTestCase):
    """Cart of one kettle: base_price_minor is repriced to a value that is an
    exact multiple of LOYALTY_EARN_MINOR_PER_COIN, so the expected coin count
    is exact rather than floor-approximate.
    """

    # 50,000,000 minor units / 10,000 per coin = 5,000 coins. No shipping fee
    # at this price (well above the free-shipping threshold used elsewhere in
    # the suite), so subtotal is the only variable feeding the coin count.
    PRICE_MINOR = 50_000_000
    EXPECTED_COINS = PRICE_MINOR // checkout_service.LOYALTY_EARN_MINOR_PER_COIN

    def setUp(self):
        super().setUp()
        self.token, self.headers = self.new_customer()
        self.kettle = self.product("appliance-kettle-2l")
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE products SET base_price_minor = ? WHERE id = ?",
                (self.PRICE_MINOR, self.kettle["id"]),
            )
        self.set_stock(self.kettle["id"], 50)

    def add(self, headers, quantity=1):
        return self.client.post(
            "/api/v1/cart/items",
            json={"product_id": self.kettle["id"], "quantity": quantity},
            headers=headers,
        )

    def wallet(self, headers) -> dict:
        return self.client.get("/api/v1/me/loyalty", headers=headers).get_json()

    # ------------------------------------------------------------- earning
    def test_successful_paid_purchase_earns_correct_coins(self):
        self.add(self.headers)
        order = self.checkout(self.headers).get_json()["order"]
        self.assertEqual(order["status"], "paid")

        wallet = self.wallet(self.headers)
        self.assertEqual(wallet["balance_coins"], self.EXPECTED_COINS)

        entry = wallet["recent_entries"][0]
        self.assertEqual(entry["source"], "purchase")
        self.assertEqual(entry["order_id"], order["id"])
        self.assertEqual(entry["amount_coins"], self.EXPECTED_COINS)

    def test_earning_is_based_on_subtotal_not_shipping_or_tax(self):
        self.add(self.headers)
        order = self.checkout(self.headers).get_json()["order"]
        self.assertGreater(order["total_minor"], order["subtotal_minor"])  # tax/shipping present
        expected = order["subtotal_minor"] // checkout_service.LOYALTY_EARN_MINOR_PER_COIN
        self.assertEqual(self.wallet(self.headers)["balance_coins"], expected)

    def test_purchase_below_minimum_threshold_earns_zero_deterministically(self):
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE products SET base_price_minor = 5000 WHERE id = ?", (self.kettle["id"],)
            )
        self.add(self.headers)
        order = self.checkout(self.headers).get_json()["order"]
        self.assertEqual(order["status"], "paid")
        self.assertEqual(self.wallet(self.headers)["balance_coins"], 0)
        self.assertEqual(
            self.db.query_one(
                "SELECT COUNT(*) n FROM loyalty_ledger_entries WHERE order_id = ?", (order["id"],)
            )["n"],
            0,
        )

    # --------------------------------------------------------------- failed
    def test_failed_checkout_earns_zero(self):
        """The mock PSP declines when total_minor % 100 == 13 (same trick as
        test_checkout.test_declined_payment_rolls_back_everything)."""
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE products SET base_price_minor = ? WHERE id = ?",
                (20_000_012, self.kettle["id"]),
            )
        self.add(self.headers)
        response = self.checkout(self.headers)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(self.wallet(self.headers)["balance_coins"], 0)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 0)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM loyalty_ledger_entries")["n"], 0
        )

    # ---------------------------------------------------------- idempotency
    def test_replayed_checkout_does_not_double_earn(self):
        self.add(self.headers)
        key = uuid.uuid4().hex
        first = self.checkout(self.headers, key=key)
        second = self.checkout(self.headers, key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            first.get_json()["order"]["order_number"], second.get_json()["order"]["order_number"]
        )
        self.assertEqual(self.wallet(self.headers)["balance_coins"], self.EXPECTED_COINS)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM loyalty_ledger_entries")["n"], 1
        )

    def test_replaying_earn_idempotency_key_directly_is_a_noop(self):
        """Simulates a retried loyalty grant (e.g. manual re-run after a
        transient failure) hitting the same deterministic key a second time —
        must not double-credit, matching loyalty_service's own guarantee."""
        from app.services import loyalty_service

        self.add(self.headers)
        order = self.checkout(self.headers).get_json()["order"]
        user_id = self.db.query_one(
            "SELECT user_id FROM orders WHERE id = ?", (order["id"],)
        )["user_id"]

        result = loyalty_service.earn(
            self.db, user_id=user_id, amount_coins=self.EXPECTED_COINS, source="purchase",
            order_id=order["id"], idempotency_key=f"purchase:{order['id']}",
        )
        self.assertFalse(result["created"])
        self.assertEqual(self.wallet(self.headers)["balance_coins"], self.EXPECTED_COINS)

    # --------------------------------------------------- payment methods
    def test_credit_only_successful_checkout_earns_normally(self):
        org, admin_headers, _, employee = self.org_fixture(credit_minor=200_000_000)
        self.add(employee["headers"])
        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertEqual(order["cash_minor"], 0)
        self.assertGreater(order["credit_minor"], 0)

        expected = order["subtotal_minor"] // checkout_service.LOYALTY_EARN_MINOR_PER_COIN
        self.assertEqual(self.wallet(employee["headers"])["balance_coins"], expected)

    def test_split_payment_earns_normally(self):
        org, admin_headers, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.add(employee["headers"])
        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertTrue(order["is_split_payment"])

        expected = order["subtotal_minor"] // checkout_service.LOYALTY_EARN_MINOR_PER_COIN
        self.assertEqual(self.wallet(employee["headers"])["balance_coins"], expected)

    # ------------------------------------------------------------ isolation
    def test_loyalty_failure_cannot_invalidate_a_paid_order(self):
        """A broken loyalty_service.earn() must not affect checkout's own
        success — checkout_service catches and logs, never propagates."""
        from app.services import loyalty_service as ls

        original_earn = ls.earn

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated loyalty outage")

        checkout_service.loyalty_service.earn = _boom
        try:
            self.add(self.headers)
            response = self.checkout(self.headers)
            self.assertEqual(response.status_code, 201)
            order = response.get_json()["order"]
            self.assertEqual(order["status"], "paid")
        finally:
            checkout_service.loyalty_service.earn = original_earn

        # No coins were awarded (the call failed), but the order stands.
        self.assertEqual(self.wallet(self.headers)["balance_coins"], 0)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 1
        )

    def test_financial_ledger_remains_isolated_from_loyalty_ledger(self):
        self.add(self.headers)
        order = self.checkout(self.headers).get_json()["order"]

        # 60Coin earning happened...
        self.assertGreater(self.wallet(self.headers)["balance_coins"], 0)

        # ...but the double-entry ledger is untouched by it: still balanced,
        # and no account in the trial balance carries coin units.
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)
        with self.db.read_transaction() as conn:
            legs = ledger_service.entries_for_reference(conn, f"order:{order['order_number']}")
        # The financial ledger total still equals the order total exactly,
        # unaffected by the coin count computed from the same subtotal.
        self.assertEqual(sum(l["amount_minor"] for l in legs if l["direction"] == "debit"),
                          order["total_minor"])
