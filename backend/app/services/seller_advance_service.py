"""Phase 4 — seller advances (پیش‌پرداخت به فروشنده).

A seller may draw an advance of up to `rate_bps` (default 50%) of its recorded,
delivered-but-unsettled net: supplier_payable_entries with status='unbatched',
net = gross - commission (legacy rows without a snapshot use the 10% default).
    cap       = eligible_net * rate_bps // 10000
    available = max(0, cap - outstanding)
The advance is an obligation (append-only seller_advance_entries + GL), netted
out at the next settlement through `recover_from_settlement`. No money moves here.
GL: grant    Dr 1040 advances to sellers / Cr 2040 advances awaiting disbursement
    recovery Dr 2050 seller payables (settlement offset) / Cr 1040
"""
from __future__ import annotations

import secrets
from datetime import datetime

from app.core.errors import ConflictError, ValidationError
from app.services import audit_service, ledger_service
from app.services.credit_contract_service import _int, _utc, fmt
from app.services.ledger_service import Entry

DEFAULT_RATE_BPS = 5000
LEGACY_COMMISSION_BPS = 1000
ACCOUNT_ADVANCES = "1040"
ACCOUNT_ADVANCES_TO_DISBURSE = "2040"
ACCOUNT_SELLER_PAYABLES = "2050"


def eligible_net_minor(conn, supplier_id: int) -> int:
    rows = conn.execute("SELECT gross_minor, commission_minor FROM supplier_payable_entries "
                        "WHERE supplier_id = ? AND status = 'unbatched'", (supplier_id,)).fetchall()
    return sum(int(r["gross_minor"]) - (int(r["commission_minor"]) if r["commission_minor"] is not None
                                        else int(r["gross_minor"]) * LEGACY_COMMISSION_BPS // 10_000)
               for r in rows)


def outstanding_advance(conn, supplier_id: int) -> int:
    """Settlement integration point: advance still to be netted from the seller's payout."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN entry_type='grant' THEN amount_minor ELSE -amount_minor END),0) AS n "
        "FROM seller_advance_entries WHERE supplier_id = ?", (supplier_id,)).fetchone()
    return int(row["n"])


def eligibility(conn, supplier_id: int, rate_bps: int = DEFAULT_RATE_BPS) -> dict:
    net = eligible_net_minor(conn, supplier_id)
    cap = net * rate_bps // 10_000
    outstanding = outstanding_advance(conn, supplier_id)
    return {"supplier_id": supplier_id, "eligible_net_minor": net, "rate_bps": rate_bps, "cap_minor": cap,
            "outstanding_minor": outstanding, "available_minor": max(0, cap - outstanding)}


def _entry(conn, *, supplier_id, entry_type, amount, idempotency_key, actor_user_id, now,
           basis=None, rate=None, settlement_reference=None) -> dict:
    reference = f"ADV-{secrets.token_hex(6).upper()}"
    if entry_type == "grant":
        entries = [Entry(ACCOUNT_ADVANCES, "debit", amount), Entry(ACCOUNT_ADVANCES_TO_DISBURSE, "credit", amount)]
    else:
        entries = [Entry(ACCOUNT_SELLER_PAYABLES, "debit", amount), Entry(ACCOUNT_ADVANCES, "credit", amount)]
    ledger_service.post_transaction(conn, reference=reference, entries=entries,
                                    description=f"پیش‌پرداخت فروشنده {supplier_id} ({entry_type})")
    conn.execute(
        "INSERT INTO seller_advance_entries (reference, supplier_id, entry_type, amount_minor, basis_net_minor, "
        "rate_bps, settlement_reference, ledger_reference, idempotency_key, actor_user_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (reference, supplier_id, entry_type, amount, basis, rate, settlement_reference, reference,
         idempotency_key, actor_user_id, fmt(_utc(now))),
    )
    audit_service.record(conn, action=f"seller_advance.{entry_type}", entity_type="supplier",
                         entity_id=supplier_id, actor_user_id=actor_user_id, metadata={"amount_minor": amount})
    return dict(conn.execute("SELECT * FROM seller_advance_entries WHERE reference = ?", (reference,)).fetchone())


def request_advance(conn, *, supplier_id: int, idempotency_key: str, actor_user_id: int | None,
                    amount_minor: int | None = None, rate_bps: int = DEFAULT_RATE_BPS,
                    now: datetime | None = None) -> tuple[bool, dict]:
    """Grant an advance (amount defaults to everything available). Idempotent."""
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    existing = conn.execute("SELECT * FROM seller_advance_entries WHERE idempotency_key = ?",
                            (idempotency_key,)).fetchone()
    if existing is not None:
        if int(existing["supplier_id"]) != supplier_id or existing["entry_type"] != "grant":
            raise ConflictError("کلید یکتایی با درخواست دیگری استفاده شده است", code="idempotency_conflict")
        return False, dict(existing)
    health = conn.execute("SELECT health_status FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if health is not None and health["health_status"] == "suspended":
        raise ConflictError("پیش‌پرداخت برای فروشندهٔ معلق مجاز نیست", code="seller_suspended")
    rate_bps = _int(rate_bps, "rate_bps", minimum=0, maximum=9000)
    elig = eligibility(conn, supplier_id, rate_bps)
    amount = elig["available_minor"] if amount_minor is None else _int(amount_minor, "amount_minor")
    if amount <= 0 or amount > elig["available_minor"]:
        raise ConflictError("مبلغ درخواستی از سقف پیش‌پرداخت بیشتر است", code="advance_cap_exceeded",
                            details={"available_minor": elig["available_minor"]})
    return True, _entry(conn, supplier_id=supplier_id, entry_type="grant", amount=amount,
                        idempotency_key=idempotency_key, actor_user_id=actor_user_id, now=now,
                        basis=elig["eligible_net_minor"], rate=rate_bps)


def recover_from_settlement(conn, *, supplier_id: int, available_minor: int, settlement_reference: str,
                            actor_user_id: int | None = None, now: datetime | None = None) -> int:
    """Net the outstanding advance out of a settlement payout. Returns the amount netted.

    Idempotent per settlement_reference (key 'settlement:<ref>:advance-recovery').
    """
    key = f"settlement:{settlement_reference}:advance-recovery"
    existing = conn.execute("SELECT amount_minor FROM seller_advance_entries WHERE idempotency_key = ?",
                            (key,)).fetchone()
    if existing is not None:
        return int(existing["amount_minor"])
    amount = min(outstanding_advance(conn, supplier_id), max(0, int(available_minor)))
    if amount <= 0:
        return 0
    _entry(conn, supplier_id=supplier_id, entry_type="recovery", amount=amount, idempotency_key=key,
           actor_user_id=actor_user_id, now=now, settlement_reference=settlement_reference)
    return amount


def list_entries(conn, supplier_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM seller_advance_entries WHERE supplier_id = ? ORDER BY id DESC",
                        (supplier_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("idempotency_key", None)
        out.append(d)
    return out
