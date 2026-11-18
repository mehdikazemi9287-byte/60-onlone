"""Tests for exception_service (exception inbox) — Phase 6 Final."""
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
from app.services import exception_service
from app.core.errors import NotFoundError, ValidationError

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"


def _apply_all(db: Database, staging_dir: Path) -> None:
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


class ExceptionInboxTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="60online-exc-")
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)
        _apply_all(self.db, self.staging)

        # Create a user for resolved_by tests
        with self.db.write_transaction() as conn:
            user = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role) "
                "VALUES (?,?,?,?,?)",
                ("admin@test.com", "admin@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "ادمین تست", "admin")
            )
            self.user_id = int(user.lastrowid)

            sup = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت تست استثنا", "تست استثنا", "9900001234", "retailer", "active", 40)
            )
            self.supplier_id = int(sup.lastrowid)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_exception(self):
        with self.db.write_transaction() as conn:
            exc = exception_service.create_exception(
                conn,
                exception_type="unknown_product",
                title="محصول ناشناس یافت شد",
                severity="medium",
                supplier_id=self.supplier_id,
                detail={"code": "ERP-99999"},
            )
        self.assertIsNotNone(exc["id"])
        self.assertEqual(exc["exception_type"], "unknown_product")
        self.assertEqual(exc["status"], "open")
        self.assertEqual(exc["severity"], "medium")

    def test_list_exceptions_by_status(self):
        with self.db.write_transaction() as conn:
            exception_service.create_exception(conn, exception_type="unknown_product",
                                               title="استثنا ۱", severity="low")
            exception_service.create_exception(conn, exception_type="malformed_data",
                                               title="استثنا ۲", severity="high")

        with self.db.read_transaction() as conn:
            result = exception_service.list_exceptions(conn, status="open")

        self.assertGreaterEqual(result["total"], 2)
        for item in result["items"]:
            self.assertEqual(item["status"], "open")

    def test_list_exceptions_by_type(self):
        with self.db.write_transaction() as conn:
            exception_service.create_exception(conn, exception_type="connector_outage",
                                               title="قطعی اتصال", severity="high")
            exception_service.create_exception(conn, exception_type="unknown_product",
                                               title="محصول ناشناس", severity="medium")

        with self.db.read_transaction() as conn:
            result = exception_service.list_exceptions(conn, exception_type="connector_outage")

        self.assertGreaterEqual(result["total"], 1)
        for item in result["items"]:
            self.assertEqual(item["exception_type"], "connector_outage")

    def test_resolve_exception(self):
        with self.db.write_transaction() as conn:
            exc = exception_service.create_exception(
                conn, exception_type="unknown_product", title="برای حل شدن", severity="low"
            )
            exc_id = exc["id"]

        with self.db.write_transaction() as conn:
            resolved = exception_service.resolve_exception(
                conn, exc_id, resolved_by=self.user_id, resolution_notes="حل شد"
            )

        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolved_by"], self.user_id)
        self.assertIsNotNone(resolved["resolved_at"])

    def test_assign_exception(self):
        with self.db.write_transaction() as conn:
            exc = exception_service.create_exception(
                conn, exception_type="malformed_data", title="برای تفویض", severity="medium"
            )
            exc_id = exc["id"]

        with self.db.write_transaction() as conn:
            assigned = exception_service.assign_exception(
                conn, exc_id, assigned_to=self.user_id
            )

        self.assertEqual(assigned["status"], "assigned")
        self.assertEqual(assigned["assigned_to"], self.user_id)

    def test_bulk_resolve(self):
        ids = []
        with self.db.write_transaction() as conn:
            for i in range(5):
                exc = exception_service.create_exception(
                    conn, exception_type="other", title=f"استثنا {i}", severity="low"
                )
                ids.append(exc["id"])

        with self.db.write_transaction() as conn:
            result = exception_service.bulk_resolve(
                conn, ids, resolved_by=self.user_id, resolution_notes="انبوه حل شد"
            )

        self.assertEqual(result["resolved_count"], 5)
        self.assertEqual(result["total_requested"], 5)

    def test_get_exception_not_found(self):
        with self.db.read_transaction() as conn:
            with self.assertRaises(NotFoundError):
                exception_service.get_exception(conn, 999999)

    def test_invalid_exception_type_raises_validation_error(self):
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError):
                exception_service.create_exception(
                    conn, exception_type="invalid_type_xyz", title="تست", severity="low"
                )

    def test_list_exceptions_by_supplier(self):
        with self.db.write_transaction() as conn:
            exception_service.create_exception(
                conn, exception_type="unknown_product", title="استثنا تأمین‌کننده",
                severity="medium", supplier_id=self.supplier_id
            )

        with self.db.read_transaction() as conn:
            result = exception_service.list_exceptions(conn, supplier_id=self.supplier_id)

        self.assertGreaterEqual(result["total"], 1)

    def test_resolve_idempotent(self):
        """Resolving an already-resolved exception should not fail."""
        with self.db.write_transaction() as conn:
            exc = exception_service.create_exception(
                conn, exception_type="other", title="برای حل تکراری", severity="low"
            )
            exc_id = exc["id"]
            exception_service.resolve_exception(conn, exc_id, resolved_by=self.user_id)
            resolved2 = exception_service.resolve_exception(conn, exc_id, resolved_by=self.user_id)

        self.assertEqual(resolved2["status"], "resolved")

    def test_exception_detail_json_is_dict(self):
        with self.db.write_transaction() as conn:
            exc = exception_service.create_exception(
                conn, exception_type="suspicious_price_jump",
                title="جهش قیمت مشکوک",
                severity="high",
                detail={"old_price": 1000000, "new_price": 5000000, "ratio_bps": 40000},
            )

        self.assertIsInstance(exc["detail_json"], dict)
        self.assertEqual(exc["detail_json"]["old_price"], 1000000)

    def test_bulk_resolve_partial_invalid_ids(self):
        """Bulk resolve should handle invalid IDs gracefully."""
        with self.db.write_transaction() as conn:
            exc = exception_service.create_exception(
                conn, exception_type="other", title="استثنا معتبر", severity="low"
            )
            valid_id = exc["id"]

        with self.db.write_transaction() as conn:
            result = exception_service.bulk_resolve(
                conn, [valid_id, 999999, 888888],
                resolved_by=self.user_id
            )

        self.assertEqual(result["resolved_count"], 1)
        self.assertEqual(result["total_requested"], 3)


if __name__ == "__main__":
    unittest.main()
