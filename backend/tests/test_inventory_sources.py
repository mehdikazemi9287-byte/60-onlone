"""Unit tests for inventory_source_service.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import NotFoundError
from app.services import inventory_source_service


class InventorySourceServiceTest(AppTestCase):
    """Tests for create_inventory_source, update_stock, get_authoritative_stock,
    and list_stock_by_source."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_supplier_and_offer(self):
        """Return (supplier_id, offer_id) for a fresh test fixture."""
        sup  = self.create_test_supplier()
        prod = self.create_test_product_with_offer(
            sup["supplier_id"], sup["location_id"]
        )
        return sup["supplier_id"], prod["offer_id"]

    def _create_source(self, supplier_id: int, *, name: str = "منبع آزمایشی",
                        priority: int = 0) -> dict:
        with self.db.write_transaction() as conn:
            return inventory_source_service.create_inventory_source(
                conn,
                name=name,
                source_type="manual",
                supplier_id=supplier_id,
                priority=priority,
            )

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_create_inventory_source(self):
        """create_inventory_source returns a dict with correct fields."""
        supplier_id, _ = self._make_supplier_and_offer()
        src = self._create_source(supplier_id, name="منبع تست یک")

        self.assertEqual(src["name"], "منبع تست یک")
        self.assertEqual(src["source_type"], "manual")
        self.assertEqual(src["supplier_id"], supplier_id)
        self.assertEqual(src["priority"], 0)
        self.assertTrue(src["is_active"])
        self.assertIsNotNone(src["id"])

    def test_list_inventory_sources_by_supplier(self):
        """list_inventory_sources filters by supplier_id."""
        supplier_id_a, _ = self._make_supplier_and_offer()
        supplier_id_b, _ = self._make_supplier_and_offer()

        self._create_source(supplier_id_a, name="منبع تأمین‌کننده A")
        self._create_source(supplier_id_b, name="منبع تأمین‌کننده B")

        with self.db.read_transaction() as conn:
            sources_a = inventory_source_service.list_inventory_sources(
                conn, supplier_id=supplier_id_a
            )
            sources_b = inventory_source_service.list_inventory_sources(
                conn, supplier_id=supplier_id_b
            )

        names_a = [s["name"] for s in sources_a]
        names_b = [s["name"] for s in sources_b]

        self.assertIn("منبع تأمین‌کننده A", names_a)
        self.assertNotIn("منبع تأمین‌کننده B", names_a)
        self.assertIn("منبع تأمین‌کننده B", names_b)
        self.assertNotIn("منبع تأمین‌کننده A", names_b)

    def test_update_stock_insert(self):
        """update_stock creates a new stock row for a new offer."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.db.write_transaction() as conn:
            stock = inventory_source_service.update_stock(
                conn,
                inventory_source_id=src["id"],
                offer_id=offer_id,
                quantity=42,
                version=1,
            )

        self.assertEqual(stock["quantity"], 42)
        self.assertEqual(stock["version"], 1)
        self.assertEqual(stock["offer_id"], offer_id)
        self.assertEqual(stock["inventory_source_id"], src["id"])

    def test_update_stock_higher_version_replaces(self):
        """update_stock with a higher version updates quantity."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.db.write_transaction() as conn:
            inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id,
                quantity=10, version=1,
            )
            updated = inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id,
                quantity=99, version=5,
            )

        self.assertEqual(updated["quantity"], 99)
        self.assertEqual(updated["version"], 5)

    def test_update_stock_out_of_order_ignored(self):
        """update_stock with equal or lower version is silently ignored."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.db.write_transaction() as conn:
            inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id,
                quantity=100, version=5,
            )
            # Same version — should be ignored
            stale = inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id,
                quantity=999, version=3,
            )

        self.assertEqual(stale["quantity"], 100, "Out-of-order update must be ignored")
        self.assertEqual(stale["version"], 5)

    def test_get_authoritative_stock_highest_priority(self):
        """get_authoritative_stock returns quantity from highest-priority source."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        low_src  = self._create_source(supplier_id, name="منبع اولویت پایین",  priority=0)
        high_src = self._create_source(supplier_id, name="منبع اولویت بالا",   priority=10)

        with self.db.write_transaction() as conn:
            inventory_source_service.update_stock(
                conn, inventory_source_id=low_src["id"], offer_id=offer_id,
                quantity=50, version=1,
            )
            inventory_source_service.update_stock(
                conn, inventory_source_id=high_src["id"], offer_id=offer_id,
                quantity=30, version=1,
            )

        with self.db.read_transaction() as conn:
            auth = inventory_source_service.get_authoritative_stock(conn, offer_id)

        self.assertIsNotNone(auth)
        self.assertEqual(auth["quantity"], 30, "High-priority source must win")
        self.assertEqual(auth["priority"], 10)

    def test_get_authoritative_stock_returns_none_when_no_source(self):
        """get_authoritative_stock returns None when no stock records exist."""
        supplier_id, offer_id = self._make_supplier_and_offer()

        with self.db.read_transaction() as conn:
            result = inventory_source_service.get_authoritative_stock(conn, offer_id)

        self.assertIsNone(result)

    def test_list_stock_by_source(self):
        """list_stock_by_source returns all stock rows for the given source."""
        supplier_id_a, offer_id_a = self._make_supplier_and_offer()
        # Create a second offer under the same supplier
        prod2 = self.create_test_product_with_offer(
            supplier_id_a,
            self.create_test_supplier()["location_id"],   # different location ok
        )
        offer_id_b = prod2["offer_id"]

        src = self._create_source(supplier_id_a)

        with self.db.write_transaction() as conn:
            inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id_a,
                quantity=20, version=1,
            )
            inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id_b,
                quantity=40, version=1,
            )

        with self.db.read_transaction() as conn:
            stocks = inventory_source_service.list_stock_by_source(conn, src["id"])

        self.assertEqual(len(stocks), 2)
        quantities = {s["offer_id"]: s["quantity"] for s in stocks}
        self.assertEqual(quantities[offer_id_a], 20)
        self.assertEqual(quantities[offer_id_b], 40)

    def test_get_inventory_source_not_found_raises(self):
        """get_inventory_source raises NotFoundError for a non-existent id."""
        with self.assertRaises(NotFoundError):
            with self.db.read_transaction() as conn:
                inventory_source_service.get_inventory_source(conn, 999_999)


if __name__ == "__main__":
    unittest.main()
