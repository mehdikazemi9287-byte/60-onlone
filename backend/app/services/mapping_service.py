"""
mapping_service.py
------------------
Manages ERP product mappings (erp_product_mappings): the bridge between
connector-side ERP product codes and internal catalogue product IDs.

All newly created mappings land in 'pending_review' regardless of whether a
product_id is supplied — an admin must explicitly activate them.

All DB access uses the caller-supplied ``conn`` (sqlite3.Connection).
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from app.core.errors import NotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

VALID_REVIEW_STATUSES = {"active", "rejected"}


def _map_dict(row: sqlite3.Row) -> dict:
    """Convert an erp_product_mappings row to a plain dict."""
    return {
        "id": row["id"],
        "connector_account_id": row["connector_account_id"],
        "erp_product_code": row["erp_product_code"],
        "product_id": row["product_id"],
        "supplier_id": row["supplier_id"],
        "confidence_score_bps": row["confidence_score_bps"],
        "match_method": row["match_method"],
        "status": row["status"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Mapping CRUD
# ---------------------------------------------------------------------------


def create_mapping(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int,
    erp_product_code: str,
    product_id: int | None = None,
    supplier_id: int,
    match_method: str = "manual",
    confidence_score_bps: int = 10000,
) -> dict:
    """Insert a new erp_product_mappings row.

    Status is always 'pending_review' on creation — an admin must review
    before the mapping becomes 'active'.

    Raises ValidationError on UNIQUE constraint violation
    (connector_account_id, erp_product_code).

    Returns the created row as a dict.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    try:
        cur = conn.execute(
            """
            INSERT INTO erp_product_mappings
                (connector_account_id, erp_product_code, product_id, supplier_id,
                 confidence_score_bps, match_method, status,
                 reviewed_by, reviewed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending_review', NULL, NULL, ?, ?)
            """,
            (
                connector_account_id,
                erp_product_code,
                product_id,
                supplier_id,
                confidence_score_bps,
                match_method,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValidationError(
            f"نگاشت ERP برای حساب id={connector_account_id} "
            f"با کد {erp_product_code!r} از قبل وجود دارد."
        ) from exc

    row = conn.execute(
        "SELECT * FROM erp_product_mappings WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _map_dict(row)


def list_mappings(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int | None = None,
    supplier_id: int | None = None,
    status: str | None = None,
) -> list[dict]:
    """Return erp_product_mappings rows with optional filters.

    Results ordered by id DESC (newest first).
    """
    query = "SELECT * FROM erp_product_mappings WHERE 1=1"
    params: list = []

    if connector_account_id is not None:
        query += " AND connector_account_id = ?"
        params.append(connector_account_id)
    if supplier_id is not None:
        query += " AND supplier_id = ?"
        params.append(supplier_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    return [_map_dict(r) for r in rows]


def get_mapping(conn: sqlite3.Connection, mapping_id: int) -> dict:
    """Return a single erp_product_mappings row.

    Raises NotFoundError if not found.
    """
    row = conn.execute(
        "SELECT * FROM erp_product_mappings WHERE id = ?", (mapping_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"نگاشت ERP با id={mapping_id} یافت نشد.")
    return _map_dict(row)


def review_mapping(
    conn: sqlite3.Connection,
    *,
    mapping_id: int,
    new_status: str,
    reviewed_by: int,
    product_id: int | None = None,
) -> dict:
    """Set status to active or rejected; optionally update product_id.

    Raises NotFoundError if mapping does not exist.
    Raises ValidationError for invalid new_status.

    Returns the updated row dict.
    """
    if new_status not in VALID_REVIEW_STATUSES:
        raise ValidationError(
            f"وضعیت بررسی نامعتبر: {new_status!r}. "
            f"مقادیر مجاز: {', '.join(sorted(VALID_REVIEW_STATUSES))}"
        )

    # Verify existence
    get_mapping(conn, mapping_id)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    if product_id is not None:
        conn.execute(
            """
            UPDATE erp_product_mappings
            SET status      = ?,
                product_id  = ?,
                reviewed_by = ?,
                reviewed_at = ?,
                updated_at  = ?
            WHERE id = ?
            """,
            (new_status, product_id, reviewed_by, now, now, mapping_id),
        )
    else:
        conn.execute(
            """
            UPDATE erp_product_mappings
            SET status      = ?,
                reviewed_by = ?,
                reviewed_at = ?,
                updated_at  = ?
            WHERE id = ?
            """,
            (new_status, reviewed_by, now, now, mapping_id),
        )

    return get_mapping(conn, mapping_id)


def delete_mapping(conn: sqlite3.Connection, mapping_id: int) -> None:
    """Hard-delete an erp_product_mappings row.

    These are admin-managed catalogue records, not financial data.
    Raises NotFoundError if not found.
    """
    get_mapping(conn, mapping_id)  # raises NotFoundError if absent
    conn.execute(
        "DELETE FROM erp_product_mappings WHERE id = ?", (mapping_id,)
    )


def resolve_erp_code(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int,
    erp_product_code: str,
) -> dict | None:
    """Look up the active mapping for an ERP code and return its offer IDs.

    Returns:
        {"product_id": int, "offer_ids": [int, ...]}
    or None if no active mapping exists.
    """
    mapping_row = conn.execute(
        """
        SELECT product_id FROM erp_product_mappings
        WHERE connector_account_id = ?
          AND erp_product_code     = ?
          AND status               = 'active'
        LIMIT 1
        """,
        (connector_account_id, erp_product_code),
    ).fetchone()

    if mapping_row is None or mapping_row["product_id"] is None:
        return None

    product_id: int = mapping_row["product_id"]

    # Collect all seller_offers for this product (across suppliers)
    offer_rows = conn.execute(
        "SELECT id FROM seller_offers WHERE product_id = ? ORDER BY id",
        (product_id,),
    ).fetchall()
    offer_ids = [r["id"] for r in offer_rows]

    return {
        "product_id": product_id,
        "offer_ids": offer_ids,
    }
