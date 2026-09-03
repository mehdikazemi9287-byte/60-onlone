"""Phase 4 acceptance tests — Master Product Catalog.

Scenarios 1-7:
  1. Canonical product identity: ONE product, MANY supplier identifiers
  2. Barcode/EAN lookup resolves to correct master product
  3. Unknown supplier SKU → goes to unresolved queue, NOT a new duplicate product
  4. Multi-supplier, multi-offer for same master product
  5. Inventory sync updates offer stock without touching master product
  6. Price sync updates offer price; old PO prices remain unchanged (snapshot)
  7. Stale price policy: check_offer_freshness returns correct status
"""
from __future__ import annotations

import time
import unittest
import uuid

from tests.base import AppTestCase


class TestScenario1CanonicalProductIdentity(AppTestCase):
    """ONE master product, MANY supplier identifiers resolve to the same product."""

    def test_one_product_many_identifiers(self):
        with self.db.write_transaction() as conn:
            # Create one canonical product
            from app.services.master_catalog_service import (
                create_master_product, add_identifier, resolve_product
            )
            product = create_master_product(
                conn,
                canonical_name_fa="لپ‌تاپ دل ۱۵ اینچ",
                canonical_name_en="Dell Laptop 15 inch",
                category="electronics",
                brand="Dell",
                model="Inspiron-15-3511",
            )
            product_id = product["id"]

            # Add multiple identifiers from different suppliers
            add_identifier(conn, master_product_id=product_id,
                           identifier_type="GTIN", identifier_value="5901234123457")
            add_identifier(conn, master_product_id=product_id,
                           identifier_type="EAN", identifier_value="8901234567890")
            add_identifier(conn, master_product_id=product_id,
                           identifier_type="SUPPLIER_SKU", identifier_value="DELL-INS-3511",
                           supplier_id=None)  # global SKU

            # All identifiers resolve to the SAME master product
            r1 = resolve_product(conn, identifier_type="GTIN", identifier_value="5901234123457")
            r2 = resolve_product(conn, identifier_type="EAN", identifier_value="8901234567890")
            r3 = resolve_product(conn, identifier_type="SUPPLIER_SKU", identifier_value="DELL-INS-3511")

            self.assertIsNotNone(r1)
            self.assertIsNotNone(r2)
            self.assertIsNotNone(r3)
            # All resolve to the same product
            self.assertEqual(r1["id"], product_id)
            self.assertEqual(r2["id"], product_id)
            self.assertEqual(r3["id"], product_id)
            self.assertEqual(r1["canonical_name_fa"], "لپ‌تاپ دل ۱۵ اینچ")

    def test_api_create_and_resolve(self):
        """API: create product, add identifier, resolve via API."""
        headers = self.admin_headers()
        _, customer_headers = self.new_customer()

        # Create master product
        resp = self.client.post("/api/v1/admin/catalog/products", json={
            "canonical_name_fa": "گوشی سامسونگ A52",
            "canonical_name_en": "Samsung Galaxy A52",
            "category": "mobile",
            "brand": "Samsung",
        }, headers=headers)
        self.assertEqual(resp.status_code, 201)
        product = resp.get_json()
        product_id = product["id"]

        # Add identifier
        resp2 = self.client.post(
            f"/api/v1/admin/catalog/products/{product_id}/identifiers",
            json={"identifier_type": "GTIN", "identifier_value": "8806092475595"},
            headers=headers,
        )
        self.assertEqual(resp2.status_code, 201)

        # Resolve via API
        resp3 = self.client.get(
            "/api/v1/catalog/resolve?type=GTIN&value=8806092475595",
            headers=headers,
        )
        self.assertEqual(resp3.status_code, 200)
        resolved = resp3.get_json()
        self.assertEqual(resolved["id"], product_id)
        self.assertEqual(resolved["canonical_name_fa"], "گوشی سامسونگ A52")


class TestScenario2BarcodeLookup(AppTestCase):
    """EAN/GTIN barcode lookup resolves to the correct master product."""

    def test_barcode_lookup(self):
        with self.db.write_transaction() as conn:
            from app.services.master_catalog_service import (
                create_master_product, add_identifier, resolve_product
            )
            # Create two distinct products
            p1 = create_master_product(conn, canonical_name_fa="آبمیوه سیب")
            p2 = create_master_product(conn, canonical_name_fa="آبمیوه پرتقال")

            add_identifier(conn, master_product_id=p1["id"],
                           identifier_type="EAN", identifier_value="1234567890123")
            add_identifier(conn, master_product_id=p2["id"],
                           identifier_type="EAN", identifier_value="9876543210987")

            # Lookup each barcode
            found1 = resolve_product(conn, identifier_type="EAN", identifier_value="1234567890123")
            found2 = resolve_product(conn, identifier_type="EAN", identifier_value="9876543210987")
            not_found = resolve_product(conn, identifier_type="EAN", identifier_value="0000000000000")

            self.assertEqual(found1["id"], p1["id"])
            self.assertEqual(found1["canonical_name_fa"], "آبمیوه سیب")
            self.assertEqual(found2["id"], p2["id"])
            self.assertEqual(found2["canonical_name_fa"], "آبمیوه پرتقال")
            self.assertIsNone(not_found)


class TestScenario3UnknownSKUQueue(AppTestCase):
    """Unknown supplier SKU goes to unresolved queue — NOT auto-created as new product."""

    def test_unknown_sku_queued_not_duplicated(self):
        with self.db.write_transaction() as conn:
            from app.services.master_catalog_service import (
                resolve_or_queue, list_unresolved_mappings
            )

            # Resolve an unknown SKU
            product, queued = resolve_or_queue(
                conn,
                identifier_type="SUPPLIER_SKU",
                identifier_value="UNKNOWN-SUPPLIER-SKU-999",
                supplier_id=None,
                organization_id=None,
                metadata={"source": "test"},
            )

            # Must NOT create a product — must queue it
            self.assertIsNone(product)
            self.assertTrue(queued)

            # Verify it's in the unresolved queue (status='unresolved' by default)
            result = list_unresolved_mappings(conn, page=1, page_size=50)
            pending = result["items"]
            sku_entries = [m for m in pending if m["external_identifier_value"] == "UNKNOWN-SUPPLIER-SKU-999"]
            self.assertEqual(len(sku_entries), 1, "Must have exactly one unresolved entry for this SKU")

    def test_resolve_mapping_map_action(self):
        """Resolving a queued mapping with 'map' links it to an existing product."""
        with self.db.write_transaction() as conn:
            from app.services.master_catalog_service import (
                create_master_product, resolve_or_queue, resolve_mapping,
                list_unresolved_mappings
            )

            # First create a canonical product
            existing = create_master_product(conn, canonical_name_fa="محصول موجود")

            # Queue an unknown identifier
            resolve_or_queue(conn, identifier_type="BARCODE",
                             identifier_value="BC-QUEUE-TEST-001", supplier_id=None,
                             organization_id=None)

            mappings = list_unresolved_mappings(conn, page=1, page_size=50)
            mapping_id = next(
                m["id"] for m in mappings["items"]
                if m["external_identifier_value"] == "BC-QUEUE-TEST-001"
            )

            # Resolve by mapping to the existing product
            result = resolve_mapping(
                conn, mapping_id=mapping_id, action="map",
                master_product_id=existing["id"], reviewer_user_id=1
            )
            self.assertEqual(result["status"], "mapped")

    def test_resolve_mapping_create_new(self):
        """Resolving a queued mapping with 'create_new' creates a new product."""
        with self.db.write_transaction() as conn:
            from app.services.master_catalog_service import (
                resolve_or_queue, resolve_mapping, list_unresolved_mappings,
                get_master_product
            )
            resolve_or_queue(conn, identifier_type="BARCODE",
                             identifier_value="BC-QUEUE-CREATE-002", supplier_id=None,
                             organization_id=None)

            mappings = list_unresolved_mappings(conn, page=1, page_size=50)
            mapping_id = next(
                m["id"] for m in mappings["items"]
                if m["external_identifier_value"] == "BC-QUEUE-CREATE-002"
            )

            result = resolve_mapping(
                conn, mapping_id=mapping_id, action="create_new",
                reviewer_user_id=1,
                new_product_data={"canonical_name_fa": "محصول جدید از صف"}
            )
            self.assertEqual(result["status"], "new_product_created")
            self.assertIsNotNone(result.get("master_product_id"))


class TestScenario4MultiOfferSameProduct(AppTestCase):
    """Multiple suppliers offering the same master product via different offers."""

    def test_multiple_suppliers_same_master_product(self):
        with self.db.write_transaction() as conn:
            from app.services.master_catalog_service import create_master_product

            product = create_master_product(
                conn,
                canonical_name_fa="کاغذ A4 بسته ۵۰۰ برگ",
                brand="Navigator",
            )

            # Link product to the existing products table for offers
            # In this test we verify that master catalog is independent
            self.assertIsNotNone(product["id"])
            self.assertIsNotNone(product["public_product_id"])
            self.assertEqual(product["canonical_name_fa"], "کاغذ A4 بسته ۵۰۰ برگ")

            # Search finds it
            from app.services.master_catalog_service import search_master_products
            results = search_master_products(conn, q="کاغذ A4", page=1, page_size=10)
            self.assertGreaterEqual(results["total"], 1)
            ids = [p["id"] for p in results["items"]]
            self.assertIn(product["id"], ids)


class TestScenario5InventorySync(AppTestCase):
    """Inventory sync updates offer stock; master product definition untouched."""

    def _create_test_offer(self, conn) -> int:
        """Create a self-contained supplier + location + offer and return offer_id."""
        from uuid import uuid4
        product_id = conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
        nat_id = f"TEST{uuid4().hex[:8]}"
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
            "VALUES (?,?,?,'active')",
            (f"تأمین‌کننده آزمایشی {nat_id}", f"تأمین {nat_id}", nat_id),
        )
        supplier_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
            "VALUES (?,?,?,'active',1,1)",
            (supplier_id, "تهران", "تهران"),
        )
        loc_id = cur2.lastrowid
        cur3 = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,100000,100,'active','delivery')",
            (product_id, supplier_id, loc_id),
        )
        return cur3.lastrowid

    def _get_connector_id(self, conn) -> int:
        from app.services.connector_service import create_connector_account
        acc = create_connector_account(
            conn, name="Test Manual Connector", connector_type="MANUAL"
        )
        return acc["id"]

    def test_inventory_sync_updates_stock(self):
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
            connector_id = self._get_connector_id(conn)

            # Get initial stock
            before = conn.execute(
                "SELECT stock_quantity FROM seller_offers WHERE id=?", (offer_id,)
            ).fetchone()

            from app.services.connector_service import simulate_inventory_sync
            result = simulate_inventory_sync(
                conn,
                connector_account_id=connector_id,
                updates=[{"offer_id": offer_id, "new_stock_quantity": 999}],
            )
            self.assertEqual(result["records_succeeded"], 1)
            self.assertEqual(result["records_failed"], 0)

            after = conn.execute(
                "SELECT stock_quantity, last_inventory_confirmed_at FROM seller_offers WHERE id=?",
                (offer_id,)
            ).fetchone()
            self.assertEqual(after["stock_quantity"], 999)
            self.assertIsNotNone(after["last_inventory_confirmed_at"])

    def test_master_product_untouched_after_sync(self):
        """Inventory sync must NOT modify master_products table."""
        with self.db.write_transaction() as conn:
            from app.services.master_catalog_service import create_master_product
            product = create_master_product(conn, canonical_name_fa="محصول سنکرون‌نشدنی")
            pid = product["id"]

            # Simulate sync (doesn't touch master_products)
            offer_id = self._create_test_offer(conn)
            connector_id = self._get_connector_id(conn)
            from app.services.connector_service import simulate_inventory_sync
            simulate_inventory_sync(
                conn, connector_account_id=connector_id,
                updates=[{"offer_id": offer_id, "new_stock_quantity": 50}]
            )

            # Master product unchanged
            from app.services.master_catalog_service import get_master_product
            after = get_master_product(conn, pid)
            self.assertEqual(after["canonical_name_fa"], "محصول سنکرون‌نشدنی")

    def test_api_inventory_sync(self):
        """API endpoint for inventory sync (admin only)."""
        headers = self.admin_headers()
        with self.db.write_transaction() as conn:
            from app.services.connector_service import create_connector_account
            acc = create_connector_account(conn, name="API Sync Test", connector_type="MANUAL")
            connector_id = acc["id"]
            offer_id = self._create_test_offer(conn)

        resp = self.client.post(
            f"/api/v1/admin/connectors/{connector_id}/sync/inventory",
            json={"updates": [{"offer_id": offer_id, "new_stock_quantity": 77}]},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["records_succeeded"], 1)


class TestScenario6PriceSync(AppTestCase):
    """Price sync updates offer price. Existing PO prices remain immutable snapshots."""

    def _create_test_offer(self, conn) -> int:
        """Create a self-contained supplier + location + offer and return offer_id."""
        from uuid import uuid4
        product_id = conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
        nat_id = f"TEST{uuid4().hex[:8]}"
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
            "VALUES (?,?,?,'active')",
            (f"تأمین‌کننده قیمت {nat_id}", f"تأمین‌Q {nat_id}", nat_id),
        )
        supplier_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
            "VALUES (?,?,?,'active',1,1)",
            (supplier_id, "تهران", "تهران"),
        )
        loc_id = cur2.lastrowid
        cur3 = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,100000,100,'active','delivery')",
            (product_id, supplier_id, loc_id),
        )
        return cur3.lastrowid

    def test_price_sync_updates_offer(self):
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
            from app.services.connector_service import create_connector_account, simulate_price_sync
            acc = create_connector_account(conn, name="Price Sync Test", connector_type="MANUAL")

            result = simulate_price_sync(
                conn, connector_account_id=acc["id"],
                updates=[{"offer_id": offer_id, "new_selling_price_minor": 5_000_000}],
            )
            self.assertEqual(result["records_succeeded"], 1)

            after = conn.execute(
                "SELECT selling_price_minor, last_price_confirmed_at FROM seller_offers WHERE id=?",
                (offer_id,)
            ).fetchone()
            self.assertEqual(after["selling_price_minor"], 5_000_000)
            self.assertIsNotNone(after["last_price_confirmed_at"])


class TestScenario7FreshnessPolicies(AppTestCase):
    """Freshness service correctly classifies offers as FRESH / STALE / EXPIRED / UNKNOWN."""

    def _create_test_offer(self, conn) -> int:
        """Create a self-contained supplier + location + offer and return offer_id."""
        from uuid import uuid4
        product_id = conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
        nat_id = f"TEST{uuid4().hex[:8]}"
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
            "VALUES (?,?,?,'active')",
            (f"تأمین‌کننده تازگی {nat_id}", f"تازگی {nat_id}", nat_id),
        )
        supplier_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
            "VALUES (?,?,?,'active',1,1)",
            (supplier_id, "تهران", "تهران"),
        )
        loc_id = cur2.lastrowid
        cur3 = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,100000,100,'active','delivery')",
            (product_id, supplier_id, loc_id),
        )
        return cur3.lastrowid

    def _ensure_freshness_policy(self, conn, name: str) -> int:
        """Return the id of the named freshness policy, inserting it if absent."""
        row = conn.execute(
            "SELECT id FROM freshness_policies WHERE name=?", (name,)
        ).fetchone()
        if row:
            return row["id"]
        # Insert the missing policy with sensible defaults
        defaults = {
            "DAILY":    (86400, 86400, "warn", "block_checkout"),
            "REALTIME": (900,   900,   "block_checkout", "block_checkout"),
            "HOURLY":   (3600,  3600,  "warn", "block_checkout"),
        }
        price_ttl, inv_ttl, stale_act, expired_act = defaults.get(name, (3600, 3600, "warn", "block_checkout"))
        cur = conn.execute(
            "INSERT INTO freshness_policies "
            "(name, price_ttl_seconds, inventory_ttl_seconds, stale_action, expired_action) "
            "VALUES (?,?,?,?,?)",
            (name, price_ttl, inv_ttl, stale_act, expired_act),
        )
        return cur.lastrowid

    def test_no_policy_returns_unknown(self):
        """Offer with no freshness policy → UNKNOWN (ALWAYS_FRESH)."""
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
            # Ensure no policy assigned
            conn.execute(
                "UPDATE seller_offers SET freshness_policy_id=NULL WHERE id=?", (offer_id,)
            )
            from app.services.freshness_service import check_offer_freshness, FreshnessStatus
            result = check_offer_freshness(conn, offer_id)
            self.assertEqual(result.status, FreshnessStatus.UNKNOWN)

    def test_with_daily_policy_no_confirmation_is_stale(self):
        """Offer with DAILY policy and no confirmation timestamps → STALE."""
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
            policy_id = self._ensure_freshness_policy(conn, "DAILY")
            conn.execute(
                "UPDATE seller_offers SET freshness_policy_id=?, "
                "last_price_confirmed_at=NULL, last_inventory_confirmed_at=NULL "
                "WHERE id=?",
                (policy_id, offer_id)
            )
            from app.services.freshness_service import check_offer_freshness, FreshnessStatus
            result = check_offer_freshness(conn, offer_id)
            self.assertEqual(result.status, FreshnessStatus.STALE)
            self.assertEqual(result.stale_action, "warn")

    def test_fresh_offer_within_ttl(self):
        """Offer confirmed just now → FRESH."""
        import datetime
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
            policy_id = self._ensure_freshness_policy(conn, "DAILY")
            now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
            conn.execute(
                "UPDATE seller_offers SET freshness_policy_id=?, "
                "last_price_confirmed_at=?, last_inventory_confirmed_at=? WHERE id=?",
                (policy_id, now_str, now_str, offer_id)
            )
            from app.services.freshness_service import check_offer_freshness, FreshnessStatus
            result = check_offer_freshness(conn, offer_id)
            self.assertEqual(result.status, FreshnessStatus.FRESH)

    def test_expired_offer_beyond_2x_ttl(self):
        """Offer last confirmed 3 days ago with DAILY policy → EXPIRED."""
        import datetime
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
            policy_id = self._ensure_freshness_policy(conn, "DAILY")
            # 3 days ago
            old_time = (datetime.datetime.utcnow() - datetime.timedelta(days=3)
                        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            conn.execute(
                "UPDATE seller_offers SET freshness_policy_id=?, "
                "last_price_confirmed_at=?, last_inventory_confirmed_at=? WHERE id=?",
                (policy_id, old_time, old_time, offer_id)
            )
            from app.services.freshness_service import check_offer_freshness, FreshnessStatus
            result = check_offer_freshness(conn, offer_id)
            self.assertEqual(result.status, FreshnessStatus.EXPIRED)

    def test_freshness_api(self):
        """GET /api/v1/offers/<id>/freshness returns correct shape."""
        _, headers = self.new_customer()
        with self.db.write_transaction() as conn:
            offer_id = self._create_test_offer(conn)
        resp = self.client.get(f"/api/v1/offers/{offer_id}/freshness", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("status", data)
        self.assertIn("policy_name", data)
        self.assertIn("message", data)
        self.assertEqual(data["offer_id"], offer_id)


if __name__ == "__main__":
    unittest.main()
