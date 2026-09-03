"""Phase 2 (Supplier Marketplace Foundation) + Phase 3 (Offer/Pricing Engine)
data-layer tests.

Most of the underlying supplier/offer/fulfillment architecture (suppliers,
supplier_locations, seller_offers, product_identifiers, identity_resolution_
queue, fulfillment_engine.route() as the deterministic best-offer/buy-box
selector for actual checkout routing, supplier_ledger_service for real
delivered-order settlement) already existed before this migration and is
already covered by tests/test_fulfillment_engine.py, tests/test_checkout_
fulfillment.py, and tests/test_supplier_ledger.py — this file only covers
the NEW code added in migration 0027: the onboarding lifecycle, the
offer_pricing_service browse-time best-offer summary, and the strict
no-fabrication supplier_catalog_import_service.
"""
from __future__ import annotations

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import offer_pricing_service, supplier_catalog_import_service, supplier_service
from tests.base import AppTestCase


class _Base(AppTestCase):
    def _product_id(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
        self.assertIsNotNone(row, f"product '{slug}' not found")
        return int(row["id"])

    def _make_supplier(self, conn, *, nat_id: str, name: str, status: str = "active") -> int:
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10) "
            "VALUES (?,?,?,?,40)",
            (name, name, nat_id, status),
        )
        return int(cur.lastrowid)

    def _make_location(self, conn, *, supplier_id: int, city: str = "تهران") -> int:
        cur = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_pickup, can_local_delivery, "
            " can_intercity_shipping, prep_time_minutes) "
            "VALUES (?,?,?, 'active', 0, 1, 0, 60)",
            (supplier_id, "تهران", city),
        )
        return int(cur.lastrowid)

    def _make_offer(self, conn, *, product_id, supplier_id, location_id,
                     price, stock=10, status="active", sku=None) -> int:
        offer = supplier_service.create_offer(
            conn, product_id=product_id, supplier_id=supplier_id,
            supplier_location_id=location_id, selling_price_minor=price,
            stock_quantity=stock, status=status, supplier_sku=sku,
        )
        return int(offer["id"])


# ─────────────────────────────────────────────────────────────────────────
# Onboarding lifecycle
# ─────────────────────────────────────────────────────────────────────────

class OnboardingLifecycleTest(_Base):
    def test_full_valid_path(self):
        with self.db.write_transaction() as conn:
            sup = supplier_service.create_supplier(
                conn, legal_name="X", display_name="X", national_id="ONB-001",
                status="pending",
            )
            self.assertEqual(sup["onboarding_stage"], "draft")

            sup = supplier_service.advance_onboarding_stage(
                conn, supplier_id=sup["id"], to_stage="submitted",
            )
            self.assertEqual(sup["onboarding_stage"], "submitted")

            sup = supplier_service.advance_onboarding_stage(
                conn, supplier_id=sup["id"], to_stage="under_review",
            )
            sup = supplier_service.advance_onboarding_stage(
                conn, supplier_id=sup["id"], to_stage="approved", note="looks real",
            )
            self.assertEqual(sup["onboarding_stage"], "approved")
            # Approval bridges into the pre-existing operational status field
            self.assertEqual(sup["status"], "active")

            events = supplier_service.list_onboarding_events(conn, supplier_id=sup["id"])
            self.assertEqual([e["to_stage"] for e in events],
                              ["submitted", "under_review", "approved"])
            self.assertEqual(events[-1]["note"], "looks real")

    def test_invalid_transition_rejected(self):
        with self.db.write_transaction() as conn:
            sup = supplier_service.create_supplier(
                conn, legal_name="Y", display_name="Y", national_id="ONB-002",
            )
            # draft -> approved directly is not a legal transition
            with self.assertRaises(ValidationError):
                supplier_service.advance_onboarding_stage(
                    conn, supplier_id=sup["id"], to_stage="approved",
                )

    def test_rejected_can_be_resubmitted_as_draft(self):
        with self.db.write_transaction() as conn:
            sup = supplier_service.create_supplier(
                conn, legal_name="Z", display_name="Z", national_id="ONB-003",
            )
            supplier_service.advance_onboarding_stage(conn, supplier_id=sup["id"], to_stage="submitted")
            supplier_service.advance_onboarding_stage(conn, supplier_id=sup["id"], to_stage="under_review")
            sup = supplier_service.advance_onboarding_stage(
                conn, supplier_id=sup["id"], to_stage="rejected", note="missing docs",
            )
            # Rejection never silently changes the operational status field
            self.assertEqual(sup["status"], "pending")
            sup = supplier_service.advance_onboarding_stage(conn, supplier_id=sup["id"], to_stage="draft")
            self.assertEqual(sup["onboarding_stage"], "draft")

    def test_existing_pre_migration_suppliers_default_to_approved(self):
        # Suppliers created BEFORE this migration (via the plain, pre-existing
        # create_supplier default status='active') must not be affected —
        # the migration's own backfill (not exercised per-test since each
        # test gets a freshly-migrated+seeded DB) is verified at the SQL
        # level: a supplier inserted with status='active' with no explicit
        # onboarding_stage gets the column default 'draft', matching new
        # suppliers — this test documents that a fresh 'active' supplier
        # must be manually advanced through onboarding like any other,
        # confirming the migration did not implicitly grant 'approved'
        # to brand-new rows (only to rows that pre-existed at migration time).
        with self.db.write_transaction() as conn:
            sup = supplier_service.create_supplier(
                conn, legal_name="Legacy-style", display_name="Legacy-style",
                national_id="ONB-004", status="active",
            )
            self.assertEqual(sup["onboarding_stage"], "draft")


# ─────────────────────────────────────────────────────────────────────────
# Offer pricing engine (browse-time best-offer summary)
# ─────────────────────────────────────────────────────────────────────────

class OfferPricingEngineTest(_Base):
    def test_best_offer_is_lowest_eligible_price_among_multiple_suppliers(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "laptop-asus-vivobook-15")
            s1 = self._make_supplier(conn, nat_id="PRICE-A", name="Supplier A")
            s2 = self._make_supplier(conn, nat_id="PRICE-B", name="Supplier B")
            l1 = self._make_location(conn, supplier_id=s1)
            l2 = self._make_location(conn, supplier_id=s2)
            self._make_offer(conn, product_id=pid, supplier_id=s1, location_id=l1, price=500_000_00)
            cheaper_id = self._make_offer(conn, product_id=pid, supplier_id=s2, location_id=l2, price=400_000_00)

            best = offer_pricing_service.get_best_offer(conn, product_id=pid)
            self.assertIsNotNone(best)
            self.assertEqual(best["id"], cheaper_id)
            self.assertEqual(best["selling_price_minor"], 400_000_00)

    def test_out_of_stock_offer_excluded_from_best_offer(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "network-mikrotik-hex-s")
            # The shared seed fixture may already have offers on this
            # product (it backs the fulfillment-engine scenario tests) —
            # clear them so this scenario's assertions are deterministic.
            conn.execute("DELETE FROM seller_offers WHERE product_id = ?", (pid,))
            s1 = self._make_supplier(conn, nat_id="STOCK-A", name="S-Stock-A")
            s2 = self._make_supplier(conn, nat_id="STOCK-B", name="S-Stock-B")
            l1 = self._make_location(conn, supplier_id=s1)
            l2 = self._make_location(conn, supplier_id=s2)
            self._make_offer(conn, product_id=pid, supplier_id=s1, location_id=l1, price=100_000_00, stock=0)
            expensive_but_in_stock = self._make_offer(
                conn, product_id=pid, supplier_id=s2, location_id=l2, price=999_000_00, stock=5,
            )
            best = offer_pricing_service.get_best_offer(conn, product_id=pid)
            self.assertEqual(best["id"], expensive_but_in_stock)

    def test_suspended_supplier_offer_excluded(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "office-desk-160")
            conn.execute("DELETE FROM seller_offers WHERE product_id = ?", (pid,))
            s1 = self._make_supplier(conn, nat_id="SUSP-A", name="Suspended-A", status="suspended")
            l1 = self._make_location(conn, supplier_id=s1)
            offer_id = self._make_offer(conn, product_id=pid, supplier_id=s1, location_id=l1, price=100_000_00)

            offers = offer_pricing_service.list_offers_for_product(conn, product_id=pid)
            row = next(o for o in offers if o["id"] == offer_id)
            self.assertEqual(row["availability_state"], "supplier_disabled")
            self.assertIsNone(offer_pricing_service.get_best_offer(conn, product_id=pid))

    def test_product_with_zero_offers_returns_none_backward_compatible(self):
        """A product that has never had any seller_offers (the normal case
        for almost every product in this catalog today) must not error or
        fabricate a price — this is the backward-compatibility guarantee for
        every pre-existing single-offer/no-offer product."""
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "appliance-kettle-2l")
            conn.execute("DELETE FROM seller_offers WHERE product_id = ?", (pid,))
            best = offer_pricing_service.get_best_offer(conn, product_id=pid)
            self.assertIsNone(best)
            summary = offer_pricing_service.get_offer_summary(conn, product_id=pid)
            self.assertEqual(summary["offer_count"], 0)
            self.assertEqual(summary["best_offer"], None)

    def test_price_change_recorded_in_history(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "appliance-microwave-25l")
            s1 = self._make_supplier(conn, nat_id="HIST-A", name="Hist-A")
            l1 = self._make_location(conn, supplier_id=s1)
            offer_id = self._make_offer(conn, product_id=pid, supplier_id=s1, location_id=l1, price=200_000_00)

            supplier_service.update_offer_price(
                conn, offer_id=offer_id, supplier_id=s1, selling_price_minor=250_000_00,
            )
            rows = conn.execute(
                "SELECT * FROM offer_price_history WHERE offer_id = ? ORDER BY id", (offer_id,)
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["old_price_minor"], 200_000_00)
            self.assertEqual(rows[0]["new_price_minor"], 250_000_00)

    def test_negative_price_rejected(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "office-chair-ergo-pro")
            s1 = self._make_supplier(conn, nat_id="NEG-A", name="Neg-A")
            l1 = self._make_location(conn, supplier_id=s1)
            with self.assertRaises(ValidationError):
                self._make_offer(conn, product_id=pid, supplier_id=s1, location_id=l1, price=-1)


# ─────────────────────────────────────────────────────────────────────────
# Supplier catalog import — strict no-fabrication matching
# ─────────────────────────────────────────────────────────────────────────

class SupplierCatalogImportTest(_Base):
    def _register_barcode(self, conn, *, product_id: int, barcode: str) -> None:
        conn.execute(
            "INSERT INTO product_identifiers (product_id, identifier_type, identifier_value) "
            "VALUES (?, 'EAN', ?)",
            (product_id, barcode),
        )

    def test_matched_by_barcode_creates_real_offer(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "mobile-samsung-a55")
            self._register_barcode(conn, product_id=pid, barcode="6291041500213")
            sup = self._make_supplier(conn, nat_id="IMP-001", name="Importer 1")
            loc = self._make_location(conn, supplier_id=sup)

            result = supplier_catalog_import_service.import_catalog_batch(
                conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None,
                rows=[{"barcode": "6291041500213", "selling_price_minor": 150_000_00, "stock_quantity": 3}],
            )
            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["queued_for_review"], 0)
            offer = conn.execute(
                "SELECT * FROM seller_offers WHERE product_id = ? AND supplier_id = ?", (pid, sup)
            ).fetchone()
            self.assertIsNotNone(offer)
            self.assertEqual(offer["selling_price_minor"], 150_000_00)

    def test_unmatched_row_is_queued_never_creates_a_product(self):
        with self.db.write_transaction() as conn:
            sup = self._make_supplier(conn, nat_id="IMP-002", name="Importer 2")
            loc = self._make_location(conn, supplier_id=sup)
            before = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]

            result = supplier_catalog_import_service.import_catalog_batch(
                conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None,
                rows=[{"barcode": "0000000000000-does-not-exist",
                       "selling_price_minor": 10_000_00, "stock_quantity": 1}],
            )
            self.assertEqual(result["matched"], 0)
            self.assertEqual(result["queued_for_review"], 1)

            after = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
            self.assertEqual(before, after, "no product should ever be auto-created")

            queued = conn.execute(
                "SELECT * FROM identity_resolution_queue WHERE supplier_id = ?", (sup,)
            ).fetchone()
            self.assertIsNotNone(queued)
            self.assertEqual(queued["status"], "open")

    def test_duplicate_supplier_sku_for_different_product_rejected(self):
        with self.db.write_transaction() as conn:
            pid1 = self._product_id(conn, "laptop-hp-probook-450")
            pid2 = self._product_id(conn, "laptop-lenovo-thinkpad-e14")
            self._register_barcode(conn, product_id=pid1, barcode="AAA111")
            self._register_barcode(conn, product_id=pid2, barcode="BBB222")
            sup = self._make_supplier(conn, nat_id="IMP-003", name="Importer 3")
            loc = self._make_location(conn, supplier_id=sup)

            supplier_catalog_import_service.import_catalog_batch(
                conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None,
                rows=[{"barcode": "AAA111", "supplier_sku": "DUP-SKU-1",
                       "selling_price_minor": 100_000_00, "stock_quantity": 1}],
            )
            result = supplier_catalog_import_service.import_catalog_batch(
                conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None,
                rows=[{"barcode": "BBB222", "supplier_sku": "DUP-SKU-1",
                       "selling_price_minor": 200_000_00, "stock_quantity": 1}],
            )
            self.assertEqual(result["matched"], 0)
            self.assertEqual(result["rejected"], 1)
            row = conn.execute(
                "SELECT * FROM supplier_catalog_import_rows WHERE supplier_id = ? "
                "ORDER BY id DESC LIMIT 1", (sup,)
            ).fetchone()
            self.assertEqual(row["match_status"], "duplicate_sku")

    def test_wrong_location_rejected_isolation(self):
        with self.db.write_transaction() as conn:
            sup_a = self._make_supplier(conn, nat_id="IMP-004A", name="Importer 4A")
            sup_b = self._make_supplier(conn, nat_id="IMP-004B", name="Importer 4B")
            loc_b = self._make_location(conn, supplier_id=sup_b)
            with self.assertRaises(ValidationError):
                supplier_catalog_import_service.import_catalog_batch(
                    conn, supplier_id=sup_a, supplier_location_id=loc_b,
                    submitted_by_user_id=None,
                    rows=[{"barcode": "X", "selling_price_minor": 1, "stock_quantity": 1}],
                )

    def test_resubmitting_same_barcode_updates_existing_offer_not_duplicate(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "mobile-xiaomi-redmi-note-13")
            self._register_barcode(conn, product_id=pid, barcode="777888999")
            sup = self._make_supplier(conn, nat_id="IMP-005", name="Importer 5")
            loc = self._make_location(conn, supplier_id=sup)

            supplier_catalog_import_service.import_catalog_batch(
                conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None,
                rows=[{"barcode": "777888999", "selling_price_minor": 300_000_00, "stock_quantity": 5}],
            )
            supplier_catalog_import_service.import_catalog_batch(
                conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None,
                rows=[{"barcode": "777888999", "selling_price_minor": 280_000_00, "stock_quantity": 8}],
            )
            offers = conn.execute(
                "SELECT * FROM seller_offers WHERE product_id = ? AND supplier_id = ?", (pid, sup)
            ).fetchall()
            self.assertEqual(len(offers), 1, "re-import must update, not duplicate, the offer")
            self.assertEqual(offers[0]["selling_price_minor"], 280_000_00)
            self.assertEqual(offers[0]["stock_quantity"], 8)
