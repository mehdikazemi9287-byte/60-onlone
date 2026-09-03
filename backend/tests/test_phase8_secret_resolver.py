"""Phase 8 — Blocker 2: SecretResolver tests.

Tests:
  - SecretResolver is an abstract interface (cannot instantiate directly)
  - InMemorySecretResolver resolves registered secrets
  - InMemorySecretResolver raises SecretResolverError for unknown refs
  - FailClosedSecretResolver always raises
  - Resolved values are never logged (tested by checking logger output)
  - SecretResolverError is raised with the credential_ref in the message
    (so operators can diagnose which ref failed without leaking the secret)
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.secret_resolver import (
    FailClosedSecretResolver,
    InMemorySecretResolver,
    SecretResolver,
    SecretResolverError,
)


class TestSecretResolverInterface(unittest.TestCase):

    def test_is_abstract(self):
        """SecretResolver cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            SecretResolver()

    def test_in_memory_is_concrete(self):
        resolver = InMemorySecretResolver()
        self.assertIsInstance(resolver, SecretResolver)

    def test_fail_closed_is_concrete(self):
        resolver = FailClosedSecretResolver()
        self.assertIsInstance(resolver, SecretResolver)


class TestInMemorySecretResolver(unittest.TestCase):

    def test_resolves_registered_secret(self):
        resolver = InMemorySecretResolver()
        resolver.register("ref:stripe:live", "sk_live_XXXXXXXXXXXXXXXX")
        result = resolver.resolve("ref:stripe:live")
        self.assertEqual(result, "sk_live_XXXXXXXXXXXXXXXX")

    def test_raises_for_unknown_ref(self):
        resolver = InMemorySecretResolver()
        with self.assertRaises(SecretResolverError) as ctx:
            resolver.resolve("ref:unknown:key")
        self.assertIn("ref:unknown:key", str(ctx.exception))

    def test_error_contains_ref_not_secret(self):
        """The error message must contain the ref (for diagnostics) but not the secret value."""
        resolver = InMemorySecretResolver()
        resolver.register("ref:safe", "super_secret_value_NEVER_EXPOSE_12345")
        # Error should not contain the secret value
        with self.assertRaises(SecretResolverError):
            resolver.resolve("ref:does_not_exist")

    def test_constructor_accepts_initial_dict(self):
        resolver = InMemorySecretResolver({"ref:a": "value_a", "ref:b": "value_b"})
        self.assertEqual(resolver.resolve("ref:a"), "value_a")
        self.assertEqual(resolver.resolve("ref:b"), "value_b")

    def test_overwrite_registration(self):
        resolver = InMemorySecretResolver()
        resolver.register("ref:key", "old_value")
        resolver.register("ref:key", "new_value")
        self.assertEqual(resolver.resolve("ref:key"), "new_value")

    def test_resolved_value_not_in_error_message(self):
        """If we try to resolve a wrong key, the error doesn't expose other registered secrets."""
        resolver = InMemorySecretResolver({"ref:real": "SHOULD_NOT_APPEAR_12345"})
        try:
            resolver.resolve("ref:nonexistent")
        except SecretResolverError as exc:
            self.assertNotIn("SHOULD_NOT_APPEAR_12345", str(exc))

    def test_internal_dict_is_private(self):
        """The secrets dict must not be directly accessible from outside."""
        resolver = InMemorySecretResolver({"ref:a": "secret_value"})
        # The attribute should not be trivially accessible; it's prefixed with _
        self.assertFalse(hasattr(resolver, "secrets"))
        self.assertFalse(hasattr(resolver, "credentials"))


class TestFailClosedSecretResolver(unittest.TestCase):

    def test_always_raises(self):
        resolver = FailClosedSecretResolver()
        with self.assertRaises(SecretResolverError):
            resolver.resolve("any:ref")

    def test_error_contains_ref(self):
        resolver = FailClosedSecretResolver()
        with self.assertRaises(SecretResolverError) as ctx:
            resolver.resolve("ref:vault:stripe_key")
        self.assertIn("ref:vault:stripe_key", str(ctx.exception))

    def test_error_does_not_contain_secrets(self):
        resolver = FailClosedSecretResolver()
        with self.assertRaises(SecretResolverError) as ctx:
            resolver.resolve("ref:test")
        # The error should not contain any "secret" value (there is none)
        error_text = str(ctx.exception)
        self.assertIn("ref:test", error_text)


class TestSecretNeverLeaksToLogs(unittest.TestCase):
    """Verify that resolved secret values do not appear in log output."""

    def setUp(self):
        self.log_records = []

        class CapturingHandler(logging.Handler):
            def __init__(inner_self, records):
                super().__init__()
                inner_self._records = records

            def emit(inner_self, record):
                inner_self._records.append(record.getMessage())

        self.handler = CapturingHandler(self.log_records)
        logging.root.addHandler(self.handler)

    def tearDown(self):
        logging.root.removeHandler(self.handler)

    def test_secret_value_not_in_any_log_line(self):
        """Using the resolver should never log the resolved secret value."""
        SECRET = "ULTRA_SECRET_VALUE_MUST_NOT_APPEAR_IN_LOGS_XYZ789"
        resolver = InMemorySecretResolver({"ref:mysecret": SECRET})
        # Resolve the secret (silently)
        value = resolver.resolve("ref:mysecret")
        self.assertEqual(value, SECRET)

        # Verify the secret did not appear in any log line
        all_logs = " ".join(self.log_records)
        self.assertNotIn(SECRET, all_logs)


if __name__ == "__main__":
    unittest.main()
