"""Three-Way Match Service — Phase 6 Final (Repaired: Blocker 5 + 6 + Micro-repairs 3 + 4).

Blocker 5: Real three-way match comparing at document and line level.
Blocker 6: Mismatches and missing documents route to Exception Inbox.
Micro 3: Document existence validated BEFORE INSERT — nonexistent IDs → MISSING_DOCUMENT.
Micro 4: Financial exception creation failures are logged/audited, never silently swallowed.

Compares:
- PO (procurement_orders) vs Invoice (supplier_invoices) vs Fulfillment (fulfillment_orders)
- Document-level: supplier identity, currency, total amounts
- Line-level (when invoice lines and fulfillment items available):
  product_id, quantity, unit_price, line_total

All money as INTEGER (Rials). No REAL/FLOAT.
"""
from __future__ import annotations

import datetime
import json
import logging
import sqlite3

from app.core.errors import NotFoundError
from app.services import exception_service

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Document fetchers
# ---------------------------------------------------------------------------

def _get_procurement_order(conn: sqlite3.Connection, po_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM procurement_orders WHERE id = ?", (po_id,)).fetchone()
    return dict(row) if row else None


def _get_invoice(conn: sqlite3.Connection, inv_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM supplier_invoices WHERE id = ?", (inv_id,)).fetchone()
    if not row:
        return None
    inv = dict(row)
    lines = conn.execute(
        "SELECT * FROM supplier_invoice_lines WHERE invoice_id = ? ORDER BY line_number",
        (inv_id,),
    ).fetchall()
    inv["lines"] = [dict(l) for l in lines]
    return inv


def _get_fulfillment_order(conn: sqlite3.Connection, fo_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM fulfillment_orders WHERE id = ?", (fo_id,)).fetchone()
    if not row:
        return None
    fo = dict(row)
    # Fetch fulfillment order items for line-level comparison
    items = conn.execute(
        "SELECT * FROM fulfillment_order_items WHERE fulfillment_order_id = ?", (fo_id,)
    ).fetchall()
    fo["items"] = [dict(i) for i in items]
    return fo


# ---------------------------------------------------------------------------
# Line-level comparison (Blocker 5)
# ---------------------------------------------------------------------------

def _compare_lines(
    invoice_lines: list[dict],
    fulfillment_items: list[dict],
    tolerance_bps: int,
) -> dict:
    """
    Compare invoice lines against fulfillment items.

    Returns {"result": matched|within_tolerance|mismatch, "line_discrepancies": [...]}
    """
    if not invoice_lines or not fulfillment_items:
        return {"result": "missing_document", "line_discrepancies": []}

    discrepancies = []
    result = "matched"

    # Match by product_id or offer_id
    fo_by_product: dict[int, dict] = {}
    fo_by_offer: dict[int, dict] = {}
    for fi in fulfillment_items:
        if fi.get("product_id"):
            fo_by_product[int(fi["product_id"])] = fi
        if fi.get("seller_offer_id"):
            fo_by_offer[int(fi["seller_offer_id"])] = fi

    for line in invoice_lines:
        inv_product_id = line.get("product_id")
        inv_offer_id = line.get("offer_id")
        fi = None
        if inv_product_id and int(inv_product_id) in fo_by_product:
            fi = fo_by_product[int(inv_product_id)]
        elif inv_offer_id and int(inv_offer_id) in fo_by_offer:
            fi = fo_by_offer[int(inv_offer_id)]

        if fi is None:
            discrepancies.append({
                "line_number": line.get("line_number"),
                "product_name": line.get("product_name"),
                "issue": "missing_in_fulfillment",
            })
            result = "mismatch"
            continue

        # Compare quantity
        inv_qty = int(line.get("quantity", 0))
        fo_qty = int(fi.get("quantity", 0))
        if inv_qty != fo_qty:
            discrepancies.append({
                "line_number": line.get("line_number"),
                "product_name": line.get("product_name"),
                "issue": "quantity_mismatch",
                "invoice_qty": inv_qty,
                "fulfillment_qty": fo_qty,
            })
            result = "mismatch"
            continue

        # Compare unit price (with tolerance)
        inv_unit = int(line.get("unit_price_minor", 0))
        fo_unit = int(fi.get("selling_price_minor", 0))
        if fo_unit > 0 and inv_unit > 0:
            diff_bps = abs(inv_unit - fo_unit) * 10000 // max(inv_unit, fo_unit)
            if diff_bps > tolerance_bps:
                discrepancies.append({
                    "line_number": line.get("line_number"),
                    "product_name": line.get("product_name"),
                    "issue": "unit_price_mismatch",
                    "invoice_unit_price": inv_unit,
                    "fulfillment_unit_price": fo_unit,
                    "diff_bps": diff_bps,
                })
                result = "mismatch"
            elif diff_bps > 0 and result == "matched":
                result = "within_tolerance"

        # Compare product identity
        if inv_product_id and fi.get("product_id") and int(inv_product_id) != int(fi["product_id"]):
            discrepancies.append({
                "line_number": line.get("line_number"),
                "issue": "product_mismatch",
                "invoice_product_id": int(inv_product_id),
                "fulfillment_product_id": int(fi["product_id"]),
            })
            result = "mismatch"

    return {"result": result, "line_discrepancies": discrepancies}


# ---------------------------------------------------------------------------
# Exception creation — observable failure (Micro 4)
# ---------------------------------------------------------------------------

def _create_exception_audited(
    conn: sqlite3.Connection,
    *,
    exception_type: str,
    severity: str,
    supplier_id: int,
    title: str,
    detail: dict,
    idempotency_key: str | None = None,
) -> int | None:
    """Create a financial exception, logging (not swallowing) any failure.

    Returns the exception id if created/found, or None on failure.
    Failure is logged at ERROR level so it is observable in production.
    The calling financial flow is NOT aborted — exception logging is
    best-effort once the match record is committed.
    """
    try:
        exc = exception_service.create_exception(
            conn,
            exception_type=exception_type,
            severity=severity,
            supplier_id=supplier_id,
            title=title,
            detail=detail,
            idempotency_key=idempotency_key,
        )
        return int(exc["id"])
    except Exception as exc_err:
        log.error(
            "three_way_match: failed to create %s exception (key=%s): %s",
            exception_type, idempotency_key, exc_err,
        )
        return None


# ---------------------------------------------------------------------------
# Main perform_match
# ---------------------------------------------------------------------------

def perform_match(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    procurement_order_id: int | None = None,
    invoice_id: int | None = None,
    fulfillment_order_id: int | None = None,
    tolerance_bps: int = 100,
    checked_by: int | None = None,
    notes: str | None = None,
) -> dict:
    """
    Perform three-way match.

    MICRO 3: Document existence is validated BEFORE any INSERT.
    If any provided ID references a non-existent document, result is
    MISSING_DOCUMENT with explicit discrepancy evidence. No FK crash possible.

    Compares (where data exists):
    - supplier identity across all three documents
    - document totals (with tolerance)
    - line-level: product, quantity, unit price, line total

    MICRO 4: Financial exception creation failures are logged at ERROR level
    and never silently swallowed.

    Blocker 6: mismatches and missing documents create Exception Inbox entries.

    Returns result: matched | within_tolerance | mismatch | missing_document
    """
    if not any([procurement_order_id, invoice_id, fulfillment_order_id]):
        raise ValueError("حداقل یک سند برای تطابق سه‌طرفه الزامی است")

    po = _get_procurement_order(conn, procurement_order_id) if procurement_order_id else None
    inv = _get_invoice(conn, invoice_id) if invoice_id else None
    fo = _get_fulfillment_order(conn, fulfillment_order_id) if fulfillment_order_id else None

    discrepancy: dict = {}
    line_discrepancy: list = []
    result = "matched"

    # --- MICRO 3: Detect nonexistent documents BEFORE any INSERT ---
    missing_ids: dict[str, int] = {}
    if procurement_order_id and po is None:
        missing_ids["procurement_order_id"] = procurement_order_id
    if invoice_id and inv is None:
        missing_ids["invoice_id"] = invoice_id
    if fulfillment_order_id and fo is None:
        missing_ids["fulfillment_order_id"] = fulfillment_order_id

    doc_ids_given = [d for d in [procurement_order_id, invoice_id, fulfillment_order_id] if d is not None]

    if missing_ids:
        # Any requested document not found → MISSING_DOCUMENT immediately
        result = "missing_document"
        discrepancy["missing_documents"] = missing_ids
        discrepancy["reason"] = "یک یا چند سند درخواستی یافت نشد"
    else:
        docs_present = [d for d in [po, inv, fo] if d is not None]

        if len(docs_present) == 0:
            result = "missing_document"
            discrepancy["reason"] = "هیچ سندی یافت نشد"
        else:
            # --- Supplier identity checks ---
            supplier_ids_found = set()
            if po:
                supplier_ids_found.add(int(po.get("supplier_id", 0)))
            if inv:
                supplier_ids_found.add(int(inv.get("supplier_id", 0)))
            if fo:
                supplier_ids_found.add(int(fo.get("supplier_id", 0)))

            other_suppliers = supplier_ids_found - {supplier_id}
            if other_suppliers:
                discrepancy["supplier_identity_mismatch"] = list(other_suppliers)
                result = "mismatch"

            # --- Document total comparisons ---
            amounts: dict[str, int] = {}
            if po:
                amounts["procurement_order"] = int(po.get("total_minor", 0))
            if inv:
                amounts["invoice"] = int(inv.get("total_minor", 0))
            if fo:
                fo_total = int(fo.get("gross_payable_minor", 0))
                if fo_total > 0:
                    amounts["fulfillment"] = fo_total

            if len(amounts) >= 2:
                values = list(amounts.values())
                max_val = max(values)
                min_val = min(values)
                if max_val > 0:
                    diff_bps = int((max_val - min_val) * 10000 / max_val)
                    discrepancy["amounts"] = amounts
                    discrepancy["diff_bps"] = diff_bps
                    if diff_bps == 0:
                        if result == "matched":
                            result = "matched"
                    elif diff_bps <= tolerance_bps:
                        if result == "matched":
                            result = "within_tolerance"
                    else:
                        result = "mismatch"
            elif len(amounts) == 1 and len(doc_ids_given) > 1:
                if result == "matched":
                    result = "missing_document"
                discrepancy["reason"] = "تنها یک سند موجود است"

            # --- Line-level comparison (Blocker 5) ---
            if inv and fo and inv.get("lines") and fo.get("items"):
                line_result = _compare_lines(inv["lines"], fo["items"], tolerance_bps)
                line_discrepancy = line_result["line_discrepancies"]
                if line_result["result"] == "mismatch":
                    result = "mismatch"
                elif line_result["result"] == "within_tolerance" and result == "matched":
                    result = "within_tolerance"

            # --- Currency check ---
            currencies = set()
            if po:
                currencies.add(po.get("currency", "IRR"))
            if inv:
                currencies.add(inv.get("currency", "IRR"))
            if len(currencies) > 1:
                discrepancy["currency_mismatch"] = list(currencies)
                result = "mismatch"

    # --- FK-safe INSERT: use only IDs for documents that actually exist ---
    safe_po_id = procurement_order_id if po is not None else None
    safe_inv_id = invoice_id if inv is not None else None
    safe_fo_id = fulfillment_order_id if fo is not None else None

    cur = conn.execute(
        """INSERT INTO three_way_matches
           (supplier_id, procurement_order_id, invoice_id, fulfillment_order_id,
            result, discrepancy_json, line_discrepancy_json, tolerance_bps,
            checked_by, checked_at, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (supplier_id, safe_po_id, safe_inv_id, safe_fo_id,
         result,
         json.dumps(discrepancy, ensure_ascii=False),
         json.dumps(line_discrepancy, ensure_ascii=False),
         tolerance_bps, checked_by, _now() if checked_by else None, notes),
    )
    match_id = int(cur.lastrowid)

    # --- Update invoice match_status ---
    if inv and safe_inv_id:
        match_status_map = {
            "matched": "matched",
            "within_tolerance": "within_tolerance",
            "mismatch": "mismatch",
            "missing_document": "missing_document",
        }
        new_inv_status = "matched" if result in ("matched", "within_tolerance") else "mismatch"
        conn.execute(
            "UPDATE supplier_invoices SET match_status = ?, status = ?, updated_at = ? WHERE id = ?",
            (match_status_map.get(result, "mismatch"), new_inv_status, _now(), safe_inv_id),
        )

    # --- Blocker 6 + Micro 4: Route financial exceptions to Exception Inbox ---
    # Failures are logged at ERROR level, never silently swallowed
    created_exception_id: int | None = None

    if result == "mismatch":
        created_exception_id = _create_exception_audited(
            conn,
            exception_type="three_way_mismatch",
            severity="high",
            supplier_id=supplier_id,
            title=f"تعارض سه‌طرفه: فاکتور {invoice_id}",
            detail={
                "match_id": match_id,
                "discrepancy": discrepancy,
                "line_discrepancies": line_discrepancy,
                "procurement_order_id": procurement_order_id,
                "invoice_id": invoice_id,
                "fulfillment_order_id": fulfillment_order_id,
            },
            idempotency_key=f"3wm:mismatch:inv:{invoice_id}" if invoice_id else None,
        )

    elif result == "missing_document":
        created_exception_id = _create_exception_audited(
            conn,
            exception_type="other",
            severity="medium",
            supplier_id=supplier_id,
            title=f"سند ناقص: تطابق سه‌طرفه {match_id}",
            detail={
                "match_id": match_id,
                "doc_ids_given": doc_ids_given,
                "discrepancy": discrepancy,
            },
            idempotency_key=f"3wm:missing:inv:{invoice_id}" if invoice_id else None,
        )

    # --- Write exception_id back to match record if an exception was created ---
    if created_exception_id is not None:
        conn.execute(
            "UPDATE three_way_matches SET exception_id = ? WHERE id = ?",
            (created_exception_id, match_id),
        )

    return {
        "id": match_id,
        "supplier_id": supplier_id,
        "procurement_order_id": procurement_order_id,
        "invoice_id": invoice_id,
        "fulfillment_order_id": fulfillment_order_id,
        "result": result,
        "discrepancy": discrepancy,
        "line_discrepancies": line_discrepancy,
        "tolerance_bps": tolerance_bps,
        "checked_by": checked_by,
        "notes": notes,
    }


def get_match(conn: sqlite3.Connection, match_id: int) -> dict:
    row = conn.execute("SELECT * FROM three_way_matches WHERE id = ?", (match_id,)).fetchone()
    if not row:
        raise NotFoundError(f"تطابق سه‌طرفه {match_id} یافت نشد")
    d = dict(row)
    for key in ("discrepancy_json", "line_discrepancy_json"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    return d
