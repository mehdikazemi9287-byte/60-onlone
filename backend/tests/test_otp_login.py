"""ورود با کد پیامکی: normalization, limits, attempts, no enumeration, signup, phone linking."""
from __future__ import annotations

from app.adapters.sms import ConsoleSms
from app.services import otp_service as otp
from app.core.errors import ValidationError
from tests.base import AppTestCase


class OtpTest(AppTestCase):
    PHONE = "۰۹۱۲۱۲۳۴۵۶۷"
    N = "09121234567"

    def setUp(self):
        super().setUp()
        ConsoleSms.outbox.clear()

    def _age_codes(self, seconds=61):
        with self.db.write_transaction() as conn:  # move earlier challenges back in time (resend gap)
            conn.execute("UPDATE otp_challenges SET created_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)", (f"-{seconds} seconds",))

    def req(self, phone=None):
        return self.client.post("/api/v1/auth/otp/request", json={"phone": phone or self.PHONE})

    def ver(self, code, **kw):
        return self.client.post("/api/v1/auth/otp/verify", json={"phone": self.PHONE, "code": code, **kw})

    def test_normalize(self):
        for raw in ("+989121234567", "00989121234567", "989121234567", "9121234567", "0912 123 4567", self.PHONE):
            self.assertEqual(otp.normalize_phone(raw), self.N)
        for bad in ("02112345678", "0912123456", "abc", None):
            with self.assertRaises(ValidationError):
                otp.normalize_phone(bad)

    def test_signup_then_login_and_code_single_use(self):
        self.assertEqual(self.req().status_code, 200)
        code = ConsoleSms.outbox[self.N]
        with self.db.read_transaction() as conn:
            self.assertNotIn(code, conn.execute("SELECT code_hash FROM otp_challenges").fetchone()[0])
        r = self.ver(code)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "full_name_required"))
        r = self.ver(code, full_name="کارن کاظمی")
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "terms_required"))
        r = self.ver(code, full_name="کارن کاظمی", accept_terms=True)
        self.assertEqual(r.status_code, 201, r.get_json())
        token = r.get_json()["access_token"]
        me = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(self.ver(code).status_code, 401)  # used
        self._age_codes()
        self.req()
        r = self.ver(ConsoleSms.outbox[self.N])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["created"])

    def test_wrong_attempts_lock_the_code(self):
        self.req()
        code = ConsoleSms.outbox[self.N]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.ver(wrong, full_name="الف ب").status_code, 401)
        self.assertEqual(self.ver(code, full_name="الف ب").status_code, 401)  # locked after 5 tries

    def test_expired_and_superseded(self):
        self.req()
        first = ConsoleSms.outbox[self.N]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE otp_challenges SET expires_at='2000-01-01T00:00:00Z'")
        self.assertEqual(self.ver(first, full_name="الف ب").status_code, 401)
        self._age_codes()
        self.req()
        self._age_codes()
        old = ConsoleSms.outbox[self.N]
        self.req()
        if old != ConsoleSms.outbox[self.N]:
            self.assertEqual(self.ver(old, full_name="الف ب").status_code, 401)  # superseded by the newer code

    def test_rate_limits(self):
        self.assertEqual(self.req().status_code, 200)
        self.assertEqual(self.req().status_code, 429)  # resend gap
        for _ in range(4):
            self._age_codes()
            self.assertEqual(self.req().status_code, 200)
        self._age_codes()
        self.assertEqual(self.req().status_code, 429)  # 5 per hour
        for i in range(20):
            self.req(f"0935{i:07d}")
        self.assertEqual(self.req("09390000000").status_code, 429)  # per IP

    def test_no_enumeration_and_unverified_phone_not_trusted(self):
        _, h = self.new_customer()
        uid = self.client.get("/api/v1/auth/me", headers=h).get_json()["user"]["id"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET phone=? WHERE id=?", (self.N, uid))
        a = self.req().get_json()
        self.assertEqual(set(a), {"sent", "expires_in_seconds", "resend_in_seconds"})
        r = self.ver(ConsoleSms.outbox[self.N], full_name="کسی دیگر", accept_terms=True)
        self.assertEqual(r.status_code, 201)
        self.assertNotEqual(r.get_json()["user"]["id"], uid)  # free-text phone never grants access

    def test_link_phone_from_account(self):
        _, h = self.new_customer()
        uid = self.client.get("/api/v1/auth/me", headers=h).get_json()["user"]["id"]
        self.assertEqual(self.client.post("/api/v1/auth/phone/request", json={"phone": self.PHONE}).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/phone/request", json={"phone": self.PHONE}, headers=h).status_code, 200)
        code = ConsoleSms.outbox[self.N]
        self.assertEqual(self.ver(code, full_name="x y").status_code, 401)  # a link code can't be used to log in
        r = self.client.post("/api/v1/auth/phone/verify", json={"phone": self.PHONE, "code": code}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self._age_codes()
        self.req()
        r = self.ver(ConsoleSms.outbox[self.N])
        self.assertEqual(r.get_json()["user"]["id"], uid)
        _, h2 = self.new_customer()
        self._age_codes()
        ConsoleSms.outbox.clear()
        # someone else's number: same answer as any request (no enumeration) and no SMS goes to the owner
        self.assertEqual(self.client.post("/api/v1/auth/phone/request", json={"phone": self.PHONE}, headers=h2).status_code, 200)
        self.assertNotIn(self.N, ConsoleSms.outbox)

    def test_staff_cannot_login_by_sms(self):
        h = self.admin_headers()
        uid = self.client.get("/api/v1/auth/me", headers=h).get_json()["user"]["id"]
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET phone=?, phone_verified=? WHERE id=?", (self.N, self.N, uid))
        self.req()
        r = self.ver(ConsoleSms.outbox[self.N])
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "otp_not_allowed"))

    def test_production_refuses_console_sender(self):
        with self.db.write_transaction() as conn:
            with self.assertRaises(otp.SmsUnavailable):
                otp.request_code(conn, phone=self.N, secret="s" * 40, production=True)
