"""Unit tests for csv_import_service.py — two-phase CSV import lifecycle."""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import ValidationError
from app.services import csv_import_service, identifier_service


class CsvImportServiceTest(AppTestCase):
    """Tests for parse_and_validate_csv, create_import_job,
    submit_csv_for_import, and confirm_import."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_supplier_and_offer(self):
        sup  = self.create_test_supplier()
        prod = self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"])
        return sup["supplier_id"], prod["product_id"], prod["offer_id"]

    def _get_any_user_id(self) -> int:
        with self.db.read_transaction() as conn:
            row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        self.assertIsNotNone(row, "At least one user must exist in seeded DB")
        return row["id"]

    def _create_job(self, supplier_id: int, created_by: int, *,
                    filename: str = "test.csv") -> dict:
        with self.db.write_transaction() as conn:
            return csv_import_service.create_import_job(
                conn,
                supplier_id=supplier_id,
                filename=filename,
                created_by=created_by,
            )

    # ── parse & validate tests ────────────────────────────────────────────────

    def test_parse_valid_csv_with_barcode_and_stock(self):
        """CSV with barcode+stock_quantity columns produces all-valid rows."""
        csv_text = textwrap.dedent("""\
            barcode,stock_quantity
            6260001000010,200
            6260001000027,15
            6260001000034,30
        """)
        supplier_id, _, _ = self._make_supplier_and_offer()

        with self.db.read_transaction() as conn:
            result = csv_import_service.parse_and_validate_csv(
                csv_text, supplier_id=supplier_id, conn=conn
            )

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["valid"], 3)
        self.assertEqual(result["errors"], 0)
        for row in result["rows"]:
            self.assertEqual(row["status"], "valid")
            self.assertEqual(row["validation_errors"], [])

    def test_parse_rejects_float_price(self):
        """A row with price_minor='100.5' is marked invalid."""
        csv_text = textwrap.dedent("""\
            barcode,price_minor
            6260001000010,100.5
        """)
        supplier_id, _, _ = self._make_supplier_and_offer()

        with self.db.read_transaction() as conn:
            result = csv_import_service.parse_and_validate_csv(
                csv_text, supplier_id=supplier_id, conn=conn
            )

        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["rows"][0]["status"], "invalid")
        self.assertTrue(len(result["rows"][0]["validation_errors"]) > 0)

    def test_parse_rejects_negative_stock(self):
        """A row with stock_quantity='-5' is marked invalid."""
        csv_text = textwrap.dedent("""\
            barcode,stock_quantity
            6260001000010,-5
        """)
        supplier_id, _, _ = self._make_supplier_and_offer()

        with self.db.read_transaction() as conn:
            result = csv_import_service.parse_and_validate_csv(
                csv_text, supplier_id=supplier_id, conn=conn
            )

        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["rows"][0]["status"], "invalid")

    def test_parse_matches_product_via_barcode(self):
        """A row with a known barcode is resolved to the correct product_id."""
        supplier_id, product_id, _ = self._make_supplier_and_offer()
        barcode = "6260099000001"

        # Register the barcode identifier for our product
        with self.db.write_transaction() as conn:
            identifier_service.add_identifier(
                conn,
                product_id=product_id,
                supplier_id=supplier_id,
                identifier_type="barcode",
                identifier_value=barcode,
            )

        csv_text = f"barcode,stock_quantity\n{barcode},100\n"

        with self.db.read_transaction() as conn:
            result = csv_import_service.parse_and_validate_csv(
                csv_text, supplier_id=supplier_id, conn=conn
            )

        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["rows"][0]["product_id"], product_id)

    # ── job lifecycle tests ───────────────────────────────────────────────────

    def test_create_import_job(self):
        """create_import_job creates a pending job."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()
        job = self._create_job(supplier_id, user_id, filename="import_001.csv")

        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["supplier_id"], supplier_id)
        self.assertEqual(job["filename"], "import_001.csv")
        self.assertEqual(job["total_rows"], 0)
        self.assertIsNotNone(job["id"])

    def test_submit_csv_for_import_previewing(self):
        """submit_csv_for_import with valid CSV transitions job to 'previewing'."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()
        job = self._create_job(supplier_id, user_id)

        csv_text = textwrap.dedent("""\
            barcode,stock_quantity
            6260001000010,100
            6260001000027,20
        """)

        with self.db.write_transaction() as conn:
            updated = csv_import_service.submit_csv_for_import(
                conn,
                import_job_id=job["id"],
                csv_text=csv_text,
                supplier_id=supplier_id,
            )

        self.assertEqual(updated["status"], "previewing")
        self.assertEqual(updated["total_rows"], 2)
        self.assertEqual(updated["valid_rows"], 2)
        self.assertEqual(updated["error_rows"], 0)

    def test_submit_too_many_invalid_rows_fails(self):
        """submit_csv_for_import with >50% invalid rows transitions to 'validation_failed'."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()
        job = self._create_job(supplier_id, user_id)

        # All rows are missing both identifier AND data fields — all invalid
        csv_text = textwrap.dedent("""\
            product_name
            کاغذ A4
            لپ‌تاپ
            گوشی
        """)

        with self.db.write_transaction() as conn:
            updated = csv_import_service.submit_csv_for_import(
                conn,
                import_job_id=job["id"],
                csv_text=csv_text,
                supplier_id=supplier_id,
            )

        self.assertEqual(updated["status"], "validation_failed")

    def test_confirm_import_applies_stock(self):
        """confirm_import applies stock_quantity changes to matching seller_offers."""
        supplier_id, product_id, offer_id = self._make_supplier_and_offer()
        barcode = "6260088000001"
        user_id = self._get_any_user_id()

        # Register identifier for the product
        with self.db.write_transaction() as conn:
            identifier_service.add_identifier(
                conn,
                product_id=product_id,
                supplier_id=supplier_id,
                identifier_type="barcode",
                identifier_value=barcode,
            )

        # Create and submit the job
        job = self._create_job(supplier_id, user_id)
        csv_text = f"barcode,stock_quantity\n{barcode},77\n"

        with self.db.write_transaction() as conn:
            submit_result = csv_import_service.submit_csv_for_import(
                conn,
                import_job_id=job["id"],
                csv_text=csv_text,
                supplier_id=supplier_id,
            )
        self.assertEqual(submit_result["status"], "previewing")

        # Confirm the import
        with self.db.write_transaction() as conn:
            confirm_result = csv_import_service.confirm_import(
                conn,
                import_job_id=job["id"],
                supplier_id=supplier_id,
            )

        self.assertIn(confirm_result["status"], ("completed", "completed_with_errors"))
        self.assertGreaterEqual(confirm_result["applied"], 0)

        # Verify seller_offer stock was updated
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT stock_quantity FROM seller_offers WHERE id = ?",
                (offer_id,),
            ).fetchone()
        self.assertEqual(
            row["stock_quantity"], 77,
            "confirm_import must apply the stock_quantity from the CSV to the seller_offer",
        )

    def test_confirm_import_raises_for_non_previewing(self):
        """confirm_import raises ValidationError when job status is not 'previewing'."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()
        job = self._create_job(supplier_id, user_id)  # status='pending'

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                csv_import_service.confirm_import(
                    conn,
                    import_job_id=job["id"],
                    supplier_id=supplier_id,
                )

    def test_parse_rejects_missing_identifier_and_data(self):
        """A row missing both identifier and data fields is invalid."""
        csv_text = "product_name\nکاغذ A4\n"
        supplier_id, _, _ = self._make_supplier_and_offer()

        with self.db.read_transaction() as conn:
            result = csv_import_service.parse_and_validate_csv(
                csv_text, supplier_id=supplier_id, conn=conn
            )

        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["rows"][0]["status"], "invalid")

    def test_submit_csv_stores_import_job_rows(self):
        """submit_csv_for_import persists import_job_rows in the database."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()
        job = self._create_job(supplier_id, user_id)

        csv_text = "barcode,stock_quantity\n6260001000010,50\n6260001000027,10\n"

        with self.db.write_transaction() as conn:
            csv_import_service.submit_csv_for_import(
                conn,
                import_job_id=job["id"],
                csv_text=csv_text,
                supplier_id=supplier_id,
            )

        with self.db.read_transaction() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) AS n FROM import_job_rows WHERE import_job_id = ?",
                (job["id"],),
            ).fetchone()
        self.assertEqual(rows["n"], 2)


if __name__ == "__main__":
    unittest.main()
