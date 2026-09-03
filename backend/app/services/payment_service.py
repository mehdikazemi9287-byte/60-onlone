"""Payment intent state machine.

WHY THIS EXISTS
---------------
Phase 1 called the PSP from inside the database transaction. That is safe only
because the PSP is an in-process mock: with a real gateway the call is a
network round trip that can time out *after* the money moved, and no database
rollback can un-charge a card. A transaction that spans an external call is a
lie about atomicity.

So checkout is two-phase, with a durable record between the phases:

    ┌─ tx 1 ──────────────────────────────────────────────┐
    │ reserve stock, reserve credit, write payment_intent  │
    │ (status = authorized) + immutable line snapshot      │  COMMIT
    └──────────────────────────────────────────────────────┘
                    │  no transaction is open here
                    ▼
             provider.charge(...)          ← the only external call
                    │
    ┌─ tx 2 ──────────┴───────────────────────────────────┐
    │ success: create order, capture credit, post ledger   │
    │ failure: release credit, restore stock, mark failed  │  COMMIT
    └──────────────────────────────────────────────────────┘

If the process dies between the phases, the intent survives in `authorized`
with its holds intact. `reclaim_stale_intent` below releases those holds after
a grace period so the stock and credit are not stranded.

HOW A REAL PSP PLUGS IN LATER
-----------------------------
A redirect-based Iranian gateway (or any 3-D Secure flow) fits this shape
without redesign:

  * tx 1 stays exactly as is, and the API returns the intent reference plus the
    gateway's redirect URL instead of a finished order;
  * the browser leaves for the gateway and comes back to a callback route;
  * that callback — and, independently, the gateway's server-to-server
    webhook — both run phase 2, keyed on `payment_intents.reference`. Phase 2
    is written to be idempotent precisely so the callback and the webhook can
    race without double-creating an order;
  * a reconciliation job walks `payment_intents` still in `authorized` past
    their grace period, asks the gateway for the authoritative status, and
    either completes or releases them.

Nothing in this module assumes the mock. `provider.charge` is the port defined
in `app/adapters/payment/base.py`.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.core.errors import ConflictError, NotFoundError

# How long an authorized-but-unfinished attempt keeps its holds before another
# attempt may reclaim them. Generous, because reclaiming a live payment would
# be worse than making a customer wait.
RECLAIM_AFTER_SECONDS = 900

VALID_TRANSITIONS = {
    "pending": {"authorized", "failed", "cancelled"},
    "authorized": {"captured", "failed", "cancelled"},
    "captured": set(),
    "failed": set(),
    "cancelled": set(),
}


def new_reference() -> str:
    return f"PI-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(5).upper()}"


def create_intent(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    idempotency_key: str,
    request_hash: str,
    quote: dict,
    address: dict,
    lines: list[dict],
) -> int:
    """Phase-1 record. Committed before any external call is made."""
    cart = quote["cart"]
    organization_id = (quote.get("organization") or {}).get("id")
    allocation_id = (quote.get("allocation") or {}).get("id")
    credit_minor = int(quote["credit_to_use_minor"])

    # Tax snapshot — persisted so _complete_attempt reads from intent, not recalculates.
    tax_minor          = int(quote.get("tax_minor", 0))
    taxable_base_minor = int(quote.get("taxable_base_minor", int(cart["subtotal_minor"])))
    tax_rate_bps       = int(quote.get("tax_rate_bps", 0))

    redeem_coins = int(quote.get("redeem_coins", 0))
    redeem_discount_minor = int(quote.get("redeem_discount_minor", 0))

    cursor = conn.execute(
        """
        INSERT INTO payment_intents
            (reference, user_id, idempotency_key, request_hash, status, currency,
             subtotal_minor, shipping_fee_minor, tax_minor, taxable_base_minor, tax_rate_bps,
             total_minor, credit_minor, cash_minor,
             organization_id, allocation_id,
             recipient_name, recipient_phone, shipping_province, shipping_city,
             shipping_line1, shipping_postal_code,
             redeem_coins, redeem_discount_minor)
        VALUES (?,?,?,?, 'pending', ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            new_reference(), user_id, idempotency_key, request_hash, quote["currency"],
            int(cart["subtotal_minor"]), int(cart["shipping_fee_minor"]),
            tax_minor, taxable_base_minor, tax_rate_bps,
            int(cart["total_minor"]),
            credit_minor, int(quote["cash_due_minor"]),
            organization_id if credit_minor > 0 else None,
            allocation_id if credit_minor > 0 else None,
            address["recipient_name"], address["recipient_phone"], address["province"],
            address["city"], address["line1"], address["postal_code"],
            redeem_coins, redeem_discount_minor,
        ),
    )
    intent_id = int(cursor.lastrowid)

    allowed_categories = set((quote.get("allocation") or {}).get("category_slugs") or [])
    for line in lines:
        eligible = 1 if (not allowed_categories or line["category_slug"] in allowed_categories) else 0
        conn.execute(
            """
            INSERT INTO payment_intent_items
                (payment_intent_id, product_id, title_fa, sku, category_slug,
                 unit_price_minor, quantity, line_total_minor, credit_eligible)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (intent_id, line["product_id"], line["title_fa"], line["sku"], line["category_slug"],
             line["unit_price_minor"], line["quantity"], line["line_total_minor"], eligible),
        )
    return intent_id


def transition(conn: sqlite3.Connection, intent_id: int, new_status: str, **fields) -> None:
    row = conn.execute("SELECT status FROM payment_intents WHERE id = ?", (intent_id,)).fetchone()
    if row is None:
        raise NotFoundError("پرداخت یافت نشد", code="payment_intent_not_found")
    current = row["status"]
    if new_status == current:
        return
    if new_status not in VALID_TRANSITIONS[current]:
        raise ConflictError(
            f"انتقال وضعیت پرداخت از {current} به {new_status} مجاز نیست",
            code="invalid_payment_transition",
        )
    assignments = ["status = ?", "updated_at = datetime('now')"]
    params: list = [new_status]
    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        params.append(value)
    conn.execute(
        f"UPDATE payment_intents SET {', '.join(assignments)} WHERE id = ?", (*params, intent_id)
    )


def get_intent(conn: sqlite3.Connection, intent_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM payment_intents WHERE id = ?", (intent_id,)).fetchone()
    if row is None:
        raise NotFoundError("پرداخت یافت نشد", code="payment_intent_not_found")
    return row


def intent_items(conn: sqlite3.Connection, intent_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payment_intent_items WHERE payment_intent_id = ? ORDER BY id",
        (intent_id,),
    ).fetchall()


def restore_stock(conn: sqlite3.Connection, intent_id: int) -> None:
    """Give back everything the attempt was holding."""
    for item in intent_items(conn, intent_id):
        conn.execute(
            """
            UPDATE inventory
            SET quantity_available = quantity_available + ?,
                quantity_reserved = MAX(0, quantity_reserved - ?),
                updated_at = datetime('now')
            WHERE product_id = ?
            """,
            (item["quantity"], item["quantity"], item["product_id"]),
        )


def consume_stock_reservation(conn: sqlite3.Connection, intent_id: int) -> None:
    """Goods are now sold: drop the reserved counter, keep available as decremented."""
    for item in intent_items(conn, intent_id):
        conn.execute(
            """
            UPDATE inventory
            SET quantity_reserved = MAX(0, quantity_reserved - ?), updated_at = datetime('now')
            WHERE product_id = ?
            """,
            (item["quantity"], item["product_id"]),
        )


def is_stale(row: sqlite3.Row, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    return now - created > timedelta(seconds=RECLAIM_AFTER_SECONDS)


def reclaim_stale_intent(conn: sqlite3.Connection, intent_id: int, *, actor_user_id: int | None) -> None:
    """Release the holds of an abandoned attempt so they are not stranded forever.

    Called opportunistically when a new attempt collides with an old one. In
    production this belongs in a scheduled reconciliation job as well — that
    job is NOT implemented in Phase 2.
    """
    from app.services import audit_service, credit_service

    row = get_intent(conn, intent_id)
    if row["status"] not in ("pending", "authorized"):
        return
    credit_service.release(
        conn, payment_intent_id=intent_id, actor_user_id=actor_user_id,
        reason="آزادسازی خودکار پرداخت رهاشده",
    )
    restore_stock(conn, intent_id)
    transition(conn, intent_id, "cancelled", failure_reason="abandoned: reclaimed by a later attempt")
    audit_service.record(
        conn, action="payment.intent_reclaimed", entity_type="payment_intent", entity_id=intent_id,
        actor_user_id=actor_user_id,
        metadata={"reference": row["reference"], "credit_minor": row["credit_minor"]},
    )
