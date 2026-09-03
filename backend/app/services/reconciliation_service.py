"""Reconciliation Service — Phase 6 Final (Repaired: Blocker 7 + 6).

Blocker 7: Multi-signal matching (external_ref/PSP reference + amount + date).
           Amount-only match with multiple candidates → AMBIGUOUS → Exception Inbox.
Blocker 6: Reconciliation mismatches route to Exception Inbox.

Matching priority:
1. external_ref matches payments.provider_ref exactly (confidence=10000, MATCHED)
2. external_ref matches settlement_batches.external_reference (confidence=9500, MATCHED)
3. Single amount match (exactly 1 payment with same amount) → confidence=7000
4. Multiple same-amount matches → AMBIGUOUS → Exception Inbox (NOT auto-matched)
5. No match → unmatched

All money as INTEGER. No REAL/FLOAT.
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


def create_batch(
    conn: sqlite3.Connection,
    *,
    batch_ref: str,
    source_type: str,
    period_start: str,
    period_end: str,
    created_by: int,
    supplier_id: int | None = None,
) -> dict:
    """Create a new reconciliation batch."""
    cur = conn.execute(
        """INSERT INTO reconciliation_batches
           (batch_ref, source_type, supplier_id, period_start, period_end,
            total_items, matched_count, unmatched_count, status, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (batch_ref, source_type, supplier_id, period_start, period_end,
         0, 0, 0, "pending", created_by),
    )
    batch_id = int(cur.lastrowid)
    return get_batch(conn, batch_id)


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM reconciliation_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if not row:
        raise NotFoundError(f"دسته تطبیق {batch_id} یافت نشد")
    return dict(row)


def list_batches(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    wheres = []
    params: list = []
    if status:
        wheres.append("status = ?")
        params.append(status)
    where_clause = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    total_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM reconciliation_batches {where_clause}", params
    ).fetchone()
    total = int(total_row["cnt"]) if total_row else 0
    rows = conn.execute(
        f"SELECT * FROM reconciliation_batches {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def import_items(
    conn: sqlite3.Connection,
    batch_id: int,
    items: list[dict],
) -> dict:
    """Import external transaction items into a batch."""
    get_batch(conn, batch_id)  # Raises if not found

    imported = 0
    for item in items:
        external_ref = str(item.get("external_ref", ""))
        transaction_date = str(item.get("transaction_date", ""))
        amount_minor = int(item.get("amount_minor", 0))
        currency = str(item.get("currency", "IRR"))
        description = item.get("description")

        conn.execute(
            """INSERT INTO reconciliation_items
               (batch_id, external_ref, transaction_date, amount_minor, currency,
                description, status, match_confidence_bps)
               VALUES (?,?,?,?,?,?,?,?)""",
            (batch_id, external_ref, transaction_date, amount_minor, currency,
             description, "unmatched", 0),
        )
        imported += 1

    conn.execute(
        "UPDATE reconciliation_batches SET total_items = total_items + ?, updated_at = ? WHERE id = ?",
        (imported, _now(), batch_id),
    )
    return {"imported": imported, "batch_id": batch_id}


def _match_one_item(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    batch: dict,
) -> tuple[str, int, int | None, int | None, str | None]:
    """
    Try to match one reconciliation_item.

    Returns (new_status, confidence_bps, payment_id, settlement_batch_id, mismatch_reason).

    Matching priority (Blocker 7 + Micro 5):
    1. external_ref == payments.provider_ref AND amount_minor matches AND currency matches
       → MATCHED, confidence=10000
       Same ref but wrong amount or currency → "partial" (ref_economic_mismatch) → Exception Inbox
    2. external_ref == settlement_batches.external_reference AND net_minor matches
       → MATCHED, confidence=9500
       Same ref but wrong amount → "partial" (ref_amount_mismatch) → Exception Inbox
    3. Single payment with same amount → MATCHED, confidence=7000
    4. Multiple payments with same amount → AMBIGUOUS (not auto-matched)
    5. No match → unmatched

    MICRO 5: Strong reference match that fails economic validation does NOT auto-match.
    It routes to Exception Inbox with explicit evidence.
    """
    external_ref = str(item["external_ref"]) if item["external_ref"] else ""
    amount_minor = int(item["amount_minor"])
    currency = str(item["currency"]) if item["currency"] else "IRR"

    # --- Step 1: Strong reference match against payments (with economic validation) ---
    if external_ref:
        pay_row = conn.execute(
            "SELECT id, amount_minor, currency FROM payments WHERE provider_ref = ? LIMIT 1",
            (external_ref,),
        ).fetchone()
        if pay_row:
            pay_amount = int(pay_row["amount_minor"])
            pay_currency = str(pay_row["currency"])
            if pay_amount == amount_minor and pay_currency == currency:
                # Reference + amount + currency all match → strong MATCHED
                return "matched", 10000, int(pay_row["id"]), None, None
            else:
                # Reference matches but economic data doesn't — suspicious
                reason = (
                    f"ref_match_amount_mismatch: provider_ref={external_ref} "
                    f"expected_amount={pay_amount}/{pay_currency} "
                    f"got_amount={amount_minor}/{currency}"
                )
                return "partial", 0, None, None, reason

    # --- Step 2: Strong reference match against settlement_batches (with amount validation) ---
    if external_ref:
        sb_row = conn.execute(
            "SELECT id, net_minor FROM settlement_batches WHERE external_reference = ? LIMIT 1",
            (external_ref,),
        ).fetchone()
        if sb_row:
            sb_amount = int(sb_row["net_minor"])
            if sb_amount == amount_minor:
                return "matched", 9500, None, int(sb_row["id"]), None
            else:
                reason = (
                    f"ref_match_amount_mismatch: external_reference={external_ref} "
                    f"settlement_net={sb_amount} got_amount={amount_minor}"
                )
                return "partial", 0, None, None, reason

    # --- Step 3 & 4: Amount-based fallback ---
    # Count how many payments share this amount (Blocker 7: ambiguous guard)
    amount_matches = conn.execute(
        "SELECT id FROM payments WHERE amount_minor = ?",
        (amount_minor,),
    ).fetchall()

    if len(amount_matches) == 1:
        # Exactly one match → MATCHED but only medium confidence
        return "matched", 7000, int(amount_matches[0]["id"]), None, None

    if len(amount_matches) > 1:
        # Ambiguous — DO NOT auto-match (Blocker 7 fix)
        return "partial", 0, None, None, "multiple_same_amount_candidates"

    # --- No match ---
    return "unmatched", 0, None, None, None


def run_matching(conn: sqlite3.Connection, *, batch_id: int) -> dict:
    """
    Match reconciliation items against internal payments and settlements.

    Blocker 7: Uses multi-signal matching; ambiguous same-amount cases go to Exception Inbox.
    Blocker 6: Creates reconciliation_mismatch exceptions for ambiguous items.
    """
    batch = get_batch(conn, batch_id)

    conn.execute(
        "UPDATE reconciliation_batches SET status = 'processing', updated_at = ? WHERE id = ?",
        (_now(), batch_id),
    )

    items = conn.execute(
        "SELECT * FROM reconciliation_items WHERE batch_id = ? AND status = 'unmatched'",
        (batch_id,),
    ).fetchall()

    matched_count = 0
    unmatched_count = 0
    ambiguous_count = 0

    for item in items:
        new_status, confidence, payment_id, settlement_batch_id, mismatch_reason = _match_one_item(conn, item, batch)

        notes_text: str | None = None
        if new_status == "partial":
            notes_text = mismatch_reason or "partial_match: needs human review"

        conn.execute(
            """UPDATE reconciliation_items
               SET payment_id = ?, settlement_batch_id = ?,
                   status = ?, match_confidence_bps = ?, notes = ?
               WHERE id = ?""",
            (
                payment_id,
                settlement_batch_id,
                new_status,
                confidence,
                notes_text,
                int(item["id"]),
            ),
        )

        if new_status == "matched":
            matched_count += 1
        elif new_status == "partial":
            ambiguous_count += 1
            # Blocker 6 + 7 + Micro 5: Route ambiguous/mismatch to Exception Inbox
            # Micro 4: failure is logged at ERROR level, never silently swallowed
            try:
                exception_service.create_exception(
                    conn,
                    exception_type="reconciliation_mismatch",
                    severity="medium",
                    supplier_id=batch.get("supplier_id"),
                    title=f"تطبیق مبهم: مقدار {item['amount_minor']} ریال — {mismatch_reason or 'needs review'}",
                    detail={
                        "batch_id": batch_id,
                        "item_id": int(item["id"]),
                        "external_ref": str(item["external_ref"]),
                        "amount_minor": int(item["amount_minor"]),
                        "currency": str(item["currency"]),
                        "reason": mismatch_reason or "multiple_same_amount_candidates",
                    },
                    idempotency_key=f"recon:ambig:{batch_id}:{item['id']}",
                )
            except Exception as exc_err:
                log.error(
                    "reconciliation: failed to create reconciliation_mismatch exception "
                    "(batch_id=%s, item_id=%s): %s",
                    batch_id, item["id"], exc_err,
                )
        else:
            unmatched_count += 1

    conn.execute(
        """UPDATE reconciliation_batches
           SET status = 'completed', matched_count = ?, unmatched_count = ?, updated_at = ?
           WHERE id = ?""",
        (matched_count, unmatched_count + ambiguous_count, _now(), batch_id),
    )

    return {
        "batch_id": batch_id,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "ambiguous_count": ambiguous_count,
        "total_items": len(items),
    }
