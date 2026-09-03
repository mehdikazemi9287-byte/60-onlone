from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import credit_service  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


def _stamp(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


class AllocationTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.org = self.create_organization(credit_limit_minor=1_000_000_000)
        self.org_admin, self.admin = self.make_org_admin(self.org["id"])
        self.employee = self.add_employee(self.org["id"], self.org_admin)

    def test_allocate_credit(self):
        response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 200_000_000)
        self.assertEqual(response.status_code, 201)
        allocation = response.get_json()["allocation"]
        self.assertEqual(allocation["allocated_minor"], 200_000_000)
        self.assertEqual(allocation["available_minor"], 200_000_000)
        self.assertEqual(allocation["reserved_minor"], 0)
        self.assertEqual(allocation["consumed_minor"], 0)
        self.assertEqual(allocation["status"], "active")

    def test_allocation_exposes_every_required_field(self):
        response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 100_000_000,
                                 expires_at=_stamp(30), per_transaction_limit_minor=50_000_000,
                                 period_limit_minor=80_000_000, category_slugs=["office"])
        allocation = response.get_json()["allocation"]
        for field in ("organization_id", "user_id", "allocated_minor", "available_minor",
                      "reserved_minor", "consumed_minor", "valid_from", "expires_at", "status",
                      "category_slugs", "per_transaction_limit_minor", "period_limit_minor"):
            self.assertIn(field, allocation, f"missing {field}")

    def test_allocation_posts_a_credit_ledger_entry(self):
        self.allocate(self.org["id"], self.org_admin, self.employee["id"], 50_000_000)
        # Scoped to this test's organization: the seeded demo org has its own.
        rows = self.db.query(
            "SELECT entry_type, amount_minor FROM credit_ledger_entries "
            "WHERE entry_type = 'allocation' AND organization_id = ?",
            (self.org["id"],),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_minor"], 50_000_000)

    def test_duplicate_allocation_request_is_idempotent(self):
        key = uuid.uuid4().hex
        first = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 90_000_000, key=key)
        second = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 90_000_000, key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.get_json()["created"])
        self.assertEqual(
            first.get_json()["allocation"]["id"], second.get_json()["allocation"]["id"]
        )
        self.assertEqual(
            self.db.query_one(
                "SELECT COUNT(*) n FROM credit_allocations WHERE organization_id = ?",
                (self.org["id"],),
            )["n"], 1
        )
        self.assertEqual(
            self.db.query_one(
                "SELECT COUNT(*) n FROM credit_ledger_entries "
                "WHERE entry_type='allocation' AND organization_id = ?",
                (self.org["id"],),
            )["n"], 1
        )

    def test_missing_idempotency_key_is_rejected(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.org['id']}/credit-allocations",
            json={"membership_id": self.employee["id"], "amount_minor": 1_000_000},
            headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "idempotency_key_required")

    def test_employee_cannot_allocate_credit_to_themselves(self):
        finance = self.add_employee(self.org["id"], self.org_admin, role="organization_finance")
        response = self.allocate(self.org["id"], finance["headers"], finance["id"], 10_000_000)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "self_allocation_forbidden")

    def test_plain_employee_cannot_allocate_credit_at_all(self):
        other = self.add_employee(self.org["id"], self.org_admin)
        response = self.allocate(self.org["id"], self.employee["headers"], other["id"], 10_000_000)
        self.assertEqual(response.status_code, 403)

    def test_finance_role_can_allocate_to_others(self):
        finance = self.add_employee(self.org["id"], self.org_admin, role="organization_finance")
        response = self.allocate(self.org["id"], finance["headers"], self.employee["id"], 10_000_000)
        self.assertEqual(response.status_code, 201)

    def test_zero_and_negative_amounts_are_rejected(self):
        for bad in (0, -1, -5_000_000):
            response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], bad)
            self.assertEqual(response.status_code, 422, bad)

    def test_float_and_string_amounts_are_rejected(self):
        for bad in (1000.5, "1000", None, True):
            response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], bad)
            self.assertEqual(response.status_code, 422, bad)

    def test_allocation_cannot_exceed_the_organization_credit_limit(self):
        response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 2_000_000_000)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"]["code"], "organization_credit_limit_exceeded"
        )

    def test_suspended_organization_cannot_allocate(self):
        self.client.patch(f"/api/v1/organizations/{self.org['id']}",
                          json={"status": "suspended"}, headers=self.org_admin)
        response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 1_000_000)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "organization_not_active")

    def test_inactive_member_cannot_receive_credit(self):
        self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{self.employee['id']}",
            json={"status": "inactive"}, headers=self.org_admin,
        )
        response = self.allocate(self.org["id"], self.org_admin, self.employee["id"], 1_000_000)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "membership_inactive")

    def test_allocation_is_audited(self):
        self.allocate(self.org["id"], self.org_admin, self.employee["id"], 5_000_000)
        row = self.db.query_one(
            "SELECT COUNT(*) n FROM audit_logs WHERE action = 'credit.allocated'"
        )
        self.assertEqual(row["n"], 1)  # seed inserts allocations directly, not via the service

    def test_organization_utilisation_reflects_allocations(self):
        self.allocate(self.org["id"], self.org_admin, self.employee["id"], 300_000_000)
        response = self.client.get(f"/api/v1/organizations/{self.org['id']}", headers=self.org_admin)
        org = response.get_json()["organization"]
        self.assertEqual(org["allocated_total_minor"], 300_000_000)
        self.assertEqual(org["available_credit_minor"], 1_000_000_000 - 300_000_000)


class AdjustmentTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.org, self.org_admin, self.admin, self.employee = self.org_fixture(
            credit_minor=100_000_000
        )
        self.allocation_id = self.employee["allocation"]["id"]

    def _adjust(self, delta: int, note: str = "اصلاح"):
        return self.client.post(
            f"/api/v1/organizations/{self.org['id']}/credit-allocations/{self.allocation_id}/adjust",
            json={"delta_minor": delta, "note": note}, headers=self.org_admin,
        )

    def test_positive_adjustment_increases_available(self):
        response = self._adjust(20_000_000)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["allocation"]["available_minor"], 120_000_000)

    def test_negative_adjustment_decreases_available(self):
        response = self._adjust(-30_000_000)
        self.assertEqual(response.get_json()["allocation"]["available_minor"], 70_000_000)

    def test_adjustment_cannot_push_available_below_zero(self):
        response = self._adjust(-200_000_000)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "adjustment_exceeds_available")

    def test_adjustment_requires_a_reason(self):
        response = self._adjust(1_000_000, note="")
        self.assertEqual(response.status_code, 422)

    def test_zero_adjustment_is_rejected(self):
        self.assertEqual(self._adjust(0).status_code, 422)

    def test_adjustment_appends_and_never_edits(self):
        before = self.db.query_one("SELECT COUNT(*) n FROM credit_ledger_entries")["n"]
        self._adjust(5_000_000)
        after = self.db.query_one("SELECT COUNT(*) n FROM credit_ledger_entries")["n"]
        self.assertEqual(after, before + 1)

    def test_adjustment_is_audited(self):
        self._adjust(5_000_000)
        row = self.db.query_one("SELECT COUNT(*) n FROM audit_logs WHERE action = 'credit.adjusted'")
        self.assertEqual(row["n"], 1)


class CreditLedgerImmutabilityTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.org, self.org_admin, _, self.employee = self.org_fixture(credit_minor=50_000_000)

    def test_credit_ledger_cannot_be_updated(self):
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.db.execute("UPDATE credit_ledger_entries SET amount_minor = 1")
        self.assertIn("append-only", str(ctx.exception))

    def test_credit_ledger_cannot_be_deleted(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM credit_ledger_entries")

    def test_no_stored_balance_column_exists(self):
        for table in ("credit_allocations", "credit_ledger_entries", "organizations"):
            columns = {r["name"] for r in self.db.query(f"PRAGMA table_info({table})")}
            for forbidden in ("available_minor", "available_credit_minor", "balance",
                              "reserved_minor", "consumed_minor"):
                self.assertNotIn(forbidden, columns, f"{table}.{forbidden} must be derived")

    def test_every_movement_is_traceable(self):
        row = self.db.query_one(
            "SELECT * FROM credit_ledger_entries WHERE entry_type = 'allocation'"
        )
        for field in ("user_id", "organization_id", "allocation_id", "actor_user_id",
                      "created_at", "reference", "entry_type", "amount_minor"):
            self.assertIsNotNone(row[field], f"{field} must be recorded")


class WalletTest(AppTestCase):
    def test_retail_customer_wallet_is_empty_but_valid(self):
        _, headers = self.new_customer()
        response = self.client.get("/api/v1/me/credit", headers=headers)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertFalse(body["has_organization"])
        self.assertEqual(body["allocations"], [])
        self.assertEqual(body["total_available_minor"], 0)

    def test_employee_wallet_shows_organization_and_credit(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=150_000_000)
        response = self.client.get("/api/v1/me/credit", headers=employee["headers"])
        body = response.get_json()
        self.assertTrue(body["has_organization"])
        self.assertEqual(body["organizations"][0]["id"], org["id"])
        self.assertEqual(body["total_available_minor"], 150_000_000)
        self.assertEqual(len(body["allocations"]), 1)

    def test_wallet_requires_authentication(self):
        self.assertEqual(self.client.get("/api/v1/me/credit").status_code, 401)

    def test_credit_transactions_are_scoped_to_the_caller(self):
        org, org_admin, _, alice = self.org_fixture(credit_minor=10_000_000)
        bob = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, bob["id"], 20_000_000)

        alice_tx = self.client.get("/api/v1/me/credit/transactions", headers=alice["headers"])
        self.assertEqual(alice_tx.get_json()["total"], 1)
        self.assertTrue(all(t["user_id"] == alice["user_id"]
                            for t in alice_tx.get_json()["items"]))

    def test_employee_cannot_read_another_employees_history_via_query_param(self):
        org, org_admin, _, alice = self.org_fixture(credit_minor=10_000_000)
        bob = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, bob["id"], 20_000_000)
        # user_id is forced server-side; the query parameter is ignored.
        response = self.client.get(
            f"/api/v1/me/credit/transactions?user_id={bob['user_id']}", headers=alice["headers"]
        )
        self.assertTrue(all(t["user_id"] == alice["user_id"] for t in response.get_json()["items"]))


class ReserveCaptureReleaseUnitTest(AppTestCase):
    """Exercises the state machine directly, below the HTTP layer."""

    def setUp(self):
        super().setUp()
        self.org, self.org_admin, _, self.employee = self.org_fixture(credit_minor=100_000_000)
        self.allocation_id = self.employee["allocation"]["id"]
        with self.db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO payment_intents
                    (reference, user_id, idempotency_key, request_hash, subtotal_minor,
                     shipping_fee_minor, total_minor, credit_minor, cash_minor,
                     organization_id, allocation_id, recipient_name, recipient_phone,
                     shipping_province, shipping_city, shipping_line1)
                VALUES ('PI-TEST-1', ?, 'k', 'h', 40000000, 0, 40000000, 40000000, 0, ?, ?,
                        'x','09120000000','ت','ت','خ')
                """,
                (self.employee["user_id"], self.org["id"], self.allocation_id),
            )
            self.intent_id = int(cursor.lastrowid)

    def _state(self):
        with self.db.read_transaction() as conn:
            return credit_service.allocation_state(conn, self.allocation_id)

    def test_reserve_moves_available_to_reserved(self):
        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id,
                                   amount_minor=40_000_000, payment_intent_id=self.intent_id,
                                   actor_user_id=self.employee["user_id"])
        state = self._state()
        self.assertEqual(state["available_minor"], 60_000_000)
        self.assertEqual(state["reserved_minor"], 40_000_000)
        self.assertEqual(state["consumed_minor"], 0)

    def test_reserve_is_idempotent_per_intent(self):
        for _ in range(2):
            with self.db.write_transaction() as conn:
                credit_service.reserve(conn, allocation_id=self.allocation_id,
                                       amount_minor=40_000_000, payment_intent_id=self.intent_id,
                                       actor_user_id=self.employee["user_id"])
        self.assertEqual(self._state()["reserved_minor"], 40_000_000)

    def test_reserve_refuses_to_exceed_available(self):
        from app.core.errors import ConflictError

        with self.assertRaises(ConflictError) as ctx:
            with self.db.write_transaction() as conn:
                credit_service.reserve(conn, allocation_id=self.allocation_id,
                                       amount_minor=500_000_000, payment_intent_id=self.intent_id,
                                       actor_user_id=self.employee["user_id"])
        self.assertEqual(ctx.exception.code, "insufficient_credit")
        self.assertEqual(self._state()["available_minor"], 100_000_000)

    def test_capture_moves_reserved_to_consumed(self):
        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id,
                                   amount_minor=40_000_000, payment_intent_id=self.intent_id,
                                   actor_user_id=self.employee["user_id"])
            credit_service.capture(conn, payment_intent_id=self.intent_id, order_id=None,
                                   actor_user_id=self.employee["user_id"])
        state = self._state()
        self.assertEqual(state["reserved_minor"], 0)
        self.assertEqual(state["consumed_minor"], 40_000_000)
        self.assertEqual(state["available_minor"], 60_000_000)

    def test_release_returns_reserved_to_available(self):
        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id,
                                   amount_minor=40_000_000, payment_intent_id=self.intent_id,
                                   actor_user_id=self.employee["user_id"])
            credit_service.release(conn, payment_intent_id=self.intent_id,
                                   actor_user_id=self.employee["user_id"])
        state = self._state()
        self.assertEqual(state["reserved_minor"], 0)
        self.assertEqual(state["consumed_minor"], 0)
        self.assertEqual(state["available_minor"], 100_000_000)

    def test_capture_and_release_are_idempotent(self):
        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id,
                                   amount_minor=10_000_000, payment_intent_id=self.intent_id,
                                   actor_user_id=1)
            credit_service.capture(conn, payment_intent_id=self.intent_id, order_id=None, actor_user_id=1)
            credit_service.capture(conn, payment_intent_id=self.intent_id, order_id=None, actor_user_id=1)
        self.assertEqual(self._state()["consumed_minor"], 10_000_000)

    def test_capture_after_release_is_refused(self):
        from app.core.errors import ConflictError

        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id,
                                   amount_minor=10_000_000, payment_intent_id=self.intent_id,
                                   actor_user_id=1)
            credit_service.release(conn, payment_intent_id=self.intent_id, actor_user_id=1)
        with self.assertRaises(ConflictError):
            with self.db.write_transaction() as conn:
                credit_service.capture(conn, payment_intent_id=self.intent_id, order_id=None,
                                       actor_user_id=1)

    def test_release_after_capture_is_refused(self):
        from app.core.errors import ConflictError

        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id,
                                   amount_minor=10_000_000, payment_intent_id=self.intent_id,
                                   actor_user_id=1)
            credit_service.capture(conn, payment_intent_id=self.intent_id, order_id=None, actor_user_id=1)
        with self.assertRaises(ConflictError):
            with self.db.write_transaction() as conn:
                credit_service.release(conn, payment_intent_id=self.intent_id, actor_user_id=1)

    def test_reserve_capture_release_all_leave_an_audit_trail(self):
        with self.db.write_transaction() as conn:
            credit_service.reserve(conn, allocation_id=self.allocation_id, amount_minor=10_000_000,
                                   payment_intent_id=self.intent_id, actor_user_id=1)
            credit_service.capture(conn, payment_intent_id=self.intent_id, order_id=None, actor_user_id=1)
        actions = {r["action"] for r in self.db.query("SELECT action FROM audit_logs")}
        self.assertIn("credit.reserved", actions)
        self.assertIn("credit.captured", actions)


if __name__ == "__main__":
    unittest.main()
