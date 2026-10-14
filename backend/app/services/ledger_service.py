"""Double-entry, append-only ledger.

Invariants enforced here and covered by tests:
  1. Every transaction has >= 2 entries.
  2. sum(debits) == sum(credits), exactly, in integer minor units.
  3. Entry amounts are strictly positive.
  4. Entries are never updated or deleted (DB triggers make this impossible).
  5. No balance is ever stored as a mutable column -- balances are derived by
     folding the entries, so a balance cannot drift away from the ledger.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.core.errors import ConflictError, ValidationError

# Chart of accounts used by Flow 1.
ACCOUNT_PSP_CLEARING = "1010"
# Phase 2: the credit leg of a split payment is not cash — it is a receivable
# from the employing organization, which will be invoiced later. Keeping it in
# its own account is what makes the funding source of an order auditable.
ACCOUNT_ORG_RECEIVABLE = "1020"
# Phase 8 v6: VAT collected from customers is a liability (owed to the tax
# authority), not platform revenue.  Posting it to a dedicated liability account
# keeps tax payable separate from merchandise and shipping income, which is the
# correct accounting treatment under a VAT regime.
ACCOUNT_VAT_PAYABLE = "2010"
ACCOUNT_SALES_REVENUE = "4010"
ACCOUNT_SHIPPING_REVENUE = "4020"

DEFAULT_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    (ACCOUNT_PSP_CLEARING, "حساب واسط درگاه پرداخت", "asset"),
    (ACCOUNT_ORG_RECEIVABLE, "مطالبات از سازمان‌ها (اعتبار سازمانی)", "asset"),
    (ACCOUNT_VAT_PAYABLE, "مالیات بر ارزش افزوده پرداختنی", "liability"),
    (ACCOUNT_SALES_REVENUE, "درآمد فروش کالا", "revenue"),
    (ACCOUNT_SHIPPING_REVENUE, "درآمد حمل و نقل", "revenue"),
)

DEBIT_POSITIVE_TYPES = {"asset", "expense"}


@dataclass(frozen=True)
class Entry:
    account_code: str
    direction: str  # 'debit' | 'credit'
    amount_minor: int


def ensure_accounts(conn: sqlite3.Connection) -> None:
    for code, name_fa, type_ in DEFAULT_ACCOUNTS:
        conn.execute(
            "INSERT OR IGNORE INTO ledger_accounts (code, name_fa, type) VALUES (?,?,?)",
            (code, name_fa, type_),
        )


def _account_id(conn: sqlite3.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM ledger_accounts WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ValidationError(f"Unknown ledger account code {code!r}")
    return int(row["id"])


def post_transaction(
    conn: sqlite3.Connection,
    *,
    reference: str,
    description: str,
    entries: list[Entry],
    currency: str = "IRR",
) -> int:
    """Append one balanced transaction. Caller supplies the transaction boundary."""
    if len(entries) < 2:
        raise ValidationError("a double-entry transaction needs at least two entries")

    maximum = 9223372036854775807
    for entry in entries:
        if entry.direction not in ("debit", "credit"):
            raise ValidationError(f"invalid direction {entry.direction!r}")
        if type(entry.amount_minor) is not int or not 1 <= entry.amount_minor <= maximum:
            raise ValidationError("ledger amounts must be positive integers within database range")
    debits = sum(e.amount_minor for e in entries if e.direction == "debit")
    credits = sum(e.amount_minor for e in entries if e.direction == "credit")
    if debits > maximum or credits > maximum:
        raise ValidationError("ledger transaction total exceeds database range")

    if debits != credits:
        raise ValidationError(
            f"unbalanced transaction: debits={debits} credits={credits}"
        )

    ensure_accounts(conn)
    try:
        cursor = conn.execute(
            "INSERT INTO ledger_transactions (reference, description) VALUES (?,?)",
            (reference, description),
        )
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"ledger transaction {reference!r} already posted") from exc
    tx_id = int(cursor.lastrowid)

    for entry in entries:
        conn.execute(
            """
            INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor, currency)
            VALUES (?,?,?,?,?)
            """,
            (tx_id, _account_id(conn, entry.account_code), entry.direction, entry.amount_minor, currency),
        )
    return tx_id


def account_balance_minor(conn: sqlite3.Connection, account_code: str) -> int:
    """Derived balance. Never read from a stored column."""
    row = conn.execute(
        """
        SELECT a.type AS type,
               COALESCE(SUM(CASE WHEN e.direction='debit'  THEN e.amount_minor ELSE 0 END), 0) AS d,
               COALESCE(SUM(CASE WHEN e.direction='credit' THEN e.amount_minor ELSE 0 END), 0) AS c
        FROM ledger_accounts a
        LEFT JOIN ledger_entries e ON e.account_id = a.id
        WHERE a.code = ?
        GROUP BY a.id
        """,
        (account_code,),
    ).fetchone()
    if row is None:
        raise ValidationError(f"Unknown ledger account code {account_code!r}")
    debit, credit = int(row["d"]), int(row["c"])
    return debit - credit if row["type"] in DEBIT_POSITIVE_TYPES else credit - debit


def trial_balance(conn: sqlite3.Connection) -> tuple[int, int]:
    """(total_debits, total_credits) across the whole ledger. Must be equal."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN direction='debit'  THEN amount_minor ELSE 0 END),0) AS d,
               COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor ELSE 0 END),0) AS c
        FROM ledger_entries
        """
    ).fetchone()
    return int(row["d"]), int(row["c"])


def entries_for_reference(conn: sqlite3.Connection, reference: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.code AS account_code, a.name_fa AS account_name, e.direction, e.amount_minor, e.created_at
        FROM ledger_entries e
        JOIN ledger_transactions t ON t.id = e.transaction_id
        JOIN ledger_accounts a ON a.id = e.account_id
        WHERE t.reference = ?
        ORDER BY e.id
        """,
        (reference,),
    ).fetchall()
    return [dict(r) for r in rows]
