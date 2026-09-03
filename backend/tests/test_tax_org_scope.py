"""Blocker 1 — Tax organization scope tests.

POST /api/v1/tax/calculate must derive and validate organization access
server-side. The caller-supplied organization_id is never trusted directly.

Rules under test:
  - Admin may calculate for an explicitly supplied organization_id.
  - An organization member may calculate only for an organization in which they
    hold an ACTIVE membership.
  - Supplier/customer without such membership must not obtain another
    organization's exemption.
  - Unauthorized or cross-tenant organization references return 404, not 403.
  - When organization_id is omitted, no exemption is invented.
  - Unauthenticated requests return 401.

Negative tests:
  - Customer uses another organization's ID → 404
  - Member of org A uses org B's ID → 404
  - Inactive membership → 404
  - Unauthenticated request → 401
  - Valid active member → 200, exemption applied
  - Admin explicit organization → 200, exemption applied
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase


_CALCULATE_URL = "/api/v1/tax/calculate"
_BASE_BODY = {
    "subtotal_minor": 1_000_000,
    "tax_category_code": "STANDARD",
    "effective_date": "2026-01-01",
}


def _seed_exemption(case: AppTestCase, org_id: int) -> None:
    """Insert a tax exemption for the given organization (STANDARD category)."""
    with case.db.write_transaction() as conn:
        # Fetch tax_category id for STANDARD
        cat = conn.execute(
            "SELECT id FROM tax_categories WHERE code='STANDARD'"
        ).fetchone()
        if cat is None:
            return
        # Insert exemption valid for all of 2026
        conn.execute(
            """
            INSERT INTO tax_org_exemptions
                (organization_id, tax_category_id, effective_from, effective_until)
            VALUES (?, ?, '2026-01-01', '2026-12-31')
            """,
            (org_id, cat["id"]),
        )


class TestTaxOrgScope(AppTestCase):
    """Server-side organization scope enforcement on POST /tax/calculate."""

    # ── Negative: unauthenticated ────────────────────────────────────────────

    def test_unauthenticated_request_returns_401(self):
        """No Authorization header → 401."""
        resp = self.client.post(_CALCULATE_URL, json=_BASE_BODY)
        self.assertEqual(resp.status_code, 401,
                         f"Expected 401 for unauthenticated, got {resp.status_code}: {resp.get_json()}")

    # ── Negative: customer uses a foreign org ─────────────────────────────────

    def test_customer_using_another_orgs_id_returns_404(self):
        """Customer without org membership cannot use another org's exemption → 404."""
        # Create org with exemption
        org = self.create_organization()
        _seed_exemption(self, org["id"])

        # Completely unrelated customer
        _, customer_hdrs = self.new_customer()

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=customer_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Expected 404 for cross-tenant org, got {resp.status_code}: {resp.get_json()}")

    # ── Negative: member of org A uses org B ─────────────────────────────────

    def test_org_a_member_using_org_b_id_returns_404(self):
        """A member of org A must not use org B's ID → 404."""
        org_a = self.create_organization(name="سازمان الف")
        org_b = self.create_organization(name="سازمان ب")
        _seed_exemption(self, org_b["id"])

        # Create member of org A only
        admin_a_hdrs, _ = self.make_org_admin(org_a["id"])
        member = self.add_employee(org_a["id"], admin_a_hdrs)
        member_hdrs = member["headers"]

        # Member of A tries to use org B's exemption
        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org_b["id"]},
            headers=member_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Member of org A should get 404 for org B, got {resp.status_code}: {resp.get_json()}")

    # ── Negative: inactive membership ────────────────────────────────────────

    def test_inactive_membership_returns_404(self):
        """User with INACTIVE membership in the referenced org → 404."""
        org = self.create_organization()
        _seed_exemption(self, org["id"])

        # Add a member, then deactivate them directly
        admin_hdrs, _ = self.make_org_admin(org["id"])
        member = self.add_employee(org["id"], admin_hdrs, status="active")
        # Deactivate the membership directly in DB
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE organization_memberships SET status='inactive' WHERE id=?",
                (member["id"],),
            )
        member_hdrs = member["headers"]

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=member_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Inactive member should get 404, got {resp.status_code}: {resp.get_json()}")

    # ── Negative: supplier without membership ────────────────────────────────

    def test_supplier_without_membership_returns_404(self):
        """A supplier user with no org membership cannot use an org's exemption → 404."""
        org = self.create_organization()
        _seed_exemption(self, org["id"])

        info = self.create_test_supplier()
        supplier_hdrs = info["headers"]

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=supplier_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Supplier without membership should get 404, got {resp.status_code}: {resp.get_json()}")

    # ── Negative: nonexistent organization_id ────────────────────────────────

    def test_nonexistent_org_id_returns_404(self):
        """organization_id referencing a non-existent org → 404 (not 403)."""
        _, customer_hdrs = self.new_customer()
        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": 9_999_999},
            headers=customer_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Nonexistent org should get 404, got {resp.status_code}: {resp.get_json()}")

    # ── Positive: valid active member ────────────────────────────────────────

    def test_valid_active_member_gets_exemption(self):
        """Active member of the org gets the exemption applied (rate_bps = 0)."""
        org = self.create_organization()
        _seed_exemption(self, org["id"])

        admin_hdrs, _ = self.make_org_admin(org["id"])
        member = self.add_employee(org["id"], admin_hdrs)
        member_hdrs = member["headers"]

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=member_hdrs,
        )
        self.assertEqual(resp.status_code, 200,
                         f"Active member should get 200, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertEqual(data["rate_bps"], 0,
                         f"Active member with exemption should get rate_bps=0, got {data['rate_bps']}")
        self.assertEqual(data["tax_minor"], 0)

    def test_valid_active_member_no_exemption_gets_standard_rate(self):
        """Active member of an org without exemption gets the standard rate (not 0)."""
        org = self.create_organization()
        # No exemption seeded

        admin_hdrs, _ = self.make_org_admin(org["id"])
        member = self.add_employee(org["id"], admin_hdrs)
        member_hdrs = member["headers"]

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=member_hdrs,
        )
        self.assertEqual(resp.status_code, 200,
                         f"Active member should get 200, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertGreater(data["rate_bps"], 0,
                           "Without exemption rate_bps must be > 0")

    # ── Positive: admin explicit organization ─────────────────────────────────

    def test_admin_can_use_any_existing_org_id(self):
        """Platform admin may supply any existing org_id explicitly."""
        org = self.create_organization()
        _seed_exemption(self, org["id"])

        admin_hdrs = self.admin_headers()

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=admin_hdrs,
        )
        self.assertEqual(resp.status_code, 200,
                         f"Admin should get 200, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertEqual(data["rate_bps"], 0,
                         f"Admin with exemption should get rate_bps=0, got {data['rate_bps']}")

    def test_admin_nonexistent_org_returns_404(self):
        """Admin supplying a non-existent org_id → 404."""
        admin_hdrs = self.admin_headers()
        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": 9_999_998},
            headers=admin_hdrs,
        )
        self.assertEqual(resp.status_code, 404,
                         f"Admin with nonexistent org should get 404, got {resp.status_code}")

    # ── No org_id: no exemption invented ────────────────────────────────────

    def test_no_org_id_no_exemption_applied(self):
        """When organization_id is omitted, no exemption is invented — standard rate applies."""
        _, customer_hdrs = self.new_customer()
        resp = self.client.post(
            _CALCULATE_URL,
            json=_BASE_BODY,  # no organization_id
            headers=customer_hdrs,
        )
        self.assertEqual(resp.status_code, 200,
                         f"Expected 200 without org_id, got {resp.status_code}: {resp.get_json()}")
        data = resp.get_json()
        self.assertGreater(data["rate_bps"], 0,
                           "Without org_id no exemption should be applied; rate_bps must be > 0")

    # ── Response is not 403 ───────────────────────────────────────────────────

    def test_cross_tenant_returns_404_not_403(self):
        """Cross-tenant organization reference must return 404, never 403."""
        org = self.create_organization()
        _, customer_hdrs = self.new_customer()

        resp = self.client.post(
            _CALCULATE_URL,
            json={**_BASE_BODY, "organization_id": org["id"]},
            headers=customer_hdrs,
        )
        self.assertNotEqual(resp.status_code, 403,
                             "Cross-tenant org must return 404, not 403")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
