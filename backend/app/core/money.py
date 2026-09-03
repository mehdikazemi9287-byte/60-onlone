"""Exact money arithmetic.

Money is NEVER a float. Values are held as `decimal.Decimal` and persisted as
an integer count of minor units, so no binary floating point ever touches an
amount. Every arithmetic helper here is total and exact.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

Numeric = Union[int, str, Decimal]

DEFAULT_EXPONENT = 0


class MoneyError(ValueError):
    pass


def _quantum(exponent: int) -> Decimal:
    return Decimal(1).scaleb(-exponent)


def to_decimal(value: Numeric, exponent: int = DEFAULT_EXPONENT) -> Decimal:
    """Coerce to an exact Decimal quantized to the currency exponent.

    Floats are rejected outright: accepting them is how rounding drift enters a
    ledger, and this codebase must never do that.
    """
    if isinstance(value, float):
        raise MoneyError(
            "float is not an acceptable money value; pass int, str or Decimal"
        )
    if isinstance(value, bool):
        raise MoneyError("bool is not an acceptable money value")
    try:
        dec = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MoneyError(f"cannot interpret {value!r} as money") from exc
    if not dec.is_finite():
        raise MoneyError(f"money must be finite, got {value!r}")
    quantized = dec.quantize(_quantum(exponent), rounding=ROUND_HALF_UP)
    if quantized != dec:
        # Strict on purpose: silently rounding sub-minor-unit precision away is
        # how a ledger ends up off by a few units. The caller must round first
        # and be explicit about it.
        raise MoneyError(
            f"{value!r} has more precision than the currency allows "
            f"(exponent={exponent}); round explicitly before converting"
        )
    return quantized


def to_minor(value: Numeric, exponent: int = DEFAULT_EXPONENT) -> int:
    """Convert a money value to its exact integer minor-unit representation."""
    dec = to_decimal(value, exponent)
    scaled = dec.scaleb(exponent)
    as_int = scaled.to_integral_value(rounding=ROUND_HALF_UP)
    if scaled != as_int:
        raise MoneyError(f"{value!r} is not representable in minor units")
    return int(as_int)


def from_minor(minor: int, exponent: int = DEFAULT_EXPONENT) -> Decimal:
    """Convert integer minor units back to an exact Decimal."""
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise MoneyError(f"minor units must be int, got {type(minor).__name__}")
    return (Decimal(minor).scaleb(-exponent)).quantize(_quantum(exponent))


def multiply(value: Numeric, quantity: int, exponent: int = DEFAULT_EXPONENT) -> Decimal:
    """Exact unit-price x quantity."""
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise MoneyError("quantity must be an int")
    if quantity < 0:
        raise MoneyError("quantity must not be negative")
    return to_decimal(to_decimal(value, exponent) * quantity, exponent)


def add(*values: Numeric, exponent: int = DEFAULT_EXPONENT) -> Decimal:
    total = Decimal(0)
    for value in values:
        total += to_decimal(value, exponent)
    return to_decimal(total, exponent)


def format_minor(minor: int, exponent: int = DEFAULT_EXPONENT) -> str:
    """Canonical string form used in API responses (never a JSON float)."""
    return str(from_minor(minor, exponent))
