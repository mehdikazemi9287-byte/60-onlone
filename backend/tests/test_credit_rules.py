"""Unit tests for the eligibility rule engine and the payment state machine.

These touch no database and no HTTP layer, so they pin the business rules
themselves rather than their plumbing.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import ConflictError  # noqa: E402
from app.services import credit_rules, payment_service  # noqa: E402
from app.services.credit_rules import BLOCK, CAP, CartLine, CreditContext, evaluate  # noqa: E402

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _stamp(days: int) -> str:
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _line(category="office", total=10_000_000, quantity=1):
    return CartLine(product_id=1, title_fa="کالا", sku="SKU", category_slug=category,
                    unit_price_minor=total // quantity, quantity=quantity,
                    line_total_minor=total)


def _ctx(**overrides) -> CreditContext:
    defaults = dict(
        now=NOW, organization_status="active", membership_status="active",
        membership_role="employee", allocation_status="active",
        allocated_minor=50_000_000, available_minor=50_000_000,
        valid_from=_stamp(-10), expires_at=_stamp(10), category_slugs=None,
        per_transaction_limit_minor=None, period_limit_minor=None, period_consumed_minor=0,
        lines=[_line(total=30_000_000)], shipping_fee_minor=0, subtotal_minor=30_000_000,
    )
    defaults.update(overrides)
    return CreditContext(**defaults)


class RuleEngineTest(unittest.TestCase):
    def test_happy_path_uses_the_full_order_total(self):
        result = evaluate(_ctx())
        self.assertFalse(result.blocked)
        self.assertEqual(result.usable_minor, 30_000_000)

    def test_available_credit_caps_the_usable_amount(self):
        result = evaluate(_ctx(available_minor=20_000_000))
        self.assertEqual(result.usable_minor, 20_000_000)

    def test_zero_available_credit_blocks(self):
        result = evaluate(_ctx(available_minor=0))
        self.assertTrue(result.blocked)
        self.assertEqual(result.usable_minor, 0)
        self.assertIn("insufficient_credit", [r.code for r in result.blocking])

    def test_suspended_organization_blocks(self):
        for status in ("suspended", "pending", "inactive"):
            result = evaluate(_ctx(organization_status=status))
            self.assertTrue(result.blocked, status)
            self.assertIn("organization_not_active", [r.code for r in result.blocking])

    def test_inactive_membership_blocks(self):
        for status in ("inactive", "invited"):
            result = evaluate(_ctx(membership_status=status))
            self.assertTrue(result.blocked, status)
            self.assertIn("membership_inactive", [r.code for r in result.blocking])

    def test_revoked_or_expired_allocation_status_blocks(self):
        for status in ("revoked", "expired"):
            result = evaluate(_ctx(allocation_status=status))
            self.assertTrue(result.blocked, status)

    def test_expired_credit_blocks(self):
        result = evaluate(_ctx(expires_at=_stamp(-1)))
        self.assertTrue(result.blocked)
        self.assertIn("credit_expired", [r.code for r in result.blocking])

    def test_credit_expiring_exactly_now_is_treated_as_expired(self):
        result = evaluate(_ctx(expires_at=NOW.strftime("%Y-%m-%d %H:%M:%S")))
        self.assertTrue(result.blocked)

    def test_not_yet_valid_credit_blocks(self):
        result = evaluate(_ctx(valid_from=_stamp(1)))
        self.assertTrue(result.blocked)
        self.assertIn("credit_not_started", [r.code for r in result.blocking])

    def test_open_ended_expiry_is_allowed(self):
        result = evaluate(_ctx(expires_at=None))
        self.assertFalse(result.blocked)

    def test_per_transaction_limit_caps(self):
        result = evaluate(_ctx(per_transaction_limit_minor=7_000_000))
        self.assertEqual(result.usable_minor, 7_000_000)

    def test_period_limit_caps_by_the_remainder(self):
        result = evaluate(_ctx(period_limit_minor=25_000_000, period_consumed_minor=18_000_000))
        self.assertEqual(result.usable_minor, 7_000_000)

    def test_exhausted_period_limit_blocks(self):
        result = evaluate(_ctx(period_limit_minor=10_000_000, period_consumed_minor=10_000_000))
        self.assertTrue(result.blocked)
        self.assertIn("period_limit_reached", [r.code for r in result.blocking])

    def test_category_restriction_caps_to_eligible_lines(self):
        ctx = _ctx(
            category_slugs=["office"],
            lines=[_line("office", 12_000_000), _line("laptop", 18_000_000)],
            subtotal_minor=30_000_000,
        )
        self.assertEqual(evaluate(ctx).usable_minor, 12_000_000)

    def test_category_restriction_with_no_eligible_line_blocks(self):
        ctx = _ctx(category_slugs=["office"], lines=[_line("laptop", 30_000_000)])
        result = evaluate(ctx)
        self.assertTrue(result.blocked)
        self.assertIn("category_not_covered", [r.code for r in result.blocking])

    def test_shipping_is_excluded_when_a_category_restriction_applies(self):
        ctx = _ctx(category_slugs=["office"], lines=[_line("office", 30_000_000)],
                   shipping_fee_minor=350_000, subtotal_minor=30_000_000)
        self.assertEqual(evaluate(ctx).usable_minor, 30_000_000)  # not 30,350,000

    def test_shipping_is_included_when_unrestricted(self):
        ctx = _ctx(shipping_fee_minor=350_000, subtotal_minor=30_000_000)
        self.assertEqual(evaluate(ctx).usable_minor, 30_350_000)

    def test_the_tightest_cap_wins(self):
        ctx = _ctx(available_minor=25_000_000, per_transaction_limit_minor=9_000_000,
                   period_limit_minor=40_000_000)
        self.assertEqual(evaluate(ctx).usable_minor, 9_000_000)

    def test_one_block_defeats_every_cap(self):
        ctx = _ctx(organization_status="suspended", available_minor=50_000_000,
                   per_transaction_limit_minor=40_000_000)
        self.assertEqual(evaluate(ctx).usable_minor, 0)

    def test_usable_amount_never_exceeds_the_order_total(self):
        self.assertEqual(evaluate(_ctx(available_minor=999_000_000)).usable_minor, 30_000_000)

    def test_usable_amount_is_never_negative(self):
        self.assertGreaterEqual(evaluate(_ctx(available_minor=1)).usable_minor, 0)

    def test_restrictions_are_serialisable_for_the_api(self):
        for restriction in evaluate(_ctx(available_minor=0)).restrictions:
            data = restriction.to_dict()
            self.assertIn("code", data)
            self.assertIn("message", data)
            self.assertIn(data["kind"], (BLOCK, CAP))

    def test_rule_list_is_extensible_without_touching_evaluate(self):
        """Adding a rule must require only appending to RULES."""
        original = credit_rules.RULES
        try:
            credit_rules.RULES = original + (
                lambda ctx: [credit_rules.Restriction("test_cap", "cap", CAP, 3_000_000)],
            )
            self.assertEqual(evaluate(_ctx()).usable_minor, 3_000_000)
        finally:
            credit_rules.RULES = original

    def test_parse_category_slugs(self):
        self.assertIsNone(credit_rules.parse_category_slugs(None))
        self.assertIsNone(credit_rules.parse_category_slugs(""))
        self.assertIsNone(credit_rules.parse_category_slugs("not json"))
        self.assertIsNone(credit_rules.parse_category_slugs("[]"))
        self.assertEqual(credit_rules.parse_category_slugs('["office"]'), ["office"])


class PaymentStateMachineTest(unittest.TestCase):
    def test_declared_transitions(self):
        self.assertEqual(payment_service.VALID_TRANSITIONS["pending"],
                         {"authorized", "failed", "cancelled"})
        self.assertEqual(payment_service.VALID_TRANSITIONS["authorized"],
                         {"captured", "failed", "cancelled"})

    def test_terminal_states_have_no_exits(self):
        for terminal in ("captured", "failed", "cancelled"):
            self.assertEqual(payment_service.VALID_TRANSITIONS[terminal], set())

    def test_every_state_is_declared(self):
        states = set(payment_service.VALID_TRANSITIONS)
        self.assertEqual(states, {"pending", "authorized", "captured", "failed", "cancelled"})
        for targets in payment_service.VALID_TRANSITIONS.values():
            self.assertTrue(targets <= states)

    def test_reference_format(self):
        reference = payment_service.new_reference()
        self.assertTrue(reference.startswith("PI-"))
        self.assertNotEqual(reference, payment_service.new_reference())


if __name__ == "__main__":
    unittest.main()
