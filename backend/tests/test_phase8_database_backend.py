"""Phase 8 — Blocker 9: PostgreSQL Executable Readiness tests.

Tests:
  - DatabaseBackend is an ABC
  - SQLiteBackend is a concrete subclass of DatabaseBackend
  - PostgreSQLBackend is a concrete subclass of DatabaseBackend
  - Database is an alias for SQLiteBackend (backward compat)
  - make_backend('sqlite:///...') returns SQLiteBackend
  - make_backend('postgresql://...') raises RuntimeError when psycopg2 unavailable
    (or returns PostgreSQLBackend when psycopg2 is available)
  - SQLiteBackend satisfies the full interface contract
  - PostgreSQLBackend raises a clear error without psycopg2
  - make_backend raises ValueError for unknown scheme
"""
from __future__ import annotations

import abc
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import (
    Database,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
    make_backend,
)


class TestDatabaseBackendABC(unittest.TestCase):
    """DatabaseBackend is a proper ABC."""

    def test_is_abstract(self):
        """DatabaseBackend cannot be instantiated directly."""
        self.assertTrue(inspect.isabstract(DatabaseBackend))

    def test_sqlite_is_subclass(self):
        self.assertTrue(issubclass(SQLiteBackend, DatabaseBackend))

    def test_postgresql_is_subclass(self):
        self.assertTrue(issubclass(PostgreSQLBackend, DatabaseBackend))

    def test_database_alias_is_sqlite(self):
        """Database is a backward-compat alias for SQLiteBackend."""
        self.assertIs(Database, SQLiteBackend)

    def test_sqlite_is_concrete(self):
        """SQLiteBackend is fully concrete (no abstract methods remaining)."""
        self.assertFalse(inspect.isabstract(SQLiteBackend))

    def test_postgresql_is_concrete(self):
        """PostgreSQLBackend is fully concrete (lazy import does not affect this)."""
        self.assertFalse(inspect.isabstract(PostgreSQLBackend))

    def test_required_methods_declared(self):
        """All required interface methods exist on DatabaseBackend."""
        for method in ("write_transaction", "read_transaction", "query",
                       "query_one", "execute", "executescript", "close"):
            self.assertTrue(
                hasattr(DatabaseBackend, method),
                f"DatabaseBackend is missing method: {method}",
            )


class TestSQLiteBackendContract(unittest.TestCase):
    """SQLiteBackend satisfies the DatabaseBackend interface."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="70-db-test-")
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.db = SQLiteBackend(self.db_path)
        # Bootstrap a minimal table
        with self.db.write_transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_instance_of_backend(self):
        self.assertIsInstance(self.db, DatabaseBackend)

    def test_write_and_read(self):
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("hello", "world"))
        row = self.db.query_one("SELECT v FROM kv WHERE k = ?", ("hello",))
        self.assertIsNotNone(row)
        self.assertEqual(row["v"], "world")

    def test_query_returns_list(self):
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("a", "1"))
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("b", "2"))
        rows = self.db.query("SELECT * FROM kv ORDER BY k")
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 2)

    def test_query_one_returns_none_when_missing(self):
        row = self.db.query_one("SELECT v FROM kv WHERE k = ?", ("nonexistent",))
        self.assertIsNone(row)

    def test_write_transaction_rolls_back_on_error(self):
        try:
            with self.db.write_transaction() as conn:
                conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("x", "y"))
                raise ValueError("deliberate failure")
        except ValueError:
            pass
        row = self.db.query_one("SELECT v FROM kv WHERE k = ?", ("x",))
        self.assertIsNone(row)

    def test_read_transaction(self):
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?)", ("r", "read"))
        with self.db.read_transaction() as conn:
            row = conn.execute("SELECT v FROM kv WHERE k = ?", ("r",)).fetchone()
        self.assertIsNotNone(row)

    def test_executescript(self):
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS t2 (id INTEGER PRIMARY KEY);"
            "INSERT OR IGNORE INTO t2 (id) VALUES (1);"
        )
        row = self.db.query_one("SELECT id FROM t2 WHERE id = 1")
        self.assertIsNotNone(row)

    def test_close_and_reconnect(self):
        self.db.close()
        # After close, a new connection is created on access
        row = self.db.query_one("SELECT v FROM kv WHERE k = ?", ("nonexistent",))
        self.assertIsNone(row)


class TestMakeBackend(unittest.TestCase):
    """make_backend() factory picks the right backend."""

    def test_sqlite_url_returns_sqlite_backend(self):
        b = make_backend("sqlite:////tmp/factory_test.db")
        self.assertIsInstance(b, SQLiteBackend)
        b.close()

    def test_postgresql_url_raises_without_psycopg2(self):
        """PostgreSQLBackend raises RuntimeError if psycopg2 is not installed."""
        try:
            import psycopg2  # noqa
            # psycopg2 is available; we can still test the factory returns PG backend
            b = make_backend("postgresql://localhost/testdb")
            self.assertIsInstance(b, PostgreSQLBackend)
        except ImportError:
            # psycopg2 not installed — expected path in this environment
            with self.assertRaises(RuntimeError) as ctx:
                make_backend("postgresql://localhost/testdb")
            self.assertIn("psycopg2", str(ctx.exception))

    def test_postgres_alias_url_works(self):
        """postgres:// (without ql) is also accepted."""
        try:
            import psycopg2  # noqa
            b = make_backend("postgres://localhost/testdb")
            self.assertIsInstance(b, PostgreSQLBackend)
        except ImportError:
            with self.assertRaises(RuntimeError):
                make_backend("postgres://localhost/testdb")

    def test_unknown_scheme_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            make_backend("mysql://localhost/testdb")
        self.assertIn("mysql", str(ctx.exception).lower())


class TestPostgreSQLBackendWithoutDriver(unittest.TestCase):
    """PostgreSQLBackend gives a clear error when psycopg2 is absent."""

    def test_instantiation_without_psycopg2_raises_runtime_error(self):
        try:
            import psycopg2  # noqa
            self.skipTest("psycopg2 is installed; skip the 'missing driver' test")
        except ImportError:
            pass

        with self.assertRaises(RuntimeError) as ctx:
            PostgreSQLBackend("postgresql://localhost/testdb")
        msg = str(ctx.exception)
        self.assertIn("psycopg2", msg)
        # Error must tell operator how to fix it
        self.assertIn("pip install", msg)

    def test_class_is_importable_without_psycopg2(self):
        """The class itself must be importable even when psycopg2 is absent."""
        # Just importing the class is the test — no exception should be raised here
        from app.core.db import PostgreSQLBackend as PGB  # noqa: F401


if __name__ == "__main__":
    unittest.main()
