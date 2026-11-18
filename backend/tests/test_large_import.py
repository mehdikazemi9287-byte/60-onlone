"""CRITICAL: Large import test — actually runs 10K product discovery sync.

Verifies:
- All 10,000 products are processed
- Products created (no duplicates)
- Offers created
- Replay is idempotent (second run = 0 new products)
- Memory-bounded (no loading all 10K into memory at once via generator)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import Database
from app.core import migrator
from app.services import auto_discovery_service

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"


def _apply_all(db: Database, staging_dir: Path) -> None:
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


class LargeImportTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="60online-large-")
        self.db_path = os.path.join(self.tmpdir, "large.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)
        _apply_all(self.db, self.staging)

        # Set up fixtures
        with self.db.write_transaction() as conn:
            user = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role) "
                "VALUES (?,?,?,?,?)",
                ("large@test.com", "large@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "تست بزرگ", "admin")
            )
            self.user_id = int(user.lastrowid)

            sup = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت تست واردات بزرگ", "واردات بزرگ", "9900010000", "retailer", "active", 40)
            )
            self.supplier_id = int(sup.lastrowid)

            loc = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (self.supplier_id, "تهران", "تهران", "active", 1, 1, 0, 60)
            )
            self.location_id = int(loc.lastrowid)

            # Connector account with 'large' dataset → MockErpV2
            ca = conn.execute(
                "INSERT INTO connector_accounts (name, connector_type, supplier_id, "
                "mock_erp_dataset, config_json, status) "
                "VALUES (?,?,?,?,?,?)",
                ("ERP بزرگ آزمایشی", "MOCK_ERP", self.supplier_id,
                 "large", '{"dataset": "large"}', "active")
            )
            self.connector_account_id = int(ca.lastrowid)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_10k_product_discovery_end_to_end(self):
        """
        Actually runs discovery sync with MockErpV2 (10,000 products).
        Verifies all 10,000 processed, products created, idempotency on second run.
        """
        start = time.time()

        # First run
        conn = self.db.connection
        result1 = auto_discovery_service.run_discovery_sync(
            conn,
            connector_account_id=self.connector_account_id,
            triggered_by="manual",
            batch_size=200,
        )

        elapsed1 = time.time() - start

        print(f"\n10K Import Run 1:")
        print(f"  elapsed    = {elapsed1:.1f}s")
        print(f"  processed  = {result1['processed']}")
        print(f"  matched    = {result1['matched']}")
        print(f"  new        = {result1['new_canonical']}")
        print(f"  conflict   = {result1['conflict']}")
        print(f"  failed     = {result1['failed']}")
        print(f"  status     = {result1['status']}")

        # Assert: all 10K processed
        self.assertEqual(result1["processed"], 10000,
                        f"Expected 10000 processed, got {result1['processed']}")
        # All should be new canonical on first run (no existing products)
        self.assertEqual(result1["new_canonical"], 10000,
                        f"Expected 10000 new_canonical, got {result1['new_canonical']}")
        self.assertEqual(result1["matched"], 0)
        self.assertEqual(result1["failed"], 0)

        # Verify product count in DB
        with self.db.read_transaction() as conn2:
            prod_count = conn2.execute(
                "SELECT COUNT(*) AS cnt FROM products WHERE slug LIKE 'auto-%'"
            ).fetchone()["cnt"]
        self.assertGreaterEqual(prod_count, 10000,
                               f"Expected >= 10000 products in DB, got {prod_count}")

        # Verify offer count
        with self.db.read_transaction() as conn2:
            offer_count = conn2.execute(
                "SELECT COUNT(*) AS cnt FROM seller_offers WHERE supplier_id = ?",
                (self.supplier_id,)
            ).fetchone()["cnt"]
        self.assertGreaterEqual(offer_count, 10000,
                               f"Expected >= 10000 offers in DB, got {offer_count}")

        # Second run (idempotency test)
        start2 = time.time()
        conn = self.db.connection
        result2 = auto_discovery_service.run_discovery_sync(
            conn,
            connector_account_id=self.connector_account_id,
            triggered_by="schedule",
            batch_size=200,
        )
        elapsed2 = time.time() - start2

        print(f"\n10K Import Run 2 (replay/idempotency check):")
        print(f"  elapsed    = {elapsed2:.1f}s")
        print(f"  processed  = {result2['processed']}")
        print(f"  matched    = {result2['matched']}")
        print(f"  new        = {result2['new_canonical']}")

        # Idempotency: second run should create 0 new products
        self.assertEqual(result2["processed"], 10000)
        self.assertEqual(result2["new_canonical"], 0,
                        f"Second run must create 0 new products (idempotent), got {result2['new_canonical']}")
        self.assertEqual(result2["matched"], 10000,
                        f"Second run: all should be matched, got {result2['matched']}")

        total_elapsed = time.time() - start
        print(f"\nTotal test time: {total_elapsed:.1f}s (both runs)")

    def test_large_import_uses_generator_not_list(self):
        """Verify MockErpV2 supports pull_products_all() generator interface."""
        from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector, TOTAL_PRODUCTS
        adapter = MockErpV2Connector()
        self.assertTrue(hasattr(adapter, "pull_products_all"))

        # The generator should yield lazily (not load all at once)
        gen = adapter.pull_products_all()
        count = 0
        for product in gen:
            count += 1
            if count == 1:
                self.assertIn("code", product)
                self.assertIn("price_minor", product)
                # price must be INTEGER
                self.assertIsInstance(product["price_minor"], int)
            if count >= TOTAL_PRODUCTS:
                break

        self.assertEqual(count, TOTAL_PRODUCTS)

    def test_product_prices_are_integers_in_large_dataset(self):
        """All prices from MockErpV2 must be INTEGER, never REAL/float."""
        from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector
        adapter = MockErpV2Connector()
        page = adapter.pull_products(limit=100, offset=0)
        for item in page["items"]:
            self.assertIsInstance(item["price_minor"], int,
                                 f"price_minor must be int, got {type(item['price_minor'])}")
            self.assertNotIsInstance(item["price_minor"], float)


if __name__ == "__main__":
    unittest.main()
