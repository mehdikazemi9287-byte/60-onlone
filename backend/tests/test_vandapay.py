"""VandaPay («پرداخت با ونداپی»): adapter, checkout redirect flow and signed webhook.

All VandaPay traffic goes to ``FakeVandaPay`` (an in-memory, clearly synthetic stand-in for the merchant
API); nothing touches the network. Webhook signature cases come from VandaPay's shared vectors,
copied unchanged into tests/fixtures/vandapay_webhook_vectors.json (source: vandapay repo,
integrations/test-vectors/webhook.json).
"""
from __future__ import annotations

import dataclasses
import json
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.adapters.payment import registry as payment_registry
from app.adapters.payment.base import GatewayError, PaymentRequest, PaymentStatus
from app.adapters.payment.sepehr import to_rial
from app.adapters.payment.vandapay import (
    VandaPayPending, VandaPayProvider, WebhookSignatureError, compute_signature, enabled_from_env,
    verify_signature,
)
from app.main import create_app
from tests.base import AppTestCase

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "vandapay_webhook_vectors.json").read_text("utf-8"))
WH_SECRET = "whsec_synthetic_test_only"
API = "https://vandapay.test/api/v1"


class FakeVandaPay:
    """Synthetic VandaPay merchant API (test-only data)."""

    def __init__(self, mode="test"):
        self.mode, self.intents, self.calls, self.down, self.n = mode, {}, [], False, 0
        self.idem: dict[str, dict] = {}

    def __call__(self, method, url, headers, body):
        path = url[len(API):]
        payload = json.loads(body) if body else None
        self.calls.append((method, path, headers.get("Idempotency-Key"), payload))
        if self.down:
            raise GatewayError("vandapay unreachable: URLError")
        if method == "POST" and path == "/payment_intents":
            key = headers["Idempotency-Key"]
            if key in self.idem:
                return 201, self.idem[key]
            self.n += 1
            pid = f"pi_fake{self.n}"
            self.intents[pid] = {"id": pid, "status": "created", "amount": payload["amount"], "currency": "IRR",
                                 "mode": self.mode, "order_ref": payload["order_ref"],
                                 "metadata": payload.get("metadata") or {}, "refunded_amount": 0}
            resp = {**self.intents[pid], "checkout_url": f"https://pay.vandapay.test/pay/{pid}?t=ct_x"}
            self.idem[key] = resp
            return 201, resp
        parts = path.strip("/").split("/")
        intent = self.intents.get(parts[1]) if len(parts) > 1 else None
        if intent is None:
            return 404, {"error": {"code": "intent_not_found", "message": "یافت نشد"}}
        if method == "GET":
            return 200, dict(intent)
        if parts[-1] == "cancel":
            if intent["status"] not in ("created", "requires_confirmation"):
                return 409, {"error": {"code": "invalid_state"}}
            intent["status"] = "canceled"
            return 200, dict(intent)
        if parts[-1] == "refunds":
            intent["refunded_amount"] += payload["amount"]
            intent["status"] = "refunded" if intent["refunded_amount"] >= intent["amount"] else "partially_refunded"
            return 201, {"id": "re_fake1", "status": "succeeded", "amount": payload["amount"]}
        return 400, {"error": {"code": "bad_request"}}

    def pay(self, pid, status="succeeded"):
        self.intents[pid]["status"] = status


def _provider(fake, key="sk_test_synthetic"):
    return VandaPayProvider(key, webhook_secret=WH_SECRET, api_base=API, transport=fake)


class VandaPayAdapterTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeVandaPay()
        self.vp = _provider(self.fake)
        self.req = PaymentRequest(amount_minor=1_200_000, currency="IRR", order_reference="intent:7",
                                  idempotency_key="u:k", customer_email="a@example.test")
        self.ins = self.vp.initiate(self.req, invoice_id=7, callback_url="https://60online.test/api/v1/payments/vandapay/callback")
        self.ref = self.ins.provider_ref
        self.cb = {"invoice_id": "7", "_provider_ref": self.ref, "pi": "pi_attacker", "status": "succeeded"}

    def test_initiate_redirect_and_deterministic_key(self):
        self.assertEqual(self.ins.method, "GET")
        self.assertTrue(self.ins.url.startswith("https://pay.vandapay.test/pay/"))
        _, path, key, body = self.fake.calls[0]
        self.assertEqual(key, "60online-intent:7-invoice-7")
        self.assertEqual(body["amount"], 1_200_000)
        self.assertEqual(parse_qs(urlparse(body["return_url"]).query)["invoice_id"], ["7"])
        again = self.vp.initiate(self.req, invoice_id=7, callback_url="https://60online.test/cb")
        self.assertEqual(self.fake.calls[1][2], key)  # same key on retry → same intent
        self.assertEqual(again.provider_ref, self.ref)

    def test_toman_is_converted_to_rial(self):
        req = dataclasses.replace(self.req, currency="IRT", amount_minor=120_000, order_reference="intent:8")
        self.vp.initiate(req, invoice_id=8, callback_url="https://60online.test/cb")
        self.assertEqual(self.fake.calls[-1][3]["amount"], 1_200_000)

    def test_happy_path_uses_stored_ref_not_browser_status(self):
        self.fake.pay(self.ref)
        res = self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")
        self.assertEqual(res.status, PaymentStatus.CAPTURED)
        self.assertEqual(res.provider_ref, self.ref)
        self.assertEqual(self.fake.calls[-1][:2], ("GET", f"/payment_intents/{self.ref}"))

    def test_callback_status_alone_is_never_success(self):
        with self.assertRaises(VandaPayPending):  # API still says "created" although ?status=succeeded
            self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")

    def test_amount_mismatch(self):
        self.fake.pay(self.ref)
        res = self.vp.verify(self.cb, expected_amount_minor=1_100_000, currency="IRR")
        self.assertEqual((res.status, res.failure_reason), (PaymentStatus.FAILED, "amount_mismatch"))

    def test_currency_mismatch(self):
        self.fake.pay(self.ref)
        self.fake.intents[self.ref]["currency"] = "USD"
        res = self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")
        self.assertEqual(res.failure_reason, "amount_mismatch")

    def test_pending_statuses_are_not_paid(self):
        for status in ("processing", "card_pending", "unknown", "requires_confirmation", "something_new"):
            self.fake.pay(self.ref, status)
            with self.assertRaises(VandaPayPending, msg=status):
                self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")

    def test_failed_statuses(self):
        for status in ("failed", "expired", "canceled", "refunded", "partially_refunded"):
            self.fake.pay(self.ref, status)
            res = self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")
            self.assertEqual(res.status, PaymentStatus.FAILED, status)

    def test_mode_mismatch(self):
        self.fake.pay(self.ref)
        self.fake.intents[self.ref]["mode"] = "live"
        res = self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")
        self.assertEqual(res.failure_reason, "mode_mismatch")
        with self.assertRaises(GatewayError):  # initiate refuses an intent of the other mode too
            live_fake = FakeVandaPay(mode="live")
            _provider(live_fake).initiate(self.req, invoice_id=7, callback_url="https://x.test/cb")

    def test_invoice_mismatch_and_missing_ref(self):
        self.fake.pay(self.ref)
        res = self.vp.verify({**self.cb, "invoice_id": "8"}, expected_amount_minor=1_200_000, currency="IRR")
        self.assertEqual(res.failure_reason, "invoice_mismatch")
        res = self.vp.verify({"invoice_id": "7", "pi": self.ref}, expected_amount_minor=1_200_000, currency="IRR")
        self.assertEqual(res.failure_reason, "missing_reference")

    def test_gateway_unreachable(self):
        self.fake.down = True
        with self.assertRaises(GatewayError):
            self.vp.verify(self.cb, expected_amount_minor=1_200_000, currency="IRR")
        with self.assertRaises(GatewayError):
            self.vp.initiate(dataclasses.replace(self.req, order_reference="intent:9"), invoice_id=9,
                             callback_url="https://x.test/cb")
        self.assertFalse(self.vp.reverse(self.cb))

    def test_reverse_cancels_unpaid_and_refunds_paid(self):
        self.assertTrue(self.vp.reverse(self.cb))
        self.assertEqual(self.fake.intents[self.ref]["status"], "canceled")
        self.assertEqual(self.fake.calls[-1][2], f"60online-{self.ref}-cancel")
        ins2 = self.vp.initiate(dataclasses.replace(self.req, order_reference="intent:10"), invoice_id=10,
                                callback_url="https://x.test/cb")
        self.fake.pay(ins2.provider_ref)
        self.assertTrue(self.vp.reverse({"_provider_ref": ins2.provider_ref}))
        method, path, key, body = self.fake.calls[-1]
        self.assertEqual((path, key, body["amount"]),
                         (f"/payment_intents/{ins2.provider_ref}/refunds", f"60online-{ins2.provider_ref}-reverse-1200000", 1_200_000))
        self.assertEqual(self.fake.intents[ins2.provider_ref]["status"], "refunded")

    def test_reverse_ignores_browser_supplied_ids(self):
        self.assertFalse(self.vp.reverse({"invoice_id": "7", "pi": self.ref}))
        self.assertEqual(self.fake.intents[self.ref]["status"], "created")

    def test_refund(self):
        self.fake.pay(self.ref)
        res = self.vp.refund(self.ref, 500_000, "r1")
        self.assertEqual(res.status, PaymentStatus.REFUNDED)
        self.assertEqual(self.fake.calls[-1][2], f"60online-{self.ref}-refund-r1")


class VandaPaySignatureVectorsTest(unittest.TestCase):
    def test_sign_vectors(self):
        for v in VECTORS["sign_vectors"]:
            self.assertEqual(compute_signature(v["secret"], v["timestamp"], v["body"]), v["signature"])

    def test_verify_cases(self):
        for case in VECTORS["verify_cases"]:
            with self.subTest(case["name"]):
                if case["valid"]:
                    verify_signature(case["body"].encode("utf-8"), case["header"], VECTORS["secret"], now=case["now"])
                else:
                    with self.assertRaises(WebhookSignatureError) as ctx:
                        verify_signature(case["body"].encode("utf-8"), case["header"], VECTORS["secret"], now=case["now"])
                    self.assertEqual(ctx.exception.reason, case["error"])


class VandaPayEnvTest(unittest.TestCase):
    BASE = {"VANDAPAY_SECRET_KEY": "sk_test_x", "VANDAPAY_WEBHOOK_SECRET": "whsec_x"}

    def test_disabled_by_default_and_without_secrets(self):
        self.assertIsNone(enabled_from_env({}, app_env="development"))
        self.assertIsNone(enabled_from_env({"VANDAPAY_SECRET_KEY": "sk_test_x"}, app_env="development"))
        self.assertIsNone(enabled_from_env({**self.BASE, "VANDAPAY_ENABLED": "0"}, app_env="development"))

    def test_test_key_enabled_outside_production(self):
        p = enabled_from_env(self.BASE, app_env="development")
        self.assertEqual((p.name, p.mode), ("vandapay", "test"))

    def test_live_key_only_in_production_and_test_key_not_in_production(self):
        live = {**self.BASE, "VANDAPAY_SECRET_KEY": "sk_live_x"}
        self.assertIsNone(enabled_from_env(live, app_env="staging"))
        self.assertEqual(enabled_from_env(live, app_env="production").mode, "live")
        self.assertIsNone(enabled_from_env(self.BASE, app_env="production"))
        self.assertIsNotNone(enabled_from_env(self.BASE, app_env="production", demo_mode=True))

    def test_https_and_key_prefix_required(self):
        self.assertIsNone(enabled_from_env({**self.BASE, "VANDAPAY_API_BASE": "http://insecure"}, app_env="development"))
        self.assertIsNone(enabled_from_env({**self.BASE, "VANDAPAY_SECRET_KEY": "pk_x"}, app_env="development"))


class VandaPayCheckoutTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.settings = dataclasses.replace(self.settings, public_base_url="https://60online.test")
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()
        self.fake = FakeVandaPay()
        payment_registry.register(_provider(self.fake))
        self.app.extensions["vandapay_provider"] = "vandapay"
        _, self.headers = self.new_customer()
        kettle = self.product("appliance-kettle-2l")
        self.assertEqual(self.add_to_cart(self.headers, kettle["id"], 1).status_code, 201)

    def tearDown(self):
        payment_registry.reset_for_tests()
        super().tearDown()

    def _start(self, key="vp-1"):
        r = self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS, "payment_provider": "vandapay"},
                             headers={**self.headers, "Idempotency-Key": key})
        self.assertEqual(r.status_code, 202, r.get_json())
        body = r.get_json()
        return body, body["payment_redirect"]["url"].split("/pay/")[1].split("?")[0]

    def _orders(self):
        with self.db.read_transaction() as conn:
            return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def _webhook(self, event, *, ts=None, secret=WH_SECRET, header=None):
        raw = json.dumps(event, ensure_ascii=False).encode("utf-8")
        ts = int(time.time()) if ts is None else ts
        header = header if header is not None else f"t={ts},v1={compute_signature(secret, ts, raw)}"
        return self.client.post("/api/v1/payments/vandapay/webhook", data=raw,
                                headers={"Content-Type": "application/json", "VandaPay-Signature": header})

    def test_option_listed_only_when_enabled(self):
        opts = self.client.get("/api/v1/checkout/payment-options").get_json()["options"]
        self.assertIn({"provider": "vandapay", "label": "پرداخت با ونداپی"},
                      [{"provider": o["provider"], "label": o["label"]} for o in opts])
        self.app.extensions["vandapay_provider"] = None
        opts = self.client.get("/api/v1/checkout/payment-options").get_json()["options"]
        self.assertNotIn("vandapay", [o["provider"] for o in opts])
        r = self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS, "payment_provider": "vandapay"},
                             headers={**self.headers, "Idempotency-Key": "vp-off"})
        self.assertEqual(r.get_json()["error"]["code"], "payment_provider_unavailable")
        self.assertEqual(self._webhook({"id": "evt_x", "type": "webhook.test", "data": {}}).status_code, 404)

    def test_browser_return_happy_path_and_replay(self):
        body, pid = self._start()
        create = self.fake.calls[0][3]
        self.assertEqual(create["amount"], to_rial(body["cash_due_minor"], body["currency"]))
        self.assertEqual(create["order_ref"], f"intent:{body['payment_intent_id']}")
        self.fake.pay(pid)
        cb = {"invoice_id": str(body["payment_intent_id"]), "pi": pid, "status": "succeeded"}
        r = self.client.get("/api/v1/payments/vandapay/callback", query_string=cb)
        self.assertEqual(r.status_code, 303)
        self.assertIn("payment=success", r.headers["Location"])
        self.assertEqual(self._orders(), 1)
        self.client.get("/api/v1/payments/vandapay/callback", query_string=cb)
        self.assertEqual(self._orders(), 1)

    def test_browser_cannot_inject_trusted_ref_or_fake_status(self):
        body, pid = self._start()
        other_pid = "pi_other"
        self.fake.intents[other_pid] = {**self.fake.intents[pid], "id": other_pid, "status": "succeeded"}
        cb = {"invoice_id": str(body["payment_intent_id"]), "_provider_ref": other_pid, "status": "succeeded"}
        r = self.client.get("/api/v1/payments/vandapay/callback", query_string=cb)
        self.assertIn("reason=verify_unavailable", r.headers["Location"])  # ours is still "created" → pending
        self.assertEqual(self._orders(), 0)
        self.assertEqual(self.fake.intents[other_pid]["status"], "succeeded")  # untouched

    def test_failed_payment_creates_no_order(self):
        body, pid = self._start()
        self.fake.pay(pid, "failed")
        r = self.client.get("/api/v1/payments/vandapay/callback", query_string={"invoice_id": str(body["payment_intent_id"])})
        self.assertIn("payment=failed", r.headers["Location"])
        self.assertEqual(self._orders(), 0)

    def test_amount_mismatch_refunds(self):
        body, pid = self._start()
        self.fake.pay(pid)
        self.fake.intents[pid]["amount"] -= 1000
        self.client.get("/api/v1/payments/vandapay/callback", query_string={"invoice_id": str(body["payment_intent_id"])})
        self.assertEqual(self._orders(), 0)
        self.assertEqual(self.fake.intents[pid]["status"], "refunded")  # money given back

    def test_gateway_unreachable_on_initiate(self):
        self.fake.down = True
        r = self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS, "payment_provider": "vandapay"},
                             headers={**self.headers, "Idempotency-Key": "vp-down"})
        self.assertEqual(r.get_json()["error"]["code"], "payment_gateway_unavailable")

    def test_webhook_completes_order_and_dedupes(self):
        body, pid = self._start()
        self.fake.pay(pid)
        evt = {"id": "evt_1", "type": "payment_intent.succeeded",
               "data": {"id": pid, "status": "succeeded", "amount": 1, "metadata": {"invoice_id": "999"}}}
        r = self._webhook(evt)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["outcome"], "ok")
        self.assertEqual(self._orders(), 1)
        r = self._webhook(evt)
        self.assertEqual(r.get_json()["outcome"], "duplicate")
        self.assertEqual(self._orders(), 1)
        with self.db.read_transaction() as conn:
            stored = conn.execute("SELECT raw_payload FROM webhook_events WHERE provider_code='vandapay'").fetchall()
        self.assertEqual(len(stored), 1)
        self.assertNotIn("customer_phone", stored[0]["raw_payload"])

    def test_refund_webhook_opens_one_finance_review_item(self):
        # SO-4 (review 2026-11-12): a panel refund is tracked for finance with a deadline, once per event
        body, pid = self._start()
        self.fake.pay(pid)
        self._webhook({"id": "evt_pay", "type": "payment_intent.succeeded", "data": {"id": pid, "status": "succeeded"}})
        self.fake.intents[pid]["status"] = "refunded"
        evt = {"id": "evt_ref", "type": "refund.succeeded", "data": {"intent_id": pid, "amount": 5000, "status": "succeeded"}}
        r = self._webhook(evt)
        self.assertEqual((r.status_code, r.get_json()["outcome"]), (200, "refund_review_opened"))
        self.assertEqual(self._webhook(evt).get_json()["outcome"], "duplicate")
        with self.db.read_transaction() as conn:
            rows = conn.execute("SELECT * FROM external_refund_reviews WHERE event_id='evt_ref'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["owner_role"], rows[0]["amount_minor"]), ("open", "finance", 5000))
        self.assertTrue(rows[0]["due_at"])
        self.assertEqual(self._orders(), 1)  # the order itself is not silently changed

    def test_webhook_bad_and_stale_signatures_change_nothing(self):
        body, pid = self._start()
        self.fake.pay(pid)
        evt = {"id": "evt_2", "type": "payment_intent.succeeded", "data": {"id": pid}}
        self.assertEqual(self._webhook(evt, secret="whsec_wrong").status_code, 400)
        self.assertEqual(self._webhook(evt, ts=int(time.time()) - 301).status_code, 400)
        self.assertEqual(self._webhook(evt, header="").status_code, 400)
        r = self._webhook(evt, header="t=1,v1=" + "0" * 64)
        self.assertEqual(r.get_json()["error"]["reason"], "timestamp_out_of_tolerance")
        self.assertEqual(self._orders(), 0)
        self.assertEqual([c for c in self.fake.calls if c[0] == "GET"], [])  # never even looked up

    def test_webhook_rereads_api_and_retries_when_not_final(self):
        body, pid = self._start()
        evt = {"id": "evt_3", "type": "payment_intent.succeeded", "data": {"id": pid, "status": "succeeded"}}
        r = self._webhook(evt)  # event claims success but the API still says "created"
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self._orders(), 0)
        self.fake.down = True
        self.assertEqual(self._webhook(evt).status_code, 503)
        self.fake.down = False
        self.fake.pay(pid)
        self.assertEqual(self._webhook(evt).get_json()["outcome"], "ok")  # retry of the same event id works
        self.assertEqual(self._orders(), 1)

    def test_webhook_failed_event_releases_and_unknown_intent_ignored(self):
        body, pid = self._start()
        self.fake.pay(pid, "expired")
        r = self._webhook({"id": "evt_4", "type": "payment_intent.expired", "data": {"id": pid}})
        self.assertEqual(r.get_json()["outcome"], "payment_failed")
        with self.db.read_transaction() as conn:
            st = conn.execute("SELECT status FROM payment_intents WHERE id=?", (body["payment_intent_id"],)).fetchone()[0]
        self.assertNotEqual(st, "authorized")
        r = self._webhook({"id": "evt_5", "type": "payment_intent.succeeded", "data": {"id": "pi_not_ours"}})
        self.assertEqual(r.get_json()["outcome"], "unknown_intent")

    def test_late_success_after_release_is_refunded(self):
        body, pid = self._start()
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE payment_intents SET status='failed' WHERE id=?", (body["payment_intent_id"],))
        self.fake.pay(pid)
        r = self._webhook({"id": "evt_6", "type": "payment_intent.succeeded", "data": {"id": pid}})
        self.assertEqual(r.get_json()["outcome"], "payment_expired")
        self.assertEqual(self.fake.intents[pid]["status"], "refunded")
        self.assertEqual(self._orders(), 0)


if __name__ == "__main__":
    unittest.main()
