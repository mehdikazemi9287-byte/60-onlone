"""Migration 0011 test — product resolution tables on populated DB (from 0010)."""
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
_MIGRATION_0011 = _MIGRATIONS_DIR / "0011_product_resolution.sql"


def _apply_up_to_0010(db: Database, staging_dir: Path) -> None:
    files = sorted(
        p for p in _MIGRATIONS_DIR.glob("*.sql")
        if p.stem[:4].isdigit() and int(p.stem[:4]) <= 10
    )
    for path in files:
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


def _table_exists(db: Database, name: str) -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return row is not None


class Migration0011Test(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="70online-mig0011-")
        self.db_path = os.path.join(self.tmpdir, "test0011.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_base_fixtures(self):
        with self.db.write_transaction() as conn:
            cat = conn.execute(
                "INSERT INTO categories (slug, name_fa) VALUES (?,?)",
                ("test-mig11", "تست مهاجرت ۱۱")
            )
            cat_id = int(cat.lastrowid)
            sup = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت مهاجرت ۱۱", "آزمایشی ۱۱", "1100011000", "retailer", "active", 40)
            )
            supplier_id = int(sup.lastrowid)
        return cat_id, supplier_id

    def test_migration_0011_creates_four_tables(self):
        _apply_up_to_0010(self.db, self.staging)
        self.assertEqual(migrator.current_version(self.db), "0010")

        shutil.copy(_MIGRATION_0011, self.staging / _MIGRATION_0011.name)
        try:
            migrator.upgrade(self.db, self.staging)
        except Exception as exc:
            self.fail(f"Migration 0011 failed: {type(exc).__name__}: {exc}")

        self.assertEqual(migrator.current_version(self.db), "0011")

        for table in ("resolution_attempts", "field_provenance", "knowledge_sources", "import_column_templates"):
            self.assertTrue(_table_exists(self.db, table), f"Table {table} must exist after 0011")

    def test_no_float_columns_after_0011(self):
        _apply_up_to_0010(self.db, self.staging)
        shutil.copy(_MIGRATION_0011, self.staging / _MIGRATION_0011.name)
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

    def test_confidence_bps_is_integer_in_resolution_attempts(self):
        _apply_up_to_0010(self.db, self.staging)
        shutil.copy(_MIGRATION_0011, self.staging / _MIGRATION_0011.name)
        migrator.upgrade(self.db, self.staging)

        cols = {r["name"]: r["type"] for r in self.db.query("PRAGMA table_info(resolution_attempts)")}
        self.assertIn("confidence_bps", cols)
        self.assertIn("INTEGER", cols["confidence_bps"].upper())

    def test_can_insert_resolution_attempt(self):
        _apply_up_to_0010(self.db, self.staging)
        shutil.copy(_MIGRATION_0011, self.staging / _MIGRATION_0011.name)
        migrator.upgrade(self.db, self.staging)

        _, supplier_id = self._insert_base_fixtures()

        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """INSERT INTO resolution_attempts
                   (identifier_type, identifier_value, supplier_id, result,
                    confidence_bps, resolution_method, evidence_json)
                   VALUES (?,?,?,?,?,?,?)""",
                ("barcode", "6260000000001", supplier_id, "matched",
                 10000, "barcode_lookup", "{}")
            )
            ra_id = int(cur.lastrowid)
        self.assertGreater(ra_id, 0)

    def test_can_insert_knowledge_source(self):
        _apply_up_to_0010(self.db, self.staging)
        shutil.copy(_MIGRATION_0011, self.staging / _MIGRATION_0011.name)
        migrator.upgrade(self.db, self.staging)

        with self.db.write_transaction() as conn:
            cur = conn.execute(
                """INSERT INTO knowledge_sources
                   (name, source_type, adapter_key, priority, is_active)
                   VALUES (?,?,?,?,?)""",
                ("mock_catalogue_test", "mock_catalogue", "mock_catalogue", 1, 1)
            )
            ks_id = int(cur.lastrowid)
        self.assertGreater(ks_id, 0)

    def test_fk_check_clean_after_0011(self):
        _apply_up_to_0010(self.db, self.staging)
        shutil.copy(_MIGRATION_0011, self.staging / _MIGRATION_0011.name)
        migrator.upgrade(self.db, self.staging)

        violations = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(len(violations), 0)


if __name__ == "__main__":
    unittest.main()
