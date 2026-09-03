"""Migration 0013 test — 5 finance tables, no REAL columns."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import Database
from app.core import migrator

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"
_MIGRATION_0013 = _MIGRATIONS_DIR / "0013_finance_automation.sql"


def _apply_up_to_0012(db: Database, staging_dir: Path) -> None:
    files = sorted(
        p for p in _MIGRATIONS_DIR.glob("*.sql")
        if p.stem[:4].isdigit() and int(p.stem[:4]) <= 12
    )
    for path in files:
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


def _table_exists(db: Database, name: str) -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return row is not None


FINANCE_TABLES = [
    "procurement_orders",
    "supplier_invoices",
    "supplier_invoice_lines",
    "three_way_matches",
    "reconciliation_batches",
    "reconciliation_items",
]


class Migration0013Test(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="70online-mig0013-")
        self.db_path = os.path.join(self.tmpdir, "test0013.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_migration_0013_creates_all_finance_tables(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        try:
            migrator.upgrade(self.db, self.staging)
        except Exception as exc:
            self.fail(f"Migration 0013 failed: {type(exc).__name__}: {exc}")

        self.assertEqual(migrator.current_version(self.db), "0013")
        for table in FINANCE_TABLES:
            self.assertTrue(_table_exists(self.db, table), f"Table {table} must exist after 0013")

    def test_no_real_float_columns_in_finance_tables(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        migrator.upgrade(self.db, self.staging)

        offenders = []
        tables = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for table in tables:
            for col in self.db.query(f"PRAGMA table_info({table})"):
                declared = (col["type"] or "").upper()
                if any(t in declared for t in ("REAL", "FLOAT", "DOUB")):
                    offenders.append(f"{table}.{col['name']} {declared}")
        self.assertEqual(offenders, [], f"FLOAT columns found: {offenders}")

    def test_money_columns_in_supplier_invoices_are_integer(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        migrator.upgrade(self.db, self.staging)

        cols = {r["name"]: r["type"] for r in self.db.query("PRAGMA table_info(supplier_invoices)")}
        for field in ("subtotal_minor", "tax_minor", "total_minor"):
            self.assertIn(field, cols)
            self.assertIn("INTEGER", cols[field].upper(), f"{field} must be INTEGER")

    def test_can_insert_supplier_invoice(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        migrator.upgrade(self.db, self.staging)

        # Insert required FK rows
        with self.db.write_transaction() as conn:
            sup = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت فاکتور تست", "فاکتور تست", "1100013000", "retailer", "active", 40)
            )
            supplier_id = int(sup.lastrowid)
            user = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name) VALUES (?,?,?,?)",
                ("inv013@test.com", "inv013@test.com", "$2b$12$aaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "تست فاکتور")
            )
            user_id = int(user.lastrowid)

            cur = conn.execute(
                """INSERT INTO supplier_invoices
                   (supplier_id, invoice_number, invoice_date,
                    subtotal_minor, tax_minor, total_minor, currency,
                    status, source_type, raw_json, is_duplicate,
                    created_by, dedup_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (supplier_id, "INV-001", "2026-08-08",
                 10000000, 1000000, 11000000, "IRR",
                 "captured", "manual", "{}", 0, user_id,
                 "abc123hash")
            )
            inv_id = int(cur.lastrowid)
        self.assertGreater(inv_id, 0)

    def test_three_way_matches_references_fulfillment_orders(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        migrator.upgrade(self.db, self.staging)

        # Verify the FK column exists
        cols = {r["name"] for r in self.db.query("PRAGMA table_info(three_way_matches)")}
        self.assertIn("fulfillment_order_id", cols)
        self.assertIn("procurement_order_id", cols)
        self.assertIn("invoice_id", cols)

    def test_reconciliation_items_has_integer_amount(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        migrator.upgrade(self.db, self.staging)

        cols = {r["name"]: r["type"] for r in self.db.query("PRAGMA table_info(reconciliation_items)")}
        self.assertIn("amount_minor", cols)
        self.assertIn("INTEGER", cols["amount_minor"].upper())

    def test_fk_check_clean_after_0013(self):
        _apply_up_to_0012(self.db, self.staging)
        shutil.copy(_MIGRATION_0013, self.staging / _MIGRATION_0013.name)
        migrator.upgrade(self.db, self.staging)

        violations = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(len(violations), 0)


if __name__ == "__main__":
    unittest.main()
