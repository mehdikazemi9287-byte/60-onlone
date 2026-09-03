"""XLSX Import Service.

Parse XLSX files into the same structure as parse_and_validate_csv.
Requires openpyxl.

All money as INTEGER. Rejects float money values.
"""
from __future__ import annotations

import io
from typing import Any

from app.core.errors import ValidationError


def _reject_float_money(value: Any, field_name: str) -> int:
    """Ensure a money value is an integer. Raises ValidationError for float."""
    if isinstance(value, float):
        raise ValidationError(
            f"مقدار پول نمی‌تواند اعشاری باشد: {field_name}={value}. "
            f"لطفاً مقدار صحیح (ریال) وارد کنید."
        )
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_xlsx(file_bytes: bytes, column_map: dict) -> dict:
    """
    Parse XLSX bytes into a normalized product list.

    Args:
        file_bytes: Raw XLSX file content
        column_map: Mapping of canonical field name → column header or index
                    e.g. {"barcode": "بارکد", "price_minor": "قیمت", ...}

    Returns:
        {
          "rows": [{"barcode": ..., "name_fa": ..., "price_minor": int, ...}],
          "total_rows": int,
          "valid_rows": int,
          "error_rows": int,
          "errors": [{"row": int, "field": str, "message": str}],
        }
    """
    try:
        import openpyxl
    except ImportError:
        raise ValidationError(
            "کتابخانه openpyxl نصب نشده است. برای پردازش فایل XLSX نیاز است."
        )

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        ws = wb.active
    except Exception as exc:
        raise ValidationError(f"فایل XLSX معتبر نیست: {exc}")

    rows_data = list(ws.iter_rows(values_only=True))
    if not rows_data:
        return {"rows": [], "total_rows": 0, "valid_rows": 0, "error_rows": 0, "errors": []}

    # Extract headers from first row
    headers = [str(h).strip() if h is not None else "" for h in rows_data[0]]

    # Build column index map: canonical_field → column_index
    col_idx: dict[str, int] = {}
    for canonical, header_name in column_map.items():
        if isinstance(header_name, int):
            col_idx[canonical] = header_name
        elif isinstance(header_name, str):
            for i, h in enumerate(headers):
                if h.strip().lower() == header_name.strip().lower():
                    col_idx[canonical] = i
                    break

    # Money fields that must be INTEGER
    money_fields = {"price_minor", "cost_price_minor", "unit_price_minor", "line_total_minor"}

    parsed_rows = []
    errors = []
    error_count = 0

    for row_num, row in enumerate(rows_data[1:], start=2):
        row_data: dict = {}
        row_error = False

        for canonical, idx in col_idx.items():
            if idx < len(row):
                raw_val = row[idx]
            else:
                raw_val = None

            if canonical in money_fields and raw_val is not None:
                try:
                    row_data[canonical] = _reject_float_money(raw_val, canonical)
                except ValidationError as exc:
                    errors.append({"row": row_num, "field": canonical, "message": str(exc)})
                    row_error = True
                    row_data[canonical] = 0
            else:
                if raw_val is not None:
                    row_data[canonical] = str(raw_val).strip() if isinstance(raw_val, str) else raw_val
                else:
                    row_data[canonical] = None

        if row_error:
            error_count += 1
        else:
            parsed_rows.append(row_data)

    wb.close()

    return {
        "rows": parsed_rows,
        "total_rows": len(rows_data) - 1,
        "valid_rows": len(parsed_rows),
        "error_rows": error_count,
        "errors": errors,
    }
