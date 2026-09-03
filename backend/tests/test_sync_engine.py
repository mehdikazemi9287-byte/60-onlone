"""Unit tests for sync_engine_service.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import NotFoundError, ValidationError
from app.services import sync_engine_service, inventory_source_service


class SyncEngineServiceTest(AppTestCase):
    """Tests for sync run lifecycle, item recording, and run_full_sync."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_supplier_and_offer(self):
        sup  = self.create_test_supplier()
        prod = self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"])
        return sup["supplier_id"], prod["product_id"], prod["offer_id"]

    def _create_connector_account(self, supplier_id: int,
                                  connector_type: str = "MANUAL") -> int:
        """Insert a connector_account row and return its id."""
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO connector_accounts "
                "(name, connector_type, supplier_id, config_json) "
                "VALUES (?, ?, ?, ?)",
                (f"حساب آزمایشی {connector_type}", connector_type, supplier_id, "{}"),
            )
            return int(cur.lastrowid)

    def _create_inventory_source(self, supplier_id: int,
                                  connector_account_id: int) -> int:
        """Create an inventory_source linked to a connector_account and return its id."""
        with self.db.write_transaction() as conn:
            src = inventory_source_service.create_inventory_source(
                conn,
                name="منبع موجودی آزمایشی",
                source_type="connector",
                supplier_id=supplier_id,
                priority=5,
                connector_account_id=connector_account_id,
            )
            return src["id"]

    def _create_erp_mapping(self, connector_account_id: int,
                             erp_code: str, product_id: int,
                             supplier_id: int) -> None:
        """Insert an active erp_product_mapping row."""
        with self.db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO erp_product_mappings
                    (connector_account_id, erp_product_code, product_id, supplier_id,
                     confidence_score_bps, match_method, status,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, 10000, 'manual', 'active',
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                """,
                (connector_account_id, erp_code, product_id, supplier_id),
            )

    # ── lifecycle tests ───────────────────────────────────────────────────────

    def test_start_and_complete_sync_run(self):
        """start_sync_run creates a running run; complete_sync_run transitions to completed."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        account_id = self._create_connector_account(supplier_id)

        with self.db.write_transaction() as conn:
            run_id = sync_engine_service.start_sync_run(
                conn,
                connector_account_id=account_id,
                job_type="inventory",
            )
            self.assertIsNotNone(run_id)
            self.assertGreater(run_id, 0)

            sync_engine_service.complete_sync_run(
                conn,
                run_id=run_id,
                status="completed",
                records_processed=5,
                records_succeeded=5,
                records_failed=0,
            )

        with self.db.read_transaction() as conn:
            run = sync_engine_service.get_sync_run(conn, run_id)

        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["records_processed"], 5)
        self.assertEqual(run["records_succeeded"], 5)
        self.assertEqual(run["records_failed"], 0)
        self.assertIsNotNone(run["completed_at"])

    def test_complete_sync_run_failed(self):
        """complete_sync_run with status='failed' stores error_log correctly."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        account_id = self._create_connector_account(supplier_id)

        with self.db.write_transaction() as conn:
            run_id = sync_engine_service.start_sync_run(
                conn,
                connector_account_id=account_id,
                job_type="inventory",
            )
            sync_engine_service.complete_sync_run(
                conn,
                run_id=run_id,
                status="failed",
                error_log=["خطای اتصال", "تایم‌اوت"],
            )

        with self.db.read_transaction() as conn:
            run = sync_engine_service.get_sync_run(conn, run_id)

        self.assertEqual(run["status"], "failed")
        self.assertIsInstance(run["error_log"], list)
        self.assertGreaterEqual(len(run["error_log"]), 1)

    def test_add_sync_run_item(self):
        """add_sync_run_item inserts a row; list_sync_run_items returns it."""
        supplier_id, product_id, offer_id = self._make_supplier_and_offer()
        account_id = self._create_connector_account(supplier_id)

        with self.db.write_transaction() as conn:
            run_id = sync_engine_service.start_sync_run(
                conn,
                connector_account_id=account_id,
                job_type="inventory",
            )
            sync_engine_service.add_sync_run_item(
                conn,
                sync_run_id=run_id,
                external_code="ERP-TEST-001",
                product_id=product_id,
                offer_id=offer_id,
                status="mapped",
                action_taken="موجودی به‌روزرسانی شد",
            )

        with self.db.read_transaction() as conn:
            items = sync_engine_service.list_sync_run_items(conn, run_id)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["external_code"], "ERP-TEST-001")
        self.assertEqual(items[0]["status"], "mapped")
        self.assertEqual(items[0]["product_id"], product_id)

    # ── full sync tests ───────────────────────────────────────────────────────

    def test_run_full_sync_mock_erp_inventory(self):
        """run_full_sync with a MOCK_ERP adapter finds the mapping and marks item 'mapped'."""
        supplier_id, product_id, offer_id = self._make_supplier_and_offer()

        # Use MANUAL connector_type (within DB CHECK) but mock get_adapter
        account_id = self._create_connector_account(supplier_id, connector_type="MANUAL")
        inv_source_id = self._create_inventory_source(supplier_id, account_id)

        # Create an active ERP mapping for ERP-001 → our product
        self._create_erp_mapping(account_id, "ERP-001", product_id, supplier_id)

        # Build a mock adapter that returns one inventory item for ERP-001
        mock_adapter = MagicMock()
        mock_adapter.pull_inventory.return_value = [
            {
                "code":           "ERP-001",
                "quantity":       200,
                "stock_quantity": 200,
                "version":        1,
            }
        ]

        with patch(
            "app.adapters.connectors.registry.get_adapter",
            return_value=mock_adapter,
        ):
            with self.db.write_transaction() as conn:
                result = sync_engine_service.run_full_sync(
                    conn,
                    connector_account_id=account_id,
                    job_type="inventory",
                )

        self.assertIn("run_id", result)
        run_id = result["run_id"]

        with self.db.read_transaction() as conn:
            run   = sync_engine_service.get_sync_run(conn, run_id)
            items = sync_engine_service.list_sync_run_items(conn, run_id)

        # The run must be completed (with or without errors)
        self.assertIn(run["status"], ("completed", "completed_with_errors"))
        self.assertEqual(result["records_processed"], 1)

        # At least one item should have status='mapped' for ERP-001
        mapped = [i for i in items if i["status"] == "mapped"]
        self.assertGreater(len(mapped), 0, "ERP-001 must be mapped via active erp_product_mapping")

    def test_run_full_sync_not_implemented_raises(self):
        """run_full_sync raises ValidationError when the adapter's pull_inventory raises NotImplementedError."""
        supplier_id, _, _ = self._make_supplier_and_offer()

        # HOLO_ERP is a valid connector_type in the DB CHECK and returns NotYetImplementedAdapter
        account_id = self._create_connector_account(supplier_id, connector_type="HOLO_ERP")

        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                sync_engine_service.run_full_sync(
                    conn,
                    connector_account_id=account_id,
                    job_type="inventory",
                )

    def test_get_sync_run_not_found_raises(self):
        """get_sync_run raises NotFoundError for a non-existent run_id."""
        with self.assertRaises(NotFoundError):
            with self.db.read_transaction() as conn:
                sync_engine_service.get_sync_run(conn, 999_999)

    def test_list_sync_runs_filter_by_account(self):
        """list_sync_runs filters by connector_account_id."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        account_a = self._create_connector_account(supplier_id)
        account_b = self._create_connector_account(supplier_id)

        with self.db.write_transaction() as conn:
            run_a = sync_engine_service.start_sync_run(
                conn, connector_account_id=account_a, job_type="inventory"
            )
            run_b = sync_engine_service.start_sync_run(
                conn, connector_account_id=account_b, job_type="prices"
            )

        with self.db.read_transaction() as conn:
            runs_a = sync_engine_service.list_sync_runs(conn, connector_account_id=account_a)
            runs_b = sync_engine_service.list_sync_runs(conn, connector_account_id=account_b)

        run_ids_a = [r["id"] for r in runs_a]
        run_ids_b = [r["id"] for r in runs_b]

        self.assertIn(run_a, run_ids_a)
        self.assertNotIn(run_b, run_ids_a)
        self.assertIn(run_b, run_ids_b)
        self.assertNotIn(run_a, run_ids_b)


if __name__ == "__main__":
    unittest.main()
