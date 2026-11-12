"""Vambi pricing entitlements: per-membership role/entitlements and the server-to-server refresh.

Synthetic test fixtures only (organizations/users labeled «آزمون»), inside the isolated test DB.
"""
from __future__ import annotations

import os
from unittest import mock

from app.services import vambi_feed_service as feed
from tests.base import AppTestCase

TOKEN = "e" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = "/api/v1/sso/vambi/entitlements"


class VambiEntitlementsTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ, {"VAMBI_FEED_TOKEN": TOKEN, "VAMBI_ENTITLEMENTS_RATE_PER_MIN": "1000"})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.org = self.create_organization(name="سازمان آزمون مزایا")["id"]
        self.shop = self.create_organization(name="فروشگاه آزمون")["id"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organizations SET buyer_kind='retailer' WHERE id=?", (self.shop,))
        self.uid = self.user()
        from app.core.deps import get_settings
        with self.app.app_context():
            self.secret = get_settings().secret_key
        self.ref = feed.user_ref(self.uid, self.secret)

    def user(self) -> int:
        _, _, r = self.register()
        return r.get_json()["user"]["id"]

    def member(self, org, uid, role="employee", procurement_role=None, status="active") -> int:
        with self.db.write_transaction() as conn:
            return conn.execute("INSERT INTO organization_memberships (organization_id, user_id, role, procurement_role, status)"
                                " VALUES (?,?,?,?,?)", (org, uid, role, procurement_role, status)).lastrowid

    def refresh(self, ref="__self__", headers=None):
        return self.client.post(URL, json={"user_ref": self.ref if ref == "__self__" else ref},
                                headers=AUTH if headers is None else headers)

    def ctx(self, ref="__self__"):
        r = self.refresh(ref)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()["pricing_context"]

    # ── roles and entitlements ──
    def test_roles_are_faithful(self):
        cases = {("employee", None): dict(is_admin=False, can_buy_for_org=False, can_approve_purchases=False, can_manage_finance=False),
                 ("organization_admin", None): dict(is_admin=True, can_buy_for_org=True, can_approve_purchases=True, can_manage_finance=True),
                 ("procurement_agent", None): dict(is_admin=False, can_buy_for_org=True, can_approve_purchases=False, can_manage_finance=False),
                 ("organization_finance", None): dict(is_admin=False, can_buy_for_org=False, can_approve_purchases=False, can_manage_finance=True),
                 ("employee", "approver"): dict(is_admin=False, can_buy_for_org=False, can_approve_purchases=True, can_manage_finance=False),
                 ("employee", "procurement_officer"): dict(is_admin=False, can_buy_for_org=True, can_approve_purchases=False, can_manage_finance=False)}
        for (role, proc), expected in cases.items():
            uid = self.user()
            self.member(self.org, uid, role, proc)
            [m] = self.ctx(feed.user_ref(uid, self.secret))["memberships"]
            self.assertEqual((m["role"], m["procurement_role"]), (role, proc))
            self.assertEqual({k: m[k] for k in expected}, expected, (role, proc))

    def test_pack_beneficiary_welfare_and_credit(self):
        mid = self.member(self.org, self.uid)
        [m] = self.ctx()["memberships"]
        self.assertEqual((m["pack_beneficiary"], m["welfare_plan_active"], m["credit_allocation_active"]), (False, False, False))
        admin = self.user()
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO benefit_programs (organization_id, title, mode, status, created_by_user_id) "
                         "VALUES (?, 'برنامهٔ آزمون نوروز', 'pack_choice', 'open', ?)", (self.org, admin))
            conn.execute("INSERT INTO credit_allocations (reference, organization_id, membership_id, user_id, allocated_minor,"
                         " valid_from, status, created_by_user_id) VALUES ('TEST-ALLOC-1', ?, ?, ?, 1000, '2020-01-01 00:00:00',"
                         " 'active', ?)", (self.org, mid, self.uid, admin))
            conn.execute("INSERT INTO welfare_plans (reference, organization_id, title, plan_type, per_employee_cap_minor,"
                         " starts_at, expires_at, all_members, status, idempotency_key) VALUES ('TEST-WP-1', ?, 'طرح آزمون',"
                         " 'free', 1000, '2020-01-01T00:00:00Z', '2999-01-01T00:00:00Z', 1, 'active', 'test-wp-1')", (self.org,))
        [m] = self.ctx()["memberships"]
        self.assertEqual((m["pack_beneficiary"], m["welfare_plan_active"], m["credit_allocation_active"]), (True, True, True))
        for k in m:  # minimal: no amounts, no personal data
            self.assertNotIn(k, ("allocated_minor", "employee_code", "department", "phone", "email", "national_id"))
        with self.db.write_transaction() as conn:  # program closed, allocation revoked → entitlements gone
            conn.execute("UPDATE benefit_programs SET status='closed'")
            conn.execute("UPDATE credit_allocations SET status='revoked'")
        [m] = self.ctx()["memberships"]
        self.assertEqual((m["pack_beneficiary"], m["credit_allocation_active"]), (False, False))

    def test_wholesale_for_retailer_account(self):
        self.member(self.shop, self.uid, "organization_admin")
        c = self.ctx()
        self.assertEqual((c["wholesale_eligible"], c["buyer_kinds"], c["org_ids"]), (True, ["retailer"], [self.shop]))

    # ── refresh: negatives ──
    def test_revoked_membership_and_suspended_org_reduce_context(self):
        mid = self.member(self.org, self.uid, "procurement_agent")
        self.member(self.shop, self.uid)
        self.assertEqual(self.ctx()["org_ids"], [self.org, self.shop])
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organization_memberships SET status='inactive' WHERE id=?", (mid,))
            conn.execute("UPDATE organizations SET status='suspended' WHERE id=?", (self.shop,))
        c = self.ctx()
        self.assertEqual((c["active"], c["org_ids"], c["memberships"], c["tiers"], c["wholesale_eligible"]),
                         (True, [], [], ["public"], False))

    def test_disabled_account_gets_public_only(self):
        self.member(self.org, self.uid, "organization_admin")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET is_active=0 WHERE id=?", (self.uid,))
        c = self.ctx()
        self.assertEqual((c["active"], c["memberships"], c["tiers"]), (False, [], ["public"]))

    def test_auth_and_bad_refs(self):
        self.assertEqual(self.refresh(headers={}).status_code, 401)
        self.assertEqual(self.refresh(headers={"Authorization": "Bearer " + "z" * 40}).status_code, 401)
        with mock.patch.dict(os.environ, {"VAMBI_FEED_TOKEN": ""}):
            self.assertEqual(self.refresh().status_code, 404)
        forged = f"u{self.uid}." + "0" * 32
        other = feed.user_ref(self.uid + 1, self.secret)  # valid mac for another (maybe nonexistent) user only
        for bad in (forged, "u1", "", None, 123, self.ref.upper(), f"u{self.uid + 10**6}." + other.split(".")[1],
                    feed.user_ref(10**9, self.secret), feed.user_ref(self.uid, "another-secret")):
            r = self.refresh(ref=bad)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (404, "unknown_user_ref"), bad)

    def test_rate_limited(self):
        with mock.patch.dict(os.environ, {"VAMBI_ENTITLEMENTS_RATE_PER_MIN": "2"}):
            self.assertEqual(self.refresh().status_code, 200)
            self.assertEqual(self.refresh().status_code, 200)
            self.assertEqual(self.refresh().status_code, 429)
