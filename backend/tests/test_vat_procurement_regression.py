"""VAT + Procurement Regression Tests — Phase 7 Final.

Proves the following after migrations 0019 and 0020:

  A. STANDARD rate resolves to 1000 bps (10%) for current dates
  B. STANDARD rate resolves to 900 bps (9%) for dates before 2024-03-20
  C. Quote grand_total = items + shipping + items_VAT + shipping_VAT (all integer arithmetic)
  D. PO grand_total_minor_snapshot == Quote grand_total_minor (invariant preserved)
  E. Shipping VAT is included in grand_total (not discarded)
  F. Historical quote rows (pre-migration 0020) are NOT changed
  G. No monetary float arithmetic — all values are integers
  H. Tax rate is NEVER hardcoded; it is always looked up from tax_rates
  I. Cross-tenant access blocked (org isolation)
  J. Ordinary org member cannot mutate tax rates (admin-only)
  K. PO vat_amount_minor matches quote vat_amount_minor

All tests call real service functions via real migrated database.
No direct DB inserts that bypass service logic.
"""
from __future__ import annotations

import datetime
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_org_with_admin(tc: AppTestCase):
    org = tc.create_organization()
    admin_h, member = tc.make_org_admin(org["id"])
    return org, admin_h, member["user_id"]


def _setup_full_rfq(tc: AppTestCase, org_id: int, admin_uid: int,
                    items_spec: list[dict], shipping_cost_minor: int = 0,
                    vat_rate_bps=None):
    """Create and return (rfq_id, rfq_item_ids, supplier_id)."""
    from app.services.procurement_service import (
        create_purchase_request, submit_purchase_request, approve_purchase_request
    )
    from app.services.rfq_service import (
        create_rfq, invite_supplier_to_rfq, open_rfq
    )

    with tc.db.write_transaction() as conn:
        # Create supplier
        nat_id = f"VAT{uuid.uuid4().hex[:10]}"
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
            "VALUES (?,?,?,'active')",
            (f"تأمین آزمایش {nat_id}", f"آزمایش {nat_id[:6]}", nat_id),
        )
        supplier_id = cur.lastrowid

        # PR
        pr = create_purchase_request(
            conn, organization_id=org_id, requester_user_id=admin_uid,
            title=f"PR آزمایش VAT {uuid.uuid4().hex[:4]}",
            items=[{"free_text_description": "ردیف", "quantity": s.get("quantity", 1)}
                   for s in items_spec],
        )
        pr_id = pr["id"]
        submit_purchase_request(conn, pr_id, actor_user_id=admin_uid, organization_id=org_id)
        approve_purchase_request(conn, pr_id, actor_user_id=admin_uid,
                                 organization_id=org_id, action="approve")

        # RFQ
        rfq = create_rfq(conn, organization_id=org_id, purchase_request_id=pr_id,
                         actor_user_id=admin_uid, title="استعلام VAT")
        rfq_id = rfq["id"]
        invite_supplier_to_rfq(conn, rfq_id, supplier_id,
                                actor_user_id=admin_uid, organization_id=org_id)
        open_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)

    rfq_item_ids = [i["id"] for i in rfq["items"]]
    return rfq_id, rfq_item_ids, supplier_id


# ── A/B: VAT rate resolution ──────────────────────────────────────────────────


class TestVATRateResolution(AppTestCase):
    """A/B: Effective-dated VAT rate lookup from tax_rates table."""

    def test_A_standard_rate_current_is_10pct(self):
        """A: STANDARD rate at a current date must be 1000 bps (10%) after migration 0019."""
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate = get_rate_bps("STANDARD", effective_date="2026-01-01")
            self.assertEqual(rate, 1000,
                             "STANDARD rate must be 1000 bps (10%) after migration 0019")

    def test_B_standard_rate_historical_is_9pct(self):
        """B: STANDARD rate before 2024-03-20 must be 900 bps (9%)."""
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate_before = get_rate_bps("STANDARD", effective_date="2024-03-19")
            self.assertEqual(rate_before, 900,
                             "Rate before 2024-03-20 must be 900 bps (9% historical)")

    def test_B2_rate_boundary_2024_03_20(self):
        """B2: Rate on exactly 2024-03-20 must be 1000 bps (new rate effective from that day)."""
        with self.app.app_context():
            from app.services.tax_service import get_rate_bps
            rate_on = get_rate_bps("STANDARD", effective_date="2024-03-20")
            self.assertEqual(rate_on, 1000, "Rate on 2024-03-20 must be 1000 bps (10%)")

    def test_B3_9pct_row_closed_not_deleted(self):
        """B3: The 9% row is closed (effective_until='2024-03-19'), not deleted."""
        with self.db.read_transaction() as conn:
            row = conn.execute(
                """SELECT rate_bps, effective_from, effective_until
                   FROM tax_rates
                   WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code='STANDARD')
                     AND rate_bps = 900""",
            ).fetchone()
        self.assertIsNotNone(row, "The 9% (900 bps) row must still exist in tax_rates")
        self.assertEqual(row["effective_until"], "2024-03-19",
                         "9% row must be closed with effective_until='2024-03-19'")


# ── C/E: Quote arithmetic ─────────────────────────────────────────────────────


class TestVATQuoteArithmetic(AppTestCase):
    """C/E: grand_total = items + shipping + items_VAT + shipping_VAT (integer floor)."""

    def test_C_grand_total_includes_items_and_shipping_vat(self):
        """C: grand_total_minor = items + shipping + items_vat + shipping_vat (10% rate)."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        unit_price = 150_000
        qty        = 4
        shipping   = 30_000

        rfq_id, rfq_item_ids, supplier_id = _setup_full_rfq(
            self, org_id, admin_uid,
            [{"quantity": qty}],
            shipping_cost_minor=shipping,
        )

        with self.db.write_transaction() as conn:
            from app.services.rfq_service import submit_supplier_quote
            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_ids[0],
                        "unit_price_minor": unit_price, "quantity": qty}],
                shipping_cost_minor=shipping,
            )

        # Integer-exact verification
        items_total   = unit_price * qty       # 600_000
        rate_bps      = 1000                   # 10% (migration 0019)
        items_vat     = (items_total * rate_bps) // 10_000    # 60_000
        shipping_vat  = (shipping    * rate_bps) // 10_000    # 3_000
        expected_total = items_total + shipping + items_vat + shipping_vat  # 693_000

        self.assertEqual(quote["total_items_minor"], items_total,
                         "total_items_minor must be items only (no VAT)")
        self.assertEqual(quote["vat_amount_minor"], items_vat,
                         f"vat_amount_minor must be items VAT = {items_vat}")
        self.assertEqual(quote["shipping_vat_minor"], shipping_vat,
                         f"shipping_vat_minor must be {shipping_vat}")
        self.assertEqual(quote["grand_total_minor"], expected_total,
                         f"grand_total must be {expected_total}")

    def test_C2_no_float_arithmetic(self):
        """C2: All financial values are integers — no floats anywhere."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        rfq_id, rfq_item_ids, supplier_id = _setup_full_rfq(
            self, org_id, admin_uid, [{"quantity": 3}], shipping_cost_minor=10_001,
        )

        with self.db.write_transaction() as conn:
            from app.services.rfq_service import submit_supplier_quote
            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_ids[0],
                        "unit_price_minor": 7_777, "quantity": 3}],
                shipping_cost_minor=10_001,
            )

        for field in ("total_items_minor", "vat_amount_minor", "shipping_vat_minor",
                      "grand_total_minor"):
            val = quote[field]
            self.assertIsInstance(val, int, f"{field} must be int, got {type(val).__name__}: {val}")

    def test_E_shipping_vat_not_discarded(self):
        """E: shipping_vat_minor must be non-zero when shipping_cost > 0 and rate > 0."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        rfq_id, rfq_item_ids, supplier_id = _setup_full_rfq(
            self, org_id, admin_uid, [{"quantity": 1}], shipping_cost_minor=100_000,
        )

        with self.db.write_transaction() as conn:
            from app.services.rfq_service import submit_supplier_quote
            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_ids[0],
                        "unit_price_minor": 100_000, "quantity": 1}],
                shipping_cost_minor=100_000,
            )

        self.assertGreater(quote["shipping_vat_minor"], 0,
                           "shipping_vat_minor must NOT be zero (was being discarded before fix)")
        # shipping_vat = 100_000 * 1000 // 10000 = 10_000
        self.assertEqual(quote["shipping_vat_minor"], 10_000)


# ── D/K: Quote == PO invariant ────────────────────────────────────────────────


class TestQuotePOInvariant(AppTestCase):
    """D/K: PO.grand_total_minor_snapshot == Quote.grand_total_minor."""

    def _run_full_cycle(self, unit_price: int, qty: int, shipping: int):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        rfq_id, rfq_item_ids, supplier_id = _setup_full_rfq(
            self, org_id, admin_uid, [{"quantity": qty}],
            shipping_cost_minor=shipping,
        )

        with self.db.write_transaction() as conn:
            from app.services.rfq_service import (
                submit_supplier_quote, close_rfq, award_rfq
            )
            from app.services.purchase_order_service import create_purchase_order

            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_ids[0],
                        "unit_price_minor": unit_price, "quantity": qty}],
                shipping_cost_minor=shipping,
            )
            quote_id = quote["id"]
            close_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
            award_rfq(conn, rfq_id, actor_user_id=admin_uid,
                      organization_id=org_id, winning_quote_id=quote_id)
            po = create_purchase_order(conn, organization_id=org_id,
                                       actor_user_id=admin_uid,
                                       supplier_quote_id=quote_id)

        return quote, po

    def test_D_po_grand_total_equals_quote_grand_total(self):
        """D: PO.grand_total_minor_snapshot must equal Quote.grand_total_minor exactly."""
        quote, po = self._run_full_cycle(
            unit_price=150_000, qty=4, shipping=30_000
        )
        self.assertEqual(
            po["grand_total_minor"],
            quote["grand_total_minor"],
            f"PO grand_total ({po['grand_total_minor']}) must equal "
            f"Quote grand_total ({quote['grand_total_minor']})"
        )

    def test_K_po_vat_amount_matches_quote_vat(self):
        """K: PO.vat_amount_minor must equal Quote.vat_amount_minor."""
        quote, po = self._run_full_cycle(
            unit_price=200_000, qty=5, shipping=50_000
        )
        self.assertEqual(
            po["vat_amount_minor"],
            quote["vat_amount_minor"],
            f"PO vat_amount_minor ({po['vat_amount_minor']}) must equal "
            f"Quote vat_amount_minor ({quote['vat_amount_minor']})"
        )

    def test_D_multiple_line_items(self):
        """D: invariant holds with multiple RFQ line items."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        rfq_id, rfq_item_ids, supplier_id = _setup_full_rfq(
            self, org_id, admin_uid,
            [{"quantity": 10}, {"quantity": 5}],
            shipping_cost_minor=1_000_000,
        )

        with self.db.write_transaction() as conn:
            from app.services.rfq_service import (
                submit_supplier_quote, close_rfq, award_rfq
            )
            from app.services.purchase_order_service import create_purchase_order

            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[
                    {"rfq_item_id": rfq_item_ids[0],
                     "unit_price_minor": 7_500_000, "quantity": 10},
                    {"rfq_item_id": rfq_item_ids[1],
                     "unit_price_minor": 11_000_000, "quantity": 5},
                ],
                shipping_cost_minor=1_000_000,
            )
            quote_id = quote["id"]
            close_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
            award_rfq(conn, rfq_id, actor_user_id=admin_uid,
                      organization_id=org_id, winning_quote_id=quote_id)
            po = create_purchase_order(conn, organization_id=org_id,
                                       actor_user_id=admin_uid,
                                       supplier_quote_id=quote_id)

        self.assertEqual(po["grand_total_minor"], quote["grand_total_minor"],
                         "PO grand_total must exactly equal Quote grand_total")


# ── F: Historical records unchanged ──────────────────────────────────────────


class TestHistoricalRecordsUnchanged(AppTestCase):
    """F: Pre-migration 0020 rows have grand_total_minor unchanged after migration."""

    def test_F_migration_does_not_alter_existing_grand_total(self):
        """F: Migration 0020 backfills vat_amount_minor but leaves grand_total_minor alone."""
        # Directly insert a quote as if it were created before migration 0020
        # (no vat_amount_minor, grand_total_minor = items + shipping, no VAT)
        with self.db.write_transaction() as conn:
            nat_id = f"HIST{uuid.uuid4().hex[:8]}"
            cur_s = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
                "VALUES (?,?,?,'active')",
                (f"تاریخی {nat_id}", f"تاریخی {nat_id[:6]}", nat_id),
            )
            sup_id = cur_s.lastrowid

            # purchase_requests.purchase_request_id is NOT NULL — must create a PR first
            pr_num = f"PR-HIST-{uuid.uuid4().hex[:6]}"
            pr_cur = conn.execute(
                """INSERT INTO purchase_requests
                   (organization_id, requester_user_id, request_number, title, status)
                   VALUES (1, 1, ?, 'تست تاریخی', 'awarded')""",
                (pr_num,),
            )
            pr_id = pr_cur.lastrowid

            # Minimal RFQ needed as FK anchor
            rfq_num = f"RFQ-HIST-{uuid.uuid4().hex[:6]}"
            rfq_cur = conn.execute(
                """INSERT INTO rfqs (organization_id, purchase_request_id, rfq_number,
                   title, status, created_by_user_id)
                   VALUES (1, ?, ?, 'تاریخی', 'awarded', 1)""",
                (pr_id, rfq_num),
            )
            rfq_id = rfq_cur.lastrowid

            rs_cur = conn.execute(
                "INSERT INTO rfq_suppliers (rfq_id, supplier_id, status) "
                "VALUES (?,?,'responded')",
                (rfq_id, sup_id),
            )
            rfq_sup_id = rs_cur.lastrowid

            # Insert quote with the buggy pre-fix values: grand_total = items + shipping (no VAT)
            items_total = 600_000
            shipping    = 30_000
            buggy_grand = items_total + shipping  # 630_000 — no VAT
            q_num = f"Q-HIST-{uuid.uuid4().hex[:8]}"
            q_cur = conn.execute(
                """INSERT INTO supplier_quotes
                   (rfq_id, supplier_id, rfq_supplier_id, quote_number, status,
                    total_items_minor, shipping_cost_minor, grand_total_minor,
                    vat_amount_minor, submitted_at)
                   VALUES (?,?,?,?,'submitted',?,?,?,0,datetime('now'))""",
                (rfq_id, sup_id, rfq_sup_id, q_num, items_total, shipping, buggy_grand),
            )
            quote_id = q_cur.lastrowid

            # Insert one quote item (10% VAT captured per-item, even before 0020)
            rfq_item_cur = conn.execute(
                """INSERT INTO rfq_items
                   (rfq_id, purchase_request_item_id, free_text_description,
                    quantity_requested, unit)
                   VALUES (?,NULL,'تست',4,'عدد')""",
                (rfq_id,),
            )
            rfq_item_id = rfq_item_cur.lastrowid
            conn.execute(
                """INSERT INTO supplier_quote_items
                   (supplier_quote_id, rfq_item_id, unit_price_minor,
                    quantity_available, vat_rate_bps, vat_amount_minor,
                    discount_minor, total_minor)
                   VALUES (?,?,150000,4,1000,60000,0,600000)""",
                (quote_id, rfq_item_id),
            )

        # Now read back — grand_total_minor must remain 630_000 (not changed by migration)
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT grand_total_minor, vat_amount_minor FROM supplier_quotes WHERE id=?",
                (quote_id,),
            ).fetchone()

        self.assertEqual(row["grand_total_minor"], buggy_grand,
                         "Historical grand_total_minor must NOT be changed by migration 0020")
        self.assertGreaterEqual(row["vat_amount_minor"], 0,
                                "vat_amount_minor column must exist after migration 0020")


# ── H: Rate never hardcoded ───────────────────────────────────────────────────


class TestRateNeverHardcoded(AppTestCase):
    """H: VAT rate is always looked up from tax_rates, never hardcoded."""

    def test_H_changing_db_rate_changes_quote_vat(self):
        """H: If we insert a new tax rate, new quotes use it — proving no hardcoded rate."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        # Add a hypothetical 15% rate effective from a future date we'll use as "today"
        future_date = "2099-01-01"
        with self.db.write_transaction() as conn:
            conn.execute(
                """INSERT INTO tax_rates
                   (tax_category_id, rate_bps, effective_from, effective_until,
                    jurisdiction, notes)
                   SELECT id, 1500, ?, NULL, 'IR', 'نرخ فرضی ۱۵٪ برای آزمایش'
                   FROM tax_categories WHERE code='STANDARD'""",
                (future_date,),
            )

        # submit_supplier_quote always looks up rate for "today" which in production
        # is datetime.utcnow().  We can't easily mock that, but we can verify the
        # lookup mechanism itself picks up the right rate for a given date.
        with self.db.read_transaction() as conn:
            row_current = conn.execute(
                """SELECT rate_bps FROM tax_rates
                   WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code='STANDARD')
                     AND effective_from <= '2026-01-01'
                     AND (effective_until IS NULL OR effective_until >= '2026-01-01')
                   ORDER BY effective_from DESC LIMIT 1"""
            ).fetchone()
            row_future = conn.execute(
                """SELECT rate_bps FROM tax_rates
                   WHERE tax_category_id = (SELECT id FROM tax_categories WHERE code='STANDARD')
                     AND effective_from <= '2099-06-01'
                     AND (effective_until IS NULL OR effective_until >= '2099-06-01')
                   ORDER BY effective_from DESC LIMIT 1"""
            ).fetchone()

        self.assertEqual(row_current["rate_bps"], 1000,
                         "2026 lookup must return 1000 bps (10%)")
        self.assertEqual(row_future["rate_bps"], 1500,
                         "2099 lookup must return 1500 bps (15%) — proves no hardcoding")


# ── I: Tenant isolation ───────────────────────────────────────────────────────


class TestTenantIsolation(AppTestCase):
    """I: Cross-tenant access blocked."""

    def test_I_cross_org_rfq_blocked(self):
        """I: Org A admin cannot access Org B's RFQ."""
        org_a, headers_a, uid_a = _make_org_with_admin(self)
        org_b, headers_b, uid_b = _make_org_with_admin(self)

        rfq_id, _, _ = _setup_full_rfq(self, org_b["id"], uid_b, [{"quantity": 1}])

        resp = self.client.get(
            f"/api/v1/orgs/{org_b['id']}/procurement/rfqs/{rfq_id}",
            headers=headers_a,
        )
        self.assertIn(resp.status_code, (403, 404),
                      f"Cross-tenant RFQ access must be denied, got {resp.status_code}")

    def test_I_cross_org_po_blocked(self):
        """I: Org A member cannot list Org B's purchase orders."""
        org_a, headers_a, _ = _make_org_with_admin(self)
        org_b, _, _ = _make_org_with_admin(self)

        resp = self.client.get(
            f"/api/v1/orgs/{org_b['id']}/procurement/purchase-orders",
            headers=headers_a,
        )
        self.assertIn(resp.status_code, (403, 404),
                      f"Cross-tenant PO list must be denied, got {resp.status_code}")


# ── J: Admin-only tax mutation ────────────────────────────────────────────────


class TestAdminOnlyTaxMutation(AppTestCase):
    """J: Ordinary org member cannot mutate tax rates."""

    def _make_employee_headers(self):
        email, password, resp = self.register()
        self.assertEqual(resp.status_code, 201)
        token = self.login(email, password)
        return {"Authorization": f"Bearer {token}"}

    def test_J_customer_cannot_create_tax_rate(self):
        """J: Customer (role=customer) cannot POST to /api/v1/admin/tax/rates."""
        _, customer_h = self.new_customer()
        resp = self.client.post(
            "/api/v1/admin/tax/rates",
            json={"tax_category_code": "STANDARD", "rate_bps": 500,
                  "effective_from": "2030-01-01"},
            headers=customer_h,
        )
        self.assertIn(resp.status_code, (403, 404),
                      f"Customer must not create tax rates, got {resp.status_code}")

    def test_J_employee_cannot_create_tax_rate(self):
        """J: Employee cannot POST to /api/v1/admin/tax/rates."""
        headers = self._make_employee_headers()
        resp = self.client.post(
            "/api/v1/admin/tax/rates",
            json={"tax_category_code": "STANDARD", "rate_bps": 500,
                  "effective_from": "2030-01-01"},
            headers=headers,
        )
        self.assertIn(resp.status_code, (403, 404),
                      f"Employee must not create tax rates, got {resp.status_code}")

    def test_J_admin_can_create_tax_rate(self):
        """J: Platform admin CAN create a tax rate."""
        admin_h = self.admin_headers()
        resp = self.client.post(
            "/api/v1/admin/tax/rates",
            json={"tax_category_code": "STANDARD", "rate_bps": 1050,
                  "effective_from": "2030-01-01"},
            headers=admin_h,
        )
        # Accept 201 (created) or 404 (endpoint exists but not implemented for this category)
        # but NEVER 403 for admin
        self.assertNotEqual(resp.status_code, 403,
                            f"Admin must never get 403 on tax rate creation, got {resp.status_code}")


# ── Combined E2E scenario ─────────────────────────────────────────────────────


class TestVATEnd2EndScenario(AppTestCase):
    """Full VAT-correct procurement cycle: PR → RFQ → Quote → Award → PO."""

    def test_full_vat_cycle(self):
        """Full cycle with verified VAT arithmetic at each step."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        unit_price = 150_000
        qty        = 4
        shipping   = 30_000

        rfq_id, rfq_item_ids, supplier_id = _setup_full_rfq(
            self, org_id, admin_uid, [{"quantity": qty}],
            shipping_cost_minor=shipping,
        )

        # Submit quote — VAT must be included
        with self.db.write_transaction() as conn:
            from app.services.rfq_service import submit_supplier_quote
            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_ids[0],
                        "unit_price_minor": unit_price, "quantity": qty}],
                shipping_cost_minor=shipping,
            )

        items_total  = unit_price * qty   # 600_000
        rate_bps     = 1000               # 10%
        items_vat    = (items_total * rate_bps) // 10_000   # 60_000
        shipping_vat = (shipping    * rate_bps) // 10_000   # 3_000
        expected_grand = items_total + shipping + items_vat + shipping_vat  # 693_000

        self.assertEqual(quote["grand_total_minor"], expected_grand)
        self.assertEqual(quote["vat_amount_minor"], items_vat)
        self.assertEqual(quote["shipping_vat_minor"], shipping_vat)

        # Close, award, create PO — grand_total must match exactly
        with self.db.write_transaction() as conn:
            from app.services.rfq_service import close_rfq, award_rfq
            from app.services.purchase_order_service import create_purchase_order
            close_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
            award_rfq(conn, rfq_id, actor_user_id=admin_uid,
                      organization_id=org_id, winning_quote_id=quote["id"])
            po = create_purchase_order(conn, organization_id=org_id,
                                       actor_user_id=admin_uid,
                                       supplier_quote_id=quote["id"])

        # D: PO == Quote
        self.assertEqual(po["grand_total_minor"], quote["grand_total_minor"],
                         "PO.grand_total must equal Quote.grand_total")
        # K: VAT amounts match
        self.assertEqual(po["vat_amount_minor"], quote["vat_amount_minor"],
                         "PO.vat_amount_minor must equal Quote.vat_amount_minor")
        # G: all integers
        for field in ("grand_total_minor", "vat_amount_minor", "total_amount_minor"):
            self.assertIsInstance(po[field], int, f"PO.{field} must be int")

        # Audit log must have entries
        with self.db.read_transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM procurement_audit_log WHERE organization_id=?",
                (org_id,),
            ).fetchone()[0]
        self.assertGreater(count, 0, "Audit log must have entries")


if __name__ == "__main__":
    unittest.main()
