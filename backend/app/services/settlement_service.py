"""Settlement service (BLOCKERS 7 + 8 + 9).

Architecture:
  - Settlement batches are IDEMPOTENT (BLOCKER 7)
  - Settlement payments are APPEND-ONLY (BLOCKER 8)
  - Shipping cost payer is explicit (BLOCKER 9)
  - All arithmetic is integer (BLOCKER 5 — no floats)

Settlement lifecycle:
  pending → processing → completed
                       ↘ failed

When a batch reaches 'completed', exactly ONE settlement_payment row is
appended.  Retrying completion is safe: if a payment already exists, the
existing payment is returned without creating a duplicate.

Real bank payout: NOT IMPLEMENTED.
Settlement amounts are computed and recorded; actual bank transfers are out
of scope for Phase 5.

Rounding policy:
  commission_minor = (gross_minor * commission_rate_bps) // 10_000
  net_minor = gross_minor - commission_minor - shipping_charge_minor
  All integer floor division.  No floats.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import supplier_ledger_service

log = logging.getLogger("70online.settlement")

DEFAULT_COMMISSION_RATE_BPS = 1000  # 10%


# ---------------------------------------------------------------------------
# Create settlement batch (BLOCKER 7 — idempotent)
# ---------------------------------------------------------------------------

def create_settlement_batch(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    payable_entry_ids: list[int],
    idempotency_key: str,
    commission_rate_bps: int | None = None,
    release_held: bool = False,
    shipping_charge_minor: int = 0,
    shipping_payer: str = "customer",
) -> dict:
    """Create an idempotent settlement batch.

    BLOCKER 7 rules:
      - Same idempotency_key → returns the SAME batch (no duplicate).
      - An entry that is already in another batch → ConflictError (409).
      - NEVER swallow UNIQUE violations silently.
      - commission_minor = (gross_minor * commission_rate_bps) // 10_000

    shipping_payer controls whether shipping_charge is deducted from supplier:
      - 'supplier' → shipping_charge_minor deducted from net
      - 'customer'/'organization'/'platform' → supplier net is unaffected

    BLOCKER 5:
      All arithmetic is integer.  commission_rate_bps must be int.  No floats.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise ValidationError("idempotency_key is required for settlement batch")
    if commission_rate_bps is not None and (not isinstance(commission_rate_bps, int) or commission_rate_bps < 0):
        raise ValidationError("commission_rate_bps must be a non-negative integer")
    if not isinstance(shipping_charge_minor, int) or shipping_charge_minor < 0:
        raise ValidationError("shipping_charge_minor must be a non-negative integer")
    if shipping_payer not in ("customer", "organization", "platform", "supplier"):
        raise ValidationError(f"invalid shipping_payer: {shipping_payer!r}")

    # Idempotency: return existing batch if same key
    existing = conn.execute(
        "SELECT * FROM settlement_batches WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if existing is not None:
        existing_dict = dict(existing)
        if int(existing_dict["supplier_id"]) != supplier_id:
            raise ConflictError(
                "Idempotency key used for a different supplier",
                code="idempotency_key_supplier_mismatch",
            )
        items = conn.execute(
            "SELECT sbi.*, spe.gross_minor FROM settlement_batch_items sbi "
            "JOIN supplier_payable_entries spe ON spe.id = sbi.supplier_payable_entry_id "
            "WHERE sbi.settlement_batch_id = ?",
            (existing_dict["id"],),
        ).fetchall()
        return {**existing_dict, "items": [dict(i) for i in items]}

    # Verify all entries exist, belong to this supplier, and are unbatched
    if not payable_entry_ids:
        raise ValidationError("payable_entry_ids must not be empty")

    entries = conn.execute(
        f"SELECT * FROM supplier_payable_entries WHERE id IN ({','.join('?' * len(payable_entry_ids))})",
        payable_entry_ids,
    ).fetchall()
    entries_by_id = {int(e["id"]): dict(e) for e in entries}

    for eid in payable_entry_ids:
        entry = entries_by_id.get(eid)
        if entry is None:
            raise NotFoundError(f"Payable entry {eid} not found", code="entry_not_found")
        if int(entry["supplier_id"]) != supplier_id:
            raise ConflictError(
                f"Entry {eid} does not belong to supplier {supplier_id}",
                code="entry_supplier_mismatch",
            )
        if entry["status"] != "unbatched":
            raise ConflictError(
                f"Entry {eid} is already in status '{entry['status']}' "
                "and cannot be added to a new batch. "
                "Use the existing batch or conflict is returned.",
                code="entry_already_batched",
            )

    # Escrow: entries still inside the buyer's protection window are not settleable,
    # nor is anything owed to a seller whose account health is suspended.
    if not release_held:
        from app.services import seller_shop_service
        import datetime as _dt
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        held = [eid for eid in payable_entry_ids
                if entries_by_id[eid].get("available_at") and entries_by_id[eid]["available_at"] > stamp]
        if held:
            raise ConflictError("این مبالغ هنوز در دورهٔ امانت (بعد از تحویل) هستند",
                                code="payable_on_hold", details={"entry_ids": held})
        health = conn.execute("SELECT health_status, payout_hold FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if health is not None and health["payout_hold"]:
            raise ConflictError("شبای این فروشنده تازه تغییر کرده و منتظر تأیید ادمین است",
                                code="payout_account_unverified")
        if health is not None and health["health_status"] == "suspended":
            raise ConflictError("تسویهٔ این فروشنده به دلیل وضعیت سلامت حساب متوقف است",
                                code="seller_suspended")

    # Compute financials — integer arithmetic only (BLOCKER 5)
    gross_minor = sum(entries_by_id[eid]["gross_minor"] for eid in payable_entry_ids)
    if commission_rate_bps is None:
        # Per-entry snapshots (category/channel rules); legacy entries fall back to the default rate.
        commission_minor = sum(
            entries_by_id[eid]["commission_minor"] if entries_by_id[eid].get("commission_minor") is not None
            else (entries_by_id[eid]["gross_minor"] * DEFAULT_COMMISSION_RATE_BPS) // 10_000
            for eid in payable_entry_ids)
        commission_rate_bps = (commission_minor * 10_000) // gross_minor if gross_minor else 0
    else:
        commission_minor = (gross_minor * commission_rate_bps) // 10_000  # integer floor division
    # Shipping charge only deducted if supplier pays
    effective_shipping = shipping_charge_minor if shipping_payer == "supplier" else 0
    net_minor = gross_minor - commission_minor - effective_shipping

    # Phase 4: an advance already paid to the seller is netted out of this payout (idempotent per batch key).
    advance_recovered = 0
    if net_minor > 0:
        try:
            from app.services import seller_advance_service
            advance_recovered = seller_advance_service.recover_from_settlement(
                conn, supplier_id=supplier_id, available_minor=net_minor, settlement_reference=idempotency_key)
        except ImportError:  # pragma: no cover
            advance_recovered = 0
        net_minor -= advance_recovered

    if net_minor < 0:
        raise ValidationError(
            f"Settlement net would be negative: gross={gross_minor} "
            f"commission={commission_minor} shipping={effective_shipping}",
            code="negative_net",
        )

    # Create the batch
    cursor = conn.execute(
        """
        INSERT INTO settlement_batches
            (supplier_id, idempotency_key, status,
             commission_rate_bps, gross_minor, commission_minor,
             shipping_charge_minor, net_minor, items_count)
        VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)
        """,
        (supplier_id, idempotency_key, commission_rate_bps,
         gross_minor, commission_minor, effective_shipping,
         net_minor, len(payable_entry_ids)),
    )
    batch_id = int(cursor.lastrowid)

    # Link entries to batch (UNIQUE constraint prevents double-batching)
    try:
        for eid in payable_entry_ids:
            conn.execute(
                """
                INSERT INTO settlement_batch_items
                    (settlement_batch_id, supplier_payable_entry_id, gross_minor)
                VALUES (?, ?, ?)
                """,
                (batch_id, eid, entries_by_id[eid]["gross_minor"]),
            )
    except Exception as exc:
        # UNIQUE violation on supplier_payable_entry_id means an entry slipped into
        # another batch between our check and insert.  NEVER swallow this silently.
        raise ConflictError(
            "One or more entries were concurrently added to another batch. "
            "This batch has not been created.",
            code="concurrent_batch_conflict",
        ) from exc

    # Mark entries as batched
    conn.execute(
        f"""
        UPDATE supplier_payable_entries
        SET status = 'batched', settlement_batch_id = ?
        WHERE id IN ({','.join('?' * len(payable_entry_ids))})
        """,
        [batch_id] + list(payable_entry_ids),
    )

    items = conn.execute(
        "SELECT * FROM settlement_batch_items WHERE settlement_batch_id = ?", (batch_id,)
    ).fetchall()
    batch = conn.execute(
        "SELECT * FROM settlement_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    return {**dict(batch), "items": [dict(i) for i in items], "advance_recovered_minor": advance_recovered}


# ---------------------------------------------------------------------------
# Complete settlement batch (BLOCKER 8 — append-only payment)
# ---------------------------------------------------------------------------

def complete_settlement_batch(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    payment_reference: str | None = None,
    external_reference: str | None = None,
) -> dict:
    """Complete a settlement batch and append exactly ONE settlement_payment entry.

    Idempotent: if the batch is already completed and a payment exists, the
    existing payment is returned without creating a new one.

    NEVER updates or deletes previous ledger entries.
    NEVER creates more than one settlement_payment per batch.

    Real bank payout: NOT IMPLEMENTED — this records the accounting entry only.
    """
    batch = conn.execute(
        "SELECT * FROM settlement_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if batch is None:
        raise NotFoundError(f"Settlement batch {batch_id} not found", code="batch_not_found")

    b = dict(batch)

    if b["status"] == "completed":
        # Already completed — return existing payment idempotently
        payment = conn.execute(
            "SELECT * FROM settlement_payments WHERE settlement_batch_id = ?", (batch_id,)
        ).fetchone()
        return {"batch": b, "payment": dict(payment) if payment else None}

    if b["status"] not in ("pending", "processing"):
        raise ConflictError(
            f"Batch {batch_id} is in status '{b['status']}' and cannot be completed",
            code="batch_not_completable",
        )

    net_minor = int(b["net_minor"])
    if net_minor <= 0:
        raise ValidationError(
            f"Cannot complete settlement with net_minor={net_minor}",
            code="zero_net_settlement",
        )

    # Move to processing
    conn.execute(
        "UPDATE settlement_batches SET status='processing', updated_at=datetime('now') WHERE id=?",
        (batch_id,),
    )

    # Append settlement_payment (append-only — UNIQUE(settlement_batch_id) enforces once)
    try:
        p_cursor = conn.execute(
            """
            INSERT INTO settlement_payments
                (settlement_batch_id, supplier_id, net_minor,
                 payment_reference, external_reference)
            VALUES (?, ?, ?, ?, ?)
            """,
            (batch_id, int(b["supplier_id"]), net_minor,
             payment_reference, external_reference),
        )
    except Exception as exc:
        raise ConflictError(
            f"Settlement payment for batch {batch_id} already exists (concurrent completion?)",
            code="payment_already_exists",
        ) from exc

    payment_id = int(p_cursor.lastrowid)

    # Mark entries as settled
    conn.execute(
        """
        UPDATE supplier_payable_entries
        SET status = 'settled'
        WHERE settlement_batch_id = ?
        """,
        (batch_id,),
    )

    # Mark batch as completed and store references
    conn.execute(
        """
        UPDATE settlement_batches
        SET status = 'completed',
            payment_reference = ?,
            external_reference = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (payment_reference, external_reference, batch_id),
    )

    batch_updated = conn.execute(
        "SELECT * FROM settlement_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    payment = conn.execute(
        "SELECT * FROM settlement_payments WHERE id = ?", (payment_id,)
    ).fetchone()

    log.info(
        "complete_settlement_batch: batch_id=%s supplier=%s net=%s payment_id=%s",
        batch_id, b["supplier_id"], net_minor, payment_id,
    )
    return {"batch": dict(batch_updated), "payment": dict(payment)}


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_settlement_batch(conn: sqlite3.Connection, batch_id: int) -> dict:
    batch = conn.execute(
        "SELECT * FROM settlement_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if batch is None:
        raise NotFoundError(f"Settlement batch {batch_id} not found")
    items = conn.execute(
        """
        SELECT sbi.*, spe.fulfillment_order_id, spe.gross_minor AS entry_gross
        FROM settlement_batch_items sbi
        JOIN supplier_payable_entries spe ON spe.id = sbi.supplier_payable_entry_id
        WHERE sbi.settlement_batch_id = ?
        """,
        (batch_id,),
    ).fetchall()
    payment = conn.execute(
        "SELECT * FROM settlement_payments WHERE settlement_batch_id = ?", (batch_id,)
    ).fetchone()
    return {
        "batch": dict(batch),
        "items": [dict(i) for i in items],
        "payment": dict(payment) if payment else None,
    }


def list_settlement_batches(
    conn: sqlite3.Connection,
    supplier_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    sql = "SELECT * FROM settlement_batches WHERE 1=1"
    params: list = []
    if supplier_id is not None:
        sql += " AND supplier_id = ?"
        params.append(supplier_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
