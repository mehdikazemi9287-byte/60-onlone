"""Split payment: quote, checkout, ledger, concurrency, failure handling.

The headline test is `test_section_17_scenario`, which is the exact end-to-end
walk-through required by the Phase 2 brief.
"""
from __future__ import annotations

import sys
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import ApiError  # noqa: E402
from app.services import checkout_service, ledger_service  # noqa: E402
from tests.base import AppTestCase  # noqa: E402


def _stamp(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


class SplitPaymentBase(AppTestCase):
    """A cart worth exactly 30,000,000 IRR subtotal with free shipping.

    laptop-hp-probook-450 is repriced to 30,000,000 and stocked, so the
    arithmetic in these tests matches the brief's example exactly.

    v6: total_minor = subtotal + shipping + tax (STANDARD 10% = 1000 bps).
    """

    CART_TOTAL = 30_000_000                           # product price = subtotal
    TAX_MINOR = CART_TOTAL * 1000 // 10000            # 3,000,000 at 10% STANDARD
    CART_TOTAL_WITH_TAX = CART_TOTAL + TAX_MINOR      # 33,000,000

    def setUp(self):
        super().setUp()
        self.product = self.product("laptop-hp-probook-450")
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE products SET base_price_minor = ? WHERE id = ?",
                (self.CART_TOTAL, self.product["id"]),
            )
        self.set_stock(self.product["id"], 50)
        self.product = self.product_by_slug("laptop-hp-probook-450")

    def product_by_slug(self, slug: str) -> dict:
        return self.client.get(f"/api/v1/products/{slug}").get_json()["product"]

    def fill_cart(self, headers: dict, quantity: int = 1):
        response = self.add_to_cart(headers, self.product["id"], quantity)
        self.assertEqual(response.status_code, 201, response.get_json())
        cart = self.client.get("/api/v1/cart", headers=headers).get_json()
        # Above the free-shipping threshold, so total == subtotal.
        self.assertEqual(cart["shipping_fee_minor"], 0)
        return cart


class QuoteTest(SplitPaymentBase):
    def test_retail_customer_quote_is_all_cash(self):
        _, headers = self.new_customer()
        self.fill_cart(headers)
        quote = self.quote(headers)
        self.assertFalse(quote["has_organization_credit"])
        self.assertEqual(quote["credit_to_use_minor"], 0)
        # v6: total includes VAT — all paid in cash for a retail customer
        self.assertEqual(quote["cash_due_minor"], self.CART_TOTAL_WITH_TAX)
        self.assertEqual(quote["payment_method"], "card")

    def test_partial_credit_produces_a_split_quote(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        # v6: total is VAT-inclusive (33,000,000); credit 20m, cash covers the rest
        self.assertEqual(quote["cart"]["total_minor"], self.CART_TOTAL_WITH_TAX)
        self.assertEqual(quote["credit_to_use_minor"], 20_000_000)
        self.assertEqual(quote["cash_due_minor"], self.CART_TOTAL_WITH_TAX - 20_000_000)
        self.assertEqual(quote["final_payable_minor"], self.CART_TOTAL_WITH_TAX)
        self.assertEqual(quote["payment_method"], "split")

    def test_ample_credit_covers_the_whole_order(self):
        _, _, _, employee = self.org_fixture(credit_minor=200_000_000)
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        # v6: credit covers the full VAT-inclusive total when ample
        self.assertEqual(quote["credit_to_use_minor"], self.CART_TOTAL_WITH_TAX)
        self.assertEqual(quote["cash_due_minor"], 0)
        self.assertEqual(quote["payment_method"], "credit")

    def test_credit_never_exceeds_the_order_total(self):
        _, _, _, employee = self.org_fixture(credit_minor=500_000_000)
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], quote["cart"]["total_minor"])

    def test_quote_always_balances(self):
        for credit in (0, 5_000_000, 20_000_000, 30_000_000, 90_000_000):
            with self.subTest(credit=credit):
                _, _, _, employee = self.org_fixture(credit_minor=credit or None) \
                    if credit else (None, None, None, None)
                if credit == 0:
                    _, headers = self.new_customer()
                else:
                    headers = employee["headers"]
                self.fill_cart(headers)
                quote = self.quote(headers)
                self.assertEqual(
                    quote["credit_to_use_minor"] + quote["cash_due_minor"],
                    quote["cart"]["total_minor"],
                )

    def test_empty_cart_quote_is_zero(self):
        _, _, _, employee = self.org_fixture(credit_minor=50_000_000)
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["cart"]["total_minor"], 0)
        self.assertEqual(quote["credit_to_use_minor"], 0)

    def test_quote_requires_authentication(self):
        self.assertEqual(self.client.get("/api/v1/checkout/quote").status_code, 401)


class SplitCheckoutTest(SplitPaymentBase):
    def test_section_17_scenario(self):
        """Org A, employee Alice, 20m credit, 30m subtotal → 33m total (VAT) → 20m credit + 13m cash."""
        org = self.create_organization(name="سازمان الف", credit_limit_minor=1_000_000_000)
        org_admin, _ = self.make_org_admin(org["id"])
        alice = self.add_employee(org["id"], org_admin, email="alice.s17@example.com")

        allocation = self.allocate(org["id"], org_admin, alice["id"], 20_000_000)
        self.assertEqual(allocation.status_code, 201)

        # Alice logs in and buys goods worth 30,000,000 (+ 3,000,000 VAT = 33,000,000 total).
        self.fill_cart(alice["headers"])
        quote = self.quote(alice["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 20_000_000)
        # v6: cash = VAT-inclusive total - credit = 33m - 20m = 13m
        self.assertEqual(quote["cash_due_minor"], self.CART_TOTAL_WITH_TAX - 20_000_000)

        response = self.checkout(alice["headers"])
        self.assertEqual(response.status_code, 201, response.get_json())
        order = response.get_json()["order"]

        # order total = 33m (VAT-inclusive), funded 20m credit + 13m cash
        self.assertEqual(order["total_minor"], self.CART_TOTAL_WITH_TAX)
        self.assertEqual(order["credit_minor"], 20_000_000)
        self.assertEqual(order["cash_minor"], self.CART_TOTAL_WITH_TAX - 20_000_000)
        self.assertEqual(order["status"], "paid")

        # only 20m credit consumed
        wallet = self.client.get("/api/v1/me/credit", headers=alice["headers"]).get_json()
        self.assertEqual(wallet["total_available_minor"], 0)
        self.assertEqual(wallet["allocations"][0]["consumed_minor"], 20_000_000)
        self.assertEqual(wallet["allocations"][0]["reserved_minor"], 0)

        # PSP charged only the cash portion (13m)
        payment = self.db.query_one(
            "SELECT amount_minor, status FROM payments WHERE order_id = ?", (order["id"],)
        )
        self.assertEqual(payment["amount_minor"], self.CART_TOTAL_WITH_TAX - 20_000_000)
        self.assertEqual(payment["status"], "captured")

        # credit ledger is correct
        entries = self.db.query(
            "SELECT entry_type, amount_minor FROM credit_ledger_entries "
            "WHERE organization_id = ? ORDER BY id", (org["id"],)
        )
        self.assertEqual(
            [(e["entry_type"], e["amount_minor"]) for e in entries],
            [("allocation", 20_000_000), ("reservation", 20_000_000), ("capture", 20_000_000)],
        )

        # financial ledger is balanced, and names both funding sources
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)
        with self.db.read_transaction() as conn:
            legs = ledger_service.entries_for_reference(conn, f"order:{order['order_number']}")
        by_account = {l["account_code"]: (l["direction"], l["amount_minor"]) for l in legs}
        self.assertEqual(by_account[ledger_service.ACCOUNT_PSP_CLEARING],
                         ("debit", self.CART_TOTAL_WITH_TAX - 20_000_000))
        self.assertEqual(by_account[ledger_service.ACCOUNT_ORG_RECEIVABLE], ("debit", 20_000_000))
        # v6: sales revenue = subtotal only; VAT goes to the VAT payable account
        self.assertEqual(by_account[ledger_service.ACCOUNT_SALES_REVENUE],
                         ("credit", self.CART_TOTAL))

        # order ownership is correct
        self.assertEqual(
            self.client.get(f"/api/v1/orders/{order['order_number']}",
                            headers=alice["headers"]).status_code, 200
        )

        # the organization sees the order
        org_orders = self.client.get(
            f"/api/v1/organizations/{org['id']}/orders", headers=org_admin
        ).get_json()
        self.assertEqual(org_orders["total"], 1)
        self.assertEqual(org_orders["items"][0]["order_number"], order["order_number"])
        self.assertEqual(org_orders["items"][0]["credit_minor"], 20_000_000)
        self.assertEqual(org_orders["items"][0]["cash_minor"],
                         self.CART_TOTAL_WITH_TAX - 20_000_000)

        # another organization cannot see it
        other = self.create_organization(name="سازمان ب")
        other_admin, _ = self.make_org_admin(other["id"])
        other_orders = self.client.get(
            f"/api/v1/organizations/{other['id']}/orders", headers=other_admin
        ).get_json()
        self.assertEqual(other_orders["total"], 0)
        # and its admin cannot reach org A's endpoint at all
        self.assertEqual(
            self.client.get(f"/api/v1/organizations/{org['id']}/orders",
                            headers=other_admin).status_code, 404
        )

    def test_full_credit_purchase_charges_the_psp_nothing(self):
        _, _, _, employee = self.org_fixture(credit_minor=200_000_000)
        self.fill_cart(employee["headers"])
        order = self.checkout(employee["headers"]).get_json()["order"]
        # v6: ample credit covers the full VAT-inclusive total (33m)
        self.assertEqual(order["credit_minor"], self.CART_TOTAL_WITH_TAX)
        self.assertEqual(order["cash_minor"], 0)
        self.assertIsNone(
            self.db.query_one("SELECT id FROM payments WHERE order_id = ?", (order["id"],))
        )
        with self.db.read_transaction() as conn:
            legs = ledger_service.entries_for_reference(conn, f"order:{order['order_number']}")
        codes = {l["account_code"] for l in legs}
        self.assertIn(ledger_service.ACCOUNT_ORG_RECEIVABLE, codes)
        self.assertNotIn(ledger_service.ACCOUNT_PSP_CLEARING, codes)
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)

    def test_zero_credit_purchase_is_plain_flow_1(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)  # member, but no allocation
        self.fill_cart(employee["headers"])
        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertEqual(order["credit_minor"], 0)
        # v6: VAT-inclusive total all paid in cash
        self.assertEqual(order["cash_minor"], self.CART_TOTAL_WITH_TAX)
        payment = self.db.query_one(
            "SELECT amount_minor FROM payments WHERE order_id = ?", (order["id"],)
        )
        self.assertEqual(payment["amount_minor"], self.CART_TOTAL_WITH_TAX)

    def test_order_is_linked_to_the_funding_organization(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.fill_cart(employee["headers"])
        order = self.checkout(employee["headers"]).get_json()["order"]
        row = self.db.query_one("SELECT organization_id FROM orders WHERE id = ?", (order["id"],))
        self.assertEqual(row["organization_id"], org["id"])

    def test_split_payment_order_is_audited(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.fill_cart(employee["headers"])
        self.checkout(employee["headers"])
        row = self.db.query_one(
            "SELECT COUNT(*) n FROM audit_logs WHERE action = 'order.split_payment'"
        )
        self.assertEqual(row["n"], 1)

    def test_organization_summary_reports_utilisation(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.fill_cart(employee["headers"])
        self.checkout(employee["headers"])
        summary = self.client.get(
            f"/api/v1/organizations/{org['id']}/summary", headers=org_admin
        ).get_json()
        self.assertEqual(summary["orders"]["count"], 1)
        self.assertEqual(summary["orders"]["funded_by_credit_minor"], 20_000_000)
        # v6: cash = VAT-inclusive total - credit = 33m - 20m = 13m
        self.assertEqual(summary["orders"]["funded_by_cash_minor"],
                         self.CART_TOTAL_WITH_TAX - 20_000_000)
        self.assertEqual(summary["organization"]["consumed_total_minor"], 20_000_000)


class CreditEligibilityCheckoutTest(SplitPaymentBase):
    def test_expired_credit_is_not_used(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 50_000_000,
                      valid_from=_stamp(-10), expires_at=_stamp(-1))
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 0)
        self.assertIn("credit_expired", [r["code"] for r in quote["restrictions"]])

        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertEqual(order["credit_minor"], 0)
        # v6: VAT-inclusive total all paid in cash
        self.assertEqual(order["cash_minor"], self.CART_TOTAL_WITH_TAX)

    def test_credit_not_yet_started_is_not_used(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 50_000_000, valid_from=_stamp(5))
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 0)
        self.assertIn("credit_not_started", [r["code"] for r in quote["restrictions"]])

    def test_suspended_organization_blocks_credit(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=50_000_000)
        self.client.patch(f"/api/v1/organizations/{org['id']}",
                          json={"status": "suspended"}, headers=org_admin)
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 0)
        self.assertIn("organization_not_active", [r["code"] for r in quote["restrictions"]])
        order = self.checkout(employee["headers"]).get_json()["order"]
        # v6: VAT-inclusive total all paid in cash when org is suspended
        self.assertEqual(order["cash_minor"], self.CART_TOTAL_WITH_TAX)

    def test_inactive_membership_blocks_credit(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=50_000_000)
        self.client.patch(
            f"/api/v1/organizations/{org['id']}/members/{employee['id']}",
            json={"status": "inactive"}, headers=org_admin,
        )
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 0)
        self.assertIn("membership_inactive", [r["code"] for r in quote["restrictions"]])

    def test_per_transaction_limit_caps_credit(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 50_000_000,
                      per_transaction_limit_minor=8_000_000)
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 8_000_000)
        # v6: cash = VAT-inclusive total (33m) - credit (8m) = 25m
        self.assertEqual(quote["cash_due_minor"], self.CART_TOTAL_WITH_TAX - 8_000_000)
        self.assertIn("per_transaction_limit", [r["code"] for r in quote["restrictions"]])

        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertEqual(order["credit_minor"], 8_000_000)
        self.assertEqual(order["cash_minor"], self.CART_TOTAL_WITH_TAX - 8_000_000)

    def test_period_limit_caps_credit(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 50_000_000,
                      period_limit_minor=12_000_000)
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 12_000_000)

    def test_category_restricted_credit_only_covers_eligible_lines(self):
        """Allocation restricted to 'office'; the cart holds a 'laptop'."""
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 50_000_000,
                      category_slugs=["office"])
        self.fill_cart(employee["headers"])  # laptop-hp-probook-450 -> category 'laptop'
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 0)
        self.assertIn("category_not_covered", [r["code"] for r in quote["restrictions"]])

    def test_category_restricted_credit_covers_a_matching_line(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 50_000_000,
                      category_slugs=["laptop"])
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 30_000_000)

    def test_category_restriction_caps_to_the_eligible_subtotal_in_a_mixed_cart(self):
        org = self.create_organization()
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 900_000_000,
                      category_slugs=["office"])
        paper = self.product_by_slug("office-paper-a4-carton")  # 14,500,000, category 'office'
        self.fill_cart(employee["headers"])                     # 30,000,000, category 'laptop'
        self.add_to_cart(employee["headers"], paper["id"], 2)   # 29,000,000 eligible

        quote = self.quote(employee["headers"])
        # v6: total = (30m laptop + 29m office) subtotal + VAT(10%) + 0 shipping
        # subtotal = 59m, tax = 5,900,000, total = 64,900,000
        _subtotal = 30_000_000 + 29_000_000
        _tax = _subtotal * 1000 // 10000
        _total = _subtotal + _tax
        self.assertEqual(quote["cart"]["total_minor"], _total)
        # credit restricted to office category: eligible lines = 29m (pre-tax)
        self.assertEqual(quote["credit_to_use_minor"], 29_000_000)
        # cash = total - credit
        self.assertEqual(quote["cash_due_minor"], _total - 29_000_000)

        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertEqual(order["credit_minor"], 29_000_000)
        self.assertEqual(order["cash_minor"], _total - 29_000_000)
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)

    def test_revoked_allocation_is_not_used(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=50_000_000)
        self.client.post(
            f"/api/v1/organizations/{org['id']}/credit-allocations/"
            f"{employee['allocation']['id']}/revoke",
            headers=org_admin,
        )
        self.fill_cart(employee["headers"])
        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 0)


class SingleAllocationLimitationTest(SplitPaymentBase):
    """Documents a KNOWN Phase 2 limitation, so it cannot regress silently.

    An order is funded from exactly one allocation. When an employee holds
    several grants, the one yielding the largest usable amount is chosen and
    the rest are untouched. Combining allocations is Phase 3 work; see
    AUDIT_EVIDENCE.md.
    """

    def test_only_the_largest_usable_allocation_funds_an_order(self):
        org = self.create_organization(credit_limit_minor=1_000_000_000)
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        self.allocate(org["id"], org_admin, employee["id"], 12_000_000)
        self.allocate(org["id"], org_admin, employee["id"], 8_000_000)

        wallet = self.client.get("/api/v1/me/credit", headers=employee["headers"]).get_json()
        self.assertEqual(wallet["total_available_minor"], 20_000_000)

        self.fill_cart(employee["headers"])  # 30,000,000 subtotal → 33,000,000 total (VAT)
        quote = self.quote(employee["headers"])
        # NOT 20,000,000: the two grants are not combined. Largest single grant is 12m.
        self.assertEqual(quote["credit_to_use_minor"], 12_000_000)
        # v6: cash = VAT-inclusive total (33m) - credit (12m) = 21m
        self.assertEqual(quote["cash_due_minor"], self.CART_TOTAL_WITH_TAX - 12_000_000)

        order = self.checkout(employee["headers"]).get_json()["order"]
        self.assertEqual(order["credit_minor"], 12_000_000)

        after = self.client.get("/api/v1/me/credit", headers=employee["headers"]).get_json()
        self.assertEqual(after["total_available_minor"], 8_000_000)
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)


class PaymentFailureTest(SplitPaymentBase):
    """The mock PSP declines when the charged amount ends in 13."""

    def test_failed_payment_releases_the_credit_reservation(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=20_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_103, self.product["id"]))
        self.add_to_cart(employee["headers"], self.product["id"], 1)

        quote = self.quote(employee["headers"])
        self.assertEqual(quote["credit_to_use_minor"], 20_000_000)
        self.assertEqual(quote["cash_due_minor"] % 100, 13)  # will be declined

        response = self.checkout(employee["headers"])
        self.assertEqual(response.status_code, 402)

        wallet = self.client.get("/api/v1/me/credit", headers=employee["headers"]).get_json()
        self.assertEqual(wallet["total_available_minor"], 20_000_000)
        self.assertEqual(wallet["allocations"][0]["reserved_minor"], 0)
        self.assertEqual(wallet["allocations"][0]["consumed_minor"], 0)

        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM orders WHERE organization_id = ?",
                              (org["id"],))["n"], 0
        )
        entry_types = [
            r["entry_type"] for r in self.db.query(
                "SELECT entry_type FROM credit_ledger_entries WHERE organization_id = ? ORDER BY id",
                (org["id"],))
        ]
        self.assertEqual(entry_types, ["allocation", "reservation", "release"])

    def test_failed_payment_restores_stock(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_103, self.product["id"]))
        before = self.product_by_slug("laptop-hp-probook-450")["quantity_available"]
        # quantity 1 keeps the cash leg ending in 13, which the mock declines
        self.add_to_cart(employee["headers"], self.product["id"], 1)
        self.assertEqual(self.checkout(employee["headers"]).status_code, 402)
        after = self.product_by_slug("laptop-hp-probook-450")["quantity_available"]
        self.assertEqual(after, before)

    def test_failed_payment_leaves_the_cart_intact_for_a_retry(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_103, self.product["id"]))
        self.add_to_cart(employee["headers"], self.product["id"], 1)
        self.checkout(employee["headers"])
        cart = self.client.get("/api/v1/cart", headers=employee["headers"]).get_json()
        self.assertEqual(cart["item_count"], 1)

    def test_payment_intent_records_the_failure(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_103, self.product["id"]))
        self.add_to_cart(employee["headers"], self.product["id"], 1)
        self.checkout(employee["headers"])
        intent = self.db.query_one(
            "SELECT status, failure_reason FROM payment_intents ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(intent["status"], "failed")
        self.assertIsNotNone(intent["failure_reason"])

    def test_retry_after_a_failure_succeeds(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_103, self.product["id"]))
        self.add_to_cart(employee["headers"], self.product["id"], 1)
        self.assertEqual(self.checkout(employee["headers"]).status_code, 402)

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_000, self.product["id"]))
        self.client.patch(f"/api/v1/cart/items/{self.product['id']}",
                          json={"quantity": 1}, headers=employee["headers"])
        response = self.checkout(employee["headers"])  # a fresh idempotency key
        self.assertEqual(response.status_code, 201, response.get_json())


class IdempotencyTest(SplitPaymentBase):
    def test_replaying_a_split_checkout_does_not_double_spend_credit(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.fill_cart(employee["headers"])
        key = uuid.uuid4().hex
        first = self.checkout(employee["headers"], key=key)
        second = self.checkout(employee["headers"], key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.get_json()["order"]["order_number"],
                         second.get_json()["order"]["order_number"])

        wallet = self.client.get("/api/v1/me/credit", headers=employee["headers"]).get_json()
        self.assertEqual(wallet["allocations"][0]["consumed_minor"], 20_000_000)
        captures = self.db.query_one(
            "SELECT COUNT(*) n FROM credit_ledger_entries WHERE entry_type = 'capture'"
        )
        self.assertEqual(captures["n"], 1)

    def test_replaying_a_failed_split_checkout_returns_the_same_failure(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE products SET base_price_minor = ? WHERE id = ?",
                         (30_000_103, self.product["id"]))
        self.add_to_cart(employee["headers"], self.product["id"], 1)
        key = uuid.uuid4().hex
        first = self.checkout(employee["headers"], key=key)
        second = self.checkout(employee["headers"], key=key)
        self.assertEqual(first.status_code, 402)
        self.assertEqual(second.status_code, 402)
        releases = self.db.query_one(
            "SELECT COUNT(*) n FROM credit_ledger_entries WHERE entry_type = 'release'"
        )
        self.assertEqual(releases["n"], 1)

    def test_only_one_ledger_transaction_per_replayed_checkout(self):
        _, _, _, employee = self.org_fixture(credit_minor=20_000_000)
        self.fill_cart(employee["headers"])
        key = uuid.uuid4().hex
        self.checkout(employee["headers"], key=key)
        self.checkout(employee["headers"], key=key)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM ledger_transactions")["n"], 1
        )
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)


class CreditRaceConditionTest(SplitPaymentBase):
    """Two simultaneous purchases competing for the same remaining credit."""

    def test_two_concurrent_checkouts_cannot_spend_the_same_credit_twice(self):
        org = self.create_organization(credit_limit_minor=1_000_000_000)
        org_admin, _ = self.make_org_admin(org["id"])
        employee = self.add_employee(org["id"], org_admin)
        # Exactly enough credit for ONE of the two carts.
        self.allocate(org["id"], org_admin, employee["id"], 30_000_000)
        user_id = employee["user_id"]

        # Two independent carts is not possible for one user, so both threads
        # race on the same cart: whichever loses must not consume credit.
        self.fill_cart(employee["headers"], quantity=2)

        results: list[object] = []
        barrier = threading.Barrier(2)

        def attempt() -> None:
            barrier.wait()
            try:
                status, _ = checkout_service.checkout(
                    self.db, user_id=user_id, user_email=employee["email"],
                    address=self.DEFAULT_ADDRESS, idempotency_key=uuid.uuid4().hex,
                    payment_provider_name="mock",
                )
                results.append(status)
            except ApiError as exc:
                results.append(exc)
            finally:
                self.db.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = [r for r in results if r == 201]
        self.assertEqual(len(successes), 1, f"expected exactly one winner, got {results}")

        # Credit must never be over-consumed or go negative.
        with self.db.read_transaction() as conn:
            from app.services.credit_service import allocation_state

            allocation = conn.execute(
                "SELECT id FROM credit_allocations WHERE organization_id = ?", (org["id"],)
            ).fetchone()
            state = allocation_state(conn, int(allocation["id"]))
        self.assertGreaterEqual(state["available_minor"], 0)
        self.assertLessEqual(state["consumed_minor"], 30_000_000)
        self.assertEqual(state["reserved_minor"], 0)

        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM orders WHERE organization_id = ?",
                              (org["id"],))["n"], 1
        )
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)

    def test_credit_available_never_goes_negative_under_repeated_purchases(self):
        org, org_admin, _, employee = self.org_fixture(credit_minor=45_000_000)
        cheap = self.product_by_slug("appliance-kettle-2l")
        for _ in range(6):
            self.add_to_cart(employee["headers"], cheap["id"], 2)
            self.checkout(employee["headers"])
        wallet = self.client.get("/api/v1/me/credit", headers=employee["headers"]).get_json()
        self.assertGreaterEqual(wallet["total_available_minor"], 0)
        self.assertLessEqual(wallet["allocations"][0]["consumed_minor"], 45_000_000)
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits)


if __name__ == "__main__":
    unittest.main()
