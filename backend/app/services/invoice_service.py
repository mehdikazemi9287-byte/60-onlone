"""Invoice Service — Supplier invoice CRUD and duplicate detection.

All money as INTEGER (Rials). No REAL/FLOAT.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3

import logging

from app.core.errors import NotFoundError, ValidationError
from app.services import exception_service

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _dedup_hash(supplier_id: int, invoice_number: str, invoice_date: str, total_minor: int) -> str:
    """Generate a deduplication hash for an invoice."""
    raw = f"{supplier_id}:{invoice_number}:{invoice_date}:{total_minor}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if isinstance(d.get("raw_json"), str):
        try:
            d["raw_json"] = json.loads(d["raw_json"])
        except Exception:
            pass
    return d


def detect_duplicate(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    invoice_number: str,
    invoice_date: str,
    total_minor: int,
) -> dict | None:
    """Check if an invoice already exists. Returns existing invoice dict or None."""
    h = _dedup_hash(supplier_id, invoice_number, invoice_date, total_minor)
    row = conn.execute(
        "SELECT * FROM supplier_invoices WHERE dedup_hash = ? AND supplier_id = ?",
        (h, supplier_id),
    ).fetchone()
    if row:
        return _row_to_dict(row)

    # Also check by supplier_id + invoice_number + invoice_date
    row = conn.execute(
        "SELECT * FROM supplier_invoices WHERE supplier_id = ? AND invoice_number = ? AND invoice_date = ?",
        (supplier_id, invoice_number, invoice_date),
    ).fetchone()
    return _row_to_dict(row) if row else None


def create_invoice(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    invoice_number: str,
    invoice_date: str,
    lines: list[dict],
    source_type: str = "manual",
    created_by: int,
    connector_account_id: int | None = None,
    tax_minor: int = 0,
    currency: str = "IRR",
    raw_json: dict | None = None,
) -> dict:
    """Create a supplier invoice with lines. Returns created invoice dict."""
    # Calculate totals from lines
    subtotal_minor = sum(int(line.get("line_total_minor", 0)) for line in lines)
    tax_minor = int(tax_minor)
    total_minor = subtotal_minor + tax_minor

    # Check for duplicate
    existing = detect_duplicate(
        conn,
        supplier_id=supplier_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        total_minor=total_minor,
    )
    dedup_h = _dedup_hash(supplier_id, invoice_number, invoice_date, total_minor)

    if existing:
        is_dup = 1
        dup_of_id = existing["id"]
        status = "duplicate"
    else:
        is_dup = 0
        dup_of_id = None
        status = "captured"

    raw = json.dumps(raw_json or {}, ensure_ascii=False)

    cur = conn.execute(
        """INSERT INTO supplier_invoices
           (supplier_id, connector_account_id, invoice_number, invoice_date,
            subtotal_minor, tax_minor, total_minor, currency,
            status, source_type, raw_json, dedup_hash,
            is_duplicate, duplicate_of_id, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (supplier_id, connector_account_id, invoice_number, invoice_date,
         subtotal_minor, tax_minor, total_minor, currency,
         status, source_type, raw, dedup_h,
         is_dup, dup_of_id, created_by),
    )
    invoice_id = int(cur.lastrowid)

    # Blocker 6 + Micro 4: route duplicate invoice to Exception Inbox.
    # Failure is logged at ERROR level — never silently swallowed.
    if is_dup and dup_of_id:
        try:
            exception_service.create_exception(
                conn,
                exception_type="duplicate_invoice",
                severity="medium",
                supplier_id=supplier_id,
                title=f"فاکتور تکراری: {invoice_number}",
                detail={
                    "invoice_id": invoice_id,
                    "duplicate_of_id": dup_of_id,
                    "supplier_id": supplier_id,
                    "invoice_number": invoice_number,
                },
                idempotency_key=f"dup_invoice:{supplier_id}:{invoice_number}:{invoice_date}",
            )
        except Exception as exc_err:
            log.error(
                "invoice_service: failed to create duplicate_invoice exception "
                "(invoice_id=%s, key=dup_invoice:%s:%s:%s): %s",
                invoice_id, supplier_id, invoice_number, invoice_date, exc_err,
            )

    # Insert lines
    for i, line in enumerate(lines, start=1):
        qty = int(line.get("quantity", 1))
        unit_price = int(line.get("unit_price_minor", 0))
        line_total = int(line.get("line_total_minor", qty * unit_price))
        line_tax = int(line.get("tax_minor", 0))
        conn.execute(
            """INSERT INTO supplier_invoice_lines
               (invoice_id, line_number, external_code, barcode, product_name,
                quantity, unit_price_minor, line_total_minor, tax_minor,
                product_id, offer_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (invoice_id, i,
             line.get("external_code"),
             line.get("barcode"),
             line.get("product_name"),
             qty, unit_price, line_total, line_tax,
             line.get("product_id"),
             line.get("offer_id")),
        )

    return get_invoice(conn, invoice_id)


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> dict:
    """Get an invoice with its lines. Raises NotFoundError if not found."""
    row = conn.execute(
        "SELECT * FROM supplier_invoices WHERE id = ?", (invoice_id,)
    ).fetchone()
    if not row:
        raise NotFoundError(f"فاکتور {invoice_id} یافت نشد")

    inv = _row_to_dict(row)

    # Get lines
    lines = conn.execute(
        "SELECT * FROM supplier_invoice_lines WHERE invoice_id = ? ORDER BY line_number",
        (invoice_id,),
    ).fetchall()
    inv["lines"] = [dict(l) for l in lines]
    return inv


def list_invoices(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List invoices with optional filters."""
    wheres = []
    params: list = []

    if supplier_id:
        wheres.append("supplier_id = ?")
        params.append(supplier_id)
    if status:
        wheres.append("status = ?")
        params.append(status)

    where_clause = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    total_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM supplier_invoices {where_clause}", params
    ).fetchone()
    total = int(total_row["cnt"]) if total_row else 0

    rows = conn.execute(
        f"SELECT * FROM supplier_invoices {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
