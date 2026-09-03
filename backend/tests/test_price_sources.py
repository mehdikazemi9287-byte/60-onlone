"""Unit tests for price_source_service.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import NotFoundError, ValidationError
from app.services import price_source_service


class PriceSourceServiceTest(AppTestCase):
    """Tests for create_price_source, update_price, and get_authoritative_price."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_supplier_and_offer(self):
        """Return (supplier_id, offer_id) for a fresh test fixture."""
        sup  = self.create_test_supplier()
        prod = self.create_test_product_with_offer(
            sup["supplier_id"], sup["location_id"]
        )
        return sup["supplier_id"], prod["offer_id"]

    def _create_source(self, supplier_id: int, *, name: str = "منبع قیمت آزمایشی",
                        priority: int = 0) -> dict:
        with self.db.write_transaction() as conn:
            return price_source_service.create_price_source(
                conn,
                name=name,
                source_type="manual",
                supplier_id=supplier_id,
                priority=priority,
            )

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_create_price_source(self):
        """create_price_source returns a dict with correct fields."""
        supplier_id, _ = self._make_supplier_and_offer()
        src = self._create_source(supplier_id, name="منبع قیمت تست")

        self.assertEqual(src["name"], "منبع قیمت تست")
        self.assertEqual(src["source_type"], "manual")
        self.assertEqual(src["supplier_id"], supplier_id)
        self.assertEqual(src["priority"], 0)
        self.assertTrue(src["is_active"])
        self.assertIsNotNone(src["id"])

    def test_update_price(self):
        """update_price creates a price entry with correct price_minor."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.db.write_transaction() as conn:
            entry = price_source_service.update_price(
                conn,
                price_source_id=src["id"],
                offer_id=offer_id,
                price_minor=500_000,
                version=1,
            )

        self.assertEqual(entry["price_minor"], 500_000)
        self.assertEqual(entry["version"], 1)
        self.assertEqual(entry["offer_id"], offer_id)

    def test_update_price_out_of_order_ignored(self):
        """update_price with equal or lower version is silently ignored."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.db.write_transaction() as conn:
            price_source_service.update_price(
                conn, price_source_id=src["id"], offer_id=offer_id,
                price_minor=1_000_000, version=10,
            )
            stale = price_source_service.update_price(
                conn, price_source_id=src["id"], offer_id=offer_id,
                price_minor=999_999, version=5,
            )

        self.assertEqual(stale["price_minor"], 1_000_000, "Out-of-order update must be ignored")
        self.assertEqual(stale["version"], 10)

    def test_update_price_float_rejected(self):
        """update_price with a float price_minor raises ValidationError."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                price_source_service.update_price(
                    conn, price_source_id=src["id"], offer_id=offer_id,
                    price_minor=100.5,          # float — must be rejected
                    version=1,
                )

    def test_update_price_negative_rejected(self):
        """update_price with a negative price_minor raises ValidationError."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        src = self._create_source(supplier_id)

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                price_source_service.update_price(
                    conn, price_source_id=src["id"], offer_id=offer_id,
                    price_minor=-1,
                    version=1,
                )

    def test_get_authoritative_price_highest_priority(self):
        """get_authoritative_price returns price_minor from highest-priority source."""
        supplier_id, offer_id = self._make_supplier_and_offer()
        low_src  = self._create_source(supplier_id, name="منبع قیمت پایین",  priority=0)
        high_src = self._create_source(supplier_id, name="منبع قیمت بالا",   priority=10)

        with self.db.write_transaction() as conn:
            price_source_service.update_price(
                conn, price_source_id=low_src["id"],  offer_id=offer_id,
                price_minor=10_000, version=1,
            )
            price_source_service.update_price(
                conn, price_source_id=high_src["id"], offer_id=offer_id,
                price_minor=20_000, version=1,
            )

        with self.db.read_transaction() as conn:
            auth = price_source_service.get_authoritative_price(conn, offer_id)

        self.assertIsNotNone(auth)
        self.assertEqual(auth["price_minor"], 20_000, "High-priority source must win")
        self.assertEqual(auth["priority"], 10)

    def test_get_authoritative_price_none_when_no_source(self):
        """get_authoritative_price returns None when no price entry exists."""
        _, offer_id = self._make_supplier_and_offer()

        with self.db.read_transaction() as conn:
            result = price_source_service.get_authoritative_price(conn, offer_id)

        self.assertIsNone(result)

    def test_list_prices_by_source(self):
        """list_prices_by_source returns all entries for the given source."""
        supplier_id, offer_id_a = self._make_supplier_and_offer()
        sup2 = self.create_test_supplier()
        prod2 = self.create_test_product_with_offer(
            supplier_id, sup2["location_id"]
        )
        offer_id_b = prod2["offer_id"]

        src = self._create_source(supplier_id)

        with self.db.write_transaction() as conn:
            price_source_service.update_price(
                conn, price_source_id=src["id"], offer_id=offer_id_a,
                price_minor=1_000, version=1,
            )
            price_source_service.update_price(
                conn, price_source_id=src["id"], offer_id=offer_id_b,
                price_minor=2_000, version=1,
            )

        with self.db.read_transaction() as conn:
            entries = price_source_service.list_prices_by_source(conn, src["id"])

        self.assertEqual(len(entries), 2)
        prices = {e["offer_id"]: e["price_minor"] for e in entries}
        self.assertEqual(prices[offer_id_a], 1_000)
        self.assertEqual(prices[offer_id_b], 2_000)


if __name__ == "__main__":
    unittest.main()
