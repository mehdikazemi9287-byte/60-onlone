"""60Coin checkout-time redemption, 60Club tiers, and coin expiration.

Extends the existing, already-passing loyalty/checkout suites — nothing
here replaces or duplicates test_loyalty.py / test_loyalty_checkout.py.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import loyalty_service  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class RedeemCheckoutTest(AppTestCase):
    """Real product, real checkout, redeem_coins as a request parameter."""

    def setUp(self):
        super().setUp()
        self.token, self.headers = self.new_customer()
        self.kettle = self.product("appliance-kettle-2l")
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE products SET base_price_minor = 50000000 WHERE id = ?",
                (self.kettle["id"],),
            )
        self.set_stock(self.kettle["id"], 50)

    def add(self, quantity=1):
        return self.client.post(
            "/api/v1/cart/items",
            json={"product_id": self.kettle["id"], "quantity": quantity},
            headers=self.headers,
        )

    def grant_coins(self, amount):
        loyalty_service.earn(
            self.db, user_id=self._user_id(), amount_coins=amount, source="campaign",
            idempotency_key=uuid.uuid4().hex,
        )

    def _user_id(self):
        return self.db.query_one("SELECT id FROM users ORDER BY id DESC LIMIT 1")["id"]

    def checkout_with_redeem(self, redeem_coins, key=None):
        return self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": self.DEFAULT_ADDRESS, "redeem_coins": redeem_coins},
            headers={**self.headers, "Idempotency-Key": key or uuid.uuid4().hex},
        )

    # -------------------------------------------------------------- happy
    def test_redeem_reduces_total_and_debits_ledger_exactly_once(self):
        self.grant_coins(1000)  # 1000 coins = 10,000,000 minor discount
        self.add()
        response = self.checkout_with_redeem(500)
        self.assertEqual(response.status_code, 201, response.get_json())
        order = response.get_json()["order"]
        self.assertEqual(order["redeem_coins"], 500)
        self.assertEqual(order["redeem_discount_minor"], 5_000_000)
        # subtotal 50,000,000 - discount 5,000,000 = 45,000,000 taxable base
        self.assertEqual(order["subtotal_minor"], 45_000_000)
        self.assertEqual(order["tax_minor"], 4_500_000)  # 10% of discounted base
        self.assertEqual(order["total_minor"], 45_000_000 + 4_500_000)

        wallet = self.client.get("/api/v1/me/loyalty", headers=self.headers).get_json()
        # earned on the discounted subtotal (45,000,000 // 10,000 = 4500),
        # minus the 500 redeemed, plus the 1000 campaign grant already there
        self.assertEqual(wallet["balance_coins"], 1000 - 500 + 4500)

    def test_redeem_zero_is_a_plain_checkout(self):
        self.add()
        response = self.checkout_with_redeem(0)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["order"]["redeem_coins"], 0)

    # ------------------------------------------------------------- guards
    def test_redeem_more_than_balance_is_rejected(self):
        self.grant_coins(10)
        self.add()
        response = self.checkout_with_redeem(999)
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(response.get_json()["error"]["code"], "conflict")
        # no coins were touched
        wallet = self.client.get("/api/v1/me/loyalty", headers=self.headers).get_json()
        self.assertEqual(wallet["balance_coins"], 10)
        # and no order was created
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 0)

    def test_redeem_above_the_50pct_cap_is_rejected(self):
        # subtotal 50,000,000 -> cap is 50% = 25,000,000 minor -> 2500 coins
        self.grant_coins(100_000)
        self.add()
        response = self.checkout_with_redeem(2501)
        self.assertEqual(response.status_code, 422, response.get_json())

    def test_redeem_at_exactly_the_cap_succeeds(self):
        self.grant_coins(100_000)
        self.add()
        response = self.checkout_with_redeem(2500)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["order"]["redeem_discount_minor"], 25_000_000)

    # -------------------------------------------------------- idempotency
    def test_replayed_checkout_does_not_double_redeem(self):
        self.grant_coins(1000)
        self.add()
        key = uuid.uuid4().hex
        first = self.checkout_with_redeem(500, key=key)
        second = self.checkout_with_redeem(500, key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            first.get_json()["order"]["order_number"], second.get_json()["order"]["order_number"]
        )
        redeem_entries = self.db.query(
            "SELECT * FROM loyalty_ledger_entries WHERE entry_type = 'redeem'"
        )
        self.assertEqual(len(redeem_entries), 1)

    # -------------------------------------------------------------- quote
    def test_quote_reflects_redemption(self):
        self.grant_coins(1000)
        self.add()
        response = self.client.get(
            "/api/v1/checkout/quote?redeem_coins=500", headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        quote = response.get_json()
        self.assertEqual(quote["redeem_coins"], 500)
        self.assertEqual(quote["redeem_discount_minor"], 5_000_000)
        self.assertEqual(quote["cart"]["subtotal_minor"], 45_000_000)


class TierTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.token, self.headers = self.new_customer()
        email = self.db.query_one(
            "SELECT email_normalized FROM users ORDER BY id DESC LIMIT 1"
        )["email_normalized"]
        self.user_id = self.db.query_one(
            "SELECT id FROM users WHERE email_normalized = ?", (email,)
        )["id"]

    def test_zero_coins_is_the_base_tier(self):
        wallet = self.client.get("/api/v1/me/loyalty", headers=self.headers).get_json()
        self.assertEqual(wallet["tier"]["code"], "member")
        self.assertEqual(wallet["tier"]["lifetime_coins"], 0)
        self.assertEqual(wallet["tier"]["next_tier"]["code"], "silver")
        self.assertEqual(wallet["tier"]["coins_to_next_tier"], 500)

    def test_crossing_a_threshold_upgrades_the_tier(self):
        loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=500, source="campaign",
            idempotency_key=uuid.uuid4().hex,
        )
        wallet = self.client.get("/api/v1/me/loyalty", headers=self.headers).get_json()
        self.assertEqual(wallet["tier"]["code"], "silver")

    def test_redeeming_does_not_downgrade_tier(self):
        """Tier is based on LIFETIME earned, not current balance."""
        loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=500, source="campaign",
            idempotency_key=uuid.uuid4().hex,
        )
        loyalty_service.redeem(self.db, user_id=self.user_id, amount_coins=400)
        wallet = self.client.get("/api/v1/me/loyalty", headers=self.headers).get_json()
        self.assertEqual(wallet["balance_coins"], 100)
        self.assertEqual(wallet["tier"]["code"], "silver")

    def test_tiers_endpoint_lists_configured_thresholds(self):
        response = self.client.get("/api/v1/loyalty/tiers", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        codes = [t["code"] for t in response.get_json()["items"]]
        self.assertEqual(codes, ["member", "silver", "gold"])


class ExpirationTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.token, self.headers = self.new_customer()
        email = self.db.query_one(
            "SELECT email_normalized FROM users ORDER BY id DESC LIMIT 1"
        )["email_normalized"]
        self.user_id = self.db.query_one(
            "SELECT id FROM users WHERE email_normalized = ?", (email,)
        )["id"]

    def _past(self, days):
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def _future(self, days):
        return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def test_expired_coins_are_debited_with_an_expire_entry(self):
        loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=300, source="purchase",
            idempotency_key=uuid.uuid4().hex, expires_at=self._past(1),
        )
        result = loyalty_service.expire_due_coins(self.db, user_id=self.user_id)
        self.assertTrue(result["created"])
        self.assertEqual(result["expired_coins"], 300)
        self.assertEqual(result["balance_coins"], 0)
        entry = self.db.query_one(
            "SELECT * FROM loyalty_ledger_entries WHERE entry_type = 'expire'"
        )
        self.assertEqual(entry["amount_coins"], -300)

    def test_not_yet_due_coins_are_untouched(self):
        loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=300, source="purchase",
            idempotency_key=uuid.uuid4().hex, expires_at=self._future(30),
        )
        result = loyalty_service.expire_due_coins(self.db, user_id=self.user_id)
        self.assertFalse(result["created"])
        self.assertEqual(result["balance_coins"], 300)

    def test_never_expires_more_than_the_current_balance(self):
        """Already-redeemed coins are never double-subtracted by expiry."""
        loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=300, source="purchase",
            idempotency_key=uuid.uuid4().hex, expires_at=self._past(1),
        )
        loyalty_service.redeem(self.db, user_id=self.user_id, amount_coins=250)
        result = loyalty_service.expire_due_coins(self.db, user_id=self.user_id)
        self.assertEqual(result["expired_coins"], 50)
        self.assertEqual(result["balance_coins"], 0)

    def test_running_expiry_twice_the_same_day_does_not_double_expire(self):
        loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=300, source="purchase",
            idempotency_key=uuid.uuid4().hex, expires_at=self._past(1),
        )
        first = loyalty_service.expire_due_coins(self.db, user_id=self.user_id)
        second = loyalty_service.expire_due_coins(self.db, user_id=self.user_id)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(second["balance_coins"], 0)

    def test_purchase_earn_gets_a_real_expiry_stamp(self):
        """checkout_service._award_purchase_coins sets expires_at automatically."""
        _, headers = self.new_customer()
        kettle = self.product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)
        self.client.post(
            "/api/v1/cart/items", json={"product_id": kettle["id"], "quantity": 1},
            headers=headers,
        )
        response = self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": self.DEFAULT_ADDRESS},
            headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        entry = self.db.query_one(
            "SELECT * FROM loyalty_ledger_entries WHERE entry_type='earn' AND source='purchase' "
            "ORDER BY id DESC LIMIT 1"
        )
        self.assertIsNotNone(entry["expires_at"])
