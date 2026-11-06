"""تسویه با همکاران فروش: verified Sheba, minimum, batch, CSV, paid/failed."""
from __future__ import annotations

import os
from unittest import mock

from tests import test_affiliates as _ta

SHEBA = "IR820540102680020817909002"


class PayoutTest(_ta.AffiliateTest):
    def _ready(self, **kw):
        h, entry, fo = self._referred_delivery(**kw)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE affiliate_earnings SET available_at='2000-01-01T00:00:00Z'")
        return h

    def _amount(self):
        with self.db.read_transaction() as conn:
            r = conn.execute("SELECT platform_paid_minor+seller_paid_minor FROM affiliate_earnings").fetchone()
        return int(r[0])

    def test_full_cycle(self):
        h = self._ready(bonus_bps=500)
        amount = self._amount()
        adm = self.admin_headers()
        with mock.patch.dict(os.environ, {"AFFILIATE_MIN_PAYOUT_MINOR": "1"}):
            p = self.client.get("/api/v1/admin/affiliate-payouts/preview", headers=adm).get_json()
            self.assertEqual(p["waiting"][0]["reason"], "no_sheba")
            self.assertEqual(self.client.put("/api/v1/me/affiliate/sheba", json={"sheba": "IR12", "holder": "کارن"}, headers=h).status_code, 422)
            r = self.client.put("/api/v1/me/affiliate/sheba", json={"sheba": SHEBA, "holder": "کارن کاظمی"}, headers=h)
            self.assertEqual(r.status_code, 200, r.get_json())
            self.assertNotIn(SHEBA[4:-6], r.get_json()["sheba"])
            p = self.client.get("/api/v1/admin/affiliate-payouts/preview", headers=adm).get_json()
            self.assertEqual(p["waiting"][0]["reason"], "sheba_unverified")
            self.assertEqual(self.client.post("/api/v1/admin/affiliate-payouts/batches", headers=adm).status_code, 409)
            aid = p["unverified"][0]["affiliate_id"]
            self.client.post(f"/api/v1/admin/affiliates/{aid}/verify-sheba", headers=adm)
            b = self.client.post("/api/v1/admin/affiliate-payouts/batches", headers=adm)
            self.assertEqual(b.status_code, 201, b.get_json())
            batch = b.get_json()
            self.assertEqual((batch["payout_count"], batch["total_minor"]), (1, amount))
            mine = self.client.get("/api/v1/me/affiliate/payouts", headers=h).get_json()
            self.assertEqual((mine["in_payout_minor"], mine["available_minor"]), (amount, 0))
            # no second payout while one is open, and the Sheba is locked
            self.assertEqual(self.client.post("/api/v1/admin/affiliate-payouts/batches", headers=adm).status_code, 409)
            self.assertEqual(self.client.put("/api/v1/me/affiliate/sheba", json={"sheba": SHEBA, "holder": "x y"}, headers=h).status_code, 409)
            csv_r = self.client.get(f"/api/v1/admin/affiliate-payouts/batches/{batch['id']}/export.csv", headers=adm)
            self.assertIn(SHEBA, csv_r.get_data(as_text=True))
            self.assertEqual(self.client.get(f"/api/v1/admin/affiliate-payouts/batches/{batch['id']}/export.csv", headers=h).status_code, 403)
            pid = batch["payouts"][0]["id"]
            self.assertEqual(self.client.post(f"/api/v1/admin/affiliate-payouts/{pid}/paid", json={}, headers=adm).status_code, 422)
            ok = self.client.post(f"/api/v1/admin/affiliate-payouts/{pid}/paid", json={"bank_reference": "PAYA-778899"}, headers=adm)
            self.assertEqual(ok.status_code, 200, ok.get_json())
            self.assertEqual(self.client.post(f"/api/v1/admin/affiliate-payouts/{pid}/failed", json={}, headers=adm).status_code, 409)
            mine = self.client.get("/api/v1/me/affiliate/payouts", headers=h).get_json()
            self.assertEqual((mine["paid_minor"], mine["in_payout_minor"]), (amount, 0))
            self.assertEqual(self.client.get(f"/api/v1/admin/affiliate-payouts/batches/{batch['id']}", headers=adm).get_json()["status"], "closed")

    def test_failed_returns_to_balance_and_minimum(self):
        h = self._ready()
        amount = self._amount()
        adm = self.admin_headers()
        self.client.put("/api/v1/me/affiliate/sheba", json={"sheba": SHEBA, "holder": "کارن کاظمی"}, headers=h)
        aid = self.client.get("/api/v1/admin/affiliate-payouts/preview", headers=adm).get_json()["unverified"][0]["affiliate_id"]
        self.client.post(f"/api/v1/admin/affiliates/{aid}/verify-sheba", headers=adm)
        with mock.patch.dict(os.environ, {"AFFILIATE_MIN_PAYOUT_MINOR": str(amount + 1)}):
            p = self.client.get("/api/v1/admin/affiliate-payouts/preview", headers=adm).get_json()
            self.assertEqual(p["waiting"][0]["reason"], "below_minimum")
        with mock.patch.dict(os.environ, {"AFFILIATE_MIN_PAYOUT_MINOR": "1"}):
            pid = self.client.post("/api/v1/admin/affiliate-payouts/batches", headers=adm).get_json()["payouts"][0]["id"]
            self.client.post(f"/api/v1/admin/affiliate-payouts/{pid}/failed", json={"reason": "شبا اشتباه"}, headers=adm)
            mine = self.client.get("/api/v1/me/affiliate/payouts", headers=h).get_json()
            self.assertEqual((mine["available_minor"], mine["in_payout_minor"], mine["verified"]), (amount, 0, False))
            p = self.client.get("/api/v1/admin/affiliate-payouts/preview", headers=adm).get_json()
            self.assertEqual(p["waiting"][0]["reason"], "sheba_unverified")


for _name in [n for n in vars(_ta.AffiliateTest) if n.startswith("test_")]:
    setattr(PayoutTest, _name, None)  # inherited only for the helpers; don't run AffiliateTest's tests twice
