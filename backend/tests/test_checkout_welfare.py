"""کیف پول رفاهی در پرداخت: welfare first, then credit, then card; reversal on failure; ledger balances."""
from __future__ import annotations

import uuid

from app.services import welfare_wallet_service as wf
from tests.base import AppTestCase


class CheckoutWelfareTest(AppTestCase):
    def setup_cart(self, credit_minor=0, qty=1):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=credit_minor)
        p = self.product("office-paper-a4-carton")
        self.set_stock(p["id"], 20)
        self.add_to_cart(emp["headers"], p["id"], qty)
        q = self.quote(emp["headers"])["cart"]
        self.subtotal = q["subtotal_minor"]
        return org, emp, q["total_minor"]

    def plan(self, org_id, cap, key="w1"):
        with self.db.write_transaction() as conn:
            wf.create_plan(conn, organization_id=org_id, idempotency_key=key, actor_user_id=None,
                           payload={"title": "بن خرید", "plan_type": "free", "per_employee_cap_minor": cap,
                                    "expires_at": "2099-01-01"})

    def pay(self, emp, use_welfare=True, key=None):
        return self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS, "use_welfare": use_welfare},
                                headers={**emp["headers"], "Idempotency-Key": key or uuid.uuid4().hex})

    def remaining(self, emp):
        with self.db.read_transaction() as conn:
            return wf.member_summary(conn, emp["user_id"])["remaining_minor"]

    def test_partial_welfare_card_pays_rest(self):
        org, emp, total = self.setup_cart()
        self.plan(org["id"], 100_000)
        w = self.client.get("/api/v1/checkout/welfare", headers=emp["headers"]).get_json()
        self.assertEqual((w["available"], w["allowed_minor"]), (True, 100_000))
        r = self.pay(emp)
        self.assertEqual(r.status_code, 201, r.get_json())
        oid = r.get_json()["order"]["id"]
        with self.db.read_transaction() as conn:
            o = conn.execute("SELECT total_minor, cash_minor, credit_minor, welfare_minor FROM orders WHERE id=?", (oid,)).fetchone()
            paid = conn.execute("SELECT amount_minor FROM payments WHERE order_id=?", (oid,)).fetchone()[0]
        self.assertEqual((o["welfare_minor"], o["total_minor"]), (100_000, total))
        self.assertEqual(r.get_json()["order"]["welfare_minor"], 100_000)
        self.assertEqual(o["total_minor"], o["cash_minor"] + o["credit_minor"])
        self.assertEqual(paid, total - 100_000)  # the card never pays the employer's share
        self.assertEqual(self.remaining(emp), 0)
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)

    def test_welfare_before_credit_and_full_cover(self):
        org, emp, total = self.setup_cart(credit_minor=50_000_000)
        self.plan(org["id"], total + 5)
        r = self.pay(emp)
        self.assertEqual(r.status_code, 201, r.get_json())
        oid = r.get_json()["order"]["id"]
        with self.db.read_transaction() as conn:
            o = conn.execute("SELECT credit_minor, welfare_minor FROM orders WHERE id=?", (oid,)).fetchone()
            self.assertIsNone(conn.execute("SELECT 1 FROM payments WHERE order_id=?", (oid,)).fetchone())
        # welfare pays the goods (applied first); VAT and shipping fall to credit; the card pays nothing
        self.assertEqual((o["welfare_minor"], o["credit_minor"]), (self.subtotal, total - self.subtotal))
        self.assertEqual(self.remaining(emp), total + 5 - self.subtotal)

    def test_opt_in_only(self):
        org, emp, total = self.setup_cart()
        self.plan(org["id"], 100_000)
        r = self.pay(emp, use_welfare=False)
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(self.remaining(emp), 100_000)

    def test_card_decline_gives_welfare_back(self):
        org, emp, total = self.setup_cart()
        self.plan(org["id"], self.subtotal - 1013)  # card share ends in 13 → the mock gateway declines it
        r = self.pay(emp)
        self.assertEqual(r.status_code, 402, r.get_json())
        self.assertEqual(self.remaining(emp), self.subtotal - 1013)
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)


from app.core.errors import ConflictError  # noqa: E402


class WelfareRefundTest(CheckoutWelfareTest):
    def _return(self, order_id, amount, admin_id):
        from app.services import commerce_ops_service as ops
        with self.db.write_transaction() as conn:
            rid = conn.execute("INSERT INTO order_return_requests (order_id, user_id, items_json, reason, status) "
                               "SELECT id, user_id, '[]', 'خراب بود', 'refund_pending' FROM orders WHERE id=?", (order_id,)).lastrowid
            split = ops.refund_split(conn, return_id=rid, amount=amount)
            self.assertGreater(split["welfare_minor"], 0)
            with self.assertRaises(ConflictError):  # finance must confirm the bank share, not wire the full amount
                ops.admin_transition(conn, actor=admin_id, return_id=rid, action="refund",
                                     data={"amount_minor": amount, "reference": "REF-123"})
            v = ops.admin_transition(conn, actor=admin_id, return_id=rid, action="refund",
                                     data={"amount_minor": amount, "reference": "REF-123", "bank_amount_minor": split["bank_minor"]})
            self.assertEqual(v["bank_refund_minor"], split["bank_minor"])
            return v

    def test_refund_refills_wallet_in_proportion(self):
        org, emp, total = self.setup_cart()
        self.plan(org["id"], 100_000)
        oid = self.pay(emp).get_json()["order"]["id"]
        admin_id = self.client.get("/api/v1/auth/me", headers=self.admin_headers()).get_json()["user"]["id"]
        half = total // 2
        v = self._return(oid, half, admin_id)
        self.assertEqual(v["welfare_restored_minor"], half * 100_000 // total)
        self.assertEqual(v["bank_refund_minor"], half - v["welfare_restored_minor"])
        self.assertEqual(self.remaining(emp), v["welfare_restored_minor"])
        v2 = self._return(oid, total - half, admin_id)  # final refund returns whatever is still out
        self.assertEqual(v["welfare_restored_minor"] + v2["welfare_restored_minor"], 100_000)
        self.assertEqual(self.remaining(emp), 100_000)


for _n in [n for n in vars(CheckoutWelfareTest) if n.startswith("test_")]:
    setattr(WelfareRefundTest, _n, None)
