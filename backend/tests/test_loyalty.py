from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import loyalty_service  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class LoyaltyTestBase(AppTestCase):
    def _customer(self) -> tuple[int, dict]:
        """Registers a fresh customer, returns (user_id, auth_headers)."""
        email, password, response = self.register()
        self.assertEqual(response.status_code, 201, response.get_json())
        token = response.get_json()["access_token"]
        user_id = self.db.query_one(
            "SELECT id FROM users WHERE email_normalized = ?", (email.strip().lower(),)
        )["id"]
        return user_id, {"Authorization": f"Bearer {token}"}


class LoyaltyServiceTest(LoyaltyTestBase):
    """Direct service-level tests: ledger folding, isolation, append-only guard."""

    def setUp(self):
        super().setUp()
        self.user_id, self.headers = self._customer()

    def test_earn_increases_balance(self):
        result = loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=100, source="purchase",
        )
        self.assertEqual(result["balance_coins"], 100)
        self.assertEqual(result["entry"]["entry_type"], "earn")
        self.assertEqual(result["entry"]["amount_coins"], 100)

    def test_balance_folds_multiple_entries(self):
        loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=100, source="purchase")
        loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=50, source="campaign")
        result = loyalty_service.redeem(self.db, user_id=self.user_id, amount_coins=30)
        self.assertEqual(result["balance_coins"], 120)

    def test_redeem_rejects_insufficient_balance(self):
        loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=10, source="purchase")
        with self.assertRaises(Exception) as ctx:
            loyalty_service.redeem(self.db, user_id=self.user_id, amount_coins=50)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 409)

    def test_earn_is_idempotent(self):
        key = uuid.uuid4().hex
        first = loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=100, source="purchase", idempotency_key=key,
        )
        second = loyalty_service.earn(
            self.db, user_id=self.user_id, amount_coins=100, source="purchase", idempotency_key=key,
        )
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["entry"]["id"], second["entry"]["id"])
        self.assertEqual(second["balance_coins"], 100)  # not double-credited

    def test_redeem_is_idempotent(self):
        loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=100, source="purchase")
        key = uuid.uuid4().hex
        first = loyalty_service.redeem(self.db, user_id=self.user_id, amount_coins=40, idempotency_key=key)
        second = loyalty_service.redeem(self.db, user_id=self.user_id, amount_coins=40, idempotency_key=key)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(second["balance_coins"], 60)  # not double-debited

    def test_balance_isolated_per_user(self):
        other_id, _ = self._customer()
        loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=100, source="purchase")
        self.assertEqual(loyalty_service.wallet(self.db, user_id=other_id)["balance_coins"], 0)

    def test_zero_or_negative_amount_rejected(self):
        with self.assertRaises(Exception) as ctx:
            loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=0, source="purchase")
        self.assertEqual(getattr(ctx.exception, "status_code", None), 422)
        with self.assertRaises(Exception):
            loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=-5, source="purchase")

    def test_invalid_source_rejected(self):
        with self.assertRaises(Exception) as ctx:
            loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=10, source="not_a_real_source")
        self.assertEqual(getattr(ctx.exception, "status_code", None), 422)

    def test_ledger_is_append_only(self):
        result = loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=10, source="purchase")
        entry_id = result["entry"]["id"]
        with self.assertRaises(Exception):
            with self.db.write_transaction() as conn:
                conn.execute(
                    "UPDATE loyalty_ledger_entries SET amount_coins = 999 WHERE id = ?", (entry_id,)
                )

    def test_loyalty_ledger_never_touches_credit_ledger(self):
        loyalty_service.earn(self.db, user_id=self.user_id, amount_coins=500, source="purchase")
        rows = self.db.query("SELECT * FROM credit_ledger_entries WHERE user_id = ?", (self.user_id,))
        self.assertEqual(len(rows), 0)


class LoyaltyApiTest(LoyaltyTestBase):
    """HTTP-level tests: auth, isolation, endpoint wiring."""

    def setUp(self):
        super().setUp()
        self.user_id, self.headers = self._customer()

    def test_wallet_starts_at_zero(self):
        response = self.client.get("/api/v1/me/loyalty", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["balance_coins"], 0)

    def test_customer_cannot_self_grant_coins(self):
        response = self.client.post(
            "/api/v1/loyalty/earn", headers=self.headers,
            json={"user_id": self.user_id, "amount_coins": 1000, "source": "purchase"},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_grant_coins_and_customer_sees_balance(self):
        admin = self.admin_headers()
        grant = self.client.post(
            "/api/v1/loyalty/earn", headers=admin,
            json={"user_id": self.user_id, "amount_coins": 250, "source": "campaign"},
        )
        self.assertEqual(grant.status_code, 201, grant.get_json())

        wallet = self.client.get("/api/v1/me/loyalty", headers=self.headers)
        self.assertEqual(wallet.get_json()["balance_coins"], 250)

    def test_redeem_requires_auth(self):
        response = self.client.post("/api/v1/me/loyalty/redeem", json={"amount_coins": 10})
        self.assertEqual(response.status_code, 401)

    def test_redeem_more_than_balance_is_409(self):
        response = self.client.post(
            "/api/v1/me/loyalty/redeem", headers=self.headers, json={"amount_coins": 10},
        )
        self.assertEqual(response.status_code, 409)

    def test_transactions_list_paginates(self):
        admin = self.admin_headers()
        for _ in range(3):
            self.client.post(
                "/api/v1/loyalty/earn", headers=admin,
                json={"user_id": self.user_id, "amount_coins": 10, "source": "activity"},
            )
        response = self.client.get(
            "/api/v1/me/loyalty/transactions?page=1&page_size=2", headers=self.headers,
        )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["total"], 3)
