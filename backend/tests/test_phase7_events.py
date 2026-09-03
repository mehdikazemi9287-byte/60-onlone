"""Phase 7 — Integration Events tests.

Tests:
  - enqueue_outbound_event: creates pending event
  - enqueue_inbound_event: idempotent (duplicate external_event_id rejected)
  - mark_event_delivered: status → delivered
  - mark_event_failed: increments attempt, schedules retry, dead-letters at max
  - fetch_pending_events: only returns past-due events
  - replay_dead_letter_event: resets to pending
  - mark_consumed: idempotent consumer tracking
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


class TestIntegrationEventService(AppTestCase):

    def test_enqueue_outbound_event(self):
        with self.app.app_context():
            from app.services.integration_event_service import (
                enqueue_outbound_event, fetch_pending_events
            )
            event_id = enqueue_outbound_event(
                event_type="invoice.export",
                connector_account_id=None,
                supplier_id=1,
                payload={"order_id": 42},
            )
            self.assertIsNotNone(event_id)
            self.assertGreater(event_id, 0)

            events = fetch_pending_events(limit=100)
            event_ids = [e["id"] for e in events]
            self.assertIn(event_id, event_ids)

    def test_mark_event_delivered(self):
        with self.app.app_context():
            from app.services.integration_event_service import (
                enqueue_outbound_event, mark_event_delivered
            )
            from app.core.db import query
            event_id = enqueue_outbound_event(
                event_type="invoice.export",
                payload={"order_id": 1},
            )
            mark_event_delivered(event_id)
            row = query(
                "SELECT status FROM integration_events WHERE id=?",
                (event_id,),
                one=True,
            )
            self.assertEqual(row["status"], "delivered")

    def test_mark_event_failed_schedules_retry(self):
        with self.app.app_context():
            from app.services.integration_event_service import (
                enqueue_outbound_event, mark_event_failed
            )
            from app.core.db import query
            event_id = enqueue_outbound_event(
                event_type="invoice.export",
                payload={"order_id": 2},
            )
            mark_event_failed(event_id, error="Connection refused")
            row = query(
                "SELECT status, attempt_count, next_attempt_at FROM integration_events WHERE id=?",
                (event_id,),
                one=True,
            )
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["attempt_count"], 1)
            self.assertIsNotNone(row["next_attempt_at"])

    def test_mark_event_dead_lettered_after_max_attempts(self):
        with self.app.app_context():
            from app.services import integration_event_service as svc
            from app.core.db import query
            event_id = svc.enqueue_outbound_event(
                event_type="invoice.export",
                payload={"order_id": 3},
            )
            # Simulate MAX_ATTEMPTS failures
            for i in range(svc._MAX_ATTEMPTS):
                svc.mark_event_failed(event_id, error=f"error {i}")

            row = query(
                "SELECT status, attempt_count FROM integration_events WHERE id=?",
                (event_id,),
                one=True,
            )
            self.assertEqual(row["status"], "dead_letter")
            self.assertEqual(row["attempt_count"], svc._MAX_ATTEMPTS)

    def _get_or_create_connector(self) -> int:
        """Return a valid connector_account id, creating one if needed."""
        from app.core.db import write_transaction, query
        row = query("SELECT id FROM connector_accounts LIMIT 1", (), one=True)
        if row:
            return row["id"]
        with write_transaction() as conn:
            row_sup = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()
            supplier_id = row_sup["id"] if row_sup else None
            cur = conn.execute(
                """
                INSERT INTO connector_accounts
                    (name, connector_type, supplier_id, status, created_at, updated_at)
                VALUES ('Test Connector', 'MOCK_ERP', ?, 'active', datetime('now'), datetime('now'))
                """,
                (supplier_id,),
            )
            return cur.lastrowid

    def test_inbound_event_idempotent(self):
        """Same external_event_id for same connector_account → second insert returns None."""
        with self.app.app_context():
            from app.services.integration_event_service import enqueue_inbound_event
            connector_id = self._get_or_create_connector()
            event_id1 = enqueue_inbound_event(
                event_type="shipment.update",
                connector_account_id=connector_id,
                external_event_id="ext-event-123",
                payload={"status": "in_transit"},
            )
            event_id2 = enqueue_inbound_event(
                event_type="shipment.update",
                connector_account_id=connector_id,
                external_event_id="ext-event-123",
                payload={"status": "in_transit"},
            )
            self.assertIsNotNone(event_id1)
            self.assertIsNone(event_id2)  # duplicate rejected

    def test_replay_dead_letter(self):
        with self.app.app_context():
            from app.services import integration_event_service as svc
            from app.core.db import query
            event_id = svc.enqueue_outbound_event(
                event_type="invoice.export",
                payload={"order_id": 4},
            )
            # Force to dead_letter
            for i in range(svc._MAX_ATTEMPTS):
                svc.mark_event_failed(event_id, error="err")

            replayed = svc.replay_dead_letter_event(event_id)
            self.assertTrue(replayed)

            row = query(
                "SELECT status FROM integration_events WHERE id=?",
                (event_id,), one=True
            )
            self.assertEqual(row["status"], "pending")

    def test_replay_non_dead_letter_returns_false(self):
        with self.app.app_context():
            from app.services import integration_event_service as svc
            event_id = svc.enqueue_outbound_event(
                event_type="invoice.export",
                payload={"order_id": 5},
            )
            replayed = svc.replay_dead_letter_event(event_id)
            self.assertFalse(replayed)  # not dead_letter

    def test_mark_consumed_idempotent(self):
        with self.app.app_context():
            from app.services.integration_event_service import (
                enqueue_outbound_event, mark_consumed
            )
            event_id = enqueue_outbound_event(
                event_type="invoice.export",
                payload={"order_id": 6},
            )
            first = mark_consumed(event_id, consumer_name="accounting_consumer")
            second = mark_consumed(event_id, consumer_name="accounting_consumer")
            self.assertTrue(first)
            self.assertFalse(second)

    def test_fetch_dead_letter_events(self):
        with self.app.app_context():
            from app.services import integration_event_service as svc
            event_id = svc.enqueue_outbound_event(
                event_type="test.dead",
                payload={"x": 1},
            )
            for i in range(svc._MAX_ATTEMPTS):
                svc.mark_event_failed(event_id, error="err")

            dead = svc.fetch_dead_letter_events(limit=100)
            dead_ids = [e["id"] for e in dead]
            self.assertIn(event_id, dead_ids)


if __name__ == "__main__":
    unittest.main()
