"""
csv_import_service.py
----------------------
Implements a safe, two-phase CSV import lifecycle for stock and price data:

  Phase 1 — Upload + Validate (parse_and_validate_csv / submit_csv_for_import)
      CSV is parsed, validated row-by-row, and staged in import_job_rows.
      The live catalogue is NEVER mutated at this stage.

  Phase 2 — Confirm (confirm_import)
      The user explicitly confirms the previewed data. Only then are
      seller_offers rows updated with new stock_quantity / selling_price_minor.

Required CSV columns (minimum):
  - At least one identifier: barcode | sku | erp_code
  - At least one data field:  stock_quantity | price_minor
Optional columns: currency, source_ref, product_name

All prices and quantities are integers (no floats).
All DB access uses the caller-supplied ``conn`` (sqlite3.Connection).
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import sqlite3

from app.core.errors import NotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IDENTIFIER_FIELDS = {"barcode", "sku", "erp_code"}
DATA_FIELDS = {"stock_quantity", "price_minor"}
OPTIONAL_FIELDS = {"currency", "source_ref", "product_name"}
PREVIEW_LIMIT = 20

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _job_dict(row: sqlite3.Row) -> dict:
    """Convert an import_jobs row to a plain dict."""
    col_map = row["column_mapping_json"]
    if isinstance(col_map, str):
        try:
            col_map = json.loads(col_map)
        except (json.JSONDecodeError, TypeError):
            col_map = {}

    preview = row["preview_json"]
    if isinstance(preview, str):
        try:
            preview = json.loads(preview)
        except (json.JSONDecodeError, TypeError):
            preview = None

    err_summary = row["error_summary_json"]
    if isinstance(err_summary, str):
        try:
            err_summary = json.loads(err_summary)
        except (json.JSONDecodeError, TypeError):
            err_summary = []

    return {
        "id": row["id"],
        "connector_account_id": row["connector_account_id"],
        "supplier_id": row["supplier_id"],
        "filename": row["filename"],
        "status": row["status"],
        "total_rows": row["total_rows"],
        "valid_rows": row["valid_rows"],
        "error_rows": row["error_rows"],
        "column_mapping": col_map,
        "preview": preview,
        "error_summary": err_summary,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_dict(row: sqlite3.Row) -> dict:
    """Convert an import_job_rows row to a plain dict."""
    raw = row["raw_json"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = {}

    errors = row["validation_errors_json"]
    if isinstance(errors, str):
        try:
            errors = json.loads(errors)
        except (json.JSONDecodeError, TypeError):
            errors = []

    return {
        "id": row["id"],
        "import_job_id": row["import_job_id"],
        "row_number": row["row_number"],
        "raw": raw,
        "status": row["status"],
        "validation_errors": errors,
        "product_id": row["product_id"],
        "offer_id": row["offer_id"],
        "created_at": row["created_at"],
    }


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# CSV parsing and validation (pure — no DB writes)
# ---------------------------------------------------------------------------


def parse_and_validate_csv(
    csv_text: str,
    *,
    supplier_id: int,
    conn: sqlite3.Connection,
) -> dict:
    """Parse and validate a CSV string. Does NOT write anything to the DB.

    Each row must have:
    - At least one identifier field: barcode, sku, or erp_code
    - At least one data field: stock_quantity or price_minor

    Validation rules:
    - stock_quantity must be a non-negative integer
    - price_minor must be a non-negative integer (NO floats)

    Attempts to resolve product_id from product_identifiers for barcode/sku.

    Returns:
        {
          "rows":    [{"row_number", "raw", "status", "validation_errors", "product_id"}],
          "total":   int,
          "valid":   int,
          "errors":  int,
          "preview": [first 20 valid rows],
        }
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = set(reader.fieldnames or [])

    rows: list[dict] = []

    for row_number, raw_row in enumerate(reader, start=1):
        raw = dict(raw_row)
        errors: list[str] = []

        # Check identifier presence
        present_identifiers = [f for f in IDENTIFIER_FIELDS if raw.get(f, "").strip()]
        if not present_identifiers:
            errors.append(
                "حداقل یکی از فیلدهای شناسه (barcode, sku, erp_code) باید مقدار داشته باشد."
            )

        # Check data field presence
        present_data = [f for f in DATA_FIELDS if raw.get(f, "").strip()]
        if not present_data:
            errors.append(
                "حداقل یکی از فیلدهای داده (stock_quantity, price_minor) باید مقدار داشته باشد."
            )

        # Validate stock_quantity
        if "stock_quantity" in raw and raw["stock_quantity"].strip():
            sq_str = raw["stock_quantity"].strip()
            try:
                sq = int(sq_str)
                if sq < 0:
                    errors.append(
                        f"stock_quantity باید عدد صحیح غیرمنفی باشد (دریافتی: {sq_str!r})."
                    )
            except ValueError:
                errors.append(
                    f"stock_quantity باید عدد صحیح باشد (دریافتی: {sq_str!r})."
                )

        # Validate price_minor — strictly no floats
        if "price_minor" in raw and raw["price_minor"].strip():
            pm_str = raw["price_minor"].strip()
            try:
                # Reject if decimal point is present
                if "." in pm_str:
                    raise ValueError("عدد اعشاری مجاز نیست")
                pm = int(pm_str)
                if pm < 0:
                    errors.append(
                        f"price_minor باید عدد صحیح غیرمنفی باشد (دریافتی: {pm_str!r})."
                    )
            except ValueError as exc:
                errors.append(
                    f"price_minor باید عدد صحیح باشد (دریافتی: {pm_str!r}): {exc}."
                )

        # Attempt to resolve product_id
        product_id: int | None = None
        if not errors or present_identifiers:
            product_id = _resolve_product_id(conn, raw, supplier_id)

        status = "invalid" if errors else "valid"
        rows.append(
            {
                "row_number": row_number,
                "raw": raw,
                "status": status,
                "validation_errors": errors,
                "product_id": product_id,
            }
        )

    total = len(rows)
    valid = sum(1 for r in rows if r["status"] == "valid")
    errors_count = total - valid
    preview = [r for r in rows if r["status"] == "valid"][:PREVIEW_LIMIT]

    return {
        "rows": rows,
        "total": total,
        "valid": valid,
        "errors": errors_count,
        "preview": preview,
    }


def _resolve_product_id(
    conn: sqlite3.Connection,
    raw: dict,
    supplier_id: int,
) -> int | None:
    """Try to find a product_id from the identifier fields in a raw CSV row."""
    # barcode
    if raw.get("barcode", "").strip():
        row = conn.execute(
            """
            SELECT product_id FROM product_identifiers
            WHERE identifier_type = 'barcode'
              AND identifier_value = ?
              AND (supplier_id IS NULL OR supplier_id = ?)
            LIMIT 1
            """,
            (raw["barcode"].strip(), supplier_id),
        ).fetchone()
        if row:
            return row["product_id"]

    # sku
    if raw.get("sku", "").strip():
        row = conn.execute(
            """
            SELECT product_id FROM product_identifiers
            WHERE identifier_type = 'sku'
              AND identifier_value = ?
              AND (supplier_id IS NULL OR supplier_id = ?)
            LIMIT 1
            """,
            (raw["sku"].strip(), supplier_id),
        ).fetchone()
        if row:
            return row["product_id"]

    # erp_code — treated as sku or erp_code type
    if raw.get("erp_code", "").strip():
        row = conn.execute(
            """
            SELECT product_id FROM product_identifiers
            WHERE identifier_type IN ('erp_code', 'sku')
              AND identifier_value = ?
              AND (supplier_id IS NULL OR supplier_id = ?)
            LIMIT 1
            """,
            (raw["erp_code"].strip(), supplier_id),
        ).fetchone()
        if row:
            return row["product_id"]

    return None


# ---------------------------------------------------------------------------
# Import job lifecycle
# ---------------------------------------------------------------------------


def create_import_job(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    filename: str,
    created_by: int,
    connector_account_id: int | None = None,
    column_mapping: dict | None = None,
) -> dict:
    """Create a new import_jobs record with status='pending'.

    Returns the created job as a dict.
    """
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO import_jobs
            (connector_account_id, supplier_id, filename, status,
             total_rows, valid_rows, error_rows,
             column_mapping_json, preview_json, error_summary_json,
             created_by, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', 0, 0, 0, ?, NULL, '[]', ?, ?, ?)
        """,
        (
            connector_account_id,
            supplier_id,
            filename,
            json.dumps(column_mapping or {}, ensure_ascii=False),
            created_by,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM import_jobs WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _job_dict(row)


def submit_csv_for_import(
    conn: sqlite3.Connection,
    *,
    import_job_id: int,
    csv_text: str,
    supplier_id: int,
) -> dict:
    """Parse and validate the CSV, stage rows in import_job_rows, update job status.

    Status progression:
    - 'pending' → 'parsing' → 'previewing'  (if <= 50 % rows invalid)
    - 'pending' → 'parsing' → 'validation_failed' (if > 50 % rows invalid)

    Returns the updated job dict (includes preview).
    """
    now = _now()

    # Mark as parsing
    conn.execute(
        "UPDATE import_jobs SET status='parsing', updated_at=? WHERE id=?",
        (now, import_job_id),
    )

    # Parse + validate
    result = parse_and_validate_csv(csv_text, supplier_id=supplier_id, conn=conn)

    # Insert import_job_rows
    for r in result["rows"]:
        conn.execute(
            """
            INSERT INTO import_job_rows
                (import_job_id, row_number, raw_json, status,
                 validation_errors_json, product_id, offer_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                import_job_id,
                r["row_number"],
                json.dumps(r["raw"], ensure_ascii=False),
                r["status"],
                json.dumps(r["validation_errors"], ensure_ascii=False),
                r["product_id"],
                now,
            ),
        )

    total = result["total"]
    valid = result["valid"]
    errors = result["errors"]

    # Determine final status
    if total > 0 and errors / total > 0.5:
        new_status = "validation_failed"
    else:
        new_status = "previewing"

    preview_json = json.dumps(result["preview"], ensure_ascii=False)

    # Build error summary (first 50 invalid rows)
    invalid_rows = [r for r in result["rows"] if r["status"] == "invalid"][:50]
    error_summary = [
        {"row_number": r["row_number"], "errors": r["validation_errors"]}
        for r in invalid_rows
    ]
    error_summary_json = json.dumps(error_summary, ensure_ascii=False)

    now2 = _now()
    conn.execute(
        """
        UPDATE import_jobs
        SET status             = ?,
            total_rows         = ?,
            valid_rows         = ?,
            error_rows         = ?,
            preview_json       = ?,
            error_summary_json = ?,
            updated_at         = ?
        WHERE id = ?
        """,
        (new_status, total, valid, errors, preview_json, error_summary_json, now2, import_job_id),
    )

    row = conn.execute(
        "SELECT * FROM import_jobs WHERE id = ?", (import_job_id,)
    ).fetchone()
    return _job_dict(row)


def confirm_import(
    conn: sqlite3.Connection,
    *,
    import_job_id: int,
    supplier_id: int,
) -> dict:
    """Apply staged import_job_rows to the live catalogue.

    The job must be in 'previewing' status.
    For each valid row with a resolved product_id:
    - Finds the seller_offer for product + supplier
    - Updates stock_quantity if stock_quantity column present
    - Updates selling_price_minor if price_minor column present (integer only)
    - Sets row status to 'applied' or 'skipped'

    Job ends with 'completed' or 'completed_with_errors'.

    Returns a summary dict.
    """
    # Load and verify job
    job_row = conn.execute(
        "SELECT * FROM import_jobs WHERE id = ?", (import_job_id,)
    ).fetchone()
    if job_row is None:
        raise NotFoundError(f"کار وارد کردن با id={import_job_id} یافت نشد.")
    if job_row["supplier_id"] != supplier_id:
        raise ValidationError("این کار وارد کردن متعلق به تأمین‌کننده‌ی دیگری است.")
    if job_row["status"] != "previewing":
        raise ValidationError(
            f"تأیید تنها در وضعیت 'previewing' مجاز است "
            f"(وضعیت فعلی: {job_row['status']!r})."
        )

    now = _now()
    conn.execute(
        "UPDATE import_jobs SET status='applying', updated_at=? WHERE id=?",
        (now, import_job_id),
    )

    # Load all valid rows
    pending_rows = conn.execute(
        """
        SELECT * FROM import_job_rows
        WHERE import_job_id = ? AND status = 'valid'
        ORDER BY row_number
        """,
        (import_job_id,),
    ).fetchall()

    applied = 0
    skipped = 0
    errors_count = 0

    for job_row_item in pending_rows:
        raw: dict
        try:
            raw = json.loads(job_row_item["raw_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            raw = {}

        product_id: int | None = job_row_item["product_id"]

        if product_id is None:
            # Cannot apply without a resolved product
            conn.execute(
                "UPDATE import_job_rows SET status='skipped', offer_id=NULL WHERE id=?",
                (job_row_item["id"],),
            )
            skipped += 1
            continue

        # Find seller_offer for this product + supplier
        offer_row = conn.execute(
            """
            SELECT id FROM seller_offers
            WHERE product_id = ? AND supplier_id = ?
            LIMIT 1
            """,
            (product_id, supplier_id),
        ).fetchone()

        if offer_row is None:
            conn.execute(
                "UPDATE import_job_rows SET status='skipped' WHERE id=?",
                (job_row_item["id"],),
            )
            skipped += 1
            continue

        offer_id: int = offer_row["id"]

        try:
            updates: list[str] = []
            params: list = []

            # Stock quantity update
            sq_str = raw.get("stock_quantity", "").strip() if isinstance(raw.get("stock_quantity"), str) else str(raw.get("stock_quantity", "")).strip()
            if sq_str:
                sq = int(sq_str)
                updates.append("stock_quantity = ?")
                params.append(sq)

            # Price minor update (integer only)
            pm_str = raw.get("price_minor", "").strip() if isinstance(raw.get("price_minor"), str) else str(raw.get("price_minor", "")).strip()
            if pm_str and "." not in pm_str:
                pm = int(pm_str)
                if pm >= 0:
                    updates.append("selling_price_minor = ?")
                    params.append(pm)

            if updates:
                updates.append("updated_at = ?")
                params.append(_now())
                params.append(offer_id)
                conn.execute(
                    f"UPDATE seller_offers SET {', '.join(updates)} WHERE id = ?",
                    params,
                )

            conn.execute(
                "UPDATE import_job_rows SET status='applied', offer_id=? WHERE id=?",
                (offer_id, job_row_item["id"]),
            )
            applied += 1

        except Exception:
            conn.execute(
                "UPDATE import_job_rows SET status='skipped' WHERE id=?",
                (job_row_item["id"],),
            )
            skipped += 1
            errors_count += 1

    # Determine final job status
    final_status = "completed" if errors_count == 0 else "completed_with_errors"
    conn.execute(
        "UPDATE import_jobs SET status=?, updated_at=? WHERE id=?",
        (final_status, _now(), import_job_id),
    )

    return {
        "import_job_id": import_job_id,
        "status": final_status,
        "applied": applied,
        "skipped": skipped,
        "errors": errors_count,
    }


def get_import_job(
    conn: sqlite3.Connection,
    job_id: int,
    supplier_id: int | None = None,
) -> dict:
    """Return a single import_jobs row.

    Raises NotFoundError if not found.
    Raises ValidationError if supplier_id is given and doesn't match.
    """
    row = conn.execute(
        "SELECT * FROM import_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"کار وارد کردن با id={job_id} یافت نشد.")
    if supplier_id is not None and row["supplier_id"] != supplier_id:
        raise ValidationError("این کار وارد کردن متعلق به تأمین‌کننده‌ی دیگری است.")
    return _job_dict(row)


def list_import_jobs(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return import_jobs rows, newest first, with optional supplier filter."""
    query = "SELECT * FROM import_jobs WHERE 1=1"
    params: list = []

    if supplier_id is not None:
        query += " AND supplier_id = ?"
        params.append(supplier_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [_job_dict(r) for r in rows]
