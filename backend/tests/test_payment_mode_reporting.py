"""Card-gateway mode is reported in /health and payment-options, and mock captures are
never available on a deployed (staging/production) app."""
from __future__ import annotations

import dataclasses
import unittest

from tests.base import AppTestCase
from app.adapters.logistics import registry as carrier_registry
from app.main import create_app
from app.services.checkout_service import card_payment_mode


class PaymentModeTest(AppTestCase):
    def tearDown(self):
        carrier_registry.configure("test", {})
        super().tearDown()

    def test_test_harness_reports_test_mode(self):
        body = self.client.get("/api/v1/health").get_json()
        self.assertEqual(body["payment"], {"card_provider": "mock", "card_mode": "test"})
        opts = self.client.get("/api/v1/checkout/payment-options").get_json()
        self.assertEqual(opts["card_payment_mode"], "test")
        self.assertEqual(opts["options"][0]["mode"], "test")

    def test_staging_app_reports_unavailable_and_never_simulates(self):
        app = create_app(dataclasses.replace(self.settings, app_env="staging"), self.db)
        client = app.test_client()
        body = client.get("/api/v1/health").get_json()
        self.assertEqual(body["environment"], "staging")
        self.assertEqual(body["payment"], {"card_provider": "mock", "card_mode": "unavailable"})
        self.assertFalse(body["mock_carrier"]["enabled"])
        self.assertEqual(client.get("/api/v1/checkout/payment-options").get_json()["card_payment_mode"], "unavailable")
        with app.app_context():
            self.assertEqual(card_payment_mode("mock"), "unavailable")
            self.assertEqual(card_payment_mode("sepehr"), "live")


if __name__ == "__main__":
    unittest.main()
