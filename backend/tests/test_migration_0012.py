"""Migration 0012 test — exceptions and connector_health_log tables."""
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
_MIGRATION_0012 = _MIGRATIONS_DIR / "0012_exceptions.sql"


def _apply_up_to_0011(db: Database, staging_dir: Path) -> None:
    files = sorted(
        p for p in _MIGRATIONS_DIR.glob("*.sql")
        if p.stem[:4].isdigit() and int(p.stem[:4]) <= 11
    )
    for path in files:
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


def _table_exists(db: Database, name: str) -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return row is not None


class Migration0012Test(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="60online-mig0012-")
        self.db_path = os.path.join(self.tmpdir, "test0012.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_migration_0012_creates_exceptions_table(self):
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        try:
            migrator.upgrade(self.db, self.staging)
        except Exception as exc:
            self.fail(f"Migration 0012 failed: {type(exc).__name__}: {exc}")

        self.assertEqual(migrator.current_version(self.db), "0012")
        self.assertTrue(_table_exists(self.db, "exceptions"))
        self.assertTrue(_table_exists(self.db, "connector_health_log"))

    def test_exceptions_table_has_required_columns(self):
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        migrator.upgrade(self.db, self.staging)

        cols = {r["name"] for r in self.db.query("PRAGMA table_info(exceptions)")}
        required = {
            "id", "exception_type", "severity", "supplier_id", "connector_account_id",
            "sync_run_id", "title", "detail_json", "status", "assigned_to",
            "resolved_by", "resolved_at", "resolution_notes", "retry_count",
            "created_at", "updated_at"
        }
        missing = required - cols
        self.assertEqual(missing, set(), f"Missing columns in exceptions: {missing}")

    def test_no_float_columns_after_0012(self):
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        migrator.upgrade(self.db, self.staging)

        tables = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        offenders = []
        for table in tables:
            for col in self.db.query(f"PRAGMA table_info({table})"):
                declared = (col["type"] or "").upper()
                if any(t in declared for t in ("REAL", "FLOAT", "DOUB")):
                    offenders.append(f"{table}.{col['name']} {declared}")
        self.assertEqual(offenders, [], f"FLOAT columns found: {offenders}")

    def test_can_insert_exception(self):
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        migrator.upgrade(self.db, self.staging)

        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """INSERT INTO exceptions
                   (exception_type, severity, title, detail_json, status, retry_count)
                   VALUES (?,?,?,?,?,?)""",
                ("unknown_product", "medium", "محصول ناشناس", "{}", "open", 0)
            )
            exc_id = int(cur.lastrowid)
        self.assertGreater(exc_id, 0)

    def test_can_insert_connector_health_log(self):
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        migrator.upgrade(self.db, self.staging)

        # Insert a connector account first
        with self.db.write_transaction() as conn:
            ca = conn.execute(
                "INSERT INTO connector_accounts (name, connector_type, config_json) VALUES (?,?,?)",
                ("تست مهاجرت ۱۲", "MANUAL", "{}")
            )
            ca_id = int(ca.lastrowid)

            cur = conn.execute(
                """INSERT INTO connector_health_log
                   (connector_account_id, status, latency_ms, error_message)
                   VALUES (?,?,?,?)""",
                (ca_id, "healthy", 10, None)
            )
            chl_id = int(cur.lastrowid)
        self.assertGreater(chl_id, 0)

    def test_exception_type_check_constraint(self):
        import sqlite3
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        migrator.upgrade(self.db, self.staging)

        with self.assertRaises((sqlite3.IntegrityError, Exception)):
            with self.db.write_transaction() as conn:
                conn.execute(
                    "INSERT INTO exceptions (exception_type, title, detail_json) VALUES (?,?,?)",
                    ("invalid_type_xyz", "Test", "{}")
                )

    def test_fk_check_clean_after_0012(self):
        _apply_up_to_0011(self.db, self.staging)
        shutil.copy(_MIGRATION_0012, self.staging / _MIGRATION_0012.name)
        migrator.upgrade(self.db, self.staging)

        violations = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(len(violations), 0)


if __name__ == "__main__":
    unittest.main()
