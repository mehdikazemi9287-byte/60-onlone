"""VandaPay adapter v2 + federated-credit rules (owner decision 2026-11-18).

Covers: exact per-line VAT spread in ``items``; exclusive funding (internal welfare/credit XOR VandaPay);
refunds of VandaPay-paid returns through the adapter and ``refund.*`` webhooks; organisation cash share via
VandaPay (flag-gated); the flag-off issuer connector stub.

All VandaPay traffic goes to ``FakeVandaPay`` from tests/test_vandapay.py (synthetic, in-memory); amounts,
phones and ids below are synthetic test fixtures, never business data.
"""
from __future__ import annotations

import dataclasses
import json
import os
import time
import unittest
import uuid
from unittest import mock

from app.adapters.payment import registry as payment_registry
from app.adapters.payment.base import GatewayError, PaymentRequest
from app.adapters.payment.vandapay import (
    build_items, compute_signature, enabled_from_env, line_vat, parse_category_map,
)
from app.main import create_app
from app.services import federated_issuer_service as issuer
from tests.base import AppTestCase
from tests.test_phase3_org_orders import Phase3Base
from tests.test_vandapay import API, WH_SECRET, FakeVandaPay, _provider


class RefundAwareFake(FakeVandaPay):
    """FakeVandaPay that can answer a refund with 202 pending (card leg still being returned)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.refund_mode = "succeeded"
        self.refund_seq = 0
        self.refund_by_key: dict[str, dict] = {}
        self.refuse_refund = None

    def __call__(self, method, url, headers, body):
        path = url[len(API):]
        if method == "POST" and path.endswith("/refunds"):
            self.calls.append((method, path, headers.get("Idempotency-Key"), json.loads(body)))
            if self.down:
                raise GatewayError("vandapay unreachable: URLError")
            key = headers.get("Idempotency-Key")
            if key in self.refund_by_key:
                return 201, self.refund_by_key[key]
            if self.refuse_refund:
                return 422, {"error": {"code": self.refuse_refund}}
            intent = self.intents[path.strip("/").split("/")[1]]
            amount = json.loads(body)["amount"]
            self.refund_seq += 1
            res = {"id": f"re_fake{self.refund_seq}", "status": self.refund_mode, "amount": amount}
            if self.refund_mode == "succeeded":
                intent["refunded_amount"] += amount
                intent["status"] = "refunded" if intent["refunded_amount"] >= intent["amount"] else "partially_refunded"
            self.refund_by_key[key] = res
            return (201 if self.refund_mode == "succeeded" else 202), res
        return super().__call__(method, url, headers, body)

    def settle_refund(self, refund_id):
        for res in self.refund_by_key.values():
            if res["id"] == refund_id:
                pid = [c[1] for c in self.calls if c[0] == "POST" and c[1].endswith("/refunds")][-1].split("/")[2]
                intent = self.intents[pid]
                intent["refunded_amount"] += res["amount"]
                intent["status"] = "refunded" if intent["refunded_amount"] >= intent["amount"] else "partially_refunded"
                res["status"] = "succeeded"


# ───────────────────────────────────────────────────────────── items / VAT ──
class ItemsAndVatTest(unittest.TestCase):
    LINES = [
        {"product_id": 1, "sku": "A", "title_fa": "برنج", "quantity": 2, "category_slug": "rice", "line_total_minor": 333_333},
        {"product_id": 2, "sku": "B", "title_fa": "روغن", "quantity": 1, "category_slug": "oil", "line_total_minor": 666_667},
        {"product_id": 3, "sku": "C", "title_fa": "چای", "quantity": 1, "category_slug": "tea", "line_total_minor": 1_001},
    ]

    def test_bps_rule_remainder_on_largest_line(self):
        bases = [333_333, 666_667, 1_001]
        total_tax = sum(bases) * 1000 // 10_000
        vat = line_vat(bases, tax_minor=total_tax, rate_bps=1000)
        self.assertEqual(sum(vat), total_tax)
        floors = [b * 1000 // 10_000 for b in bases]
        self.assertEqual(vat[0], floors[0])
        self.assertEqual(vat[2], floors[2])
        self.assertEqual(vat[1] - floors[1], total_tax - sum(floors))  # remainder only on the largest line
        self.assertLess(total_tax - sum(floors), len(bases))

    def test_exemption_or_other_rule_spreads_the_order_tax(self):
        self.assertEqual(line_vat([100, 200], tax_minor=0, rate_bps=1000), [0, 0])  # exempt organisation
        vat = line_vat([100, 200, 7], tax_minor=13, rate_bps=1000)  # not the bps rule → proportional, exact
        self.assertEqual(sum(vat), 13)
        with self.assertRaises(GatewayError):
            line_vat([100], tax_minor=-1, rate_bps=1000)

    def test_items_add_up_exactly_with_discount_vat_and_shipping(self):
        gross = sum(l["line_total_minor"] for l in self.LINES)
        subtotal = gross - 77_777  # 60Coin / recurring discount spread over the lines first
        tax = subtotal * 1000 // 10_000
        items = build_items(lines=self.LINES, subtotal_minor=subtotal, shipping_minor=45_000, tax_minor=tax,
                            tax_rate_bps=1000, currency="IRR", category_map={"rice": "goods.livelihood"})
        self.assertEqual(sum(i["amount"] for i in items), subtotal + 45_000 + tax)
        self.assertEqual(items[0]["category"], "goods.livelihood")
        self.assertEqual(items[1]["category"], "goods.general")  # unmapped → default
        self.assertEqual(items[-1], {"sku": "SHIPPING", "name": "هزینهٔ ارسال", "quantity": 1,
                                     "category": "goods.general", "amount": 45_000})  # shipping: no VAT added
        self.assertNotIn("tax", [i["sku"].lower() for i in items])  # never a separate VAT line
        self.assertTrue(all(type(i["amount"]) is int for i in items))

    def test_toman_lines_are_converted_to_rial(self):
        items = build_items(lines=self.LINES[:1], subtotal_minor=333_333, shipping_minor=0,
                            tax_minor=33_333, tax_rate_bps=1000, currency="IRT")
        self.assertEqual(items[0]["amount"], (333_333 + 33_333) * 10)

    def test_fully_discounted_line_is_dropped_and_overdiscount_refused(self):
        lines = [dict(self.LINES[0], line_total_minor=10), dict(self.LINES[1], line_total_minor=1_000_000)]
        items = build_items(lines=lines, subtotal_minor=1_000_000, shipping_minor=0, tax_minor=0, tax_rate_bps=0,
                            currency="IRR")
        self.assertEqual(sum(i["amount"] for i in items), 1_000_000)
        with self.assertRaises(GatewayError):
            build_items(lines=lines, subtotal_minor=2_000_000, shipping_minor=0, tax_minor=0, tax_rate_bps=0,
                        currency="IRR")

    def test_category_map_config(self):
        self.assertEqual(parse_category_map('{"rice":"goods.livelihood"}'), {"rice": "goods.livelihood"})
        for bad in ('[1]', '{"rice":"GOODS"}', '{"rice": 3}', "not json"):
            with self.assertRaises(ValueError, msg=bad):
                parse_category_map(bad)
        env = {"VANDAPAY_SECRET_KEY": "sk_test_x", "VANDAPAY_WEBHOOK_SECRET": "whsec_x",
               "VANDAPAY_CATEGORY_MAP": "{bad"}
        self.assertIsNone(enabled_from_env(env, app_env="development"))  # bad config → stays off


class AdapterIntentBodyTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeVandaPay()
        self.vp = _provider(self.fake)

    def _req(self, ctx, amount):
        return PaymentRequest(amount_minor=amount, currency="IRR", order_reference="intent:9", idempotency_key="k",
                              customer_email="a@example.test", metadata={"vandapay": ctx})

    def test_items_category_phone_and_metadata_sent(self):
        lines = ItemsAndVatTest.LINES[:2]
        sub = sum(l["line_total_minor"] for l in lines)
        tax = sub * 1000 // 10_000
        ctx = {"lines": lines, "subtotal_minor": sub, "shipping_minor": 50_000, "tax_minor": tax,
               "tax_rate_bps": 1000, "price_tier": "public", "customer_phone": "09120000000"}
        self.vp.initiate(self._req(ctx, sub + tax + 50_000), invoice_id=9, callback_url="https://60online.test/cb")
        body = self.fake.calls[-1][3]
        self.assertEqual(body["category"], "goods")
        self.assertEqual(body["customer_phone"], "09120000000")
        self.assertEqual(sum(i["amount"] for i in body["items"]), body["amount"])
        self.assertEqual(body["metadata"]["vat_rial"], tax)
        self.assertEqual(body["metadata"]["shipping_rial"], 50_000)
        self.assertEqual(body["metadata"]["funding"], "vandapay_exclusive")
        self.assertEqual(body["metadata"]["invoice_id"], "9")

    def test_mismatch_is_refused_before_sending(self):
        lines = ItemsAndVatTest.LINES[:1]
        ctx = {"lines": lines, "subtotal_minor": 333_333, "shipping_minor": 0, "tax_minor": 33_333, "tax_rate_bps": 1000}
        with self.assertRaises(GatewayError):
            self.vp.initiate(self._req(ctx, 333_333 + 33_333 + 1), invoice_id=9, callback_url="https://60online.test/cb")
        self.assertEqual(self.fake.calls, [])

    def test_unverified_phone_is_not_sent(self):
        ctx = {"lines": ItemsAndVatTest.LINES[:1], "subtotal_minor": 333_333, "shipping_minor": 0,
               "tax_minor": 0, "tax_rate_bps": 0, "customer_phone": "+98 912"}
        self.vp.initiate(self._req(ctx, 333_333), invoice_id=9, callback_url="https://60online.test/cb")
        self.assertNotIn("customer_phone", self.fake.calls[-1][3])

    def test_create_refund_pending_and_key(self):
        fake = RefundAwareFake()
        vp = _provider(fake)
        ins = vp.initiate(dataclasses.replace(self._req({}, 1000), metadata=None), invoice_id=3,
                          callback_url="https://60online.test/cb")
        fake.pay(ins.provider_ref)
        fake.refund_mode = "pending"
        res = vp.create_refund(ins.provider_ref, 400, key="60online-return-5-400", reason="t")
        self.assertEqual(res["status"], "pending")
        self.assertEqual(fake.calls[-1][2], "60online-return-5-400")


# ─────────────────────────────────────────────────── checkout exclusivity ──
class VandaPayExclusiveFundingTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.settings = dataclasses.replace(self.settings, public_base_url="https://60online.test")
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()
        self.fake = RefundAwareFake()
        payment_registry.register(_provider(self.fake))
        self.app.extensions["vandapay_provider"] = "vandapay"
        self.org, self.admin_h, self.admin, self.emp = self.org_fixture(credit_minor=50_000_000)
        p = self.product("office-paper-a4-carton")
        self.set_stock(p["id"], 20)
        self.add_to_cart(self.emp["headers"], p["id"], 1)  # below the free-shipping threshold → shipping line
        q = self.quote(self.emp["headers"])
        self.assertGreater(q["cart"]["shipping_fee_minor"], 0)
        self.total, self.subtotal = q["cart"]["total_minor"], q["cart"]["subtotal_minor"]
        self.assertGreater(q["credit_to_use_minor"], 0)  # internal org credit WOULD apply on the card path
        from app.services import welfare_wallet_service as wf
        with self.db.write_transaction() as conn:
            wf.create_plan(conn, organization_id=self.org["id"], idempotency_key="w1", actor_user_id=None,
                           payload={"title": "بن خرید", "plan_type": "free", "per_employee_cap_minor": 100_000,
                                    "expires_at": "2099-01-01"})
            conn.execute("UPDATE users SET phone_verified='09120000001' WHERE id=?", (self.emp["user_id"],))

    def tearDown(self):
        payment_registry.reset_for_tests()
        super().tearDown()

    def _checkout(self, provider="vandapay", use_welfare=False, key=None):
        body = {"shipping_address": self.DEFAULT_ADDRESS, "payment_provider": provider}
        if use_welfare:
            body["use_welfare"] = True
        return self.client.post("/api/v1/checkout", json=body,
                                headers={**self.emp["headers"], "Idempotency-Key": key or uuid.uuid4().hex})

    def _credit_available(self):
        from app.services.credit_service import allocation_state
        with self.db.read_transaction() as c:
            return allocation_state(c, self.emp["allocation"]["id"])["available_minor"]

    def _welfare_left(self):
        from app.services import welfare_wallet_service as wf
        with self.db.read_transaction() as c:
            return wf.member_summary(c, self.emp["user_id"])["remaining_minor"]

    def _pay_and_return(self, body):
        pid = body["payment_redirect"]["url"].split("/pay/")[1].split("?")[0]
        self.fake.pay(pid)
        r = self.client.get("/api/v1/payments/vandapay/callback",
                            query_string={"invoice_id": str(body["payment_intent_id"])})
        self.assertIn("payment=success", r.headers["Location"])
        return pid

    def test_vandapay_gets_whole_total_and_internal_funding_untouched(self):
        credit_before, welfare_before = self._credit_available(), self._welfare_left()
        r = self._checkout()
        self.assertEqual(r.status_code, 202, r.get_json())
        body = r.get_json()
        self.assertEqual((body["cash_due_minor"], body["credit_minor"]), (self.total, 0))
        create = [c for c in self.fake.calls if c[1] == "/payment_intents"][0][3]
        self.assertEqual(create["amount"], self.total)
        self.assertEqual(sum(i["amount"] for i in create["items"]), self.total)
        ship = [i for i in create["items"] if i["sku"] == "SHIPPING"]
        self.assertEqual(ship[0]["amount"], self.total - self.subtotal - self.subtotal * 1000 // 10_000)
        self.assertEqual(create["customer_phone"], "09120000001")
        self.assertEqual(self._credit_available(), credit_before)  # no internal hold
        self.assertEqual(self._welfare_left(), welfare_before)
        self._pay_and_return(body)
        with self.db.read_transaction() as c:
            o = c.execute("SELECT total_minor, credit_minor, cash_minor, welfare_minor FROM orders").fetchone()
            pay = c.execute("SELECT provider, amount_minor FROM payments").fetchone()
        self.assertEqual((o["credit_minor"], o["welfare_minor"], o["cash_minor"]), (0, 0, self.total))
        self.assertEqual((pay["provider"], pay["amount_minor"]), ("vandapay", self.total))
        self.assertEqual(self._credit_available(), credit_before)
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)

    def test_welfare_with_vandapay_is_refused_explicitly(self):
        r = self._checkout(use_welfare=True)
        self.assertEqual(r.status_code, 422, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"], "funding_source_conflict")
        self.assertEqual(self.fake.calls, [])
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM payment_intents").fetchone()[0], 0)
        self.assertEqual(self._welfare_left(), 100_000)

    def test_internal_path_still_uses_welfare_then_credit_then_card(self):
        r = self._checkout(provider="mock", use_welfare=True)
        self.assertEqual(r.status_code, 201, r.get_json())
        o = r.get_json()["order"]
        self.assertEqual(o["welfare_minor"], 100_000)
        self.assertGreater(o["credit_minor"], 0)
        self.assertEqual(self.fake.calls, [])  # VandaPay never involved

    # ── refunds through the adapter ──
    def _paid_order_with_return(self, amount=None):
        body = self._checkout().get_json()
        self.pid = self._pay_and_return(body)
        admin_h = self.admin_headers()
        self.admin_h2 = admin_h
        with self.db.write_transaction() as c:
            oid = c.execute("SELECT id FROM orders").fetchone()[0]
            rid = c.execute("INSERT INTO order_return_requests (order_id, user_id, items_json, reason, status) "
                            "SELECT id, user_id, '[]', 'خراب بود', 'refund_pending' FROM orders WHERE id=?",
                            (oid,)).lastrowid
            uid = c.execute("SELECT user_id FROM orders WHERE id=?", (oid,)).fetchone()[0]
            c.execute("INSERT INTO order_return_events (return_id, actor_user_id, status) VALUES (?,?, 'refund_pending')",
                      (rid, uid))
        return oid, rid, admin_h

    def _refund(self, rid, admin_h, **data):
        return self.client.post(f"/api/v1/admin/returns/{rid}/refund", json=data,
                                headers={**admin_h, "Idempotency-Key": uuid.uuid4().hex})

    def _return_row(self, rid):
        with self.db.read_transaction() as c:
            return dict(c.execute("SELECT * FROM order_return_requests WHERE id=?", (rid,)).fetchone())

    def _webhook(self, event):
        raw = json.dumps(event, ensure_ascii=False).encode("utf-8")
        ts = int(time.time())
        return self.client.post("/api/v1/payments/vandapay/webhook", data=raw, headers={
            "Content-Type": "application/json", "VandaPay-Signature": f"t={ts},v1={compute_signature(WH_SECRET, ts, raw)}"})

    def test_return_refund_goes_through_vandapay(self):
        oid, rid, admin_h = self._paid_order_with_return()
        r = self._refund(rid, admin_h, amount_minor=self.total, reference="ignored-bank-ref")
        self.assertEqual(r.status_code, 200, r.get_json())
        refund_call = [c for c in self.fake.calls if c[1].endswith("/refunds")][-1]
        self.assertEqual(refund_call[2], f"60online-return-{rid}-{self.total}")
        self.assertEqual(refund_call[3]["amount"], self.total)
        row = self._return_row(rid)
        self.assertEqual((row["status"], row["refund_reference"]), ("refunded", "vandapay:re_fake1"))
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "refunded")
        # a replay cannot refund twice (status guard + deterministic VandaPay key)
        self.assertEqual(self._refund(rid, admin_h, amount_minor=self.total).status_code, 409)
        self.assertEqual(self.fake.intents[self.pid]["refunded_amount"], self.total)

    def test_manual_refund_blocked_unless_override(self):
        oid, rid, admin_h = self._paid_order_with_return()
        from app.services import commerce_ops_service as ops
        from app.core.errors import ConflictError
        with self.db.write_transaction() as c:
            with self.assertRaises(ConflictError) as ctx:
                ops.admin_transition(c, actor=1, return_id=rid, action="refund",
                                     data={"amount_minor": 1000, "reference": "BANK-1"})
            self.assertEqual(ctx.exception.code, "gateway_refund_required")
        r = self._refund(rid, admin_h, amount_minor=1000, reference="BANK-1", manual_override=True)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self._return_row(rid)["refund_reference"], "BANK-1")
        self.assertEqual([c for c in self.fake.calls if c[1].endswith("/refunds")], [])

    def test_vandapay_refusal_changes_nothing(self):
        oid, rid, admin_h = self._paid_order_with_return()
        self.fake.refuse_refund = "partial_refund_unsupported"
        r = self._refund(rid, admin_h, amount_minor=1000)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error"]["code"], "gateway_refund_manual_review")
        self.assertEqual(self._return_row(rid)["status"], "refund_pending")
        self.fake.refuse_refund = None
        self.fake.down = True
        self.assertEqual(self._refund(rid, admin_h, amount_minor=1000).status_code, 503)
        self.assertEqual(self._return_row(rid)["status"], "refund_pending")

    def test_pending_refund_finished_by_webhook_idempotently(self):
        oid, rid, admin_h = self._paid_order_with_return()
        self.fake.refund_mode = "pending"
        r = self._refund(rid, admin_h, amount_minor=self.total)
        self.assertEqual(r.status_code, 202, r.get_json())
        row = self._return_row(rid)
        self.assertEqual((row["status"], row["refund_reference"]), ("refund_pending", "vandapay:re_fake1"))
        evt = {"id": "evt_r1", "type": "refund.succeeded", "data": {"id": "re_fake1", "intent_id": self.pid}}
        r = self._webhook(evt)  # VandaPay's intent does not show the money back yet → retry later
        self.assertEqual(r.status_code, 503, r.get_json())
        self.assertEqual(self._return_row(rid)["status"], "refund_pending")
        self.fake.settle_refund("re_fake1")
        self.assertEqual(self._webhook(evt).get_json()["outcome"], "refund_applied")
        self.assertEqual(self._return_row(rid)["status"], "refunded")
        self.assertEqual(self._webhook(evt).get_json()["outcome"], "duplicate")
        evt2 = dict(evt, id="evt_r2")  # same refund, new delivery id
        self.assertEqual(self._webhook(evt2).get_json()["outcome"], "already_refunded")
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "refunded")

    def test_failed_refund_event_hands_back_to_finance(self):
        oid, rid, admin_h = self._paid_order_with_return()
        self.fake.refund_mode = "pending"
        self._refund(rid, admin_h, amount_minor=1000)
        r = self._webhook({"id": "evt_f", "type": "refund.failed", "data": {"id": "re_fake1", "intent_id": self.pid}})
        self.assertEqual(r.get_json()["outcome"], "refund_failed_manual_review")
        row = self._return_row(rid)
        self.assertEqual((row["status"], row["refund_reference"]), ("refund_pending", None))

    def test_panel_refund_without_return_is_recorded_not_applied(self):
        self._checkout_paid = self._pay_and_return(self._checkout().get_json())
        r = self._webhook({"id": "evt_p", "type": "refund.succeeded",
                           "data": {"id": "re_panel", "intent_id": self._checkout_paid}})
        self.assertEqual(r.get_json()["outcome"], "refund_logged")
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='payment.refund_external'")
                             .fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT status FROM orders").fetchone()[0], "paid")


# ──────────────────────────────────────────────── org order cash via VandaPay ──
class OrgCashVandaPayTest(Phase3Base):
    def setUp(self):
        super().setUp()
        self.settings = dataclasses.replace(self.settings, public_base_url="https://60online.test")
        self.app = create_app(self.settings, self.db)
        if "org_brands" not in self.app.blueprints:
            from app.api.v1.org_brands import bp
            self.app.register_blueprint(bp)
        self.client = self.app.test_client()
        self.fake = FakeVandaPay()
        payment_registry.register(_provider(self.fake))
        self.app.extensions["vandapay_provider"] = "vandapay"
        self.env = mock.patch.dict(os.environ, {"VANDAPAY_ORG_CASH_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        payment_registry.reset_for_tests()
        super().tearDown()

    def _due_order(self, method="cash", bps=None):
        from app.services import org_order_service as svc
        pr_id, item = self._approved_pr(qty=2)
        with self.db.write_transaction() as c:
            svc.update_buying_policy(c, organization_id=self.org_id, actor_user_id=self.admin["user_id"],
                                     data={"payment_method": method, **({"prepayment_bps": bps} if bps else {})})
        r = self._convert(self._body(pr_id, item))
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["order"]

    def _start(self, order):
        return self.client.post(f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/pay/vandapay",
                                headers=self.org_admin_h)

    def _src(self, order):
        with self.db.read_transaction() as c:
            return dict(c.execute("SELECT * FROM order_sources WHERE order_id=?", (order["id"],)).fetchone())

    def test_flag_off_is_404(self):
        order = self._due_order()
        with mock.patch.dict(os.environ, {"VANDAPAY_ORG_CASH_ENABLED": "0"}):
            self.assertEqual(self._start(order).status_code, 404)
        self.assertEqual(self.fake.calls, [])

    def test_full_cash_order_paid_through_vandapay(self):
        order = self._due_order("cash")
        self.assertEqual(order["cash_minor"], order["total_minor"])
        # VAT-on-shipping PIN for the org-order path (decision 11 pending): VAT on merchandise only
        self.assertEqual(order["tax_minor"], order["subtotal_minor"] * order["tax_rate_bps"] // 10_000)
        r = self._start(order)
        self.assertEqual(r.status_code, 201, r.get_json())
        body = r.get_json()
        create = self.fake.calls[-1][3]
        self.assertEqual(create["amount"], order["total_minor"])
        self.assertEqual(sum(i["amount"] for i in create["items"]), create["amount"])
        self.assertEqual(create["metadata"]["org_order_id"], str(order["id"]))
        self.assertEqual(self._src(order)["cash_reference"], f"vandapay-pending:{body['intent_id']}")
        again = self._start(order).get_json()  # idempotent: same intent
        self.assertEqual(again["intent_id"], body["intent_id"])
        # return before payment: nothing changes
        r = self.client.get("/api/v1/payments/vandapay/org-cash/return", query_string={"order_id": order["id"]})
        self.assertIn("payment=pending", r.headers["Location"])
        self.fake.pay(body["intent_id"])
        r = self.client.get("/api/v1/payments/vandapay/org-cash/return", query_string={"order_id": order["id"]})
        self.assertIn("payment=success", r.headers["Location"])
        src = self._src(order)
        self.assertEqual((src["cash_status"], src["cash_reference"]), ("paid", f"vandapay:{body['intent_id']}"))
        self.assertEqual(self.trial_balance()[0], self.trial_balance()[1])
        # webhook afterwards is a no-op
        from app.services import org_cash_vandapay_service as oc
        self.assertEqual(oc.settle_by_intent(self.db, provider=payment_registry.get_payment_provider("vandapay"),
                                             intent_id=body["intent_id"]), "already_paid")

    def test_prepayment_share_single_line_and_late_money_after_manual_confirm_is_returned(self):
        order = self._due_order("prepayment", 3000)
        self.assertLess(order["cash_minor"], order["total_minor"])
        body = self._start(order).get_json()
        create = self.fake.calls[-1][3]
        self.assertEqual(len(create["items"]), 1)
        self.assertEqual(create["items"][0]["amount"], order["cash_minor"])
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/confirm-payment",
                             json={"reference": "WIRE-1"}, headers=self.org_admin_h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.fake.pay(body["intent_id"])  # the payer ALSO paid on VandaPay
        from app.services import org_cash_vandapay_service as oc
        out = oc.settle_by_intent(self.db, provider=payment_registry.get_payment_provider("vandapay"),
                                  intent_id=body["intent_id"])
        self.assertEqual(out, "payment_expired")
        self.assertEqual(self.fake.intents[body["intent_id"]]["status"], "refunded")  # never kept twice

    def test_non_finance_member_cannot_start(self):
        order = self._due_order("cash")
        r = self.client.post(f"/api/v1/orgs/{self.org_id}/orders/{order['id']}/pay/vandapay",
                             headers=self.employee["headers"])
        self.assertEqual(r.status_code, 403, r.get_json())


# ─────────────────────────────────────────────────────── issuer connector stub ──
class IssuerStubTest(AppTestCase):
    SECRET = "issuer_secret_synthetic_0123456789"

    def _post(self, path, body, *, secret=None, key="idem-1", env=None):
        raw = json.dumps(body).encode("utf-8")
        ts = int(time.time())
        headers = {"Content-Type": "application/json",
                   "VandaPay-Signature": f"t={ts},v1={compute_signature(secret or self.SECRET, ts, raw)}"}
        if key:
            headers["Idempotency-Key"] = key
        environ = {"FEDERATED_ISSUER_ENABLED": "1", "FEDERATED_ISSUER_SECRET": self.SECRET} if env is None else env
        with mock.patch.dict(os.environ, environ, clear=False):
            return self.client.post(f"/api/v1/federation/issuer{path}", data=raw, headers=headers)

    AUTH = {"authorization_ref": "lg_1", "customer_phone": "09120000000", "program_ref": "prg_60o_1",
            "amount": 1000, "currency": "IRR", "order_ref": "ORD-1", "merchant_ref": "mer_1"}

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {"FEDERATED_ISSUER_ENABLED": "0"}):
            r = self.client.post("/api/v1/federation/issuer/authorizations", json=self.AUTH)
        self.assertEqual(r.status_code, 404)
        self.assertIsNone(issuer.config({"FEDERATED_ISSUER_ENABLED": "1", "FEDERATED_ISSUER_SECRET": "short"}))

    def test_signature_required(self):
        self.assertEqual(self._post("/authorizations", self.AUTH, secret="wrong_secret_wrong_secret").status_code, 401)

    def test_valid_requests_are_not_implemented_and_move_nothing(self):
        for path, body in (("/eligibility", {"customer_phone": "09120000000", "program_ref": "prg_1", "amount": 5}),
                           ("/authorizations", self.AUTH),
                           ("/authorizations/fa_1/capture", {"amount": 1000}),
                           ("/authorizations/fa_1/void", {}),
                           ("/authorizations/fa_1/refunds", {"amount": 10, "refund_ref": "re_1"})):
            r = self._post(path, body)
            self.assertEqual(r.status_code, 501, (path, r.get_json()))
            self.assertEqual(r.get_json()["error"]["code"], "issuer_not_implemented")

    def test_validation(self):
        self.assertEqual(self._post("/authorizations", dict(self.AUTH, amount=0)).status_code, 422)
        self.assertEqual(self._post("/authorizations", dict(self.AUTH, currency="USD")).status_code, 422)
        self.assertEqual(self._post("/authorizations", dict(self.AUTH, customer_phone="0912")).status_code, 422)
        bad_items = dict(self.AUTH, items=[{"amount": 999, "category": "goods"}])
        self.assertEqual(self._post("/authorizations", bad_items).get_json()["error"]["code"], "items_total_mismatch")
        self.assertEqual(self._post("/authorizations", self.AUTH, key=None).status_code, 400)

    def test_outbound_event_is_signed_with_the_shared_scheme(self):
        from app.adapters.payment.vandapay import verify_signature
        raw, headers = issuer.build_outbound_event("issuer.authorization.expired", {"authorization_id": "fa_1"},
                                                   secret=self.SECRET, now=1_700_000_000, event_id="evt_x")
        verify_signature(raw, headers["SixtyOnline-Signature"], self.SECRET, now=1_700_000_010)
        with self.assertRaises(ValueError):
            issuer.build_outbound_event("issuer.anything", {}, secret=self.SECRET)


if __name__ == "__main__":
    unittest.main()
