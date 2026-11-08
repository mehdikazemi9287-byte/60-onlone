"""External credit (Tara pattern): checkout → provider page → callback → verify exact amount → order."""
from __future__ import annotations

import dataclasses

from app.adapters.payment import registry as payment_registry
from app.adapters.payment.external_credit import ExternalCreditProvider, enabled_from_env
from app.adapters.payment.sepehr import to_rial
from app.main import create_app
from tests.base import AppTestCase


class FakeLender:
    def __init__(self):
        self.calls, self.approved, self.paid = [], True, None

    def __call__(self, url, body, headers):
        self.calls.append((url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1], body, headers))
        if url.endswith("purchase/init"):
            self.paid = body["amount"]
            return {"token": "tara-tok", "redirect_url": "https://lender.test/pay/tara-tok"}
        if url.endswith("purchase/verify"):
            return {"status": "approved" if self.approved else "declined", "amount": self.paid, "reference": "TR-1"}
        if url.endswith("purchase/cancel"):
            return {"ok": True}
        return {"ok": True}


class ExternalCreditCheckoutTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.settings = dataclasses.replace(self.settings, public_base_url="https://60online.test")
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()
        self.lender = FakeLender()
        payment_registry.register(ExternalCreditProvider("tara", api_base="https://lender.test/api", merchant_id="M1",
                                                         api_key="k", transport=self.lender))
        self.app.extensions["external_credit_providers"] = ["tara"]
        _, self.headers = self.new_customer()
        kettle = self.product("appliance-kettle-2l")
        self.assertEqual(self.add_to_cart(self.headers, kettle["id"], 1).status_code, 201)

    def tearDown(self):
        payment_registry.reset_for_tests()
        super().tearDown()

    def _start(self, provider="tara", key="x-1"):
        return self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS, "payment_provider": provider},
                                headers={**self.headers, "Idempotency-Key": key})

    def _orders(self):
        with self.db.read_transaction() as conn:
            return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def test_options_and_happy_path(self):
        opts = self.client.get("/api/v1/checkout/payment-options").get_json()["options"]
        self.assertIn("tara", [o["provider"] for o in opts])
        r = self._start()
        self.assertEqual(r.status_code, 202, r.get_json())
        body = r.get_json()
        self.assertEqual(body["payment_redirect"]["url"], "https://lender.test/pay/tara-tok")
        init = self.lender.calls[0][1]
        self.assertEqual(init["amount"], to_rial(body["cash_due_minor"], body["currency"]))
        self.assertEqual(init["callback_url"], "https://60online.test/api/v1/payments/tara/callback")
        self.assertEqual(self._orders(), 0)
        cb = self.client.post("/api/v1/payments/tara/callback",
                              data={"invoice_id": str(body["payment_intent_id"]), "token": "tara-tok"})
        self.assertEqual(cb.status_code, 303)
        self.assertEqual(self._orders(), 1)
        self.client.post("/api/v1/payments/tara/callback", data={"invoice_id": str(body["payment_intent_id"]), "token": "tara-tok"})
        self.assertEqual(self._orders(), 1)  # replay-safe

    def test_amount_mismatch_or_decline_creates_no_order(self):
        body = self._start().get_json()
        self.lender.paid = self.lender.paid - 1000  # lender reports a different amount
        self.client.post("/api/v1/payments/tara/callback", data={"invoice_id": str(body["payment_intent_id"]), "token": "tara-tok"})
        self.assertEqual(self._orders(), 0)
        self.assertIn("purchase/cancel", [c[0] for c in self.lender.calls])  # money given back

    def test_disabled_provider_refused_and_cross_provider_callback_ignored(self):
        r = self._start(provider="digipay")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "payment_provider_unavailable")
        body = self._start(key="x-2").get_json()
        # A callback arriving on another provider's route must not complete this intent.
        self.client.post("/api/v1/payments/mock/callback", data={"invoice_id": str(body["payment_intent_id"])})
        self.assertEqual(self._orders(), 0)

    def test_enabled_from_env_needs_all_credentials_and_https(self):
        env = {"EXTERNAL_CREDIT_PROVIDERS": "tara,digipay,unknown", "TARA_API_BASE": "https://t", "TARA_MERCHANT_ID": "m",
               "TARA_API_KEY": "k", "DIGIPAY_API_BASE": "http://insecure", "DIGIPAY_MERCHANT_ID": "m", "DIGIPAY_API_KEY": "k"}
        self.assertEqual([p.name for p in enabled_from_env(env)], ["tara"])
