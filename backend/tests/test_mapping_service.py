"""Unit tests for mapping_service.py — ERP product mapping lifecycle."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import NotFoundError, ValidationError
from app.services import mapping_service


class MappingServiceTest(AppTestCase):
    """Tests for create_mapping, list_mappings, review_mapping,
    delete_mapping, and resolve_erp_code."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_supplier_and_product(self):
        """Return (supplier_id, product_id, offer_id, connector_account_id)."""
        sup  = self.create_test_supplier()
        prod = self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"])

        # Create a connector account for this supplier
        with self.db.write_transaction() as conn:
            ca_cur = conn.execute(
                "INSERT INTO connector_accounts "
                "(name, connector_type, supplier_id, config_json) "
                "VALUES (?,?,?,?)",
                ("حساب آزمایشی", "MANUAL", sup["supplier_id"], "{}"),
            )
            connector_account_id = int(ca_cur.lastrowid)

        return (
            sup["supplier_id"],
            prod["product_id"],
            prod["offer_id"],
            connector_account_id,
        )

    def _create_mapping(self, connector_account_id: int,
                         supplier_id: int, product_id: int,
                         erp_code: str = "ERP-MAP-001") -> dict:
        with self.db.write_transaction() as conn:
            return mapping_service.create_mapping(
                conn,
                connector_account_id=connector_account_id,
                erp_product_code=erp_code,
                product_id=product_id,
                supplier_id=supplier_id,
            )

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_create_mapping_pending_review(self):
        """New mapping always lands in 'pending_review' status."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        mapping = self._create_mapping(account_id, supplier_id, product_id)

        self.assertEqual(mapping["status"], "pending_review")
        self.assertEqual(mapping["erp_product_code"], "ERP-MAP-001")
        self.assertEqual(mapping["connector_account_id"], account_id)
        self.assertIsNone(mapping["reviewed_by"])

    def test_create_mapping_duplicate_raises(self):
        """Duplicate (connector_account_id, erp_product_code) raises ValidationError."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        self._create_mapping(account_id, supplier_id, product_id, "ERP-DUP-001")

        with self.assertRaises(ValidationError):
            self._create_mapping(account_id, supplier_id, product_id, "ERP-DUP-001")

    def test_list_mappings_filter_by_status(self):
        """list_mappings filters by status correctly."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()

        # Create two pending mappings
        m1 = self._create_mapping(account_id, supplier_id, product_id, "ERP-LIST-001")
        m2 = self._create_mapping(account_id, supplier_id, product_id, "ERP-LIST-002")

        # Activate m1 via review
        with self.db.read_transaction() as conn:
            user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        user_id = user_row["id"]

        with self.db.write_transaction() as conn:
            mapping_service.review_mapping(
                conn,
                mapping_id=m1["id"],
                new_status="active",
                reviewed_by=user_id,
                product_id=product_id,
            )

        with self.db.read_transaction() as conn:
            pending = mapping_service.list_mappings(conn, status="pending_review")
            active  = mapping_service.list_mappings(conn, status="active")

        pending_ids = [m["id"] for m in pending]
        active_ids  = [m["id"] for m in active]

        self.assertIn(m2["id"], pending_ids)
        self.assertNotIn(m1["id"], pending_ids)
        self.assertIn(m1["id"], active_ids)
        self.assertNotIn(m2["id"], active_ids)

    def test_review_mapping_approve(self):
        """review_mapping with new_status='active' sets status, product_id, reviewed_by."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        mapping = self._create_mapping(account_id, supplier_id, product_id, "ERP-APPROVE-001")

        with self.db.read_transaction() as conn:
            user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        user_id = user_row["id"]

        with self.db.write_transaction() as conn:
            updated = mapping_service.review_mapping(
                conn,
                mapping_id=mapping["id"],
                new_status="active",
                reviewed_by=user_id,
                product_id=product_id,
            )

        self.assertEqual(updated["status"], "active")
        self.assertEqual(updated["product_id"], product_id)
        self.assertEqual(updated["reviewed_by"], user_id)
        self.assertIsNotNone(updated["reviewed_at"])

    def test_review_mapping_reject(self):
        """review_mapping with new_status='rejected' sets status to rejected."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        mapping = self._create_mapping(account_id, supplier_id, product_id, "ERP-REJECT-001")

        with self.db.read_transaction() as conn:
            user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        user_id = user_row["id"]

        with self.db.write_transaction() as conn:
            updated = mapping_service.review_mapping(
                conn,
                mapping_id=mapping["id"],
                new_status="rejected",
                reviewed_by=user_id,
            )

        self.assertEqual(updated["status"], "rejected")

    def test_delete_mapping(self):
        """delete_mapping removes the row; subsequent get_mapping raises NotFoundError."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        mapping = self._create_mapping(account_id, supplier_id, product_id, "ERP-DEL-001")
        mapping_id = mapping["id"]

        with self.db.write_transaction() as conn:
            mapping_service.delete_mapping(conn, mapping_id)

        with self.assertRaises(NotFoundError):
            with self.db.read_transaction() as conn:
                mapping_service.get_mapping(conn, mapping_id)

    def test_resolve_erp_code_active(self):
        """resolve_erp_code returns dict with product_id for an active mapping."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        mapping = self._create_mapping(account_id, supplier_id, product_id, "ERP-RESOLVE-001")

        with self.db.read_transaction() as conn:
            user_row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        user_id = user_row["id"]

        with self.db.write_transaction() as conn:
            mapping_service.review_mapping(
                conn,
                mapping_id=mapping["id"],
                new_status="active",
                reviewed_by=user_id,
                product_id=product_id,
            )

        with self.db.read_transaction() as conn:
            result = mapping_service.resolve_erp_code(
                conn,
                connector_account_id=account_id,
                erp_product_code="ERP-RESOLVE-001",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["product_id"], product_id)
        self.assertIn("offer_ids", result)
        self.assertIsInstance(result["offer_ids"], list)

    def test_resolve_erp_code_pending_returns_none(self):
        """resolve_erp_code returns None when the mapping is not active."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        self._create_mapping(account_id, supplier_id, product_id, "ERP-PENDING-001")

        with self.db.read_transaction() as conn:
            result = mapping_service.resolve_erp_code(
                conn,
                connector_account_id=account_id,
                erp_product_code="ERP-PENDING-001",
            )

        self.assertIsNone(result, "Pending (non-active) mapping must not resolve")

    def test_review_mapping_invalid_status_raises(self):
        """review_mapping raises ValidationError for an unknown status string."""
        supplier_id, product_id, _, account_id = self._make_supplier_and_product()
        mapping = self._create_mapping(account_id, supplier_id, product_id, "ERP-INVALID-001")

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                mapping_service.review_mapping(
                    conn,
                    mapping_id=mapping["id"],
                    new_status="pending_review",  # not in VALID_REVIEW_STATUSES
                    reviewed_by=1,
                )


if __name__ == "__main__":
    unittest.main()
