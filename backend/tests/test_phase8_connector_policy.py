"""Phase 8 — Blocker 7: Implementation-Status Gates tests.

Tests:
  - check_delivery_allowed passes for production_verified in production
  - check_delivery_allowed passes for sandbox_verified in staging
  - check_delivery_allowed raises for not_implemented in any environment
  - check_delivery_allowed raises for mock/simulator in production
  - check_delivery_allowed raises for sandbox_verified in production
  - is_delivery_allowed returns bool without raising
  - Policy gate is enforced in outbox_worker dispatch path
  - mock/manual/stub adapters are blocked in production environment
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.connectors.policy import (
    ConnectorPolicyViolation,
    check_delivery_allowed,
    is_delivery_allowed,
)


class TestCheckDeliveryAllowed(unittest.TestCase):

    # ── production_verified ───────────────────────────────────────────────

    def test_production_verified_in_production(self):
        """production_verified connectors may deliver in production."""
        check_delivery_allowed("production_verified", "MY_ERP", app_env="production")  # no raise

    def test_production_verified_in_staging(self):
        check_delivery_allowed("production_verified", "MY_ERP", app_env="staging")  # no raise

    def test_production_verified_in_development(self):
        check_delivery_allowed("production_verified", "MY_ERP", app_env="development")  # no raise

    def test_production_alias_in_production(self):
        """'production' is an alias for 'production_verified' (used by MANUAL adapter)."""
        check_delivery_allowed("production", "MANUAL", app_env="production")  # no raise

    # ── sandbox_verified ──────────────────────────────────────────────────

    def test_sandbox_verified_in_staging(self):
        check_delivery_allowed("sandbox_verified", "MY_ERP", app_env="staging")  # no raise

    def test_sandbox_verified_in_development(self):
        check_delivery_allowed("sandbox_verified", "MY_ERP", app_env="development")  # no raise

    def test_sandbox_verified_blocked_in_production(self):
        """sandbox_verified must not deliver in production."""
        with self.assertRaises(ConnectorPolicyViolation) as ctx:
            check_delivery_allowed("sandbox_verified", "MY_ERP", app_env="production")
        self.assertIn("MY_ERP", str(ctx.exception))

    # ── simulator/mock ────────────────────────────────────────────────────

    def test_simulator_in_development(self):
        check_delivery_allowed("simulator", "MOCK_ERP", app_env="development")  # no raise

    def test_simulator_in_test(self):
        check_delivery_allowed("simulator", "MOCK_ERP", app_env="test")  # no raise

    def test_simulator_blocked_in_production(self):
        with self.assertRaises(ConnectorPolicyViolation):
            check_delivery_allowed("simulator", "MOCK_ERP", app_env="production")

    def test_simulator_blocked_in_staging(self):
        with self.assertRaises(ConnectorPolicyViolation):
            check_delivery_allowed("simulator", "MOCK_ERP", app_env="staging")

    def test_mock_blocked_in_production(self):
        with self.assertRaises(ConnectorPolicyViolation):
            check_delivery_allowed("mock", "MOCK_CONNECTOR", app_env="production")

    # ── not_implemented ───────────────────────────────────────────────────

    def test_not_implemented_blocked_everywhere(self):
        for env in ("development", "test", "staging", "production"):
            with self.assertRaises(ConnectorPolicyViolation, msg=f"Should raise for {env}"):
                check_delivery_allowed("not_implemented", "HOLO_ERP", app_env=env)

    def test_stub_blocked_in_production(self):
        with self.assertRaises(ConnectorPolicyViolation):
            check_delivery_allowed("stub", "STUB_CONN", app_env="production")

    def test_manual_blocked_in_production(self):
        """'manual' status (not the MANUAL adapter) must fail closed in production."""
        with self.assertRaises(ConnectorPolicyViolation):
            check_delivery_allowed("manual", "SOME_MANUAL", app_env="production")

    # ── error message quality ─────────────────────────────────────────────

    def test_error_message_contains_connector_type(self):
        with self.assertRaises(ConnectorPolicyViolation) as ctx:
            check_delivery_allowed("not_implemented", "HOLO_ERP", app_env="production")
        self.assertIn("HOLO_ERP", str(ctx.exception))

    def test_error_message_contains_env(self):
        with self.assertRaises(ConnectorPolicyViolation) as ctx:
            check_delivery_allowed("simulator", "MOCK_ERP", app_env="production")
        self.assertIn("production", str(ctx.exception))


class TestIsDeliveryAllowed(unittest.TestCase):

    def test_returns_true_when_allowed(self):
        result = is_delivery_allowed("production_verified", "MY_ERP", app_env="production")
        self.assertTrue(result)

    def test_returns_false_when_not_allowed(self):
        result = is_delivery_allowed("not_implemented", "HOLO_ERP", app_env="production")
        self.assertFalse(result)

    def test_no_exception_raised(self):
        """is_delivery_allowed must not raise — returns bool only."""
        result = is_delivery_allowed("simulator", "MOCK_ERP", app_env="production")
        self.assertIsInstance(result, bool)
        self.assertFalse(result)


class TestOutboxWorkerPolicyGate(unittest.TestCase):
    """The policy gate must be enforced in the outbox dispatch path."""

    def test_not_implemented_adapter_raises_in_dispatch(self):
        """Dispatching to a not_implemented adapter raises ConnectorPolicyViolation."""
        import os
        from unittest.mock import patch, MagicMock
        from app.services.outbox_worker import _dispatch_event

        event = {
            "id": 1,
            "event_type": "ORDER_CREATED",
            "connector_account_id": 99,
            "payload": {"order_id": "123"},
            "attempt_count": 1,
        }

        mock_adapter = MagicMock()
        mock_capabilities = MagicMock()
        mock_capabilities.implementation_status = "not_implemented"
        mock_adapter.capabilities.return_value = mock_capabilities

        def mock_query(sql, params=(), *, one=False):
            if one:
                return {"connector_type": "HOLO_ERP", "config_json": "{}"}
            return [{"connector_type": "HOLO_ERP", "config_json": "{}"}]

        with patch("app.services.outbox_worker.query", side_effect=mock_query):
            with patch("app.adapters.connectors.registry.get_adapter", return_value=mock_adapter):
                with patch.dict(os.environ, {"APP_ENV": "production"}):
                    with self.assertRaises(ConnectorPolicyViolation):
                        _dispatch_event(event)


if __name__ == "__main__":
    unittest.main()
