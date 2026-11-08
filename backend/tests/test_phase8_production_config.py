"""Phase 8 — Blocker 12: Production Configuration tests.

Tests:
  - PAYMENT_PROVIDER=mock is rejected in production without DEMO_MODE
  - CREDIT_PROVIDER=mock is rejected in production without DEMO_MODE
  - DEMO_MODE=1 allows mock providers in production (with explicit opt-in)
  - demo_mode is False by default
  - demo_mode is accessible as Settings attribute
  - PAYMENT_PROVIDER=mock works in non-production environments
  - Error message tells operator to set DEMO_MODE=1 or use a real provider
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import ConfigError, load_settings

_SAFE_KEY = "f3a9b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1"


@contextmanager
def _env(**kwargs):
    original = {k: os.environ.get(k) for k in kwargs}
    try:
        for k, v in kwargs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _load(**kwargs):
    with _env(**kwargs):
        return load_settings()


class TestMockProviderProductionGuard(unittest.TestCase):

    def test_mock_payment_provider_rejected_in_production(self):
        """PAYMENT_PROVIDER=mock must be rejected in production without DEMO_MODE."""
        with self.assertRaises(ConfigError) as ctx:
            _load(
                APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                DATABASE_URL="sqlite:///./data/test.db",
                PAYMENT_PROVIDER="mock",
                CREDIT_PROVIDER="real_provider",
                DEMO_MODE=None,
            )
        error_msg = str(ctx.exception)
        self.assertIn("PAYMENT_PROVIDER", error_msg)
        self.assertIn("mock", error_msg.lower())

    def test_mock_credit_provider_rejected_in_production(self):
        """CREDIT_PROVIDER=mock must be rejected in production without DEMO_MODE."""
        with self.assertRaises(ConfigError) as ctx:
            _load(
                APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                DATABASE_URL="sqlite:///./data/test.db",
                PAYMENT_PROVIDER="real_provider",
                CREDIT_PROVIDER="mock",
                DEMO_MODE=None,
            )
        error_msg = str(ctx.exception)
        self.assertIn("CREDIT_PROVIDER", error_msg)

    def test_demo_mode_allows_mock_in_production(self):
        """DEMO_MODE=1 explicitly allows mock providers in production."""
        s = _load(
            APP_ENV="production", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            PAYMENT_PROVIDER="mock",
            CREDIT_PROVIDER="mock",
            DEMO_MODE="1",
            SEED_ON_START=None,
        )
        self.assertTrue(s.is_production)
        self.assertTrue(s.demo_mode)
        self.assertEqual(s.payment_provider, "mock")
        self.assertEqual(s.credit_provider, "mock")

    def test_error_message_mentions_demo_mode(self):
        """The error must tell operators about DEMO_MODE=1 as the escape hatch."""
        with self.assertRaises(ConfigError) as ctx:
            _load(
                APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                DATABASE_URL="sqlite:///./data/test.db",
                PAYMENT_PROVIDER="mock",
                DEMO_MODE=None,
            )
        self.assertIn("DEMO_MODE", str(ctx.exception))

    def test_mock_payment_allowed_in_development(self):
        """mock providers are fine in non-production environments."""
        s = _load(
            APP_ENV="development", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            PAYMENT_PROVIDER="mock",
            CREDIT_PROVIDER="mock",
        )
        self.assertEqual(s.payment_provider, "mock")
        self.assertFalse(s.is_production)

    def test_mock_payment_allowed_in_staging(self):
        """mock providers are fine in staging."""
        s = _load(
            APP_ENV="staging", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            PAYMENT_PROVIDER="mock",
            CREDIT_PROVIDER="mock",
        )
        self.assertEqual(s.payment_provider, "mock")

    def test_mock_payment_allowed_in_test(self):
        """mock providers are fine in test."""
        s = _load(
            APP_ENV="test", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            PAYMENT_PROVIDER="mock",
            CREDIT_PROVIDER="mock",
        )
        self.assertEqual(s.payment_provider, "mock")

    def test_demo_mode_false_by_default(self):
        """Without DEMO_MODE env var, demo_mode is False."""
        s = _load(
            APP_ENV="development", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            DEMO_MODE=None,
        )
        self.assertFalse(s.demo_mode)

    def test_demo_mode_true_when_set(self):
        s = _load(
            APP_ENV="development", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            DEMO_MODE="1",
        )
        self.assertTrue(s.demo_mode)

    def test_demo_mode_attribute_on_settings(self):
        """Settings.demo_mode is a boolean attribute."""
        s = _load(
            APP_ENV="development", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
        )
        self.assertIsInstance(s.demo_mode, bool)

    def test_real_provider_accepted_in_production_without_demo_mode(self):
        """When real providers are configured, production does not require DEMO_MODE."""
        s = _load(
            APP_ENV="production", SECRET_KEY=_SAFE_KEY,
            DATABASE_URL="sqlite:///./data/test.db",
            PAYMENT_PROVIDER="sepehr",
            SEPEHR_TERMINAL_ID="98765432",
            PUBLIC_BASE_URL="https://60online.ir",
            CREDIT_PROVIDER="internal",
            DEMO_MODE=None,
            SEED_ON_START=None,
        )
        self.assertTrue(s.is_production)
        self.assertFalse(s.demo_mode)


if __name__ == "__main__":
    unittest.main()
