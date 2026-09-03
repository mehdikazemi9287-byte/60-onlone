"""Phase 8 — Blocker 3: Exception and Log Redaction tests.

Tests:
  - redact() removes sensitive keys from dicts recursively
  - redact() handles nested dicts and lists
  - redact() is depth-limited (no infinite recursion)
  - All SENSITIVE_KEYS patterns are covered
  - safe_exception_message() never returns str(exc) directly
  - Readiness endpoint does not expose raw DB exceptions
  - Adapter exception containing known secret does not leak in response
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.redaction import SENSITIVE_KEYS, redact, safe_exception_message
from tests.base import AppTestCase


class TestRedactFunction(unittest.TestCase):

    def test_plain_dict_no_sensitive_keys(self):
        data = {"foo": "bar", "count": 42}
        result = redact(data)
        self.assertEqual(result, {"foo": "bar", "count": 42})

    def test_password_key_is_redacted(self):
        data = {"username": "alice", "password": "s3cret!"}
        result = redact(data)
        self.assertEqual(result["username"], "alice")
        self.assertNotEqual(result["password"], "s3cret!")
        self.assertIn("REDACTED", result["password"])

    def test_token_key_is_redacted(self):
        data = {"access_token": "eyJhbGci..."}
        result = redact(data)
        self.assertIn("REDACTED", result["access_token"])

    def test_authorization_key_is_redacted(self):
        data = {"Authorization": "Bearer eyJhbGci..."}
        result = redact(data)
        self.assertIn("REDACTED", result["Authorization"])

    def test_secret_key_is_redacted(self):
        data = {"client_secret": "super_secret_value"}
        result = redact(data)
        self.assertIn("REDACTED", result["client_secret"])

    def test_api_key_is_redacted(self):
        data = {"api_key": "api_key_12345", "apikey": "other_key"}
        result = redact(data)
        self.assertIn("REDACTED", result["api_key"])
        self.assertIn("REDACTED", result["apikey"])

    def test_private_key_is_redacted(self):
        data = {"private_key": "-----BEGIN RSA..."}
        result = redact(data)
        self.assertIn("REDACTED", result["private_key"])

    def test_bearer_token_in_value_not_affected(self):
        """Value-based scanning is NOT done (per spec); only key-name matching."""
        data = {"message": "Bearer eyJhbGci..."}
        result = redact(data)
        # 'message' is not a sensitive key; value is preserved
        self.assertEqual(result["message"], "Bearer eyJhbGci...")

    def test_recursive_nested_dict(self):
        # NOTE: "credentials" is itself a sensitive key and is redacted wholesale.
        # Use a neutral wrapper key to test deep-nested redaction of inner keys.
        data = {
            "user": {
                "email": "alice@example.com",
                "account_info": {
                    "password": "hunter2",
                    "token": "tok_123",
                }
            }
        }
        result = redact(data)
        self.assertEqual(result["user"]["email"], "alice@example.com")
        self.assertIn("REDACTED", result["user"]["account_info"]["password"])
        self.assertIn("REDACTED", result["user"]["account_info"]["token"])

    def test_credentials_key_is_redacted_wholesale(self):
        """The 'credentials' key itself is sensitive and the whole value is redacted."""
        data = {"user": {"credentials": {"password": "hunter2", "token": "tok"}}}
        result = redact(data)
        # credentials is a sensitive key, so its value is replaced with REDACTED
        self.assertIn("REDACTED", result["user"]["credentials"])

    def test_list_of_dicts(self):
        data = [{"token": "tok_a"}, {"name": "alice", "secret": "xyz"}]
        result = redact(data)
        self.assertIn("REDACTED", result[0]["token"])
        self.assertEqual(result[1]["name"], "alice")
        self.assertIn("REDACTED", result[1]["secret"])

    def test_case_insensitive_key_matching(self):
        data = {"PASSWORD": "p@ss", "TOKEN": "t0k"}
        result = redact(data)
        self.assertIn("REDACTED", result["PASSWORD"])
        self.assertIn("REDACTED", result["TOKEN"])

    def test_non_dict_passthrough(self):
        self.assertEqual(redact("hello"), "hello")
        self.assertEqual(redact(42), 42)
        self.assertIsNone(redact(None))

    def test_depth_limit_prevents_infinite_recursion(self):
        """Deep nesting beyond _MAX_DEPTH is handled without crashing."""
        # Build a 20-deep nested dict
        deep = {"value": "safe"}
        for _ in range(20):
            deep = {"nested": deep}
        result = redact(deep)
        # Should not raise; result is returned (some levels may be collapsed)
        self.assertIsNotNone(result)

    def test_all_sensitive_key_categories_covered(self):
        """Every entry in SENSITIVE_KEYS has at least one test."""
        for key in SENSITIVE_KEYS:
            data = {key: "sensitive_value"}
            result = redact(data)
            self.assertIn("REDACTED", result[key], f"Key {key!r} was not redacted")

    def test_cookie_key_redacted(self):
        data = {"cookie": "session=abc123", "set-cookie": "token=xyz"}
        result = redact(data)
        self.assertIn("REDACTED", result["cookie"])

    def test_credential_key_redacted(self):
        data = {"credential": "cred_val", "credentials": "cred_vals"}
        result = redact(data)
        self.assertIn("REDACTED", result["credential"])
        self.assertIn("REDACTED", result["credentials"])


class TestSafeExceptionMessage(unittest.TestCase):

    def test_returns_generic_message(self):
        exc = ValueError("SECRET_KEY=super_secret_key was invalid")
        msg = safe_exception_message(exc)
        self.assertNotIn("super_secret_key", msg)
        self.assertNotIn("SECRET_KEY", msg)
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_sql_error_does_not_leak(self):
        exc = Exception("SQLITE_BUSY: database is locked — path=/var/data/prod.db")
        msg = safe_exception_message(exc)
        self.assertNotIn("SQLITE_BUSY", msg)
        self.assertNotIn("/var/data/prod.db", msg)


class TestReadinessNeverExposesRawExceptions(AppTestCase):
    """Readiness endpoint must not expose raw exception text (Blocker 3 + 5)."""

    def test_readiness_200_does_not_expose_internals(self):
        resp = self.client.get("/api/v1/health/ready")
        self.assertIn(resp.status_code, (200, 503))
        body = resp.get_json()
        # Must not contain raw Python exception repr
        body_str = str(body)
        self.assertNotIn("Traceback", body_str)
        self.assertNotIn("sqlite3.", body_str)
        self.assertNotIn("Error:", body_str)

    def test_readiness_response_has_safe_reason_field(self):
        resp = self.client.get("/api/v1/health/ready")
        body = resp.get_json()
        if resp.status_code == 503:
            # 'reason' must be a simple code, not raw exception text
            reason = body.get("reason", "")
            self.assertNotIn("Exception", reason)
            self.assertNotIn("Traceback", reason)
            self.assertNotIn("sqlite3", reason)


class TestAdapterExceptionDoesNotLeakSecrets(unittest.TestCase):
    """Adapter exceptions containing secrets must not reach API responses (Blocker 3)."""

    def test_redacted_config_does_not_expose_api_key(self):
        """If a connector config contains api_key, redact() must remove it before logging."""
        from app.core.redaction import redact

        config_with_secret = {
            "connector_type": "REST_API",
            "api_key": "sk_live_SUPER_SECRET_12345",
            "endpoint": "https://api.example.com",
        }
        safe = redact(config_with_secret)
        self.assertEqual(safe["connector_type"], "REST_API")
        self.assertEqual(safe["endpoint"], "https://api.example.com")
        self.assertNotIn("sk_live_SUPER_SECRET_12345", str(safe))
        self.assertIn("REDACTED", safe["api_key"])

    def test_exception_containing_secret_does_not_propagate(self):
        """An exception that str()-contains a secret must be masked before responding."""
        SECRET = "REAL_PAYMENT_API_SECRET_KEY_1234567890"

        class LeakyException(Exception):
            pass

        try:
            raise LeakyException(f"Connection to PSP failed: key={SECRET}")
        except LeakyException as exc:
            msg = safe_exception_message(exc)
            self.assertNotIn(SECRET, msg)


if __name__ == "__main__":
    unittest.main()
