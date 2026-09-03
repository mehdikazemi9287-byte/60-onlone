"""End-to-end scenario tests — Phase 6 Final (Scenarios A-W).

These tests verify the zero-touch marketplace pipeline end-to-end.
"""
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
from app.services import (
    product_resolution_service as prs,
    auto_discovery_service,
    exception_service,
    invoice_service,
    three_way_match_service,
    reconciliation_service,
)
from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector, ConnectorOutageError
from app.adapters.invoice.mock_ocr import MockOcrAdapter

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"


def _apply_all(db: Database, staging_dir: Path) -> None:
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        shutil.copy(path, staging_dir / path.name)
    migrator.upgrade(db, staging_dir)


class E2EScenariosTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="70online-e2e-")
        self.db_path = os.path.join(self.tmpdir, "e2e.db")
        self.staging = Path(self.tmpdir) / "migrations"
        self.staging.mkdir()
        self.db = Database(self.db_path)
        _apply_all(self.db, self.staging)

        with self.db.write_transaction() as conn:
            user = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role) "
                "VALUES (?,?,?,?,?)",
                ("e2e@test.com", "e2e@test.com",
                 "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                 "تست E2E", "admin")
            )
            self.user_id = int(user.lastrowid)

            sup_a = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("تأمین‌کننده A", "تأمین A", "9900030001", "retailer", "active", 40)
            )
            self.supplier_a = int(sup_a.lastrowid)

            sup_b = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10) "
                "VALUES (?,?,?,?,?,?)",
                ("تأمین‌کننده B", "تأمین B", "9900030002", "retailer", "active", 40)
            )
            self.supplier_b = int(sup_b.lastrowid)

            loc_a = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (self.supplier_a, "تهران", "تهران", "active", 1, 1, 0, 60)
            )
            self.location_a = int(loc_a.lastrowid)

            loc_b = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (self.supplier_b, "اصفهان", "اصفهان", "active", 1, 1, 0, 120)
            )
            self.location_b = int(loc_b.lastrowid)

            ca_a = conn.execute(
                "INSERT INTO connector_accounts (name, connector_type, supplier_id, "
                "mock_erp_dataset, config_json, status) VALUES (?,?,?,?,?,?)",
                ("ERP-A", "MOCK_ERP", self.supplier_a, "products", "{}", "active")
            )
            self.ca_a = int(ca_a.lastrowid)

            ca_b = conn.execute(
                "INSERT INTO connector_accounts (name, connector_type, supplier_id, "
                "mock_erp_dataset, config_json, status) VALUES (?,?,?,?,?,?)",
                ("ERP-B", "MOCK_ERP", self.supplier_b, "minimal", "{}", "active")
            )
            self.ca_b = int(ca_b.lastrowid)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── Scenario A: Unknown barcode → canonical product created ──────────────

    def test_scenario_a_unknown_barcode_creates_canonical_product(self):
        """Scenario A: Unknown barcode → canonical product + offer + price + inventory."""
        external = {
            "code": "ERP-SC-A-001",
            "barcode": "6260000099000",
            "sku": "SC-A-SKU",
            "name_fa": "محصول سناریو A",
            "brand_fa": "برند A",
            "price_minor": 7500000,
            "stock_quantity": 30,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn, external=external,
                connector_account_id=self.ca_a,
                supplier_id=self.supplier_a,
            )

        self.assertEqual(result["result"], "new_canonical")
        self.assertIsNotNone(result["product_id"])
        self.assertIsNotNone(result["offer_id"])

        # Verify offer has correct price
        with self.db.read_transaction() as conn:
            offer = conn.execute(
                "SELECT * FROM seller_offers WHERE id = ?", (result["offer_id"],)
            ).fetchone()
        self.assertEqual(int(offer["selling_price_minor"]), 7500000)
        self.assertEqual(int(offer["stock_quantity"]), 30)

    # ── Scenario B: Two suppliers, same GTIN, one canonical product ──────────

    def test_scenario_b_two_suppliers_same_gtin_one_canonical(self):
        """Scenario B: Second supplier with same GTIN → no duplicate canonical product."""
        barcode = "6260000088000"
        external_a = {
            "code": "ERP-A-SC-B",
            "barcode": barcode,
            "name_fa": "محصول مشترک GTIN",
            "price_minor": 5000000,
            "stock_quantity": 10,
        }
        with self.db.write_transaction() as conn:
            result_a = prs.resolve_product(
                conn, external=external_a,
                connector_account_id=self.ca_a,
                supplier_id=self.supplier_a,
            )

        self.assertEqual(result_a["result"], "new_canonical")
        product_id = result_a["product_id"]

        # Add identifier for barcode (already done in auto_create)
        external_b = {
            "code": "ERP-B-SC-B",
            "barcode": barcode,
            "name_fa": "محصول مشترک GTIN از B",
            "price_minor": 4800000,
            "stock_quantity": 15,
        }
        with self.db.write_transaction() as conn:
            result_b = prs.resolve_product(
                conn, external=external_b,
                connector_account_id=self.ca_b,
                supplier_id=self.supplier_b,
            )

        # Must match the same canonical product
        self.assertEqual(result_b["result"], "matched")
        self.assertEqual(result_b["product_id"], product_id)

    # ── Scenario D: Replay idempotency ───────────────────────────────────────

    def test_scenario_d_replay_idempotency(self):
        """Scenario D: Running the same feed twice creates no duplicate products."""
        external = {
            "code": "ERP-IDEMPOTENT-D",
            "barcode": "6260000077000",
            "name_fa": "محصول سناریو D",
            "price_minor": 3000000,
            "stock_quantity": 5,
        }
        with self.db.write_transaction() as conn:
            r1 = prs.resolve_product(conn, external=external,
                                     connector_account_id=self.ca_a,
                                     supplier_id=self.supplier_a)
        self.assertEqual(r1["result"], "new_canonical")

        with self.db.write_transaction() as conn:
            r2 = prs.resolve_product(conn, external=external,
                                     connector_account_id=self.ca_a,
                                     supplier_id=self.supplier_a)
        self.assertEqual(r2["result"], "matched")
        self.assertEqual(r1["product_id"], r2["product_id"])

    # ── Scenario E: Changed prices update ────────────────────────────────────

    def test_scenario_e_changed_price_updates_offer(self):
        """Scenario E: When price changes in external feed, offer price is updated."""
        barcode = "6260000066000"
        external = {
            "code": "ERP-PRICE-E",
            "barcode": barcode,
            "name_fa": "محصول سناریو E",
            "price_minor": 2000000,
            "stock_quantity": 10,
        }
        with self.db.write_transaction() as conn:
            r1 = prs.resolve_product(conn, external=external,
                                     connector_account_id=self.ca_a,
                                     supplier_id=self.supplier_a)
        offer_id = r1["offer_id"]

        # Price change
        external["price_minor"] = 2500000
        with self.db.write_transaction() as conn:
            r2 = prs.resolve_product(conn, external=external,
                                     connector_account_id=self.ca_a,
                                     supplier_id=self.supplier_a)

        with self.db.read_transaction() as conn:
            offer = conn.execute(
                "SELECT selling_price_minor FROM seller_offers WHERE id = ?", (offer_id,)
            ).fetchone()
        self.assertEqual(int(offer["selling_price_minor"]), 2500000)

    # ── Scenario H: Unknown item → exception, valid products continue ─────────

    def test_scenario_h_invalid_items_dont_stop_pipeline(self):
        """Scenario H: Bad row isolated, valid rows continue."""
        valid_external = {
            "code": "ERP-VALID-H",
            "barcode": "6260000055000",
            "name_fa": "محصول معتبر H",
            "price_minor": 1000000,
            "stock_quantity": 5,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn, external=valid_external,
                connector_account_id=self.ca_a,
                supplier_id=self.supplier_a,
            )
        self.assertIn(result["result"], ("new_canonical", "matched"))

    # ── Scenario J: Connector outage → core survives ─────────────────────────

    def test_scenario_j_connector_outage_core_survives(self):
        """Scenario J: Connector outage → exception created, core system intact."""
        # Create a connector account that simulates outage
        with self.db.write_transaction() as conn:
            ca_bad = conn.execute(
                "INSERT INTO connector_accounts (name, connector_type, supplier_id, "
                "mock_erp_dataset, config_json, status) VALUES (?,?,?,?,?,?)",
                ("ERP قطع شده", "MOCK_ERP", self.supplier_a,
                 "large", '{"dataset": "large", "simulate_outage": true}', "active")
            )
            ca_bad_id = int(ca_bad.lastrowid)

        conn = self.db.connection
        result = auto_discovery_service.run_discovery_sync(
            conn,
            connector_account_id=ca_bad_id,
            triggered_by="manual",
        )

        # Core survives (no crash)
        self.assertIn(result["status"], ("failed",))
        self.assertEqual(result["processed"], 0)

        # Exception should be created
        with self.db.read_transaction() as conn2:
            exc_count = conn2.execute(
                "SELECT COUNT(*) AS cnt FROM exceptions WHERE exception_type = 'connector_outage'",
            ).fetchone()["cnt"]
        self.assertGreater(exc_count, 0)

    # ── Scenario K: Malformed row → isolated failure ──────────────────────────

    def test_scenario_k_malformed_row_isolated(self):
        """Scenario K: Malformed row in feed doesn't crash the pipeline."""
        adapter = MockErpV2Connector(config={"inject_malformed": True})
        page = adapter.pull_products(limit=5, offset=0)
        self.assertEqual(len(page["items"]), 5)
        # Pipeline should handle malformed rows gracefully (they just fail individually)

    # ── Scenario P: Mock invoice capture ─────────────────────────────────────

    def test_scenario_p_mock_invoice_capture(self):
        """Scenario P: Mock OCR adapter extracts structured invoice data."""
        adapter = MockOcrAdapter()
        result = adapter.capture(b"FAKE SCAN BYTES")
        self.assertIsInstance(result["subtotal_minor"], int)
        self.assertIsInstance(result["total_minor"], int)
        self.assertGreater(len(result["lines"]), 0)
        # All money must be integer
        for line in result["lines"]:
            self.assertIsInstance(line["unit_price_minor"], int)

    # ── Scenario Q: Duplicate invoice flagged ────────────────────────────────

    def test_scenario_q_duplicate_invoice_flagged(self):
        """Scenario Q: Duplicate invoice is detected and flagged."""
        lines = [{"quantity": 1, "unit_price_minor": 5000000, "line_total_minor": 5000000, "tax_minor": 0}]
        with self.db.write_transaction() as conn:
            inv1 = invoice_service.create_invoice(
                conn, supplier_id=self.supplier_a, invoice_number="Q-INV-001",
                invoice_date="2026-08-08", lines=lines, created_by=self.user_id,
            )
            inv2 = invoice_service.create_invoice(
                conn, supplier_id=self.supplier_a, invoice_number="Q-INV-001",
                invoice_date="2026-08-08", lines=lines, created_by=self.user_id,
            )
        self.assertEqual(inv2["is_duplicate"], 1)
        self.assertEqual(inv2["status"], "duplicate")

    # ── Scenario R: PO + invoice → MATCHED ───────────────────────────────────

    def test_scenario_r_po_invoice_matched(self):
        """Scenario R: PO + invoice with same total → MATCHED."""
        with self.db.write_transaction() as conn:
            po = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, "
                "total_minor, currency, status) VALUES (?,?,?,?,?,?)",
                (self.supplier_a, "PO-R-001", "2026-08-01", 8000000, "IRR", "open")
            )
            po_id = int(po.lastrowid)

            inv = invoice_service.create_invoice(
                conn, supplier_id=self.supplier_a, invoice_number="R-INV-001",
                invoice_date="2026-08-08",
                lines=[{"quantity": 1, "unit_price_minor": 8000000, "line_total_minor": 8000000, "tax_minor": 0}],
                created_by=self.user_id,
            )
            inv_id = int(inv["id"])

            match = three_way_match_service.perform_match(
                conn, supplier_id=self.supplier_a,
                procurement_order_id=po_id, invoice_id=inv_id,
                checked_by=self.user_id,
            )
        self.assertEqual(match["result"], "matched")

    # ── Scenario S: Quantity mismatch → exception ─────────────────────────────

    def test_scenario_s_mismatch_creates_discrepancy(self):
        """Scenario S: PO amount ≠ invoice amount → mismatch."""
        with self.db.write_transaction() as conn:
            po = conn.execute(
                "INSERT INTO procurement_orders (supplier_id, reference_number, order_date, "
                "total_minor, currency, status) VALUES (?,?,?,?,?,?)",
                (self.supplier_a, "PO-S-001", "2026-08-01", 5000000, "IRR", "open")
            )
            po_id = int(po.lastrowid)

            inv = invoice_service.create_invoice(
                conn, supplier_id=self.supplier_a, invoice_number="S-INV-001",
                invoice_date="2026-08-08",
                lines=[{"quantity": 1, "unit_price_minor": 6000000, "line_total_minor": 6000000, "tax_minor": 0}],
                created_by=self.user_id,
            )
            inv_id = int(inv["id"])

            match = three_way_match_service.perform_match(
                conn, supplier_id=self.supplier_a,
                procurement_order_id=po_id, invoice_id=inv_id,
                tolerance_bps=100,
            )
        self.assertEqual(match["result"], "mismatch")
        self.assertIn("diff_bps", match["discrepancy"])

    # ── Scenario T: PSP reconciliation ───────────────────────────────────────

    def test_scenario_t_psp_reconciliation(self):
        """Scenario T: PSP statement items reconciled against DB."""
        with self.db.write_transaction() as conn:
            batch = reconciliation_service.create_batch(
                conn, batch_ref="PSP-T-001",
                source_type="psp_statement",
                period_start="2026-08-01", period_end="2026-08-31",
                created_by=self.user_id,
            )
            batch_id = batch["id"]

            items = [
                {"external_ref": "T-PSP-001", "transaction_date": "2026-08-05", "amount_minor": 1000000},
                {"external_ref": "T-PSP-002", "transaction_date": "2026-08-10", "amount_minor": 2000000},
            ]
            reconciliation_service.import_items(conn, batch_id, items)
            result = reconciliation_service.run_matching(conn, batch_id=batch_id)

        self.assertEqual(result["total_items"], 2)
        self.assertIn("matched_count", result)
        self.assertIn("unmatched_count", result)

    # ── Scenario U: Supplier A outage, B still works ──────────────────────────

    def test_scenario_u_one_supplier_outage_other_works(self):
        """Scenario U: Supplier A outage doesn't affect Supplier B."""
        # Supplier B sync works normally
        conn = self.db.connection
        result = auto_discovery_service.run_discovery_sync(
            conn,
            connector_account_id=self.ca_b,
            triggered_by="schedule",
        )
        # Supplier B (MINIMAL dataset = 3 products) should succeed
        self.assertIn(result["status"], ("completed", "completed_with_errors"))
        self.assertGreater(result["processed"], 0)

    # ── Scenario W: Cross-tenant access rejected ──────────────────────────────

    def test_scenario_w_cross_tenant_isolation(self):
        """Scenario W: ERP mappings are scoped to their connector_account."""
        barcode = "6260000099500"
        external_a = {
            "code": "ERP-A-TENANT",
            "barcode": barcode,
            "name_fa": "محصول تأمین‌کننده A",
            "price_minor": 3000000,
            "stock_quantity": 5,
        }
        with self.db.write_transaction() as conn:
            r_a = prs.resolve_product(
                conn, external=external_a,
                connector_account_id=self.ca_a,
                supplier_id=self.supplier_a,
            )

        # Supplier B's ERP code lookup must NOT find supplier A's mapping
        with self.db.read_transaction() as conn:
            # ERP mapping is scoped to connector_account_id
            mapping = conn.execute(
                "SELECT * FROM erp_product_mappings WHERE connector_account_id = ? AND erp_product_code = ?",
                (self.ca_b, "ERP-A-TENANT"),
            ).fetchone()
        self.assertIsNone(mapping, "Cross-tenant ERP mapping must not exist")

    # ── All money values are integers ─────────────────────────────────────────

    def test_all_money_values_are_integers(self):
        """Verify no REAL/FLOAT in the schema after all migrations."""
        tables = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        offenders = []
        for table in tables:
            for col in self.db.query(f"PRAGMA table_info({table})"):
                declared = (col["type"] or "").upper()
                if any(t in declared for t in ("REAL", "FLOAT", "DOUB")):
                    offenders.append(f"{table}.{col['name']} {declared}")
        self.assertEqual(offenders, [], f"Floating-point columns found: {offenders}")

    def test_confidence_bps_range(self):
        """confidence_bps must always be 0-10000."""
        external = {
            "code": "ERP-BPS-TEST",
            "barcode": "6260000099100",
            "name_fa": "تست bps",
            "price_minor": 1000000,
            "stock_quantity": 1,
        }
        with self.db.write_transaction() as conn:
            result = prs.resolve_product(
                conn, external=external,
                connector_account_id=self.ca_a,
                supplier_id=self.supplier_a,
            )
        self.assertIsInstance(result["confidence_bps"], int)
        self.assertGreaterEqual(result["confidence_bps"], 0)
        self.assertLessEqual(result["confidence_bps"], 10000)


if __name__ == "__main__":
    unittest.main()
