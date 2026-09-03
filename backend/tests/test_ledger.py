from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import ConflictError, ValidationError  # noqa: E402
from app.services import ledger_service as L  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


class LedgerTest(AppTestCase):
    seed_data = False

    def _post(self, reference="tx-1", debit=1000, credit=1000):
        with self.db.write_transaction() as conn:
            return L.post_transaction(
                conn,
                reference=reference,
                description="test",
                entries=[
                    L.Entry(L.ACCOUNT_PSP_CLEARING, "debit", debit),
                    L.Entry(L.ACCOUNT_SALES_REVENUE, "credit", credit),
                ],
            )

    def test_balanced_transaction_is_accepted(self):
        self._post()
        with self.db.read_transaction() as conn:
            debits, credits = L.trial_balance(conn)
        self.assertEqual(debits, credits)
        self.assertEqual(debits, 1000)

    def test_unbalanced_transaction_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._post(debit=1000, credit=999)
        with self.db.read_transaction() as conn:
            self.assertEqual(L.trial_balance(conn), (0, 0))

    def test_single_entry_transaction_is_rejected(self):
        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                L.post_transaction(
                    conn, reference="solo", description="",
                    entries=[L.Entry(L.ACCOUNT_PSP_CLEARING, "debit", 100)],
                )

    def test_zero_and_negative_amounts_rejected(self):
        for bad in (0, -5):
            with self.assertRaises(ValidationError):
                with self.db.write_transaction() as conn:
                    L.post_transaction(
                        conn, reference=f"bad{bad}", description="",
                        entries=[
                            L.Entry(L.ACCOUNT_PSP_CLEARING, "debit", bad),
                            L.Entry(L.ACCOUNT_SALES_REVENUE, "credit", bad),
                        ],
                    )

    def test_duplicate_reference_is_rejected(self):
        self._post(reference="dup")
        with self.assertRaises(ConflictError):
            self._post(reference="dup")

    def test_entries_cannot_be_updated(self):
        self._post(reference="immutable-u")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.db.execute("UPDATE ledger_entries SET amount_minor = 1")
        self.assertIn("append-only", str(ctx.exception))

    def test_entries_cannot_be_deleted(self):
        self._post(reference="immutable-d")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.db.execute("DELETE FROM ledger_entries")
        self.assertIn("append-only", str(ctx.exception))

    def test_transactions_cannot_be_mutated(self):
        self._post(reference="immutable-t")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE ledger_transactions SET description = 'x'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM ledger_transactions")

    def test_balances_are_derived_not_stored(self):
        """There is no balance column anywhere in the ledger schema."""
        columns = {
            row["name"]
            for table in ("ledger_accounts", "ledger_entries", "ledger_transactions")
            for row in self.db.query(f"PRAGMA table_info({table})")
        }
        self.assertNotIn("balance", columns)
        self.assertNotIn("balance_minor", columns)

    def test_account_balance_signs_by_account_type(self):
        self._post(reference="signs", debit=7000, credit=7000)
        with self.db.read_transaction() as conn:
            # asset: debit-positive
            self.assertEqual(L.account_balance_minor(conn, L.ACCOUNT_PSP_CLEARING), 7000)
            # revenue: credit-positive
            self.assertEqual(L.account_balance_minor(conn, L.ACCOUNT_SALES_REVENUE), 7000)

    def test_unknown_account_rejected(self):
        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                L.post_transaction(
                    conn, reference="unknown-acct", description="",
                    entries=[
                        L.Entry("9999", "debit", 10),
                        L.Entry(L.ACCOUNT_SALES_REVENUE, "credit", 10),
                    ],
                )

    def test_audit_log_is_append_only(self):
        with self.db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO audit_logs (action, entity_type) VALUES ('t','test')"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE audit_logs SET action = 'x'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM audit_logs")


if __name__ == "__main__":
    unittest.main()
