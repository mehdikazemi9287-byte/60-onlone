"""Phase 4 — credit contracts/statements, welfare wallet, installments, debt sale, seller advances, group API."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from app.api.v1 import credit_platform
from app.main import create_app
from app.services import credit_contract_service as cc
from app.services import installment_service as ins
from app.services import ledger_service
from app.services import seller_advance_service as adv
from app.services import welfare_wallet_service as wf
from tests.base import AppTestCase


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class Phase4Base(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.settings, self.db)
        if "credit_platform" not in self.app.blueprints:
            self.app.register_blueprint(credit_platform.bp)
        self.client = self.app.test_client()

    def capture(self, employee: dict, org_id: int, amount: int, at: str) -> None:
        with self.db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO credit_ledger_entries (reference, allocation_id, organization_id, user_id, entry_type, "
                "amount_minor, created_at) VALUES (?,?,?,?, 'capture', ?, ?)",
                (f"T-{uuid.uuid4().hex[:8]}", employee["allocation"]["id"], org_id, employee["user_id"], amount, at),
            )

    def make_order(self, user_id: int, total: int, suppliers: list[dict] | None = None) -> int:
        with self.db.write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO orders (order_number, user_id, status, subtotal_minor, shipping_fee_minor, tax_minor, "
                "total_minor, recipient_name, recipient_phone, shipping_province, shipping_city, shipping_line1) "
                "VALUES (?,?, 'paid', ?, 0, 0, ?, 'x', '0912', 'تهران', 'تهران', 'x')",
                (f"O-{uuid.uuid4().hex[:8]}", user_id, total, total),
            )
            for sup in suppliers or []:  # the order's own lines name its seller(s)
                conn.execute("INSERT INTO fulfillment_orders (order_id, supplier_id, supplier_location_id) "
                             "VALUES (?,?,?)", (cur.lastrowid, sup["supplier_id"], sup["location_id"]))
            return int(cur.lastrowid)


class CreditContractTests(Phase4Base):
    def _contract(self):
        org, admin_headers, admin, employee = self.org_fixture(credit_minor=500_000_000)
        with self.db.write_transaction() as conn:
            _, contract = cc.create_contract(conn, organization_id=org["id"], idempotency_key="k1", actor_user_id=None,
                                             payload={"limit_minor": 1_000_000_000, "starts_at": "2026-11-01 00:00:00",
                                                      "funder_type": "institution", "funder_name": "صندوق رفاه"})
        return org, employee, contract

    def test_weekly_statement_math_and_boundaries(self):
        org, emp, contract = self._contract()
        self.capture(emp, org["id"], 30_000_000, "2026-11-03 10:00:00")
        self.capture(emp, org["id"], 20_000_000, "2026-11-06 20:00:00")   # before Sat 00:00 Tehran
        self.capture(emp, org["id"], 7_000_000, "2026-11-06 21:00:00")    # after → next week
        with self.db.write_transaction() as conn:
            r = cc.run_weekly_statements(conn, utc(2026, 11, 14, 12))
            again = cc.run_weekly_statements(conn, utc(2026, 11, 14, 12))
            cc.record_payment(conn, contract["id"], amount_minor=10_000_000, idempotency_key="p0",
                              actor_user_id=None, received_at="2026-11-15 08:00:00", now=utc(2026, 11, 15, 8))
            sts = sorted(cc.list_statements(conn, org["id"]), key=lambda s: s["period_start"])
        self.assertEqual(r["statements_issued"], 2)
        self.assertEqual(again["statements_issued"], 0)
        s1, s2 = sts
        self.assertEqual((s1["period_end"], s1["usage_minor"], s1["closing_minor"]),
                         ("2026-11-06 20:30:00", 50_000_000, 50_000_000))
        self.assertEqual(s1["due_at"], "2026-11-13 20:30:00")
        self.assertEqual((s2["opening_minor"], s2["usage_minor"], s2["closing_minor"]), (50_000_000, 7_000_000, 57_000_000))

    def test_overdue_freezes_reservations_and_payment_unfreezes(self):
        org, emp, contract = self._contract()
        self.capture(emp, org["id"], 40_000_000, "2026-11-03 10:00:00")
        with self.db.write_transaction() as conn:
            cc.run_weekly_statements(conn, utc(2026, 11, 7))
            self.assertEqual(cc.enforce_overdue(conn, utc(2026, 11, 10))["frozen"], 0)
            self.assertEqual(cc.enforce_overdue(conn, utc(2026, 11, 14))["frozen"], 1)
        self.assertEqual(self.db.query_one("SELECT status FROM credit_contracts WHERE id=?", (contract["id"],))["status"],
                         "frozen")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.write_transaction() as conn:
                conn.execute("INSERT INTO credit_reservations (reference, allocation_id, organization_id, user_id, "
                             "payment_intent_id, amount_minor) VALUES ('R1', ?, ?, ?, 999, 1000)",
                             (emp["allocation"]["id"], org["id"], emp["user_id"]))
        with self.db.write_transaction() as conn:
            cc.record_payment(conn, contract["id"], amount_minor=39_000_000, idempotency_key="p1",
                              actor_user_id=None, now=utc(2026, 11, 15))
            self.assertEqual(cc.get_contract(conn, contract["id"])["status"], "frozen")
            created, _ = cc.record_payment(conn, contract["id"], amount_minor=1_000_000, idempotency_key="p2",
                                           actor_user_id=None, now=utc(2026, 11, 15))
            replay, _ = cc.record_payment(conn, contract["id"], amount_minor=1_000_000, idempotency_key="p2",
                                          actor_user_id=None, now=utc(2026, 11, 15))
            c = cc.get_contract(conn, contract["id"])
            st = cc.list_statements(conn, org["id"])[0]
        self.assertTrue(created)
        self.assertFalse(replay)
        self.assertEqual((c["status"], st["status"], c["outstanding_minor"]), ("active", "paid", 0))

    def test_statement_amounts_are_immutable_and_api(self):
        org, emp, contract = self._contract()
        with self.db.write_transaction() as conn:
            cc.run_weekly_statements(conn, utc(2026, 11, 7))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.write_transaction() as conn:
                conn.execute("UPDATE credit_statements SET usage_minor = 1")
        admin = self.admin_headers()
        r = self.client.get(f"/api/v1/orgs/{org['id']}/statements", headers=admin)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(len(r.get_json()["statements"]), 1)
        r = self.client.post(f"/api/v1/admin/credit-contracts/{contract['id']}/freeze", headers=admin)
        self.assertEqual(r.get_json()["contract"]["freeze_reason"], "manual")
        _, outsider = self.new_customer()
        self.assertEqual(self.client.get(f"/api/v1/orgs/{org['id']}/statements", headers=outsider).status_code, 404)


class WelfareTests(Phase4Base):
    def test_caps_categories_products_and_expiry(self):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=0)
        with self.db.write_transaction() as conn:
            wf.create_plan(conn, organization_id=org["id"], idempotency_key="w1", actor_user_id=None,
                           now=utc(2026, 11, 1),
                           payload={"title": "بن غذا", "plan_type": "category", "category_slugs": ["food"],
                                    "per_employee_cap_minor": 1_000_000, "expires_at": "2026-12-01"})
            wf.create_plan(conn, organization_id=org["id"], idempotency_key="w2", actor_user_id=None,
                           now=utc(2026, 11, 1),
                           payload={"title": "کالای خاص", "plan_type": "product", "product_ids": [1],
                                    "per_employee_cap_minor": 300_000, "expires_at": "2026-11-20"})
            lines = [{"product_id": 1, "category_slug": "office", "line_total_minor": 500_000},
                     {"product_id": 2, "category_slug": "food", "line_total_minor": 1_500_000},
                     {"product_id": 3, "category_slug": "tools", "line_total_minor": 900_000}]
            r = wf.can_spend(conn, emp["id"], lines, now=utc(2026, 11, 10))
            self.assertEqual([l["allowed_minor"] for l in r["lines"]], [300_000, 1_000_000, 0])
            wf.record_spend(conn, membership_id=emp["id"], cart_lines=lines[:2], idempotency_key="o1",
                            now=utc(2026, 11, 10))
            again = wf.record_spend(conn, membership_id=emp["id"], cart_lines=lines[:2], idempotency_key="o1",
                                    now=utc(2026, 11, 10))
            self.assertFalse(again["created"])
            self.assertEqual(wf.can_spend(conn, emp["id"], lines, now=utc(2026, 11, 10))["total_allowed_minor"], 0)
            # product plan expired on 11-20; food plan still used up
            self.assertEqual(len(wf.eligible_plans(conn, emp["id"], now=utc(2026, 11, 25))), 1)
            self.assertEqual(wf.eligible_plans(conn, emp["id"], now=utc(2026, 12, 2)), [])

    def test_free_plan_member_restriction_and_api(self):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=0)
        other = self.add_employee(org["id"], admin_headers)
        r = self.client.post(f"/api/v1/orgs/{org['id']}/welfare-plans",
                             json={"title": "هدیه نوروز", "plan_type": "free", "per_employee_cap_minor": 2_000_000,
                                   "expires_at": "2099-01-01", "membership_ids": [emp["id"]]},
                             headers={**admin_headers, "Idempotency-Key": "wp1"})
        self.assertEqual(r.status_code, 201, r.get_json())
        body = {"lines": [{"product_id": 1, "category_slug": "x", "line_total_minor": 5_000_000}]}
        r = self.client.post(f"/api/v1/orgs/{org['id']}/welfare-plans/can-spend", json=body, headers=emp["headers"])
        self.assertEqual(r.get_json()["total_allowed_minor"], 2_000_000)
        r = self.client.post(f"/api/v1/orgs/{org['id']}/welfare-plans/can-spend", json=body, headers=other["headers"])
        self.assertEqual(r.get_json()["total_allowed_minor"], 0)


class InstallmentTests(Phase4Base):
    def test_schedule_sums_exactly_with_remainder_on_last(self):
        for months in (3, 6, 12, 18):
            s = ins.build_schedule(10_000_001, months, 300, 1000, utc(2026, 11, 1))
            self.assertEqual(sum(r["amount_minor"] for r in s["rows"]), s["total_payable_minor"])
            self.assertEqual(sum(r["principal_minor"] for r in s["rows"]), 10_000_001)
            self.assertEqual(s["fee_total_minor"], 9_000_001 * 300 * months // 10_000)
            monthly = [r for r in s["rows"] if r["seq"] >= 1]
            self.assertEqual(len(monthly), months)
            self.assertTrue(all(r["principal_minor"] == monthly[0]["principal_minor"] for r in monthly[:-1]))
            self.assertGreaterEqual(monthly[-1]["principal_minor"], monthly[0]["principal_minor"])

    def test_agreement_payments_late_and_debt_sale(self):
        sup = self.create_test_supplier()
        _, headers = self.new_customer()
        me = self.client.get("/api/v1/auth/me", headers=headers).get_json()
        user_id = (me.get("user") or me)["id"]
        order_id = self.make_order(user_id, 12_000_000, suppliers=[sup])
        plan = self.db.query_one("SELECT id FROM installment_plans WHERE code='m3'")
        r = self.client.post("/api/v1/installments", json={"order_id": order_id, "plan_id": plan["id"]},
                             headers={**headers, "Idempotency-Key": "i1"})
        self.assertEqual(r.status_code, 201, r.get_json())
        a = r.get_json()["installment"]
        # m3: down 25% = 3,000,000; financed 9,000,000; fee 3%×3 = 810,000
        self.assertEqual((a["down_payment_minor"], a["fee_total_minor"], a["total_payable_minor"]),
                         (3_000_000, 810_000, 12_810_000))
        self.assertEqual(a["remaining_minor"], 9_810_000)
        first = [s for s in a["schedules"] if s["seq"] == 1][0]
        with self.db.write_transaction() as conn:
            ins.record_payment(conn, agreement_id=a["id"], schedule_id=first["id"], amount_minor=first["amount_minor"],
                               idempotency_key="ip1", actor_user_id=None)
            self.assertEqual(ins.mark_late(conn, utc(2027, 3, 1)), 3)  # down payment + seq 2, 3
            q = ins.debt_sale_quote(conn, a["id"], 1500)
            created, sale = ins.sell_debt(conn, agreement_id=a["id"], discount_bps=1500, idempotency_key="ds1",
                                          actor_user_id=None)
            replay, _ = ins.sell_debt(conn, agreement_id=a["id"], discount_bps=1500, idempotency_key="ds1",
                                      actor_user_id=None)
            entries = ledger_service.entries_for_reference(conn, sale["ledger_reference"])
        remaining = 9_810_000 - first["amount_minor"]
        self.assertEqual(q["remaining_minor"], remaining)
        self.assertEqual(sale["discount_minor"], remaining * 1500 // 10_000)
        self.assertEqual(sale["purchase_price_minor"] + sale["discount_minor"], remaining)
        self.assertTrue(created)
        self.assertFalse(replay)
        self.assertEqual(sum(e["amount_minor"] for e in entries if e["direction"] == "debit"), remaining)
        d, c = self.trial_balance()
        self.assertEqual(d, c)
        got = self.client.get(f"/api/v1/installments/{a['id']}", headers=headers).get_json()["installment"]
        self.assertEqual(got["creditor_kind"], "platform")
        _, stranger = self.new_customer()
        self.assertEqual(self.client.get(f"/api/v1/installments/{a['id']}", headers=stranger).status_code, 404)


class SellerAdvanceTests(Phase4Base):
    def _payable(self, supplier_id: int, gross: int, commission: int | None, status: str = "unbatched") -> None:
        conn = self.db.connection
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.db.write_transaction() as c:
                c.execute("INSERT INTO supplier_payable_entries (supplier_id, fulfillment_order_id, gross_minor, "
                          "idempotency_key, status, commission_minor) VALUES (?,?,?,?,?,?)",
                          (supplier_id, 999_999, gross, uuid.uuid4().hex, status, commission))
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

    def test_cap_outstanding_and_recovery(self):
        sup = self.create_test_supplier()
        sid = sup["supplier_id"]
        self._payable(sid, 10_000_000, 900_000)
        self._payable(sid, 5_000_000, None)          # legacy: 10% default commission
        self._payable(sid, 8_000_000, 0, "settled")  # not eligible
        with self.db.write_transaction() as conn:
            e = adv.eligibility(conn, sid)
            self.assertEqual(e["eligible_net_minor"], 9_100_000 + 4_500_000)
            self.assertEqual(e["cap_minor"], 6_800_000)
        r = self.client.post("/api/v1/supplier/advances", json={"amount_minor": 7_000_000},
                             headers={**sup["headers"], "Idempotency-Key": "a0"})
        self.assertEqual(r.status_code, 409)
        r = self.client.post("/api/v1/supplier/advances", json={"amount_minor": 5_000_000},
                             headers={**sup["headers"], "Idempotency-Key": "a1"})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(r.get_json()["eligibility"]["available_minor"], 1_800_000)
        with self.db.write_transaction() as conn:
            self.assertEqual(adv.outstanding_advance(conn, sid), 5_000_000)
            self.assertEqual(adv.recover_from_settlement(conn, supplier_id=sid, available_minor=3_000_000,
                                                         settlement_reference="SB-1"), 3_000_000)
            self.assertEqual(adv.recover_from_settlement(conn, supplier_id=sid, available_minor=3_000_000,
                                                         settlement_reference="SB-1"), 3_000_000)
            self.assertEqual(adv.outstanding_advance(conn, sid), 2_000_000)
        d, c = self.trial_balance()
        self.assertEqual(d, c)


class GroupApiTests(Phase4Base):
    def test_group_summary_and_enroll(self):
        _, headers = self.new_customer()
        r = self.client.get("/api/v1/me/group", headers=headers)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIsNone(r.get_json()["group_account"])
        r = self.client.post("/api/v1/me/group", json={"businesses": ["karenseir", "giftasan"]}, headers=headers)
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(r.get_json()["group_account"]["linked_businesses"], ["60online", "karenseir", "giftasan"])
        body = self.client.get("/api/v1/me/group", headers=headers).get_json()
        self.assertEqual(body["coins"]["balance_coins"], 0)
        self.assertIn("credit", body)
        self.assertEqual(self.client.post("/api/v1/me/group", json={"businesses": ["nope"]},
                                          headers=headers).status_code, 422)
