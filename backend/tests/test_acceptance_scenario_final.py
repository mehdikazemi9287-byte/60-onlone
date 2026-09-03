"""NEW FINAL ACCEPTANCE SCENARIO — end-to-end proof.

Supplier A sends unknown GTIN X:
  → ProductKnowledgeSource enriches X
  → canonical product P created
  → field_provenance persisted
  → Offer A created
  → price_source_entry A + inventory_source_stock A created

Supplier B sends SAME GTIN X:
  → same canonical product P (matched)
  → independent Offer B created
  → independent price_source_entry B + inventory_source_stock B
  → Offer A price/stock UNCHANGED

Stale update from A → ignored.
Fresh inventory from B → accepted.
Supplier A outage → Supplier B still resolves.
"""
import unittest
from tests.base import AppTestCase
from app.services import product_resolution_service as prs
from app.adapters.connectors.mock_erp_v2 import ConnectorOutageError


def _insert_supplier(conn, email: str, nat_id: str, display: str) -> tuple[int, int]:
    """Insert a user + supplier. Returns (supplier_id, user_id)."""
    cur = conn.execute(
        "INSERT INTO users (email, email_normalized, password_hash, full_name, role, is_active) VALUES (?,?,?,?,?,?)",
        (email, email.lower(),
         "$2b$12$aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
         display, "supplier", 1),
    )
    user_id = int(cur.lastrowid)
    cur = conn.execute(
        "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, rating_x10, user_id) VALUES (?,?,?,?,?,?,?)",
        (display, display, nat_id, "retailer", "active", 40, user_id),
    )
    supplier_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO supplier_locations (supplier_id, province, city, status, can_local_delivery, can_intercity_shipping, can_pickup, prep_time_minutes) VALUES (?,?,?,?,?,?,?,?)",
        (supplier_id, "Tehran", "Tehran", "active", 1, 1, 0, 60),
    )
    return supplier_id, user_id


def _create_sync_run(conn, connector_account_id: int) -> int:
    """Insert a sync_run and return its real database id."""
    cur = conn.execute(
        """INSERT INTO sync_runs
           (connector_account_id, job_type, status, started_at, triggered_by)
           VALUES (?, ?, ?, datetime('now'), ?)""",
        (connector_account_id, "full_sync", "completed", "manual"),
    )
    return int(cur.lastrowid)


class FinalAcceptanceScenarioTest(AppTestCase):

    def setUp(self):
        super().setUp()
        # Create two suppliers and their connector accounts
        with self.db.write_transaction() as conn:
            # Supplier A
            self.supplier_a_id, _ = _insert_supplier(
                conn, "supplier_a_final@test.com", "FA111111111", "Supplier A Final"
            )
            cur = conn.execute(
                """INSERT INTO connector_accounts
                   (supplier_id, connector_type, name, status, config_json, mock_erp_dataset)
                   VALUES (?,?,?,?,?,?)""",
                (self.supplier_a_id, "MOCK_ERP", "A-ERP", "active",
                 '{"dataset":"large"}', "products"),
            )
            self.ca_a_id = int(cur.lastrowid)

            # Supplier B
            self.supplier_b_id, _ = _insert_supplier(
                conn, "supplier_b_final@test.com", "FB222222222", "Supplier B Final"
            )
            cur = conn.execute(
                """INSERT INTO connector_accounts
                   (supplier_id, connector_type, name, status, config_json, mock_erp_dataset)
                   VALUES (?,?,?,?,?,?)""",
                (self.supplier_b_id, "MOCK_ERP", "B-ERP", "active",
                 '{"dataset":"large"}', "products"),
            )
            self.ca_b_id = int(cur.lastrowid)

            # Register mock_catalogue in knowledge_sources if not present
            conn.execute(
                """INSERT OR IGNORE INTO knowledge_sources
                   (name, source_type, adapter_key, priority, is_active)
                   VALUES (?,?,?,?,?)""",
                ("mock_catalogue", "mock_catalogue", "mock_catalogue", 100, 1),
            )

        # A barcode known to MockCatalogueKnowledgeSource (index 0 → barcode 6260000000000)
        self.test_barcode = "6260000000000"
        self.external_a = {
            "barcode": self.test_barcode,
            "code": "ERP-00000",
            "sku": "SKU-A-0000",
            "name_fa": "محصول آزمایشی",
            "price_minor": 5000000,
            "stock_quantity": 50,
        }
        self.external_b = {
            "barcode": self.test_barcode,
            "code": "ERP-B-0000",
            "sku": "SKU-B-0000",
            "name_fa": "محصول آزمایشی",
            "price_minor": 6000000,
            "stock_quantity": 30,
        }

    def test_supplier_a_unknown_gtin_creates_canonical_with_knowledge_enrichment(self):
        """Supplier A sends unknown GTIN → knowledge adapter called → product created with enrichment."""
        with self.db.write_transaction() as conn:
            sr_id = _create_sync_run(conn, self.ca_a_id)
            result = prs.resolve_product(
                conn,
                external=self.external_a,
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id,
                sync_run_id=sr_id,
            )
        self.assertEqual(result["result"], "new_canonical")
        self.assertIsNotNone(result["product_id"])
        self.assertIsNotNone(result["offer_id"])
        # Knowledge adapter must have been consulted
        self.assertIsNotNone(result.get("knowledge_adapter_used"),
                              "knowledge_adapter_used must not be None for unknown GTIN")

    def test_field_provenance_persisted_for_enriched_product(self):
        """field_provenance rows must exist for knowledge-enriched canonical product."""
        with self.db.write_transaction() as conn:
            sr_id = _create_sync_run(conn, self.ca_a_id)
            result = prs.resolve_product(
                conn,
                external=self.external_a,
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id,
                sync_run_id=sr_id,
            )
            product_id = result["product_id"]
            prov_rows = conn.execute(
                "SELECT * FROM field_provenance WHERE entity_type='product' AND entity_id=?",
                (product_id,),
            ).fetchall()
        self.assertGreater(len(prov_rows), 0,
                           "field_provenance must have rows for knowledge-enriched product")
        sources = {r["source_type"] for r in prov_rows}
        self.assertIn("knowledge_source", sources)

    def test_supplier_b_same_gtin_reuses_canonical_creates_new_offer(self):
        """Supplier B sends same GTIN → same canonical product P → NEW Offer B → Offer A unchanged."""
        with self.db.write_transaction() as conn:
            sr_a = _create_sync_run(conn, self.ca_a_id)
            result_a = prs.resolve_product(
                conn,
                external=self.external_a,
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id,
                sync_run_id=sr_a,
            )
            product_p = result_a["product_id"]
            offer_a = result_a["offer_id"]

            # Get Offer A price before B arrives
            price_a_before = conn.execute(
                "SELECT selling_price_minor FROM seller_offers WHERE id = ?", (offer_a,)
            ).fetchone()["selling_price_minor"]

            sr_b = _create_sync_run(conn, self.ca_b_id)
            result_b = prs.resolve_product(
                conn,
                external=self.external_b,
                connector_account_id=self.ca_b_id,
                supplier_id=self.supplier_b_id,
                sync_run_id=sr_b,
            )

        # Same canonical product
        self.assertEqual(result_b["product_id"], product_p,
                         "Supplier B must resolve to same canonical product P")

        # Offer B is different from Offer A
        offer_b = result_b["offer_id"]
        self.assertNotEqual(offer_a, offer_b, "Offer A and Offer B must be different rows")

        # Exactly 1 offer per supplier for this product
        with self.db.read_transaction() as conn:
            offers_a = conn.execute(
                "SELECT id FROM seller_offers WHERE product_id=? AND supplier_id=? AND status='active'",
                (product_p, self.supplier_a_id),
            ).fetchall()
            offers_b = conn.execute(
                "SELECT id FROM seller_offers WHERE product_id=? AND supplier_id=? AND status='active'",
                (product_p, self.supplier_b_id),
            ).fetchall()
            # Offer A price must be unchanged
            price_a_after = conn.execute(
                "SELECT selling_price_minor FROM seller_offers WHERE id=?", (offer_a,)
            ).fetchone()["selling_price_minor"]

        self.assertEqual(len(offers_a), 1, "Supplier A must have exactly 1 offer for product P")
        self.assertEqual(len(offers_b), 1, "Supplier B must have exactly 1 offer for product P")
        self.assertEqual(price_a_after, price_a_before,
                         "Offer A price must be unchanged after Supplier B sync")

    def test_stale_price_update_from_supplier_a_ignored(self):
        """Stale update (lower sync_run_id) must be ignored by price source model."""
        with self.db.write_transaction() as conn:
            # Create two sync_runs: sr_low (first=lower id), sr_high (second=higher id)
            sr_low = _create_sync_run(conn, self.ca_a_id)
            sr_high = _create_sync_run(conn, self.ca_a_id)
            # sr_high > sr_low because auto-increment

            # Fresh update with high version
            result = prs.resolve_product(
                conn,
                external={**self.external_a, "price_minor": 7000000},
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id,
                sync_run_id=sr_high,
            )
            offer_a = result["offer_id"]
            current_price = conn.execute(
                "SELECT price_minor FROM price_source_entries WHERE offer_id=? ORDER BY id DESC LIMIT 1",
                (offer_a,),
            ).fetchone()["price_minor"]

            # Stale update with low version (sr_low < sr_high)
            prs.resolve_product(
                conn,
                external={**self.external_a, "price_minor": 1000000},
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id,
                sync_run_id=sr_low,
            )
            price_after_stale = conn.execute(
                "SELECT price_minor FROM price_source_entries WHERE offer_id=? ORDER BY id DESC LIMIT 1",
                (offer_a,),
            ).fetchone()["price_minor"]

        self.assertEqual(price_after_stale, current_price,
                         "Stale price update must be ignored (version protection)")

    def test_fresh_inventory_from_supplier_b_accepted(self):
        """Fresh inventory from Supplier B must update inventory_source_stock."""
        with self.db.write_transaction() as conn:
            sr_a = _create_sync_run(conn, self.ca_a_id)
            prs.resolve_product(
                conn,
                external=self.external_a,
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id,
                sync_run_id=sr_a,
            )
            sr_b = _create_sync_run(conn, self.ca_b_id)
            result_b = prs.resolve_product(
                conn,
                external={**self.external_b, "stock_quantity": 99},
                connector_account_id=self.ca_b_id,
                supplier_id=self.supplier_b_id,
                sync_run_id=sr_b,
            )
            offer_b = result_b["offer_id"]

            inv_row = conn.execute(
                "SELECT quantity FROM inventory_source_stock WHERE offer_id=? ORDER BY id DESC LIMIT 1",
                (offer_b,),
            ).fetchone()

        self.assertIsNotNone(inv_row, "inventory_source_stock must have a row for Offer B")
        self.assertEqual(int(inv_row["quantity"]), 99)

    def test_supplier_a_outage_supplier_b_still_resolves(self):
        """Supplier A connector outage must not affect Supplier B."""
        from app.adapters.connectors.mock_erp_v2 import MockErpV2Connector
        # Supplier A adapter in outage
        try:
            adapter_a = MockErpV2Connector(config={"simulate_outage": True})
            adapter_a.pull_products(limit=1, offset=0)
        except ConnectorOutageError:
            pass  # Expected

        # Supplier B still resolves fine
        with self.db.write_transaction() as conn:
            sr_b = _create_sync_run(conn, self.ca_b_id)
            result_b = prs.resolve_product(
                conn,
                external=self.external_b,
                connector_account_id=self.ca_b_id,
                supplier_id=self.supplier_b_id,
                sync_run_id=sr_b,
            )
        self.assertIn(result_b["result"], ("new_canonical", "matched"))
        self.assertIsNotNone(result_b["product_id"])

    def test_canonical_product_count_is_one_after_both_suppliers(self):
        """After both suppliers send same GTIN, canonical_products == 1."""
        with self.db.write_transaction() as conn:
            sr_a = _create_sync_run(conn, self.ca_a_id)
            prs.resolve_product(
                conn, external=self.external_a,
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id, sync_run_id=sr_a,
            )
            sr_b = _create_sync_run(conn, self.ca_b_id)
            prs.resolve_product(
                conn, external=self.external_b,
                connector_account_id=self.ca_b_id,
                supplier_id=self.supplier_b_id, sync_run_id=sr_b,
            )
            count = conn.execute(
                """SELECT COUNT(DISTINCT pi.product_id) as cnt
                   FROM product_identifiers pi
                   WHERE pi.identifier_type='barcode' AND pi.identifier_value=?""",
                (self.test_barcode,),
            ).fetchone()["cnt"]
        self.assertEqual(int(count), 1, "Exactly 1 canonical product for this GTIN")

    def test_price_and_inventory_go_through_source_model(self):
        """Price and inventory must be in source model tables, not just seller_offers."""
        with self.db.write_transaction() as conn:
            sr_a = _create_sync_run(conn, self.ca_a_id)
            result = prs.resolve_product(
                conn, external=self.external_a,
                connector_account_id=self.ca_a_id,
                supplier_id=self.supplier_a_id, sync_run_id=sr_a,
            )
            offer_id = result["offer_id"]
            price_entry = conn.execute(
                "SELECT price_minor FROM price_source_entries WHERE offer_id=?", (offer_id,)
            ).fetchone()
            inv_entry = conn.execute(
                "SELECT quantity FROM inventory_source_stock WHERE offer_id=?", (offer_id,)
            ).fetchone()
        self.assertIsNotNone(price_entry, "price_source_entries must have a row for the offer")
        self.assertIsNotNone(inv_entry, "inventory_source_stock must have a row for the offer")
        self.assertEqual(int(price_entry["price_minor"]), 5000000)
        self.assertEqual(int(inv_entry["quantity"]), 50)


if __name__ == "__main__":
    unittest.main()
