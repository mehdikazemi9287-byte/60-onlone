"""Integration scenarios for Phase 6 — end-to-end story tests (A–L).

Each scenario is a standalone test method exercising the full service stack
on a real migrated database.
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase
from app.core.errors import ValidationError
from app.services import (
    identifier_service,
    inventory_source_service,
    price_source_service,
    mapping_service,
    csv_import_service,
)
from app.adapters.connectors.registry import get_adapter
from app.adapters.connectors.mock_erp import MockErpConnector


class Phase6ScenariosTest(AppTestCase):
    """Integration scenarios A through L for Phase 6 features."""

    # ── shared fixture helpers ────────────────────────────────────────────────

    def _make_supplier_and_offer(self):
        sup  = self.create_test_supplier()
        prod = self.create_test_product_with_offer(sup["supplier_id"], sup["location_id"])
        return sup["supplier_id"], prod["product_id"], prod["offer_id"]

    def _get_any_user_id(self) -> int:
        with self.db.read_transaction() as conn:
            row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        return row["id"]

    def _create_connector_account(self, supplier_id: int,
                                   connector_type: str = "MANUAL") -> int:
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO connector_accounts "
                "(name, connector_type, supplier_id, config_json) "
                "VALUES (?,?,?,?)",
                (f"CA-{connector_type}", connector_type, supplier_id, "{}"),
            )
            return int(cur.lastrowid)

    # ── Scenario A: Barcode Registration ─────────────────────────────────────

    def test_scenario_a_barcode_registration(self):
        """A: Add a barcode → resolve finds it → duplicate raises."""
        supplier_id, product_id, _ = self._make_supplier_and_offer()
        barcode = "6260090000001"

        # Add the identifier
        with self.db.write_transaction() as conn:
            identifier_service.add_identifier(
                conn,
                product_id=product_id,
                supplier_id=supplier_id,
                identifier_type="barcode",
                identifier_value=barcode,
            )

        # Resolve finds it
        with self.db.read_transaction() as conn:
            result = identifier_service.resolve_by_identifier(
                conn,
                identifier_type="barcode",
                identifier_value=barcode,
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["product_id"], product_id)

        # Duplicate raises ValidationError
        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                identifier_service.add_identifier(
                    conn,
                    product_id=product_id,
                    supplier_id=supplier_id,
                    identifier_type="barcode",
                    identifier_value=barcode,
                )

    # ── Scenario B: Identifier Conflict ──────────────────────────────────────

    def test_scenario_b_identifier_conflict(self):
        """B: Create conflict, verify status='open', resolve to 'resolved_merge'."""
        supplier_id, product_id_a, _ = self._make_supplier_and_offer()
        _, product_id_b, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()

        # Create conflict manually (same barcode for two different products)
        with self.db.write_transaction() as conn:
            conflict = identifier_service.create_conflict(
                conn,
                product_id_a=product_id_a,
                product_id_b=product_id_b,
                identifier_type="barcode",
                identifier_value="6260090000002",
            )
        conflict_id = conflict["id"]
        self.assertEqual(conflict["status"], "open")

        # Resolve it
        with self.db.write_transaction() as conn:
            resolved = identifier_service.resolve_conflict(
                conn,
                conflict_id=conflict_id,
                resolution="resolved_merge",
                resolved_by=user_id,
                notes="محصول A و B ادغام شدند",
            )

        self.assertEqual(resolved["status"], "resolved_merge")
        self.assertIsNotNone(resolved["resolved_at"])

    # ── Scenario C: Inventory Source Priority ─────────────────────────────────

    def test_scenario_c_inventory_source_priority(self):
        """C: High-priority source wins over low-priority."""
        supplier_id, _, offer_id = self._make_supplier_and_offer()

        with self.db.write_transaction() as conn:
            low_src = inventory_source_service.create_inventory_source(
                conn, name="منبع اولویت پایین", source_type="manual",
                supplier_id=supplier_id, priority=0,
            )
            high_src = inventory_source_service.create_inventory_source(
                conn, name="منبع اولویت بالا", source_type="manual",
                supplier_id=supplier_id, priority=10,
            )
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

    # ── Scenario D: Out-of-Order Stock Rejected ───────────────────────────────

    def test_scenario_d_out_of_order_stock_rejected(self):
        """D: Stale version update does not replace current quantity."""
        supplier_id, _, offer_id = self._make_supplier_and_offer()

        with self.db.write_transaction() as conn:
            src = inventory_source_service.create_inventory_source(
                conn, name="منبع D", source_type="manual",
                supplier_id=supplier_id, priority=5,
            )
            # Newer update first
            inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id,
                quantity=100, version=5,
            )
            # Stale update (older version)
            inventory_source_service.update_stock(
                conn, inventory_source_id=src["id"], offer_id=offer_id,
                quantity=999, version=3,
            )

        with self.db.read_transaction() as conn:
            auth = inventory_source_service.get_authoritative_stock(conn, offer_id)

        self.assertEqual(auth["quantity"], 100, "Stale update must not replace current quantity")

    # ── Scenario E: Price Source Priority ─────────────────────────────────────

    def test_scenario_e_price_source_priority(self):
        """E: High-priority price source wins."""
        supplier_id, _, offer_id = self._make_supplier_and_offer()

        with self.db.write_transaction() as conn:
            low_psrc = price_source_service.create_price_source(
                conn, name="قیمت اولویت پایین", source_type="manual",
                supplier_id=supplier_id, priority=0,
            )
            high_psrc = price_source_service.create_price_source(
                conn, name="قیمت اولویت بالا", source_type="manual",
                supplier_id=supplier_id, priority=10,
            )
            price_source_service.update_price(
                conn, price_source_id=low_psrc["id"], offer_id=offer_id,
                price_minor=10_000, version=1,
            )
            price_source_service.update_price(
                conn, price_source_id=high_psrc["id"], offer_id=offer_id,
                price_minor=20_000, version=1,
            )

        with self.db.read_transaction() as conn:
            auth = price_source_service.get_authoritative_price(conn, offer_id)

        self.assertIsNotNone(auth)
        self.assertEqual(auth["price_minor"], 20_000)

    # ── Scenario F: No Float Money in Price Source ────────────────────────────

    def test_scenario_f_no_float_money(self):
        """F: Float price_minor raises ValidationError; integer succeeds."""
        supplier_id, _, offer_id = self._make_supplier_and_offer()

        with self.db.write_transaction() as conn:
            src = price_source_service.create_price_source(
                conn, name="منبع قیمت F", source_type="manual",
                supplier_id=supplier_id, priority=1,
            )

        # Float must raise
        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                price_source_service.update_price(
                    conn, price_source_id=src["id"], offer_id=offer_id,
                    price_minor=500.0,     # float — must be rejected
                    version=1,
                )

        # Integer must succeed
        with self.db.write_transaction() as conn:
            entry = price_source_service.update_price(
                conn, price_source_id=src["id"], offer_id=offer_id,
                price_minor=500,           # integer — OK
                version=1,
            )
        self.assertEqual(entry["price_minor"], 500)

    # ── Scenario G: Mock ERP Health Check ────────────────────────────────────

    def test_scenario_g_mock_erp_health_check(self):
        """G: get_adapter('MOCK_ERP').health_check() returns healthy=True."""
        adapter = get_adapter("MOCK_ERP")
        result  = adapter.health_check()

        self.assertTrue(result["healthy"])

    # ── Scenario H: Mock ERP Pull Products ───────────────────────────────────

    def test_scenario_h_mock_erp_pull_products(self):
        """H: pull_products(limit=5) returns 5 items with integer price_minor."""
        adapter  = MockErpConnector(dataset="products")
        products = adapter.pull_products(limit=5, offset=0)

        self.assertEqual(len(products), 5)
        for p in products:
            self.assertIn("code",           p)
            self.assertIn("name",           p)
            self.assertIn("stock_quantity", p)
            self.assertIn("price_minor",    p)
            self.assertIsInstance(p["price_minor"],    int,
                                  "price_minor must be int, not float")
            self.assertIsInstance(p["stock_quantity"], int)
            self.assertNotIn(".", str(p["price_minor"]),
                             "price_minor must not contain a decimal point")

    # ── Scenario I: ERP Mapping Workflow ─────────────────────────────────────

    def test_scenario_i_erp_mapping_workflow(self):
        """I: Create mapping (pending) → approve → resolve_erp_code returns product_id."""
        supplier_id, product_id, offer_id = self._make_supplier_and_offer()
        user_id    = self._get_any_user_id()
        account_id = self._create_connector_account(supplier_id)

        # Create mapping (pending_review)
        with self.db.write_transaction() as conn:
            m = mapping_service.create_mapping(
                conn,
                connector_account_id=account_id,
                erp_product_code="ERP-I-001",
                product_id=product_id,
                supplier_id=supplier_id,
            )
        self.assertEqual(m["status"], "pending_review")

        # Approve it
        with self.db.write_transaction() as conn:
            updated = mapping_service.review_mapping(
                conn,
                mapping_id=m["id"],
                new_status="active",
                reviewed_by=user_id,
                product_id=product_id,
            )
        self.assertEqual(updated["status"], "active")

        # resolve_erp_code returns product_id
        with self.db.read_transaction() as conn:
            result = mapping_service.resolve_erp_code(
                conn,
                connector_account_id=account_id,
                erp_product_code="ERP-I-001",
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["product_id"], product_id)

    # ── Scenario J: CSV Import Round-Trip ────────────────────────────────────

    def test_scenario_j_csv_import_round_trip(self):
        """J: Create job → submit valid CSV → confirm → stock updated."""
        supplier_id, product_id, offer_id = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()
        barcode = "6260099000009"

        # Register identifier
        with self.db.write_transaction() as conn:
            identifier_service.add_identifier(
                conn,
                product_id=product_id,
                supplier_id=supplier_id,
                identifier_type="barcode",
                identifier_value=barcode,
            )

        # Create job + submit CSV
        with self.db.write_transaction() as conn:
            job = csv_import_service.create_import_job(
                conn,
                supplier_id=supplier_id,
                filename="scenario_j.csv",
                created_by=user_id,
            )

        csv_text = f"barcode,stock_quantity\n{barcode},55\n"

        with self.db.write_transaction() as conn:
            submitted = csv_import_service.submit_csv_for_import(
                conn,
                import_job_id=job["id"],
                csv_text=csv_text,
                supplier_id=supplier_id,
            )
        self.assertEqual(submitted["status"], "previewing")

        # Confirm
        with self.db.write_transaction() as conn:
            confirmed = csv_import_service.confirm_import(
                conn,
                import_job_id=job["id"],
                supplier_id=supplier_id,
            )
        self.assertIn(confirmed["status"], ("completed", "completed_with_errors"))

        # Verify stock updated
        with self.db.read_transaction() as conn:
            offer_row = conn.execute(
                "SELECT stock_quantity FROM seller_offers WHERE id=?",
                (offer_id,),
            ).fetchone()
        self.assertEqual(offer_row["stock_quantity"], 55)

    # ── Scenario K: Supplier Isolation (Inventory Sources) ────────────────────

    def test_scenario_k_supplier_isolation_inventory_sources(self):
        """K: Supplier A's inventory source is not visible to Supplier B."""
        supplier_a_id, _, _ = self._make_supplier_and_offer()
        supplier_b_id, _, _ = self._make_supplier_and_offer()

        with self.db.write_transaction() as conn:
            inventory_source_service.create_inventory_source(
                conn,
                name="منبع تأمین‌کننده A",
                source_type="manual",
                supplier_id=supplier_a_id,
                priority=0,
            )

        with self.db.read_transaction() as conn:
            sources_b = inventory_source_service.list_inventory_sources(
                conn, supplier_id=supplier_b_id
            )

        source_names = [s["name"] for s in sources_b]
        self.assertNotIn(
            "منبع تأمین‌کننده A",
            source_names,
            "Supplier B must not see Supplier A's inventory sources",
        )

    # ── Scenario L: CSV Import Validation Gate ────────────────────────────────

    def test_scenario_l_csv_import_validation_gate(self):
        """L: All-invalid CSV → validation_failed; confirm raises ValidationError."""
        supplier_id, _, _ = self._make_supplier_and_offer()
        user_id = self._get_any_user_id()

        with self.db.write_transaction() as conn:
            job = csv_import_service.create_import_job(
                conn,
                supplier_id=supplier_id,
                filename="scenario_l_bad.csv",
                created_by=user_id,
            )

        # All rows missing identifier and data columns
        bad_csv = textwrap.dedent("""\
            product_name
            کالای بد
            کالای بدتر
            کالای بدترین
        """)

        with self.db.write_transaction() as conn:
            submitted = csv_import_service.submit_csv_for_import(
                conn,
                import_job_id=job["id"],
                csv_text=bad_csv,
                supplier_id=supplier_id,
            )
        self.assertEqual(submitted["status"], "validation_failed")

        # confirm_import on a validation_failed job must raise ValidationError
        with self.assertRaises(ValidationError):
            with self.db.write_transaction() as conn:
                csv_import_service.confirm_import(
                    conn,
                    import_job_id=job["id"],
                    supplier_id=supplier_id,
                )


if __name__ == "__main__":
    unittest.main()
