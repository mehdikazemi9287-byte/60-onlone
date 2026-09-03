"""Unit tests for identifier_service.py — product identifiers and conflict management."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import NotFoundError, ValidationError
from app.services import identifier_service


class IdentifierServiceTest(AppTestCase):
    """Tests for add_identifier, list_identifiers, delete_identifier,
    resolve_by_identifier, create_conflict, and resolve_conflict."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_supplier_and_product(self):
        """Return (supplier_id, product_id, offer_id) for a fresh test fixture."""
        sup = self.create_test_supplier()
        prod = self.create_test_product_with_offer(
            sup["supplier_id"], sup["location_id"]
        )
        return sup["supplier_id"], prod["product_id"], prod["offer_id"]

    def _add_barcode(self, product_id: int, supplier_id: int,
                     value: str = "6260001234567") -> dict:
        with self.db.write_transaction() as conn:
            return identifier_service.add_identifier(
                conn,
                product_id=product_id,
                supplier_id=supplier_id,
                identifier_type="barcode",
                identifier_value=value,
            )

    # ── test methods ──────────────────────────────────────────────────────────

    def test_add_identifier_barcode(self):
        """add_identifier with type=barcode stores the row correctly."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        row = self._add_barcode(product_id, supplier_id, "6260001111111")

        self.assertEqual(row["product_id"], product_id)
        self.assertEqual(row["supplier_id"], supplier_id)
        self.assertEqual(row["identifier_type"], "barcode")
        self.assertEqual(row["identifier_value"], "6260001111111")
        self.assertEqual(row["namespace"], "")
        self.assertIsNotNone(row["id"])

    def test_add_identifier_unique_constraint(self):
        """Duplicate (type, value, namespace, supplier_id) raises ValidationError."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        self._add_barcode(product_id, supplier_id, "6260009999999")

        with self.assertRaises(ValidationError):
            self._add_barcode(product_id, supplier_id, "6260009999999")

    def test_list_identifiers_by_product(self):
        """list_identifiers filters by product_id."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        _, other_product_id, _ = self._make_supplier_and_product()

        self._add_barcode(product_id, supplier_id, "6260001000001")
        self._add_barcode(other_product_id, supplier_id, "6260001000002")

        with self.db.read_transaction() as conn:
            rows = identifier_service.list_identifiers(conn, product_id=product_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["identifier_value"], "6260001000001")

    def test_list_identifiers_by_type(self):
        """list_identifiers filters by identifier_type."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        with self.db.write_transaction() as conn:
            identifier_service.add_identifier(
                conn, product_id=product_id, supplier_id=supplier_id,
                identifier_type="barcode", identifier_value="6260002000001",
            )
            identifier_service.add_identifier(
                conn, product_id=product_id, supplier_id=supplier_id,
                identifier_type="sku", identifier_value="MY-SKU-001",
            )

        with self.db.read_transaction() as conn:
            barcodes = identifier_service.list_identifiers(conn, identifier_type="barcode")
            skus     = identifier_service.list_identifiers(conn, identifier_type="sku")

        barcode_values = [r["identifier_value"] for r in barcodes]
        sku_values     = [r["identifier_value"] for r in skus]
        self.assertIn("6260002000001", barcode_values)
        self.assertIn("MY-SKU-001", sku_values)
        self.assertNotIn("MY-SKU-001", barcode_values)

    def test_delete_identifier(self):
        """delete_identifier removes the row from the table."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        row = self._add_barcode(product_id, supplier_id, "6260003000001")
        identifier_id = row["id"]

        with self.db.write_transaction() as conn:
            identifier_service.delete_identifier(conn, identifier_id=identifier_id)

        with self.db.read_transaction() as conn:
            remaining = identifier_service.list_identifiers(conn, product_id=product_id)

        ids_remaining = [r["id"] for r in remaining]
        self.assertNotIn(identifier_id, ids_remaining)

    def test_delete_wrong_supplier_raises(self):
        """delete_identifier raises ValidationError when supplier_id doesn't match."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        other_sup = self.create_test_supplier()
        other_supplier_id = other_sup["supplier_id"]

        row = self._add_barcode(product_id, supplier_id, "6260004000001")
        identifier_id = row["id"]

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                identifier_service.delete_identifier(
                    conn,
                    identifier_id=identifier_id,
                    supplier_id=other_supplier_id,
                )

    def test_resolve_by_identifier_found(self):
        """resolve_by_identifier returns a dict containing product_id when found."""
        supplier_id, product_id, _ = self._make_supplier_and_product()
        self._add_barcode(product_id, supplier_id, "6260005000001")

        with self.db.read_transaction() as conn:
            result = identifier_service.resolve_by_identifier(
                conn,
                identifier_type="barcode",
                identifier_value="6260005000001",
            )

        self.assertIsNotNone(result, "resolve_by_identifier must return a dict when identifier exists")
        self.assertEqual(result["product_id"], product_id)
        self.assertEqual(result["identifier_type"], "barcode")
        self.assertEqual(result["identifier_value"], "6260005000001")

    def test_resolve_by_identifier_not_found(self):
        """resolve_by_identifier returns None when identifier does not exist."""
        with self.db.read_transaction() as conn:
            result = identifier_service.resolve_by_identifier(
                conn,
                identifier_type="barcode",
                identifier_value="9999999999999",
            )
        self.assertIsNone(result)

    def test_create_conflict(self):
        """create_conflict inserts a row with status='open'."""
        supplier_id, product_id_a, _ = self._make_supplier_and_product()
        _, product_id_b, _ = self._make_supplier_and_product()

        with self.db.write_transaction() as conn:
            conflict = identifier_service.create_conflict(
                conn,
                product_id_a=product_id_a,
                product_id_b=product_id_b,
                identifier_type="barcode",
                identifier_value="6260006000001",
            )

        self.assertEqual(conflict["status"], "open")
        self.assertEqual(conflict["product_id_a"], product_id_a)
        self.assertEqual(conflict["product_id_b"], product_id_b)
        self.assertIsNone(conflict["resolved_by"])

    def test_resolve_conflict_resolved_merge(self):
        """resolve_conflict with 'resolved_merge' updates status correctly."""
        supplier_id, product_id_a, _ = self._make_supplier_and_product()
        _, product_id_b, _ = self._make_supplier_and_product()

        # Need a user_id to pass as resolved_by
        with self.db.read_transaction() as conn:
            user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        self.assertIsNotNone(user_row, "At least one user must exist in seeded DB")
        user_id = user_row["id"]

        with self.db.write_transaction() as conn:
            conflict = identifier_service.create_conflict(
                conn,
                product_id_a=product_id_a,
                product_id_b=product_id_b,
                identifier_type="barcode",
                identifier_value="6260007000001",
            )
            conflict_id = conflict["id"]

        with self.db.write_transaction() as conn:
            updated = identifier_service.resolve_conflict(
                conn,
                conflict_id=conflict_id,
                resolution="resolved_merge",
                resolved_by=user_id,
                notes="ادغام شد",
            )

        self.assertEqual(updated["status"], "resolved_merge")
        self.assertEqual(updated["resolved_by"], user_id)
        self.assertIsNotNone(updated["resolved_at"])

    def test_resolve_conflict_invalid_resolution_raises(self):
        """resolve_conflict raises ValidationError for an invalid resolution string."""
        supplier_id, product_id_a, _ = self._make_supplier_and_product()
        _, product_id_b, _ = self._make_supplier_and_product()

        with self.db.write_transaction() as conn:
            conflict = identifier_service.create_conflict(
                conn,
                product_id_a=product_id_a,
                product_id_b=product_id_b,
                identifier_type="barcode",
                identifier_value="6260008000001",
            )
            conflict_id = conflict["id"]

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                identifier_service.resolve_conflict(
                    conn,
                    conflict_id=conflict_id,
                    resolution="not_a_real_resolution",
                    resolved_by=1,
                )


if __name__ == "__main__":
    unittest.main()
