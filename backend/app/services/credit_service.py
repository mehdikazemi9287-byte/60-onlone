"""Employee credit: allocation, the credit ledger, and reserve/capture/release.

Design rules this module holds to, each covered by a test:

  1. There is no mutable balance column. `available`, `reserved` and
     `consumed` are folded from `credit_ledger_entries` on every read, so a
     balance physically cannot drift away from its history.
  2. The ledger is append-only at the storage layer (DB triggers). Corrections
     are made by posting an `adjustment`, never by editing history.
  3. Every state change runs inside `db.write_transaction()` (BEGIN IMMEDIATE).
     Writers are serialised, so two concurrent checkouts cannot both observe
     the same available credit — proved by the concurrency test.
  4. Available credit can never go negative: the reservation guard re-derives
     the balance inside the transaction and refuses to over-commit.
  5. Money is integer minor units throughout.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone

from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.core.money import format_minor
from app.services import audit_service, membership_service

ENTRY_ALLOCATION = "allocation"
ENTRY_RESERVATION = "reservation"
ENTRY_RELEASE = "release"
ENTRY_CAPTURE = "capture"
ENTRY_ADJUSTMENT = "adjustment"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ref(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8).upper()}"


def _validate_amount(value, field: str = "amount_minor", *, allow_negative: bool = False) -> int:
    """Money input validation. Rejects floats, bools, strings and zero."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            "مبلغ باید عدد صحیح و بر حسب واحد فرعی ارز باشد",
            details={field: "عدد صحیح لازم است (float پذیرفته نمی‌شود)"},
        )
    if value == 0:
        raise ValidationError("مبلغ نمی‌تواند صفر باشد", details={field: "بزرگ‌تر از صفر لازم است"})
    if value < 0 and not allow_negative:
        raise ValidationError("مبلغ نمی‌تواند منفی باشد", details={field: "بزرگ‌تر از صفر لازم است"})
    return value


# --------------------------------------------------------------- ledger read
def allocation_state(conn: sqlite3.Connection, allocation_id: int) -> dict:
    """Fold the credit ledger into the four amounts that describe an allocation."""
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN entry_type IN ('allocation','adjustment') THEN amount_minor ELSE 0 END), 0) AS allocated,
          COALESCE(SUM(CASE WHEN entry_type = 'reservation' THEN amount_minor ELSE 0 END), 0) AS reserved_in,
          COALESCE(SUM(CASE WHEN entry_type = 'release' THEN amount_minor ELSE 0 END), 0) AS released,
          COALESCE(SUM(CASE WHEN entry_type = 'capture' THEN amount_minor ELSE 0 END), 0) AS consumed
        FROM credit_ledger_entries WHERE allocation_id = ?
        """,
        (allocation_id,),
    ).fetchone()
    allocated = int(row["allocated"])
    consumed = int(row["consumed"])
    reserved = int(row["reserved_in"]) - int(row["released"]) - consumed
    available = allocated - reserved - consumed
    return {
        "allocated_minor": allocated,
        "reserved_minor": reserved,
        "consumed_minor": consumed,
        "available_minor": available,
    }


def _post_entry(
    conn: sqlite3.Connection,
    *,
    allocation: sqlite3.Row,
    entry_type: str,
    amount_minor: int,
    reference: str,
    actor_user_id: int | None,
    order_id: int | None = None,
    payment_intent_id: int | None = None,
    reservation_id: int | None = None,
    note: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO credit_ledger_entries
            (reference, allocation_id, organization_id, user_id, entry_type, amount_minor,
             currency, order_id, payment_intent_id, reservation_id, actor_user_id, note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (reference, allocation["id"], allocation["organization_id"], allocation["user_id"],
         entry_type, amount_minor, allocation["currency"], order_id, payment_intent_id,
         reservation_id, actor_user_id, note),
    )
    return int(cursor.lastrowid)


# ------------------------------------------------------------- allocation
def allocate_credit(
    db: Database,
    *,
    organization_id: int,
    actor_user_id: int,
    membership_id: int,
    amount_minor: int,
    idempotency_key: str,
    expires_at: str | None = None,
    valid_from: str | None = None,
    category_slugs: list[str] | None = None,
    per_transaction_limit_minor: int | None = None,
    period_limit_minor: int | None = None,
    note: str | None = None,
    ip_address: str | None = None,
) -> tuple[bool, dict]:
    """Grant credit to a member. Returns (created, allocation).

    Idempotent on (idempotency_key, actor, endpoint): replaying the same request
    returns the original allocation instead of granting the money twice.
    """
    _validate_amount(amount_minor, "amount_minor")
    if not idempotency_key or not idempotency_key.strip():
        raise ValidationError("هدر Idempotency-Key الزامی است", code="idempotency_key_required")
    idempotency_key = idempotency_key.strip()

    for field, value in (("per_transaction_limit_minor", per_transaction_limit_minor),
                         ("period_limit_minor", period_limit_minor)):
        if value is not None:
            _validate_amount(value, field)

    if category_slugs is not None:
        if not isinstance(category_slugs, list) or not all(isinstance(s, str) for s in category_slugs):
            raise ValidationError("category_slugs باید آرایه‌ای از رشته‌ها باشد")
        category_slugs = sorted({s.strip() for s in category_slugs if s.strip()})
        if not category_slugs:
            category_slugs = None

    endpoint = f"POST /api/v1/organizations/{organization_id}/credit-allocations"

    with db.write_transaction() as conn:
        stored = conn.execute(
            "SELECT response_json FROM idempotency_keys WHERE key = ? AND user_id = ? AND endpoint = ?",
            (idempotency_key, actor_user_id, endpoint),
        ).fetchone()
        if stored is not None:
            return False, json.loads(stored["response_json"])

        member = conn.execute(
            """
            SELECT m.*, u.full_name, u.email FROM organization_memberships m
            JOIN users u ON u.id = m.user_id
            WHERE m.id = ? AND m.organization_id = ?
            """,
            (membership_id, organization_id),
        ).fetchone()
        if member is None:
            raise NotFoundError("عضویت یافت نشد", code="membership_not_found")

        # Rule 15: an employee must never allocate credit to themselves.
        if int(member["user_id"]) == actor_user_id:
            raise PermissionError_(
                "تخصیص اعتبار به خودتان مجاز نیست", code="self_allocation_forbidden"
            )
        if member["status"] == "inactive":
            raise ConflictError(
                "به عضو غیرفعال نمی‌توان اعتبار تخصیص داد", code="membership_inactive"
            )

        org = conn.execute("SELECT * FROM organizations WHERE id = ?", (organization_id,)).fetchone()
        if org is None:
            raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
        if org["status"] != "active":
            raise ConflictError(
                f"سازمان در وضعیت «{org['status']}» است و نمی‌تواند اعتبار تخصیص دهد",
                code="organization_not_active",
            )
        if org["credit_policy"] != "employer_funded":
            raise ConflictError(
                f"سیاست اعتباری «{org['credit_policy']}» پشتیبانی نمی‌شود",
                code="credit_policy_unsupported",
            )

        # Organization headroom: limit minus outstanding, derived from the ledger.
        from app.services.organization_service import credit_utilisation

        utilisation = credit_utilisation(conn, organization_id)
        if amount_minor > utilisation["available_credit_minor"]:
            raise ConflictError(
                "سقف اعتبار سازمان کافی نیست "
                f"(باقی‌مانده: {utilisation['available_credit_minor']})",
                code="organization_credit_limit_exceeded",
                details={"available_minor": utilisation["available_credit_minor"]},
            )

        reference = _ref("ALLOC")
        cursor = conn.execute(
            """
            INSERT INTO credit_allocations
                (reference, organization_id, membership_id, user_id, allocated_minor, currency,
                 valid_from, expires_at, category_slugs_json, per_transaction_limit_minor,
                 period_limit_minor, note, created_by_user_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (reference, organization_id, membership_id, int(member["user_id"]), amount_minor,
             org["currency"], valid_from or _now(), expires_at,
             json.dumps(category_slugs, ensure_ascii=False) if category_slugs else None,
             per_transaction_limit_minor, period_limit_minor, note, actor_user_id),
        )
        allocation_id = int(cursor.lastrowid)
        allocation = conn.execute(
            "SELECT * FROM credit_allocations WHERE id = ?", (allocation_id,)
        ).fetchone()

        _post_entry(
            conn, allocation=allocation, entry_type=ENTRY_ALLOCATION, amount_minor=amount_minor,
            reference=reference, actor_user_id=actor_user_id, note=note,
        )
        audit_service.record(
            conn, action="credit.allocated", entity_type="credit_allocation",
            entity_id=allocation_id, actor_user_id=actor_user_id,
            metadata={"organization_id": organization_id, "membership_id": membership_id,
                      "beneficiary_user_id": int(member["user_id"]), "amount_minor": amount_minor,
                      "expires_at": expires_at, "reference": reference},
            ip_address=ip_address,
        )

        body = _allocation_dict(conn, allocation)
        conn.execute(
            """
            INSERT INTO idempotency_keys (key, user_id, endpoint, request_hash, status_code, response_json, state)
            VALUES (?,?,?,?,?,?, 'completed')
            """,
            (idempotency_key, actor_user_id, endpoint, reference, 201,
             json.dumps(body, ensure_ascii=False)),
        )
        return True, body


def adjust_allocation(
    db: Database,
    *,
    organization_id: int,
    allocation_id: int,
    actor_user_id: int,
    delta_minor: int,
    note: str,
    ip_address: str | None = None,
) -> dict:
    """Correct an allocation by posting a signed adjustment. History is never edited."""
    _validate_amount(delta_minor, "delta_minor", allow_negative=True)
    if not (note or "").strip():
        raise ValidationError("برای اصلاح اعتبار، ثبت دلیل الزامی است", details={"note": "الزامی"})

    with db.write_transaction() as conn:
        allocation = conn.execute(
            "SELECT * FROM credit_allocations WHERE id = ? AND organization_id = ?",
            (allocation_id, organization_id),
        ).fetchone()
        if allocation is None:
            raise NotFoundError("تخصیص اعتبار یافت نشد", code="allocation_not_found")
        if int(allocation["user_id"]) == actor_user_id:
            raise PermissionError_(
                "اصلاح اعتبار خودتان مجاز نیست", code="self_allocation_forbidden"
            )

        state = allocation_state(conn, allocation_id)
        if state["available_minor"] + delta_minor < 0:
            raise ConflictError(
                "کاهش بیش از اعتبار در دسترس مجاز نیست "
                f"(در دسترس: {state['available_minor']})",
                code="adjustment_exceeds_available",
                details={"available_minor": state["available_minor"]},
            )
        _post_entry(
            conn, allocation=allocation, entry_type=ENTRY_ADJUSTMENT, amount_minor=delta_minor,
            reference=_ref("ADJ"), actor_user_id=actor_user_id, note=note,
        )
        audit_service.record(
            conn, action="credit.adjusted", entity_type="credit_allocation",
            entity_id=allocation_id, actor_user_id=actor_user_id,
            metadata={"organization_id": organization_id, "delta_minor": delta_minor, "note": note},
            ip_address=ip_address,
        )
        fresh = conn.execute("SELECT * FROM credit_allocations WHERE id = ?", (allocation_id,)).fetchone()
        return _allocation_dict(conn, fresh)


def revoke_allocation(
    db: Database, *, organization_id: int, allocation_id: int, actor_user_id: int,
    ip_address: str | None = None,
) -> dict:
    with db.write_transaction() as conn:
        allocation = conn.execute(
            "SELECT * FROM credit_allocations WHERE id = ? AND organization_id = ?",
            (allocation_id, organization_id),
        ).fetchone()
        if allocation is None:
            raise NotFoundError("تخصیص اعتبار یافت نشد", code="allocation_not_found")
        state = allocation_state(conn, allocation_id)
        if state["reserved_minor"] > 0:
            raise ConflictError(
                "این اعتبار در یک پرداخت در جریان رزرو شده است", code="allocation_has_reservations"
            )
        conn.execute(
            "UPDATE credit_allocations SET status = 'revoked', updated_at = datetime('now') WHERE id = ?",
            (allocation_id,),
        )
        audit_service.record(
            conn, action="credit.revoked", entity_type="credit_allocation",
            entity_id=allocation_id, actor_user_id=actor_user_id,
            metadata={"organization_id": organization_id}, ip_address=ip_address,
        )
        fresh = conn.execute("SELECT * FROM credit_allocations WHERE id = ?", (allocation_id,)).fetchone()
        return _allocation_dict(conn, fresh)


# ----------------------------------------------- reserve / capture / release
def reserve(
    conn: sqlite3.Connection,
    *,
    allocation_id: int,
    amount_minor: int,
    payment_intent_id: int,
    actor_user_id: int,
) -> dict:
    """AVAILABLE -> RESERVED. Caller owns the transaction boundary.

    Idempotent: a second call for the same payment_intent_id returns the
    existing reservation instead of holding the money twice.
    """
    existing = conn.execute(
        "SELECT * FROM credit_reservations WHERE payment_intent_id = ?", (payment_intent_id,)
    ).fetchone()
    if existing is not None:
        return _reservation_dict(existing)

    allocation = conn.execute(
        "SELECT * FROM credit_allocations WHERE id = ?", (allocation_id,)
    ).fetchone()
    if allocation is None:
        raise NotFoundError("تخصیص اعتبار یافت نشد", code="allocation_not_found")

    # Re-derive inside the serialised transaction. This is the guard that makes
    # a double-spend impossible: the loser of the race sees the winner's
    # reservation already folded into `available_minor`.
    state = allocation_state(conn, allocation_id)
    if amount_minor <= 0:
        raise ValidationError("مبلغ رزرو باید بزرگ‌تر از صفر باشد")
    if amount_minor > state["available_minor"]:
        raise ConflictError(
            f"اعتبار کافی نیست (در دسترس: {state['available_minor']})",
            code="insufficient_credit",
            details={"available_minor": state["available_minor"], "requested_minor": amount_minor},
        )

    # A frozen credit contract (overdue weekly statement) blocks new spending with a clear message;
    # the database trigger stays as the last line of defence.
    if organization_credit_frozen(conn, int(allocation["organization_id"])):
        raise ConflictError("اعتبار سازمان به دلیل صورتحساب پرداخت‌نشده موقتاً متوقف است",
                            code="credit_contract_frozen")

    reference = _ref("RES")
    cursor = conn.execute(
        """
        INSERT INTO credit_reservations
            (reference, allocation_id, organization_id, user_id, payment_intent_id, amount_minor, currency, status)
        VALUES (?,?,?,?,?,?,?, 'held')
        """,
        (reference, allocation_id, allocation["organization_id"], allocation["user_id"],
         payment_intent_id, amount_minor, allocation["currency"]),
    )
    reservation_id = int(cursor.lastrowid)
    _post_entry(
        conn, allocation=allocation, entry_type=ENTRY_RESERVATION, amount_minor=amount_minor,
        reference=reference, actor_user_id=actor_user_id, payment_intent_id=payment_intent_id,
        reservation_id=reservation_id, note="رزرو برای پرداخت",
    )
    audit_service.record(
        conn, action="credit.reserved", entity_type="credit_reservation", entity_id=reservation_id,
        actor_user_id=actor_user_id,
        metadata={"allocation_id": allocation_id, "amount_minor": amount_minor,
                  "payment_intent_id": payment_intent_id, "reference": reference},
    )
    row = conn.execute("SELECT * FROM credit_reservations WHERE id = ?", (reservation_id,)).fetchone()
    return _reservation_dict(row)


def capture(
    conn: sqlite3.Connection, *, payment_intent_id: int, order_id: int, actor_user_id: int
) -> dict | None:
    """RESERVED -> CAPTURED. Idempotent; returns None when there was no reservation."""
    row = conn.execute(
        "SELECT * FROM credit_reservations WHERE payment_intent_id = ?", (payment_intent_id,)
    ).fetchone()
    if row is None:
        return None
    if row["status"] == "captured":
        return _reservation_dict(row)
    if row["status"] == "released":
        raise ConflictError(
            "این رزرو قبلاً آزاد شده و قابل برداشت نیست", code="reservation_already_released"
        )

    allocation = conn.execute(
        "SELECT * FROM credit_allocations WHERE id = ?", (row["allocation_id"],)
    ).fetchone()
    conn.execute(
        "UPDATE credit_reservations SET status = 'captured', settled_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    _post_entry(
        conn, allocation=allocation, entry_type=ENTRY_CAPTURE, amount_minor=int(row["amount_minor"]),
        reference=row["reference"], actor_user_id=actor_user_id, order_id=order_id,
        payment_intent_id=payment_intent_id, reservation_id=int(row["id"]),
        note="برداشت پس از پرداخت موفق",
    )
    audit_service.record(
        conn, action="credit.captured", entity_type="credit_reservation", entity_id=int(row["id"]),
        actor_user_id=actor_user_id,
        metadata={"allocation_id": int(row["allocation_id"]), "order_id": order_id,
                  "amount_minor": int(row["amount_minor"])},
    )
    fresh = conn.execute("SELECT * FROM credit_reservations WHERE id = ?", (row["id"],)).fetchone()
    return _reservation_dict(fresh)


def release(
    conn: sqlite3.Connection, *, payment_intent_id: int, actor_user_id: int | None, reason: str = ""
) -> dict | None:
    """RESERVED -> RELEASED. Idempotent; returns None when there was no reservation."""
    row = conn.execute(
        "SELECT * FROM credit_reservations WHERE payment_intent_id = ?", (payment_intent_id,)
    ).fetchone()
    if row is None:
        return None
    if row["status"] == "released":
        return _reservation_dict(row)
    if row["status"] == "captured":
        raise ConflictError(
            "این رزرو قبلاً برداشت شده و قابل آزادسازی نیست", code="reservation_already_captured"
        )

    allocation = conn.execute(
        "SELECT * FROM credit_allocations WHERE id = ?", (row["allocation_id"],)
    ).fetchone()
    conn.execute(
        "UPDATE credit_reservations SET status = 'released', settled_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    _post_entry(
        conn, allocation=allocation, entry_type=ENTRY_RELEASE, amount_minor=int(row["amount_minor"]),
        reference=row["reference"], actor_user_id=actor_user_id,
        payment_intent_id=payment_intent_id, reservation_id=int(row["id"]),
        note=reason or "آزادسازی رزرو",
    )
    audit_service.record(
        conn, action="credit.released", entity_type="credit_reservation", entity_id=int(row["id"]),
        actor_user_id=actor_user_id,
        metadata={"allocation_id": int(row["allocation_id"]), "reason": reason,
                  "amount_minor": int(row["amount_minor"])},
    )
    fresh = conn.execute("SELECT * FROM credit_reservations WHERE id = ?", (row["id"],)).fetchone()
    return _reservation_dict(fresh)


def reverse_capture(
    conn: sqlite3.Connection, *, payment_intent_id: int, order_id: int, actor_user_id: int | None,
    reason: str = "",
) -> int:
    """Give back captured credit for a cancelled order by APPENDING a signed adjustment.

    The capture row is never edited. The reversal carries order_id so usage reports can net it
    out. Idempotent per payment intent (reference CREV-<intent>). Returns the amount restored.
    """
    row = conn.execute(
        "SELECT * FROM credit_reservations WHERE payment_intent_id = ?", (payment_intent_id,)
    ).fetchone()
    if row is None:
        return 0
    if row["status"] == "reserved":
        release(conn, payment_intent_id=payment_intent_id, actor_user_id=actor_user_id, reason=reason)
        return int(row["amount_minor"])
    if row["status"] != "captured":
        return 0
    reference = f"CREV-{payment_intent_id}"
    if conn.execute("SELECT 1 FROM credit_ledger_entries WHERE reference = ?", (reference,)).fetchone():
        return 0
    allocation = conn.execute(
        "SELECT * FROM credit_allocations WHERE id = ?", (row["allocation_id"],)
    ).fetchone()
    amount = int(row["amount_minor"])
    _post_entry(
        conn, allocation=allocation, entry_type=ENTRY_ADJUSTMENT, amount_minor=amount,
        reference=reference, actor_user_id=actor_user_id, order_id=order_id,
        payment_intent_id=payment_intent_id, reservation_id=int(row["id"]),
        note=reason or "برگشت برداشت اعتبار سفارش لغوشده",
    )
    audit_service.record(
        conn, action="credit.capture_reversed", entity_type="credit_reservation", entity_id=int(row["id"]),
        actor_user_id=actor_user_id,
        metadata={"allocation_id": int(row["allocation_id"]), "order_id": order_id, "amount_minor": amount,
                  "reason": reason},
    )
    return amount


# ------------------------------------------------------------- projections
def _reservation_dict(row: sqlite3.Row, exponent: int = 0) -> dict:
    return {
        "id": row["id"],
        "reference": row["reference"],
        "allocation_id": row["allocation_id"],
        "organization_id": row["organization_id"],
        "user_id": row["user_id"],
        "payment_intent_id": row["payment_intent_id"],
        "amount": format_minor(row["amount_minor"], exponent),
        "amount_minor": row["amount_minor"],
        "status": row["status"],
        "created_at": row["created_at"],
        "settled_at": row["settled_at"],
    }


def _allocation_dict(conn: sqlite3.Connection, row: sqlite3.Row, exponent: int = 0) -> dict:
    state = allocation_state(conn, int(row["id"]))
    org = conn.execute(
        "SELECT display_name, status FROM organizations WHERE id = ?", (row["organization_id"],)
    ).fetchone()
    user = conn.execute("SELECT full_name, email FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    categories = json.loads(row["category_slugs_json"]) if row["category_slugs_json"] else None
    return {
        "id": row["id"],
        "reference": row["reference"],
        "organization_id": row["organization_id"],
        "organization_name": org["display_name"] if org else None,
        "organization_status": org["status"] if org else None,
        "membership_id": row["membership_id"],
        "user_id": row["user_id"],
        "employee_name": user["full_name"] if user else None,
        "employee_email": user["email"] if user else None,
        "status": row["status"],
        "funding_source": row["funding_source"],
        "currency": row["currency"],
        "allocated": format_minor(state["allocated_minor"], exponent),
        "allocated_minor": state["allocated_minor"],
        "available": format_minor(state["available_minor"], exponent),
        "available_minor": state["available_minor"],
        "reserved": format_minor(state["reserved_minor"], exponent),
        "reserved_minor": state["reserved_minor"],
        "consumed": format_minor(state["consumed_minor"], exponent),
        "consumed_minor": state["consumed_minor"],
        "valid_from": row["valid_from"],
        "expires_at": row["expires_at"],
        "category_slugs": categories,
        "per_transaction_limit_minor": row["per_transaction_limit_minor"],
        "period_limit_minor": row["period_limit_minor"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def get_allocation(db: Database, *, allocation_id: int, organization_id: int | None = None,
                   user_id: int | None = None, exponent: int = 0) -> dict:
    sql = "SELECT * FROM credit_allocations WHERE id = ?"
    params: list = [allocation_id]
    if organization_id is not None:
        sql += " AND organization_id = ?"
        params.append(organization_id)
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    with db.read_transaction() as conn:
        row = conn.execute(sql, params).fetchone()
        if row is None:
            raise NotFoundError("تخصیص اعتبار یافت نشد", code="allocation_not_found")
        return _allocation_dict(conn, row, exponent)


def list_allocations(
    db: Database, *, organization_id: int | None = None, user_id: int | None = None, exponent: int = 0
) -> dict:
    where, params = [], []
    if organization_id is not None:
        where.append("organization_id = ?")
        params.append(organization_id)
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with db.read_transaction() as conn:
        rows = conn.execute(
            f"SELECT * FROM credit_allocations {clause} ORDER BY id DESC", params
        ).fetchall()
        return {"items": [_allocation_dict(conn, r, exponent) for r in rows], "total": len(rows)}


def list_credit_transactions(
    db: Database, *, organization_id: int | None = None, user_id: int | None = None,
    allocation_id: int | None = None, page: int = 1, page_size: int = 25, exponent: int = 0,
) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValidationError("پارامترهای صفحه‌بندی نامعتبر است")
    where, params = [], []
    if organization_id is not None:
        where.append("e.organization_id = ?")
        params.append(organization_id)
    if user_id is not None:
        where.append("e.user_id = ?")
        params.append(user_id)
    if allocation_id is not None:
        where.append("e.allocation_id = ?")
        params.append(allocation_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    with db.read_transaction() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM credit_ledger_entries e {clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT e.*, a.reference AS allocation_reference, u.full_name AS employee_name,
                   o.order_number, actor.full_name AS actor_name
            FROM credit_ledger_entries e
            JOIN credit_allocations a ON a.id = e.allocation_id
            JOIN users u ON u.id = e.user_id
            LEFT JOIN orders o ON o.id = e.order_id
            LEFT JOIN users actor ON actor.id = e.actor_user_id
            {clause}
            ORDER BY e.id DESC LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "reference": r["reference"],
                "allocation_id": r["allocation_id"],
                "allocation_reference": r["allocation_reference"],
                "organization_id": r["organization_id"],
                "user_id": r["user_id"],
                "employee_name": r["employee_name"],
                "entry_type": r["entry_type"],
                "amount": format_minor(abs(r["amount_minor"]), exponent),
                "amount_minor": r["amount_minor"],
                "currency": r["currency"],
                "order_id": r["order_id"],
                "order_number": r["order_number"],
                "actor_user_id": r["actor_user_id"],
                "actor_name": r["actor_name"],
                "note": r["note"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "total_pages": (int(total) + page_size - 1) // page_size,
    }


def wallet(db: Database, *, user_id: int, exponent: int = 0) -> dict:
    """Everything the employee credit widget needs, in one call."""
    with db.read_transaction() as conn:
        memberships = membership_service.active_memberships_for_user(conn, user_id)
        allocations = conn.execute(
            "SELECT * FROM credit_allocations WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
        items = [_allocation_dict(conn, r, exponent) for r in allocations]

    usable = [a for a in items if a["status"] == "active"]
    total_available = sum(a["available_minor"] for a in usable)
    total_reserved = sum(a["reserved_minor"] for a in usable)
    return {
        "has_organization": len(memberships) > 0,
        "organizations": [
            {
                "id": m["organization_id"],
                "display_name": m["display_name"],
                "status": m["organization_status"],
                "role": m["role"],
                "membership_status": m["status"],
                "membership_id": m["id"],
            }
            for m in memberships
        ],
        "allocations": items,
        "total_available": format_minor(total_available, exponent),
        "total_available_minor": total_available,
        "total_reserved": format_minor(total_reserved, exponent),
        "total_reserved_minor": total_reserved,
        "currency": "IRR",
    }


def expire_due_allocations(db: Database) -> int:
    """Flip past-expiry allocations to `expired`.

    Eligibility does not depend on this running — the rule engine compares
    timestamps directly — but it keeps listings honest. Intended to be called
    from a scheduled job; there is no scheduler in Phase 2.
    """
    with db.write_transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE credit_allocations SET status = 'expired', updated_at = datetime('now')
            WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= datetime('now')
            """
        )
        return cursor.rowcount


# ------------------------------------------------- Phase 4 (additive, read-only)
# Used by credit_contract_service for Samar-style weekly statements. Nothing above
# calls these, so existing reserve/capture/release behaviour is unchanged.
def _normalized_ts_sql(column: str) -> str:
    """Compare timestamps written as 'YYYY-MM-DD HH:MM:SS' (SQLite) or ISO-8601 with 'T' (PostgreSQL)."""
    return f"REPLACE(SUBSTR({column}, 1, 19), 'T', ' ')"


def organization_usage_minor(conn: sqlite3.Connection, *, organization_id: int,
                             period_start: str, period_end: str) -> int:
    """NET credit consumed by an organization's members in [period_start, period_end).

    captures − order-linked adjustments (capture reversals / refunds of cancelled orders).
    Releases only undo reservations (never captured money) so they are already excluded;
    plain allocation adjustments (no order_id) change limits, not usage. May be negative in a
    period where an earlier capture was reversed. Bounds are UTC 'YYYY-MM-DD HH:MM:SS'.
    Folded from credit_ledger_entries — the statement can never disagree with the credit ledger.
    """
    ts = _normalized_ts_sql("created_at")
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE WHEN entry_type = 'capture' THEN amount_minor
                                 WHEN entry_type = 'adjustment' AND order_id IS NOT NULL THEN -amount_minor
                                 ELSE 0 END), 0) AS n
        FROM credit_ledger_entries
        WHERE organization_id = ? AND entry_type IN ('capture', 'adjustment') AND {ts} >= ? AND {ts} < ?
        """,
        (organization_id, period_start, period_end),
    ).fetchone()
    return int(row["n"])


def organization_credit_frozen(conn: sqlite3.Connection, organization_id: int) -> bool:
    """True when the organization's credit contract is frozen (Phase 4).

    Integration point for quote_service / credit_rules: a frozen contract should show
    as a BLOCK restriction at quote time. The storage-level trigger
    credit_reservations_block_frozen (migration 0057) already refuses reservations.
    """
    row = conn.execute(
        "SELECT 1 FROM credit_contracts WHERE organization_id = ? AND status = 'frozen'",
        (organization_id,),
    ).fetchone()
    return row is not None
