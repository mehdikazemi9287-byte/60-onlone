"""Phase 7 Security Repair — Negative / Isolation Test Suite.

Tests that the security fixes actually hold:

  1. Tax administration gated to platform admin
  2. Accounting connector tenant isolation (Supplier A ≠ Supplier B)
  3. Integration event tenant isolation
  4. Circuit breaker tenant isolation
  5. Connector wizard ownership isolation
  6. Secret / credential fields absent from API responses
  7. Unimplemented accounting connectors are disabled + fail-closed
  8. Outbox atomicity (business rollback → event absent from outbox)
  9. Concurrent event claim — only one worker claims each event
 10. Tax arithmetic is exact for amounts above 2^53
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid

from tests.base import AppTestCase


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _supplier_headers(case: AppTestCase) -> dict:
    """Create a fresh supplier user and return their auth headers + supplier_id."""
    info = case.create_test_supplier()
    return info["headers"], info["supplier_id"]


def _customer_headers(case: AppTestCase) -> dict:
    """Create a fresh customer and return auth headers."""
    _, hdrs = case.new_customer()
    return hdrs


def _admin_headers(case: AppTestCase) -> dict:
    return case.admin_headers()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tax administration — admin-only endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TaxAdminAccessTests(AppTestCase):
    """POST /tax/categories and POST /tax/rates must require platform admin."""

    def test_customer_cannot_create_tax_category(self):
        """Unauthenticated user or customer must receive 403 on POST /tax/categories."""
        customer_hdrs = _customer_headers(self)
        resp = self.client.post(
            "/api/v1/tax/categories",
            json={"code": "VAT", "name_fa": "مالیات بر ارزش افزوده", "rate_bps": 900},
            headers=customer_hdrs,
        )
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for customer creating tax category, got {resp.status_code}")

    def test_customer_cannot_create_tax_rate(self):
        """Customer must receive 403 on POST /tax/rates."""
        customer_hdrs = _customer_headers(self)
        resp = self.client.post(
            "/api/v1/tax/rates",
            json={"category_code": "VAT", "rate_bps": 1000,
                  "effective_from": "2024-01-01"},
            headers=customer_hdrs,
        )
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for customer creating tax rate, got {resp.status_code}")

    def test_supplier_cannot_create_tax_category(self):
        """Supplier must receive 403 on POST /tax/categories."""
        supplier_hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            "/api/v1/tax/categories",
            json={"code": "MYCAT", "name_fa": "دسته‌بندی جعلی", "rate_bps": 500},
            headers=supplier_hdrs,
        )
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for supplier creating tax category, got {resp.status_code}")

    def test_supplier_cannot_create_tax_rate(self):
        """Supplier must receive 403 on POST /tax/rates."""
        supplier_hdrs, _ = _supplier_headers(self)
        resp = self.client.post(
            "/api/v1/tax/rates",
            json={"category_code": "VAT", "rate_bps": 500,
                  "effective_from": "2020-01-01"},
            headers=supplier_hdrs,
        )
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for supplier creating tax rate, got {resp.status_code}")

    def test_unauthenticated_cannot_create_tax_category(self):
        """Unauthenticated request must receive 401 on POST /tax/categories."""
        resp = self.client.post(
            "/api/v1/tax/categories",
            json={"code": "VAT", "name_fa": "مالیات", "rate_bps": 900},
        )
        self.assertEqual(resp.status_code, 401,
                         f"Expected 401 for unauthenticated, got {resp.status_code}")

    def test_admin_can_create_tax_category(self):
        """Platform admin must succeed on POST /tax/categories (smoke-test positive path)."""
        admin_hdrs = _admin_headers(self)
        code = f"TEST_{uuid.uuid4().hex[:6].upper()}"
        resp = self.client.post(
            "/api/v1/tax/categories",
            json={"code": code, "name_fa": "دسته آزمایشی", "rate_bps": 100},
            headers=admin_hdrs,
        )
        self.assertIn(resp.status_code, (200, 201),
                      f"Admin should be able to create tax category, got {resp.status_code}: {resp.get_json()}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Accounting connector tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

class AccountingConnectorIsolationTests(AppTestCase):
    """Supplier A must never see Supplier B's connector accounts."""

    def _create_accounting_connector(self, admin_hdrs: dict, supplier_id: int) -> int:
        """Create an accounting connector for a given supplier via admin. Returns connector_id."""
        resp = self.client.post(
            "/api/v1/accounting-connectors",
            json={
                "name": f"اتصال آزمایشی {supplier_id}",
                "accounting_system": "MOCK",
                "supplier_id": supplier_id,
            },
            headers=admin_hdrs,
        )
        self.assertIn(resp.status_code, (200, 201),
                      f"Admin connector creation failed: {resp.get_json()}")
        return resp.get_json()["id"]

    def test_supplier_a_cannot_get_supplier_b_connector(self):
        """GET /accounting-connectors/<id> returns 404 when supplier does not own it."""
        admin_hdrs = _admin_headers(self)
        sup_a_hdrs, sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        # Create connector owned by Supplier B (via admin)
        connector_b_id = self._create_accounting_connector(admin_hdrs, sup_b_id)

        # Supplier A tries to fetch Supplier B's connector
        resp = self.client.get(
            f"/api/v1/accounting-connectors/{connector_b_id}",
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 for cross-tenant access, got {resp.status_code}: {resp.get_json()}")

    def test_supplier_a_list_excludes_supplier_b_connectors(self):
        """GET /accounting-connectors returns only the calling supplier's connectors."""
        admin_hdrs = _admin_headers(self)
        sup_a_hdrs, sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        # Create connectors for both suppliers
        conn_a_id = self._create_accounting_connector(admin_hdrs, sup_a_id)
        conn_b_id = self._create_accounting_connector(admin_hdrs, sup_b_id)

        # Supplier A lists their connectors
        resp = self.client.get("/api/v1/accounting-connectors", headers=sup_a_hdrs)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        returned_ids = {c["id"] for c in data.get("accounting_connectors", [])}

        self.assertIn(conn_a_id, returned_ids,
                      "Supplier A should see their own connector")
        self.assertNotIn(conn_b_id, returned_ids,
                         "Supplier A must NOT see Supplier B's connector in the list")

    def test_customer_cannot_list_accounting_connectors(self):
        """Customer gets 403 on GET /accounting-connectors."""
        customer_hdrs = _customer_headers(self)
        resp = self.client.get("/api/v1/accounting-connectors", headers=customer_hdrs)
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for customer, got {resp.status_code}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration event tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

class IntegrationEventIsolationTests(AppTestCase):
    """Supplier A must never see Supplier B's integration events."""

    def _insert_event(self, supplier_id: int) -> int:
        """Directly insert a test outbound event for a supplier. Returns event_id."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO integration_events
                    (event_type, direction, supplier_id, payload_json, status,
                     attempt_count, next_attempt_at, created_at, updated_at)
                VALUES ('TEST_EVENT', 'outbound', ?, '{}', 'pending', 0,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (supplier_id,),
            )
            return int(cur.lastrowid)

    def test_supplier_a_list_excludes_supplier_b_events(self):
        """GET /integration-events for Supplier A must not return Supplier B's events."""
        sup_a_hdrs, sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        ev_a_id = self._insert_event(sup_a_id)
        ev_b_id = self._insert_event(sup_b_id)

        resp = self.client.get("/api/v1/integration-events", headers=sup_a_hdrs)
        self.assertEqual(resp.status_code, 200)
        events = resp.get_json().get("integration_events", [])
        returned_ids = {e["id"] for e in events}

        self.assertIn(ev_a_id, returned_ids, "Supplier A should see their own event")
        self.assertNotIn(ev_b_id, returned_ids,
                         "Supplier A must NOT see Supplier B's event")

    def test_supplier_a_cannot_replay_supplier_b_event(self):
        """POST /integration-events/<id>/replay returns 404 if event belongs to Supplier B."""
        sup_a_hdrs, _sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        # Insert a dead-letter event for Supplier B
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO integration_events
                    (event_type, direction, supplier_id, payload_json, status,
                     attempt_count, created_at, updated_at)
                VALUES ('TEST_EVENT', 'outbound', ?, '{}', 'dead_letter', 10,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (sup_b_id,),
            )
            ev_b_id = int(cur.lastrowid)

        resp = self.client.post(
            f"/api/v1/integration-events/{ev_b_id}/replay",
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 for cross-tenant replay, got {resp.status_code}: {resp.get_json()}")

    def test_customer_cannot_list_integration_events(self):
        """Customer gets 401/403 on GET /integration-events."""
        customer_hdrs = _customer_headers(self)
        resp = self.client.get("/api/v1/integration-events", headers=customer_hdrs)
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for customer, got {resp.status_code}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Circuit breaker tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreakerIsolationTests(AppTestCase):
    """Supplier A must not be able to read or reset Supplier B's circuit breakers."""

    def _insert_connector_account(self, supplier_id: int) -> int:
        """Insert a connector_accounts row for a supplier. Returns id."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO connector_accounts
                    (name, connector_type, supplier_id, config_json,
                     environment, status, created_at, updated_at)
                VALUES (?,?,?, '{}', 'test', 'active',
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (f"اتصال آزمایشی {supplier_id}", "MOCK_ERP", supplier_id),
            )
            return int(cur.lastrowid)

    def test_supplier_a_cannot_get_supplier_b_circuit_breaker(self):
        """GET /circuit-breakers/<id> returns 404 when supplier doesn't own the connector."""
        sup_a_hdrs, _sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        conn_b_id = self._insert_connector_account(sup_b_id)

        resp = self.client.get(
            f"/api/v1/circuit-breakers/{conn_b_id}",
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 cross-tenant CB read, got {resp.status_code}: {resp.get_json()}")

    def test_supplier_a_cannot_reset_supplier_b_circuit_breaker(self):
        """POST /circuit-breakers/<id>/reset returns 404 when supplier doesn't own it."""
        sup_a_hdrs, _sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        conn_b_id = self._insert_connector_account(sup_b_id)

        resp = self.client.post(
            f"/api/v1/circuit-breakers/{conn_b_id}/reset",
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 cross-tenant CB reset, got {resp.status_code}: {resp.get_json()}")

    def test_supplier_circuit_breakers_list_scoped(self):
        """GET /circuit-breakers for a supplier only returns their own connectors."""
        sup_a_hdrs, sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        conn_a_id = self._insert_connector_account(sup_a_id)
        conn_b_id = self._insert_connector_account(sup_b_id)

        resp = self.client.get("/api/v1/circuit-breakers", headers=sup_a_hdrs)
        self.assertEqual(resp.status_code, 200)
        cb_ids = {c["connector_account_id"] for c in resp.get_json().get("circuit_breakers", [])}

        self.assertIn(conn_a_id, cb_ids, "Supplier A should see their own connector")
        self.assertNotIn(conn_b_id, cb_ids,
                         "Supplier A must NOT see Supplier B's circuit breaker")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Connector wizard ownership isolation
# ─────────────────────────────────────────────────────────────────────────────

class ConnectorWizardIsolationTests(AppTestCase):
    """Each wizard session is visible only to its creator (or admin)."""

    def _start_session(self, headers: dict) -> str:
        """Start a wizard session; return session_token."""
        resp = self.client.post(
            "/api/v1/connector-wizard/sessions",
            json={"connector_type": "MOCK_ERP"},
            headers=headers,
        )
        self.assertIn(resp.status_code, (200, 201),
                      f"Session creation failed: {resp.get_json()}")
        return resp.get_json()["session_token"]

    def test_supplier_a_cannot_get_supplier_b_session(self):
        """GET /connector-wizard/sessions/<token> returns 404 for non-owner."""
        sup_a_hdrs, _ = _supplier_headers(self)
        sup_b_hdrs, _ = _supplier_headers(self)

        token_b = self._start_session(sup_b_hdrs)

        resp = self.client.get(
            f"/api/v1/connector-wizard/sessions/{token_b}",
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 for non-owner session access, got {resp.status_code}: {resp.get_json()}")

    def test_supplier_a_cannot_advance_supplier_b_session(self):
        """PUT /connector-wizard/sessions/<token>/step returns 404 for non-owner."""
        sup_a_hdrs, _ = _supplier_headers(self)
        sup_b_hdrs, _ = _supplier_headers(self)

        token_b = self._start_session(sup_b_hdrs)

        resp = self.client.put(
            f"/api/v1/connector-wizard/sessions/{token_b}/step",
            json={"config": {"host": "example.com"}},
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 for non-owner step advance, got {resp.status_code}: {resp.get_json()}")

    def test_owner_can_access_own_session(self):
        """Positive path: session creator can GET their own session."""
        sup_a_hdrs, _ = _supplier_headers(self)
        token_a = self._start_session(sup_a_hdrs)

        resp = self.client.get(
            f"/api/v1/connector-wizard/sessions/{token_a}",
            headers=sup_a_hdrs,
        )
        self.assertEqual(resp.status_code, 200,
                         f"Owner should access their own session: {resp.get_json()}")

    def test_admin_can_access_any_session(self):
        """Admin can GET any wizard session."""
        sup_b_hdrs, _ = _supplier_headers(self)
        admin_hdrs = _admin_headers(self)

        token_b = self._start_session(sup_b_hdrs)

        resp = self.client.get(
            f"/api/v1/connector-wizard/sessions/{token_b}",
            headers=admin_hdrs,
        )
        self.assertEqual(resp.status_code, 200,
                         f"Admin should access any session: {resp.get_json()}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Secret / credential fields must not appear in responses
# ─────────────────────────────────────────────────────────────────────────────

_SECRET_FIELDS = {
    "password", "api_key", "secret", "token", "bearer_token",
    "private_key", "rsa_key", "webhook_secret", "client_secret",
}


class CredentialRedactionTests(AppTestCase):
    """Secret-bearing fields must be absent from all API responses."""

    def test_accounting_connector_response_has_no_secrets(self):
        """POST /accounting-connectors response must not include any secret fields."""
        admin_hdrs = _admin_headers(self)
        _, sup_id = _supplier_headers(self)

        resp = self.client.post(
            "/api/v1/accounting-connectors",
            json={
                "name": "اتصال آزمایشی",
                "accounting_system": "MOCK",
                "supplier_id": sup_id,
                "config": {
                    "host": "erp.example.com",
                    "api_key": "SUPERSECRET",
                    "password": "hunter2",
                },
            },
            headers=admin_hdrs,
        )
        self.assertIn(resp.status_code, (200, 201))
        body = resp.get_json()
        body_str = json.dumps(body)
        for field in _SECRET_FIELDS:
            # The field should not appear with a non-None value
            if field in body_str:
                # It's present — check it's null/None
                config = body.get("config", {})
                val = config.get(field)
                self.assertIsNone(val,
                    f"Secret field '{field}' must be null/None in response, got: {val!r}")

    def test_wizard_session_response_has_no_secrets(self):
        """Wizard session response must not contain any raw secret values."""
        sup_hdrs, _ = _supplier_headers(self)

        # Start session with a secret in config
        resp = self.client.post(
            "/api/v1/connector-wizard/sessions",
            json={
                "connector_type": "MOCK_ERP",
                "config": {
                    "host": "erp.example.com",
                    "api_key": "SUPER_SECRET_KEY",
                    "password": "hunter2",
                },
            },
            headers=sup_hdrs,
        )
        self.assertIn(resp.status_code, (200, 201))
        body_str = json.dumps(resp.get_json())
        # "SUPER_SECRET_KEY" must not appear anywhere in the response
        self.assertNotIn("SUPER_SECRET_KEY", body_str,
                         "Raw secret value must not appear in wizard session response")
        self.assertNotIn("hunter2", body_str,
                         "Raw password must not appear in wizard session response")

    def test_wizard_advance_step_response_has_no_secrets(self):
        """Advancing a wizard step with secrets in config must not echo them back."""
        sup_hdrs, _ = _supplier_headers(self)
        # Start session
        start_resp = self.client.post(
            "/api/v1/connector-wizard/sessions",
            json={"connector_type": "MOCK_ERP"},
            headers=sup_hdrs,
        )
        token = start_resp.get_json()["session_token"]

        # Advance step with secret in config
        resp = self.client.put(
            f"/api/v1/connector-wizard/sessions/{token}/step",
            json={
                "config": {
                    "host": "erp.example.com",
                    "webhook_secret": "WEBHOOK_SECRET_VALUE",
                }
            },
            headers=sup_hdrs,
        )
        body_str = json.dumps(resp.get_json())
        self.assertNotIn("WEBHOOK_SECRET_VALUE", body_str,
                         "Webhook secret must not appear in step advance response")

        # Also verify the GET session doesn't leak it
        get_resp = self.client.get(
            f"/api/v1/connector-wizard/sessions/{token}",
            headers=sup_hdrs,
        )
        get_body_str = json.dumps(get_resp.get_json())
        self.assertNotIn("WEBHOOK_SECRET_VALUE", get_body_str,
                         "Webhook secret must not appear in GET session response")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Unimplemented accounting connectors remain disabled / fail-closed
# ─────────────────────────────────────────────────────────────────────────────

class UnimplementedConnectorTests(AppTestCase):
    """Sepidar / Rahkaran / Holo / SAP / Odoo must be not_implemented + disabled."""

    UNIMPLEMENTED_SYSTEMS = ["SEPIDAR", "RAHKARAN", "HOLO", "SAP", "ODOO"]

    def test_unimplemented_connectors_created_as_disabled(self):
        """Creating an unimplemented connector must produce not_implemented + disabled."""
        admin_hdrs = _admin_headers(self)
        _, sup_id = _supplier_headers(self)

        for system in self.UNIMPLEMENTED_SYSTEMS:
            with self.subTest(system=system):
                resp = self.client.post(
                    "/api/v1/accounting-connectors",
                    json={
                        "name": f"اتصال {system}",
                        "accounting_system": system,
                        "supplier_id": sup_id,
                    },
                    headers=admin_hdrs,
                )
                self.assertIn(resp.status_code, (200, 201),
                              f"{system}: expected 200/201, got {resp.status_code}: {resp.get_json()}")
                body = resp.get_json()
                self.assertEqual(body.get("implementation_status"), "not_implemented",
                                 f"{system}: expected not_implemented, got {body.get('implementation_status')}")
                self.assertEqual(body.get("status"), "disabled",
                                 f"{system}: expected disabled, got {body.get('status')}")

    def test_unimplemented_connector_health_check_fails_closed(self):
        """Health check on an unimplemented connector must return healthy=False."""
        admin_hdrs = _admin_headers(self)
        _, sup_id = _supplier_headers(self)

        # Create a Sepidar connector (not implemented)
        create_resp = self.client.post(
            "/api/v1/accounting-connectors",
            json={"name": "سپیدار آزمایشی", "accounting_system": "SEPIDAR",
                  "supplier_id": sup_id},
            headers=admin_hdrs,
        )
        connector_id = create_resp.get_json()["id"]

        resp = self.client.get(
            f"/api/v1/accounting-connectors/{connector_id}/health",
            headers=admin_hdrs,
        )
        self.assertEqual(resp.status_code, 200)
        health = resp.get_json().get("health", {})
        self.assertFalse(health.get("healthy"),
                         f"Unimplemented connector health must be False, got: {health}")

    def test_unimplemented_connector_export_returns_501(self):
        """Export invoice on an unimplemented connector must return 501."""
        admin_hdrs = _admin_headers(self)
        _, sup_id = _supplier_headers(self)

        create_resp = self.client.post(
            "/api/v1/accounting-connectors",
            json={"name": "اودو آزمایشی", "accounting_system": "ODOO",
                  "supplier_id": sup_id},
            headers=admin_hdrs,
        )
        connector_id = create_resp.get_json()["id"]

        resp = self.client.post(
            f"/api/v1/accounting-connectors/{connector_id}/export-invoice",
            json={"order_id": 999999},
            headers=admin_hdrs,
        )
        self.assertEqual(resp.status_code, 501,
                         f"Unimplemented connector export must be 501, got {resp.status_code}")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Outbox atomicity — business rollback → event absent
# ─────────────────────────────────────────────────────────────────────────────

class OutboxAtomicityTests(AppTestCase):
    """If the business transaction rolls back, the outbox event must NOT be persisted."""

    def test_outbox_event_absent_when_business_transaction_rolls_back(self):
        """Explicitly trigger a rollback and verify no orphan event appears."""
        from app.services.integration_event_service import insert_outbox_event

        # Count events before the aborted transaction
        before_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM integration_events"
        )["n"]

        # Run a transaction that inserts an event then rolls back
        try:
            with self.db.write_transaction() as conn:
                insert_outbox_event(
                    conn,
                    event_type="ATOMIC_TEST_ROLLBACK",
                    payload={"test": True},
                )
                # Force a rollback by raising inside the transaction
                raise ValueError("deliberate rollback")
        except ValueError:
            pass  # expected

        after_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM integration_events"
        )["n"]
        self.assertEqual(before_count, after_count,
                         f"Rolled-back event must not persist: before={before_count}, after={after_count}")

    def test_outbox_event_present_when_business_transaction_commits(self):
        """When the transaction commits, the outbox event must be persisted."""
        from app.services.integration_event_service import insert_outbox_event

        before_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM integration_events"
        )["n"]

        event_id = None
        with self.db.write_transaction() as conn:
            event_id = insert_outbox_event(
                conn,
                event_type="ATOMIC_TEST_COMMIT",
                payload={"test": True},
            )

        self.assertIsNotNone(event_id)
        after_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM integration_events"
        )["n"]
        self.assertEqual(after_count, before_count + 1,
                         f"Committed event must persist: before={before_count}, after={after_count}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Concurrent event claim — only one worker claims each event
# ─────────────────────────────────────────────────────────────────────────────

class ConcurrentClaimTests(AppTestCase):
    """Two worker threads must not double-claim the same event."""

    def test_two_workers_claim_each_event_exactly_once(self):
        """Insert N events; run two concurrent workers; verify each event claimed exactly once."""
        from app.services.outbox_worker import claim_batch

        # Insert 10 test events in 'pending' state
        event_ids = []
        with self.db.write_transaction() as conn:
            for i in range(10):
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, payload_json, status, attempt_count,
                         next_attempt_at, created_at, updated_at)
                    VALUES ('CONCURRENT_TEST', 'outbound', '{}', 'pending', 0,
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                )
                event_ids.append(int(cur.lastrowid))

        # Run two concurrent workers against the same DB.
        # Each runs claim_batch inside the Flask app context so write_transaction works.
        claimed_by_worker: dict[int, list[int]] = {1: [], 2: []}
        errors: list[str] = []

        def worker(worker_num: int) -> None:
            try:
                with self.app.app_context():
                    claimed = claim_batch(batch_size=20)
                    claimed_by_worker[worker_num] = claimed
            except Exception as exc:
                errors.append(f"worker {worker_num}: {exc}")

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertFalse(errors, f"Worker errors: {errors}")

        all_claimed = claimed_by_worker[1] + claimed_by_worker[2]
        our_events = [eid for eid in all_claimed if eid in event_ids]

        # Each of our test event IDs must appear at most once across both workers
        seen: set[int] = set()
        for eid in our_events:
            self.assertNotIn(eid, seen,
                             f"Event {eid} was claimed by BOTH workers — double-claim detected!")
            seen.add(eid)

        # All 10 events must have been claimed (combined)
        for eid in event_ids:
            self.assertIn(eid, seen,
                          f"Event {eid} was not claimed by either worker")

    # ── Regression scenario 2: four concurrent workers ─────────────────────

    def test_four_workers_no_event_lost_no_duplicate(self):
        """Four concurrent workers: every event claimed exactly once."""
        from app.services.outbox_worker import claim_batch

        N_EVENTS = 16
        event_ids: list[int] = []
        with self.db.write_transaction() as conn:
            for _ in range(N_EVENTS):
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, payload_json, status, attempt_count,
                         next_attempt_at, created_at, updated_at)
                    VALUES ('CONC4_TEST', 'outbound', '{}', 'pending', 0,
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                )
                event_ids.append(int(cur.lastrowid))

        claimed_by: dict[int, list[int]] = {i: [] for i in range(1, 5)}
        errors: list[str] = []

        def worker(num: int) -> None:
            try:
                with self.app.app_context():
                    claimed_by[num] = claim_batch(batch_size=20)
            except Exception as exc:
                errors.append(f"worker {num}: {exc}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertFalse(errors, f"Worker errors: {errors}")

        all_claimed = [eid for lst in claimed_by.values() for eid in lst]
        our_events = [eid for eid in all_claimed if eid in event_ids]

        # No duplicates
        seen: set[int] = set()
        for eid in our_events:
            self.assertNotIn(eid, seen,
                             f"Event {eid} was double-claimed by multiple workers")
            seen.add(eid)

        # No lost events
        for eid in event_ids:
            self.assertIn(eid, seen,
                          f"Event {eid} was not claimed by any of the 4 workers")

    # ── Regression scenario 3: more events than any single worker batch ─────

    def test_more_events_than_batch_size_all_eventually_claimed(self):
        """When events exceed a single worker's batch, multiple rounds claim all."""
        from app.services.outbox_worker import claim_batch

        N_EVENTS = 25
        BATCH = 10
        event_ids: list[int] = []
        with self.db.write_transaction() as conn:
            for _ in range(N_EVENTS):
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, payload_json, status, attempt_count)
                    VALUES ('BATCH_TEST', 'outbound', '{}', 'pending', 0)
                    """,
                )
                event_ids.append(int(cur.lastrowid))

        claimed_all: list[int] = []
        with self.app.app_context():
            for _ in range(5):  # up to 5 rounds to drain all 25
                batch = claim_batch(batch_size=BATCH)
                claimed_all.extend(batch)
                if not batch:
                    break

        our_events = [eid for eid in claimed_all if eid in event_ids]
        # No duplicates
        self.assertEqual(len(our_events), len(set(our_events)),
                         "Some events were claimed more than once")
        # All claimed
        for eid in event_ids:
            self.assertIn(eid, set(our_events),
                          f"Event {eid} was never claimed despite multiple rounds")

    # ── Regression scenario 4: stress test — many concurrent workers ────────

    def test_high_concurrency_stress_no_duplicate_no_lost(self):
        """8 concurrent workers racing on 24 events: no duplicates, no losses."""
        from app.services.outbox_worker import claim_batch

        N_EVENTS = 24
        N_WORKERS = 8
        event_ids: list[int] = []
        with self.db.write_transaction() as conn:
            for _ in range(N_EVENTS):
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, payload_json, status, attempt_count,
                         next_attempt_at, created_at, updated_at)
                    VALUES ('STRESS_TEST', 'outbound', '{}', 'pending', 0,
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                )
                event_ids.append(int(cur.lastrowid))

        all_claimed: list[int] = []
        lock = threading.Lock()
        errors: list[str] = []

        def worker(num: int) -> None:
            try:
                with self.app.app_context():
                    claimed = claim_batch(batch_size=6)
                    with lock:
                        all_claimed.extend(claimed)
            except Exception as exc:
                errors.append(f"worker {num}: {exc}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertFalse(errors, f"Worker errors: {errors}")

        our_events = [eid for eid in all_claimed if eid in event_ids]
        seen: set[int] = set()
        for eid in our_events:
            self.assertNotIn(eid, seen,
                             f"Event {eid} was double-claimed under high concurrency")
            seen.add(eid)

        for eid in event_ids:
            self.assertIn(eid, seen,
                          f"Event {eid} was lost under high concurrency ({N_WORKERS} workers)")

    # ── Regression scenario 6: worker failure after claim ───────────────────

    def test_worker_failure_after_claim_does_not_lose_event(self):
        """Events claimed but not delivered remain in 'processing' until stale-lease recovery."""
        from app.services.outbox_worker import claim_batch, recover_stale_leases
        from datetime import datetime, timezone, timedelta

        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO integration_events
                    (event_type, direction, payload_json, status, attempt_count)
                VALUES ('FAILURE_TEST', 'outbound', '{}', 'pending', 0)
                """,
            )
            event_id = int(cur.lastrowid)

        # Worker claims event but then "crashes" (never marks it delivered)
        with self.app.app_context():
            claimed = claim_batch(batch_size=10)

        self.assertIn(event_id, claimed,
                      "Worker should have claimed the pending event")

        # Event should be 'processing' (simulating a crashed worker)
        row = self.db.query_one(
            "SELECT status FROM integration_events WHERE id=?", (event_id,)
        )
        self.assertEqual(row["status"], "processing",
                         "Event must be 'processing' after claim (not yet delivered)")

        # Fast-forward time: back-date updated_at so stale-lease recovery fires
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE integration_events SET updated_at=? WHERE id=?",
                (old_ts, event_id),
            )

        with self.app.app_context():
            recovered = recover_stale_leases(lease_timeout_s=300)

        self.assertGreaterEqual(recovered, 1, "Stale lease should have been recovered")
        row = self.db.query_one(
            "SELECT status FROM integration_events WHERE id=?", (event_id,)
        )
        self.assertEqual(row["status"], "pending",
                         "Event must return to 'pending' after stale-lease recovery")

    # ── Regression scenario 9: eventual completion of all eligible events ───

    def test_eventual_completion_all_eligible_events_claimed(self):
        """All eligible events are eventually claimed across multiple worker invocations."""
        from app.services.outbox_worker import claim_batch

        N_EVENTS = 30
        BATCH = 7
        event_ids: list[int] = []
        with self.db.write_transaction() as conn:
            for _ in range(N_EVENTS):
                cur = conn.execute(
                    """
                    INSERT INTO integration_events
                        (event_type, direction, payload_json, status, attempt_count)
                    VALUES ('EVENTUAL_TEST', 'outbound', '{}', 'pending', 0)
                    """,
                )
                event_ids.append(int(cur.lastrowid))

        claimed_set: set[int] = set()
        with self.app.app_context():
            for _ in range(10):  # enough rounds to drain all 30 events in batches of 7
                batch = claim_batch(batch_size=BATCH)
                claimed_set.update(batch)

        our_events = claimed_set & set(event_ids)
        self.assertEqual(len(our_events), N_EVENTS,
                         f"Expected all {N_EVENTS} events claimed; got {len(our_events)}")

    # ── Regression scenario 10: repeated concurrent execution ───────────────

    def test_repeated_concurrent_execution_always_safe(self):
        """Run the two-worker concurrent claim 20 times in a loop; all must pass."""
        from app.services.outbox_worker import claim_batch

        for iteration in range(20):
            event_ids: list[int] = []
            with self.db.write_transaction() as conn:
                for _ in range(8):
                    cur = conn.execute(
                        """
                        INSERT INTO integration_events
                            (event_type, direction, payload_json, status, attempt_count,
                             next_attempt_at, created_at, updated_at)
                        VALUES ('REPEAT_TEST', 'outbound', '{}', 'pending', 0,
                                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        """,
                    )
                    event_ids.append(int(cur.lastrowid))

            claimed_by: dict[int, list[int]] = {1: [], 2: []}
            errors: list[str] = []

            def worker(num: int) -> None:  # noqa: E306
                try:
                    with self.app.app_context():
                        claimed_by[num] = claim_batch(batch_size=20)
                except Exception as exc:
                    errors.append(f"iter {iteration} worker {num}: {exc}")

            t1 = threading.Thread(target=worker, args=(1,))
            t2 = threading.Thread(target=worker, args=(2,))
            t1.start(); t2.start()
            t1.join(timeout=15); t2.join(timeout=15)

            self.assertFalse(errors,
                             f"Iteration {iteration}: Worker errors: {errors}")

            all_claimed = claimed_by[1] + claimed_by[2]
            our_events = [eid for eid in all_claimed if eid in event_ids]
            seen: set[int] = set()
            for eid in our_events:
                self.assertNotIn(eid, seen,
                                 f"Iteration {iteration}: Event {eid} was double-claimed")
                seen.add(eid)
            for eid in event_ids:
                self.assertIn(eid, seen,
                              f"Iteration {iteration}: Event {eid} was not claimed by either worker")

            # Mark all claimed events as 'delivered' so they don't pollute the next iteration
            if claimed_by[1] or claimed_by[2]:
                all_ids = claimed_by[1] + claimed_by[2]
                ph = ",".join("?" * len(all_ids))
                with self.db.write_transaction() as conn:
                    conn.execute(
                        f"UPDATE integration_events SET status='delivered' WHERE id IN ({ph})",
                        all_ids,
                    )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Tax arithmetic is exact for amounts above 2^53
# ─────────────────────────────────────────────────────────────────────────────

class TaxArithmeticPrecisionTests(AppTestCase):
    """VAT calculations must be integer-exact even for subtotals above 2^53."""

    def _calculate_line_tax(self, subtotal_minor: int, rate_bps: int) -> dict:
        """Thin wrapper: calls tax_service.calculate_line_tax using 'STANDARD' category
        but overrides the returned rate for direct formula checking."""
        from app.services.tax_service import calculate_line_tax
        # Use calculate_line_tax with the actual date-based rate lookup, but we
        # validate the formula rather than the specific rate here.
        result = calculate_line_tax(
            subtotal_minor=subtotal_minor,
            tax_category_code="STANDARD",
            effective_date="2024-06-01",
        )
        return result

    def test_vat_formula_integer_floor_above_2_pow_53(self):
        """Tax computed via integer floor division must equal subtotal * rate // 10000."""
        from app.services.tax_service import calculate_line_tax

        # 2^53 + 1 — this is where floats lose integer precision
        subtotal_minor = (2 ** 53) + 1

        with self.app.app_context():
            result = calculate_line_tax(
                subtotal_minor=subtotal_minor,
                tax_category_code="STANDARD",
                effective_date="2024-06-01",
            )
        rate_bps = result["rate_bps"]
        expected = subtotal_minor * rate_bps // 10000

        self.assertEqual(result["tax_minor"], expected,
                         f"Tax must be integer-exact above 2^53: "
                         f"expected={expected}, got={result['tax_minor']}, rate_bps={rate_bps}")

    def test_vat_exact_large_amount_floor_vs_float(self):
        """For large subtotals, integer // and float / must not produce same result when they diverge."""
        from app.services.tax_service import calculate_line_tax

        # 2^53 + 1: float cannot represent this exactly as integer * rate
        subtotal_minor = 9_007_199_254_740_993  # 2^53 + 1
        with self.app.app_context():
            result = calculate_line_tax(
                subtotal_minor=subtotal_minor,
                tax_category_code="STANDARD",
                effective_date="2024-06-01",
            )
        rate_bps = result["rate_bps"]

        # Integer floor — the ground truth
        expected = subtotal_minor * rate_bps // 10000
        self.assertEqual(result["tax_minor"], expected,
                         f"Tax must equal integer floor for large amounts: "
                         f"expected={expected}, got={result['tax_minor']}, rate_bps={rate_bps}")

    def test_mock_tax_adapter_integer_floor_above_2_pow_53(self):
        """Mock tax adapter must use integer floor division for line tax calculations."""
        from app.adapters.tax.mock import MockTaxAdapter
        from app.adapters.tax.base import TaxLineInput

        adapter = MockTaxAdapter()
        subtotal_minor = (2 ** 53) + 999
        # Use a single unit at the large price
        lines = [TaxLineInput(
            description="آیتم آزمایشی",
            quantity=1,
            unit_price_minor=subtotal_minor,
            tax_category_code="STANDARD",
        )]

        result = adapter.calculate_tax(lines, effective_date="2024-06-01")

        # The adapter returns a TaxCalculationResult with tax_minor
        actual_tax = result.tax_minor
        rate_bps = result.rate_bps
        expected = subtotal_minor * rate_bps // 10000
        self.assertEqual(actual_tax, expected,
                         f"Mock adapter must use integer floor division above 2^53: "
                         f"expected={expected}, got={actual_tax}, rate_bps={rate_bps}")

    def test_no_float_in_tax_arithmetic_multi_boundary(self):
        """Tax calculations on multiple boundary values must all be integer-exact."""
        from app.services.tax_service import calculate_line_tax

        for subtotal in [2**53, 2**53 + 1, 2**53 + 7, 2**54 - 1]:
            with self.subTest(subtotal=subtotal):
                with self.app.app_context():
                    result = calculate_line_tax(
                        subtotal_minor=subtotal,
                        tax_category_code="STANDARD",
                        effective_date="2024-06-01",
                    )
                rate_bps = result["rate_bps"]
                expected = subtotal * rate_bps // 10000
                self.assertEqual(result["tax_minor"], expected,
                                 f"subtotal={subtotal} rate={rate_bps}: "
                                 f"expected={expected}, got={result['tax_minor']}")


# ─────────────────────────────────────────────────────────────────────────────
# 11. Dead-letter tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

class DeadLetterIsolationTests(AppTestCase):
    """Dead-letter list endpoint must scope to calling supplier."""

    def test_supplier_a_dead_letter_excludes_supplier_b(self):
        """GET /integration-events/dead-letter for Supplier A must not include Supplier B's events."""
        sup_a_hdrs, sup_a_id = _supplier_headers(self)
        _sup_b_hdrs, sup_b_id = _supplier_headers(self)

        # Insert dead-letter events for each supplier
        with self.db.write_transaction() as conn:
            cur_a = conn.execute(
                """
                INSERT INTO integration_events
                    (event_type, direction, supplier_id, payload_json, status,
                     attempt_count, created_at, updated_at)
                VALUES ('DL_TEST', 'outbound', ?, '{}', 'dead_letter', 10,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (sup_a_id,),
            )
            ev_a_id = int(cur_a.lastrowid)
            cur_b = conn.execute(
                """
                INSERT INTO integration_events
                    (event_type, direction, supplier_id, payload_json, status,
                     attempt_count, created_at, updated_at)
                VALUES ('DL_TEST', 'outbound', ?, '{}', 'dead_letter', 10,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (sup_b_id,),
            )
            ev_b_id = int(cur_b.lastrowid)

        resp = self.client.get("/api/v1/integration-events/dead-letter", headers=sup_a_hdrs)
        self.assertEqual(resp.status_code, 200)
        dl_ids = {e["id"] for e in resp.get_json().get("dead_letter_events", [])}

        self.assertIn(ev_a_id, dl_ids, "Supplier A should see their own dead-letter event")
        self.assertNotIn(ev_b_id, dl_ids,
                         "Supplier A must NOT see Supplier B's dead-letter event")


if __name__ == "__main__":
    import unittest
    unittest.main()
