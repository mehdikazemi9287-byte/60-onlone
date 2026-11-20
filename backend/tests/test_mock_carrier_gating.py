"""The mock courier adapter is limited to test/development unless explicitly allowed,
and its inbound webhooks need a secret from the environment outside the test harness."""
from __future__ import annotations

import hashlib
import hmac
import unittest

from tests.base import AppTestCase
from app.adapters.logistics import registry
from app.adapters.logistics.base import WebhookVerificationError
from app.adapters.logistics.mock import MOCK_WEBHOOK_SECRET, MockCarrierAdapter

ENV_SECRET = "x" * 40


def _headers(body: bytes, secret: bytes) -> dict:
    return {
        "X-Mock-Signature": hmac.new(secret, body, hashlib.sha256).hexdigest(),
        "X-Mock-Event-Id": "evt-gate-1",
        "X-Mock-Shipment-Id": "MOCK-GATE",
        "X-Mock-Event-Type": "delivered",
    }


class RegistryGatingTest(unittest.TestCase):
    def tearDown(self):
        registry.configure("test", {})

    def test_staging_without_flag_has_no_mock(self):
        registry.configure("staging", {})
        self.assertNotIn("mock", registry.list_provider_codes())
        with self.assertRaises(ValueError):
            registry.get_carrier_adapter("mock")
        self.assertEqual(registry.mock_carrier_status(), {"enabled": False, "webhooks_enabled": False})

    def test_production_without_flag_has_no_mock(self):
        registry.configure("production", {"MOCK_CARRIER_WEBHOOK_SECRET": ENV_SECRET})
        self.assertNotIn("mock", registry.list_provider_codes())

    def test_production_flag_needs_demo_mode(self):
        registry.configure("production", {"ALLOW_MOCK_CARRIER": "1"})
        self.assertNotIn("mock", registry.list_provider_codes())
        registry.configure("production", {"ALLOW_MOCK_CARRIER": "1", "DEMO_MODE": "1"})
        self.assertIn("mock", registry.list_provider_codes())

    def test_staging_flag_without_secret_rejects_webhooks(self):
        registry.configure("staging", {"ALLOW_MOCK_CARRIER": "1"})
        adapter = registry.get_carrier_adapter("mock")
        body = b"{}"
        # Even a body signed with the test-harness secret is rejected outside APP_ENV=test.
        with self.assertRaises(WebhookVerificationError) as ctx:
            adapter.verify_webhook(_headers(body, MOCK_WEBHOOK_SECRET), body)
        self.assertEqual(ctx.exception.code, "webhook_disabled")
        self.assertEqual(registry.mock_carrier_status(), {"enabled": True, "webhooks_enabled": False})

    def test_development_has_no_default_secret(self):
        registry.configure("development", {})
        adapter = registry.get_carrier_adapter("mock")
        body = b"{}"
        with self.assertRaises(WebhookVerificationError) as ctx:
            adapter.verify_webhook(_headers(body, MOCK_WEBHOOK_SECRET), body)
        self.assertEqual(ctx.exception.code, "webhook_disabled")

    def test_short_env_secret_is_ignored(self):
        registry.configure("staging", {"ALLOW_MOCK_CARRIER": "1", "MOCK_CARRIER_WEBHOOK_SECRET": "short"})
        self.assertFalse(registry.mock_carrier_status()["webhooks_enabled"])

    def test_env_secret_is_used_and_test_secret_is_not(self):
        registry.configure("staging", {"ALLOW_MOCK_CARRIER": "1", "MOCK_CARRIER_WEBHOOK_SECRET": ENV_SECRET})
        adapter = registry.get_carrier_adapter("mock")
        body = b"{}"
        event = adapter.verify_webhook(_headers(body, ENV_SECRET.encode()), body)
        self.assertEqual(event.new_status, "delivered")
        with self.assertRaises(WebhookVerificationError) as ctx:
            adapter.verify_webhook(_headers(body, MOCK_WEBHOOK_SECRET), body)
        self.assertEqual(ctx.exception.code, "invalid_signature")

    def test_adapter_without_secret_fails_closed(self):
        body = b"{}"
        with self.assertRaises(WebhookVerificationError) as ctx:
            MockCarrierAdapter().verify_webhook(_headers(body, MOCK_WEBHOOK_SECRET), body)
        self.assertEqual(ctx.exception.code, "webhook_disabled")


class StagingWebhookEndpointTest(AppTestCase):
    """A real app booted with APP_ENV=staging refuses mock carrier webhooks."""

    def setUp(self):
        super().setUp()
        import dataclasses
        from app.main import create_app
        self.staging_app = create_app(dataclasses.replace(self.settings, app_env="staging"), self.db)
        self.staging_client = self.staging_app.test_client()

    def tearDown(self):
        registry.configure("test", {})
        super().tearDown()

    def test_mock_webhook_rejected_as_unknown_provider(self):
        self.assertFalse(registry.mock_carrier_status()["enabled"])
        body = b'{"x":1}'
        before = self.db.query_one("SELECT COUNT(*) AS n FROM webhook_events")["n"]
        resp = self.staging_client.post("/api/v1/webhooks/carrier/mock", data=body, content_type="application/json",
                                        headers=_headers(body, MOCK_WEBHOOK_SECRET))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"outcome": "rejected", "reason": "unknown_provider"})
        after = self.db.query_one("SELECT COUNT(*) AS n FROM webhook_events")["n"]
        self.assertEqual(before, after)


class CreateAppConfiguresRegistryTest(AppTestCase):
    def test_test_env_app_enables_mock_with_harness_secret(self):
        self.assertEqual(registry.mock_carrier_status(), {"enabled": True, "webhooks_enabled": True})


if __name__ == "__main__":
    unittest.main()
