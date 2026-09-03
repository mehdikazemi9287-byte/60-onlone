"""Exception Service — CRUD for the exceptions inbox.

All money as INTEGER. No REAL/FLOAT.
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from app.core.errors import NotFoundError, ValidationError

VALID_EXCEPTION_TYPES = {
    "unknown_product", "identifier_conflict", "ambiguous_match",
    "suspicious_price_jump", "invalid_stock", "stale_source",
    "connector_outage", "invoice_mismatch", "duplicate_invoice",
    "reconciliation_mismatch", "malformed_data", "three_way_mismatch",
    "credential_warning", "other",
}

VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_STATUSES = {"open", "assigned", "resolved", "ignored", "retrying"}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if isinstance(d.get("detail_json"), str):
        try:
            d["detail_json"] = json.loads(d["detail_json"])
        except Exception:
            pass
    return d


def create_exception(
    conn: sqlite3.Connection,
    *,
    exception_type: str,
    title: str,
    severity: str = "medium",
    supplier_id: int | None = None,
    connector_account_id: int | None = None,
    sync_run_id: int | None = None,
    detail: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create a new exception record. Returns the created exception dict."""
    if exception_type not in VALID_EXCEPTION_TYPES:
        raise ValidationError(f"نوع استثنا نامعتبر: {exception_type}")
    if severity not in VALID_SEVERITIES:
        raise ValidationError(f"شدت نامعتبر: {severity}")

    if idempotency_key:
        existing = conn.execute(
            "SELECT id FROM exceptions WHERE idempotency_key = ? LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return get_exception(conn, int(existing["id"]))

    detail_json = json.dumps(detail or {}, ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO exceptions
           (exception_type, severity, supplier_id, connector_account_id,
            sync_run_id, title, detail_json, status, retry_count, idempotency_key)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (exception_type, severity, supplier_id, connector_account_id,
         sync_run_id, title, detail_json, "open", 0, idempotency_key),
    )
    exc_id = int(cur.lastrowid)
    return get_exception(conn, exc_id)


def get_exception(conn: sqlite3.Connection, exception_id: int) -> dict:
    """Get a single exception by ID. Raises NotFoundError if not found."""
    row = conn.execute(
        "SELECT * FROM exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    if not row:
        raise NotFoundError(f"استثنا {exception_id} یافت نشد")
    return _row_to_dict(row)


def list_exceptions(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    exception_type: str | None = None,
    supplier_id: int | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List exceptions with optional filters."""
    wheres = []
    params: list = []

    if status:
        wheres.append("status = ?")
        params.append(status)
    if exception_type:
        wheres.append("exception_type = ?")
        params.append(exception_type)
    if supplier_id:
        wheres.append("supplier_id = ?")
        params.append(supplier_id)
    if severity:
        wheres.append("severity = ?")
        params.append(severity)

    where_clause = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    total_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM exceptions {where_clause}", params
    ).fetchone()
    total = int(total_row["cnt"]) if total_row else 0

    rows = conn.execute(
        f"SELECT * FROM exceptions {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def resolve_exception(
    conn: sqlite3.Connection,
    exception_id: int,
    *,
    resolved_by: int,
    resolution_notes: str | None = None,
) -> dict:
    """Mark an exception as resolved."""
    exc = get_exception(conn, exception_id)
    if exc["status"] == "resolved":
        return exc  # Idempotent

    conn.execute(
        """UPDATE exceptions
           SET status = 'resolved', resolved_by = ?, resolved_at = ?,
               resolution_notes = ?, updated_at = ?
           WHERE id = ?""",
        (resolved_by, _now(), resolution_notes, _now(), exception_id),
    )
    return get_exception(conn, exception_id)


def assign_exception(
    conn: sqlite3.Connection,
    exception_id: int,
    *,
    assigned_to: int,
) -> dict:
    """Assign an exception to a user."""
    get_exception(conn, exception_id)  # Raises if not found
    conn.execute(
        "UPDATE exceptions SET status = 'assigned', assigned_to = ?, updated_at = ? WHERE id = ?",
        (assigned_to, _now(), exception_id),
    )
    return get_exception(conn, exception_id)


def bulk_resolve(
    conn: sqlite3.Connection,
    exception_ids: list[int],
    *,
    resolved_by: int,
    resolution_notes: str | None = None,
) -> dict:
    """Bulk resolve multiple exceptions."""
    resolved_count = 0
    for exc_id in exception_ids:
        try:
            resolve_exception(conn, exc_id, resolved_by=resolved_by, resolution_notes=resolution_notes)
            resolved_count += 1
        except Exception:
            pass
    return {"resolved_count": resolved_count, "total_requested": len(exception_ids)}


def ignore_exception(conn: sqlite3.Connection, exception_id: int) -> dict:
    """Mark an exception as ignored."""
    get_exception(conn, exception_id)
    conn.execute(
        "UPDATE exceptions SET status = 'ignored', updated_at = ? WHERE id = ?",
        (_now(), exception_id),
    )
    return get_exception(conn, exception_id)
