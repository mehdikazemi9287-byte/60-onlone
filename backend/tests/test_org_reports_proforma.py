"""HR payroll file, organization spend export, and the price-held pro-forma guard."""
from __future__ import annotations

import csv
import io
import uuid

from tests.base import AppTestCase


def _rows(resp) -> list[list[str]]:
    return list(csv.reader(io.StringIO(resp.get_data(as_text=True).lstrip("﻿"))))


class OrgReportsTest(AppTestCase):
    def test_payroll_and_spend_exports(self):
        org, admin_h, _, emp = self.org_fixture(credit_minor=200_000_000)
        product = self.product()
        self.set_stock(product["id"], 10)
        self.add_to_cart(emp["headers"], product["id"], 1)
        r = self.checkout(emp["headers"])
        self.assertEqual(r.status_code, 201, r.get_json())
        import datetime as dt
        today = dt.date.today()
        q = f"from={today - dt.timedelta(days=30)}&to={today + dt.timedelta(days=1)}"
        pay = self.client.get(f"/api/v1/orgs/{org['id']}/reports/payroll.csv?{q}", headers=admin_h)
        self.assertEqual(pay.status_code, 200, pay.get_data(as_text=True))
        rows = _rows(pay)
        self.assertEqual(rows[0], ["employee_code", "full_name", "department", "credit_used_rial"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(int(rows[1][3]), r.get_json()["order"]["credit_minor"])
        spend = _rows(self.client.get(f"/api/v1/orgs/{org['id']}/reports/spend.csv?{q}", headers=admin_h))
        self.assertEqual(len(spend), 2)
        self.assertIn("credit", spend[1][9])
        # employees and outsiders cannot pull the files; bad ranges are refused
        self.assertEqual(self.client.get(f"/api/v1/orgs/{org['id']}/reports/payroll.csv?{q}",
                                         headers=emp["headers"]).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/orgs/{org['id']}/reports/spend.csv?from=2026-02-01&to=2026-01-01",
                                         headers=admin_h).status_code, 422)


class ProformaTest(AppTestCase):
    def test_proforma_blocks_a_dearer_checkout(self):
        _, h = self.new_customer()
        product = self.product()
        self.set_stock(product["id"], 10)
        self.add_to_cart(h, product["id"], 1)
        pf = self.client.post("/api/v1/me/proformas", headers=h)
        self.assertEqual(pf.status_code, 201, pf.get_json())
        pf = pf.get_json()
        self.assertEqual((len(pf["items"]), pf["expired"]), (1, False))
        self.assertEqual(self.client.get(f"/api/v1/me/proformas/{pf['number']}", headers=h).status_code, 200)
        _, other = self.new_customer()
        self.assertEqual(self.client.get(f"/api/v1/me/proformas/{pf['number']}", headers=other).status_code, 404)
        self.add_to_cart(h, product["id"], 1)   # cart grew after approval
        r = self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS,
                                                       "proforma_number": pf["number"]},
                             headers={**h, "Idempotency-Key": uuid.uuid4().hex})
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "proforma_price_changed"))
