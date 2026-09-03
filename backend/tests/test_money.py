from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.money import MoneyError, add, format_minor, from_minor, multiply, to_decimal, to_minor


class MoneyTest(unittest.TestCase):
    def test_float_is_rejected(self):
        for bad in (1.0, 0.1, 1e5):
            with self.assertRaises(MoneyError):
                to_decimal(bad)
            with self.assertRaises(MoneyError):
                to_minor(bad)

    def test_bool_is_rejected(self):
        with self.assertRaises(MoneyError):
            to_decimal(True)

    def test_roundtrip_is_exact(self):
        for amount in (0, 1, 999, 289_000_000, 10**15):
            self.assertEqual(to_minor(from_minor(amount)), amount)

    def test_no_binary_drift_on_repeated_addition(self):
        """0.1+0.2 style drift must be impossible."""
        cents = [Decimal("0.10"), Decimal("0.20")]
        total = add(*cents, exponent=2)
        self.assertEqual(total, Decimal("0.30"))
        self.assertEqual(to_minor(total, 2), 30)

    def test_multiply_is_exact(self):
        self.assertEqual(multiply("14500000", 3), Decimal("43500000"))
        self.assertEqual(multiply(Decimal("11900000"), 7), Decimal("83300000"))

    def test_multiply_rejects_negative_and_non_int_quantity(self):
        with self.assertRaises(MoneyError):
            multiply("100", -1)
        with self.assertRaises(MoneyError):
            multiply("100", 2.5)  # type: ignore[arg-type]

    def test_from_minor_requires_int(self):
        with self.assertRaises(MoneyError):
            from_minor("100")  # type: ignore[arg-type]

    def test_format_minor_never_produces_a_float_literal(self):
        text = format_minor(289_000_000)
        self.assertEqual(text, "289000000")
        self.assertNotIn(".", text)

    def test_exponent_two_currency(self):
        self.assertEqual(to_minor("12.34", 2), 1234)
        self.assertEqual(from_minor(1234, 2), Decimal("12.34"))

    def test_sub_minor_precision_is_rejected_not_silently_rounded(self):
        for bad in ("1.005", "0.001", "12.3456"):
            with self.assertRaises(MoneyError):
                to_decimal(Decimal(bad), 2)
            with self.assertRaises(MoneyError):
                to_minor(Decimal(bad), 2)

    def test_fractional_value_rejected_for_zero_exponent_currency(self):
        with self.assertRaises(MoneyError):
            to_decimal(Decimal("100.5"), 0)


if __name__ == "__main__":
    unittest.main()
