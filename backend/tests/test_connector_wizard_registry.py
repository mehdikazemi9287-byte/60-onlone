"""Blocker 3 — Connector wizard registry validation tests.

Tests that the connector wizard finalizes sessions correctly:
  - connector_type is validated against the real registry before session
    creation and completion.
  - Arbitrary connector_type values are rejected.
  - Unimplemented connectors are finalized as status='inactive', never 'active'.
  - implementation_status and status are derived from the registry, not from
    browser input.
  - Owner/supplier isolation is preserved.
  - Raw secrets are never stored or returned.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase

_SESSION_URL = "/api/v1/connector-wizard/sessions"


def _supplier_headers(case: AppTestCase) -> tuple[dict, int]:
    """Returns (auth_headers, supplier_id)."""
    info = case.create_test_supplier()
    return info["headers"], info["supplier_id"]


def _complete_session(case: AppTestCase, token: str, headers: dict,
                      name: str = "Test Connector") -> dict:
    resp = case.client.post(
        f"{_SESSION_URL}/{token}/complete",
        json={"name": name},
        headers=headers,
    )
    return resp


class TestConnectorWizardRegistryValidation(AppTestCase):

    # ── Negative: arbitrary connector_type at session creation ───────────────

    def test_arbitrary_connector_type_rejected_at_session_creation(self):
        """Unknown connector_type at session creation → 422."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "TOTALLY_MADE_UP_CONNECTOR_XYZ"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for arbitrary connector_type, got {resp.status_code}: {resp.get_json()}")

    def test_empty_string_connector_type_accepted_at_session_creation(self):
        """Empty connector_type means 'not yet chosen' — session created without type."""
        hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            _SESSION_URL,
            json={},  # no connector_type
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 201,
                         f"Expected 201 for empty connector_type, got {resp.status_code}: {resp.get_json()}")

    # ── Negative: arbitrary connector_type at step advance ───────────────────

    def test_arbitrary_connector_type_rejected_at_step_advance(self):
        """Unknown connector_type when advancing a step → 422."""
        hdrs, _ = _supplier_headers(self)
        # Create session without type
        create_resp = self.client.post(_SESSION_URL, json={}, headers=hdrs)
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        resp = self.client.put(
            f"{_SESSION_URL}/{token}/step",
            json={"connector_type": "MADE_UP_XYZ_CONNECTOR"},
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for arbitrary connector_type in step, got {resp.status_code}")

    # ── Negative: completion with no connector_type ───────────────────────────

    def test_complete_without_connector_type_rejected(self):
        """Completing a session that has no connector_type → 422."""
        hdrs, _ = _supplier_headers(self)
        # Create session without type
        create_resp = self.client.post(_SESSION_URL, json={}, headers=hdrs)
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        resp = _complete_session(self, token, hdrs)
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422 for completion without connector_type, got {resp.status_code}")

    # ── Negative: unimplemented connector finalized as inactive ──────────────

    def test_unimplemented_connector_finalized_as_inactive(self):
        """Connectors with implementation_status='not_implemented' must be inactive."""
        hdrs, _ = _supplier_headers(self)
        # Use HOLO_ERP which is registered as not_implemented
        create_resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "HOLO_ERP"},
            headers=hdrs,
        )
        self.assertEqual(create_resp.status_code, 201,
                         f"HOLO_ERP session creation failed: {create_resp.get_json()}")
        token = create_resp.get_json()["session_token"]

        resp = _complete_session(self, token, hdrs, name="هلو ERP")
        self.assertEqual(resp.status_code, 201,
                         f"Expected 201 for completion, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertEqual(data.get("implementation_status"), "not_implemented",
                         "implementation_status must be 'not_implemented' for HOLO_ERP")
        self.assertEqual(data.get("connector_account_status"), "inactive",
                         "connector_account_status must be 'inactive' for not_implemented connector")

        # Verify in DB
        connector_account_id = data["connector_account_id"]
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT status FROM connector_accounts WHERE id=?",
                (connector_account_id,),
            ).fetchone()
        self.assertIsNotNone(row, "connector_account row must exist after completion")
        self.assertEqual(row["status"], "inactive",
                         "DB must have status='inactive' for unimplemented connector")

    def test_implemented_connector_finalized_as_active(self):
        """Implemented connectors (MANUAL, MOCK_ERP) must be finalized as active."""
        hdrs, _ = _supplier_headers(self)
        create_resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL"},
            headers=hdrs,
        )
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        resp = _complete_session(self, token, hdrs, name="اتصال دستی")
        self.assertEqual(resp.status_code, 201,
                         f"Expected 201 for MANUAL completion, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertIn(data.get("implementation_status"), ("production", "simulator"),
                      "MANUAL must have production/simulator implementation_status")
        self.assertEqual(data.get("connector_account_status"), "active",
                         "MANUAL connector must be finalized as active")

        connector_account_id = data["connector_account_id"]
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT status FROM connector_accounts WHERE id=?",
                (connector_account_id,),
            ).fetchone()
        self.assertEqual(row["status"], "active",
                         "DB must have status='active' for implemented connector")

    # ── Positive: MOCK_ERP finalized as active ───────────────────────────────

    def test_mock_erp_finalized_as_active(self):
        """MOCK_ERP is a simulator connector and should be finalized as active."""
        hdrs, _ = _supplier_headers(self)
        create_resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MOCK_ERP"},
            headers=hdrs,
        )
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        resp = _complete_session(self, token, hdrs, name="ERP آزمایشی")
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data.get("connector_account_status"), "active")

    # ── Negative: implementation_status from registry, not input ─────────────

    def test_implementation_status_derived_from_registry_not_input(self):
        """Caller cannot override implementation_status via request body."""
        hdrs, _ = _supplier_headers(self)
        create_resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "SEPIDAR_ERP"},
            headers=hdrs,
        )
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        # Try to pass implementation_status in the config (must be ignored)
        resp = self.client.post(
            f"{_SESSION_URL}/{token}/complete",
            json={
                "name": "سپیدار",
                "config": {"implementation_status": "production"},  # attacker tries to override
            },
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        # Must still be not_implemented regardless of what was sent
        self.assertEqual(data.get("implementation_status"), "not_implemented",
                         "implementation_status must come from registry, not request body")
        self.assertEqual(data.get("connector_account_status"), "inactive")

    # ── Owner / supplier isolation ────────────────────────────────────────────

    def test_session_owner_isolation(self):
        """Supplier A cannot access or complete supplier B's wizard session."""
        hdrs_a, _ = _supplier_headers(self)
        hdrs_b, _ = _supplier_headers(self)

        # Supplier A creates a session
        create_resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL"},
            headers=hdrs_a,
        )
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        # Supplier B tries to GET A's session → 404
        resp_get = self.client.get(f"{_SESSION_URL}/{token}", headers=hdrs_b)
        self.assertEqual(resp_get.status_code, 404,
                         "Supplier B must get 404 for supplier A's session")

        # Supplier B tries to complete A's session → 404
        resp_complete = self.client.post(
            f"{_SESSION_URL}/{token}/complete",
            json={"name": "hijacked"},
            headers=hdrs_b,
        )
        self.assertEqual(resp_complete.status_code, 404,
                         "Supplier B must get 404 when trying to complete supplier A's session")

    # ── No raw secrets in response ────────────────────────────────────────────

    def test_no_raw_secrets_in_session_response(self):
        """Secret fields must be stripped from all API responses."""
        hdrs, _ = _supplier_headers(self)
        create_resp = self.client.post(
            _SESSION_URL,
            json={
                "connector_type": "MANUAL",
                "config": {
                    "host": "example.com",
                    "password": "supersecret123",
                    "api_key": "sk-abc123",
                    "token": "bearer-xyz",
                },
            },
            headers=hdrs,
        )
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        resp = self.client.get(f"{_SESSION_URL}/{token}", headers=hdrs)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        # Check config_draft for secret fields
        config_draft = data.get("config_draft", {})
        for secret_key in ("password", "api_key", "token"):
            self.assertNotIn(secret_key, config_draft,
                             f"'{secret_key}' must not appear in session response config_draft")

    def test_no_raw_secrets_stored_in_completed_connector(self):
        """Secret fields must be stripped from connector_account config on completion."""
        hdrs, _ = _supplier_headers(self)
        create_resp = self.client.post(
            _SESSION_URL,
            json={"connector_type": "MANUAL"},
            headers=hdrs,
        )
        self.assertEqual(create_resp.status_code, 201)
        token = create_resp.get_json()["session_token"]

        # Complete with secrets in config
        resp = self.client.post(
            f"{_SESSION_URL}/{token}/complete",
            json={
                "name": "اتصال امن",
                "config": {
                    "host": "secure.example.com",
                    "password": "should-not-be-stored",
                    "api_key": "sk-should-not-be-stored",
                },
            },
            headers=hdrs,
        )
        self.assertEqual(resp.status_code, 201)
        cid = resp.get_json()["connector_account_id"]

        # Check DB directly
        import json
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT config_json FROM connector_accounts WHERE id=?", (cid,)
            ).fetchone()
        stored_config = json.loads(row["config_json"] or "{}")
        for secret_key in ("password", "api_key"):
            self.assertNotIn(secret_key, stored_config,
                             f"'{secret_key}' must not be stored in connector_account config_json")


if __name__ == "__main__":
    import unittest
    unittest.main()
