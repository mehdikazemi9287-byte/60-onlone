"""Phase 7 — Circuit Breaker tests.

Tests:
  - CLOSED → OPEN after threshold failures
  - CLOSED → stays CLOSED on success (failure count reset)
  - OPEN → HALF_OPEN after recovery window elapses
  - HALF_OPEN + success → CLOSED
  - HALF_OPEN + failure → OPEN again
  - Manual reset → CLOSED
  - is_open() returns True only when OPEN
  - get_health_summary() returns all connector accounts
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.services import circuit_breaker_service as cb


class TestCircuitBreaker(AppTestCase):
    """Uses real DB; requires connector_accounts table from migration 0001+."""

    def _create_connector(self, name: str = "test-connector") -> int:
        """Create a minimal connector_account and return its id."""
        with self.app.app_context():
            from app.core.db import write_transaction
            with write_transaction() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO connector_accounts
                        (name, connector_type, supplier_id, status, created_at, updated_at)
                    VALUES (?, 'MOCK_ERP', 1, 'active', datetime('now'), datetime('now'))
                    """,
                    (name,),
                )
                return cur.lastrowid

    def test_initial_state_is_closed(self):
        with self.app.app_context():
            cid = self._create_connector("cb-initial")
            state = cb.get_state(cid)
            self.assertEqual(state["state"], cb.STATE_CLOSED)
            self.assertEqual(state["failure_count"], 0)
            self.assertFalse(state["is_open"])

    def test_closed_to_open_after_threshold(self):
        with self.app.app_context():
            cid = self._create_connector("cb-open")
            threshold = 3
            for i in range(threshold):
                new_state = cb.record_failure(cid, failure_threshold=threshold)
            self.assertEqual(new_state, cb.STATE_OPEN)
            self.assertTrue(cb.is_open(cid))

    def test_success_resets_failure_count(self):
        with self.app.app_context():
            cid = self._create_connector("cb-reset")
            cb.record_failure(cid, failure_threshold=5)
            cb.record_failure(cid, failure_threshold=5)
            cb.record_success(cid)
            state = cb.get_state(cid)
            self.assertEqual(state["failure_count"], 0)
            self.assertEqual(state["state"], cb.STATE_CLOSED)

    def test_half_open_success_closes(self):
        """Simulate HALF_OPEN → CLOSED transition."""
        with self.app.app_context():
            from app.core.db import write_transaction
            cid = self._create_connector("cb-halfopen-success")
            # Manually set to HALF_OPEN
            with write_transaction() as conn:
                conn.execute(
                    "UPDATE connector_accounts SET circuit_breaker_state='HALF_OPEN' WHERE id=?",
                    (cid,),
                )
            new_state = cb.record_success(cid)
            self.assertEqual(new_state, cb.STATE_CLOSED)
            self.assertFalse(cb.is_open(cid))

    def test_half_open_failure_reopens(self):
        """HALF_OPEN + failure → OPEN again."""
        with self.app.app_context():
            from app.core.db import write_transaction
            cid = self._create_connector("cb-halfopen-fail")
            with write_transaction() as conn:
                conn.execute(
                    "UPDATE connector_accounts SET circuit_breaker_state='HALF_OPEN' WHERE id=?",
                    (cid,),
                )
            new_state = cb.record_failure(cid, failure_threshold=3)
            self.assertEqual(new_state, cb.STATE_OPEN)
            self.assertTrue(cb.is_open(cid))

    def test_manual_reset_closes_open_circuit(self):
        with self.app.app_context():
            cid = self._create_connector("cb-manual-reset")
            for _ in range(5):
                cb.record_failure(cid, failure_threshold=3)
            self.assertTrue(cb.is_open(cid))
            cb.reset(cid)
            self.assertFalse(cb.is_open(cid))
            state = cb.get_state(cid)
            self.assertEqual(state["failure_count"], 0)

    def test_open_transitions_to_half_open_after_window(self):
        """If circuit_breaker_until is in the past, get_state auto-transitions to HALF_OPEN."""
        with self.app.app_context():
            from app.core.db import write_transaction
            cid = self._create_connector("cb-auto-halfopen")
            # Set OPEN with past expiry
            with write_transaction() as conn:
                conn.execute(
                    """
                    UPDATE connector_accounts
                    SET circuit_breaker_state='OPEN',
                        circuit_breaker_until='2020-01-01T00:00:00+00:00'
                    WHERE id=?
                    """,
                    (cid,),
                )
            state = cb.get_state(cid)
            self.assertEqual(state["state"], cb.STATE_HALF_OPEN)

    def test_get_health_summary_includes_all_connectors(self):
        with self.app.app_context():
            cid = self._create_connector("cb-summary")
            summary = cb.get_health_summary()
            ids = [s["connector_account_id"] for s in summary]
            self.assertIn(cid, ids)

    def test_is_open_false_for_closed_circuit(self):
        with self.app.app_context():
            cid = self._create_connector("cb-is-open-false")
            self.assertFalse(cb.is_open(cid))

    def test_is_open_true_for_open_circuit(self):
        with self.app.app_context():
            cid = self._create_connector("cb-is-open-true")
            for _ in range(3):
                cb.record_failure(cid, failure_threshold=3)
            self.assertTrue(cb.is_open(cid))


if __name__ == "__main__":
    unittest.main()
