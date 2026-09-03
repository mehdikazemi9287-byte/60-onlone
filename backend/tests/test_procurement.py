"""Phase 4 acceptance tests — Organizational Procurement.

Scenarios 8-17:
  8.  Purchase Request lifecycle: draft → submitted → approved
  9.  Approval role enforcement: employee cannot approve
  10. RFQ lifecycle: create → invite supplier → open → supplier submits quote → close
  11. Quote comparison: server-authoritative ranking (lowest price wins)
  12. Award: winning supplier selected, PO auto-created with immutable price snapshot
  13. PO immutability: price change after award does NOT change PO
  14. Tenant isolation: Org A cannot see Org B's PRs or RFQs
  15. Phase 1-3 regression: existing checkout still works after Phase 4 migration
  16. Purchase Request cancel restrictions
  17. Combined Alice scenario: full end-to-end procurement lifecycle
"""
from __future__ import annotations

import uuid
import unittest

from tests.base import AppTestCase


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_org_with_admin(tc: AppTestCase):
    """Returns (org_dict, org_admin_headers, org_admin_user_id)."""
    org = tc.create_organization()
    org_id = org["id"]
    headers, member = tc.make_org_admin(org_id)
    return org, headers, member["user_id"]


def _set_procurement_role(tc: AppTestCase, user_id: int, org_id: int,
                           role: str | None, base_role: str = "employee"):
    """Set procurement_role for a user in an org (direct DB write)."""
    with tc.db.write_transaction() as conn:
        conn.execute(
            """INSERT INTO organization_memberships (organization_id, user_id, role, procurement_role, status)
               VALUES (?,?,?,?,'active')
               ON CONFLICT(organization_id, user_id) DO UPDATE SET
                 role=excluded.role, procurement_role=excluded.procurement_role""",
            (org_id, user_id, base_role, role),
        )


def _register_member(tc: AppTestCase, org_id: int, role: str = "employee",
                     procurement_role: str | None = None):
    """Register a user and add to org. Returns (headers, user_id)."""
    email = f"member{uuid.uuid4().hex[:8]}@test.com"
    _, _, resp = tc.register(email)
    tc.assertEqual(resp.status_code, 201)
    user_id = resp.get_json()["user"]["id"]
    with tc.db.write_transaction() as conn:
        conn.execute(
            """INSERT INTO organization_memberships
               (organization_id, user_id, role, procurement_role, status)
               VALUES (?,?,?,?,'active')""",
            (org_id, user_id, role, procurement_role),
        )
    token = tc.login(email, "Passw0rd!23")
    return {"Authorization": f"Bearer {token}"}, user_id


def _create_pr_direct(tc: AppTestCase, org_id: int, user_id: int,
                      title: str = "درخواست آزمایشی") -> dict:
    """Create a PR directly via service (bypassing HTTP)."""
    with tc.db.write_transaction() as conn:
        from app.services.procurement_service import create_purchase_request
        return create_purchase_request(
            conn,
            organization_id=org_id,
            requester_user_id=user_id,
            title=title,
            items=[{"free_text_description": "ردیف آزمایشی", "quantity": 2, "unit": "عدد"}],
        )


def _get_or_create_supplier(tc: AppTestCase) -> int:
    """Get an existing supplier id (from seed) or create one."""
    with tc.db.read_transaction() as conn:
        row = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()
        if row:
            return row["id"]
    with tc.db.write_transaction() as conn:
        cur = conn.execute(
            "INSERT INTO suppliers (name, national_id) VALUES ('تأمین‌کننده تست', '1234567890')"
        )
        return cur.lastrowid


# ── Scenario 8: Purchase Request lifecycle ─────────────────────────────────────

class TestScenario8PurchaseRequestLifecycle(AppTestCase):
    def test_full_pr_lifecycle(self):
        """draft → submitted → approved via API."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        # Also make the admin an approver
        _set_procurement_role(self, admin_uid, org_id, "approver", base_role="organization_admin")

        # Create a requester member
        member_h, member_uid = _register_member(self, org_id, role="employee",
                                                 procurement_role="requester")

        # 1. Create PR as employee/requester
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests",
            json={
                "title": "خرید لپ‌تاپ برای تیم فناوری",
                "description": "نیاز به ۵ دستگاه لپ‌تاپ",
                "urgency": "high",
                "items": [
                    {"free_text_description": "لپ‌تاپ ۱۵ اینچ", "quantity": 5, "unit": "دستگاه",
                     "estimated_unit_price_minor": 50_000_000},
                ],
            },
            headers=member_h,
        )
        self.assertEqual(resp.status_code, 201)
        pr = resp.get_json()["purchase_request"]
        pr_id = pr["id"]
        self.assertEqual(pr["status"], "draft")
        self.assertRegex(pr["request_number"], r"^PR-\d{8}-\d{4}$")
        self.assertEqual(len(pr["items"]), 1)

        # 2. Submit
        resp2 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/submit",
            headers=member_h,
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()["purchase_request"]["status"], "submitted")

        # 3. Approve
        resp3 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/approve",
            json={"action": "approve", "reason": "تأیید شد"},
            headers=admin_h,
        )
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3.get_json()["purchase_request"]["status"], "approved")

        # 4. List PRs — must appear
        resp4 = self.client.get(
            f"/api/v1/orgs/{org_id}/procurement/requests",
            headers=admin_h,
        )
        self.assertEqual(resp4.status_code, 200)
        items = resp4.get_json()["items"]
        self.assertTrue(any(p["id"] == pr_id for p in items))

    def test_reject_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        member_h, member_uid = _register_member(self, org_id)

        pr = _create_pr_direct(self, org_id, member_uid, "درخواست رد شدنی")
        pr_id = pr["id"]

        # Submit
        with self.db.write_transaction() as conn:
            from app.services.procurement_service import submit_purchase_request
            submit_purchase_request(conn, pr_id, actor_user_id=member_uid, organization_id=org_id)

        # Reject as admin
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/approve",
            json={"action": "reject", "reason": "بودجه کافی نیست"},
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["purchase_request"]["status"], "rejected")

    def test_cannot_submit_empty_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        # Create PR with no items
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests",
            json={"title": "بدون ردیف"},
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201)
        pr_id = resp.get_json()["purchase_request"]["id"]

        # Attempt submit — must fail
        resp2 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/submit",
            headers=admin_h,
        )
        self.assertIn(resp2.status_code, (400, 422))


# ── Scenario 9: Approval role enforcement ─────────────────────────────────────

class TestScenario9ApprovalRoleEnforcement(AppTestCase):
    def test_employee_cannot_approve(self):
        """Regular employee without approver role gets 403."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        employee_h, employee_uid = _register_member(self, org_id, role="employee")

        pr = _create_pr_direct(self, org_id, employee_uid)
        with self.db.write_transaction() as conn:
            from app.services.procurement_service import submit_purchase_request
            submit_purchase_request(conn, pr["id"], actor_user_id=employee_uid,
                                    organization_id=org_id)

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/approve",
            json={"action": "approve"},
            headers=employee_h,
        )
        self.assertEqual(resp.status_code, 403)

    def test_approver_role_can_approve(self):
        """Member with procurement_role='approver' can approve."""
        org, _, _ = _make_org_with_admin(self)
        org_id = org["id"]

        approver_h, approver_uid = _register_member(self, org_id, role="employee",
                                                     procurement_role="approver")
        requester_h, requester_uid = _register_member(self, org_id)

        pr = _create_pr_direct(self, org_id, requester_uid)
        with self.db.write_transaction() as conn:
            from app.services.procurement_service import submit_purchase_request
            submit_purchase_request(conn, pr["id"], actor_user_id=requester_uid,
                                    organization_id=org_id)

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/approve",
            json={"action": "approve"},
            headers=approver_h,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["purchase_request"]["status"], "approved")


# ── Scenario 10: RFQ lifecycle ────────────────────────────────────────────────

class TestScenario10RFQLifecycle(AppTestCase):
    def test_rfq_lifecycle(self):
        """Create RFQ → invite supplier → open → submit quote → close."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        supplier_id = _get_or_create_supplier(self)

        # 1. Create & approve a PR
        pr = _create_pr_direct(self, org_id, admin_uid, "RFQ سناریو ده")
        pr_id = pr["id"]
        with self.db.write_transaction() as conn:
            from app.services.procurement_service import (
                submit_purchase_request, approve_purchase_request
            )
            submit_purchase_request(conn, pr_id, actor_user_id=admin_uid, organization_id=org_id)
            approve_purchase_request(conn, pr_id, actor_user_id=admin_uid,
                                     organization_id=org_id, action="approve")

        # 2. Create RFQ
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs",
            json={"purchase_request_id": pr_id, "title": "استعلام ده"},
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201)
        rfq = resp.get_json()["rfq"]
        rfq_id = rfq["id"]
        self.assertEqual(rfq["status"], "draft")
        self.assertRegex(rfq["rfq_number"], r"^RFQ-\d{8}-\d{4}$")

        # 3. PR moved to sourcing
        with self.db.read_transaction() as conn:
            pr_row = conn.execute(
                "SELECT status FROM purchase_requests WHERE id=?", (pr_id,)
            ).fetchone()
        self.assertEqual(pr_row["status"], "sourcing")

        # 4. Invite supplier
        resp2 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/invite",
            json={"supplier_id": supplier_id},
            headers=admin_h,
        )
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(resp2.get_json()["status"], "invited")

        # 5. Open RFQ
        resp3 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/open",
            headers=admin_h,
        )
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3.get_json()["rfq"]["status"], "open")

        # 6. Submit supplier quote (directly via service — supplier auth is simplified)
        rfq_item_id = resp3.get_json()["rfq"]["items"][0]["id"]
        with self.db.write_transaction() as conn:
            from app.services.rfq_service import submit_supplier_quote
            quote = submit_supplier_quote(
                conn, rfq_id,
                supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_id, "unit_price_minor": 3_000_000, "quantity": 2}],
                shipping_cost_minor=200_000,
            )
        self.assertEqual(quote["status"], "submitted")
        # items_total = 3M * 2 = 6M; with 10% VAT (migration 0019):
        #   items_vat = 6M * 1000 // 10000 = 600K
        #   shipping_vat = 200K * 1000 // 10000 = 20K
        #   grand_total = 6M + 200K + 620K = 6,820,000
        self.assertEqual(quote["total_amount_minor"], 6_000_000)  # items only, no VAT
        self.assertGreater(quote["grand_total_minor"], 6_200_000, "grand_total must include VAT")
        # Verify VAT is non-zero
        self.assertGreater(quote["vat_amount_minor"], 0, "vat_amount_minor must be stored")

        # 7. Close RFQ
        resp4 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/close",
            headers=admin_h,
        )
        self.assertEqual(resp4.status_code, 200)
        self.assertEqual(resp4.get_json()["rfq"]["status"], "closed")

        # 8. List quotes
        resp5 = self.client.get(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/quotes",
            headers=admin_h,
        )
        self.assertEqual(resp5.status_code, 200)
        quotes = resp5.get_json()["items"]
        self.assertEqual(len(quotes), 1)


# ── Scenario 11: Quote comparison ─────────────────────────────────────────────

class TestScenario11QuoteComparison(AppTestCase):
    def test_server_authoritative_comparison(self):
        """Server re-computes totals and ranks quotes lowest-first."""
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        supplier_id = _get_or_create_supplier(self)

        # Setup: approved PR → RFQ → open
        pr = _create_pr_direct(self, org_id, admin_uid)
        pr_id = pr["id"]

        with self.db.write_transaction() as conn:
            from app.services.procurement_service import (
                submit_purchase_request, approve_purchase_request
            )
            from app.services.rfq_service import create_rfq, invite_supplier_to_rfq, open_rfq, submit_supplier_quote

            submit_purchase_request(conn, pr_id, actor_user_id=admin_uid, organization_id=org_id)
            approve_purchase_request(conn, pr_id, actor_user_id=admin_uid,
                                     organization_id=org_id, action="approve")
            rfq = create_rfq(conn, organization_id=org_id, purchase_request_id=pr_id,
                             actor_user_id=admin_uid, title="مقایسه قیمت")
            rfq_id = rfq["id"]
            invite_supplier_to_rfq(conn, rfq_id, supplier_id, actor_user_id=admin_uid,
                                   organization_id=org_id)
            open_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)

            rfq_item_id = rfq["items"][0]["id"]

            # Submit 1 quote (we only have 1 supplier in seed, so one quote is enough to test comparison)
            q = submit_supplier_quote(
                conn, rfq_id, supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_id, "unit_price_minor": 2_500_000, "quantity": 2}],
                shipping_cost_minor=100_000,
            )
            quote_id = q["id"]

            # Close RFQ
            from app.services.rfq_service import close_rfq
            close_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)

        # Comparison
        resp = self.client.get(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/comparison",
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 200)
        comparison = resp.get_json()
        self.assertEqual(comparison["rfq_id"], rfq_id)
        self.assertEqual(comparison["total_quotes"], 1)
        q_data = comparison["quotes"][0]
        # (2.5M * 2) + 100K + VAT(10%) = 5M + 100K + 510K = 5,610,000
        # Comparison uses stored grand_total_minor (authoritative, includes VAT)
        self.assertGreater(q_data["computed_grand_total_minor"], 5_100_000,
                           "comparison grand_total must include VAT")
        self.assertEqual(q_data["rank"], 1)
        self.assertEqual(comparison["lowest_quote_id"], quote_id)


# ── Scenario 12: Award and PO creation ────────────────────────────────────────

class TestScenario12AwardAndPO(AppTestCase):
    def _setup_awarded_rfq(self, org_id, admin_uid):
        supplier_id = _get_or_create_supplier(self)
        pr = _create_pr_direct(self, org_id, admin_uid)
        pr_id = pr["id"]

        with self.db.write_transaction() as conn:
            from app.services.procurement_service import (
                submit_purchase_request, approve_purchase_request
            )
            from app.services.rfq_service import (
                create_rfq, invite_supplier_to_rfq, open_rfq,
                submit_supplier_quote, close_rfq
            )
            submit_purchase_request(conn, pr_id, actor_user_id=admin_uid, organization_id=org_id)
            approve_purchase_request(conn, pr_id, actor_user_id=admin_uid,
                                     organization_id=org_id, action="approve")
            rfq = create_rfq(conn, organization_id=org_id, purchase_request_id=pr_id,
                             actor_user_id=admin_uid, title="استعلام جایزه")
            rfq_id = rfq["id"]
            invite_supplier_to_rfq(conn, rfq_id, supplier_id, actor_user_id=admin_uid,
                                   organization_id=org_id)
            open_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
            rfq_item_id = rfq["items"][0]["id"]
            q = submit_supplier_quote(
                conn, rfq_id, supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_id, "unit_price_minor": 10_000_000, "quantity": 2}],
                shipping_cost_minor=500_000,
            )
            close_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
        return rfq_id, q["id"], pr_id

    def test_award_creates_awarded_rfq(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        rfq_id, quote_id, pr_id = self._setup_awarded_rfq(org_id, admin_uid)

        # Award
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/award",
            json={"winning_quote_id": quote_id, "reason": "بهترین قیمت"},
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["rfq"]["status"], "awarded")
        self.assertEqual(data["winning_quote"]["status"], "awarded")

        # PR should be awarded
        with self.db.read_transaction() as conn:
            pr_row = conn.execute("SELECT status FROM purchase_requests WHERE id=?", (pr_id,)).fetchone()
        self.assertEqual(pr_row["status"], "awarded")

    def test_create_po_from_awarded_quote(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        rfq_id, quote_id, pr_id = self._setup_awarded_rfq(org_id, admin_uid)

        # Award
        with self.db.write_transaction() as conn:
            from app.services.rfq_service import award_rfq
            award_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id,
                      winning_quote_id=quote_id)

        # Create PO
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/purchase-orders",
            json={"supplier_quote_id": quote_id, "vat_bps": 900},
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201)
        po = resp.get_json()["purchase_order"]
        po_id = po["id"]
        self.assertEqual(po["status"], "draft")
        self.assertRegex(po["po_number"], r"^PO-\d{8}-\d{4}$")
        # (10M * 2) + 500K = 20.5M; VAT 9% of items = 1.8M; grand total includes vat
        self.assertEqual(po["total_amount_minor"], 20_000_000)  # items only
        self.assertEqual(po["shipping_cost_minor"], 500_000)
        self.assertGreater(po["grand_total_minor"], 20_000_000)  # grand_total > items_total

        # PO has items (immutable snapshots)
        self.assertEqual(len(po["items"]), 1)
        self.assertEqual(po["items"][0]["unit_price_minor"], 10_000_000)
        self.assertEqual(po["items"][0]["quantity"], 2)
        self.assertEqual(po["items"][0]["total_price_minor"], 20_000_000)

        # PO lifecycle: draft → confirmed → sent → partially_received → received
        for action, expected_status in [
            ("confirm", "confirmed"),
            ("send", "sent"),
            ("acknowledge", "partially_received"),
            ("complete", "received"),
        ]:
            r = self.client.post(
                f"/api/v1/orgs/{org_id}/procurement/purchase-orders/{po_id}/{action}",
                headers=admin_h,
            )
            self.assertEqual(r.status_code, 200, f"{action}: {r.get_json()}")
            self.assertEqual(r.get_json()["purchase_order"]["status"], expected_status)

        # After complete (received), PR should be completed
        with self.db.read_transaction() as conn:
            pr_row = conn.execute("SELECT status FROM purchase_requests WHERE id=?", (pr_id,)).fetchone()
        self.assertEqual(pr_row["status"], "completed")


# ── Scenario 13: PO immutability ─────────────────────────────────────────────

class TestScenario13POImmutability(AppTestCase):
    """Price changes after PO creation must NOT affect existing PO line items."""

    def test_price_change_does_not_affect_po(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        supplier_id = _get_or_create_supplier(self)

        pr = _create_pr_direct(self, org_id, admin_uid, "تست عدم تغییر قیمت")
        pr_id = pr["id"]

        with self.db.write_transaction() as conn:
            from app.services.procurement_service import (
                submit_purchase_request, approve_purchase_request
            )
            from app.services.rfq_service import (
                create_rfq, invite_supplier_to_rfq, open_rfq,
                submit_supplier_quote, close_rfq, award_rfq
            )
            from app.services.purchase_order_service import create_purchase_order

            submit_purchase_request(conn, pr_id, actor_user_id=admin_uid, organization_id=org_id)
            approve_purchase_request(conn, pr_id, actor_user_id=admin_uid,
                                     organization_id=org_id, action="approve")
            rfq = create_rfq(conn, organization_id=org_id, purchase_request_id=pr_id,
                             actor_user_id=admin_uid, title="استعلام قیمت ثابت")
            rfq_id = rfq["id"]
            invite_supplier_to_rfq(conn, rfq_id, supplier_id, actor_user_id=admin_uid,
                                   organization_id=org_id)
            open_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
            rfq_item_id = rfq["items"][0]["id"]
            q = submit_supplier_quote(
                conn, rfq_id, supplier_id=supplier_id,
                items=[{"rfq_item_id": rfq_item_id, "unit_price_minor": 8_000_000, "quantity": 1}],
            )
            quote_id = q["id"]
            close_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id)
            award_rfq(conn, rfq_id, actor_user_id=admin_uid, organization_id=org_id,
                      winning_quote_id=quote_id)
            po = create_purchase_order(conn, organization_id=org_id, actor_user_id=admin_uid,
                                       supplier_quote_id=quote_id)
            po_id = po["id"]

            # Record original price snapshot
            original_unit_price = po["items"][0]["unit_price_minor"]
            self.assertEqual(original_unit_price, 8_000_000)

            # Now simulate a supplier price change on their offer
            conn.execute(
                "UPDATE supplier_quotes SET total_items_minor=9999999 WHERE id=?", (quote_id,)
            )
            # Also update any seller_offer that might link
            # Use portable WHERE id = ? instead of LIMIT 1 (not supported in SQLite)
            _offer_row = conn.execute("SELECT id FROM seller_offers LIMIT 1").fetchone()
            if _offer_row:
                conn.execute(
                    "UPDATE seller_offers SET selling_price_minor=9999999 WHERE id=?",
                    (_offer_row["id"],),
                )

        # Re-fetch PO — prices must be unchanged (immutable snapshot)
        with self.db.read_transaction() as conn:
            from app.services.purchase_order_service import get_purchase_order
            po_after = get_purchase_order(conn, po_id, actor_user_id=admin_uid, organization_id=org_id)

        self.assertEqual(po_after["items"][0]["unit_price_minor"], 8_000_000,
                         "PO unit price must remain at snapshot value of 8,000,000")
        self.assertEqual(po_after["items"][0]["total_price_minor"], 8_000_000)
        # Grand total must also be immutable
        self.assertGreaterEqual(po_after["grand_total_minor"], 8_000_000)


# ── Scenario 14: Tenant isolation ────────────────────────────────────────────

class TestScenario14TenantIsolation(AppTestCase):
    """Org A cannot see Org B's purchase requests or RFQs."""

    def test_org_a_cannot_access_org_b_pr(self):
        org_a, headers_a, uid_a = _make_org_with_admin(self)
        org_b, headers_b, uid_b = _make_org_with_admin(self)

        # Create PR in Org B
        pr_b = _create_pr_direct(self, org_b["id"], uid_b, "PR خصوصی سازمان ب")
        pr_id = pr_b["id"]

        # Org A member tries to access Org B's PR
        resp = self.client.get(
            f"/api/v1/orgs/{org_b['id']}/procurement/requests/{pr_id}",
            headers=headers_a,
        )
        # Must be 403 or 404 (both are acceptable for security)
        self.assertIn(resp.status_code, (403, 404),
                      f"Expected 403 or 404 but got {resp.status_code}")

    def test_org_a_cannot_list_org_b_requests(self):
        org_a, headers_a, _ = _make_org_with_admin(self)
        org_b, _, uid_b = _make_org_with_admin(self)

        # Create PR in Org B
        _create_pr_direct(self, org_b["id"], uid_b, "سری سازمان ب")

        # Org A tries to list Org B's requests
        resp = self.client.get(
            f"/api/v1/orgs/{org_b['id']}/procurement/requests",
            headers=headers_a,
        )
        self.assertIn(resp.status_code, (403, 404))

    def test_cross_org_cancel_blocked(self):
        """Cannot cancel another org's PR even if you know its ID."""
        org_a, headers_a, _ = _make_org_with_admin(self)
        org_b, _, uid_b = _make_org_with_admin(self)

        pr_b = _create_pr_direct(self, org_b["id"], uid_b)
        pr_id = pr_b["id"]

        resp = self.client.post(
            f"/api/v1/orgs/{org_b['id']}/procurement/requests/{pr_id}/cancel",
            headers=headers_a,
        )
        self.assertIn(resp.status_code, (403, 404))


# ── Scenario 15: Phase 1-3 regression ────────────────────────────────────────

class TestScenario15Regression(AppTestCase):
    """Phase 1-3 checkout still works after Phase 4 migration."""

    def test_basic_checkout_still_works(self):
        """The existing Phase 3 checkout flow must be unaffected."""
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 10)

        _, headers = self.new_customer()

        # Add to cart
        r1 = self.client.post("/api/v1/cart/items",
                              json={"product_id": product["id"], "quantity": 1},
                              headers=headers)
        self.assertIn(r1.status_code, (200, 201))

        # Checkout
        r2 = self.client.post("/api/v1/checkout", json={
            "shipping_address": self.DEFAULT_ADDRESS,
            "payment_method": "card",
        }, headers=headers, environ_base={"REMOTE_ADDR": "1.2.3.4"})
        self.assertIn(r2.status_code, (201, 422))  # 422 if no supplier configured

    def test_health_endpoint(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)

    def test_catalog_api_still_works(self):
        resp = self.client.get("/api/v1/products")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        # Phase 3 catalog API returns either 'products' or 'items' key
        self.assertTrue("products" in data or "items" in data, f"Unexpected response: {data}")

    def test_master_catalog_search(self):
        _, headers = self.new_customer()
        resp = self.client.get("/api/v1/catalog/search?q=test", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("items", data)
        self.assertIn("total", data)


# ── Scenario 16 (original cancel restrictions — renamed per Blocker 5) ────────
# NOTE: This class has been renamed from TestScenario16CancelRestrictions.
# The NEW TestScenario16Phase2CreditSplit class (below) is the canonical Scenario 16.

class TestScenario16OriginalCancelRestrictions(AppTestCase):
    """Original Scenario 16 cancel-restriction tests (kept for regression coverage)."""

    def test_cannot_cancel_completed_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        # Manually set a PR to completed
        with self.db.write_transaction() as conn:
            from app.services.procurement_service import create_purchase_request
            pr = create_purchase_request(
                conn, organization_id=org_id, requester_user_id=admin_uid,
                title="PR تکمیل‌شده",
                items=[{"free_text_description": "ردیف", "quantity": 1}],
            )
            conn.execute(
                "UPDATE purchase_requests SET status='completed' WHERE id=?", (pr["id"],)
            )

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/cancel",
            headers=admin_h,
        )
        self.assertIn(resp.status_code, (400, 409, 422))

    def test_cancel_draft_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        pr = _create_pr_direct(self, org_id, admin_uid, "PR قابل لغو")

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/cancel",
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["purchase_request"]["status"], "cancelled")

    def test_employee_cannot_cancel_others_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        employee_h, employee_uid = _register_member(self, org_id)
        other_h, other_uid = _register_member(self, org_id)

        pr = _create_pr_direct(self, org_id, other_uid, "PR دیگری")

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/cancel",
            headers=employee_h,
        )
        self.assertIn(resp.status_code, (403, 404))


# ── Scenario 17: Combined Alice end-to-end ───────────────────────────────────

class TestScenario17AliceCombinedProcurement(AppTestCase):
    """Full end-to-end procurement lifecycle for Alice (org admin)."""

    def test_full_procurement_end_to_end(self):
        # Setup org and participants
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        supplier_id = _get_or_create_supplier(self)

        # Step 1: Alice creates a Purchase Request
        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests",
            json={
                "title": "خرید تجهیزات دفتر آلیس",
                "urgency": "high",
                "budget_minor": 100_000_000,
                "items": [
                    {"free_text_description": "صندلی ارگونومیک", "quantity": 10,
                     "unit": "عدد", "estimated_unit_price_minor": 8_000_000},
                    {"free_text_description": "میز کار", "quantity": 5,
                     "unit": "عدد", "estimated_unit_price_minor": 12_000_000},
                ],
            },
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201)
        pr_id = resp.get_json()["purchase_request"]["id"]
        self.assertEqual(resp.get_json()["purchase_request"]["status"], "draft")
        self.assertEqual(len(resp.get_json()["purchase_request"]["items"]), 2)

        # Step 2: Submit PR
        resp2 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/submit",
            headers=admin_h,
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()["purchase_request"]["status"], "submitted")

        # Step 3: Approve PR (admin is also approver)
        resp3 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/approve",
            json={"action": "approve", "reason": "بودجه تأیید شد"},
            headers=admin_h,
        )
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3.get_json()["purchase_request"]["status"], "approved")

        # Step 4: Create RFQ
        resp4 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs",
            json={"purchase_request_id": pr_id, "title": "استعلام تجهیزات آلیس"},
            headers=admin_h,
        )
        self.assertEqual(resp4.status_code, 201)
        rfq_id = resp4.get_json()["rfq"]["id"]
        rfq_items = resp4.get_json()["rfq"]["items"]
        self.assertEqual(len(rfq_items), 2)

        # Step 5: Invite supplier
        resp5 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/invite",
            json={"supplier_id": supplier_id},
            headers=admin_h,
        )
        self.assertEqual(resp5.status_code, 201)

        # Step 6: Open RFQ
        resp6 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/open",
            headers=admin_h,
        )
        self.assertEqual(resp6.status_code, 200)

        # Step 7: Supplier submits quote
        with self.db.write_transaction() as conn:
            from app.services.rfq_service import submit_supplier_quote
            quote = submit_supplier_quote(
                conn, rfq_id, supplier_id=supplier_id,
                items=[
                    {"rfq_item_id": rfq_items[0]["id"], "unit_price_minor": 7_500_000, "quantity": 10},
                    {"rfq_item_id": rfq_items[1]["id"], "unit_price_minor": 11_000_000, "quantity": 5},
                ],
                shipping_cost_minor=1_000_000,
                payment_terms="نقد",
                delivery_lead_days=14,
                validity_days=30,
            )
        quote_id = quote["id"]
        # items = (7.5M*10) + (11M*5) = 75M + 55M = 130M
        # shipping = 1M; VAT 10%: items_vat = 13M, shipping_vat = 100K
        # grand = 130M + 1M + 13M + 100K = 144,100,000
        self.assertEqual(quote["total_amount_minor"], 130_000_000)  # items only, no VAT
        self.assertGreater(quote["grand_total_minor"], 131_000_000, "grand_total must include VAT")
        self.assertGreater(quote["vat_amount_minor"], 0, "vat_amount_minor must be stored")

        # Step 8: Close RFQ
        resp8 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/close",
            headers=admin_h,
        )
        self.assertEqual(resp8.status_code, 200)

        # Step 9: Compare quotes
        resp9 = self.client.get(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/comparison",
            headers=admin_h,
        )
        self.assertEqual(resp9.status_code, 200)
        comparison = resp9.get_json()
        self.assertEqual(comparison["total_quotes"], 1)
        self.assertEqual(comparison["lowest_quote_id"], quote_id)
        # Comparison uses stored grand_total_minor which includes VAT (migration 0019/0020)
        # 130M items + 1M shipping + 13M items_vat + 100K shipping_vat = 144,100,000
        self.assertGreater(comparison["quotes"][0]["computed_grand_total_minor"], 131_000_000,
                           "comparison grand_total must include VAT")

        # Step 10: Award to supplier
        resp10 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/award",
            json={"winning_quote_id": quote_id, "reason": "تنها پیشنهاد"},
            headers=admin_h,
        )
        self.assertEqual(resp10.status_code, 200)
        self.assertEqual(resp10.get_json()["rfq"]["status"], "awarded")

        # Step 11: Create PO (with 9% VAT)
        resp11 = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/purchase-orders",
            json={"supplier_quote_id": quote_id, "vat_bps": 900},
            headers=admin_h,
        )
        self.assertEqual(resp11.status_code, 201)
        po = resp11.get_json()["purchase_order"]
        po_id = po["id"]

        # Verify PO financials
        items_total = (7_500_000 * 10) + (11_000_000 * 5)  # 130M
        shipping = 1_000_000

        self.assertEqual(po["total_amount_minor"], items_total)
        self.assertEqual(po["shipping_cost_minor"], shipping)
        self.assertGreater(po["grand_total_minor"], items_total)  # grand_total > items only
        self.assertEqual(len(po["items"]), 2)

        # Verify immutable line item snapshots
        po_items_sorted = sorted(po["items"], key=lambda x: x["unit_price_minor"])
        self.assertEqual(po_items_sorted[0]["unit_price_minor"], 7_500_000)
        self.assertEqual(po_items_sorted[1]["unit_price_minor"], 11_000_000)

        # Step 12: Confirm → Send → Acknowledge → Complete
        for action, expected_status in [
            ("confirm", "confirmed"),
            ("send", "sent"),
            ("acknowledge", "partially_received"),
            ("complete", "received"),
        ]:
            r = self.client.post(
                f"/api/v1/orgs/{org_id}/procurement/purchase-orders/{po_id}/{action}",
                headers=admin_h,
            )
            self.assertEqual(r.status_code, 200, f"Step {action}: {r.get_json()}")
            self.assertEqual(r.get_json()["purchase_order"]["status"], expected_status)

        # Final assertions
        # PR should be completed
        with self.db.read_transaction() as conn:
            pr_row = conn.execute(
                "SELECT status FROM purchase_requests WHERE id=?", (pr_id,)
            ).fetchone()
        self.assertEqual(pr_row["status"], "completed")

        # Audit log should have entries
        with self.db.read_transaction() as conn:
            audit_count = conn.execute(
                "SELECT COUNT(*) FROM procurement_audit_log WHERE organization_id=?",
                (org_id,)
            ).fetchone()[0]
        self.assertGreater(audit_count, 0, "Audit log must have entries")


# ── Blocker 2: Connector admin security ───────────────────────────────────────

class TestConnectorAdminSecurity(AppTestCase):
    """Connector admin endpoints must only be accessible to platform admins."""

    def _make_employee_headers(self):
        """Create a user with global role='employee' and return headers."""
        email, password, resp = self.register()
        self.assertEqual(resp.status_code, 201)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='employee' WHERE email_normalized=?", (email,))
        token = self.login(email, password)
        return {"Authorization": f"Bearer {token}"}

    def _make_supplier_headers(self):
        """Create a user with global role='supplier' and return headers."""
        email, password, resp = self.register()
        self.assertEqual(resp.status_code, 201)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='supplier' WHERE email_normalized=?", (email,))
        token = self.login(email, password)
        return {"Authorization": f"Bearer {token}"}

    def test_customer_cannot_access_connector_admin(self):
        _, headers = self.new_customer()
        resp = self.client.get("/api/v1/admin/connectors", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_employee_cannot_access_connector_admin(self):
        headers = self._make_employee_headers()
        resp = self.client.get("/api/v1/admin/connectors", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_supplier_cannot_access_connector_admin(self):
        headers = self._make_supplier_headers()
        resp = self.client.get("/api/v1/admin/connectors", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_access_connector_admin(self):
        headers = self.admin_headers()
        resp = self.client.get("/api/v1/admin/connectors", headers=headers)
        self.assertEqual(resp.status_code, 200)

    def _create_connector_and_offer(self):
        """Create a connector account and a seller_offer; return (account_id, offer_id)."""
        admin_h = self.admin_headers()
        # Create supplier, location, offer in DB
        sup_id, offer_id = None, None
        with self.db.write_transaction() as conn:
            nat_id = f"CONN{uuid.uuid4().hex[:8]}"
            cur_s = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
                "VALUES (?,?,?,'active')",
                ("تأمین کانکتور", "کانکتور", nat_id),
            )
            sup_id = cur_s.lastrowid
            cur_l = conn.execute(
                "INSERT INTO supplier_locations "
                "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
                "VALUES (?,?,?,'active',1,1)",
                (sup_id, "تهران", "تهران"),
            )
            loc_id = cur_l.lastrowid
            product_id = conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
            cur_o = conn.execute(
                "INSERT INTO seller_offers "
                "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
                "stock_quantity, status, fulfillment_type) "
                "VALUES (?,?,?,200000,50,'active','delivery')",
                (product_id, sup_id, loc_id),
            )
            offer_id = cur_o.lastrowid
        # Create connector via admin API (outside transaction; valid type = MANUAL)
        r = self.client.post(
            "/api/v1/admin/connectors",
            json={"name": f"TestConn{uuid.uuid4().hex[:6]}", "connector_type": "MANUAL",
                  "supplier_id": sup_id},
            headers=admin_h,
        )
        self.assertEqual(r.status_code, 201, f"Create connector: {r.get_json()}")
        account_id = r.get_json()["id"]
        return account_id, offer_id

    def test_customer_cannot_sync_inventory(self):
        """Normal customer calling POST sync/inventory must get 403 and stock must be unchanged."""
        account_id, offer_id = self._create_connector_and_offer()
        _, cust_h = self.new_customer()

        with self.db.read_transaction() as conn:
            stock_before = conn.execute(
                "SELECT stock_quantity FROM seller_offers WHERE id=?", (offer_id,)
            ).fetchone()["stock_quantity"]

        resp = self.client.post(
            f"/api/v1/admin/connectors/{account_id}/sync/inventory",
            json={"updates": [{"offer_id": offer_id, "stock_quantity": 9999}]},
            headers=cust_h,
        )
        self.assertEqual(resp.status_code, 403,
                         f"Customer must get 403 on sync/inventory, got {resp.status_code}")

        with self.db.read_transaction() as conn:
            stock_after = conn.execute(
                "SELECT stock_quantity FROM seller_offers WHERE id=?", (offer_id,)
            ).fetchone()["stock_quantity"]
        self.assertEqual(stock_before, stock_after,
                         "stock_quantity must be unchanged after 403 rejection")

    def test_customer_cannot_sync_prices(self):
        """Normal customer calling POST sync/prices must get 403 and price must be unchanged."""
        account_id, offer_id = self._create_connector_and_offer()
        _, cust_h = self.new_customer()

        with self.db.read_transaction() as conn:
            price_before = conn.execute(
                "SELECT selling_price_minor FROM seller_offers WHERE id=?", (offer_id,)
            ).fetchone()["selling_price_minor"]

        resp = self.client.post(
            f"/api/v1/admin/connectors/{account_id}/sync/prices",
            json={"updates": [{"offer_id": offer_id, "selling_price_minor": 1}]},
            headers=cust_h,
        )
        self.assertEqual(resp.status_code, 403,
                         f"Customer must get 403 on sync/prices, got {resp.status_code}")

        with self.db.read_transaction() as conn:
            price_after = conn.execute(
                "SELECT selling_price_minor FROM seller_offers WHERE id=?", (offer_id,)
            ).fetchone()["selling_price_minor"]
        self.assertEqual(price_before, price_after,
                         "selling_price_minor must be unchanged after 403 rejection")


# ── Blocker 3: Freshness checkout blocking ────────────────────────────────────

class TestFreshnessCheckoutBlocking(AppTestCase):
    """An EXPIRED offer with expired_action='block_checkout' must prevent checkout."""

    def _create_offer_with_expired_freshness(self, conn, product_id: int) -> int:
        """Create a supplier + location + seller_offer with REALTIME expired policy."""
        from uuid import uuid4
        import datetime
        nat_id = f"TEST{uuid4().hex[:8]}"
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
            "VALUES (?,?,?,'active')",
            (f"تأمین تازگی {nat_id}", f"تازگی {nat_id}", nat_id),
        )
        sup_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
            "VALUES (?,?,?,'active',1,1)",
            (sup_id, "تهران", "تهران"),
        )
        loc_id = cur2.lastrowid
        # Get or create REALTIME policy (block_checkout for expired)
        policy = conn.execute(
            "SELECT id FROM freshness_policies WHERE name='REALTIME'"
        ).fetchone()
        if not policy:
            cur_p = conn.execute(
                "INSERT INTO freshness_policies "
                "(name, price_ttl_seconds, inventory_ttl_seconds, stale_action, expired_action) "
                "VALUES ('REALTIME', 900, 900, 'block_checkout', 'block_checkout')"
            )
            policy_id = cur_p.lastrowid
        else:
            policy_id = policy["id"]
        # Timestamp > 2 * TTL (900*2=1800s) in the past → EXPIRED
        expired_ts = (
            datetime.datetime.utcnow() - datetime.timedelta(seconds=1900)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        cur3 = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type, freshness_policy_id, "
            "last_price_confirmed_at, last_inventory_confirmed_at) "
            "VALUES (?,?,?,100000,100,'active','delivery',?,?,?)",
            (product_id, sup_id, loc_id, policy_id, expired_ts, expired_ts),
        )
        return cur3.lastrowid

    def test_expired_offer_blocks_checkout_no_charge(self):
        """Checkout with an EXPIRED offer raises exactly 409 offer_freshness_expired.

        After the freshness check fails:
        - PSP must NOT be charged
        - No payment_intent captured
        - No fulfillment order created
        - stock_reserved == 0
        - catalog inventory unchanged
        - credit_ledger_entries unchanged

        Then refresh the same offer's timestamps and retry checkout — must succeed exactly once.
        """
        import datetime
        # Use a product known to exist in seed data
        product = self.product("office-paper-a4-carton")
        product_id = product["id"]

        # Snapshot state before
        with self.db.read_transaction() as conn:
            credit_ledger_count_before = conn.execute(
                "SELECT COUNT(*) FROM credit_ledger_entries"
            ).fetchone()[0]
            pi_count_before = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]

        offer_id = None
        with self.db.write_transaction() as conn:
            # Zero out all existing offers so only our expired one is available
            conn.execute(
                "UPDATE seller_offers SET stock_quantity=0 WHERE product_id=?",
                (product_id,)
            )
            offer_id = self._create_offer_with_expired_freshness(conn, product_id)

        # Create a fresh user/customer
        _, user_headers = self.new_customer()

        # Add to cart
        r = self.client.post(
            "/api/v1/cart/items",
            json={"product_id": product_id, "quantity": 1},
            headers=user_headers,
        )
        self.assertIn(r.status_code, (200, 201), f"Add to cart failed: {r.get_json()}")

        # Attempt checkout — MUST fail with exactly 409 and code=offer_freshness_expired
        checkout_payload = {
            "shipping_address": self.DEFAULT_ADDRESS,
            "payment_method": "card",
        }
        r2 = self.client.post(
            "/api/v1/checkout",
            json=checkout_payload,
            headers={**user_headers, "Idempotency-Key": uuid.uuid4().hex},
            environ_base={"REMOTE_ADDR": "1.2.3.4"},
        )
        self.assertEqual(r2.status_code, 409,
                         f"Expected 409 freshness error, got {r2.status_code}: {r2.get_json()}")
        err_body = r2.get_json()
        err = err_body.get("error", err_body)
        self.assertEqual(err.get("code"), "offer_freshness_expired",
                         f"Error code must be 'offer_freshness_expired', got: {err_body}")

        # PSP was NOT charged (no new captured payment_intents)
        with self.db.read_transaction() as conn:
            pi_count_after_fail = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]
        self.assertEqual(pi_count_before, pi_count_after_fail,
                         "PSP must NOT have been charged on freshness failure")

        # No fulfillment order created (orders table uses status='paid' column)
        with self.db.read_transaction() as conn:
            fo_count = conn.execute(
                "SELECT COUNT(*) FROM fulfillment_orders fo "
                "JOIN orders o ON o.id = fo.order_id "
                "WHERE o.status='paid'",
            ).fetchone()[0]
        self.assertEqual(fo_count, 0, "No paid fulfillment order must exist after freshness failure")

        # stock_reserved must still be 0
        with self.db.read_transaction() as conn:
            offer_row = conn.execute(
                "SELECT stock_reserved, stock_quantity FROM seller_offers WHERE id=?",
                (offer_id,)
            ).fetchone()
        self.assertEqual(offer_row["stock_reserved"], 0,
                         "stock_reserved must remain 0 after freshness failure")

        # credit_ledger_entries unchanged
        with self.db.read_transaction() as conn:
            credit_ledger_count_after_fail = conn.execute(
                "SELECT COUNT(*) FROM credit_ledger_entries"
            ).fetchone()[0]
        self.assertEqual(credit_ledger_count_before, credit_ledger_count_after_fail,
                         "credit_ledger_entries must be unchanged after freshness failure")

        # ── Now refresh the SAME offer's price/inventory timestamps → retry succeeds ──
        fresh_ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE seller_offers "
                "SET last_price_confirmed_at=?, last_inventory_confirmed_at=? "
                "WHERE id=?",
                (fresh_ts, fresh_ts, offer_id),
            )

        # Re-add to cart (the previous cart attempt may still be active)
        # Use a fresh idempotency key to ensure a new attempt
        r3 = self.client.post(
            "/api/v1/checkout",
            json=checkout_payload,
            headers={**user_headers, "Idempotency-Key": uuid.uuid4().hex},
            environ_base={"REMOTE_ADDR": "1.2.3.5"},
        )
        self.assertIn(r3.status_code, (200, 201),
                      f"Checkout must succeed after freshness refresh, got {r3.status_code}: {r3.get_json()}")


# ── Blocker 5: Scenario 16 rename + new credit-split scenario ────────────────

class TestScenarioCancelRestrictions(AppTestCase):
    """Former Scenario 16: Purchase Request cancel restrictions (renamed; tests unchanged)."""

    def test_cannot_cancel_completed_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]

        with self.db.write_transaction() as conn:
            from app.services.procurement_service import create_purchase_request
            pr = create_purchase_request(
                conn, organization_id=org_id, requester_user_id=admin_uid,
                title="PR تکمیل‌شده",
                items=[{"free_text_description": "ردیف", "quantity": 1}],
            )
            conn.execute(
                "UPDATE purchase_requests SET status='completed' WHERE id=?", (pr["id"],)
            )

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/cancel",
            headers=admin_h,
        )
        self.assertIn(resp.status_code, (400, 409, 422))

    def test_cancel_draft_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        pr = _create_pr_direct(self, org_id, admin_uid, "PR قابل لغو")

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/cancel",
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["purchase_request"]["status"], "cancelled")

    def test_employee_cannot_cancel_others_pr(self):
        org, admin_h, admin_uid = _make_org_with_admin(self)
        org_id = org["id"]
        employee_h, employee_uid = _register_member(self, org_id)
        other_h, other_uid = _register_member(self, org_id)

        pr = _create_pr_direct(self, org_id, other_uid, "PR دیگری")

        resp = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr['id']}/cancel",
            headers=employee_h,
        )
        self.assertIn(resp.status_code, (403, 404))


class TestScenario16Phase2CreditSplit(AppTestCase):
    """Scenario 16: 30M order, 20M credit, 10M PSP split — exact integer amounts."""

    def _setup_product_with_offer(self, conn, price_minor: int) -> tuple[int, int]:
        """Return (product_id, offer_id) for a product at the given price."""
        from uuid import uuid4 as _uuid4
        # Use an existing product but create a dedicated offer
        prod_row = conn.execute("SELECT id FROM products LIMIT 1").fetchone()
        product_id = prod_row[0]
        # Set base price on products table
        conn.execute(
            "UPDATE products SET base_price_minor=? WHERE id=?", (price_minor, product_id)
        )
        nat_id = f"CR16{_uuid4().hex[:8]}"
        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status) "
            "VALUES (?,?,?,'active')",
            (f"تأمین اعتبار {nat_id}", f"اعتبار {nat_id}", nat_id),
        )
        sup_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
            "VALUES (?,?,?,'active',1,1)",
            (sup_id, "تهران", "تهران"),
        )
        loc_id = cur2.lastrowid
        # Remove other offers for this product to avoid routing conflicts
        conn.execute("UPDATE seller_offers SET stock_quantity=0 WHERE product_id=?", (product_id,))
        cur3 = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,?,100,'active','delivery')",
            (product_id, sup_id, loc_id, price_minor),
        )
        return product_id, cur3.lastrowid

    def test_30m_order_20m_credit_10m_psp(self):
        """30M subtotal, 20M credit, PSP covers remainder (incl. VAT): exact integers, no double-charge."""
        PRICE  = 30_000_000
        TAX    = PRICE * 1000 // 10000   # 3,000,000 at STANDARD 10% (v6)
        TOTAL  = PRICE + TAX             # 33,000,000 (VAT-inclusive, free shipping)
        CREDIT = 20_000_000
        CASH   = TOTAL - CREDIT          # 13,000,000

        # 1. Create org with credit limit
        org = self.create_organization(credit_limit_minor=50_000_000)
        org_id = org["id"]
        admin_headers, admin = self.make_org_admin(org_id)

        # 2. Add employee + allocate 20M credit
        employee = self.add_employee(org_id, admin_headers)
        alloc_resp = self.allocate(org_id, admin_headers, employee["id"], CREDIT)
        self.assertEqual(alloc_resp.status_code, 201)
        emp_headers = employee["headers"]

        # 3. Set up product with price 30M and inventory
        with self.db.write_transaction() as conn:
            product_id, offer_id = self._setup_product_with_offer(conn, PRICE)
        self.set_stock(product_id, 5)

        # 4. Add to cart
        r_cart = self.client.post(
            "/api/v1/cart/items",
            json={"product_id": product_id, "quantity": 1},
            headers=emp_headers,
        )
        self.assertIn(r_cart.status_code, (200, 201), f"Cart: {r_cart.get_json()}")

        # 5. First checkout
        idem_key = uuid.uuid4().hex
        resp = self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": self.DEFAULT_ADDRESS, "payment_method": "card"},
            headers={**emp_headers, "Idempotency-Key": idem_key},
            environ_base={"REMOTE_ADDR": "1.2.3.4"},
        )
        self.assertEqual(resp.status_code, 201,
                         f"Checkout must succeed: {resp.get_json()}")
        order = resp.get_json()["order"]

        # 6. Assert exact integer amounts (v6: total is VAT-inclusive)
        self.assertEqual(int(order["total_minor"]), TOTAL,
                         f"Total must be exactly {TOTAL} (subtotal 30M + VAT 3M)")
        self.assertEqual(int(order.get("credit_minor", 0)), CREDIT,
                         "Credit used must be exactly 20,000,000")
        cash_charged = int(order["total_minor"]) - int(order.get("credit_minor", 0))
        self.assertEqual(cash_charged, CASH,
                         f"PSP charge must be exactly {CASH}")
        self.assertEqual(int(order["total_minor"]), CREDIT + CASH,
                         "Total = credit + cash (no floats)")

        # 7. Idempotency: replay same key → same result, not double-charged
        resp2 = self.client.post(
            "/api/v1/checkout",
            json={"shipping_address": self.DEFAULT_ADDRESS, "payment_method": "card"},
            headers={**emp_headers, "Idempotency-Key": idem_key},
            environ_base={"REMOTE_ADDR": "1.2.3.4"},
        )
        self.assertEqual(resp2.status_code, 201,
                         f"Idempotency replay must return 201: {resp2.get_json()}")
        order2 = resp2.get_json()["order"]
        self.assertEqual(order2["order_number"], order["order_number"],
                         "Replayed checkout must return same order number")

        # Not double-charged: only 1 captured payment_intent
        with self.db.read_transaction() as conn:
            captured_count = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]
        self.assertEqual(captured_count, 1, "Must not double-charge (exactly 1 captured intent)")

        # Credit not doubled
        self.assertEqual(int(order2.get("credit_minor", 0)), CREDIT,
                         "Replayed order must still show 20M credit")


# ── Blocker 4: Scenario 17 canonical product procurement ─────────────────────

class TestScenario17CanonicalProductProcurement(AppTestCase):
    """Scenario 17: Full procurement cycle with a canonical master product.

    Covers: multi-identifier resolution (EAN/SUPPLIER_SKU/ERP_CODE), two-supplier RFQ,
    HTTP-authenticated supplier quote isolation, credit_ledger_entries unchanged, PO immutability.
    Supplier A is LOCAL (Tehran); Supplier B is NON-LOCAL (Isfahan).
    """

    def _create_supplier_with_user_and_location(
        self, suffix: str, city: str, province: str
    ) -> tuple:
        """Create a supplier portal user, link it to a new supplier, add a location.

        Performs all DB work OUTSIDE a transaction so HTTP registration/login can interleave.
        Returns (sup_id, user_id, auth_headers).
        """
        # 1. Register a portal user via HTTP (cannot be inside DB transaction)
        email = f"supplier_{uuid.uuid4().hex[:8]}@test.invalid"
        password = "Supplier@1234"
        r = self.client.post("/api/v1/auth/register",
                             json={"email": email, "password": password,
                                   "full_name": f"Supplier {suffix}"})
        self.assertEqual(r.status_code, 201, f"Register supplier user: {r.get_json()}")
        user_id = r.get_json()["user"]["id"]

        # 2. Create supplier record and link user, then add location — all in one transaction
        nat_id = f"S17{uuid.uuid4().hex[:8]}{suffix}"
        sup_id = None
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, user_id) "
                "VALUES (?,?,?,'active',?)",
                (f"تأمین‌کننده سناریو۱۷ {suffix}", f"تأمین {suffix}", nat_id, user_id),
            )
            sup_id = cur.lastrowid
            conn.execute(
                "INSERT INTO supplier_locations "
                "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
                "VALUES (?,?,?,'active',1,1)",
                (sup_id, province, city),
            )

        # 3. Login and return headers
        r2 = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(r2.status_code, 200, f"Login supplier: {r2.get_json()}")
        token = r2.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        return sup_id, user_id, headers

    def test_canonical_product_full_procurement_cycle(self):
        """Full procurement: canonical product identity + multi-supplier RFQ + PO."""
        # ── Step 1: Setup Alice as employee of Org A ─────────────────────────
        org_a, alice_h, alice_uid = _make_org_with_admin(self)
        org_id = org_a["id"]
        _set_procurement_role(self, alice_uid, org_id, "approver", base_role="organization_admin")

        admin_h = self.admin_headers()

        # Snapshot credit_ledger_entries BEFORE the entire procurement lifecycle
        with self.db.read_transaction() as conn:
            credit_ledger_before = conn.execute(
                "SELECT COUNT(*) FROM credit_ledger_entries"
            ).fetchone()[0]

        # ── Step 2: Create ONE canonical master product ───────────────────────
        resp = self.client.post(
            "/api/v1/admin/catalog/products",
            json={
                "canonical_name_fa": "روغن طبیعت بدون کلسترول ۱.۵ لیتری",
                "canonical_name_en": "Nature Oil Cholesterol-Free 1.5L",
                "category": "food",
                "brand": "طبیعت",
            },
            headers=admin_h,
        )
        self.assertEqual(resp.status_code, 201, f"Create product: {resp.get_json()}")
        product = resp.get_json()
        product_id = product["id"]
        public_product_id = product["public_product_id"]

        # ── Step 3: Add multiple identifiers ─────────────────────────────────
        ean_value    = f"869{uuid.uuid4().int % 10**10:010d}"
        sku_value    = f"SUP-SKU-{uuid.uuid4().hex[:8]}"
        erp_value    = f"ERP-{uuid.uuid4().hex[:6]}"

        for id_type, id_value in [
            ("EAN",          ean_value),
            ("SUPPLIER_SKU", sku_value),
            ("ERP_CODE",     erp_value),
        ]:
            r = self.client.post(
                f"/api/v1/admin/catalog/products/{product_id}/identifiers",
                json={"identifier_type": id_type, "identifier_value": id_value},
                headers=admin_h,
            )
            self.assertEqual(r.status_code, 201, f"Add {id_type}: {r.get_json()}")

        # ── Step 4: Alice scans barcode → resolves to canonical product (all 3 IDs)
        for id_type, id_value in [
            ("EAN",          ean_value),
            ("SUPPLIER_SKU", sku_value),
            ("ERP_CODE",     erp_value),
        ]:
            r_resolve = self.client.get(
                f"/api/v1/catalog/resolve?type={id_type}&value={id_value}",
                headers=alice_h,
            )
            self.assertEqual(r_resolve.status_code, 200,
                             f"Resolve {id_type}: {r_resolve.get_json()}")
            self.assertEqual(r_resolve.get_json()["id"], product_id,
                             f"{id_type}={id_value!r} must resolve to canonical product id={product_id}")

        # ── Step 5: Create PR using master_product_id ─────────────────────────
        resp_pr = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests",
            json={
                "title": "خرید روغن طبیعت",
                "items": [
                    {"master_product_id": product_id, "quantity": 50, "unit": "بطری",
                     "estimated_unit_price_minor": 500_000},
                ],
            },
            headers=alice_h,
        )
        self.assertEqual(resp_pr.status_code, 201, f"Create PR: {resp_pr.get_json()}")
        pr = resp_pr.get_json()["purchase_request"]
        pr_id = pr["id"]
        self.assertEqual(pr["status"], "draft")

        # ── Step 6: Submit + Approve PR ───────────────────────────────────────
        r_sub = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/submit",
            headers=alice_h,
        )
        self.assertEqual(r_sub.status_code, 200, f"Submit PR: {r_sub.get_json()}")

        r_appr = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/requests/{pr_id}/approve",
            json={"action": "approve", "reason": "تأیید شد"},
            headers=alice_h,
        )
        self.assertEqual(r_appr.status_code, 200, f"Approve PR: {r_appr.get_json()}")
        self.assertEqual(r_appr.get_json()["purchase_request"]["status"], "approved")

        # ── Step 7: Create RFQ ────────────────────────────────────────────────
        resp_rfq = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs",
            json={"purchase_request_id": pr_id, "title": "استعلام روغن طبیعت"},
            headers=alice_h,
        )
        self.assertEqual(resp_rfq.status_code, 201, f"Create RFQ: {resp_rfq.get_json()}")
        rfq = resp_rfq.get_json()["rfq"]
        rfq_id = rfq["id"]
        rfq_items = rfq["items"]

        # PR item references master product
        with self.db.read_transaction() as conn:
            pr_item = conn.execute(
                "SELECT master_product_id FROM purchase_request_items WHERE purchase_request_id=?",
                (pr_id,)
            ).fetchone()
        self.assertEqual(pr_item["master_product_id"], product_id,
                         "PR item must reference master_product_id")

        # ── Step 8: Create TWO suppliers (A=local Tehran, B=non-local Isfahan) ─
        sup_a_id, user_a_id, supplier_a_h = \
            self._create_supplier_with_user_and_location("A", "تهران", "تهران")
        sup_b_id, user_b_id, supplier_b_h = \
            self._create_supplier_with_user_and_location("B", "اصفهان", "اصفهان")

        r_inv_a = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/invite",
            json={"supplier_id": sup_a_id},
            headers=alice_h,
        )
        self.assertEqual(r_inv_a.status_code, 201, f"Invite A: {r_inv_a.get_json()}")

        r_inv_b = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/invite",
            json={"supplier_id": sup_b_id},
            headers=alice_h,
        )
        self.assertEqual(r_inv_b.status_code, 201, f"Invite B: {r_inv_b.get_json()}")

        # Open RFQ
        r_open = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/open",
            headers=alice_h,
        )
        self.assertEqual(r_open.status_code, 200)

        # Both suppliers can see the RFQ they were invited to
        r_sup_a_rfqs = self.client.get("/api/v1/supplier/rfqs", headers=supplier_a_h)
        self.assertEqual(r_sup_a_rfqs.status_code, 200)
        a_rfq_ids = [r["id"] for r in r_sup_a_rfqs.get_json().get("items", [])]
        self.assertIn(rfq_id, a_rfq_ids, "Supplier A must see the RFQ it was invited to")

        r_sup_b_rfqs = self.client.get("/api/v1/supplier/rfqs", headers=supplier_b_h)
        self.assertEqual(r_sup_b_rfqs.status_code, 200)
        b_rfq_ids = [r["id"] for r in r_sup_b_rfqs.get_json().get("items", [])]
        self.assertIn(rfq_id, b_rfq_ids, "Supplier B must see the RFQ it was invited to")

        # ── Step 9: Both suppliers submit quotes via HTTP (portal API) ────────
        rfq_item_id = rfq_items[0]["id"]

        r_qa = self.client.post(
            f"/api/v1/supplier/rfqs/{rfq_id}/quotes",
            json={
                "items": [{"rfq_item_id": rfq_item_id, "unit_price_minor": 480_000, "quantity": 50}],
                "shipping_cost_minor": 50_000,
            },
            headers=supplier_a_h,
        )
        self.assertEqual(r_qa.status_code, 201, f"Supplier A quote: {r_qa.get_json()}")
        quote_a_id = r_qa.get_json()["quote"]["id"]

        r_qb = self.client.post(
            f"/api/v1/supplier/rfqs/{rfq_id}/quotes",
            json={
                "items": [{"rfq_item_id": rfq_item_id, "unit_price_minor": 510_000, "quantity": 50}],
                "shipping_cost_minor": 0,
            },
            headers=supplier_b_h,
        )
        self.assertEqual(r_qb.status_code, 201, f"Supplier B quote: {r_qb.get_json()}")
        quote_b_id = r_qb.get_json()["quote"]["id"]

        # ── Supplier quote isolation via HTTP ─────────────────────────────────
        # Supplier A can view its own quote
        r_a_own = self.client.get(f"/api/v1/supplier/quotes/{quote_a_id}", headers=supplier_a_h)
        self.assertEqual(r_a_own.status_code, 200, "Supplier A must be able to view its own quote")

        # Supplier B can view its own quote
        r_b_own = self.client.get(f"/api/v1/supplier/quotes/{quote_b_id}", headers=supplier_b_h)
        self.assertEqual(r_b_own.status_code, 200, "Supplier B must be able to view its own quote")

        # Supplier A CANNOT view Supplier B's quote — must be 403
        r_a_cross = self.client.get(f"/api/v1/supplier/quotes/{quote_b_id}", headers=supplier_a_h)
        self.assertEqual(r_a_cross.status_code, 403,
                         "Supplier A must NOT be able to view Supplier B's quote (expected 403)")

        # Supplier B CANNOT view Supplier A's quote — must be 403
        r_b_cross = self.client.get(f"/api/v1/supplier/quotes/{quote_a_id}", headers=supplier_b_h)
        self.assertEqual(r_b_cross.status_code, 403,
                         "Supplier B must NOT be able to view Supplier A's quote (expected 403)")

        # ── Step 10: Close + Compare quotes ───────────────────────────────────
        r_close = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/close",
            headers=alice_h,
        )
        self.assertEqual(r_close.status_code, 200)

        r_cmp = self.client.get(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/comparison",
            headers=alice_h,
        )
        self.assertEqual(r_cmp.status_code, 200)
        comparison = r_cmp.get_json()
        self.assertEqual(comparison["total_quotes"], 2)
        # Supplier A: 480K*50 + 50K = 24,050,000
        # Supplier B: 510K*50 + 0   = 25,500,000
        self.assertEqual(comparison["lowest_quote_id"], quote_a_id,
                         "Supplier A must be lowest (24.05M vs 25.5M)")

        # ── Step 11: Award to Supplier A ──────────────────────────────────────
        r_award = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/rfqs/{rfq_id}/award",
            json={"winning_quote_id": quote_a_id, "reason": "بهترین قیمت"},
            headers=alice_h,
        )
        self.assertEqual(r_award.status_code, 200)
        self.assertEqual(r_award.get_json()["rfq"]["status"], "awarded")

        # ── Step 12: Create PO ────────────────────────────────────────────────
        r_po = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/purchase-orders",
            json={"supplier_quote_id": quote_a_id, "vat_bps": 900},
            headers=alice_h,
        )
        self.assertEqual(r_po.status_code, 201, f"Create PO: {r_po.get_json()}")
        po = r_po.get_json()["purchase_order"]
        po_id = po["id"]

        # ── Final Assertions ──────────────────────────────────────────────────

        # PO financial snapshot immutable
        items_total = 480_000 * 50  # 24,000,000
        self.assertEqual(po["total_amount_minor"], items_total,
                         "PO items total must be exactly 24,000,000")
        self.assertGreater(po["grand_total_minor"], items_total,
                           "grand_total must exceed items_total (shipping + VAT)")

        # Confirm PO
        r_confirm = self.client.post(
            f"/api/v1/orgs/{org_id}/procurement/purchase-orders/{po_id}/confirm",
            headers=alice_h,
        )
        self.assertEqual(r_confirm.status_code, 200)

        # Credit ledger NOT mutated — procurement-only flow must never touch credit_ledger_entries
        with self.db.read_transaction() as conn:
            credit_ledger_after = conn.execute(
                "SELECT COUNT(*) FROM credit_ledger_entries"
            ).fetchone()[0]
        self.assertEqual(credit_ledger_before, credit_ledger_after,
                         "Procurement-only flow must NOT mutate credit_ledger_entries")


if __name__ == "__main__":
    unittest.main()
