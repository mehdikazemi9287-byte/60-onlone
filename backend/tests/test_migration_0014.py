"""Tests for migration 0014 (repair_blockers)."""
import unittest
from tests.base import AppTestCase
from app.services import exception_service


class Migration0014Test(AppTestCase):

    def test_exceptions_has_idempotency_key_column(self):
        """exceptions table must have idempotency_key column after 0014."""
        with self.db.read_transaction() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(exceptions)").fetchall()}
        self.assertIn("idempotency_key", cols)

    def test_three_way_matches_has_line_discrepancy_json_column(self):
        """three_way_matches must have line_discrepancy_json after 0014."""
        with self.db.read_transaction() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(three_way_matches)").fetchall()}
        self.assertIn("line_discrepancy_json", cols)

    def test_exception_idempotency_key_is_nullable(self):
        """idempotency_key must accept NULL."""
        with self.db.read_transaction() as conn:
            sup_id = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()["id"]
        with self.db.write_transaction() as conn:
            conn.execute(
                """INSERT INTO exceptions
                   (exception_type, severity, supplier_id, title, detail_json, status, retry_count)
                   VALUES (?,?,?,?,?,?,?)""",
                ("other", "low", sup_id, "test null key", "{}", "open", 0),
            )
        # If we got here without error, NULL is accepted
        self.assertTrue(True)

    def test_idempotency_dedup_works(self):
        """Creating two exceptions with same idempotency_key returns same record."""
        with self.db.read_transaction() as conn:
            sup_id = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()["id"]

        with self.db.write_transaction() as conn:
            exc1 = exception_service.create_exception(
                conn,
                exception_type="other",
                severity="low",
                supplier_id=sup_id,
                title="test dedup",
                idempotency_key="test:dedup:001",
            )
            exc2 = exception_service.create_exception(
                conn,
                exception_type="other",
                severity="low",
                supplier_id=sup_id,
                title="test dedup (repeat)",
                idempotency_key="test:dedup:001",
            )
        self.assertEqual(exc1["id"], exc2["id"])

    def test_schema_head_is_0015(self):
        """Schema head must be at least 0015 (0014 + idempotency index migration).
        Phase 7 added migrations 0016–0018, so head will be 0018 or higher."""
        from app.core.migrator import current_version
        version = current_version(self.db)
        self.assertGreaterEqual(version, "0015")

    def test_no_float_columns_after_0014(self):
        """No REAL/FLOAT/DOUBLE column types after migration 0014 (checked via PRAGMA)."""
        with self.db.read_transaction() as conn:
            tables = [
                r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            float_cols = []
            for tbl in tables:
                cols = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                for col in cols:
                    col_type = (col["type"] or "").upper()
                    for bad in ("REAL", "FLOAT", "DOUBLE"):
                        if bad == col_type or col_type.startswith(bad):
                            float_cols.append(f"{tbl}.{col['name']} {col['type']}")
        self.assertEqual(
            float_cols, [],
            f"Found forbidden float column types: {float_cols}",
        )


if __name__ == "__main__":
    unittest.main()
