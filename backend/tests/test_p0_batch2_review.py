"""Independent review of P0 batch 2 (2026-11-21): regression tests for the confirmed findings.

Synthetic test accounts only (labelled *@example.com); no business data is created outside the
throwaway test database.
"""
from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from unittest import mock

from app.main import create_app
from app.services import auth_service, mfa_service
from tests.test_p0_batch2_security import _Helpers


class _MfaApp(_Helpers):
    def setUp(self):
        super().setUp()
        self.app = create_app(dataclasses.replace(self.settings, admin_mfa_enforce="all"), self.db)
        self.client = self.app.test_client()

    def _code(self, secret, offset=0):
        return mfa_service.totp_at(secret, int(time.time() // 30) + offset)

    def _enroll(self, headers):
        r = self.client.post("/api/v1/auth/mfa/enroll/start", headers=headers)
        self.assertEqual(r.status_code, 200, r.get_json())
        secret = r.get_json()["secret"]
        r = self.client.post("/api/v1/auth/mfa/enroll/confirm", headers=headers, json={"code": self._code(secret)})
        self.assertEqual(r.status_code, 200, r.get_json())
        return secret, {"Authorization": f"Bearer {r.get_json()['access_token']}"}


class PreMfaAdminHasNoAdminPowersTests(_MfaApp):
    """Finding R1: a password-only admin session must not reach admin-only data through endpoints that
    are open to every signed-in user but branch on users.role == 'admin' inside the view."""

    def _customer_request(self):
        _, cust = self.new_customer()
        r = self.client.post("/api/v1/requests", headers={**cust, "Idempotency-Key": uuid.uuid4().hex},
                             json={"kind": "support", "subject": "درخواست آزمایشی", "message": "متن آزمایشی"})
        self.assertIn(r.status_code, (200, 201), r.get_json())
        return r.get_json()["request"]["id"]

    def test_pre_mfa_admin_cannot_read_other_customers_request(self):
        rid = self._customer_request()
        _, email, password = self.user("admin")
        pre = self.hdr(email, password)
        r = self.client.get(f"/api/v1/requests/{rid}", headers=pre)
        self.assertEqual(r.status_code, 404, r.get_json())
        # After the second factor the same admin sees it (admin behaviour unchanged).
        _, stepped = self._enroll(pre)
        self.assertEqual(self.client.get(f"/api/v1/requests/{rid}", headers=stepped).status_code, 200)

    def test_pre_mfa_admin_gets_mfa_required_on_privileged_role_endpoints(self):
        _, email, password = self.user("admin")
        pre = self.hdr(email, password)
        # Shared admin/supplier endpoint: admin powers need the second factor.
        r = self.client.get("/api/v1/connectors", headers=pre)
        self.assertEqual(r.status_code, 403, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"], "mfa_required")

    def test_pre_mfa_admin_session_still_works_and_reports_super_admin(self):
        _, email, password = self.user("admin")
        pre = self.hdr(email, password)
        body = self.client.get("/api/v1/auth/me", headers=pre).get_json()
        self.assertEqual(body["user"]["role"], "admin")
        self.assertTrue(body["admin_access"]["super_admin"])
        self.assertTrue(body["admin_access"]["mfa_required"])
        self.assertFalse(body["admin_access"]["mfa_verified"])
        # Customer-level pages keep working before the second factor (no dead end, no logout).
        self.assertEqual(self.client.get("/api/v1/requests", headers=pre).status_code, 200)

    def test_mode_off_keeps_admin_behaviour(self):
        rid = self._customer_request()
        app = create_app(dataclasses.replace(self.settings, admin_mfa_enforce="off"), self.db)
        _, email, password = self.user("admin")
        h = self.hdr(email, password)
        self.assertEqual(app.test_client().get(f"/api/v1/requests/{rid}", headers=h).status_code, 200)


class MfaResetEndsSessionsTests(_MfaApp):
    """Finding R3: resetting a lost/stolen second factor must end that account's existing admin sessions."""

    def test_reset_revokes_target_tokens(self):
        _, a_email, a_pw = self.user("admin")
        _, a_stepped = self._enroll(self.hdr(a_email, a_pw))
        uid_b, b_email, b_pw = self.user("admin")
        _, b_stepped = self._enroll(self.hdr(b_email, b_pw))
        self.assertEqual(self.client.get("/api/v1/admin/access", headers=b_stepped).status_code, 200)
        time.sleep(1.05)  # the user-wide revocation compares whole seconds
        r = self.client.post(f"/api/v1/admin/users/{uid_b}/mfa/reset", headers=a_stepped,
                             json={"reason": "گوشی گم شده", "confirm_scope": True})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.client.get("/api/v1/admin/access", headers=b_stepped).status_code, 401)
        # The acting admin keeps their session.
        self.assertEqual(self.client.get("/api/v1/admin/access", headers=a_stepped).status_code, 200)


class LoginLockoutRaceTests(_Helpers):
    """Finding R2: the lock must also hold for password checks that were already in flight when it was set,
    so parallel guessing cannot get more than `threshold` answers per lock window."""

    def test_correct_password_refused_if_lock_set_during_verification(self):
        uid, email, password = self.user()
        real_verify = auth_service.verify_password

        def slow_verify(pw, hashed):
            ok = real_verify(pw, hashed)
            # Another request locks the account while this password check is running.
            with self.db.write_transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO login_lockouts (user_id, failed_count, lock_level, locked_until) "
                             "VALUES (?, 0, 1, ?)", (uid, int(time.time()) + 900))
            return ok

        with mock.patch.object(auth_service, "verify_password", side_effect=slow_verify):
            r = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(r.status_code, 429, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"], "account_locked")

    def test_parallel_wrong_passwords_lock_and_answers_are_bounded(self):
        uid, email, _ = self.user()
        results = []
        barrier = threading.Barrier(12)

        def attempt():
            c = self.app.test_client()
            barrier.wait()
            results.append(c.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"}).status_code)

        threads = [threading.Thread(target=attempt) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # At most threshold-1 plain "wrong password" answers; everything after the lock says locked.
        self.assertLessEqual(results.count(401), 4, results)
        self.assertEqual(results.count(401) + results.count(429), 12, results)


class CatalogStaffSupplierLoginTests(_Helpers):
    """Finding R4: linking a login to a supplier is super-admin only; supplier creation must not bypass it."""

    def test_catalog_staff_cannot_link_login_when_creating_supplier(self):
        uid, cat = self.staff("catalog")
        body = {"legal_name": "تأمین‌کنندهٔ آزمایشی", "display_name": "آزمایشی",
                "national_id": str(10_000_000_000 + uuid.uuid4().int % 1_000_000_000), "user_id": uid}
        r = self.client.post("/api/v1/admin/suppliers", headers=cat, json=body)
        self.assertEqual(r.status_code, 403, r.get_json())
        with self.db.read_transaction() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM suppliers WHERE user_id = ?", (uid,)).fetchone())
        # Without a login link catalog staff can still create the supplier record.
        body.pop("user_id")
        r = self.client.post("/api/v1/admin/suppliers", headers=cat, json=body)
        self.assertEqual(r.status_code, 201, r.get_json())

    def test_super_admin_can_still_link_login(self):
        uid, _, _ = self.user("supplier")
        r = self.client.post("/api/v1/admin/suppliers", headers=self.admin_headers(), json={
            "legal_name": "تأمین‌کنندهٔ آزمایشی ۲", "display_name": "آزمایشی ۲",
            "national_id": str(10_000_000_000 + uuid.uuid4().int % 1_000_000_000), "user_id": uid})
        self.assertEqual(r.status_code, 201, r.get_json())


class AdminRouteCoverageTests(_Helpers):
    """Every /admin URL rule is behind require_auth with an admin role (enumerated from the live url_map)."""

    def _roles(self, view):
        seen = set()
        while view is not None and id(view) not in seen:
            seen.add(id(view))
            for name, cell in zip(view.__code__.co_freevars, view.__closure__ or ()):
                if name == "allowed":
                    return tuple(cell.cell_contents)
            view = getattr(view, "__wrapped__", None)
        return None

    def test_every_admin_rule_requires_admin_role(self):
        missing = []
        for rule in self.app.url_map.iter_rules():
            if "/admin/" not in rule.rule and not rule.rule.endswith("/admin"):
                continue
            roles = self._roles(self.app.view_functions[rule.endpoint])
            if roles is None or "admin" not in roles:
                missing.append((rule.rule, roles))
        self.assertEqual(missing, [])
        self.assertGreater(len(list(r for r in self.app.url_map.iter_rules() if "/admin/" in r.rule)), 150)

    def test_admin_rules_reject_customers_without_running_the_view(self):
        _, cust = self.new_customer()
        bad = []
        for rule in self.app.url_map.iter_rules():
            if "/api/v1/admin/" not in rule.rule or rule.arguments:
                continue
            for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
                r = self.client.open(rule.rule, method=method, headers=cust, json={})
                if r.status_code != 403:
                    bad.append((method, rule.rule, r.status_code))
        self.assertEqual(bad, [])


class SettlementRoleRevokedMidRequestTests(_Helpers):
    """Finding R5: settlement create/complete re-check the caller's access inside the money transaction."""

    def test_finance_role_revoked_after_guard_blocks_completion(self):
        from app.core import deps
        from tests.test_settlement import _make_delivered_payable
        _, creator = self.staff("finance")
        supplier_id, entry = _make_delivered_payable(self)
        r = self.client.post("/api/v1/admin/settlement-batches", headers=creator, json={
            "supplier_id": supplier_id, "payable_entry_ids": [entry["id"]], "idempotency_key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 201, r.get_json())
        batch_id = r.get_json()["batch"]["id"]
        approver_id, approver = self.staff("finance")
        real_grant = deps._grant_staff_access

        def grant_then_revoke(wanted):
            ok = real_grant(wanted)
            with self.db.write_transaction() as conn:  # super-admin revokes the role meanwhile
                conn.execute("UPDATE staff_role_assignments SET revoked_at = 'now' WHERE user_id = ?", (approver_id,))
            return ok

        with mock.patch.object(deps, "_grant_staff_access", side_effect=grant_then_revoke):
            r = self.client.post(f"/api/v1/admin/settlement-batches/{batch_id}/complete", headers=approver,
                                 json={"payment_reference": "TXN-R5"})
        self.assertEqual(r.status_code, 403, r.get_json())
        with self.db.read_transaction() as conn:
            row = conn.execute("SELECT status FROM settlement_batches WHERE id = ?", (batch_id,)).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertIsNone(conn.execute("SELECT 1 FROM settlement_payments WHERE settlement_batch_id = ?",
                                           (batch_id,)).fetchone())
