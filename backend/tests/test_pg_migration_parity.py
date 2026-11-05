"""Every SQLite migration must have a PostgreSQL twin, or production on PostgreSQL silently falls behind.

Runs without a PostgreSQL server. Applying the twins on a real server is covered by
test_phase8_postgresql_migrations (needs DATABASE_URL=postgresql://... and psycopg2).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sqlite_to_pg_migration import convert  # noqa: E402

# SQLite-only files whose effect PostgreSQL gets elsewhere (0024 adds orders.tax_minor on PostgreSQL).
NO_TWIN_NEEDED = {"0023_orders_tax_minor.sql"}


class PgMigrationParityTest(unittest.TestCase):
    def test_every_sqlite_migration_has_a_postgresql_twin(self):
        sqlite = {p.name for p in (ROOT / "migrations").glob("*.sql")}
        pg = {p.name for p in (ROOT / "migrations_postgresql").glob("*.sql")}
        missing = sorted(sqlite - pg - NO_TWIN_NEEDED)
        self.assertEqual(missing, [], "run: python3 scripts/sqlite_to_pg_migration.py <file> and apply it on PostgreSQL")

    def test_converter_keeps_statements_after_triggers(self):
        sql = (
            "CREATE TABLE a (id INTEGER PRIMARY KEY AUTOINCREMENT, total_minor INTEGER NOT NULL,"
            " created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')));\n"
            "CREATE TRIGGER a_no_update BEFORE UPDATE ON a BEGIN SELECT RAISE(ABORT, 'no'); END;\n"
            "CREATE TRIGGER a_touch AFTER UPDATE OF total_minor ON a WHEN OLD.total_minor IS NOT NEW.total_minor\n"
            "BEGIN UPDATE a SET total_minor = NEW.total_minor WHERE id = NEW.id; END;\n"
            "CREATE INDEX a_total ON a(total_minor);\n"
            "INSERT OR IGNORE INTO a (total_minor) VALUES (1);\n"
        )
        out = convert(sql)
        self.assertIn("BIGSERIAL PRIMARY KEY", out)
        self.assertIn("total_minor BIGINT", out)
        self.assertIn("RAISE EXCEPTION 'no'", out)
        self.assertIn("IF OLD.total_minor IS DISTINCT FROM NEW.total_minor THEN", out)
        self.assertIn("CREATE INDEX a_total", out)  # nothing after a trigger is lost
        self.assertIn("ON CONFLICT DO NOTHING", out)
        self.assertNotIn("strftime", out)


if __name__ == "__main__":
    unittest.main()
