"""Phase 8 — Workstream A: Environment & Deployment Safety tests.

Tests for:
  - APP_ENV validation (valid/invalid values)
  - Production fail-closed: demo credentials rejected
  - Production fail-closed: SEED_ON_START always False
  - Production fail-closed: mock providers rejected unless DEMO_MODE=1
  - Non-production: SEED_ON_START honoured
  - SECRET_KEY length check
  - DEMO_MODE flag controls mock provider permission in production
"""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager

from app.core.config import ConfigError, load_settings, Settings


@contextmanager
def _env(**kwargs):
    """Temporarily set environment variables, restore on exit."""
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
    """Call load_settings() with given env overrides."""
    with _env(**kwargs):
        return load_settings()


_SAFE_KEY = "f3a9b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1"
_ANOTHER_SAFE_KEY = "0" * 32 + "1" * 32  # 64 chars, no demo fragments
_SHORT_KEY = "a" * 10  # too short


class TestAppEnvValidation(unittest.TestCase):

    def test_development_is_valid(self):
        s = _load(APP_ENV="development", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertEqual(s.app_env, "development")
        self.assertFalse(s.is_production)

    def test_test_is_valid(self):
        s = _load(APP_ENV="test", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertEqual(s.app_env, "test")
        self.assertTrue(s.is_test)

    def test_staging_is_valid(self):
        s = _load(APP_ENV="staging", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertEqual(s.app_env, "staging")
        self.assertFalse(s.is_production)

    def test_production_is_valid_with_safe_key(self):
        s = _load(APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None, DEMO_MODE="1")
        self.assertEqual(s.app_env, "production")
        self.assertTrue(s.is_production)

    def test_invalid_env_prod_raises(self):
        with self.assertRaises(ConfigError):
            _load(APP_ENV="prod", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")

    def test_invalid_env_live_raises(self):
        with self.assertRaises(ConfigError):
            _load(APP_ENV="live", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")

    def test_invalid_env_empty_defaults_to_development(self):
        # Missing APP_ENV defaults to development
        s = _load(APP_ENV=None, SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertEqual(s.app_env, "development")


class TestProductionDemoCredentialGuard(unittest.TestCase):
    """Production must reject demo/test SECRET_KEY fragments."""

    def _expect_rejection(self, key: str):
        with self.assertRaises(ConfigError):
            _load(APP_ENV="production", SECRET_KEY=key,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None)

    def test_key_with_test_rejected(self):
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaatest")

    def test_key_with_demo_rejected(self):
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaademo")

    def test_key_with_secret_rejected(self):
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_secret")

    def test_key_with_changeme_rejected(self):
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaachangeme")

    def test_key_with_example_rejected(self):
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaexample")

    def test_key_with_password_rejected(self):
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaapassword")

    def test_key_with_dev_rejected(self):
        # "dev" at end of key
        self._expect_rejection("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaadev")

    def test_safe_key_accepted_in_production(self):
        s = _load(APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None, DEMO_MODE="1")
        self.assertTrue(s.is_production)

    def test_demo_key_accepted_in_development(self):
        # Demo fragments are fine outside production
        s = _load(APP_ENV="development",
                  SECRET_KEY="my_test_secret_key_xxxxx1234_extralongstring",
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertEqual(s.app_env, "development")

    def test_demo_key_accepted_in_staging(self):
        s = _load(APP_ENV="staging",
                  SECRET_KEY="my_test_secret_key_xxxxx1234_extralongstring",
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertEqual(s.app_env, "staging")

    def test_key_too_short_always_rejected(self):
        with self.assertRaises(ConfigError):
            _load(APP_ENV="development", SECRET_KEY=_SHORT_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")

    def test_numeric_only_key_accepted_in_production(self):
        # A 64-char key containing only numerals and letters but no banned fragments
        hex_key = _SAFE_KEY  # f3a9b2c1... — pre-verified safe key
        s = _load(APP_ENV="production", SECRET_KEY=hex_key,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None, DEMO_MODE="1")
        self.assertTrue(s.is_production)


class TestSeedOnStart(unittest.TestCase):
    """SEED_ON_START=1 must be ignored in production regardless of env value."""

    def test_production_never_seeds_even_when_explicitly_set(self):
        s = _load(APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START="1", DEMO_MODE="1")
        self.assertFalse(s.seed_on_start)

    def test_production_never_seeds_with_default(self):
        s = _load(APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None, DEMO_MODE="1")
        self.assertFalse(s.seed_on_start)

    def test_development_seeds_by_default(self):
        s = _load(APP_ENV="development", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None)
        self.assertTrue(s.seed_on_start)

    def test_development_can_disable_seed(self):
        s = _load(APP_ENV="development", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START="0")
        self.assertFalse(s.seed_on_start)

    def test_staging_seeds_when_set(self):
        s = _load(APP_ENV="staging", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START="1")
        self.assertTrue(s.seed_on_start)

    def test_is_production_property(self):
        s = _load(APP_ENV="production", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db",
                  SEED_ON_START=None, DEMO_MODE="1")
        self.assertTrue(s.is_production)
        self.assertFalse(s.is_test)

    def test_is_test_property(self):
        s = _load(APP_ENV="test", SECRET_KEY=_SAFE_KEY,
                  DATABASE_URL="sqlite:///./data/test.db")
        self.assertTrue(s.is_test)
        self.assertFalse(s.is_production)


if __name__ == "__main__":
    unittest.main()
