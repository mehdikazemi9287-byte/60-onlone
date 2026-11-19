"""Opt-in contract test against actual VandaPay source; no bank or network.

Set VANDAPAY_SOURCE_ROOT and VANDAPAY_TEST_PYTHON. Run separately from the usual
suite. Both apps use fresh SQLite DBs, VandaPay's sandbox PSP and test-only keys.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit

from app.adapters.payment import registry
from app.adapters.payment.vandapay import VandaPayProvider
from app.main import create_app
from tests.base import AppTestCase


@unittest.skipUnless(os.environ.get("VANDAPAY_SOURCE_ROOT") and os.environ.get("VANDAPAY_TEST_PYTHON"),
                     "requires a separate VandaPay source checkout and Python environment")
class VandaPaySourceContractTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(registry.reset_for_tests)
        self.errors = tempfile.TemporaryFile(mode="w+")
        self.addCleanup(self.errors.close)
        root = Path(os.environ["VANDAPAY_SOURCE_ROOT"]).resolve()
        self.peer = subprocess.Popen(
            [os.environ["VANDAPAY_TEST_PYTHON"], str(Path(__file__).parent / "contract/vandapay_peer.py"), str(root)],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
            text=True, encoding="utf-8", bufsize=1,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.addCleanup(self.close_peer)
        config = self.read_peer()
        self.sent = []
        self.settings = dataclasses.replace(self.settings, public_base_url="https://60online.test")
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()
        with self.db.read_transaction() as conn:
            mapping = {r[0]: "goods" for r in conn.execute("SELECT slug FROM categories")}
        self.provider = VandaPayProvider(config["key"], webhook_secret=config["webhook_secret"],
                                        api_base="https://api.test/api/v1", transport=self.transport,
                                        category_map=mapping, shipping_category="services")
        registry.register(self.provider)
        self.app.extensions["vandapay_provider"] = "vandapay"
        _, self.headers = self.new_customer()
        self.kettle = self.product("appliance-kettle-2l")
        for product in (self.kettle, self.product("office-paper-a4-carton")):
            self.assertEqual(self.add_to_cart(self.headers, product["id"], 1).status_code, 201)

    def close_peer(self):
        self.peer.stdin.close()
        try:
            self.peer.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.peer.kill()
            self.peer.wait(timeout=5)
        self.peer.stdout.close()

    def read_peer(self):
        with selectors.DefaultSelector() as sel:
            sel.register(self.peer.stdout, selectors.EVENT_READ)
            if not sel.select(timeout=30):
                self.fail("VandaPay peer timed out")
            line = self.peer.stdout.readline()
        if not line:
            self.errors.seek(0)
            self.fail("VandaPay peer exited: " + self.errors.read()[-4000:])
        return json.loads(line)

    def rpc(self, op, **payload):
        self.peer.stdin.write(json.dumps({"op": op, **payload}) + "\n")
        self.peer.stdin.flush()
        return self.read_peer()

    def transport(self, method, url, headers, body):
        payload = json.loads(body) if body else None
        self.sent.append((method, urlsplit(url).path, payload))
        response = self.rpc("http", method=method, path=urlsplit(url).path, headers=headers, body=payload)
        return response["status"], response["body"]

    def test_restricted_credit_split_order_replay_and_refund(self):
        response = self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS,
            "payment_provider": "vandapay"}, headers={**self.headers, "Idempotency-Key": "source-contract-1"})
        self.assertEqual(response.status_code, 202, response.get_json())
        body = response.get_json()
        with self.db.read_transaction() as conn:
            ref = conn.execute("SELECT provider_ref FROM payment_intents WHERE id=?", (body["payment_intent_id"],)).fetchone()[0]
        payload = self.sent[0][2]
        amount = payload["amount"]
        eligible = next(i["amount"] for i in payload["items"] if i["sku"] == self.kettle["sku"])
        self.assertGreater(amount, eligible)
        funding = self.rpc("fund", intent_id=ref, sku=self.kettle["sku"], amount=amount * 2)
        sources = {s["purse_id"]: s for s in funding["options"]["sources"]}
        travel, goods = funding["purses"]["travel"], funding["purses"]["sku"]
        self.assertFalse(sources[travel]["allowed"])
        self.assertEqual(sources[travel]["max_for_this_payment"], 0)
        self.assertEqual(sources[goods]["max_for_this_payment"], eligible)
        for purse, credit in ((travel, amount), (goods, eligible + 1)):
            allocation = [{"purse_id": purse, "amount": credit}]
            if credit < amount:
                allocation.append({"method": "card", "amount": amount - credit})
            rejected = self.rpc("confirm", intent_id=ref, allocation=allocation, key=f"deny-{purse}")
            self.assertEqual(rejected["status"], 422, rejected)
        allocation = [{"purse_id": goods, "amount": eligible}, {"method": "card", "amount": amount - eligible}]
        confirmed = self.rpc("confirm", intent_id=ref, allocation=allocation, key="correct-split")
        self.assertEqual(confirmed["status"], 200, confirmed)
        self.assertEqual(confirmed["body"]["status"], "card_pending")
        self.rpc("sandbox", url=confirmed["body"]["redirect_url"], outcome="success")
        for _ in range(2):
            callback = self.client.get("/api/v1/payments/vandapay/callback",
                                       query_string={"invoice_id": str(body["payment_intent_id"])})
            self.assertIn("payment=success", callback.headers["Location"])
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 1)
        balances = self.rpc("balances", purse_id=goods)
        self.assertEqual(balances["purse"]["available"], amount * 2 - eligible)
        self.assertEqual(balances["trial"][0], balances["trial"][1])
        # Direct adapter refund; the 60Online return-management workflow is a
        # separate scope and is NOT asserted to update the local order here.
        first = self.provider.refund(ref, body["cash_due_minor"], "contract-full-refund")
        replay = self.provider.refund(ref, body["cash_due_minor"], "contract-full-refund")
        self.assertEqual(first, replay)
        self.assertEqual(self.provider.retrieve(ref)["status"], "refunded")
        balances = self.rpc("balances", purse_id=goods)
        self.assertEqual(balances["purse"]["available"], amount * 2)
        self.assertEqual(balances["trial"][0], balances["trial"][1])
