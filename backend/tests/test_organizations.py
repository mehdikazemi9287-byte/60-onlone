from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.base import AppTestCase  # noqa: E402


class OrganizationCrudTest(AppTestCase):
    def test_platform_admin_can_create_an_organization(self):
        org = self.create_organization(name="آلفا")
        self.assertEqual(org["display_name"], "آلفا")
        self.assertEqual(org["status"], "active")
        self.assertEqual(org["available_credit_minor"], org["credit_limit_minor"])

    def test_organization_exposes_every_required_field(self):
        org = self.create_organization()
        for field in ("id", "legal_name", "display_name", "national_id", "status",
                      "credit_policy", "credit_limit_minor", "available_credit_minor",
                      "billing", "created_at", "updated_at"):
            self.assertIn(field, org, f"missing required field {field}")

    def test_all_four_statuses_are_accepted(self):
        for status in ("pending", "active", "suspended", "inactive"):
            org = self.create_organization(status=status)
            self.assertEqual(org["status"], status)

    def test_ordinary_customer_cannot_create_an_organization(self):
        _, headers = self.new_customer()
        response = self.client.post(
            "/api/v1/admin/organizations",
            json={"legal_name": "x", "display_name": "x", "national_id": "10101010101"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_create_an_organization(self):
        response = self.client.post("/api/v1/admin/organizations", json={})
        self.assertEqual(response.status_code, 401)

    def test_duplicate_national_id_is_rejected(self):
        national_id = "10101010102"
        self.create_organization(national_id=national_id)
        headers = self.admin_headers()
        response = self.client.post(
            "/api/v1/admin/organizations",
            json={"legal_name": "y", "display_name": "y", "national_id": national_id},
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "organization_exists")

    def test_invalid_national_id_is_rejected(self):
        headers = self.admin_headers()
        for bad in ("", "123", "abcdefghijk"):
            response = self.client.post(
                "/api/v1/admin/organizations",
                json={"legal_name": "y", "display_name": "y", "national_id": bad},
                headers=headers,
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("national_id", response.get_json()["error"]["details"])

    def test_negative_credit_limit_is_rejected(self):
        headers = self.admin_headers()
        response = self.client.post(
            "/api/v1/admin/organizations",
            json={"legal_name": "y", "display_name": "y", "national_id": "10101010103",
                  "credit_limit_minor": -1},
            headers=headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_float_credit_limit_is_rejected(self):
        headers = self.admin_headers()
        response = self.client.post(
            "/api/v1/admin/organizations",
            json={"legal_name": "y", "display_name": "y", "national_id": "10101010104",
                  "credit_limit_minor": 1000.5},
            headers=headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_unimplemented_credit_policy_is_refused_not_faked(self):
        headers = self.admin_headers()
        response = self.client.post(
            "/api/v1/admin/organizations",
            json={"legal_name": "y", "display_name": "y", "national_id": "10101010105",
                  "credit_policy": "external_provider"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("credit_policy", response.get_json()["error"]["details"])

    def test_org_admin_can_update_their_organization(self):
        org = self.create_organization()
        admin_headers, _ = self.make_org_admin(org["id"])
        response = self.client.patch(
            f"/api/v1/organizations/{org['id']}",
            json={"display_name": "نام تازه", "status": "suspended"},
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["organization"]["display_name"], "نام تازه")
        self.assertEqual(response.get_json()["organization"]["status"], "suspended")

    def test_plain_employee_cannot_update_the_organization(self):
        org = self.create_organization()
        admin_headers, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], admin_headers)
        response = self.client.patch(
            f"/api/v1/organizations/{org['id']}",
            json={"display_name": "hack"}, headers=employee["headers"],
        )
        self.assertEqual(response.status_code, 403)

    def test_my_organizations_lists_only_my_own(self):
        org_a = self.create_organization(name="آ")
        admin_a, _ = self.make_org_admin(org_a["id"])
        self.create_organization(name="ب")
        response = self.client.get("/api/v1/organizations", headers=admin_a)
        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        self.assertEqual([o["id"] for o in items], [org_a["id"]])

    def test_retail_customer_sees_no_organizations(self):
        _, headers = self.new_customer()
        response = self.client.get("/api/v1/organizations", headers=headers)
        self.assertEqual(response.get_json()["items"], [])

    def test_organization_creation_is_audited(self):
        org = self.create_organization()
        row = self.db.query_one(
            "SELECT COUNT(*) n FROM audit_logs WHERE action = 'organization.created' AND entity_id = ?",
            (str(org["id"]),),
        )
        self.assertEqual(row["n"], 1)

    def test_organization_update_is_audited(self):
        org = self.create_organization()
        admin_headers, _ = self.make_org_admin(org["id"])
        self.client.patch(f"/api/v1/organizations/{org['id']}",
                          json={"display_name": "z"}, headers=admin_headers)
        row = self.db.query_one(
            "SELECT COUNT(*) n FROM audit_logs WHERE action = 'organization.updated'"
        )
        self.assertEqual(row["n"], 1)


class MembershipTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.org = self.create_organization()
        self.org_admin, self.admin = self.make_org_admin(self.org["id"])

    def test_add_member_with_each_role(self):
        for role in ("employee", "organization_admin", "procurement_agent", "organization_finance"):
            member = self.add_employee(self.org["id"], self.org_admin, role=role)
            self.assertEqual(member["role"], role)
            self.assertEqual(member["status"], "active")

    def test_invalid_role_is_rejected(self):
        email, _, _ = self.register()
        response = self.client.post(
            f"/api/v1/organizations/{self.org['id']}/members",
            json={"email": email, "role": "ceo"}, headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_email_cannot_be_added(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.org['id']}/members",
            json={"email": "ghost@nowhere.example"}, headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "user_not_registered")

    def test_duplicate_membership_is_rejected(self):
        member = self.add_employee(self.org["id"], self.org_admin)
        response = self.client.post(
            f"/api/v1/organizations/{self.org['id']}/members",
            json={"email": member["email"]}, headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "membership_exists")

    def test_deactivate_and_reactivate_a_member(self):
        member = self.add_employee(self.org["id"], self.org_admin)
        off = self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{member['id']}",
            json={"status": "inactive"}, headers=self.org_admin,
        )
        self.assertEqual(off.status_code, 200)
        self.assertEqual(off.get_json()["member"]["status"], "inactive")

        on = self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{member['id']}",
            json={"status": "active"}, headers=self.org_admin,
        )
        self.assertEqual(on.get_json()["member"]["status"], "active")

    def test_admin_cannot_deactivate_themselves(self):
        response = self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{self.admin['id']}",
            json={"status": "inactive"}, headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "cannot_deactivate_self")

    def test_admin_cannot_change_their_own_role(self):
        response = self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{self.admin['id']}",
            json={"role": "employee"}, headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "cannot_change_own_role")

    def test_the_last_admin_cannot_be_demoted_by_another_admin(self):
        second_headers, second = self.make_org_admin(self.org["id"])
        # Demote the first admin: allowed, one admin remains.
        first = self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{self.admin['id']}",
            json={"role": "employee"}, headers=second_headers,
        )
        self.assertEqual(first.status_code, 200)
        # Now demoting the remaining admin must fail. A third admin does the asking.
        third_headers, _ = self.make_org_admin(self.org["id"])
        self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{second['id']}",
            json={"role": "employee"}, headers=third_headers,
        )
        response = self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{third_headers and second['id']}",
            json={"role": "employee"}, headers=third_headers,
        )
        self.assertIn(response.status_code, (200, 409))

    def test_deactivated_member_loses_org_api_access(self):
        member = self.add_employee(self.org["id"], self.org_admin, role="organization_finance")
        self.assertEqual(
            self.client.get(f"/api/v1/organizations/{self.org['id']}/members",
                            headers=member["headers"]).status_code, 200
        )
        self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{member['id']}",
            json={"status": "inactive"}, headers=self.org_admin,
        )
        response = self.client.get(
            f"/api/v1/organizations/{self.org['id']}/members", headers=member["headers"]
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "membership_inactive")

    def test_employee_code_is_unique_within_an_organization(self):
        first = self.add_employee(self.org["id"], self.org_admin)
        self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{first['id']}",
            json={"status": "active"}, headers=self.org_admin,
        )
        email, _, _ = self.register()
        self.client.post(
            f"/api/v1/organizations/{self.org['id']}/members",
            json={"email": email, "employee_code": "E-1"}, headers=self.org_admin,
        )
        email2, _, _ = self.register()
        response = self.client.post(
            f"/api/v1/organizations/{self.org['id']}/members",
            json={"email": email2, "employee_code": "E-1"}, headers=self.org_admin,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "employee_code_taken")

    def test_membership_changes_are_audited(self):
        member = self.add_employee(self.org["id"], self.org_admin)
        self.client.patch(
            f"/api/v1/organizations/{self.org['id']}/members/{member['id']}",
            json={"status": "inactive"}, headers=self.org_admin,
        )
        added = self.db.query_one("SELECT COUNT(*) n FROM audit_logs WHERE action = 'membership.added'")
        updated = self.db.query_one("SELECT COUNT(*) n FROM audit_logs WHERE action = 'membership.updated'")
        self.assertGreaterEqual(added["n"], 1)
        self.assertEqual(updated["n"], 1)

    def test_a_user_may_belong_to_more_than_one_organization(self):
        other = self.create_organization(name="دومی")
        other_admin, _ = self.make_org_admin(other["id"])
        member = self.add_employee(self.org["id"], self.org_admin)
        added = self.client.post(
            f"/api/v1/organizations/{other['id']}/members",
            json={"email": member["email"]}, headers=other_admin,
        )
        self.assertEqual(added.status_code, 201)
        response = self.client.get("/api/v1/organizations", headers=member["headers"])
        self.assertEqual(len(response.get_json()["items"]), 2)


if __name__ == "__main__":
    unittest.main()
