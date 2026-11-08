"""REGRESSION TEST — migration 0009 on a populated database.

Verifies that 0009_inventory_identifiers.sql:
  - succeeds when FK-referencing rows exist (products, suppliers, seller_offers,
    connector_accounts) under PRAGMA foreign_keys = ON;
  - creates all six new tables;
  - leaves PRAGMA foreign_key_check returning 0 rows;
  - enforces UNIQUE constraints on product_identifiers and inventory_source_stock.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import Database
from app.core import migrator

# ── paths ─────────────────────────────────────────────────────────────────────

_BACKEND_DIR    = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"

_PRE_MIGRATION_FILES = sorted(
    p for p in _MIGRATIONS_DIR.glob("*.sql")
    if p.stem[:4].isdigit() and int(p.stem[:4]) <= 8
)

_MIGRATION_0009 = _MIGRATIONS_DIR / "0009_inventory_identifiers.sql"


# ── helpers ───────────────────────────────────────────────────────────────────

def _apply_up_to_0008(db: Database, staging_dir: Path) -> None:
    """Copy migrations 0001-0008 to a temp staging dir and upgrade."""
    for path in _PRE_MIGRATION_FILES:
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


def _table_exists(db: Database, table_name: str) -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return row is not None


# ── test ──────────────────────────────────────────────────────────────────────

class Migration0009PopulatedDBTest(unittest.TestCase):
    """Migration 0008→0009 must succeed with FK-referencing rows in place."""

    def setUp(self) -> None:
        self.tmpdir  = tempfile.mkdtemp(prefix="60online-mig0009-test-")
        self.db_path = os.path.join(self.tmpdir, "test0009.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── fixture ───────────────────────────────────────────────────────────────

    def _insert_fixture_rows(self) -> dict:
        """Insert FK-satisfying rows into the 0008-schema DB and return their ids."""
        with self.db.write_transaction() as conn:

            # 1. category (required by products)
            cat_cur = conn.execute(
                "INSERT INTO categories (slug, name_fa) VALUES (?,?)",
                ("office", "اداری"),
            )
            cat_id = int(cat_cur.lastrowid)

            # 2. product
            prod_cur = conn.execute(
                "INSERT INTO products "
                "(slug, sku, title_fa, description_fa, brand_fa, "
                " category_id, base_price_minor, currency, image_emoji, rating_x10, is_active, "
                " logistics_profile) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "test-paper-mig0009", "TEST-MIG0009-SKU",
                    "کاغذ آزمایشی مهاجرت ۹", "توضیحات", "برند آزمایشی",
                    cat_id, 500_000, "IRR", "📦", 40, 1, "standard",
                ),
            )
            product_id = int(prod_cur.lastrowid)

            # inventory row (required by some FK chains)
            conn.execute(
                "INSERT INTO inventory (product_id, quantity_available, quantity_reserved) "
                "VALUES (?,50,0)",
                (product_id,),
            )

            # 3. supplier
            sup_cur = conn.execute(
                "INSERT INTO suppliers "
                "(legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت آزمایشی مهاجرت ۹", "آزمایشی ۹", "9990009000", "retailer", "active", 40),
            )
            supplier_id = int(sup_cur.lastrowid)

            # 4. supplier_location
            loc_cur = conn.execute(
                "INSERT INTO supplier_locations "
                "(supplier_id, province, city, status, "
                " can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (supplier_id, "تهران", "تهران", "active", 1, 1, 0, 60),
            )
            location_id = int(loc_cur.lastrowid)

            # 5. seller_offer
            offer_cur = conn.execute(
                "INSERT INTO seller_offers "
                "(product_id, supplier_id, supplier_location_id, "
                " selling_price_minor, cost_price_minor, stock_quantity, status, fulfillment_type) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (product_id, supplier_id, location_id,
                 500_000, 375_000, 50, "active", "delivery"),
            )
            offer_id = int(offer_cur.lastrowid)

            # 6. connector_account (valid pre-0009 type)
            ca_cur = conn.execute(
                "INSERT INTO connector_accounts "
                "(name, connector_type, supplier_id, config_json) "
                "VALUES (?,?,?,?)",
                ("حساب آزمایشی مهاجرت ۹", "MANUAL", supplier_id, "{}"),
            )
            connector_account_id = int(ca_cur.lastrowid)

        return {
            "cat_id":              cat_id,
            "product_id":          product_id,
            "supplier_id":         supplier_id,
            "location_id":         location_id,
            "offer_id":            offer_id,
            "connector_account_id": connector_account_id,
        }

    # ── main test ─────────────────────────────────────────────────────────────

    def test_migration_0009_succeeds_on_populated_database(self):
        """Migration 0008→0009 must succeed and create all six new tables."""

        # Step 1: apply 0001-0008
        _apply_up_to_0008(self.db, self.staging)
        schema_before = migrator.current_version(self.db)
        self.assertEqual(schema_before, "0008", f"Expected schema 0008, got {schema_before!r}")

        # Step 2: insert FK-satisfying rows
        ids = self._insert_fixture_rows()

        # Step 3: apply migration 0009
        shutil.copy(_MIGRATION_0009, self.staging / _MIGRATION_0009.name)
        try:
            migrator.upgrade(self.db, self.staging)
        except Exception as exc:
            self.fail(
                f"Migration 0008→0009 must succeed on a populated database, "
                f"but it raised {type(exc).__name__}: {exc}"
            )

        schema_after = migrator.current_version(self.db)
        self.assertEqual(schema_after, "0009", f"Expected schema 0009, got {schema_after!r}")

        # Assertion 1: PRAGMA foreign_key_check returns 0 rows
        fk_violations = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(
            len(fk_violations), 0,
            f"post-0009: foreign_key_check must return 0 violations; got: {fk_violations}",
        )

        # Assertion 2: PRAGMA foreign_keys = 1
        fk_on = self.db.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(fk_on, 1, "post-0009: PRAGMA foreign_keys must be 1 (ON)")

        # Assertion 3: Table product_identifiers exists
        self.assertTrue(
            _table_exists(self.db, "product_identifiers"),
            "post-0009: table 'product_identifiers' must exist",
        )

        # Assertion 4: Table identifier_conflicts exists
        self.assertTrue(
            _table_exists(self.db, "identifier_conflicts"),
            "post-0009: table 'identifier_conflicts' must exist",
        )

        # Assertion 5: Table inventory_sources exists
        self.assertTrue(
            _table_exists(self.db, "inventory_sources"),
            "post-0009: table 'inventory_sources' must exist",
        )

        # Assertion 6: Table inventory_source_stock exists
        self.assertTrue(
            _table_exists(self.db, "inventory_source_stock"),
            "post-0009: table 'inventory_source_stock' must exist",
        )

        # Assertion 7: Table price_sources exists
        self.assertTrue(
            _table_exists(self.db, "price_sources"),
            "post-0009: table 'price_sources' must exist",
        )

        # Assertion 8: Table price_source_entries exists
        self.assertTrue(
            _table_exists(self.db, "price_source_entries"),
            "post-0009: table 'price_source_entries' must exist",
        )

        product_id  = ids["product_id"]
        supplier_id = ids["supplier_id"]
        offer_id    = ids["offer_id"]

        # Assertion 9: Can INSERT a product_identifier row
        with self.db.write_transaction() as conn:
            pi_cur = conn.execute(
                """
                INSERT INTO product_identifiers
                    (product_id, supplier_id, identifier_type, identifier_value, namespace)
                VALUES (?, ?, 'barcode', '6260009000010', '')
                """,
                (product_id, supplier_id),
            )
            pi_id = int(pi_cur.lastrowid)
        self.assertGreater(pi_id, 0, "post-0009: product_identifier insert must return a valid id")

        # Assertion 10: Can INSERT an inventory_source row
        with self.db.write_transaction() as conn:
            is_cur = conn.execute(
                """
                INSERT INTO inventory_sources
                    (name, source_type, supplier_id, priority, config_json,
                     created_at, updated_at)
                VALUES (?, 'manual', ?, 0, '{}',
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                ("منبع آزمایشی مهاجرت ۹", supplier_id),
            )
            inv_source_id = int(is_cur.lastrowid)
        self.assertGreater(inv_source_id, 0, "post-0009: inventory_source insert must return a valid id")

        # Assertion 11: UNIQUE constraint on product_identifiers works
        with self.assertRaises(
            (sqlite3.IntegrityError, Exception),
            msg="post-0009: UNIQUE constraint on (identifier_type, identifier_value, namespace, supplier_id) must reject duplicates",
        ):
            with self.db.write_transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO product_identifiers
                        (product_id, supplier_id, identifier_type, identifier_value, namespace)
                    VALUES (?, ?, 'barcode', '6260009000010', '')
                    """,
                    (product_id, supplier_id),
                )

        # Assertion 12: inventory_source_stock UNIQUE(inventory_source_id, offer_id) works
        with self.db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO inventory_source_stock
                    (inventory_source_id, offer_id, quantity, version,
                     synced_at, created_at, updated_at)
                VALUES (?, ?, 100, 1,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (inv_source_id, offer_id),
            )

        with self.assertRaises(
            (sqlite3.IntegrityError, Exception),
            msg="post-0009: UNIQUE(inventory_source_id, offer_id) must reject duplicates",
        ):
            with self.db.write_transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO inventory_source_stock
                        (inventory_source_id, offer_id, quantity, version,
                         synced_at, created_at, updated_at)
                    VALUES (?, ?, 200, 2,
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    """,
                    (inv_source_id, offer_id),
                )

        # Final FK check
        fk_final = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(
            len(fk_final), 0,
            f"final: foreign_key_check must return 0 violations; got: {fk_final}",
        )


if __name__ == "__main__":
    unittest.main()
