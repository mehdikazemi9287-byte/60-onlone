"""Independent review of P1 batch 1 (2026-11-22): regression tests for the confirmed findings.

Synthetic test fixtures only (throwaway users/organizations, seeded test catalog); nothing here is runtime
business data.
"""
from __future__ import annotations

import uuid

from tests.base import AppTestCase

STAFF = {"X-Shopping-Mode": "staff"}
ORG = {"X-Shopping-Mode": "org"}
PAPER = "office-paper-a4-carton"


class _Review(AppTestCase):
    def exempt(self, org_id: int) -> None:
        with self.db.write_transaction() as conn:
            cat = conn.execute("SELECT id FROM tax_categories WHERE code='STANDARD'").fetchone()
            conn.execute("INSERT INTO tax_org_exemptions (organization_id, tax_category_id, effective_from, "
                         "effective_until) VALUES (?,?, '2000-01-01', NULL)", (org_id, cat["id"]))

    def headers_of(self, member: dict) -> dict:
        return {"Authorization": member["headers"]["Authorization"]}

    def filled(self, headers: dict) -> None:
        p = self.product(PAPER)
        self.set_stock(p["id"], 50)
        r = self.add_to_cart(headers, p["id"], 1)
        self.assertEqual(r.status_code, 201, r.get_json())


class ModeTaxExemptionTest(_Review):
    """The organization VAT exemption follows the organization the shopping mode is entitled to use."""

    def test_suspended_org_membership_gives_no_exemption_in_org_mode(self):
        org, admin_headers, _, emp = self.org_fixture(credit_minor=0)
        self.exempt(org["id"])
        auth = self.headers_of(emp)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organizations SET status='suspended' WHERE id=?", (org["id"],))
        # staff mode is closed for a suspended organization …
        self.assertEqual(self.client.get("/api/v1/cart", headers={**auth, **STAFF}).get_json()["mode_access"]["allowed"],
                         False)
        # … and the open «سازمانی و عمده» cart must not carry that organization's exemption either.
        self.filled({**auth, **ORG})
        q = self.quote({**auth, **ORG})
        self.assertGreater(q["tax_minor"], 0, q)

    def test_plain_employee_gets_no_org_exemption_in_buyer_paid_org_mode(self):
        org, admin_headers, _, emp = self.org_fixture(credit_minor=0)
        self.exempt(org["id"])
        auth = self.headers_of(emp)
        self.filled({**auth, **STAFF})
        self.assertEqual(self.quote({**auth, **STAFF})["tax_minor"], 0)  # staff purchase: unchanged behaviour
        self.filled({**auth, **ORG})
        self.assertGreater(self.quote({**auth, **ORG})["tax_minor"], 0)  # not an org buyer role in org mode
        # an organization manager in org mode is the organization buying: exemption applies
        self.filled({**admin_headers, **ORG})
        self.assertEqual(self.quote({**admin_headers, **ORG})["tax_minor"], 0)

    def test_order_tax_matches_quote_in_org_mode(self):
        org, admin_headers, _, emp = self.org_fixture(credit_minor=0)
        self.exempt(org["id"])
        auth = self.headers_of(emp)
        self.filled({**auth, **ORG})
        r = self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS},
                             headers={**auth, **ORG, "Idempotency-Key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertGreater(r.get_json()["order"]["tax_minor"], 0)


class ProformaBuyerTest(_Review):
    def test_personal_proforma_is_not_issued_to_the_organization(self):
        org, admin_headers, _, emp = self.org_fixture(credit_minor=0)
        auth = self.headers_of(emp)
        self.filled(auth)
        pf = self.client.post("/api/v1/me/proformas", json={}, headers=auth)
        self.assertEqual(pf.status_code, 201, pf.get_json())
        self.assertIsNone(pf.get_json()["organization"])  # a personal purchase is not the organization's
        self.filled({**auth, **STAFF})
        pf = self.client.post("/api/v1/me/proformas", json={}, headers={**auth, **STAFF})
        self.assertEqual(pf.status_code, 201, pf.get_json())
        self.assertIsNotNone(pf.get_json()["organization"])


class ModeCartCreationTest(_Review):
    def test_removing_from_a_forbidden_mode_never_creates_a_cart(self):
        _, customer = self.new_customer()
        p = self.product(PAPER)
        r = self.client.delete(f"/api/v1/cart/items/{p['id']}", headers={**customer, **STAFF})
        self.assertEqual(r.status_code, 200, r.get_json())
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM carts WHERE shopping_mode='staff'").fetchone()[0], 0)
