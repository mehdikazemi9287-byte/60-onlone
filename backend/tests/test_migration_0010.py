"""REGRESSION TEST — migration 0010 on a populated database.

Verifies that 0010_connectors_import.sql:
  - succeeds when FK-referencing rows exist (products, suppliers, seller_offers,
    connector_accounts, sync_runs) under PRAGMA foreign_keys = ON;
  - creates erp_product_mappings, sync_run_items, import_jobs, import_job_rows;
  - adds mock_erp_dataset column to connector_accounts via ALTER TABLE;
  - leaves PRAGMA foreign_key_check returning 0 rows;
  - enforces UNIQUE(connector_account_id, erp_product_code) on erp_product_mappings.
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
    if p.stem[:4].isdigit() and int(p.stem[:4]) <= 9
)

_MIGRATION_0010 = _MIGRATIONS_DIR / "0010_connectors_import.sql"


# ── helpers ───────────────────────────────────────────────────────────────────

def _apply_up_to_0009(db: Database, staging_dir: Path) -> None:
    """Copy migrations 0001-0009 to a temp staging dir and upgrade."""
    for path in _PRE_MIGRATION_FILES:
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


def _table_exists(db: Database, table_name: str) -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return row is not None


def _column_exists(db: Database, table_name: str, column_name: str) -> bool:
    rows = db.query(f"PRAGMA table_info({table_name})")
    return any(r["name"] == column_name for r in rows)


# ── test ──────────────────────────────────────────────────────────────────────

class Migration0010PopulatedDBTest(unittest.TestCase):
    """Migration 0009→0010 must succeed and create all new tables."""

    def setUp(self) -> None:
        self.tmpdir  = tempfile.mkdtemp(prefix="70online-mig0010-test-")
        self.db_path = os.path.join(self.tmpdir, "test0010.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── fixtures ──────────────────────────────────────────────────────────────

    def _insert_fixture_rows(self) -> dict:
        """Insert FK-satisfying rows into the 0009-schema DB and return their ids."""
        with self.db.write_transaction() as conn:

            # category
            cat_cur = conn.execute(
                "INSERT INTO categories (slug, name_fa) VALUES (?,?)",
                ("office-mig10", "اداری مهاجرت ۱۰"),
            )
            cat_id = int(cat_cur.lastrowid)

            # product
            prod_cur = conn.execute(
                "INSERT INTO products "
                "(slug, sku, title_fa, description_fa, brand_fa, "
                " category_id, base_price_minor, currency, image_emoji, rating_x10, is_active, "
                " logistics_profile) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "test-product-mig0010", "TEST-MIG0010-SKU",
                    "محصول آزمایشی مهاجرت ۱۰", "توضیحات", "برند آزمایشی",
                    cat_id, 1_000_000, "IRR", "📦", 40, 1, "standard",
                ),
            )
            product_id = int(prod_cur.lastrowid)

            conn.execute(
                "INSERT INTO inventory (product_id, quantity_available, quantity_reserved) "
                "VALUES (?,50,0)",
                (product_id,),
            )

            # user (for import_jobs.created_by FK)
            user_cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name) "
                "VALUES (?,?,?,?)",
                (
                    "mig0010@test.example",
                    "mig0010@test.example",
                    "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "تست مهاجرت ۱۰",
                ),
            )
            user_id = int(user_cur.lastrowid)

            # supplier
            sup_cur = conn.execute(
                "INSERT INTO suppliers "
                "(legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("شرکت آزمایشی مهاجرت ۱۰", "آزمایشی ۱۰", "1100010000", "retailer", "active", 40),
            )
            supplier_id = int(sup_cur.lastrowid)

            # supplier_location
            loc_cur = conn.execute(
                "INSERT INTO supplier_locations "
                "(supplier_id, province, city, status, "
                " can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (supplier_id, "تهران", "تهران", "active", 1, 1, 0, 60),
            )
            location_id = int(loc_cur.lastrowid)

            # seller_offer
            offer_cur = conn.execute(
                "INSERT INTO seller_offers "
                "(product_id, supplier_id, supplier_location_id, "
                " selling_price_minor, cost_price_minor, stock_quantity, status, fulfillment_type) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (product_id, supplier_id, location_id,
                 1_000_000, 750_000, 50, "active", "delivery"),
            )
            offer_id = int(offer_cur.lastrowid)

            # connector_account
            ca_cur = conn.execute(
                "INSERT INTO connector_accounts "
                "(name, connector_type, supplier_id, config_json) "
                "VALUES (?,?,?,?)",
                ("حساب آزمایشی مهاجرت ۱۰", "MANUAL", supplier_id, "{}"),
            )
            connector_account_id = int(ca_cur.lastrowid)

            # sync_run (for sync_run_items FK)
            sr_cur = conn.execute(
                "INSERT INTO sync_runs "
                "(connector_account_id, job_type, status, started_at, "
                " records_processed, records_succeeded, records_failed, error_log_json, triggered_by) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    connector_account_id, "inventory", "running",
                    "2026-08-08T10:00:00",
                    0, 0, 0, "[]", "manual",
                ),
            )
            sync_run_id = int(sr_cur.lastrowid)

        return {
            "cat_id":               cat_id,
            "product_id":           product_id,
            "user_id":              user_id,
            "supplier_id":          supplier_id,
            "location_id":          location_id,
            "offer_id":             offer_id,
            "connector_account_id": connector_account_id,
            "sync_run_id":          sync_run_id,
        }

    # ── main test ─────────────────────────────────────────────────────────────

    def test_migration_0010_succeeds_on_populated_database(self):
        """Migration 0009→0010 must succeed and add all new tables/columns."""

        # Step 1: apply 0001-0009
        _apply_up_to_0009(self.db, self.staging)
        schema_before = migrator.current_version(self.db)
        self.assertEqual(schema_before, "0009", f"Expected schema 0009, got {schema_before!r}")

        # Step 2: insert fixture rows
        ids = self._insert_fixture_rows()

        # Step 3: apply migration 0010
        shutil.copy(_MIGRATION_0010, self.staging / _MIGRATION_0010.name)
        try:
            migrator.upgrade(self.db, self.staging)
        except Exception as exc:
            self.fail(
                f"Migration 0009→0010 must succeed on a populated database, "
                f"but it raised {type(exc).__name__}: {exc}"
            )

        schema_after = migrator.current_version(self.db)
        self.assertEqual(schema_after, "0010", f"Expected schema 0010, got {schema_after!r}")

        # Assertion 1: PRAGMA foreign_key_check = 0 rows
        fk_violations = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(
            len(fk_violations), 0,
            f"post-0010: foreign_key_check must return 0 violations; got: {fk_violations}",
        )

        # Assertion 2: PRAGMA foreign_keys = 1
        fk_on = self.db.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(fk_on, 1, "post-0010: PRAGMA foreign_keys must be 1 (ON)")

        # Assertion 3: Table erp_product_mappings exists
        self.assertTrue(
            _table_exists(self.db, "erp_product_mappings"),
            "post-0010: table 'erp_product_mappings' must exist",
        )

        # Assertion 4: Table sync_run_items exists
        self.assertTrue(
            _table_exists(self.db, "sync_run_items"),
            "post-0010: table 'sync_run_items' must exist",
        )

        # Assertion 5: Table import_jobs exists
        self.assertTrue(
            _table_exists(self.db, "import_jobs"),
            "post-0010: table 'import_jobs' must exist",
        )

        # Assertion 6: Table import_job_rows exists
        self.assertTrue(
            _table_exists(self.db, "import_job_rows"),
            "post-0010: table 'import_job_rows' must exist",
        )

        # Assertion 7: connector_accounts has mock_erp_dataset column
        self.assertTrue(
            _column_exists(self.db, "connector_accounts", "mock_erp_dataset"),
            "post-0010: connector_accounts must have 'mock_erp_dataset' column after ALTER",
        )

        connector_account_id = ids["connector_account_id"]
        product_id           = ids["product_id"]
        supplier_id          = ids["supplier_id"]
        sync_run_id          = ids["sync_run_id"]
        user_id              = ids["user_id"]

        # Assertion 8: Can INSERT erp_product_mapping row
        with self.db.write_transaction() as conn:
            epm_cur = conn.execute(
                """
                INSERT INTO erp_product_mappings
                    (connector_account_id, erp_product_code, product_id, supplier_id,
                     confidence_score_bps, match_method, status,
                     created_at, updated_at)
                VALUES (?, 'ERP-TEST-001', ?, ?, 10000, 'manual', 'pending_review',
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (connector_account_id, product_id, supplier_id),
            )
            epm_id = int(epm_cur.lastrowid)
        self.assertGreater(epm_id, 0, "post-0010: erp_product_mapping insert must return a valid id")

        # Assertion 9: UNIQUE(connector_account_id, erp_product_code) constraint works
        with self.assertRaises(
            (sqlite3.IntegrityError, Exception),
            msg="post-0010: UNIQUE(connector_account_id, erp_product_code) must reject duplicates",
        ):
            with self.db.write_transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO erp_product_mappings
                        (connector_account_id, erp_product_code, product_id, supplier_id,
                         confidence_score_bps, match_method, status,
                         created_at, updated_at)
                    VALUES (?, 'ERP-TEST-001', ?, ?, 10000, 'manual', 'pending_review',
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    """,
                    (connector_account_id, product_id, supplier_id),
                )

        # Assertion 10: Can INSERT import_job row
        with self.db.write_transaction() as conn:
            ij_cur = conn.execute(
                """
                INSERT INTO import_jobs
                    (supplier_id, filename, status, total_rows, valid_rows, error_rows,
                     column_mapping_json, error_summary_json, created_by,
                     created_at, updated_at)
                VALUES (?, 'test_mig10.csv', 'pending', 0, 0, 0, '{}', '[]', ?,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (supplier_id, user_id),
            )
            ij_id = int(ij_cur.lastrowid)
        self.assertGreater(ij_id, 0, "post-0010: import_job insert must return a valid id")

        # Assertion 11: Can INSERT import_job_row
        with self.db.write_transaction() as conn:
            ijr_cur = conn.execute(
                """
                INSERT INTO import_job_rows
                    (import_job_id, row_number, raw_json, status,
                     validation_errors_json, created_at)
                VALUES (?, 1, '{}', 'valid', '[]',
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (ij_id,),
            )
            ijr_id = int(ijr_cur.lastrowid)
        self.assertGreater(ijr_id, 0, "post-0010: import_job_row insert must return a valid id")

        # Assertion 12: sync_run_items FK to sync_runs works
        with self.db.write_transaction() as conn:
            sri_cur = conn.execute(
                """
                INSERT INTO sync_run_items
                    (sync_run_id, external_code, status, created_at)
                VALUES (?, 'ERP-TEST-001', 'unmapped',
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (sync_run_id,),
            )
            sri_id = int(sri_cur.lastrowid)
        self.assertGreater(sri_id, 0, "post-0010: sync_run_item insert must return a valid id")

        # Also verify FK enforcement: non-existent sync_run_id must be rejected
        with self.assertRaises(
            (sqlite3.IntegrityError, Exception),
            msg="post-0010: FK from sync_run_items.sync_run_id must be enforced",
        ):
            with self.db.write_transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO sync_run_items
                        (sync_run_id, external_code, status, created_at)
                    VALUES (999999, 'GHOST', 'unmapped',
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    """,
                )

        # Final FK check
        fk_final = self.db.connection.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(
            len(fk_final), 0,
            f"final: foreign_key_check must return 0 violations; got: {fk_final}",
        )


if __name__ == "__main__":
    unittest.main()
