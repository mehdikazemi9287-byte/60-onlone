"""شروع سازمانی: one-step onboarding, phone invitations claimed at OTP login, public applications."""
from __future__ import annotations

from app.adapters.sms import ConsoleSms
from tests.base import AppTestCase

URL = "/api/v1/admin/b2b/accounts"


def _payload(**kw):
    p = {"buyer_kind": "retailer", "legal_name": "فروشگاه نمونهٔ تهران", "national_id": "14001234567",
         "business_license_no": "LIC-9876", "city": "تهران",
         "contract": {"title": "قرارداد خرید عمده ۱۴۰۵", "reference": "QR-1405-01", "start_date": "2026-11-07"},
         "credit": {"limit_minor": 500_000_000, "due_days": 14},
         "invites": [{"phone": "09121112233", "role": "organization_admin"}, {"phone": "09121112244", "role": "procurement_agent"}]}
    p.update(kw)
    return p


class B2BTest(AppTestCase):
    def setUp(self):
        super().setUp()
        ConsoleSms.outbox.clear()
        self.h = {**self.admin_headers(), "Idempotency-Key": "onb-1"}

    def onboard(self, **kw):
        return self.client.post(URL, json=_payload(**kw), headers=self.h)

    def test_onboard_once_and_idempotent(self):
        r = self.onboard()
        self.assertEqual(r.status_code, 201, r.get_json())
        acc = r.get_json()["account"]
        self.assertEqual((acc["buyer_kind"], acc["status"], acc["pending_invites"]), ("retailer", "active", 2))
        self.assertEqual(acc["credit_contract"]["limit_minor"], 500_000_000)
        self.assertEqual(acc["credit_contract"]["due_days"], 14)
        self.assertEqual(acc["contract"]["contract_reference"], "QR-1405-01")
        again = self.onboard()
        self.assertEqual((again.status_code, again.get_json()["account"]["id"]), (200, acc["id"]))
        self.assertEqual(self.onboard(city="شیراز").status_code, 409)  # same key, different body
        dup = self.client.post(URL, json=_payload(), headers={**self.h, "Idempotency-Key": "onb-2"})
        self.assertEqual(dup.get_json()["error"]["code"], "organization_exists")
        with self.db.read_transaction() as conn:  # nothing half-written by the refused attempt
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM credit_contracts").fetchone()[0], 1)

    def test_validation(self):
        bad = [dict(business_license_no=None), dict(invites=[{"phone": "09121112233", "role": "employee"}]),
               dict(national_id="12"), dict(credit={"limit_minor": -1}), dict(buyer_kind="bank")]
        for i, kw in enumerate(bad):
            r = self.client.post(URL, json=_payload(**kw), headers={**self.h, "Idempotency-Key": f"bad-{i}"})
            self.assertIn(r.status_code, (409, 422), (kw, r.get_json()))
        _, cust = self.new_customer()
        self.assertEqual(self.client.post(URL, json=_payload(), headers={**cust, "Idempotency-Key": "x"}).status_code, 403)
        self.assertEqual(self.client.post(URL, json=_payload(), headers=self.admin_headers()).status_code, 422)  # no key

    def test_owner_claims_invite_with_otp_login(self):
        org_id = self.onboard().get_json()["account"]["id"]
        self.client.post("/api/v1/auth/otp/request", json={"phone": "09121112233"})
        r = self.client.post("/api/v1/auth/otp/verify", json={"phone": "09121112233", "code": ConsoleSms.outbox["09121112233"],
                                                                "full_name": "مدیر فروشگاه", "accept_terms": True})
        self.assertEqual(r.status_code, 201, r.get_json())
        h = {"Authorization": f"Bearer {r.get_json()['access_token']}"}
        # a recycled number must not drop its new owner into the org: membership waits for an explicit yes
        self.assertEqual(self.client.get(f"/api/v1/orgs/{org_id}/credit-contract", headers=h).status_code, 403)
        invs = self.client.get("/api/v1/me/org-invitations", headers=h).get_json()["items"]
        self.assertEqual(len(invs), 1, invs)
        ok = self.client.post(f"/api/v1/me/org-invitations/{invs[0]['membership_id']}/accept", headers=h)
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(self.client.post(f"/api/v1/me/org-invitations/{invs[0]['membership_id']}/accept", headers=h).status_code, 409)
        c = self.client.get(f"/api/v1/orgs/{org_id}/credit-contract", headers=h)
        self.assertEqual(c.status_code, 200, c.get_json())
        acc = self.client.get(f"{URL}/{org_id}", headers=self.admin_headers()).get_json()
        self.assertEqual((acc["active_members"], acc["pending_invites"]), (1, 1))
        # a person who already verified their number joins at once when invited
        inv = self.client.post(f"{URL}/{org_id}/invites", json={"phone": "09121112233", "role": "organization_finance"},
                               headers=self.admin_headers())
        self.assertEqual(inv.get_json()["status"], "claimed")
        self.assertNotIn("1112233", inv.get_json()["phone"])

    def test_applications(self):
        body = {"buyer_kind": "organization", "legal_name": "شرکت آزمایشی", "contact_name": "علی رضایی",
                "phone": "۰۹۱۲۳۳۳۴۴۵۵", "staff_band": "51-200", "monthly_band": "100m-500m"}
        r = self.client.post("/api/v1/b2b/applications", json=body)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "consent_required"))
        body["privacy_consent"] = True
        self.assertEqual(self.client.post("/api/v1/b2b/applications", json=body).status_code, 201)
        self.assertEqual(self.client.post("/api/v1/b2b/applications", json={**body, "staff_band": "x"}).status_code, 422)
        for _ in range(2):
            self.client.post("/api/v1/b2b/applications", json=body)
        self.assertEqual(self.client.post("/api/v1/b2b/applications", json=body).status_code, 429)
        items = self.client.get("/api/v1/admin/b2b/applications", headers=self.admin_headers()).get_json()["items"]
        self.assertEqual(len(items), 3)
        r = self.onboard(application_id=items[0]["id"])
        self.assertEqual(r.status_code, 201, r.get_json())
        rej = self.client.post(f"/api/v1/admin/b2b/applications/{items[1]['id']}/reject", json={"note": "تکراری"},
                               headers=self.admin_headers())
        self.assertEqual(rej.get_json()["status"], "rejected")
        self.assertEqual(self.client.post(f"/api/v1/admin/b2b/applications/{items[0]['id']}/reject", json={},
                                          headers=self.admin_headers()).status_code, 409)
        self.assertEqual(self.client.get("/api/v1/admin/b2b/applications").status_code, 401)
        import datetime as dt
        from app.services import b2b_service
        with self.db.write_transaction() as conn:  # retention: rejected leads go after 180 days, approved stay
            later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=181)
            self.assertEqual(b2b_service.purge_stale_applications(conn, now=later), 2)
            self.assertEqual(conn.execute("SELECT status FROM b2b_applications").fetchall()[0][0], "approved")
