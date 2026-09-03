"""Phase 7 — Product Identity Graph tests.

Tests:
  - resolve_identifier: all 4 stages
  - register_identifier: creates / idempotent
  - queue_for_review: unresolved items
  - resolve_batch: batch API
  - Identifier type constants
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


class TestProductIdentityService(AppTestCase):
    """Tests run against a real migrated database (migrations 0001–0018)."""

    def _create_product(self, name: str = "Test Product") -> int:
        """Helper: insert a minimal product and return its id."""
        import time, random
        with self.app.app_context():
            from app.core.db import write_transaction
            # Ensure there's a category to reference
            with write_transaction() as conn:
                cat = conn.execute(
                    "SELECT id FROM categories LIMIT 1"
                ).fetchone()
                if cat is None:
                    cur_cat = conn.execute(
                        "INSERT INTO categories (name_fa, name_en, slug) VALUES (?, ?, ?)",
                        ("عمومی", "General", "general"),
                    )
                    cat_id = cur_cat.lastrowid
                else:
                    cat_id = cat["id"]
                unique = f"{int(time.time()*1000)}{random.randint(0,9999)}"
                cur = conn.execute(
                    """
                    INSERT INTO products
                        (slug, sku, title_fa, description_fa, category_id, base_price_minor, created_at)
                    VALUES (?, ?, ?, '', ?, 0, datetime('now'))
                    """,
                    (f"test-{unique}", f"SKU-{unique}", name, cat_id),
                )
                return cur.lastrowid

    def test_resolve_global_gtin_found(self):
        """Stage 1: global GTIN resolves correctly."""
        with self.app.app_context():
            from app.services.product_identity_service import (
                register_identifier, resolve_identifier
            )
            product_id = self._create_product("GTIN Product")
            register_identifier(product_id, "GTIN13", "1234567890123")
            result = resolve_identifier("GTIN13", "1234567890123")
            self.assertTrue(result["resolved"])
            self.assertEqual(result["product_id"], product_id)
            self.assertEqual(result["stage"], "stage1_global_gtin")
            self.assertEqual(result["confidence_bps"], 1000)

    def test_resolve_supplier_sku(self):
        """Stage 2: supplier-scoped SKU resolves correctly."""
        with self.app.app_context():
            from app.services.product_identity_service import (
                register_identifier, resolve_identifier
            )
            product_id = self._create_product("SKU Product")
            register_identifier(product_id, "SUPPLIER_SKU", "MY-SKU-001", supplier_id=1)
            result = resolve_identifier("SUPPLIER_SKU", "MY-SKU-001", supplier_id=1)
            self.assertTrue(result["resolved"])
            self.assertEqual(result["product_id"], product_id)
            self.assertEqual(result["stage"], "stage2_supplier_sku")

    def test_resolve_unscoped_sku_no_supplier_fails(self):
        """SUPPLIER_SKU without supplier_id = unresolved."""
        with self.app.app_context():
            from app.services.product_identity_service import (
                register_identifier, resolve_identifier
            )
            product_id = self._create_product("SKU Product 2")
            register_identifier(product_id, "SUPPLIER_SKU", "MY-SKU-002", supplier_id=1)
            # Without supplier_id in resolve call, scoped lookup skipped
            result = resolve_identifier("SUPPLIER_SKU", "MY-SKU-002")
            self.assertFalse(result["resolved"])

    def test_resolve_mpn_unique(self):
        """Stage 3: unique MPN resolves to product."""
        with self.app.app_context():
            from app.services.product_identity_service import (
                register_identifier, resolve_identifier
            )
            product_id = self._create_product("MPN Product")
            register_identifier(product_id, "MPN", "UNIQUE-MPN-XYZ")
            result = resolve_identifier("MPN", "UNIQUE-MPN-XYZ")
            self.assertTrue(result["resolved"])
            self.assertEqual(result["stage"], "stage3_mpn")

    def test_resolve_unknown_identifier(self):
        """Unregistered identifier returns unresolved."""
        with self.app.app_context():
            from app.services.product_identity_service import resolve_identifier
            result = resolve_identifier("GTIN13", "0000000000000")
            self.assertFalse(result["resolved"])
            self.assertEqual(result["stage"], "unresolved")
            self.assertIsNone(result["product_id"])

    def test_register_identifier_idempotent(self):
        """Re-registering same identifier returns 'exists', no DB error."""
        with self.app.app_context():
            from app.services.product_identity_service import register_identifier
            product_id = self._create_product("Idempotent Product")
            r1 = register_identifier(product_id, "GTIN13", "9876543210987")
            r2 = register_identifier(product_id, "GTIN13", "9876543210987")
            self.assertEqual(r1["action"], "created")
            self.assertEqual(r2["action"], "exists")

    def test_queue_for_review(self):
        """Unresolved items can be queued for human review."""
        with self.app.app_context():
            from app.services.product_identity_service import queue_for_review
            queue_id = queue_for_review(
                "GTIN13", "1111111111111",
                raw_product_data={"name": "مجهول", "price": 100},
                supplier_id=1,
            )
            self.assertIsNotNone(queue_id)
            self.assertGreater(queue_id, 0)

    def test_resolve_batch(self):
        """Batch resolution returns resolved/unresolved mix."""
        with self.app.app_context():
            from app.services.product_identity_service import (
                register_identifier, resolve_batch
            )
            product_id = self._create_product("Batch Product")
            register_identifier(product_id, "GTIN13", "5555555555555")
            items = [
                {"identifier_type": "GTIN13", "identifier_value": "5555555555555"},
                {"identifier_type": "GTIN13", "identifier_value": "0000000000001"},
            ]
            results = resolve_batch(items)
            self.assertEqual(len(results), 2)
            self.assertTrue(results[0]["resolved"])
            self.assertFalse(results[1]["resolved"])

    def test_identifier_type_normalised_uppercase(self):
        """Identifier type is normalised to uppercase."""
        with self.app.app_context():
            from app.services.product_identity_service import (
                register_identifier, resolve_identifier
            )
            product_id = self._create_product("Case Product")
            register_identifier(product_id, "gtin13", "3333333333333")
            result = resolve_identifier("GTIN13", "3333333333333")
            self.assertTrue(result["resolved"])


if __name__ == "__main__":
    unittest.main()
