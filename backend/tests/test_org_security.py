"""Negative security tests for the organization tenant boundary.

Every test here asserts that something is REFUSED. If one of these starts
passing silently, a tenant boundary has been broken.
"""
from __future__ import annotations

import re
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase  # noqa: E402


class TwoOrganizations(AppTestCase):
    """Org A and Org B, each with an admin, a finance user and an employee."""

    def setUp(self):
        super().setUp()
        self.a = self.create_organization(name="سازمان الف", credit_limit_minor=1_000_000_000)
        self.b = self.create_organization(name="سازمان ب", credit_limit_minor=1_000_000_000)
        self.a_admin, self.a_admin_member = self.make_org_admin(self.a["id"])
        self.b_admin, self.b_admin_member = self.make_org_admin(self.b["id"])
        self.a_employee = self.add_employee(self.a["id"], self.a_admin)
        self.b_employee = self.add_employee(self.b["id"], self.b_admin)
        self.allocate(self.a["id"], self.a_admin, self.a_employee["id"], 50_000_000)
        self.allocate(self.b["id"], self.b_admin, self.b_employee["id"], 70_000_000)


class CrossTenantReadTest(TwoOrganizations):
    def test_org_a_admin_cannot_read_org_b(self):
        response = self.client.get(f"/api/v1/organizations/{self.b['id']}", headers=self.a_admin)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "organization_not_found")

    def test_org_a_admin_cannot_list_org_b_members(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/members", headers=self.a_admin
        )
        self.assertEqual(response.status_code, 404)

    def test_org_a_admin_cannot_read_org_b_credit_allocations(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/credit-allocations", headers=self.a_admin
        )
        self.assertEqual(response.status_code, 404)

    def test_org_a_admin_cannot_read_org_b_credit_transactions(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/credit-transactions", headers=self.a_admin
        )
        self.assertEqual(response.status_code, 404)

    def test_org_a_admin_cannot_read_org_b_orders(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/orders", headers=self.a_admin
        )
        self.assertEqual(response.status_code, 404)

    def test_org_a_admin_cannot_read_org_b_summary(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/summary", headers=self.a_admin
        )
        self.assertEqual(response.status_code, 404)

    def test_cross_tenant_denial_is_404_not_403(self):
        """A 403 would confirm the organization exists. It must not."""
        real = self.client.get(f"/api/v1/organizations/{self.b['id']}", headers=self.a_admin)
        fake = self.client.get("/api/v1/organizations/999999", headers=self.a_admin)
        self.assertEqual(real.status_code, fake.status_code)
        self.assertEqual(real.get_json()["error"]["code"], fake.get_json()["error"]["code"])


class CrossTenantWriteTest(TwoOrganizations):
    def test_org_a_admin_cannot_update_org_b(self):
        response = self.client.patch(
            f"/api/v1/organizations/{self.b['id']}",
            json={"display_name": "hijacked"}, headers=self.a_admin,
        )
        self.assertEqual(response.status_code, 404)
        fresh = self.client.get(f"/api/v1/organizations/{self.b['id']}", headers=self.b_admin)
        self.assertEqual(fresh.get_json()["organization"]["display_name"], "سازمان ب")

    def test_org_a_admin_cannot_add_a_member_to_org_b(self):
        email, _, _ = self.register()
        response = self.client.post(
            f"/api/v1/organizations/{self.b['id']}/members",
            json={"email": email}, headers=self.a_admin,
        )
        self.assertEqual(response.status_code, 404)

    def test_org_a_admin_cannot_deactivate_an_org_b_member(self):
        response = self.client.patch(
            f"/api/v1/organizations/{self.b['id']}/members/{self.b_employee['id']}",
            json={"status": "inactive"}, headers=self.a_admin,
        )
        self.assertEqual(response.status_code, 404)

    def test_org_a_admin_cannot_allocate_credit_in_org_b(self):
        response = self.allocate(self.b["id"], self.a_admin, self.b_employee["id"], 1_000_000)
        self.assertEqual(response.status_code, 404)

    def test_membership_id_from_another_org_is_rejected_on_the_own_org_route(self):
        """Passing org B's membership id to org A's allocate endpoint."""
        response = self.allocate(self.a["id"], self.a_admin, self.b_employee["id"], 1_000_000)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "membership_not_found")

    def test_allocation_id_from_another_org_cannot_be_adjusted(self):
        b_allocation = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/credit-allocations", headers=self.b_admin
        ).get_json()["items"][0]
        response = self.client.post(
            f"/api/v1/organizations/{self.a['id']}/credit-allocations/{b_allocation['id']}/adjust",
            json={"delta_minor": 1_000_000, "note": "x"}, headers=self.a_admin,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "allocation_not_found")

    def test_membership_id_from_another_org_cannot_be_updated_via_own_org_route(self):
        response = self.client.patch(
            f"/api/v1/organizations/{self.a['id']}/members/{self.b_employee['id']}",
            json={"status": "inactive"}, headers=self.a_admin,
        )
        self.assertEqual(response.status_code, 404)


class PrivilegeEscalationTest(TwoOrganizations):
    def test_employee_cannot_promote_themselves_to_admin(self):
        response = self.client.patch(
            f"/api/v1/organizations/{self.a['id']}/members/{self.a_employee['id']}",
            json={"role": "organization_admin"}, headers=self.a_employee["headers"],
        )
        self.assertEqual(response.status_code, 403)

    def test_employee_cannot_read_the_member_list(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.a['id']}/members", headers=self.a_employee["headers"]
        )
        self.assertEqual(response.status_code, 403)

    def test_employee_cannot_read_organization_wide_credit_transactions(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.a['id']}/credit-transactions",
            headers=self.a_employee["headers"],
        )
        self.assertEqual(response.status_code, 403)

    def test_employee_cannot_read_organization_orders(self):
        response = self.client.get(
            f"/api/v1/organizations/{self.a['id']}/orders", headers=self.a_employee["headers"]
        )
        self.assertEqual(response.status_code, 403)

    def test_procurement_agent_cannot_allocate_credit(self):
        agent = self.add_employee(self.a["id"], self.a_admin, role="procurement_agent")
        response = self.allocate(self.a["id"], agent["headers"], self.a_employee["id"], 1_000_000)
        self.assertEqual(response.status_code, 403)

    def test_finance_role_cannot_add_members(self):
        finance = self.add_employee(self.a["id"], self.a_admin, role="organization_finance")
        email, _, _ = self.register()
        response = self.client.post(
            f"/api/v1/organizations/{self.a['id']}/members",
            json={"email": email}, headers=finance["headers"],
        )
        self.assertEqual(response.status_code, 403)

    def test_a_non_member_gets_404_not_403(self):
        _, outsider = self.new_customer()
        response = self.client.get(f"/api/v1/organizations/{self.a['id']}", headers=outsider)
        self.assertEqual(response.status_code, 404)

    def test_every_organization_route_rejects_anonymous_access(self):
        org_id = self.a["id"]
        cases = [
            ("get", f"/api/v1/organizations/{org_id}"),
            ("patch", f"/api/v1/organizations/{org_id}"),
            ("get", f"/api/v1/organizations/{org_id}/members"),
            ("post", f"/api/v1/organizations/{org_id}/members"),
            ("get", f"/api/v1/organizations/{org_id}/credit-allocations"),
            ("post", f"/api/v1/organizations/{org_id}/credit-allocations"),
            ("get", f"/api/v1/organizations/{org_id}/credit-transactions"),
            ("get", f"/api/v1/organizations/{org_id}/orders"),
            ("get", f"/api/v1/organizations/{org_id}/summary"),
            ("get", "/api/v1/me/credit"),
            ("get", "/api/v1/me/credit/transactions"),
            ("get", "/api/v1/checkout/quote"),
        ]
        for method, path in cases:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, json={})
                self.assertEqual(response.status_code, 401, f"{method} {path}")


class CrossTenantDataLeakTest(TwoOrganizations):
    def test_employee_of_a_cannot_spend_credit_of_b(self):
        """Alice's quote must only ever consider allocations issued to Alice."""
        kettle = self.client.get("/api/v1/products/appliance-kettle-2l").get_json()["product"]
        self.add_to_cart(self.a_employee["headers"], kettle["id"], 1)
        quote = self.quote(self.a_employee["headers"])
        self.assertEqual(quote["organization"]["id"], self.a["id"])
        self.assertNotEqual(quote["organization"]["id"], self.b["id"])

    def test_order_funded_by_a_is_invisible_to_b(self):
        kettle = self.client.get("/api/v1/products/appliance-kettle-2l").get_json()["product"]
        self.add_to_cart(self.a_employee["headers"], kettle["id"], 1)
        order = self.checkout(self.a_employee["headers"]).get_json()["order"]

        a_orders = self.client.get(
            f"/api/v1/organizations/{self.a['id']}/orders", headers=self.a_admin
        ).get_json()
        b_orders = self.client.get(
            f"/api/v1/organizations/{self.b['id']}/orders", headers=self.b_admin
        ).get_json()
        self.assertEqual(a_orders["total"], 1)
        self.assertEqual(b_orders["total"], 0)
        self.assertEqual(a_orders["items"][0]["order_number"], order["order_number"])

    def test_employee_of_a_cannot_read_an_order_of_b(self):
        kettle = self.client.get("/api/v1/products/appliance-kettle-2l").get_json()["product"]
        self.add_to_cart(self.b_employee["headers"], kettle["id"], 1)
        order = self.checkout(self.b_employee["headers"]).get_json()["order"]
        response = self.client.get(
            f"/api/v1/orders/{order['order_number']}", headers=self.a_employee["headers"]
        )
        self.assertEqual(response.status_code, 404)

    def test_org_credit_transactions_never_include_another_tenant(self):
        rows = self.client.get(
            f"/api/v1/organizations/{self.a['id']}/credit-transactions", headers=self.a_admin
        ).get_json()
        self.assertTrue(rows["items"])
        self.assertTrue(all(t["organization_id"] == self.a["id"] for t in rows["items"]))

    def test_org_member_list_never_includes_another_tenant(self):
        members = self.client.get(
            f"/api/v1/organizations/{self.a['id']}/members", headers=self.a_admin
        ).get_json()
        self.assertTrue(all(m["organization_id"] == self.a["id"] for m in members["items"]))
        emails = {m["email"] for m in members["items"]}
        self.assertNotIn(self.b_employee["email"], emails)


class PlatformAdminTest(TwoOrganizations):
    def test_platform_admin_can_reach_any_organization(self):
        platform = self.admin_headers()
        for org in (self.a, self.b):
            response = self.client.get(f"/api/v1/organizations/{org['id']}", headers=platform)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["membership"]["platform_admin"])

    def test_platform_admin_still_gets_404_for_a_missing_organization(self):
        platform = self.admin_headers()
        response = self.client.get("/api/v1/organizations/999999", headers=platform)
        self.assertEqual(response.status_code, 404)


class SecretsAndPasswordsTest(AppTestCase):
    def test_no_plaintext_password_in_any_phase_2_table(self):
        password = "Phase2Uniq!Pass"
        org = self.create_organization()
        admin_headers, _ = self.make_org_admin(org["id"])
        email = f"p2scan{uuid.uuid4().hex[:8]}@example.com"
        self.register(email, password=password)
        self.client.post(f"/api/v1/organizations/{org['id']}/members",
                         json={"email": email}, headers=admin_headers)

        tables = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for table in tables:
            columns = [r["name"] for r in self.db.query(f"PRAGMA table_info({table})")]
            for row in self.db.query(f"SELECT * FROM {table}"):
                for column in columns:
                    self.assertNotIn(password, str(row[column] or ""),
                                     f"plaintext password leaked into {table}.{column}")

    def test_no_hardcoded_secret_in_phase_2_source(self):
        """Flag any assignment of a string literal to a secret-ish name.

        `MIN_SECRET_KEY_LENGTH = 32` is a length constant, not a secret, so the
        pattern requires a quote on the right-hand side.
        """
        secret_assignment = re.compile(
            r"""\b(SECRET_KEY|API_KEY|PASSWORD|TOKEN|PRIVATE_KEY)\w*\s*[:=]\s*['"][^'"]+['"]""",
            re.IGNORECASE,
        )
        root = Path(__file__).resolve().parents[1] / "app"
        offenders = []
        for path in root.rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "os.environ" in stripped or "_require(" in stripped:
                    continue
                if secret_assignment.search(stripped):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
        self.assertEqual(offenders, [], f"hard-coded secrets: {offenders}")

    def test_credit_money_columns_are_integers(self):
        expected = {
            "organizations": ["credit_limit_minor"],
            "credit_allocations": ["allocated_minor"],
            "credit_ledger_entries": ["amount_minor"],
            "credit_reservations": ["amount_minor"],
            "payment_intents": ["total_minor", "credit_minor", "cash_minor"],
            "payment_intent_items": ["unit_price_minor", "line_total_minor"],
            "orders": ["credit_minor", "cash_minor"],
        }
        for table, columns in expected.items():
            info = {r["name"]: (r["type"] or "").upper()
                    for r in self.db.query(f"PRAGMA table_info({table})")}
            for column in columns:
                self.assertIn(column, info, f"{table}.{column} missing")
                self.assertEqual(info[column], "INTEGER", f"{table}.{column} is {info[column]}")


if __name__ == "__main__":
    unittest.main()
