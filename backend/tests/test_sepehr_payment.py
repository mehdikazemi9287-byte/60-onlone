"""Sepehr redirect gateway: checkout → bank page → callback → Advice → order.

The bank is a fake injected into the adapter; no network is used.
"""
from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.payment import registry as payment_registry  # noqa: E402
from app.adapters.payment.sepehr import SepehrPaymentProvider, to_rial  # noqa: E402
from app.core.config import ConfigError, _validate_payment_config  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.base import AppTestCase  # noqa: E402

TERMINAL = "98765432"


class FakeSepehr:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.token_response = {"Status": 0, "AccessToken": "tok-abc"}
        self.advice_response = None  # default: Ok with the paid amount
        self.paid_amount = None

    def __call__(self, url: str, payload: dict) -> dict:
        op = url.rsplit("/", 1)[-1]
        self.calls.append((op, dict(payload)))
        if op == "GetToken":
            self.paid_amount = payload["Amount"]
            return dict(self.token_response)
        if op == "Advice":
            return self.advice_response or {"Status": "Ok", "ReturnId": self.paid_amount, "Message": "ok"}
        if op == "Rollback":
            return {"Status": "Ok", "ReturnId": self.paid_amount}
        raise AssertionError(url)

    def ops(self) -> list[str]:
        return [op for op, _ in self.calls]


class SepehrTestBase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.settings = dataclasses.replace(
            self.settings, payment_provider="sepehr", sepehr_terminal_id=TERMINAL,
            public_base_url="https://60online.test",
        )
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()
        self.bank = FakeSepehr()
        payment_registry.register(SepehrPaymentProvider(TERMINAL, http_post=self.bank))
        self.token, self.headers = self.new_customer()
        self.kettle = self.product("appliance-kettle-2l")
        self.assertEqual(self.add_to_cart(self.headers, self.kettle["id"], 2).status_code, 201)

    # ----------------------------------------------------------- helpers
    def start(self, key: str = "k-1"):
        return self.checkout(self.headers, key=key)

    def callback(self, intent_id: int, *, respcode="0", amount=None, receipt="RCPT-1", method="post"):
        data = {
            "respcode": respcode, "respmsg": "test", "amount": str(self.bank.paid_amount if amount is None else amount),
            "invoiceid": str(intent_id), "terminalid": TERMINAL, "tracenumber": "111",
            "rrn": "222", "digitalreceipt": receipt,
        }
        url = "/api/v1/payments/sepehr/callback"
        return self.client.post(url, data=data) if method == "post" else self.client.get(url, query_string=data)

    def intent(self, intent_id: int):
        with self.db.read_transaction() as conn:
            return conn.execute("SELECT * FROM payment_intents WHERE id = ?", (intent_id,)).fetchone()

    def order_count(self) -> int:
        with self.db.read_transaction() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]



class SepehrCheckoutTest(SepehrTestBase):
    def test_checkout_returns_bank_redirect_without_creating_an_order(self):
        res = self.start()
        self.assertEqual(res.status_code, 202, res.get_json())
        body = res.get_json()
        redirect = body["payment_redirect"]
        self.assertEqual(redirect["method"], "POST")
        self.assertEqual(redirect["fields"], {"TerminalID": TERMINAL, "token": "tok-abc"})
        token_call = self.bank.calls[0][1]
        self.assertEqual(token_call["InvoiceID"], body["payment_intent_id"])
        self.assertEqual(token_call["Amount"], to_rial(body["cash_due_minor"], body["currency"]))
        self.assertEqual(token_call["callbackURL"], "https://60online.test/api/v1/payments/sepehr/callback")
        self.assertEqual(self.order_count(), 0)
        self.assertEqual(self.intent(body["payment_intent_id"])["status"], "authorized")
        stock = self.product("appliance-kettle-2l")["quantity_available"]
        self.assertEqual(stock, self.kettle["quantity_available"] - 2)

    def test_successful_payment_creates_one_paid_order_even_if_callback_repeats(self):
        intent_id = self.start().get_json()["payment_intent_id"]
        res = self.callback(intent_id)
        self.assertEqual(res.status_code, 303)
        target = urlparse(res.headers["Location"])
        self.assertTrue(target.path.startswith("/orders/ORD-"), target)
        self.assertEqual(parse_qs(target.query)["payment"], ["success"])
        self.assertEqual(self.intent(intent_id)["status"], "captured")
        self.assertEqual(self.order_count(), 1)
        order_number = target.path.rsplit("/", 1)[-1]
        order = self.client.get(f"/api/v1/orders/{order_number}", headers=self.headers).get_json()["order"]
        self.assertEqual(order["status"], "paid")

        again = self.callback(intent_id, method="get")
        self.assertEqual(urlparse(again.headers["Location"]).path, target.path)
        self.assertEqual(self.order_count(), 1)
        self.assertEqual(self.bank.ops().count("Advice"), 1)

        # the same checkout key now replays the finished order
        replay = self.start()
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.get_json()["order"]["order_number"], order_number)

    def test_cancelled_on_bank_page_releases_stock_and_never_calls_advice(self):
        intent_id = self.start().get_json()["payment_intent_id"]
        res = self.callback(intent_id, respcode="-1", receipt="")
        query = parse_qs(urlparse(res.headers["Location"]).query)
        self.assertEqual(query["payment"], ["failed"])
        self.assertEqual(self.intent(intent_id)["status"], "failed")
        self.assertNotIn("Advice", self.bank.ops())
        self.assertEqual(self.product("appliance-kettle-2l")["quantity_available"], self.kettle["quantity_available"])
        self.assertEqual(self.order_count(), 0)
        self.assertEqual(self.start().status_code, 402)  # same key replays the stored failure

    def test_tampered_amount_is_rejected_and_reversed(self):
        intent_id = self.start().get_json()["payment_intent_id"]
        self.callback(intent_id, amount=1000)
        self.assertEqual(self.intent(intent_id)["status"], "failed")
        self.assertNotIn("Advice", self.bank.ops())
        self.assertIn("Rollback", self.bank.ops())
        self.assertEqual(self.order_count(), 0)

    def test_advice_failure_reverses_and_fails(self):
        self.bank.advice_response = {"Status": "Nok", "ReturnId": -1, "Message": "x"}
        intent_id = self.start().get_json()["payment_intent_id"]
        self.callback(intent_id)
        self.assertEqual(self.intent(intent_id)["status"], "failed")
        self.assertIn("Rollback", self.bank.ops())
        self.assertEqual(self.order_count(), 0)

    def test_advice_amount_mismatch_is_not_accepted(self):
        intent_id = self.start().get_json()["payment_intent_id"]
        self.bank.advice_response = {"Status": "Ok", "ReturnId": 1000}
        self.callback(intent_id)
        self.assertEqual(self.intent(intent_id)["status"], "failed")
        self.assertEqual(self.order_count(), 0)

    def test_retrying_checkout_while_on_bank_page_returns_same_session(self):
        first = self.start()
        second = self.start()
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.get_json(), first.get_json())
        self.assertEqual(self.bank.ops().count("GetToken"), 1)

    def test_gateway_refusal_fails_cleanly(self):
        self.bank.token_response = {"Status": -1}
        res = self.start()
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.get_json()["error"]["code"], "payment_gateway_unavailable")
        self.assertEqual(self.product("appliance-kettle-2l")["quantity_available"], self.kettle["quantity_available"])

    def test_callback_for_unknown_invoice_is_reversed(self):
        res = self.callback(999999)
        self.assertEqual(parse_qs(urlparse(res.headers["Location"]).query)["reason"], ["unknown_payment"])
        self.assertIn("Rollback", self.bank.ops())

    def test_late_callback_after_intent_released_gives_money_back(self):
        intent_id = self.start().get_json()["payment_intent_id"]
        from app.services import payment_service
        with self.db.write_transaction() as conn:
            payment_service.reclaim_stale_intent(conn, intent_id, actor_user_id=None)
        res = self.callback(intent_id)
        self.assertEqual(parse_qs(urlparse(res.headers["Location"]).query)["reason"], ["payment_expired"])
        self.assertIn("Rollback", self.bank.ops())
        self.assertEqual(self.order_count(), 0)


class AbandonedBankVisitTest(SepehrTestBase):
    def age(self, intent_id: int, minutes: int):
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE payment_intents SET created_at = datetime('now', ?) WHERE id = ?",
                (f"-{minutes} minutes", intent_id),
            )

    def test_abandoned_visit_is_released_and_a_late_payment_reversed(self):
        from app.services import checkout_service
        intent_id = self.start().get_json()["payment_intent_id"]
        self.age(intent_id, 10)
        self.assertEqual(checkout_service.release_abandoned_redirects(self.db), 0)  # still on the bank page
        self.age(intent_id, 31)
        self.assertEqual(checkout_service.release_abandoned_redirects(self.db), 1)
        self.assertEqual(self.intent(intent_id)["status"], "failed")
        self.assertEqual(self.product("appliance-kettle-2l")["quantity_available"], self.kettle["quantity_available"])
        res = self.callback(intent_id)
        self.assertEqual(parse_qs(urlparse(res.headers["Location"]).query)["reason"], ["payment_expired"])
        self.assertIn("Rollback", self.bank.ops())
        self.assertEqual(self.order_count(), 0)

    def test_next_checkout_sweeps_old_abandoned_visits(self):
        intent_id = self.start(key="old").get_json()["payment_intent_id"]
        self.age(intent_id, 45)
        self.assertEqual(self.start(key="new").status_code, 202)
        self.assertEqual(self.intent(intent_id)["status"], "failed")


class SepehrConfigTest(unittest.TestCase):
    def test_requires_terminal_and_https_origin(self):
        with self.assertRaises(ConfigError):
            _validate_payment_config("sepehr", "", "https://60online.ir")
        with self.assertRaises(ConfigError):
            _validate_payment_config("sepehr", TERMINAL, "http://60online.ir")
        with self.assertRaises(ConfigError):
            _validate_payment_config("zarinpal", "", "")
        _validate_payment_config("sepehr", TERMINAL, "https://60online.ir")
        _validate_payment_config("mock", "", "")


if __name__ == "__main__":
    unittest.main()
