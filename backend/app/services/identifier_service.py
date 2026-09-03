"""
identifier_service.py
---------------------
Manages product identifiers (barcode, SKU, ERP code, etc.) and identifier
conflict records that arise when two products share the same identifier.

All DB access uses the caller-supplied ``conn`` (sqlite3.Connection).
Money is never handled here; this module is purely identifier/catalog logic.
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from app.core.errors import NotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

VALID_RESOLUTIONS = {"resolved_merge", "resolved_keep_both", "ignored"}


def _pi_dict(row: sqlite3.Row) -> dict:
    """Convert a product_identifiers sqlite3.Row to a plain dict."""
    return {
        "id": row["id"],
        "product_id": row["product_id"],
        "supplier_id": row["supplier_id"],
        "identifier_type": row["identifier_type"],
        "identifier_value": row["identifier_value"],
        "namespace": row["namespace"],
        "is_primary": bool(row["is_primary"]),
        "created_at": row["created_at"],
    }


def _conflict_dict(row: sqlite3.Row) -> dict:
    """Convert an identifier_conflicts sqlite3.Row to a plain dict."""
    return {
        "id": row["id"],
        "product_id_a": row["product_id_a"],
        "product_id_b": row["product_id_b"],
        "identifier_type": row["identifier_type"],
        "identifier_value": row["identifier_value"],
        "namespace": row["namespace"],
        "status": row["status"],
        "resolved_by": row["resolved_by"],
        "resolved_at": row["resolved_at"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Identifier CRUD
# ---------------------------------------------------------------------------

def add_identifier(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    supplier_id: int | None = None,
    identifier_type: str,
    identifier_value: str,
    namespace: str = "",
    is_primary: bool = False,
) -> dict:
    """Insert a new product identifier row.

    Raises ValidationError on UNIQUE constraint violation
    (identifier_type, identifier_value, namespace, supplier_id).
    Returns the inserted row as a dict.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    try:
        cur = conn.execute(
            """
            INSERT INTO product_identifiers
                (product_id, supplier_id, identifier_type, identifier_value,
                 namespace, is_primary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                supplier_id,
                identifier_type,
                identifier_value,
                namespace,
                1 if is_primary else 0,
                now,
            ),
        )
        row_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValidationError(
            f"شناسه‌ی تکراری: نوع={identifier_type}, مقدار={identifier_value}, "
            f"فضانام={namespace!r} برای این تأمین‌کننده از قبل وجود دارد."
        ) from exc

    row = conn.execute(
        "SELECT * FROM product_identifiers WHERE id = ?", (row_id,)
    ).fetchone()
    return _pi_dict(row)


def list_identifiers(
    conn: sqlite3.Connection,
    *,
    product_id: int | None = None,
    supplier_id: int | None = None,
    identifier_type: str | None = None,
) -> list[dict]:
    """Return product_identifiers rows matching the given optional filters."""
    query = "SELECT * FROM product_identifiers WHERE 1=1"
    params: list = []

    if product_id is not None:
        query += " AND product_id = ?"
        params.append(product_id)
    if supplier_id is not None:
        query += " AND supplier_id = ?"
        params.append(supplier_id)
    if identifier_type is not None:
        query += " AND identifier_type = ?"
        params.append(identifier_type)

    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    return [_pi_dict(r) for r in rows]


def delete_identifier(
    conn: sqlite3.Connection,
    *,
    identifier_id: int,
    supplier_id: int | None = None,
) -> None:
    """Delete a product_identifiers row.

    If supplier_id is provided, verifies ownership before deletion.
    Raises NotFoundError if row does not exist.
    Raises ValidationError if supplier_id does not match.
    """
    row = conn.execute(
        "SELECT * FROM product_identifiers WHERE id = ?", (identifier_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"شناسه با id={identifier_id} یافت نشد.")

    if supplier_id is not None and row["supplier_id"] != supplier_id:
        raise ValidationError(
            f"شناسه id={identifier_id} متعلق به تأمین‌کننده‌ی دیگری است."
        )

    conn.execute(
        "DELETE FROM product_identifiers WHERE id = ?", (identifier_id,)
    )


def resolve_by_identifier(
    conn: sqlite3.Connection,
    *,
    identifier_type: str,
    identifier_value: str,
    namespace: str = "",
    supplier_id: int | None = None,
) -> dict | None:
    """Find a product via product_identifiers JOIN products.

    Returns a dict with keys:
        product_id, product_name, identifier_type, identifier_value,
        namespace, supplier_id, is_primary
    or None if not found.
    """
    query = """
        SELECT
            pi.product_id,
            p.title_fa   AS product_name,
            pi.identifier_type,
            pi.identifier_value,
            pi.namespace,
            pi.supplier_id,
            pi.is_primary
        FROM product_identifiers pi
        JOIN products p ON p.id = pi.product_id
        WHERE pi.identifier_type = ?
          AND pi.identifier_value = ?
          AND pi.namespace       = ?
    """
    params: list = [identifier_type, identifier_value, namespace]

    if supplier_id is not None:
        query += " AND pi.supplier_id = ?"
        params.append(supplier_id)

    query += " LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if row is None:
        return None

    return {
        "product_id": row["product_id"],
        "product_name": row["product_name"],
        "identifier_type": row["identifier_type"],
        "identifier_value": row["identifier_value"],
        "namespace": row["namespace"],
        "supplier_id": row["supplier_id"],
        "is_primary": bool(row["is_primary"]),
    }


# ---------------------------------------------------------------------------
# Conflict management
# ---------------------------------------------------------------------------

def create_conflict(
    conn: sqlite3.Connection,
    *,
    product_id_a: int,
    product_id_b: int,
    identifier_type: str,
    identifier_value: str,
    namespace: str = "",
) -> dict:
    """Insert a new identifier_conflicts row with status='open'.

    Returns the created conflict as a dict.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO identifier_conflicts
            (product_id_a, product_id_b, identifier_type, identifier_value,
             namespace, status, resolved_by, resolved_at, notes, created_at)
        VALUES (?, ?, ?, ?, ?, 'open', NULL, NULL, '', ?)
        """,
        (product_id_a, product_id_b, identifier_type, identifier_value, namespace, now),
    )
    row = conn.execute(
        "SELECT * FROM identifier_conflicts WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _conflict_dict(row)


def list_conflicts(
    conn: sqlite3.Connection,
    *,
    status: str = "open",
    supplier_id: int | None = None,
) -> list[dict]:
    """Return identifier_conflicts rows.

    Filters by status.  If supplier_id is provided, only conflicts where
    product_id_a or product_id_b belongs to that supplier (via product_identifiers).
    """
    if supplier_id is not None:
        query = """
            SELECT DISTINCT ic.*
            FROM identifier_conflicts ic
            JOIN product_identifiers pi
              ON pi.product_id IN (ic.product_id_a, ic.product_id_b)
             AND pi.supplier_id = ?
            WHERE ic.status = ?
            ORDER BY ic.id
        """
        rows = conn.execute(query, (supplier_id, status)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM identifier_conflicts WHERE status = ? ORDER BY id",
            (status,),
        ).fetchall()

    return [_conflict_dict(r) for r in rows]


def resolve_conflict(
    conn: sqlite3.Connection,
    *,
    conflict_id: int,
    resolution: str,
    resolved_by: int,
    notes: str = "",
) -> dict:
    """Update an identifier_conflicts row to a resolved status.

    resolution must be one of: resolved_merge, resolved_keep_both, ignored.
    Raises NotFoundError if row not found.
    Raises ValidationError for invalid resolution value.
    Returns updated conflict dict.
    """
    if resolution not in VALID_RESOLUTIONS:
        raise ValidationError(
            f"وضعیت حل‌اختلاف نامعتبر: {resolution!r}. "
            f"مقادیر مجاز: {', '.join(sorted(VALID_RESOLUTIONS))}"
        )

    row = conn.execute(
        "SELECT * FROM identifier_conflicts WHERE id = ?", (conflict_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"تعارض با id={conflict_id} یافت نشد.")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        UPDATE identifier_conflicts
        SET status      = ?,
            resolved_by = ?,
            resolved_at = ?,
            notes       = ?
        WHERE id = ?
        """,
        (resolution, resolved_by, now, notes, conflict_id),
    )

    updated = conn.execute(
        "SELECT * FROM identifier_conflicts WHERE id = ?", (conflict_id,)
    ).fetchone()
    return _conflict_dict(updated)
