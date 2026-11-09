"""ورود مشترک vambi.ir ↔ 60online.ir: one-time code issue + exchange."""
from __future__ import annotations

import hashlib
import os
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from app.services import sso_service
from tests.base import AppTestCase

VAMBI = "https://vambi.ir"
STATE = "s" * 8 + "AbCd_-1234567890"


class SsoTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ, {"VAMBI_DOMAIN": "vambi.ir"})
        self._env.start()
        os.environ.pop("SSO_ALLOWED_ORIGINS", None)
        self.token, self.h = self.new_customer()

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def issue(self, origin=VAMBI, state=STATE, headers=None):
        return self.client.post("/api/v1/auth/sso/issue", json={"target_origin": origin, "state": state},
                                headers=self.h if headers is None else headers)

    def code(self, origin=VAMBI, state=STATE):
        r = self.issue(origin, state)
        self.assertEqual(r.status_code, 200, r.get_json())
        url = r.get_json()["redirect_url"]
        parts = urlsplit(url)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", f"{origin}/sso/callback")
        q = parse_qs(parts.query)
        self.assertEqual(q["state"], [state])
        return q["code"][0]

    def exchange(self, code, state=STATE, origin=VAMBI):
        headers = {"Origin": origin} if origin else {}
        return self.client.post("/api/v1/auth/sso/exchange", json={"code": code, "state": state}, headers=headers)

    def assertInvalid(self, r):
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "sso_invalid"), r.get_json())

    def test_issue_requires_auth(self):
        self.assertEqual(self.issue(headers={}).status_code, 401)

    def test_disallowed_origins(self):
        for bad in ("https://evil.example", "https://vambi.ir.evil.example", "https://vambi.ir/", "https://VAMBI.ir",
                    "https://vambi.ir/sso", "javascript:alert(1)", "//vambi.ir", "", None, "http://vambi.ir"):
            r = self.issue(origin=bad)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "sso_origin_not_allowed"), bad)
        self.assertEqual(self.issue(origin="https://www.vambi.ir").status_code, 200)

    def test_localhost_only_outside_production(self):
        self.assertTrue(sso_service.is_allowed_origin("http://localhost:3000", production=False))
        self.assertFalse(sso_service.is_allowed_origin("http://localhost:3000", production=True))
        with mock.patch.dict(os.environ, {"SSO_ALLOWED_ORIGINS": "http://vambi.test,https://a.example"}):
            self.assertEqual(sso_service.allowed_origins(production=True), {"https://a.example"})
            self.assertFalse(sso_service.is_allowed_origin(VAMBI, production=True))

    def test_bad_state_refused_at_issue(self):
        for bad in ("short", "x" * 200, "has space here!!!!", None):
            r = self.issue(state=bad)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "sso_invalid_state"), bad)

    def test_exchange_gives_working_token_and_code_is_single_use(self):
        code = self.code()
        r = self.exchange(code)
        self.assertEqual(r.status_code, 200, r.get_json())
        token = r.get_json()["access_token"]
        me = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        mine = self.client.get("/api/v1/auth/me", headers=self.h).get_json()["user"]["id"]
        self.assertEqual(me.get_json()["user"]["id"], mine)
        self.assertInvalid(self.exchange(code))  # reuse
        with self.db.read_transaction() as conn:
            actions = [r[0] for r in conn.execute("SELECT action FROM audit_logs WHERE actor_user_id = ?", (mine,))]
            meta = " ".join(r[0] for r in conn.execute("SELECT metadata_json FROM audit_logs WHERE action LIKE 'auth.sso%'"))
        self.assertIn("auth.sso_issued", actions)
        self.assertIn("auth.sso_exchanged", actions)
        self.assertNotIn(code, meta)

    def test_exchange_without_origin_header_is_accepted(self):
        self.assertEqual(self.exchange(self.code(), origin=None).status_code, 200)

    def test_expired_code_fails(self):
        code = self.code()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE sso_codes SET expires_at = '2000-01-01T00:00:00Z'")
        self.assertInvalid(self.exchange(code))

    def test_wrong_state_fails_and_burns_code(self):
        code = self.code()
        self.assertInvalid(self.exchange(code, state="Z" * 24))
        self.assertInvalid(self.exchange(code))

    def test_wrong_origin_fails(self):
        code = self.code()
        self.assertInvalid(self.exchange(code, origin="https://evil.example"))
        code = self.code(origin="https://www.vambi.ir")
        self.assertInvalid(self.exchange(code, origin=VAMBI))

    def test_unknown_or_malformed_code_fails_uniformly(self):
        self.assertInvalid(self.exchange("A" * 43))
        self.assertInvalid(self.exchange("bad code"))
        self.assertInvalid(self.exchange(None))

    def test_inactive_user(self):
        code = self.code()
        uid = self.client.get("/api/v1/auth/me", headers=self.h).get_json()["user"]["id"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
        self.assertInvalid(self.exchange(code))  # deactivated between issue and exchange
        self.assertEqual(self.issue().status_code, 401)  # and cannot issue any more

    def test_code_stored_hashed_only(self):
        code = self.code()
        with self.db.read_transaction() as conn:
            row = conn.execute("SELECT * FROM sso_codes").fetchone()
        values = " ".join(str(v) for v in tuple(row))
        self.assertNotIn(code, values)
        self.assertNotIn(STATE, values)
        self.assertEqual(row["code_hash"], hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(row["target_origin"], VAMBI)
        self.assertIsNone(row["used_at"])

    def test_issue_rate_limited_per_user(self):
        for _ in range(sso_service.ISSUE_PER_USER_10_MIN):
            self.assertEqual(self.issue().status_code, 200)
        r = self.issue()
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (429, "sso_rate_limited"))
