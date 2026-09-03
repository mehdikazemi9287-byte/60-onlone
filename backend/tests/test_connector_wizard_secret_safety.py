"""Connector Wizard — Secret Sanitization Safety Tests.

Tests that the recursive, case-insensitive secret sanitizer in
connector_wizard.py correctly removes secrets at ALL nesting levels and
from ALL API surfaces, while preserving allowed configuration and non-secret
values.

Requirement coverage (numbered per spec):
  1.  Nested api_key is not stored.
  2.  Nested client_secret is not stored.
  3.  Nested secrets inside lists are removed.
  4.  Uppercase API_KEY is removed.
  5.  CamelCase ApiKey is removed.
  6.  token_value is removed.
  7.  access_token and refresh_token are removed.
  8.  private_key and webhook_secret are removed.
  9.  Allowed non-secret nested configuration survives unchanged.
  10. credential_ref survives unchanged.
  11. Secrets do not appear in step_data_json.
  12. Secrets do not appear in connector_accounts.config_json.
  13. Secrets do not appear in GET session responses.
  14. Secrets do not appear in completion responses (config_json).
  15. Secrets do not appear in health-check responses.
  16. Invalid non-object config produces controlled 422.
  17. Excessive nesting produces controlled 422.
  18. Sanitization does not mutate the original input object.
  19. Existing top-level secret tests continue to pass.
  20. Connector registry and ownership security tests continue to pass.

Marker values used in assertions (chosen to be clearly non-real):
  NESTED_SECRET   — nested api_key value
  CASE_SECRET     — uppercase API_KEY value
  DEEP_SECRET     — deeply-nested client_secret value
  TOKEN_SECRET    — token_value value
  LIST_SECRET     — secret inside a list element
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase

_SESSION_URL = "/api/v1/connector-wizard/sessions"


def _supplier_headers(case: AppTestCase) -> tuple[dict, int]:
    """Returns (auth_headers, supplier_id)."""
    info = case.create_test_supplier()
    return info["headers"], info["supplier_id"]


def _create_session(case: AppTestCase, headers: dict,
                    connector_type: str = "MANUAL",
                    config: dict | None = None) -> str:
    """Create a wizard session and return the session_token."""
    body: dict = {"connector_type": connector_type}
    if config is not None:
        body["config"] = config
    resp = case.client.post(_SESSION_URL, json=body, headers=headers)
    assert resp.status_code == 201, f"Session creation failed: {resp.get_json()}"
    return resp.get_json()["session_token"]


def _complete_session(case: AppTestCase, token: str, headers: dict,
                      config: dict | None = None) -> dict:
    body: dict = {"name": "اتصال امنیتی آزمایشی"}
    if config is not None:
        body["config"] = config
    resp = case.client.post(f"{_SESSION_URL}/{token}/complete",
                             json=body, headers=headers)
    return resp


def _read_step_data_json(case: AppTestCase, token: str) -> str:
    """Read the raw step_data_json from the DB for a given session token."""
    with case.db.read_transaction() as conn:
        row = conn.execute(
            "SELECT step_data_json FROM connector_wizard_sessions WHERE session_token=?",
            (token,),
        ).fetchone()
    return row["step_data_json"] if row else ""


def _read_config_json(case: AppTestCase, connector_account_id: int) -> str:
    """Read the raw config_json from connector_accounts."""
    with case.db.read_transaction() as conn:
        row = conn.execute(
            "SELECT config_json FROM connector_accounts WHERE id=?",
            (connector_account_id,),
        ).fetchone()
    return row["config_json"] if row else ""


class TestSanitizerUnit(AppTestCase):
    """Unit tests for _sanitize_config and _normalise_key in isolation."""

    def _sanitize(self, value):
        from app.api.v1.connector_wizard import _sanitize_config
        return _sanitize_config(value)

    def _normalise(self, key):
        from app.api.v1.connector_wizard import _normalise_key
        return _normalise_key(key)

    # ── Key normalisation ─────────────────────────────────────────────────────

    def test_normalise_uppercase(self):
        self.assertEqual(self._normalise("API_KEY"), "api_key")

    def test_normalise_camelcase(self):
        self.assertEqual(self._normalise("ApiKey"), "api_key")

    def test_normalise_hyphen(self):
        self.assertEqual(self._normalise("client-secret"), "client_secret")

    def test_normalise_pascal_camel(self):
        self.assertEqual(self._normalise("ClientSecret"), "client_secret")

    def test_normalise_already_lower(self):
        self.assertEqual(self._normalise("password"), "password")

    # ── Req 4: Uppercase API_KEY ──────────────────────────────────────────────

    def test_uppercase_api_key_removed(self):
        result = self._sanitize({"API_KEY": "CASE_SECRET", "host": "example.com"})
        self.assertNotIn("API_KEY", result)
        self.assertNotIn("CASE_SECRET", str(result))
        self.assertEqual(result.get("host"), "example.com")

    # ── Req 5: CamelCase ApiKey ───────────────────────────────────────────────

    def test_camelcase_api_key_removed(self):
        result = self._sanitize({"ApiKey": "CASE_SECRET_2", "endpoint": "https://api.example.com"})
        self.assertNotIn("ApiKey", result)
        self.assertNotIn("CASE_SECRET_2", str(result))

    # ── Req 6: token_value ────────────────────────────────────────────────────

    def test_token_value_removed(self):
        result = self._sanitize({"token_value": "TOKEN_SECRET", "user": "admin"})
        self.assertNotIn("token_value", result)
        self.assertNotIn("TOKEN_SECRET", str(result))

    # ── Req 7: access_token and refresh_token ─────────────────────────────────

    def test_access_token_removed(self):
        result = self._sanitize({"access_token": "ACCESS_SECRET", "scope": "read"})
        self.assertNotIn("access_token", result)
        self.assertNotIn("ACCESS_SECRET", str(result))

    def test_refresh_token_removed(self):
        result = self._sanitize({"refresh_token": "REFRESH_SECRET", "scope": "read"})
        self.assertNotIn("refresh_token", result)
        self.assertNotIn("REFRESH_SECRET", str(result))

    # ── Req 8: private_key and webhook_secret ─────────────────────────────────

    def test_private_key_removed(self):
        result = self._sanitize({"private_key": "PK_SECRET", "key_id": "kid-1"})
        self.assertNotIn("private_key", result)
        self.assertNotIn("PK_SECRET", str(result))

    def test_webhook_secret_removed(self):
        result = self._sanitize({"webhook_secret": "WH_SECRET", "url": "https://hook.example.com"})
        self.assertNotIn("webhook_secret", result)
        self.assertNotIn("WH_SECRET", str(result))

    # ── Req 1: Nested api_key ─────────────────────────────────────────────────

    def test_nested_api_key_removed(self):
        result = self._sanitize({
            "credentials": {"api_key": "NESTED_SECRET"},
            "host": "db.example.com",
        })
        self.assertNotIn("NESTED_SECRET", json.dumps(result),
                         "NESTED_SECRET must not survive nested sanitization")
        self.assertEqual(result.get("host"), "db.example.com")

    # ── Req 2: Nested client_secret ───────────────────────────────────────────

    def test_nested_client_secret_removed(self):
        result = self._sanitize({
            "oauth": {"client_id": "my-client", "client_secret": "DEEP_SECRET"},
        })
        self.assertNotIn("DEEP_SECRET", json.dumps(result),
                         "DEEP_SECRET must not survive nested sanitization")
        oauth = result.get("oauth", {})
        self.assertEqual(oauth.get("client_id"), "my-client",
                         "Non-secret nested value must be preserved")

    # ── Req 3: Secrets inside lists ───────────────────────────────────────────

    def test_secrets_inside_lists_removed(self):
        result = self._sanitize({
            "endpoints": [
                {"url": "https://a.example.com", "api_key": "LIST_SECRET"},
                {"url": "https://b.example.com", "token": "LIST_TOKEN"},
            ]
        })
        serialised = json.dumps(result)
        self.assertNotIn("LIST_SECRET", serialised,
                         "LIST_SECRET must be removed from list element")
        self.assertNotIn("LIST_TOKEN", serialised,
                         "LIST_TOKEN must be removed from list element")
        # URL values must survive
        self.assertIn("https://a.example.com", serialised)
        self.assertIn("https://b.example.com", serialised)

    # ── Req 9: Allowed non-secret nested config survives ──────────────────────

    def test_allowed_nested_config_survives(self):
        payload = {
            "host": "db.example.com",
            "port": 5432,
            "database": "orders",
            "ssl": {"enabled": True, "cert_path": "/etc/ssl/cert.pem"},
            "retry": {"max_attempts": 3, "backoff_ms": 500},
        }
        result = self._sanitize(payload)
        self.assertEqual(result["host"], "db.example.com")
        self.assertEqual(result["port"], 5432)
        self.assertEqual(result["database"], "orders")
        self.assertEqual(result["ssl"]["enabled"], True)
        self.assertEqual(result["ssl"]["cert_path"], "/etc/ssl/cert.pem")
        self.assertEqual(result["retry"]["max_attempts"], 3)

    # ── Req 10: credential_ref survives ───────────────────────────────────────

    def test_credential_ref_survives(self):
        result = self._sanitize({
            "credential_ref": "vault:secret/path/to/cred",
            "host": "api.example.com",
        })
        self.assertIn("credential_ref", result,
                      "credential_ref must NOT be removed — it is a safe reference key")
        self.assertEqual(result["credential_ref"], "vault:secret/path/to/cred")

    def test_credential_ref_survives_nested(self):
        result = self._sanitize({
            "auth": {"credential_ref": "vault:secret/nested", "scheme": "Bearer"},
        })
        auth = result.get("auth", {})
        self.assertIn("credential_ref", auth,
                      "Nested credential_ref must survive sanitization")

    # ── Req 17: Excessive nesting → ValidationError ───────────────────────────

    def test_excessive_nesting_raises_validation_error(self):
        from app.core.errors import ValidationError as VE
        # Build a deeply-nested dict that exceeds _MAX_CONFIG_DEPTH
        deep: dict = {"value": "leaf"}
        for _ in range(15):   # 15 > _MAX_CONFIG_DEPTH (10)
            deep = {"nested": deep}
        with self.assertRaises(VE):
            self._sanitize(deep)

    # ── Req 18: Sanitization does not mutate original input ───────────────────

    def test_sanitize_does_not_mutate_input(self):
        original = {
            "api_key": "SHOULD_NOT_MUTATE",
            "host": "example.com",
            "auth": {"password": "MUTATE_ME_NOT"},
        }
        import copy
        snapshot = copy.deepcopy(original)
        self._sanitize(original)
        self.assertEqual(original, snapshot,
                         "_sanitize_config must not mutate the caller's object")

    # ── Scalars pass through unchanged ────────────────────────────────────────

    def test_scalar_None_passthrough(self):
        self.assertIsNone(self._sanitize(None))

    def test_scalar_int_passthrough(self):
        self.assertEqual(self._sanitize(42), 42)

    def test_scalar_bool_passthrough(self):
        self.assertIs(self._sanitize(True), True)


class TestSecretSafetyEndToEnd(AppTestCase):
    """End-to-end tests through the real Flask API and real SQLite DB."""

    # ── Req 11: Secrets do not appear in step_data_json (DB) ─────────────────

    def test_nested_api_key_not_in_step_data_json(self):
        """Req 1 + 11: Nested api_key must not be stored in step_data_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "credentials": {"api_key": "NESTED_SECRET"},
            "host": "db.example.com",
        })
        raw = _read_step_data_json(self, token)
        self.assertNotIn("NESTED_SECRET", raw,
                         "NESTED_SECRET must not appear in step_data_json")
        self.assertIn("db.example.com", raw,
                      "Non-secret host must be stored")

    def test_nested_client_secret_not_in_step_data_json(self):
        """Req 2 + 11: Nested client_secret must not be stored in step_data_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "oauth": {"client_id": "my-client", "client_secret": "DEEP_SECRET"},
        })
        raw = _read_step_data_json(self, token)
        self.assertNotIn("DEEP_SECRET", raw,
                         "DEEP_SECRET must not appear in step_data_json")

    def test_list_secrets_not_in_step_data_json(self):
        """Req 3 + 11: Secrets inside list elements must not be stored."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "endpoints": [
                {"url": "https://ep1.example.com", "api_key": "LIST_SECRET"},
            ]
        })
        raw = _read_step_data_json(self, token)
        self.assertNotIn("LIST_SECRET", raw,
                         "LIST_SECRET inside list must not appear in step_data_json")

    def test_uppercase_api_key_not_in_step_data_json(self):
        """Req 4 + 11: Uppercase API_KEY must not be stored."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={"API_KEY": "CASE_SECRET"})
        raw = _read_step_data_json(self, token)
        self.assertNotIn("CASE_SECRET", raw)

    def test_token_value_not_in_step_data_json(self):
        """Req 6 + 11: token_value must not be stored."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={"token_value": "TOKEN_SECRET"})
        raw = _read_step_data_json(self, token)
        self.assertNotIn("TOKEN_SECRET", raw)

    # ── Req 12: Secrets do not appear in connector_accounts.config_json ───────

    def test_nested_secret_not_in_connector_config_json(self):
        """Req 12: Nested secrets must not appear in the finalized connector_account."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={
            "credentials": {"api_key": "NESTED_SECRET"},
            "host": "secure.example.com",
        })
        self.assertEqual(resp.status_code, 201, resp.get_json())
        cid = resp.get_json()["connector_account_id"]
        raw = _read_config_json(self, cid)
        self.assertNotIn("NESTED_SECRET", raw,
                         "NESTED_SECRET must not appear in connector_accounts.config_json")
        self.assertIn("secure.example.com", raw,
                      "Non-secret host must be preserved in config_json")

    def test_case_secret_not_in_connector_config_json(self):
        """Req 4 + 12: Uppercase API_KEY value must not appear in config_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={"API_KEY": "CASE_SECRET"})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        cid = resp.get_json()["connector_account_id"]
        raw = _read_config_json(self, cid)
        self.assertNotIn("CASE_SECRET", raw)

    def test_access_refresh_not_in_connector_config_json(self):
        """Req 7 + 12: access_token and refresh_token must not be in config_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={
            "access_token": "AT_SECRET",
            "refresh_token": "RT_SECRET",
            "base_url": "https://api.example.com",
        })
        self.assertEqual(resp.status_code, 201, resp.get_json())
        cid = resp.get_json()["connector_account_id"]
        raw = _read_config_json(self, cid)
        self.assertNotIn("AT_SECRET", raw)
        self.assertNotIn("RT_SECRET", raw)
        self.assertIn("https://api.example.com", raw)

    def test_private_key_webhook_not_in_connector_config_json(self):
        """Req 8 + 12: private_key and webhook_secret must not be in config_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={
            "private_key": "PK_SECRET",
            "webhook_secret": "WH_SECRET",
            "endpoint": "https://webhook.example.com",
        })
        self.assertEqual(resp.status_code, 201, resp.get_json())
        cid = resp.get_json()["connector_account_id"]
        raw = _read_config_json(self, cid)
        self.assertNotIn("PK_SECRET", raw)
        self.assertNotIn("WH_SECRET", raw)
        self.assertIn("https://webhook.example.com", raw)

    # ── Req 9 + 10: Non-secret and credential_ref survive through completion ──

    def test_non_secret_config_survives_in_config_json(self):
        """Req 9: Allowed nested config must be preserved in config_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={
            "host": "db.example.com",
            "port": 5432,
            "ssl": {"enabled": True, "mode": "verify-full"},
        })
        self.assertEqual(resp.status_code, 201, resp.get_json())
        cid = resp.get_json()["connector_account_id"]
        raw = _read_config_json(self, cid)
        stored = json.loads(raw)
        self.assertEqual(stored.get("host"), "db.example.com")
        self.assertEqual(stored.get("port"), 5432)
        self.assertEqual(stored.get("ssl", {}).get("mode"), "verify-full")

    def test_credential_ref_survives_in_config_json(self):
        """Req 10: credential_ref must be preserved — it is a safe reference key."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={
            "credential_ref": "vault:secret/connectors/my-erp",
            "host": "erp.example.com",
        })
        self.assertEqual(resp.status_code, 201, resp.get_json())
        cid = resp.get_json()["connector_account_id"]
        raw = _read_config_json(self, cid)
        stored = json.loads(raw)
        self.assertIn("credential_ref", stored,
                      "credential_ref must be preserved in config_json")
        self.assertEqual(stored["credential_ref"], "vault:secret/connectors/my-erp")

    # ── Req 13: Secrets do not appear in GET session response ─────────────────

    def test_nested_secret_not_in_get_session_response(self):
        """Req 13: Nested api_key must not appear in GET /sessions/<token> response."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "credentials": {"api_key": "NESTED_SECRET"},
            "host": "safe.example.com",
        })
        resp = self.client.get(f"{_SESSION_URL}/{token}", headers=hdrs)
        self.assertEqual(resp.status_code, 200)
        body = json.dumps(resp.get_json())
        self.assertNotIn("NESTED_SECRET", body,
                         "NESTED_SECRET must not appear in GET session response")
        self.assertIn("safe.example.com", body,
                      "Non-secret host must appear in GET session response")

    def test_case_secret_not_in_get_session_response(self):
        """Req 13: Uppercase API_KEY value must not appear in GET session response."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={"API_KEY": "CASE_SECRET"})
        resp = self.client.get(f"{_SESSION_URL}/{token}", headers=hdrs)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("CASE_SECRET", json.dumps(resp.get_json()))

    def test_token_value_not_in_get_session_response(self):
        """Req 13: token_value must not appear in GET session response."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={"token_value": "TOKEN_SECRET"})
        resp = self.client.get(f"{_SESSION_URL}/{token}", headers=hdrs)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("TOKEN_SECRET", json.dumps(resp.get_json()))

    # ── Req 14: Secrets do not appear in completion response ──────────────────

    def test_secret_not_in_completion_response(self):
        """Req 14: Completion response body must not echo any secret values."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = _complete_session(self, token, hdrs, config={
            "credentials": {"api_key": "NESTED_SECRET"},
            "API_KEY": "CASE_SECRET",
        })
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = json.dumps(resp.get_json())
        self.assertNotIn("NESTED_SECRET", body,
                         "NESTED_SECRET must not appear in completion response")
        self.assertNotIn("CASE_SECRET", body,
                         "CASE_SECRET must not appear in completion response")

    # ── Req 15: Secrets do not appear in health-check response ───────────────

    def test_health_check_does_not_expose_config(self):
        """Req 15: Health-check response must not include config or any secret values."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "credentials": {"api_key": "NESTED_SECRET"},
            "host": "erp.internal",
        })
        resp = self.client.post(f"{_SESSION_URL}/{token}/test", headers=hdrs)
        self.assertEqual(resp.status_code, 200)
        body = json.dumps(resp.get_json())
        self.assertNotIn("NESTED_SECRET", body,
                         "NESTED_SECRET must not appear in health-check response")
        # The health_check block should not contain the full config dict
        self.assertNotIn("config_draft", body)

    # ── Req 16: Invalid non-object config → 422 ───────────────────────────────

    def test_string_config_at_session_creation_returns_422(self):
        """Req 16: A config value that is a plain string must return 422."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL", "config": "this-is-not-an-object"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for string config, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertEqual(data.get("error", {}).get("code"), "validation_error")

    def test_integer_config_at_session_creation_returns_422(self):
        """Req 16: A config value that is an integer must return 422."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL", "config": 12345},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for integer config, got {resp.status_code}: {resp.get_json()}")

    def test_list_config_at_session_creation_returns_422(self):
        """Req 16: A config value that is a list (not a dict) must return 422."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL", "config": ["host", "port"]},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for list config, got {resp.status_code}: {resp.get_json()}")

    def test_string_config_at_step_advance_returns_422(self):
        """Req 16: Non-dict config at step advance must return 422."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = self.client.put(
            f"{_SESSION_URL}/{token}/step",
            json={"config": "not-a-dict"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for non-dict step config, got {resp.status_code}")

    def test_string_config_at_completion_returns_422(self):
        """Req 16: Non-dict config at completion must return 422."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = self.client.post(
            f"{_SESSION_URL}/{token}/complete",
            json={"name": "test", "config": "bad-config"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for non-dict completion config, got {resp.status_code}")

    # ── Req 17: Excessive nesting → 422 ─────────────────────────────────────

    def test_excessive_nesting_at_session_creation_returns_422(self):
        """Req 17: Config nested deeper than _MAX_CONFIG_DEPTH must return 422."""
        # Build a config nested 15 levels deep (exceeds default limit of 10)
        deep: dict = {"value": "leaf"}
        for _ in range(15):
            deep = {"nested": deep}

        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL", "config": deep},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for excessive nesting, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertEqual(data.get("error", {}).get("code"), "validation_error")

    def test_excessive_nesting_at_step_advance_returns_422(self):
        """Req 17: Config nested deeper than limit must return 422 at step advance."""
        deep: dict = {"v": "leaf"}
        for _ in range(15):
            deep = {"n": deep}

        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)
        resp = self.client.put(
            f"{_SESSION_URL}/{token}/step",
            json={"config": deep},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422)

    # ── Req 19: Existing top-level secret removal still works ─────────────────

    def test_top_level_password_not_stored(self):
        """Req 19: Top-level password must still be stripped (regression guard)."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "host": "example.com",
            "password": "supersecret123",
        })
        raw = _read_step_data_json(self, token)
        self.assertNotIn("supersecret123", raw)
        self.assertIn("example.com", raw)

    def test_top_level_api_key_not_stored(self):
        """Req 19: Top-level api_key must still be stripped (regression guard)."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={
            "host": "example.com",
            "api_key": "sk-abc123",
        })
        raw = _read_step_data_json(self, token)
        self.assertNotIn("sk-abc123", raw)

    def test_top_level_token_not_stored(self):
        """Req 19: Top-level token must still be stripped (regression guard)."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs, config={"token": "bearer-xyz"})
        raw = _read_step_data_json(self, token)
        self.assertNotIn("bearer-xyz", raw)

    # ── Req 20: Registry and ownership tests (delegation to existing suite) ───

    def test_arbitrary_connector_type_still_rejected_422(self):
        """Req 20: Registry validation still rejects unknown connector types."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "TOTALLY_MADE_UP_XYZ"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422)

    def test_cross_user_session_still_returns_404(self):
        """Req 20: Owner isolation still works — cross-user access returns 404."""
        hdrs_a, _ = _supplier_headers(self)
        hdrs_b, _ = _supplier_headers(self)

        token = _create_session(self, hdrs_a)

        resp = self.client.get(f"{_SESSION_URL}/{token}", headers=hdrs_b)
        self.assertEqual(resp.status_code, 404,
                         "Supplier B must get 404 for supplier A's session")

    def test_unimplemented_connector_still_inactive(self):
        """Req 20: HOLO_ERP must still be finalized as status='inactive'."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "HOLO_ERP"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        token = resp.get_json()["session_token"]

        resp2 = _complete_session(self, token, hdrs)
        self.assertEqual(resp2.status_code, 201, resp2.get_json())
        self.assertEqual(resp2.get_json().get("connector_account_status"), "inactive")

    # ── Step-data written through step advance is also sanitized ─────────────

    def test_nested_secret_not_stored_via_step_advance(self):
        """Secrets supplied through PUT /step must not be stored in step_data_json."""
        hdrs, _ = _supplier_headers(self)
        token = _create_session(self, hdrs)

        resp = self.client.put(
            f"{_SESSION_URL}/{token}/step",
            json={"config": {
                "credentials": {"api_key": "NESTED_SECRET"},
                "host": "step.example.com",
            }},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 200)
        raw = _read_step_data_json(self, token)
        self.assertNotIn("NESTED_SECRET", raw,
                         "NESTED_SECRET from step advance must not be stored")
        self.assertIn("step.example.com", raw)


if __name__ == "__main__":
    import unittest
    unittest.main()
