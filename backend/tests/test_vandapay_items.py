"""Synthetic fixtures only: policy basket accounting and authoritative checkout snapshot."""
from __future__ import annotations

import dataclasses
import json
import unittest
from unittest.mock import patch

from app.adapters.payment import registry
from app.adapters.payment.base import GatewayError, PaymentRequest, PaymentStatus
from app.adapters.payment.vandapay import VandaPayProvider, enabled_from_env
from app.adapters.payment.vandapay_items import SHIPPING_SKU, build_items
from app.main import create_app
from tests.base import AppTestCase
from tests import test_vandapay as vp


def snapshot():
    return {"subtotal_minor": 203, "tax_minor": 20, "shipping_fee_minor": 31,
            "total_minor": 254, "credit_minor": 0, "welfare_minor": 0,
            "items": [
                {"sku": "A", "title_fa": "کالای الف", "category_slug": "food", "quantity": 1,
                 "unit_price_minor": 101, "line_total_minor": 101},
                {"sku": "B", "title_fa": "کالای ب", "category_slug": "clothes", "quantity": 2,
                 "unit_price_minor": 101, "line_total_minor": 202},
            ]}


def request(basket=None, currency="IRR"):
    basket = snapshot() if basket is None else basket
    return PaymentRequest(basket["total_minor"], currency, "intent:1", "test-1", "test@example.test",
                          metadata={"basket": basket})


class VandaPayItemsTest(unittest.TestCase):
    MAP = {"food": "goods.food", "clothes": "goods.clothing"}

    def build(self, basket=None, currency="IRR", shipping="services.delivery"):
        return build_items(request(basket, currency), self.MAP, shipping)

    def test_discount_tax_and_shipping_are_exact_and_categories_stay_separate(self):
        items = self.build()
        self.assertEqual([i["amount"] for i in items], [75, 148, 31])
        self.assertEqual([i["category"] for i in items], ["goods.food", "goods.clothing", "services.delivery"])
        self.assertEqual([i["sku"] for i in items], ["A", "B", SHIPPING_SKU])
        self.assertEqual(items[1]["quantity"], 2)  # amount is line total, not unit price

    def test_toman_conversion_occurs_once_after_allocation(self):
        self.assertEqual([i["amount"] for i in self.build(currency="IRT")], [750, 1480, 310])

    def test_every_discount_amount_conserves_order_total_without_negative_lines(self):
        for discount in range(304):
            basket = snapshot()
            basket["subtotal_minor"] = 303 - discount
            basket["tax_minor"] = 0
            basket["total_minor"] = 334 - discount
            items = self.build(basket)
            self.assertEqual(sum(i["amount"] for i in items), basket["total_minor"])
            self.assertTrue(all(i["amount"] > 0 for i in items))

    def test_missing_shipping_mapping_does_not_charge_delivery_to_goods_credit(self):
        with self.assertRaises(GatewayError):
            self.build(shipping=None)

    def test_unknown_categories_and_invalid_sku_or_line_values_fail_closed(self):
        for key, value in [("category_slug", "travel"), ("sku", SHIPPING_SKU), ("sku", "x" * 65),
                           ("quantity", True), ("quantity", 10001), ("line_total_minor", 100)]:
            with self.subTest(key=key, value=value):
                basket = snapshot()
                basket["items"][0][key] = value
                with self.assertRaises(GatewayError):
                    self.build(basket)

    def test_local_funding_needs_per_item_source_and_cannot_be_prorated(self):
        for key in ("credit_minor", "welfare_minor"):
            basket = snapshot()
            basket[key] = 1
            with self.subTest(key=key), self.assertRaises(GatewayError):
                self.build(basket)

    def test_inconsistent_total_and_missing_snapshot_are_rejected(self):
        basket = snapshot()
        basket["total_minor"] += 1
        with self.assertRaises(GatewayError):
            self.build(basket)
        with self.assertRaises(GatewayError):
            build_items(dataclasses.replace(request(), metadata={}), self.MAP, "services.delivery")

    def test_shipping_counts_toward_fifty_line_limit(self):
        basket = snapshot()
        basket["items"] = [dict(basket["items"][0], sku=f"SKU-{i}") for i in range(50)]
        basket.update(subtotal_minor=5050, tax_minor=0, total_minor=5081)
        with self.assertRaises(GatewayError):
            self.build(basket)
        basket.update(shipping_fee_minor=0, total_minor=5050)
        self.assertEqual(len(self.build(basket)), 50)

    def test_strict_mode_sends_items_but_legacy_payload_stays_compatible(self):
        fake = vp.FakeVandaPay()
        provider = VandaPayProvider("sk_test_synthetic", webhook_secret=vp.WH_SECRET,
                                   api_base=vp.API, transport=fake, category_map=self.MAP,
                                   shipping_category="services.delivery")
        provider.initiate(request(), invoice_id=1, callback_url="https://shop.test/cb")
        self.assertEqual(fake.calls[-1][3]["items"], self.build())
        self.assertEqual(fake.calls[-1][3]["metadata"], {"source": "60online", "invoice_id": "1"})
        vp._provider(fake).initiate(request(), invoice_id=2, callback_url="https://shop.test/cb")
        self.assertNotIn("items", fake.calls[-1][3])

    def test_invalid_config_disables_provider_instead_of_falling_back(self):
        base = {"VANDAPAY_SECRET_KEY": "sk_test_synthetic", "VANDAPAY_WEBHOOK_SECRET": vp.WH_SECRET}
        for value in ("", "{", "{}", "null", "[]", '{"food":true}', '{"food":""}'):
            with self.subTest(value=value):
                self.assertIsNone(enabled_from_env({**base, "VANDAPAY_CATEGORY_MAP": value}, app_env="test"))
        self.assertIsNotNone(enabled_from_env({**base, "VANDAPAY_CATEGORY_MAP": json.dumps(self.MAP)}, app_env="test"))

    def test_refund_requires_success_exact_amount_and_reference(self):
        calls = []
        for response in [{"status": "pending", "id": "re_1", "amount": 100},
                         {"status": "succeeded", "id": "re_1", "amount": 99},
                         {"status": "succeeded", "id": "re_1", "amount": True},
                         {"status": "succeeded", "amount": 100}]:
            def send(method, url, headers, body):
                calls.append(headers["Idempotency-Key"])
                return 202, response
            provider = VandaPayProvider("sk_test_synthetic", webhook_secret=vp.WH_SECRET, transport=send)
            with self.subTest(response=response), self.assertRaises(GatewayError):
                provider.refund("pi_1", 100, "same-key")
        self.assertEqual(len(set(calls)), 1)  # ambiguous outcomes retry with identical key
        provider = VandaPayProvider("sk_test_synthetic", webhook_secret=vp.WH_SECRET, currency="IRT",
                                   transport=lambda *args: (201, {"status": "succeeded", "id": "re_1", "amount": 1000}))
        self.assertEqual(provider.refund("pi_1", 100, "same-key").status, PaymentStatus.REFUNDED)

    def test_reverse_does_not_accept_a_mismatched_refund(self):
        fake = vp.FakeVandaPay()
        provider = vp._provider(fake)
        instruction = provider.initiate(request(), invoice_id=1, callback_url="https://shop.test/cb")
        fake.pay(instruction.provider_ref)
        def bad_refund(method, url, headers, body):
            status, result = fake(method, url, headers, body)
            if url.endswith("/refunds"):
                result["amount"] -= 1
            return status, result
        provider._send = bad_refund
        self.assertFalse(provider.reverse({"_provider_ref": instruction.provider_ref}))


class VandaPayItemsCheckoutTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.settings = dataclasses.replace(self.settings, public_base_url="https://60online.test")
        self.app = create_app(self.settings, self.db)
        self.client = self.app.test_client()
        self.fake = vp.FakeVandaPay()
        with self.db.read_transaction() as conn:
            mapping = {r[0]: "goods" for r in conn.execute("SELECT slug FROM categories")}
        self.provider = VandaPayProvider("sk_test_synthetic", webhook_secret=vp.WH_SECRET,
                                        api_base=vp.API, transport=self.fake, category_map=mapping,
                                        shipping_category="services")
        registry.register(self.provider)
        self.app.extensions["vandapay_provider"] = "vandapay"
        _, self.headers = self.new_customer()
        self.kettle = self.product("appliance-kettle-2l")
        self.assertEqual(self.add_to_cart(self.headers, self.kettle["id"], 1).status_code, 201)

    def tearDown(self):
        registry.reset_for_tests()
        super().tearDown()

    def checkout(self, **extra):
        return self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS,
            "payment_provider": "vandapay", **extra}, headers={**self.headers, "Idempotency-Key": "strict-items-1"})

    def test_client_cannot_supply_policy_items_or_category(self):
        response = self.checkout(items=[{"sku": "FAKE", "category": "travel", "amount": 1}],
                                 category="travel", metadata={"basket": snapshot()})
        self.assertEqual(response.status_code, 202, response.get_json())
        sent = self.fake.calls[-1][3]
        self.assertEqual(sum(i["amount"] for i in sent["items"]), sent["amount"])
        self.assertTrue(all(i["category"] in ("goods", "services") for i in sent["items"]))
        self.assertNotIn("FAKE", [i["sku"] for i in sent["items"]])
        self.assertEqual(sent["items"][0]["sku"], self.kettle["sku"])

    def test_redeemed_coins_reduce_saved_merchandise_before_gateway_credit(self):
        from app.services import loyalty_service
        user = self.client.get("/api/v1/auth/me", headers=self.headers).get_json()["user"]
        loyalty_service.earn(self.db, user_id=user["id"], amount_coins=100, source="campaign",
                             idempotency_key="synthetic-pilot-coins")
        response = self.checkout(redeem_coins=10)
        self.assertEqual(response.status_code, 202, response.get_json())
        with self.db.read_transaction() as conn:
            intent = conn.execute("SELECT * FROM payment_intents WHERE id=?",
                                  (response.get_json()["payment_intent_id"],)).fetchone()
            gross = conn.execute("SELECT SUM(line_total_minor) FROM payment_intent_items WHERE payment_intent_id=?",
                                 (intent["id"],)).fetchone()[0]
        self.assertEqual(intent["redeem_discount_minor"], 100_000)
        self.assertEqual(intent["subtotal_minor"], gross - 100_000)
        sent = self.fake.calls[-1][3]
        merchandise = next(i for i in sent["items"] if i["sku"] == self.kettle["sku"])
        self.assertEqual(merchandise["amount"], gross - 100_000 + intent["tax_minor"])
        self.assertEqual(sum(i["amount"] for i in sent["items"]), intent["total_minor"])

    def test_unknown_mapping_releases_inventory_before_any_gateway_request(self):
        self.provider._category_map = {"unrelated": "travel"}
        with self.db.read_transaction() as conn:
            before = conn.execute("SELECT quantity_available FROM inventory WHERE product_id = ?", (self.kettle["id"],)).fetchone()[0]
        response = self.checkout()
        self.assertEqual(response.get_json()["error"]["code"], "payment_gateway_unavailable")
        self.assertEqual(self.fake.calls, [])
        with self.db.read_transaction() as conn:
            after = conn.execute("SELECT quantity_available FROM inventory WHERE product_id = ?", (self.kettle["id"],)).fetchone()[0]
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
        self.assertEqual(after, before)

    def test_gateway_uses_reserved_snapshot_even_if_cart_changes_before_initiate(self):
        from app.services import checkout_service
        original = checkout_service._start_redirect
        def mutate_cart_then_initiate(*args, **kwargs):
            with self.db.write_transaction() as conn:
                conn.execute("UPDATE cart_items SET quantity = 9")
            return original(*args, **kwargs)
        with patch.object(checkout_service, "_start_redirect", side_effect=mutate_cart_then_initiate):
            response = self.checkout()
        self.assertEqual(response.status_code, 202, response.get_json())
        self.assertEqual(self.fake.calls[-1][3]["items"][0]["quantity"], 1)

    def test_local_credit_is_released_when_item_funding_cannot_be_proven(self):
        _, _, _, employee = self.org_fixture(credit_minor=100_000)
        self.headers = employee["headers"]
        self.add_to_cart(self.headers, self.kettle["id"], 1)
        before = self.quote(self.headers)["credit_to_use_minor"]
        self.assertEqual(before, 100_000)
        response = self.checkout()
        self.assertEqual(response.get_json()["error"]["code"], "payment_gateway_unavailable")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.quote(self.headers)["credit_to_use_minor"], before)

    def test_local_welfare_is_restored_on_item_policy_refusal(self):
        from app.services import welfare_wallet_service as welfare
        org, _, _, employee = self.org_fixture(credit_minor=0)
        self.headers = employee["headers"]
        self.add_to_cart(self.headers, self.kettle["id"], 1)
        with self.db.write_transaction() as conn:
            welfare.create_plan(conn, organization_id=org["id"], idempotency_key="pilot-welfare",
                                actor_user_id=None, payload={"title": "آزمون", "plan_type": "free",
                                "per_employee_cap_minor": 100_000, "expires_at": "2099-01-01"})
        response = self.checkout(use_welfare=True)
        self.assertEqual(response.get_json()["error"]["code"], "payment_gateway_unavailable")
        self.assertEqual(self.fake.calls, [])
        with self.db.read_transaction() as conn:
            self.assertEqual(welfare.member_summary(conn, employee["user_id"])["remaining_minor"], 100_000)
