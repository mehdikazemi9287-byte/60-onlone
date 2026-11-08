"""Phase 5C — product logistics data standard.

Package dimensions (mm), gross weight (g), volumetric weight, handling flags,
hazardous class, HS code, Iran Code (ایران‌کد) and GS1 GTIN-8/12/13/14.
All arithmetic is integer; all validation messages are Persian.
"""
from __future__ import annotations

import re
import sqlite3

from app.core.errors import NotFoundError, ValidationError

DEFAULT_VOLUMETRIC_DIVISOR = 5000  # L×W×H(cm)/5000 = kg  ⇔  L×W×H(mm)/5000 = g
GTIN_LENGTHS = (8, 12, 13, 14)
# UN dangerous-goods classes 1..9 with optional division (e.g. 2.1, 4.3)
_HAZMAT_RE = re.compile(r"^[1-9](\.[1-6])?$")
_HS_RE = re.compile(r"^\d{6}(\d{2}){0,2}$")   # 6, 8 or 10 digits
_IRAN_CODE_RE = re.compile(r"^\d{16}$")       # ایران‌کد کالا: ۱۶ رقمی

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _digits(value) -> str:
    return re.sub(r"[\s\-]", "", str(value or "")).translate(_FA_DIGITS)


def gtin_check_digit(body: str) -> int:
    """GS1 mod-10 check digit for the digits *before* the check digit."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def validate_gtin(value) -> str:
    """Return the normalized GTIN or raise ValidationError (Persian)."""
    code = _digits(value)
    if not code.isdigit():
        raise ValidationError("بارکد GTIN فقط باید شامل رقم باشد", code="gtin_not_numeric")
    if len(code) not in GTIN_LENGTHS:
        raise ValidationError("طول بارکد GTIN باید ۸، ۱۲، ۱۳ یا ۱۴ رقم باشد", code="gtin_bad_length")
    if gtin_check_digit(code[:-1]) != int(code[-1]):
        raise ValidationError("رقم کنترلی بارکد GTIN نادرست است", code="gtin_bad_check_digit")
    return code


def is_valid_gtin(value) -> bool:
    try:
        validate_gtin(value)
        return True
    except ValidationError:
        return False


def validate_iran_code(value) -> str:
    code = _digits(value)
    if not _IRAN_CODE_RE.match(code):
        raise ValidationError("ایران‌کد باید ۱۶ رقم باشد", code="iran_code_invalid")
    return code


def validate_hs_code(value) -> str:
    code = _digits(value).replace(".", "")
    if not _HS_RE.match(code):
        raise ValidationError("کد تعرفه گمرکی (HS) باید ۶، ۸ یا ۱۰ رقم باشد", code="hs_code_invalid")
    return code


def volumetric_weight_g(length_mm: int, width_mm: int, height_mm: int,
                        divisor: int = DEFAULT_VOLUMETRIC_DIVISOR) -> int:
    """Volumetric weight in grams, rounded up. divisor is per carrier (cm³/kg)."""
    if divisor <= 0:
        raise ValidationError("ضریب وزن حجمی نامعتبر است", code="bad_volumetric_divisor")
    return -(-(int(length_mm) * int(width_mm) * int(height_mm)) // int(divisor))


def billable_weight_g(actual_g: int, length_mm: int, width_mm: int, height_mm: int,
                      divisor: int = DEFAULT_VOLUMETRIC_DIVISOR) -> int:
    return max(int(actual_g), volumetric_weight_g(length_mm, width_mm, height_mm, divisor))


def _pos_int(data: dict, key: str, label: str) -> int:
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ValidationError(f"{label} باید عدد صحیح مثبت باشد", code=f"invalid_{key}")
    return v


def normalize_spec(data: dict) -> dict:
    """Validate a logistics spec payload; returns normalized columns."""
    spec = {
        "length_mm": _pos_int(data, "length_mm", "طول بسته (میلی‌متر)"),
        "width_mm": _pos_int(data, "width_mm", "عرض بسته (میلی‌متر)"),
        "height_mm": _pos_int(data, "height_mm", "ارتفاع بسته (میلی‌متر)"),
        "gross_weight_g": _pos_int(data, "gross_weight_g", "وزن ناخالص (گرم)"),
    }
    for flag in ("is_fragile", "is_perishable", "requires_cold_chain"):
        spec[flag] = 1 if data.get(flag) else 0
    if spec["requires_cold_chain"] and not spec["is_perishable"]:
        spec["is_perishable"] = 1
    hz = data.get("hazmat_class")
    if hz not in (None, ""):
        hz = str(hz).strip()
        if not _HAZMAT_RE.match(hz):
            raise ValidationError("کلاس کالای خطرناک باید بین ۱ تا ۹ (مثلاً 3 یا 2.1) باشد",
                                  code="hazmat_class_invalid")
        spec["hazmat_class"] = hz
    else:
        spec["hazmat_class"] = None
    spec["hs_code"] = validate_hs_code(data["hs_code"]) if data.get("hs_code") else None
    spec["iran_code"] = validate_iran_code(data["iran_code"]) if data.get("iran_code") else None
    spec["gtin"] = validate_gtin(data["gtin"]) if data.get("gtin") else None
    return spec


_COLS = ("length_mm", "width_mm", "height_mm", "gross_weight_g", "is_fragile", "is_perishable",
         "requires_cold_chain", "hazmat_class", "hs_code", "iran_code", "gtin")


def upsert_spec(conn: sqlite3.Connection, *, product_id: int, data: dict,
                seller_offer_id: int | None = None) -> dict:
    if conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone() is None:
        raise NotFoundError("کالا یافت نشد", code="product_not_found")
    if seller_offer_id is not None and conn.execute(
        "SELECT 1 FROM seller_offers WHERE id = ? AND product_id = ?", (seller_offer_id, product_id)
    ).fetchone() is None:
        raise NotFoundError("پیشنهاد فروشنده برای این کالا یافت نشد", code="offer_not_found")
    spec = normalize_spec(data)
    scope = f"o:{seller_offer_id}" if seller_offer_id else f"p:{product_id}"
    vals = [spec[c] for c in _COLS]
    if conn.execute("SELECT 1 FROM product_logistics_specs WHERE scope_key = ?", (scope,)).fetchone():
        conn.execute(
            "UPDATE product_logistics_specs SET " + ", ".join(f"{c} = ?" for c in _COLS)
            + ", updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE scope_key = ?",
            (*vals, scope),
        )
    else:
        conn.execute(
            "INSERT INTO product_logistics_specs (scope_key, product_id, seller_offer_id, "
            + ", ".join(_COLS) + ") VALUES (?,?,?," + ",".join("?" * len(_COLS)) + ")",
            (scope, product_id, seller_offer_id, *vals),
        )
    return get_spec(conn, product_id=product_id, seller_offer_id=seller_offer_id)


def get_spec(conn: sqlite3.Connection, *, product_id: int,
             seller_offer_id: int | None = None) -> dict | None:
    """Offer-level spec wins over product-level spec."""
    keys = ([f"o:{seller_offer_id}"] if seller_offer_id else []) + [f"p:{product_id}"]
    for k in keys:
        row = conn.execute("SELECT * FROM product_logistics_specs WHERE scope_key = ?", (k,)).fetchone()
        if row:
            d = dict(row)
            d["volumetric_weight_g"] = volumetric_weight_g(d["length_mm"], d["width_mm"], d["height_mm"])
            return d
    return None
