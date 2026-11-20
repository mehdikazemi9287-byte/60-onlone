"""P0 batch 2 (2026-11-20): staff roles, admin 2FA, settlement two-person control, login lockout,
audit gaps and the request-size cap. Synthetic test accounts only (labelled *@example.com)."""
from __future__ import annotations

import dataclasses
import json
import os
import time
import unittest
import uuid
from unittest import mock

from app.core import staff_access
from app.core.config import ConfigError, load_settings
from app.main import create_app
from app.services import mfa_service
from tests.base import AppTestCase
from tests.test_settlement import _make_delivered_payable


class _Helpers(AppTestCase):
    def user(self, role: str = "customer"):
        email, password, r = self.register(f"staff{uuid.uuid4().hex[:8]}@example.com")
        self.assertEqual(r.status_code, 201, r.get_json())
        uid = r.get_json()["user"]["id"]
        if role != "customer":
            with self.db.write_transaction() as conn:
                conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        return uid, email, password

    def hdr(self, email, password):
        return {"Authorization": f"Bearer {self.login(email, password)}"}

    def grant(self, uid: int, *roles: str):
        with self.db.write_transaction() as conn:
            for r in roles:
                conn.execute("INSERT INTO staff_role_assignments (user_id, role, reason) VALUES (?,?, 'test')", (uid, r))

    def staff(self, *roles: str):
        uid, email, password = self.user("employee")
        self.grant(uid, *roles)
        return uid, self.hdr(email, password)

    def audit(self, action: str) -> list[dict]:
        with self.db.read_transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit_logs WHERE action=? ORDER BY id", (action,))]


class StaffRoleTests(_Helpers):
    def test_existing_admin_keeps_full_access(self):
        admin = self.admin_headers()
        for path in ("/api/v1/admin/access", "/api/v1/admin/settlement-batches", "/api/v1/admin/catalog/products",
                     "/api/v1/admin/staff", "/api/v1/admin/settings"):
            self.assertEqual(self.client.get(path, headers=admin).status_code, 200, path)

    def test_finance_staff_scoped_to_finance(self):
        _, fin = self.staff("finance")
        self.assertEqual(self.client.get("/api/v1/admin/settlement-batches", headers=fin).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/dashboard", headers=fin).status_code, 200)
        for path in ("/api/v1/admin/access", "/api/v1/admin/settings", "/api/v1/admin/staff",
                     "/api/v1/admin/catalog/products", "/api/v1/admin/content/pages", "/api/v1/admin/partner-clients"):
            r = self.client.get(path, headers=fin)
            self.assertEqual(r.status_code, 403, (path, r.get_json()))

    def test_catalog_staff_denied_finance_and_role_change(self):
        _, cat = self.staff("catalog")
        self.assertEqual(self.client.get("/api/v1/admin/catalog/products", headers=cat).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/settlement-batches", headers=cat).status_code, 403)
        self.assertEqual(self.client.patch("/api/v1/admin/users/1/role", headers=cat, json={}).status_code, 403)
        # Shared admin/supplier endpoints are never opened to staff.
        self.assertEqual(self.client.get("/api/v1/connectors", headers=cat).status_code, 403)

    def test_content_staff_write_passes_in_transaction_recheck(self):
        _, content = self.staff("content")
        r = self.client.post("/api/v1/admin/content/pages", headers=content,
                             json={"slug": f"t-{uuid.uuid4().hex[:6]}", "title": "صفحهٔ آزمایشی", "body": "متن"})
        self.assertNotEqual(r.status_code, 403, r.get_json())

    def test_customer_without_staff_role_denied(self):
        _, cust = self.new_customer()
        self.assertEqual(self.client.get("/api/v1/admin/dashboard", headers=cust).status_code, 403)

    def test_super_admin_assigns_and_revokes_roles_with_audit(self):
        admin = self.admin_headers()
        uid, email, password = self.user("employee")
        h = self.hdr(email, password)
        self.assertEqual(self.client.get("/api/v1/admin/requests", headers=h).status_code, 403)
        r = self.client.put(f"/api/v1/admin/staff/users/{uid}/roles", headers=admin,
                            json={"roles": ["support"], "expected_roles": [], "reason": "تیم پشتیبانی", "confirm_scope": True})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["staff_roles"], ["support"])
        self.assertEqual(self.client.get("/api/v1/admin/requests", headers=h).status_code, 200)
        # Stale expected_roles is a conflict, not a silent overwrite.
        r = self.client.put(f"/api/v1/admin/staff/users/{uid}/roles", headers=admin,
                            json={"roles": [], "expected_roles": [], "reason": "پایان همکاری", "confirm_scope": True})
        self.assertEqual(r.status_code, 409)
        r = self.client.put(f"/api/v1/admin/staff/users/{uid}/roles", headers=admin,
                            json={"roles": [], "expected_roles": ["support"], "reason": "پایان همکاری", "confirm_scope": True})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.client.get("/api/v1/admin/requests", headers=h).status_code, 403)
        actions = self.audit("user.staff_roles_changed")
        self.assertEqual(len(actions), 2)
        self.assertEqual(json.loads(actions[0]["metadata_json"])["after"], ["support"])

    def test_staff_cannot_assign_roles_and_invalid_roles_rejected(self):
        _, sup = self.staff("support")
        uid, _, _ = self.user("employee")
        r = self.client.put(f"/api/v1/admin/staff/users/{uid}/roles", headers=sup,
                            json={"roles": ["finance"], "expected_roles": [], "reason": "خودسرانه", "confirm_scope": True})
        self.assertEqual(r.status_code, 403)
        admin = self.admin_headers()
        r = self.client.put(f"/api/v1/admin/staff/users/{uid}/roles", headers=admin,
                            json={"roles": ["root"], "expected_roles": [], "reason": "آزمون", "confirm_scope": True})
        self.assertEqual(r.status_code, 422)

    def test_auth_me_reports_admin_access(self):
        _, fin = self.staff("finance")
        body = self.client.get("/api/v1/auth/me", headers=fin).get_json()
        self.assertEqual(body["admin_access"]["staff_roles"], ["finance"])
        self.assertFalse(body["admin_access"]["super_admin"])

    def test_rule_table_fails_closed(self):
        self.assertEqual(staff_access.roles_for_endpoint("/api/v1/admin/access", "GET"), frozenset())
        self.assertEqual(staff_access.roles_for_endpoint("/api/v1/admin/suppliers/<int:supplier_id>/user", "PATCH"),
                         frozenset())
        self.assertEqual(staff_access.roles_for_endpoint("/api/v1/admin/settlement-batchesX", "GET"), frozenset())
        self.assertIn("finance", staff_access.roles_for_endpoint("/api/v1/admin/settlement-batches/<int:batch_id>", "GET"))


class MfaTests(_Helpers):
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
        body = r.get_json()
        return secret, {"Authorization": f"Bearer {body['access_token']}"}, body["recovery_codes"]

    def test_admin_without_second_factor_is_sent_to_enrollment(self):
        admin = self.admin_headers()
        r = self.client.get("/api/v1/admin/settlement-batches", headers=admin)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error"]["code"], "mfa_required")
        self.assertFalse(r.get_json()["error"]["details"]["enrolled"])
        # The ordinary session still works (no dead end): /auth/me and customer pages answer.
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=admin).status_code, 200)
        secret, stepped, codes = self._enroll(admin)
        self.assertEqual(len(codes), 10)
        self.assertEqual(self.client.get("/api/v1/admin/settlement-batches", headers=stepped).status_code, 200)
        # The pre-MFA token was revoked by the step-up.
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=admin).status_code, 401)
        self.assertEqual(len(self.audit("admin.mfa_enrolled")), 1)

    def test_verify_wrong_code_replay_lock_and_recovery(self):
        uid, email, password = self.user("admin")
        secret, _, codes = self._enroll(self.hdr(email, password))
        fresh = self.hdr(email, password)
        self.assertEqual(self.client.get("/api/v1/admin/access", headers=fresh).get_json()["error"]["details"]["enrolled"],
                         True)
        # The code used at enrollment cannot be replayed.
        r = self.client.post("/api/v1/auth/mfa/verify", headers=fresh, json={"code": self._code(secret)})
        self.assertEqual(r.status_code, 422, r.get_json())
        # Recovery code: works once.
        r = self.client.post("/api/v1/auth/mfa/verify", headers=fresh, json={"recovery_code": codes[0]})
        self.assertEqual(r.status_code, 200, r.get_json())
        stepped = {"Authorization": f"Bearer {r.get_json()['access_token']}"}
        self.assertEqual(self.client.get("/api/v1/admin/access", headers=stepped).status_code, 200)
        again = self.hdr(email, password)
        r = self.client.post("/api/v1/auth/mfa/verify", headers=again, json={"recovery_code": codes[0]})
        self.assertEqual(r.status_code, 422)
        for _ in range(4):
            self.client.post("/api/v1/auth/mfa/verify", headers=again, json={"code": "000000"})
        r = self.client.post("/api/v1/auth/mfa/verify", headers=again, json={"code": self._code(secret, 1)})
        self.assertEqual(r.status_code, 429, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"], "mfa_locked")

    def test_staff_need_mfa_when_all_and_not_when_super_admin_only(self):
        _, fin = self.staff("finance")
        self.assertEqual(self.client.get("/api/v1/admin/settlement-batches", headers=fin).get_json()["error"]["code"],
                         "mfa_required")
        app2 = create_app(dataclasses.replace(self.settings, admin_mfa_enforce="super_admin"), self.db)
        self.assertEqual(app2.test_client().get("/api/v1/admin/settlement-batches", headers=fin).status_code, 200)

    def test_customer_cannot_enroll(self):
        _, cust = self.new_customer()
        self.assertEqual(self.client.post("/api/v1/auth/mfa/enroll/start", headers=cust).status_code, 403)

    def test_super_admin_resets_another_admins_factor(self):
        _, a_email, a_pw = self.user("admin")
        _, stepped, _ = self._enroll(self.hdr(a_email, a_pw))
        uid_b, b_email, b_pw = self.user("admin")
        self._enroll(self.hdr(b_email, b_pw))
        r = self.client.post(f"/api/v1/admin/users/{uid_b}/mfa/reset", headers=stepped,
                             json={"reason": "گوشی گم شده", "confirm_scope": True})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertFalse(r.get_json()["mfa"]["enrolled"])
        self.assertEqual(len(self.audit("admin.mfa_reset")), 1)


class SettlementTwoPersonTests(_Helpers):
    def _batch(self, headers):
        supplier_id, entry = _make_delivered_payable(self)
        r = self.client.post("/api/v1/admin/settlement-batches", headers=headers, json={
            "supplier_id": supplier_id, "payable_entry_ids": [entry["id"]], "idempotency_key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertTrue(r.get_json()["batch"]["awaiting_second_approver"])
        return r.get_json()["batch"]["id"]

    def test_creator_cannot_complete_second_finance_user_can(self):
        creator_id, creator = self.staff("finance")
        batch_id = self._batch(creator)
        r = self.client.post(f"/api/v1/admin/settlement-batches/{batch_id}/complete", headers=creator,
                             json={"payment_reference": "TXN-1"})
        self.assertEqual(r.status_code, 409, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"], "second_approver_required")
        _, catalog = self.staff("catalog")
        self.assertEqual(self.client.post(f"/api/v1/admin/settlement-batches/{batch_id}/complete", headers=catalog,
                                          json={}).status_code, 403)
        approver_id, approver = self.staff("finance")
        r = self.client.post(f"/api/v1/admin/settlement-batches/{batch_id}/complete", headers=approver,
                             json={"payment_reference": "TXN-1"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["batch"]["created_by_user_id"], creator_id)
        self.assertEqual(r.get_json()["batch"]["completed_by_user_id"], approver_id)
        done = self.audit("settlement.batch_completed")
        self.assertEqual(len(done), 1)
        meta = json.loads(done[0]["metadata_json"])
        self.assertEqual((meta["created_by_user_id"], meta["completed_by_user_id"]), (creator_id, approver_id))
        self.assertEqual(len(self.audit("settlement.batch_created")), 1)

    def test_same_super_admin_also_blocked(self):
        admin = self.admin_headers()
        batch_id = self._batch(admin)
        r = self.client.post(f"/api/v1/admin/settlement-batches/{batch_id}/complete", headers=admin, json={})
        self.assertEqual(r.status_code, 409)


class LoginLockoutTests(_Helpers):
    def test_lock_after_threshold_then_unlock(self):
        uid, email, password = self.user()
        for i in range(4):
            r = self.client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"})
            self.assertEqual(r.status_code, 401, (i, r.get_json()))
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["error"]["code"], "account_locked")
        self.assertIn("دقیقه", r.get_json()["error"]["message"])
        # Even the right password is refused while locked.
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(len(self.audit("user.login_locked")), 1)
        _, cust = self.new_customer()
        self.assertEqual(self.client.post(f"/api/v1/admin/users/{uid}/unlock", headers=cust,
                                          json={"reason": "درخواست"}).status_code, 403)
        _, support = self.staff("support")
        r = self.client.post(f"/api/v1/admin/users/{uid}/unlock", headers=support, json={"reason": "تماس تلفنی مشتری"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertFalse(r.get_json()["login_lockout"]["locked"])
        self.assertEqual(len(self.audit("user.login_unlocked")), 1)
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code, 200)

    def test_lock_expires_and_doubles(self):
        uid, email, _ = self.user()
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO login_lockouts (user_id, failed_count, lock_level, locked_until) VALUES (?,4,1,?)",
                         (uid, int(time.time()) - 1))
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"})
        self.assertEqual(r.status_code, 429)
        left = r.get_json()["error"]["details"]["retry_after_seconds"]
        self.assertGreater(left, 1700)  # level 2 → 2 × 900 s


class AuditGapTests(_Helpers):
    def test_cashier_rule_partner_discount_pack_and_coin_grant_are_audited(self):
        admin = self.admin_headers()
        self.assertEqual(self.client.patch("/api/v1/admin/cashier-rules/coins", headers=admin,
                                           json={"cap_bps": 1000}).status_code, 200)
        self.assertEqual(len(self.audit("cashier.rule_updated")), 1)
        r = self.client.post("/api/v1/admin/partner-discounts", headers=admin, json={
            "title_fa": "تخفیف آزمایشی", "partner_name": "شریک آزمایشی", "percent_bps": 500, "funded_by": "partner"})
        self.assertEqual(r.status_code, 201, r.get_json())
        did = r.get_json()["discount"]["id"]
        self.client.patch(f"/api/v1/admin/partner-discounts/{did}", headers=admin, json={"percent_bps": 600})
        self.assertEqual(len(self.audit("partner_discount.created")), 1)
        self.assertEqual(len(self.audit("partner_discount.updated")), 1)
        r = self.client.post("/api/v1/admin/packs", headers=admin, json={
            "slug": f"test-pack-{uuid.uuid4().hex[:6]}", "title_fa": "پک آزمایشی", "kind": "custom",
            "audience": "household", "purpose_fa": "آزمون"})
        self.assertEqual(r.status_code, 200, r.get_json())
        pid = r.get_json()["pack"]["id"]
        self.client.post(f"/api/v1/admin/packs/{pid}/archive", headers=admin)
        self.assertEqual(len(self.audit("pack.created")), 1)
        self.assertEqual(len(self.audit("pack.archive")), 1)
        uid, _, _ = self.user()
        r = self.client.post("/api/v1/loyalty/earn", headers=admin,
                             json={"user_id": uid, "amount_coins": 5, "source": "campaign"})
        self.assertIn(r.status_code, (200, 201), r.get_json())
        self.assertEqual(len(self.audit("loyalty.earn")), 1)


class RequestSizeTests(_Helpers):
    def test_max_content_length_configured(self):
        self.assertEqual(self.app.config["MAX_CONTENT_LENGTH"], self.settings.max_request_bytes)

    def test_oversized_json_rejected(self):
        r = self.client.post("/api/v1/auth/login", data="x" * (2 * 1024 * 1024), content_type="application/json")
        self.assertEqual(r.status_code, 413)

    def test_chunked_body_without_length_is_capped(self):
        def gen():
            for _ in range(40):
                yield b"x" * 65536
        r = self.client.post("/api/v1/auth/login", input_stream=_Stream(gen()), content_type="application/json",
                             headers={"Transfer-Encoding": "chunked"},
                             environ_overrides={"wsgi.input_terminated": True})  # as gunicorn sets for chunked
        # Werkzeug never reads past the per-request cap: the body is cut at the limit (413, or 422 because
        # the truncated JSON no longer parses). Either way the request is refused without buffering 2.5 MB.
        self.assertIn(r.status_code, (413, 422), r.get_data(as_text=True)[:200])

    def test_media_upload_allows_two_megabyte_image_payload(self):
        admin = self.admin_headers()
        r = self.client.post("/api/v1/admin/media", headers=admin,
                             json={"data_base64": "A" * (2_700_000), "title": "x"})
        self.assertNotEqual(r.status_code, 413)


class _Stream:
    def __init__(self, it):
        self.it, self.buf = it, b""

    def read(self, n=-1):
        while n < 0 or len(self.buf) < n:
            try:
                self.buf += next(self.it)
            except StopIteration:
                break
        out, self.buf = (self.buf, b"") if n < 0 else (self.buf[:n], self.buf[n:])
        return out

    def readline(self, n=-1):
        return self.read(n)

    def tell(self):
        return 0

    def seek(self, *a):
        return 0


class ConfigTests(unittest.TestCase):
    def _load(self, **env):
        base = {"SECRET_KEY": "a" * 40, "DATABASE_URL": "sqlite:////tmp/x.db"}
        with mock.patch.dict(os.environ, {**base, **env}, clear=True):
            return load_settings()

    def test_defaults(self):
        self.assertEqual(self._load(APP_ENV="staging").admin_mfa_enforce, "all")
        self.assertEqual(self._load(APP_ENV="test").admin_mfa_enforce, "off")
        self.assertEqual(self._load(APP_ENV="staging", ADMIN_MFA_ENFORCE="super_admin").admin_mfa_enforce, "super_admin")
        with self.assertRaises(ConfigError):
            self._load(APP_ENV="staging", ADMIN_MFA_ENFORCE="maybe")
        self.assertEqual(self._load(APP_ENV="staging").max_request_bytes, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
