"""Phase 8 — Issue 1: RuntimeCredentials injection path tests.

Mandatory tests proving:
  1.  Spy Adapter actually receives the resolved credential material.
  2.  Spy Adapter can use credential during push_order.
  3.  Persisted connector config remains unchanged after dispatch.
  4.  Resolved secret absent from all connector_accounts DB fields.
  5.  Resolved secret absent from integration_events / outbox payloads.
  6.  Resolved secret absent from log records (captured via logging handler).
  7.  Resolved secret absent from API responses.
  8.  Resolved secret absent from exception text.
  9.  Resolved secret absent from Adapter capability output.
  10. Unknown credential_ref blocks dispatch (fail-closed).
  11. No Adapter method invoked after resolution failure.
  12. Adapter without credential_ref works safely.
  13. RuntimeCredentials cannot be JSON-serialized accidentally.

Security constraints enforced here:
  - Tests use InMemorySecretResolver, never real credentials.
  - The marker string is deliberately implausible to avoid accidental matches
    in real systems, yet unique enough to catch leaks reliably.
"""
from __future__ import annotations

import json
import logging
import pickle
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.runtime_credentials import RuntimeCredentials
from app.core.secret_resolver import InMemorySecretResolver
from app.adapters.connectors.base import (
    CapabilityDeclaration,
    ConnectorAdapter,
)

# ─────────────────────────────────────────────────────────────────────────────
# Marker secret — deliberately implausible value used ONLY in tests
# ─────────────────────────────────────────────────────────────────────────────
_MARKER = "TESTONLY-SECRET-XYZZY-SHOULD-NEVER-APPEAR-IN-OUTPUT-999"
_REF    = "ref:test:marker"


# ─────────────────────────────────────────────────────────────────────────────
# Spy adapter — records calls and credential presence
# ─────────────────────────────────────────────────────────────────────────────

class SpyAdapter(ConnectorAdapter):
    """Test-only adapter that captures what the outbox worker passes it."""

    adapter_name = "spy_erp"

    def __init__(self, config: dict | None = None):
        self.calls: list[dict] = []      # recorded calls
        self._config = config or {}

    def capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            connector_type="MOCK_ERP",
            adapter_name="spy_erp",
            supported=["push_orders"],
            implementation_status="simulator",  # not_implemented → would be blocked
        )

    def push_order(self, order_data: dict, *, runtime_credentials=None) -> dict:
        secret_value = None
        if runtime_credentials is not None and runtime_credentials.has_value():
            secret_value = runtime_credentials.resolve()
        self.calls.append({
            "method": "push_order",
            "order_data": order_data,
            "had_credentials": runtime_credentials is not None,
            "secret_value": secret_value,
        })
        return {"acknowledged": True, "external_ref": "SPY-001", "message": "ok"}

    def push_inventory(self, inventory_updates, *, runtime_credentials=None) -> dict:
        self.calls.append({
            "method": "push_inventory",
            "had_credentials": runtime_credentials is not None,
        })
        return {"acknowledged": True, "failed": [], "message": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Helper: insert a connector_account row and an integration_event row
# ─────────────────────────────────────────────────────────────────────────────

def _insert_connector_account(db, *, connector_type: str = "MOCK_ERP",
                               config: dict | None = None) -> int:
    """Insert a connector_accounts row; returns its id."""
    cfg = json.dumps(config or {})
    with db.write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO connector_accounts
                (connector_type, name, config_json, status)
            VALUES (?, ?, ?, 'active')
            """,
            (connector_type, "Spy ERP (test)", cfg),
        )
        return int(cur.lastrowid)


def _insert_event(db, *, connector_account_id: int,
                  event_type: str = "ORDER_CREATED",
                  payload: dict | None = None) -> int:
    """Insert a pending integration_event; returns its id."""
    pj = json.dumps(payload or {"order_id": 1})
    with db.write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO integration_events
                (event_type, direction, connector_account_id, payload_json,
                 status, attempt_count)
            VALUES (?, 'outbound', ?, ?, 'pending', 0)
            """,
            (event_type, connector_account_id, pj),
        )
        return int(cur.lastrowid)


# ─────────────────────────────────────────────────────────────────────────────
# Log capture helper
# ─────────────────────────────────────────────────────────────────────────────

class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))

    def contains(self, text: str) -> bool:
        return any(text in r for r in self.records)


# ─────────────────────────────────────────────────────────────────────────────
# Test suite
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeCredentialsPureUnit(unittest.TestCase):
    """Pure-unit tests for the RuntimeCredentials class itself."""

    def _make(self, value="my-secret", ref="ref:unit"):
        return RuntimeCredentials(value, ref=ref)

    # ── Test 13: no JSON serialisation ─────────────────────────────────────

    def test_13_cannot_be_json_serialized(self):
        """RuntimeCredentials must not serialise via json.dumps."""
        creds = self._make()
        with self.assertRaises((TypeError, ValueError)):
            json.dumps(creds)

    def test_13b_cannot_be_json_serialized_inside_dict(self):
        """Embedding in a dict must also fail json.dumps."""
        creds = self._make()
        with self.assertRaises((TypeError, ValueError)):
            json.dumps({"creds": creds})

    def test_13c_cannot_be_pickled(self):
        """pickle must raise TypeError."""
        creds = self._make()
        with self.assertRaises(TypeError):
            pickle.dumps(creds)

    def test_repr_does_not_contain_secret(self):
        """__repr__ must never reveal the raw value."""
        creds = self._make("ultra-secret-value-12345")
        self.assertNotIn("ultra-secret-value-12345", repr(creds))
        self.assertIn("REDACTED", repr(creds))

    def test_str_does_not_contain_secret(self):
        """__str__ must never reveal the raw value."""
        creds = self._make("ultra-secret-value-12345")
        self.assertNotIn("ultra-secret-value-12345", str(creds))

    def test_ref_is_accessible_without_secret(self):
        """ref must be readable (safe to log); value must stay hidden."""
        creds = RuntimeCredentials("secret", ref="ref:safe-key")
        self.assertEqual(creds.ref, "ref:safe-key")

    def test_resolve_returns_value(self):
        """resolve() returns the raw value exactly once."""
        creds = RuntimeCredentials("raw-secret", ref="ref:x")
        self.assertEqual(creds.resolve(), "raw-secret")

    def test_none_sentinel_raises_on_resolve(self):
        """RuntimeCredentials(None) sentinel raises RuntimeError on resolve()."""
        creds = RuntimeCredentials(None, ref="ref:missing")
        with self.assertRaises(RuntimeError):
            creds.resolve()

    def test_is_immutable(self):
        """__setattr__ and __delattr__ must raise AttributeError."""
        creds = self._make()
        with self.assertRaises(AttributeError):
            creds._value = "tampered"  # type: ignore[attr-defined]

    def test_is_not_hashable(self):
        """Must not be usable as dict key or set element."""
        creds = self._make()
        with self.assertRaises(TypeError):
            {creds: "value"}


class TestRuntimeCredentialsIntegration(AppTestCase):
    """Integration tests using a real SQLite database, real outbox worker,
    and a test-only SpyAdapter / InMemorySecretResolver.

    The SpyAdapter is patched into the connector registry for the duration
    of each test only.
    """

    def _patch_registry_with_spy(self) -> SpyAdapter:
        """Swap 'spy_erp' into get_adapter() and return the spy instance.

        We monkeypatch the registry's get_adapter function only.
        """
        import app.adapters.connectors.registry as reg_module
        self._original_get_adapter = reg_module.get_adapter
        spy = SpyAdapter()

        def _patched_get_adapter(connector_type: str, *, config: dict | None = None):
            if connector_type == "MOCK_ERP":
                return spy
            return self._original_get_adapter(connector_type, config=config)

        reg_module.get_adapter = _patched_get_adapter
        self.addCleanup(lambda: setattr(reg_module, "get_adapter",
                                        self._original_get_adapter))
        return spy

    def _install_resolver(self, ref: str, secret: str) -> None:
        """Register ref→secret in the app's InMemorySecretResolver."""
        resolver = InMemorySecretResolver()
        resolver.register(ref, secret)
        self.app.extensions["secret_resolver"] = resolver

    def _dispatch(self, event_id: int) -> None:
        """Run outbox worker dispatch for a single event inside app context."""
        from app.services.outbox_worker import _dispatch_event, _load_event
        with self.app.app_context():
            event = _load_event(event_id)
            self.assertIsNotNone(event, "event must exist")
            _dispatch_event(event)

    # ── Test 1 & 2: spy receives and can use credential ─────────────────────

    def test_01_02_spy_receives_and_can_use_credential(self):
        """Spy adapter receives RuntimeCredentials and can call resolve()."""
        spy = self._patch_registry_with_spy()
        self._install_resolver(_REF, _MARKER)

        ca_id = _insert_connector_account(
            self.db,
            connector_type="MOCK_ERP",
            config={"credential_ref": _REF},
        )
        ev_id = _insert_event(self.db, connector_account_id=ca_id)

        self._dispatch(ev_id)

        self.assertEqual(len(spy.calls), 1, "push_order must be called once")
        call = spy.calls[0]
        self.assertTrue(call["had_credentials"],
                        "Adapter must receive runtime_credentials")
        # Test 2: the adapter CAN resolve the secret (it was really passed)
        self.assertEqual(call["secret_value"], _MARKER,
                         "resolve() must return the exact marker secret")

    # ── Test 3: persisted config unchanged ───────────────────────────────────

    def test_03_persisted_config_unchanged(self):
        """connector_accounts.config_json must not mutate after dispatch."""
        spy = self._patch_registry_with_spy()
        self._install_resolver(_REF, _MARKER)

        original_config = {"credential_ref": _REF, "base_url": "https://example.com"}
        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP", config=original_config
        )
        ev_id = _insert_event(self.db, connector_account_id=ca_id)
        self._dispatch(ev_id)

        with self.app.app_context():
            from app.core.db import _get_db
            row = _get_db().query_one(
                "SELECT config_json FROM connector_accounts WHERE id = ?",
                (ca_id,),
            )
        stored = json.loads(row["config_json"])
        # Must equal original exactly — secret must NOT be injected
        self.assertEqual(stored, original_config)
        self.assertNotIn(_MARKER, row["config_json"])

    # ── Test 4: secret absent from all DB fields ─────────────────────────────

    def test_04_secret_absent_from_database(self):
        """Marker secret must not appear in any column of connector_accounts."""
        spy = self._patch_registry_with_spy()
        self._install_resolver(_REF, _MARKER)

        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP",
            config={"credential_ref": _REF},
        )
        ev_id = _insert_event(self.db, connector_account_id=ca_id)
        self._dispatch(ev_id)

        with self.app.app_context():
            from app.core.db import _get_db
            db = _get_db()
            ca_row = db.query_one(
                "SELECT * FROM connector_accounts WHERE id = ?", (ca_id,)
            )
            ev_row = db.query_one(
                "SELECT * FROM integration_events WHERE id = ?", (ev_id,)
            )

        for col, val in dict(ca_row).items():
            self.assertNotIn(_MARKER, str(val or ""),
                             f"connector_accounts.{col} must not contain secret")

        for col, val in dict(ev_row).items():
            self.assertNotIn(_MARKER, str(val or ""),
                             f"integration_events.{col} must not contain secret")

    # ── Test 5: secret absent from outbox payload ────────────────────────────

    def test_05_secret_absent_from_outbox_payload(self):
        """The integration_events.payload_json must never contain the secret."""
        spy = self._patch_registry_with_spy()
        self._install_resolver(_REF, _MARKER)

        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP",
            config={"credential_ref": _REF},
        )
        # Insert event with a payload that does NOT contain the secret
        payload = {"order_id": 42, "total_minor": 100000}
        ev_id = _insert_event(self.db, connector_account_id=ca_id, payload=payload)
        self._dispatch(ev_id)

        with self.app.app_context():
            from app.core.db import _get_db
            row = _get_db().query_one(
                "SELECT payload_json FROM integration_events WHERE id = ?",
                (ev_id,),
            )
        self.assertNotIn(_MARKER, row["payload_json"] or "")

    # ── Test 6: secret absent from logs ─────────────────────────────────────

    def test_06_secret_absent_from_logs(self):
        """No log record at any level must contain the resolved secret."""
        spy = self._patch_registry_with_spy()
        self._install_resolver(_REF, _MARKER)

        handler = _CapturingHandler()
        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(handler)
        try:
            ca_id = _insert_connector_account(
                self.db, connector_type="MOCK_ERP",
                config={"credential_ref": _REF},
            )
            ev_id = _insert_event(self.db, connector_account_id=ca_id)
            self._dispatch(ev_id)
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(original_level)

        for record in handler.records:
            self.assertNotIn(_MARKER, record,
                             f"Secret leaked into log record: {record[:200]}")

    # ── Test 7: secret absent from API responses ─────────────────────────────

    def test_07_secret_absent_from_api_responses(self):
        """GET /api/v1/connectors/... must never expose the secret in the JSON."""
        self._install_resolver(_REF, _MARKER)

        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP",
            config={"credential_ref": _REF, "base_url": "https://example.com"},
        )

        # Hit any connector-related endpoint that returns config info
        admin_h = self.admin_headers()
        # Check the connector_accounts endpoint if it exists; fall back to a
        # general check that the marker string isn't anywhere in the response.
        with self.app.app_context():
            resp = self.client.get(
                f"/api/v1/admin/connector-accounts/{ca_id}",
                headers=admin_h,
            )
            body = resp.get_data(as_text=True)
            self.assertNotIn(_MARKER, body,
                             f"Secret leaked in API response body (status={resp.status_code})")

    # ── Test 8: secret absent from exception text ────────────────────────────

    def test_08_secret_absent_from_exception_text(self):
        """When dispatch raises, the exception message must not contain secret."""
        # Use a FailClosedSecretResolver so resolution itself succeeds,
        # but use an adapter that raises after receiving credentials.
        import app.adapters.connectors.registry as reg_module
        original_get_adapter = reg_module.get_adapter

        class ExplodingAdapter(SpyAdapter):
            def push_order(self, order_data, *, runtime_credentials=None):
                # deliberately include repr(runtime_credentials) NOT the secret
                raise RuntimeError(
                    f"Adapter exploded for connector spy_erp "
                    f"creds_ref={runtime_credentials.ref if runtime_credentials else None}"
                )

        exploding = ExplodingAdapter()

        def _patched(connector_type, *, config=None):
            if connector_type == "MOCK_ERP":
                return exploding
            return original_get_adapter(connector_type, config=config)

        reg_module.get_adapter = _patched
        try:
            self._install_resolver(_REF, _MARKER)
            ca_id = _insert_connector_account(
                self.db, connector_type="MOCK_ERP",
                config={"credential_ref": _REF},
            )
            ev_id = _insert_event(self.db, connector_account_id=ca_id)

            with self.app.app_context():
                from app.services.outbox_worker import _dispatch_event, _load_event
                event = _load_event(ev_id)
                try:
                    _dispatch_event(event)
                except RuntimeError as exc:
                    exc_text = str(exc)
                    self.assertNotIn(_MARKER, exc_text,
                                     "Secret must not appear in exception message")
                else:
                    self.fail("Expected RuntimeError was not raised")
        finally:
            reg_module.get_adapter = original_get_adapter

    # ── Test 9: secret absent from capabilities ──────────────────────────────

    def test_09_secret_absent_from_capabilities_output(self):
        """capabilities().to_dict() must never surface the resolved secret."""
        spy = self._patch_registry_with_spy()
        cap_dict = spy.capabilities().to_dict()
        cap_json = json.dumps(cap_dict)
        self.assertNotIn(_MARKER, cap_json,
                         "Secret must not appear in capability declaration")

    # ── Test 10: unknown ref blocks dispatch (fail-closed) ───────────────────

    def test_10_unknown_ref_blocks_dispatch(self):
        """FailClosedSecretResolver blocks dispatch when ref is unknown."""
        from app.core.secret_resolver import FailClosedSecretResolver
        self.app.extensions["secret_resolver"] = FailClosedSecretResolver()

        spy = self._patch_registry_with_spy()
        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP",
            config={"credential_ref": "ref:does-not-exist"},
        )
        ev_id = _insert_event(self.db, connector_account_id=ca_id)

        with self.app.app_context():
            from app.services.outbox_worker import _dispatch_event, _load_event
            event = _load_event(ev_id)
            with self.assertRaises(RuntimeError) as ctx:
                _dispatch_event(event)

        # Error mentions ref, not a secret
        self.assertIn("ref:does-not-exist", str(ctx.exception))

    # ── Test 11: no adapter call after resolution failure ───────────────────

    def test_11_no_adapter_called_after_resolution_failure(self):
        """If credential resolution fails, push_order must never be called."""
        from app.core.secret_resolver import FailClosedSecretResolver
        self.app.extensions["secret_resolver"] = FailClosedSecretResolver()

        spy = self._patch_registry_with_spy()
        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP",
            config={"credential_ref": "ref:absent"},
        )
        ev_id = _insert_event(self.db, connector_account_id=ca_id)

        with self.app.app_context():
            from app.services.outbox_worker import _dispatch_event, _load_event
            event = _load_event(ev_id)
            try:
                _dispatch_event(event)
            except RuntimeError:
                pass  # expected — resolution fails

        self.assertEqual(len(spy.calls), 0,
                         "Adapter must not be called when credential resolution fails")

    # ── Test 12: adapter without credential_ref works safely ─────────────────

    def test_12_adapter_without_credential_ref_works_safely(self):
        """When no credential_ref is set, dispatch proceeds with creds=None."""
        spy = self._patch_registry_with_spy()
        # No secret_resolver configured (FailClosed by default) but no credential_ref
        # so the resolver is never called.
        ca_id = _insert_connector_account(
            self.db, connector_type="MOCK_ERP",
            config={},  # no credential_ref
        )
        ev_id = _insert_event(self.db, connector_account_id=ca_id)
        self._dispatch(ev_id)

        self.assertEqual(len(spy.calls), 1)
        self.assertFalse(spy.calls[0]["had_credentials"],
                         "runtime_credentials must be None when no credential_ref is set")


if __name__ == "__main__":
    unittest.main()
