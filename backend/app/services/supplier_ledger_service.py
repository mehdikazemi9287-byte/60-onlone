"""Supplier payable ledger (BLOCKER 6).

Business rules:
  - Supplier payable is earned when the ACTUAL FulfillmentOrder reaches DELIVERED.
  - NOT when the customer pays (payment ≠ payable).
  - If supplier A rejected and supplier B delivered, only supplier B earns payable.
  - Gross basis: SUM(COALESCE(line_cost_minor, line_selling_minor)) from the
    IMMUTABLE fulfillment_order_items snapshot.  Never read current seller_offer prices.
  - Idempotency key: 'fulfillment:{fo_id}:sale-payable'
  - Exactly one record per FO (enforced by UNIQUE idempotency_key).

Rounding policy (BLOCKER 5):
  All financial arithmetic uses integer floor division.
  commission_minor = (gross_minor * commission_rate_bps) // 10_000
  No floats anywhere.

This module does NOT perform real bank settlement.
Real banking: NOT IMPLEMENTED.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError

log = logging.getLogger("70online.supplier_ledger")

DEFAULT_COMMISSION_RATE_BPS = 1000  # 10% platform commission


# ---------------------------------------------------------------------------
# Record sale payable on delivery
# ---------------------------------------------------------------------------

def record_sale_payable(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int,
) -> dict:
    """Record supplier payable for a delivered FO.

    Must be called within an open write transaction (the caller provides conn).

    Idempotent: if a record already exists for this FO, returns the existing
    record without creating a duplicate.

    Gross basis:
      SUM(COALESCE(line_cost_minor, line_selling_minor))
      for all fulfillment_order_items of this FO.

    This is the ONLY place supplier payable is created.  Never called at
    payment time — only at delivery time.
    """
    idempotency_key = f"fulfillment:{fulfillment_order_id}:sale-payable"

    # Idempotency check
    existing = conn.execute(
        "SELECT * FROM supplier_payable_entries WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if existing is not None:
        log.info(
            "record_sale_payable: idempotent return fo_id=%s entry_id=%s",
            fulfillment_order_id, existing["id"],
        )
        return dict(existing)

    # Validate FO exists and belongs to the given supplier
    fo = conn.execute(
        "SELECT id, supplier_id, status FROM fulfillment_orders WHERE id = ?",
        (fulfillment_order_id,),
    ).fetchone()
    if fo is None:
        raise NotFoundError(f"FO {fulfillment_order_id} not found", code="fo_not_found")
    if int(fo["supplier_id"]) != supplier_id:
        raise ConflictError(
            f"FO {fulfillment_order_id} does not belong to supplier {supplier_id}",
            code="supplier_mismatch",
        )
    if fo["status"] != "delivered":
        raise ConflictError(
            f"FO {fulfillment_order_id} is not delivered (status={fo['status']}). "
            "Payable is only recorded on delivery.",
            code="fo_not_delivered",
        )

    # Compute gross from IMMUTABLE snapshot (never re-read offer prices)
    row = conn.execute(
        """
        SELECT SUM(COALESCE(line_cost_minor, line_selling_minor)) AS gross
        FROM fulfillment_order_items
        WHERE fulfillment_order_id = ?
        """,
        (fulfillment_order_id,),
    ).fetchone()
    gross_minor = int(row["gross"] or 0)
    if gross_minor <= 0:
        raise ValidationError(
            f"Cannot record zero or negative payable for FO {fulfillment_order_id}",
            code="zero_payable",
        )

    cursor = conn.execute(
        """
        INSERT INTO supplier_payable_entries
            (supplier_id, fulfillment_order_id, entry_type, gross_minor, idempotency_key, status)
        VALUES (?, ?, 'sale_payable', ?, ?, 'unbatched')
        """,
        (supplier_id, fulfillment_order_id, gross_minor, idempotency_key),
    )
    entry_id = int(cursor.lastrowid)
    log.info(
        "record_sale_payable: created entry_id=%s fo=%s supplier=%s gross=%s",
        entry_id, fulfillment_order_id, supplier_id, gross_minor,
    )
    return {
        "id": entry_id,
        "supplier_id": supplier_id,
        "fulfillment_order_id": fulfillment_order_id,
        "entry_type": "sale_payable",
        "gross_minor": gross_minor,
        "idempotency_key": idempotency_key,
        "status": "unbatched",
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_unbatched_payables(
    conn: sqlite3.Connection,
    supplier_id: int,
) -> list[dict]:
    """Return all unbatched payable entries for a supplier."""
    rows = conn.execute(
        """
        SELECT spe.*, fo.order_id
        FROM supplier_payable_entries spe
        JOIN fulfillment_orders fo ON fo.id = spe.fulfillment_order_id
        WHERE spe.supplier_id = ? AND spe.status = 'unbatched'
        ORDER BY spe.created_at ASC
        """,
        (supplier_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_supplier_payable_summary(
    conn: sqlite3.Connection,
    supplier_id: int,
) -> dict:
    """Derive supplier outstanding balance from append-only ledger."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_entries,
            SUM(CASE WHEN status = 'unbatched' THEN gross_minor ELSE 0 END) AS unbatched_minor,
            SUM(CASE WHEN status = 'batched'   THEN gross_minor ELSE 0 END) AS in_batch_minor,
            SUM(CASE WHEN status = 'settled'   THEN gross_minor ELSE 0 END) AS settled_minor,
            SUM(gross_minor) AS total_gross_minor
        FROM supplier_payable_entries
        WHERE supplier_id = ?
        """,
        (supplier_id,),
    ).fetchone()
    return {
        "supplier_id": supplier_id,
        "total_gross_minor":   int(row["total_gross_minor"] or 0),
        "unbatched_minor":     int(row["unbatched_minor"] or 0),
        "in_batch_minor":      int(row["in_batch_minor"] or 0),
        "settled_minor":       int(row["settled_minor"] or 0),
    }
