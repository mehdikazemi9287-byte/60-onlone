"""Tests for product_resolution_service — Phase 6 Final."""
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
from app.services import product_resolution_service as prs

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"


def _apply_all(db: Database, staging_dir: Path) -> None:
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


class ProductResolutionTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="70online-pr-")
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)
        _apply_all(self.db, self.staging)

        # Insert base fixtures
        with self.db.write_transaction() as conn:
            sup = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت تست تفکیک", "تست تفکیک", "9900099000", "retailer", "active", 40)
            )
            self.supplier_id = int(sup.lastrowid)

            loc = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (self.supplier_id, "تهران", "تهران", "active", 1, 1, 0, 60)
            )
            self.location_id = int(loc.lastrowid)

            ca = conn.execute(
                "INSERT INTO connector_accounts (name, connector_type, supplier_id, config_json) "
                "VALUES (?,?,?,?)",
                ("ERP تست تفکیک", "MOCK_ERP", self.supplier_id, "{}")
            )
            self.connector_account_id = int(ca.lastrowid)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _conn(self):
        return self.db.connection

    def _make_product_with_barcode(self, barcode: str, title: str = "محصول آزمایشی") -> tuple[int, int]:
        """Create a canonical product with a barcode identifier. Returns (product_id, offer_id)."""
        with self.db.write_transaction() as conn:
            cat = conn.execute(
                "SELECT id FROM categories WHERE slug = 'auto-discovered'"
            ).fetchone()
            if not cat:
                cat = conn.execute(
                    "INSERT INTO categories (slug, name_fa, sort_order) VALUES (?,?,?)",
                    ("auto-discovered", "کشف خودکار", 9999)
                )
                cat_id = int(cat.lastrowid)
            else:
                cat_id = int(cat["id"])

            import uuid
            slug = f"test-{uuid.uuid4().hex[:8]}"
            sku = f"SKU-{uuid.uuid4().hex[:8]}"
            prod = conn.execute(
                "INSERT INTO products (slug, sku, title_fa, description_fa, brand_fa, "
                "category_id, base_price_minor, currency, image_emoji, rating_x10, is_active, "
                "logistics_profile) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (slug, sku, title, "توضیحات", "برند", cat_id, 1000000, "IRR", "📦", 40, 1, "standard")
            )
            product_id = int(prod.lastrowid)

            offer = conn.execute(
                "INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, "
                "selling_price_minor, cost_price_minor, stock_quantity, status) "
                "VALUES (?,?,?,?,?,?,?)",
                (product_id, self.supplier_id, self.location_id, 1000000, 800000, 50, "active")
            )
            offer_id = int(offer.lastrowid)

            # Add barcode identifier
            conn.execute(
                "INSERT INTO product_identifiers (product_id, supplier_id, identifier_type, "
                "identifier_value, namespace, is_primary) VALUES (?,?,?,?,?,?)",
                (product_id, self.supplier_id, "barcode", barcode, "", 1)
            )

        return product_id, offer_id

    def test_resolve_by_barcode_matched(self):
        product_id, offer_id = self._make_product_with_barcode("6260000000001")
        external = {
            "code": "ERP-00001",
            "barcode": "6260000000001",
            "name_fa": "محصول تست",
            "price_minor": 2000000,
            "stock_quantity": 10,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result["result"], "matched")
        self.assertEqual(result["product_id"], product_id)
        self.assertEqual(result["confidence_bps"], 10000)
        self.assertEqual(result["resolution_method"], "barcode_lookup")

    def test_resolve_new_canonical_creates_product_offer(self):
        external = {
            "code": "ERP-BRAND-NEW",
            "barcode": "6260000099999",
            "sku": "NEW-SKU-001",
            "name_fa": "محصول کاملاً جدید",
            "brand_fa": "برند جدید",
            "price_minor": 5000000,
            "stock_quantity": 20,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result["result"], "new_canonical")
        self.assertIsNotNone(result["product_id"])
        self.assertIsNotNone(result["offer_id"])
        # new_canonical without knowledge enrichment: confidence=5000 (moderate, auto-created)
        self.assertEqual(result["confidence_bps"], 5000)

        # Verify product was created in DB
        with self.db.read_transaction() as conn:
            prod = conn.execute(
                "SELECT * FROM products WHERE id = ?", (result["product_id"],)
            ).fetchone()
        self.assertIsNotNone(prod)
        self.assertEqual(prod["title_fa"], "محصول کاملاً جدید")

    def test_resolve_stores_resolution_attempt(self):
        external = {
            "code": "ERP-ATTEMPT-TEST",
            "barcode": "6260000088888",
            "name_fa": "محصول آزمایش ثبت تلاش",
            "price_minor": 3000000,
            "stock_quantity": 5,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        with self.db.read_transaction() as conn:
            attempt = conn.execute(
                "SELECT * FROM resolution_attempts ORDER BY id DESC LIMIT 1"
            ).fetchone()

        self.assertIsNotNone(attempt)
        self.assertIn(attempt["result"], ("matched", "new_canonical"))
        self.assertGreaterEqual(int(attempt["confidence_bps"]), 0)
        self.assertLessEqual(int(attempt["confidence_bps"]), 10000)

    def test_duplicate_barcode_no_double_create(self):
        """Second call with same barcode must MATCH, not create a new product."""
        external = {
            "code": "ERP-IDEMPOTENT",
            "barcode": "6260000077777",
            "name_fa": "محصول آزمایش همیدگی",
            "price_minor": 1500000,
            "stock_quantity": 8,
        }
        with self.db.write_transaction() as conn:
            result1 = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result1["result"], "new_canonical")
        pid1 = result1["product_id"]

        with self.db.write_transaction() as conn:
            result2 = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result2["result"], "matched")
        self.assertEqual(result2["product_id"], pid1)

    def test_resolve_by_sku(self):
        """Resolve by supplier SKU when barcode not present."""
        product_id, offer_id = self._make_product_with_barcode("6260000066666")

        # Add SKU identifier
        with self.db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO product_identifiers (product_id, supplier_id, identifier_type, "
                "identifier_value, namespace, is_primary) VALUES (?,?,?,?,?,?)",
                (product_id, self.supplier_id, "sku", "MY-SKU-001", "", 0)
            )

        external = {
            "code": "ERP-SKU-LOOKUP",
            "sku": "MY-SKU-001",
            "name_fa": "محصول جستجو با SKU",
            "price_minor": 2500000,
            "stock_quantity": 15,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result["result"], "matched")
        self.assertEqual(result["product_id"], product_id)
        self.assertEqual(result["resolution_method"], "sku_lookup")
        self.assertEqual(result["confidence_bps"], 9000)

    def test_resolve_by_erp_code(self):
        """Resolve via existing ERP mapping."""
        product_id, offer_id = self._make_product_with_barcode("6260000055555")

        # Add ERP mapping
        with self.db.write_transaction() as conn:
            conn.execute(
                """INSERT INTO erp_product_mappings
                   (connector_account_id, erp_product_code, product_id, supplier_id,
                    confidence_score_bps, match_method, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
                (self.connector_account_id, "ERP-MAPPED-001", product_id, self.supplier_id,
                 9500, "manual", "active")
            )

        external = {
            "code": "ERP-MAPPED-001",
            "name_fa": "محصول با نگاشت ERP",
            "price_minor": 3500000,
            "stock_quantity": 12,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result["result"], "matched")
        self.assertEqual(result["product_id"], product_id)
        self.assertEqual(result["resolution_method"], "erp_mapping")
        self.assertEqual(result["confidence_bps"], 9500)

    def test_confidence_bps_is_always_integer_between_0_and_10000(self):
        """confidence_bps must always be an integer in [0, 10000]."""
        external = {
            "code": "ERP-CONF-TEST",
            "barcode": "6260000044444",
            "name_fa": "محصول آزمایش اطمینان",
            "price_minor": 1000000,
            "stock_quantity": 1,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertIsInstance(result["confidence_bps"], int)
        self.assertGreaterEqual(result["confidence_bps"], 0)
        self.assertLessEqual(result["confidence_bps"], 10000)

    def test_price_is_updated_on_matched_offer(self):
        """When a product matches, the offer's price must be updated."""
        product_id, offer_id = self._make_product_with_barcode("6260000033333")

        external = {
            "code": "ERP-PRICE-UPDATE",
            "barcode": "6260000033333",
            "name_fa": "محصول آزمایش به‌روزرسانی قیمت",
            "price_minor": 9999000,
            "stock_quantity": 25,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        self.assertEqual(result["result"], "matched")

        with self.db.read_transaction() as conn:
            offer = conn.execute(
                "SELECT selling_price_minor FROM seller_offers WHERE id = ?", (offer_id,)
            ).fetchone()
        self.assertEqual(int(offer["selling_price_minor"]), 9999000)

    def test_new_product_price_is_integer(self):
        """Auto-created product's base_price_minor must be an INTEGER."""
        external = {
            "code": "ERP-INT-PRICE",
            "barcode": "6260000022222",
            "name_fa": "محصول آزمایش قیمت صحیح",
            "price_minor": 4500000,  # INTEGER, not float
            "stock_quantity": 7,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        with self.db.read_transaction() as conn:
            prod = conn.execute(
                "SELECT base_price_minor FROM products WHERE id = ?", (result["product_id"],)
            ).fetchone()

        price = prod["base_price_minor"]
        self.assertIsInstance(price, int)
        self.assertEqual(price, 4500000)

    def test_no_product_created_for_matched_barcode(self):
        """When barcode matches, no new product should be created."""
        barcode = "6260000011111"
        product_id, _ = self._make_product_with_barcode(barcode)

        with self.db.read_transaction() as conn:
            count_before = conn.execute("SELECT COUNT(*) AS cnt FROM products").fetchone()["cnt"]

        external = {
            "code": "ERP-NO-NEW",
            "barcode": barcode,
            "name_fa": "محصول موجود",
            "price_minor": 2000000,
            "stock_quantity": 3,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
            )

        with self.db.read_transaction() as conn:
            count_after = conn.execute("SELECT COUNT(*) AS cnt FROM products").fetchone()["cnt"]

        self.assertEqual(result["result"], "matched")
        self.assertEqual(count_before, count_after)

    def test_sync_run_id_recorded_in_resolution_attempt(self):
        """sync_run_id must be stored in resolution_attempts when provided."""
        with self.db.write_transaction() as conn:
            sr = conn.execute(
                "INSERT INTO sync_runs (connector_account_id, job_type, status, started_at, "
                "records_processed, records_succeeded, records_failed, error_log_json, triggered_by) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (self.connector_account_id, "discovery", "running", "2026-08-08T10:00:00",
                 0, 0, 0, "[]", "manual")
            )
            sync_run_id = int(sr.lastrowid)

        external = {
            "code": "ERP-WITH-SYNC",
            "barcode": "6260000012345",
            "name_fa": "محصول با sync_run_id",
            "price_minor": 1000000,
            "stock_quantity": 2,
        }
        with self.db.write_transaction() as conn:
            prs.resolve_product(
                conn,
                external=external,
                connector_account_id=self.connector_account_id,
                supplier_id=self.supplier_id,
                sync_run_id=sync_run_id,
            )

        with self.db.read_transaction() as conn:
            attempt = conn.execute(
                "SELECT sync_run_id FROM resolution_attempts ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(int(attempt["sync_run_id"]), sync_run_id)


if __name__ == "__main__":
    unittest.main()
