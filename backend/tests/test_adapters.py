from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.credit.base import CreditOutcome  # noqa: E402
from app.adapters.credit.mock import MockCreditProvider  # noqa: E402
from app.adapters.payment.base import PaymentRequest, PaymentStatus  # noqa: E402
from app.adapters.payment.mock import MockPaymentProvider  # noqa: E402
from app.adapters.payment.registry import get_payment_provider  # noqa: E402


def _request(amount: int, key: str = "k1") -> PaymentRequest:
    return PaymentRequest(
        amount_minor=amount, currency="IRR", order_reference="ORD-1",
        idempotency_key=key, customer_email="a@b.co",
    )


class MockPaymentProviderTest(unittest.TestCase):
    def setUp(self):
        self.provider = MockPaymentProvider()

    def test_successful_charge(self):
        result = self.provider.charge(_request(1_000_000))
        self.assertEqual(result.status, PaymentStatus.CAPTURED)
        self.assertTrue(result.succeeded)
        self.assertTrue(result.provider_ref.startswith("mockpay_"))

    def test_charge_is_idempotent(self):
        first = self.provider.charge(_request(1_000_000, "same-key"))
        second = self.provider.charge(_request(1_000_000, "same-key"))
        self.assertEqual(first, second)

    def test_declined_amount_rule(self):
        result = self.provider.charge(_request(1_013))
        self.assertEqual(result.status, PaymentStatus.FAILED)
        self.assertFalse(result.succeeded)
        self.assertIsNotNone(result.failure_reason)

    def test_zero_amount_fails(self):
        self.assertFalse(self.provider.charge(_request(0)).succeeded)

    def test_refund_is_idempotent(self):
        a = self.provider.refund("mockpay_x", 500, "r1")
        b = self.provider.refund("mockpay_x", 500, "r1")
        self.assertEqual(a, b)
        self.assertEqual(a.status, PaymentStatus.REFUNDED)

    def test_registry_returns_mock_and_rejects_unknown(self):
        self.assertEqual(get_payment_provider("mock").name, "mock")
        with self.assertRaises(KeyError):
            get_payment_provider("stripe")


class MockCreditProviderTest(unittest.TestCase):
    def setUp(self):
        self.provider = MockCreditProvider()
        self.provider.set_limit("emp:1", 10_000_000)

    def test_balance_starts_at_limit(self):
        balance = self.provider.get_balance("emp:1")
        self.assertEqual(balance.available_minor, 10_000_000)

    def test_reserve_reduces_available_without_spending(self):
        reservation = self.provider.reserve("emp:1", 3_000_000, "i1")
        self.assertEqual(reservation.outcome, CreditOutcome.OK)
        balance = self.provider.get_balance("emp:1")
        self.assertEqual(balance.reserved_minor, 3_000_000)
        self.assertEqual(balance.used_minor, 0)
        self.assertEqual(balance.available_minor, 7_000_000)

    def test_reserve_is_idempotent(self):
        a = self.provider.reserve("emp:1", 3_000_000, "same")
        b = self.provider.reserve("emp:1", 3_000_000, "same")
        self.assertEqual(a.reservation_ref, b.reservation_ref)
        self.assertEqual(self.provider.get_balance("emp:1").reserved_minor, 3_000_000)

    def test_insufficient_credit(self):
        result = self.provider.reserve("emp:1", 99_000_000, "i2")
        self.assertEqual(result.outcome, CreditOutcome.INSUFFICIENT)

    def test_capture_moves_reserved_to_used(self):
        reservation = self.provider.reserve("emp:1", 4_000_000, "i3")
        self.assertEqual(self.provider.capture(reservation.reservation_ref, "c1"), CreditOutcome.OK)
        balance = self.provider.get_balance("emp:1")
        self.assertEqual(balance.reserved_minor, 0)
        self.assertEqual(balance.used_minor, 4_000_000)

    def test_capture_is_idempotent(self):
        reservation = self.provider.reserve("emp:1", 4_000_000, "i4")
        self.provider.capture(reservation.reservation_ref, "c2")
        self.provider.capture(reservation.reservation_ref, "c2")
        self.assertEqual(self.provider.get_balance("emp:1").used_minor, 4_000_000)

    def test_release_returns_the_hold(self):
        reservation = self.provider.reserve("emp:1", 5_000_000, "i5")
        self.assertEqual(self.provider.release(reservation.reservation_ref, "r1"), CreditOutcome.OK)
        self.assertEqual(self.provider.get_balance("emp:1").available_minor, 10_000_000)

    def test_unknown_reservation(self):
        self.assertEqual(self.provider.capture("nope", "x"), CreditOutcome.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
