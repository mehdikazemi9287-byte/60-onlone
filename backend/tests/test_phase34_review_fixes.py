"""Regression tests for the phase 3/4 review findings (approval bypass, conversion bounds, unpaid-cash expiry,
installment creditor derivation, net statement usage, advance-netted settlement, minor hardening)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app.core.errors import ConflictError, ValidationError
from app.services import brand_service, credit_service, settlement_service
from app.services import credit_contract_service as cc
from app.services import org_order_service as svc
from app.services import procurement_service as pr_svc
from app.services import seller_advance_service as adv
from tests.test_phase3_org_orders import PRICE, Phase3Base
from tests.test_phase4_credit_platform import Phase4Base, utc


def _code(resp) -> str:
    body = resp.get_json() or {}
    return (body.get("error") or {}).get("code") or body.get("code") or ""


class OrgReviewFixTests(Phase3Base):
    # 1 ─ legacy approve endpoint must not bypass a multi-approver rule
    def test_legacy_approve_delegates_to_multilevel_rule(self):
        with self.db.write_transaction() as c:
            svc.create_rule(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                            data={"name": "همه", "min_total_minor": 0, "decision": "require_approvals",
                                  "required_approvals": 2})
            pr = pr_svc.create_purchase_request(c, organization_id=self.org_id, requester_user_id=self.emp_uid,
                                                title="t", items=[{"free_text_description": "x", "quantity": 1,
                                                                   "estimated_unit_price_minor": PRICE}])
            pr_svc.submit_purchase_request(c, pr["id"], actor_user_id=self.emp_uid, organization_id=self.org_id)
            out = pr_svc.approve_purchase_request(c, pr["id"], actor_user_id=self.admin["user_id"],
                                                  organization_id=self.org_id, action="approve")
        self.assertEqual(out["status"] if "status" in out else out["purchase_request"]["status"], "under_review")
        second, member = self.make_org_admin(self.org_id)
        with self.db.write_transaction() as c:
            with self.assertRaises(ConflictError):  # same approver twice still refused
                pr_svc.approve_purchase_request(c, pr["id"], actor_user_id=self.admin["user_id"],
                                                organization_id=self.org_id, action="approve")
        with self.db.write_transaction() as c:
            pr_svc.approve_purchase_request(c, pr["id"], actor_user_id=member["user_id"],
                                            organization_id=self.org_id, action="approve")
            self.assertEqual(c.execute("SELECT status FROM purchase_requests WHERE id=?", (pr["id"],)).fetchone()[0],
                             "approved")

    # 2a ─ total above the approved estimate is refused, nothing written; tolerance is configurable
    def test_conversion_refuses_total_above_approved_amount(self):
        pr_id, item = self._approved_pr(qty=3, est=PRICE)  # estimate excludes tax/shipping → total exceeds it
        before = self._available_credit()
        r = self._convert(self._body(pr_id, item))
        self.assertEqual(r.status_code, 409, r.get_json())
        self.assertEqual(_code(r), "exceeds_approved_amount")
        self.assertEqual((self._stock(), self._available_credit()), (0, before))
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_sources").fetchone()[0], 0)
        with mock.patch.dict(os.environ, {"ORG_APPROVAL_TOLERANCE_BPS": "10000"}):
            self.assertEqual(self._convert(self._body(pr_id, item), key="k2").status_code, 201)

    # 2b ─ free-text rows: offer must be chosen by an approver, never the requester
    def test_free_text_item_offer_requires_approver(self):
        pr_id, item = self._approved_pr(qty=1)
        with self.db.write_transaction() as c:
            c.execute("UPDATE organization_memberships SET procurement_role='procurement_officer' WHERE id=?",
                      (self.employee["id"],))
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/orders", json=self._body(pr_id, item),
                             headers={**self.employee["headers"], "Idempotency-Key": "e1"})
        self.assertEqual(r.status_code, 409, r.get_json())
        self.assertEqual(_code(r), "offer_choice_requires_approver")
        self.assertEqual(self._stock(), 0)

    # minor ─ explicit allocation_id must belong to the actor unless finance/admin
    def test_explicit_allocation_must_belong_to_actor(self):
        pr_id, item = self._approved_pr(qty=1)
        agent_h, agent = self.make_org_admin(self.org_id)
        with self.db.write_transaction() as c:
            c.execute("UPDATE organization_memberships SET role='procurement_agent', procurement_role='approver' "
                      "WHERE id=?", (agent["id"],))
        body = self._body(pr_id, item, allocation_id=self.employee["allocation"]["id"])
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/orders", json=body,
                             headers={**agent_h, "Idempotency-Key": "a1"})
        self.assertEqual(r.status_code, 403, r.get_json())
        self.assertEqual(_code(r), "allocation_not_owned")
        self.assertEqual(self._convert(body, key="a2").status_code, 201)  # org admin may pick it

    # 3 ─ unpaid cash share expires: stock released, captured credit given back (append-only), order cancelled
    def test_expire_unpaid_releases_stock_and_credit(self):
        with self.db.write_transaction() as c:
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"payment_method": "prepayment", "prepayment_bps": 3000})
        before = self._available_credit()
        pr_id, item = self._approved_pr(qty=2)
        order = self._convert(self._body(pr_id, item)).get_json()["order"]
        self.assertEqual((order["status"], self._stock()), ("pending", 2))
        self.assertLess(self._available_credit(), before)
        with self.db.write_transaction() as c:
            self.assertEqual(svc.expire_unpaid(c, datetime.now(timezone.utc))["expired"], 0)  # not yet due
            captures = c.execute("SELECT COUNT(*) FROM credit_ledger_entries WHERE entry_type='capture'").fetchone()[0]
            res = svc.expire_unpaid(c, datetime.now(timezone.utc) + timedelta(hours=73))
            self.assertEqual(res["order_ids"], [order["id"]])
            self.assertEqual(svc.expire_unpaid(c, datetime.now(timezone.utc) + timedelta(hours=80))["expired"], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM credit_ledger_entries WHERE entry_type='capture'")
                             .fetchone()[0], captures)  # history untouched
            view = svc.order_view(c, order["id"])
        self.assertEqual((view["status"], view["source"]["cash_status"]), ("cancelled", "cancelled"))
        self.assertEqual((self._stock(), self._available_credit()), (0, before))
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/confirm-payment",
                             json={"reference": "LATE"}, headers=self.org_admin_h)
        self.assertEqual(r.get_json()["order"]["status"], "cancelled")
        self.assertEqual(self.trial_balance()[0], self.trial_balance()[1])
        self.assertIn("expire_unpaid", (Path(__file__).resolve().parents[1] / "scripts/run_credit_cycle.py").read_text())

    def test_explicit_cancel_before_fulfillment(self):
        with self.db.write_transaction() as c:
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"payment_method": "cash"})
        pr_id, item = self._approved_pr(qty=1)
        order = self._convert(self._body(pr_id, item)).get_json()["order"]
        url = f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/cancel"
        self.assertEqual(self.client.post(url, json={}, headers=self.employee["headers"]).status_code, 403)
        r = self.client.post(url, json={"reason": "انصراف"}, headers=self.org_admin_h)
        self.assertEqual(r.get_json()["order"]["status"], "cancelled", r.get_json())
        self.assertEqual(self._stock(), 0)
        self.assertEqual(self.client.post(url, json={}, headers=self.org_admin_h).status_code, 409)

    def _paid_preorder(self, qty=1):
        now = datetime.now(timezone.utc)
        with self.db.write_transaction() as c:
            brand_service.set_window(c, supplier_id=self.supplier_id, user_id=self.admin["user_id"],
                                     offer_id=self.offer_id,
                                     data={"starts_at": (now - timedelta(hours=1)).isoformat(),
                                           "ends_at": (now + timedelta(days=7)).isoformat(),
                                           "expected_ship_date": (now + timedelta(days=30)).date().isoformat(),
                                           "deposit_bps": 2000, "unit_price_minor": 900_000, "max_quantity": 5})
            pre = brand_service.create_preorder(c, user_id=self.emp_uid, idempotency_key=uuid.uuid4().hex,
                                                data={"offer_id": self.offer_id, "quantity": qty,
                                                      "shipping_address": self.DEFAULT_ADDRESS})
            pre = pre[1] if isinstance(pre, tuple) else pre
            pre = pre.get("preorder", pre)
            brand_service.confirm_deposit(c, preorder_id=pre["id"], admin_user_id=self.admin["user_id"],
                                          reference="D1")
        return pre["id"]

    def test_preorder_convert_checks_sellability_and_expires(self):
        pid = self._paid_preorder()
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET status='inactive' WHERE id=?", (self.offer_id,))
        with self.db.write_transaction() as c, self.assertRaises(ConflictError) as ctx:
            brand_service.convert(c, preorder_id=pid, actor_user_id=self.admin["user_id"], supplier_id=None)
        self.assertEqual(ctx.exception.code, "offer_unavailable")
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET status='active' WHERE id=?", (self.offer_id,))
            order = brand_service.convert(c, preorder_id=pid, actor_user_id=self.admin["user_id"], supplier_id=None)
        self.assertEqual(self._stock(), 1)
        with self.db.write_transaction() as c:
            self.assertEqual(svc.expire_unpaid(c, datetime.now(timezone.utc) + timedelta(hours=73))["order_ids"],
                             [order["id"]])
            self.assertEqual(c.execute("SELECT status FROM preorders WHERE id=?", (pid,)).fetchone()[0], "cancelled")
        self.assertEqual(self._stock(), 0)


class CreditReviewFixTests(Phase4Base):
    def _contract(self):
        org, _h, _admin, employee = self.org_fixture(credit_minor=500_000_000)
        with self.db.write_transaction() as conn:
            _, contract = cc.create_contract(conn, organization_id=org["id"], idempotency_key="k1", actor_user_id=None,
                                             payload={"limit_minor": 1_000_000_000, "starts_at": "2026-11-01 00:00:00",
                                                      "funder_type": "institution", "funder_name": "صندوق رفاه"})
        return org, employee, contract

    # 5 ─ statement usage is net of capture reversals; freeze uses the net figure
    def test_statement_usage_is_net_and_reversal_prevents_freeze(self):
        org, emp, contract = self._contract()
        self.capture(emp, org["id"], 40_000_000, "2026-11-03 10:00:00")
        order_id = self.make_order(emp["user_id"], 40_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO credit_ledger_entries (reference, allocation_id, organization_id, user_id, "
                         "entry_type, amount_minor, order_id, created_at) VALUES ('CREV-T', ?,?,?, 'adjustment', ?,?,?)",
                         (emp["allocation"]["id"], org["id"], emp["user_id"], 40_000_000, order_id,
                          "2026-11-08 10:00:00"))
            self.assertEqual(credit_service.organization_usage_minor(
                conn, organization_id=org["id"], period_start="2026-11-01 00:00:00",
                period_end="2026-11-20 00:00:00"), 0)
            cc.run_weekly_statements(conn, utc(2026, 11, 14, 12))
            sts = sorted(cc.list_statements(conn, org["id"]), key=lambda s: s["period_start"])
            self.assertEqual([s["usage_minor"] for s in sts], [40_000_000, -40_000_000])
            self.assertEqual(cc.enforce_overdue(conn, utc(2026, 11, 14, 12))["frozen"], 0)
            self.assertEqual(cc.get_contract(conn, contract["id"])["status"], "active")
            self.assertEqual(cc.outstanding_minor(conn, contract["id"], utc(2026, 11, 14, 12)), 0)

    # minor ─ a payment may not be back-dated into an already issued statement period
    def test_payment_received_at_before_issued_period_refused(self):
        org, emp, contract = self._contract()
        self.capture(emp, org["id"], 10_000_000, "2026-11-03 10:00:00")
        with self.db.write_transaction() as conn:
            cc.run_weekly_statements(conn, utc(2026, 11, 14, 12))
            with self.assertRaises(ValidationError) as ctx:
                cc.record_payment(conn, contract["id"], amount_minor=1, idempotency_key="old", actor_user_id=None,
                                  received_at="2026-11-05 08:00:00", now=utc(2026, 11, 15))
            self.assertEqual(ctx.exception.code, "received_at_before_statement")
            created, _ = cc.record_payment(conn, contract["id"], amount_minor=1, idempotency_key="ok",
                                           actor_user_id=None, received_at="2026-11-14 08:00:00",
                                           now=utc(2026, 11, 15))
            self.assertTrue(created)

    # 4 ─ installments: creditor from the order, single seller, ownership before replay, seller view redacted
    def _user(self):
        _, headers = self.new_customer()
        me = self.client.get("/api/v1/auth/me", headers=headers).get_json()
        return (me.get("user") or me)["id"], headers

    def test_installment_creditor_derived_and_scoped(self):
        sup, other = self.create_test_supplier(), self.create_test_supplier()
        uid, headers = self._user()
        plan = self.db.query_one("SELECT id FROM installment_plans WHERE code='m3'")["id"]
        multi = self.make_order(uid, 5_000_000, suppliers=[sup, other])
        r = self.client.post("/api/v1/installments", json={"order_id": multi, "plan_id": plan},
                             headers={**headers, "Idempotency-Key": "m1"})
        self.assertEqual((r.status_code, _code(r)), (409, "multi_seller_order"))
        order = self.make_order(uid, 6_000_000, suppliers=[sup])
        r = self.client.post("/api/v1/installments", json={"order_id": order, "plan_id": plan,
                                                            "supplier_id": other["supplier_id"]},
                             headers={**headers, "Idempotency-Key": "i1"})
        self.assertEqual(r.status_code, 201, r.get_json())
        a = r.get_json()["installment"]
        self.assertEqual(a["supplier_id"], sup["supplier_id"])  # body supplier_id ignored
        # another user: replaying the key on the victim's order → 404; on their own order → conflict
        uid2, headers2 = self._user()
        r = self.client.post("/api/v1/installments", json={"order_id": order, "plan_id": plan},
                             headers={**headers2, "Idempotency-Key": "i1"})
        self.assertEqual(r.status_code, 404)
        own = self.make_order(uid2, 6_000_000, suppliers=[sup])
        r = self.client.post("/api/v1/installments", json={"order_id": own, "plan_id": plan},
                             headers={**headers2, "Idempotency-Key": "i1"})
        self.assertEqual(r.status_code, 409)
        # seller sees repayment progress only
        seen = self.client.get(f"/api/v1/installments/{a['id']}", headers=sup["headers"])
        self.assertEqual(seen.status_code, 200, seen.get_json())
        view = seen.get_json()["installment"]
        self.assertNotIn("user_id", view)
        self.assertNotIn("created_by_user_id", view)
        self.assertIn("schedules", view)
        self.assertEqual(self.client.get(f"/api/v1/installments/{a['id']}", headers=other["headers"]).status_code, 404)
        # cancelled orders cannot be financed
        dead = self.make_order(uid, 1_000_000, suppliers=[sup])
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (dead,))
        r = self.client.post("/api/v1/installments", json={"order_id": dead, "plan_id": plan},
                             headers={**headers, "Idempotency-Key": "d1"})
        self.assertEqual((r.status_code, _code(r)), (409, "order_not_eligible"))

    # 6 ─ net exactly 0 after advance netting → batch completes, payables settled, no bank payment
    def test_settlement_fully_absorbed_by_advance_completes(self):
        sup = self.create_test_supplier()
        sid = sup["supplier_id"]
        conn = self.db.connection
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.db.write_transaction() as c:
                for gross in (10_000_000, 5_000_000):
                    c.execute("INSERT INTO supplier_payable_entries (supplier_id, fulfillment_order_id, gross_minor, "
                              "idempotency_key, status, commission_minor) VALUES (?,?,?,?, 'unbatched', 0)",
                              (sid, 999_999, gross, uuid.uuid4().hex))
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
        with self.db.write_transaction() as c:
            adv.request_advance(c, supplier_id=sid, idempotency_key="adv1", actor_user_id=None, amount_minor=5_000_000)
            small = c.execute("SELECT id FROM supplier_payable_entries WHERE supplier_id=? AND gross_minor=5000000",
                              (sid,)).fetchone()[0]
            batch = settlement_service.create_settlement_batch(c, supplier_id=sid, payable_entry_ids=[small],
                                                               idempotency_key="SB-zero", release_held=True)
            self.assertEqual((batch["net_minor"], batch["advance_recovered_minor"]), (0, 5_000_000))
            done = settlement_service.complete_settlement_batch(c, batch_id=batch["id"])
            self.assertEqual(done["batch"]["status"], "completed")
            self.assertIsNone(done["payment"])
            self.assertEqual(c.execute("SELECT status FROM supplier_payable_entries WHERE id=?", (small,)).fetchone()[0],
                             "settled")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM settlement_payments").fetchone()[0], 0)
            self.assertEqual(adv.outstanding_advance(c, sid), 0)
