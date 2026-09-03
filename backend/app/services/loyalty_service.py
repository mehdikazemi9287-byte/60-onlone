"""60Coin loyalty ledger: earn, redeem, and balance.

Design rules this module holds to (mirrors credit_service.py), each covered
by a test:

  1. There is no mutable balance column. A user's balance is folded from
     `loyalty_ledger_entries` on every read, so it cannot drift away from
     its history.
  2. The ledger is append-only at the storage layer (DB triggers).
     Corrections are made by posting an `adjustment` entry, never by
     editing history.
  3. Every state change runs inside `db.write_transaction()` (BEGIN
     IMMEDIATE). Writers are serialised, so two concurrent redemptions
     cannot both observe the same available balance.
  4. Balance can never go negative: redeem re-derives the balance inside
     the transaction and refuses to over-spend.
  5. Coins are integer units. This module is intentionally isolated from
     `credit_service` / `ledger_service` — coins are not currency and must
     never be summed into a financial trial balance.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone

from app.core.db import Database
from app.core.errors import ConflictError, ValidationError
from app.services import audit_service

ENTRY_EARN = "earn"
ENTRY_REDEEM = "redeem"
ENTRY_EXPIRE = "expire"
ENTRY_ADJUSTMENT = "adjustment"

SOURCES = (
    "purchase", "campaign", "activity", "referral",
    "redemption", "expiry", "manual_adjustment",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ref(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8).upper()}"


def _validate_coins(value, field: str = "amount_coins") -> int:
    """Coin input validation. Rejects floats, bools, strings, zero and negatives.

    Direction (earn vs. redeem) is expressed by which function is called,
    not by the sign the caller passes in — callers always pass a positive
    coin count.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            "مقدار کوین باید عدد صحیح باشد",
            details={field: "عدد صحیح لازم است (float پذیرفته نمی‌شود)"},
        )
    if value <= 0:
        raise ValidationError("مقدار کوین باید بزرگ‌تر از صفر باشد", details={field: "بزرگ‌تر از صفر لازم است"})
    return value


def _validate_source(value: str) -> str:
    if value not in SOURCES:
        raise ValidationError(
            "منبع کوین نامعتبر است",
            details={"source": f"یکی از {SOURCES} باید باشد"},
        )
    return value


def _find_by_idempotency_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM loyalty_ledger_entries WHERE idempotency_key = ?", (key,)
    ).fetchone()


def _entry_dict(row: sqlite3.Row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "reference": row["reference"],
        "user_id": row["user_id"],
        "entry_type": row["entry_type"],
        "amount_coins": row["amount_coins"],
        "source": row["source"],
        "order_id": row["order_id"],
        "note": row["note"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"] if "expires_at" in keys else None,
    }


def balance(conn: sqlite3.Connection, user_id: int) -> int:
    """Fold the ledger into the current coin balance. Never negative by construction."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_coins), 0) AS n FROM loyalty_ledger_entries WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["n"])


def earn(
    db: Database,
    *,
    user_id: int,
    amount_coins: int,
    source: str,
    order_id: int | None = None,
    actor_user_id: int | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    expires_at: str | None = None,
) -> dict:
    """Credit coins to a user. Idempotent when `idempotency_key` is supplied —
    replaying the same key (e.g. a retried order-completion webhook) returns
    the original entry instead of double-crediting.

    `expires_at` (UTC "YYYY-MM-DD HH:MM:SS", optional) is a policy-driven
    expiry stamp — see EXPIRY_POLICY_DAYS and expire_due_coins() below. NULL
    means the entry never expires (the default; adjustments/manual grants
    are not auto-expired unless the caller explicitly sets one).
    """
    amount_coins = _validate_coins(amount_coins)
    source = _validate_source(source)

    with db.write_transaction() as conn:
        if idempotency_key:
            existing = _find_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return {"entry": _entry_dict(existing), "balance_coins": balance(conn, user_id), "created": False}

        cursor = conn.execute(
            """
            INSERT INTO loyalty_ledger_entries
                (reference, user_id, entry_type, amount_coins, source, order_id,
                 idempotency_key, actor_user_id, note, created_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (_ref("LOY"), user_id, ENTRY_EARN, amount_coins, source, order_id,
             idempotency_key, actor_user_id, note, _now(), expires_at),
        )
        entry_id = int(cursor.lastrowid)
        audit_service.record(
            conn, action="loyalty.earn", entity_type="loyalty_ledger_entries", entity_id=entry_id,
            actor_user_id=actor_user_id,
            metadata={"user_id": user_id, "amount_coins": amount_coins, "source": source},
        )
        row = conn.execute("SELECT * FROM loyalty_ledger_entries WHERE id = ?", (entry_id,)).fetchone()
        return {"entry": _entry_dict(row), "balance_coins": balance(conn, user_id), "created": True}


def redeem(
    db: Database,
    *,
    user_id: int,
    amount_coins: int,
    order_id: int | None = None,
    actor_user_id: int | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Debit coins from a user. Re-derives the balance inside the same
    serialised transaction, so it can never spend coins the ledger doesn't
    show — same guard shape as credit reservation.
    """
    amount_coins = _validate_coins(amount_coins)

    with db.write_transaction() as conn:
        if idempotency_key:
            existing = _find_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                return {"entry": _entry_dict(existing), "balance_coins": balance(conn, user_id), "created": False}

        current = balance(conn, user_id)
        if current < amount_coins:
            raise ConflictError(
                "موجودی کوین کافی نیست",
                details={"balance_coins": current, "requested_coins": amount_coins},
            )

        cursor = conn.execute(
            """
            INSERT INTO loyalty_ledger_entries
                (reference, user_id, entry_type, amount_coins, source, order_id,
                 idempotency_key, actor_user_id, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (_ref("LOY"), user_id, ENTRY_REDEEM, -amount_coins, "redemption", order_id,
             idempotency_key, actor_user_id, note, _now()),
        )
        entry_id = int(cursor.lastrowid)
        audit_service.record(
            conn, action="loyalty.redeem", entity_type="loyalty_ledger_entries", entity_id=entry_id,
            actor_user_id=actor_user_id,
            metadata={"user_id": user_id, "amount_coins": amount_coins},
        )
        row = conn.execute("SELECT * FROM loyalty_ledger_entries WHERE id = ?", (entry_id,)).fetchone()
        return {"entry": _entry_dict(row), "balance_coins": balance(conn, user_id), "created": True}


def wallet(db: Database, *, user_id: int) -> dict:
    """Everything a loyalty widget needs: balance, tier, and recent entries."""
    with db.read_transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM loyalty_ledger_entries WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (user_id,),
        ).fetchall()
        return {
            "user_id": user_id,
            "balance_coins": balance(conn, user_id),
            "tier": current_tier(conn, user_id),
            "recent_entries": [_entry_dict(r) for r in rows],
        }


def list_transactions(db: Database, *, user_id: int, page: int = 1, page_size: int = 25) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size
    with db.read_transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) n FROM loyalty_ledger_entries WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT * FROM loyalty_ledger_entries WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (user_id, page_size, offset),
        ).fetchall()
        return {
            "items": [_entry_dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": int(total),
        }


# ─────────────────────────────────────────────────────── checkout redemption
# 1,000 Toman (10,000 IRR minor units) of eligible merchandise = 1 60Coin —
# the same rate checkout_service.py uses to earn coins, applied symmetrically
# in reverse for redemption value. A configurable code-level default (not a
# fabricated business promise): coins may cover at most 50% of the
# merchandise subtotal on a single order.
REDEEM_MINOR_PER_COIN = 10_000
MAX_REDEEM_BPS_OF_SUBTOTAL = 5_000  # 50.00%, basis points


def max_redeemable_coins(subtotal_minor: int, balance_coins: int) -> int:
    """Cap = min(what the user actually has, what the redemption-limit policy
    allows for this subtotal). Never negative, never invented."""
    if subtotal_minor <= 0 or balance_coins <= 0:
        return 0
    cap_minor = subtotal_minor * MAX_REDEEM_BPS_OF_SUBTOTAL // 10_000
    cap_coins = cap_minor // REDEEM_MINOR_PER_COIN
    return max(0, min(balance_coins, cap_coins))


# ───────────────────────────────────────────────────────────────── 60Club
def list_tiers(db: Database) -> list[dict]:
    with db.read_transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM loyalty_tiers WHERE is_active = 1 ORDER BY min_lifetime_coins ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def lifetime_earned_coins(conn: sqlite3.Connection, user_id: int) -> int:
    """Total ever earned (ignores redemptions/expiry) — the tier metric.
    Folded from the ledger on every read, same rule as balance()."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_coins), 0) AS n FROM loyalty_ledger_entries "
        "WHERE user_id = ? AND entry_type = ?",
        (user_id, ENTRY_EARN),
    ).fetchone()
    return int(row["n"])


def current_tier(conn: sqlite3.Connection, user_id: int) -> dict | None:
    lifetime = lifetime_earned_coins(conn, user_id)
    row = conn.execute(
        "SELECT * FROM loyalty_tiers WHERE is_active = 1 AND min_lifetime_coins <= ? "
        "ORDER BY min_lifetime_coins DESC LIMIT 1",
        (lifetime,),
    ).fetchone()
    if row is None:
        return None
    tier = dict(row)
    next_row = conn.execute(
        "SELECT * FROM loyalty_tiers WHERE is_active = 1 AND min_lifetime_coins > ? "
        "ORDER BY min_lifetime_coins ASC LIMIT 1",
        (lifetime,),
    ).fetchone()
    tier["lifetime_coins"] = lifetime
    tier["next_tier"] = dict(next_row) if next_row else None
    tier["coins_to_next_tier"] = (
        int(next_row["min_lifetime_coins"]) - lifetime if next_row else 0
    )
    return tier


# ───────────────────────────────────────────────────────── coin expiration
# Policy: a purchase-earned coin expires EXPIRY_POLICY_DAYS after it was
# earned. This is a code-level default pending a real business decision —
# not a claim about an announced policy.
EXPIRY_POLICY_DAYS = 365


def expiry_stamp_for_new_earn(now: datetime | None = None) -> str:
    """UTC timestamp EXPIRY_POLICY_DAYS from now, for a caller creating a new
    purchase-earn entry. Callers that should never expire (manual grants,
    etc.) simply don't call this and pass expires_at=None instead."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(days=EXPIRY_POLICY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")


def expire_due_coins(db: Database, *, user_id: int, now: datetime | None = None) -> dict:
    """Post an 'expire' entry for any coins whose earn-expiry has passed.

    ACCOUNTING MODEL (documented limitation): this ledger has no per-lot
    consumption tracking (a redemption is a flat negative entry, not linked
    to specific earn entries), so true FIFO "this exact earned lot expired"
    is not representable without a schema change beyond this migration's
    scope. Instead this uses an aggregate FIFO approximation:

        due_minor   = SUM(earn entries with expires_at <= now)
        consumed    = SUM(all redeem + expire entries ever, absolute value)
        expirable   = max(0, due_minor - consumed), capped at current balance

    This is exact as long as redemptions are treated as consuming the
    oldest (soonest-to-expire) coins first, which is the fair, conventional
    "use-it-or-lose-it" assumption used elsewhere in this codebase (see
    quote_service.py's allocation-expiry-first ordering). It will only ever
    under-expire (never over-expire, never invent a negative balance),
    because it is capped at the real current balance.

    Idempotent: running this twice for the same user in the same moment
    posts nothing the second time once `due <= consumed`.
    """
    now = now or datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    with db.write_transaction() as conn:
        due = conn.execute(
            "SELECT COALESCE(SUM(amount_coins), 0) AS n FROM loyalty_ledger_entries "
            "WHERE user_id = ? AND entry_type = ? AND expires_at IS NOT NULL AND expires_at <= ?",
            (user_id, ENTRY_EARN, now_str),
        ).fetchone()["n"]
        consumed = conn.execute(
            "SELECT COALESCE(SUM(-amount_coins), 0) AS n FROM loyalty_ledger_entries "
            "WHERE user_id = ? AND entry_type IN (?, ?)",
            (user_id, ENTRY_REDEEM, ENTRY_EXPIRE),
        ).fetchone()["n"]
        current = balance(conn, user_id)
        expirable = max(0, min(int(due) - int(consumed), current))

        if expirable <= 0:
            return {"expired_coins": 0, "balance_coins": current, "created": False}

        idempotency_key = f"expire:{user_id}:{now.strftime('%Y-%m-%d')}"
        existing = _find_by_idempotency_key(conn, idempotency_key)
        if existing is not None:
            return {"expired_coins": 0, "balance_coins": current, "created": False}

        cursor = conn.execute(
            """
            INSERT INTO loyalty_ledger_entries
                (reference, user_id, entry_type, amount_coins, source, order_id,
                 idempotency_key, actor_user_id, note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (_ref("LOY"), user_id, ENTRY_EXPIRE, -expirable, "expiry", None,
             idempotency_key, None, f"انقضای خودکار کوین‌های زودتر از {now_str}", _now()),
        )
        entry_id = int(cursor.lastrowid)
        audit_service.record(
            conn, action="loyalty.expire", entity_type="loyalty_ledger_entries", entity_id=entry_id,
            actor_user_id=None, metadata={"user_id": user_id, "expired_coins": expirable},
        )
        return {"expired_coins": expirable, "balance_coins": balance(conn, user_id), "created": True}
