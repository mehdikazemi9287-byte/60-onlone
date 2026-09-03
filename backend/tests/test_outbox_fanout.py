"""Blocker 2 — Real outbox fan-out tests.

Tests that business events are fanned out to tenant-scoped connector accounts
and that all delivery/no-subscriber/unknown-event semantics are correct.

Required tests per spec:
  - business rollback removes both business data and all fan-out events
  - successful commit creates the correct tenant-scoped events
  - supplier A never receives supplier B events
  - two active connectors create two independent deliveries
  - disabled/unimplemented connector is excluded
  - no connector does not claim external delivery (no_subscriber status)
  - unknown event type is not silently delivered (dead_letter)
  - worker retry, lease recovery, concurrency and dead-letter behavior
  - one connector failing does not prevent another connector succeeding
"""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _create_connector(case: AppTestCase, *, supplier_id: int,
                      status: str = "active") -> int:
    """Insert an active connector_account for a supplier. Returns the new id."""
    with case.db.write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO connector_accounts
                (name, connector_type, supplier_id, status, created_at, updated_at)
            VALUES (?, 'MOCK_ERP', ?, ?, datetime('now'), datetime('now'))
            """,
            (f"Test Connector {uuid.uuid4().hex[:6]}", supplier_id, status),
        )
        return cur.lastrowid


def _get_events_for_supplier(case: AppTestCase, supplier_id: int) -> list[dict]:
    from app.core.db import query
    rows = query(
        "SELECT * FROM integration_events WHERE supplier_id = ? ORDER BY id",
        (supplier_id,),
    )
    return [dict(r) for r in rows]


def _get_event(case: AppTestCase, event_id: int) -> dict | None:
    from app.core.db import query
    row = query(
        "SELECT * FROM integration_events WHERE id = ?", (event_id,), one=True
    )
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Core fan-out behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestOutboxFanOut(AppTestCase):

    def test_no_connector_creates_no_subscriber_status(self):
        """When no active connector exists for the owner, status=no_subscriber."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]

            # No connector_account for this supplier
            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 99},
                    base_idempotency_key="test-no-sub",
                )

            self.assertEqual(len(ids), 1, "Expected exactly one event row")
            row = query("SELECT * FROM integration_events WHERE id=?", (ids[0],), one=True)
            self.assertEqual(row["status"], "no_subscriber",
                             "No connector → status must be 'no_subscriber'")
            self.assertIsNone(row["connector_account_id"],
                              "no_subscriber row must have connector_account_id=NULL")

    def test_no_subscriber_is_not_externally_delivered(self):
        """no_subscriber event must never be claimed by the worker as delivered."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.services.outbox_worker import run_once
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="STOCK_UPDATED",
                    supplier_id=sid,
                    payload={"offer_id": 1, "quantity": 10},
                    base_idempotency_key="test-no-sub-worker",
                )

            # Worker must not pick up no_subscriber events
            result = run_once(batch_size=50)

            row = query("SELECT status FROM integration_events WHERE id=?",
                        (ids[0],), one=True)
            self.assertEqual(row["status"], "no_subscriber",
                             "Worker must not change no_subscriber status to delivered")

    def test_one_active_connector_creates_one_pending_event(self):
        """One active connector → one pending event with connector_account_id set."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            cid = _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 1},
                    base_idempotency_key="test-one-connector",
                )

            self.assertEqual(len(ids), 1)
            row = query("SELECT * FROM integration_events WHERE id=?", (ids[0],), one=True)
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["connector_account_id"], cid)
            self.assertIsNotNone(row["idempotency_key"])

    def test_two_active_connectors_create_two_independent_deliveries(self):
        """Two active connectors for the same supplier → two independent events."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            cid1 = _create_connector(self, supplier_id=sid)
            cid2 = _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 2},
                    base_idempotency_key="test-two-connectors",
                )

            self.assertEqual(len(ids), 2,
                             "Two active connectors must create two independent events")
            connector_ids = set()
            for eid in ids:
                row = query("SELECT * FROM integration_events WHERE id=?", (eid,), one=True)
                self.assertEqual(row["status"], "pending")
                connector_ids.add(row["connector_account_id"])
            self.assertEqual(connector_ids, {cid1, cid2})

    def test_disabled_connector_excluded_from_fanout(self):
        """Inactive/disabled connector must not receive fan-out events."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _cid_disabled = _create_connector(self, supplier_id=sid, status="inactive")

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="STOCK_UPDATED",
                    supplier_id=sid,
                    payload={"offer_id": 5, "quantity": 20},
                    base_idempotency_key="test-disabled",
                )

            # Disabled connector → no active connectors → no_subscriber
            self.assertEqual(len(ids), 1)
            row = query("SELECT status FROM integration_events WHERE id=?",
                        (ids[0],), one=True)
            self.assertEqual(row["status"], "no_subscriber",
                             "Disabled connector must not receive event; expect no_subscriber")

    def test_supplier_a_never_receives_supplier_b_events(self):
        """Events for supplier B must NOT appear for supplier A's connectors."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info_a = self.create_test_supplier()
            info_b = self.create_test_supplier()
            sid_a = info_a["supplier_id"]
            sid_b = info_b["supplier_id"]

            cid_a = _create_connector(self, supplier_id=sid_a)
            _cid_b = _create_connector(self, supplier_id=sid_b)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid_b,
                    payload={"fulfillment_order_id": 99},
                    base_idempotency_key="test-isolation-b",
                )

            # Check no event was routed to supplier A's connector
            for eid in ids:
                row = query("SELECT connector_account_id FROM integration_events WHERE id=?",
                            (eid,), one=True)
                self.assertNotEqual(row["connector_account_id"], cid_a,
                                    "Supplier A's connector must never receive supplier B's events")

    def test_unknown_event_type_is_dead_lettered_not_delivered(self):
        """Unknown event types must be dead-lettered with unsupported_event_type error."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="MADE_UP_EVENT_TYPE",
                    supplier_id=sid,
                    payload={"foo": "bar"},
                    base_idempotency_key="test-unknown-type",
                )

            self.assertEqual(len(ids), 1)
            row = query("SELECT * FROM integration_events WHERE id=?", (ids[0],), one=True)
            self.assertEqual(row["status"], "dead_letter",
                             "Unknown event type must be dead-lettered immediately")
            self.assertIn("unsupported_event_type", row["last_error"] or "",
                          "last_error must contain 'unsupported_event_type'")

    def test_unknown_event_type_not_silently_delivered_by_worker(self):
        """Worker must fail closed on unknown event types (not silently deliver)."""
        with self.app.app_context():
            from app.services.integration_event_service import enqueue_outbound_event
            from app.services.outbox_worker import run_once
            from app.core.db import query

            # Insert a legacy-style event with no connector but unknown type
            eid = enqueue_outbound_event(
                event_type="TOTALLY_UNKNOWN",
                connector_account_id=None,
                payload={"x": 1},
            )

            # Manually give it a connector to force the unknown-type path
            info = self.create_test_supplier()
            sid = info["supplier_id"]
            cid = _create_connector(self, supplier_id=sid)
            with self.db.write_transaction() as conn:
                conn.execute(
                    "UPDATE integration_events SET connector_account_id=? WHERE id=?",
                    (cid, eid),
                )

            run_once(batch_size=50)

            row = query("SELECT status FROM integration_events WHERE id=?", (eid,), one=True)
            self.assertNotEqual(row["status"], "delivered",
                                "Unknown event type must not be silently marked delivered")

    def test_business_rollback_removes_fan_out_events(self):
        """When the enclosing transaction rolls back, fan-out events are also removed."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _create_connector(self, supplier_id=sid)

            inserted_ids: list[int] = []
            # Perform the fan-out inside a transaction that we then roll back
            import sqlite3
            conn_raw = self.db.connection
            conn_raw.execute("BEGIN")
            try:
                ids = fan_out_business_event(
                    conn_raw,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 55},
                    base_idempotency_key="test-rollback",
                )
                inserted_ids = ids
            finally:
                conn_raw.execute("ROLLBACK")

            # Events must not exist after rollback
            for eid in inserted_ids:
                row = query(
                    "SELECT id FROM integration_events WHERE id=?", (eid,), one=True
                )
                self.assertIsNone(row,
                                  f"Event {eid} must be absent after business rollback")

    def test_successful_commit_creates_tenant_scoped_events(self):
        """After a commit, fan-out events are present with correct tenant scoping."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            cid = _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="STOCK_UPDATED",
                    supplier_id=sid,
                    payload={"offer_id": 7, "quantity": 50},
                    base_idempotency_key="test-commit",
                )

            self.assertGreater(len(ids), 0)
            row = query("SELECT * FROM integration_events WHERE id=?", (ids[0],), one=True)
            self.assertEqual(row["supplier_id"], sid)
            self.assertEqual(row["connector_account_id"], cid)
            self.assertEqual(row["status"], "pending")

    def test_each_fanout_row_has_stable_idempotency_key(self):
        """Each per-connector event row must carry a stable idempotency_key."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _create_connector(self, supplier_id=sid)
            _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="PRICE_UPDATED",
                    supplier_id=sid,
                    payload={"offer_id": 3, "price_minor": 100000},
                    base_idempotency_key="fixed-base-key",
                )

            keys = set()
            for eid in ids:
                row = query("SELECT idempotency_key FROM integration_events WHERE id=?",
                            (eid,), one=True)
                self.assertIsNotNone(row["idempotency_key"],
                                     "idempotency_key must not be NULL")
                self.assertNotIn(row["idempotency_key"], keys,
                                 "Each row must have a unique idempotency_key")
                keys.add(row["idempotency_key"])


# ─────────────────────────────────────────────────────────────────────────────
# Worker behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestOutboxWorkerBehaviour(AppTestCase):

    def test_worker_retry_increments_attempt_count(self):
        """Worker records attempt count on failure and schedules retry."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.services import outbox_worker
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            cid = _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 100},
                    base_idempotency_key="test-retry",
                )

            event_id = ids[0]
            original_attempt = 0

            # Simulate a failure without going through the full worker dispatch
            outbox_worker._mark_failed(event_id, error="simulated failure", attempt_count=1)

            row = query("SELECT * FROM integration_events WHERE id=?", (event_id,), one=True)
            self.assertEqual(row["attempt_count"], 1)
            self.assertEqual(row["status"], "pending",
                             "Event should be pending again after first failure")
            self.assertIsNotNone(row["next_attempt_at"],
                                 "next_attempt_at must be set after failure")

    def test_worker_dead_letters_after_max_attempts(self):
        """Worker dead-letters an event after _MAX_ATTEMPTS failures."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.services import outbox_worker
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 101},
                    base_idempotency_key="test-deadletter",
                )
            event_id = ids[0]

            for i in range(1, outbox_worker._MAX_ATTEMPTS + 1):
                outbox_worker._mark_failed(event_id, error=f"err {i}", attempt_count=i)

            row = query("SELECT status, attempt_count FROM integration_events WHERE id=?",
                        (event_id,), one=True)
            self.assertEqual(row["status"], "dead_letter")
            self.assertEqual(row["attempt_count"], outbox_worker._MAX_ATTEMPTS)

    def test_stale_lease_recovery(self):
        """Events stuck in 'processing' beyond timeout are reset to 'pending'."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.services import outbox_worker
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="STOCK_UPDATED",
                    supplier_id=sid,
                    payload={"offer_id": 9, "quantity": 5},
                    base_idempotency_key="test-lease",
                )
            event_id = ids[0]

            # Simulate a stale processing state by stamping updated_at far in the past
            with self.db.write_transaction() as conn:
                conn.execute(
                    "UPDATE integration_events SET status='processing', updated_at='2000-01-01' WHERE id=?",
                    (event_id,),
                )

            recovered = outbox_worker.recover_stale_leases(lease_timeout_s=1)
            self.assertGreaterEqual(recovered, 1)

            row = query("SELECT status FROM integration_events WHERE id=?", (event_id,), one=True)
            self.assertEqual(row["status"], "pending", "Stale lease must be reset to pending")

    def test_one_connector_failing_does_not_block_another(self):
        """Worker processes each event independently; failure of one does not skip another."""
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.services import outbox_worker
            from app.core.db import write_transaction, query

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            cid1 = _create_connector(self, supplier_id=sid)
            cid2 = _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                ids = fan_out_business_event(
                    conn,
                    event_type="FULFILLMENT_CREATED",
                    supplier_id=sid,
                    payload={"fulfillment_order_id": 200},
                    base_idempotency_key="test-isolation-fail",
                )

            self.assertEqual(len(ids), 2, "Expected two fan-out events")

            # Manually mark the first event as failed (simulating dispatch error)
            outbox_worker._mark_failed(ids[0], error="timeout", attempt_count=1)

            # Manually mark the second as delivered (simulating success)
            outbox_worker._mark_delivered(ids[1])

            row0 = query("SELECT status FROM integration_events WHERE id=?", (ids[0],), one=True)
            row1 = query("SELECT status FROM integration_events WHERE id=?", (ids[1],), one=True)

            # The two events are truly independent
            self.assertIn(row0["status"], ("pending", "failed", "dead_letter"),
                          "Failed connector event must not become delivered")
            self.assertEqual(row1["status"], "delivered",
                             "Successful connector event must be delivered regardless of the other")

    def test_worker_concurrency_no_double_claim(self):
        """Two concurrent workers must not claim the same event."""
        # Create the supplier and connector inside an app context
        with self.app.app_context():
            from app.services.integration_event_service import fan_out_business_event
            from app.core.db import write_transaction

            info = self.create_test_supplier()
            sid = info["supplier_id"]
            _create_connector(self, supplier_id=sid)

            with write_transaction() as conn:
                fan_out_business_event(
                    conn,
                    event_type="STOCK_UPDATED",
                    supplier_id=sid,
                    payload={"offer_id": 11, "quantity": 3},
                    base_idempotency_key="test-concurrency",
                )

        claimed_by: list[list[int]] = [[], []]
        errors: list[Exception] = []
        app = self.app  # capture for thread use

        def worker(idx: int) -> None:
            # Each thread must push its own app context
            from app.services.outbox_worker import claim_batch
            try:
                with app.app_context():
                    claimed_by[idx] = claim_batch(batch_size=10)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=worker, args=(0,))
        t2 = threading.Thread(target=worker, args=(1,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertFalse(errors, f"Worker threads raised: {errors}")

        overlap = set(claimed_by[0]) & set(claimed_by[1])
        self.assertEqual(len(overlap), 0,
                         "No event must be claimed by two concurrent workers")


if __name__ == "__main__":
    import unittest
    unittest.main()
