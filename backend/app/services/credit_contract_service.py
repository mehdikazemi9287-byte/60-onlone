"""Phase 4 — credit contracts and weekly statements (Samar model).

The organization, a partner institution or a bank funds the credit and signs a
contract. Every statement weekday (Saturday, Tehran time) a statement of the past
week's usage is issued; it is due `due_days` (7) later. An unpaid statement past its
due date freezes the contract, and a frozen contract blocks new credit reservations
(DB trigger credit_reservations_block_frozen). Recording a payment that clears every
overdue statement unfreezes it again. The platform lends nothing.

Statement math (integer Rial):
    usage    = captures in credit_ledger_entries for the org, period [start, end)
    payments = credit_contract_payments received in [start, end)
    opening  = previous statement's closing (0 for the first)
    closing  = opening + usage - payments
A statement S is PAID when every payment ever recorded on the contract covers all
usage up to S.period_end (FIFO): total_payments >= cumulative_usage(S).
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import audit_service, credit_service

TS_FMT = "%Y-%m-%d %H:%M:%S"
# Iran Standard Time; Iran has observed no DST since 2022.
TEHRAN_OFFSET = timedelta(hours=3, minutes=30)
FUNDER_TYPES = ("org", "institution", "bank")
SATURDAY = 5


# ------------------------------------------------------------------ helpers
def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def fmt(dt: datetime) -> str:
    return _utc(dt).strftime(TS_FMT)


def parse_ts(value: str) -> datetime:
    text = str(value).strip().replace("T", " ").replace("Z", "")[:19]
    for f in (TS_FMT, "%Y-%m-%d"):
        try:
            return datetime.strptime(text if f == TS_FMT else text[:10], f).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValidationError("قالب تاریخ نامعتبر است", details={"value": value})


def _ref(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


def _int(value, field: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} باید عدد صحیح باشد", details={field: "عدد صحیح لازم است"})
    if value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{field} خارج از بازهٔ مجاز است", details={field: f"{minimum}..{maximum}"})
    return value


def next_statement_boundary(after: datetime, weekday: int = SATURDAY) -> datetime:
    """First Tehran-local midnight on `weekday` strictly after `after` (returned in UTC)."""
    local = _utc(after) + TEHRAN_OFFSET
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate = midnight + timedelta(days=(weekday - midnight.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate - TEHRAN_OFFSET


def _contract_row(conn, contract_id: int, organization_id: int | None = None):
    row = conn.execute("SELECT * FROM credit_contracts WHERE id = ?", (contract_id,)).fetchone()
    if row is None or (organization_id is not None and int(row["organization_id"]) != organization_id):
        raise NotFoundError("قرارداد اعتباری یافت نشد", code="credit_contract_not_found")
    return row


def _event(conn, contract_id: int, event_type: str, reason: str | None, actor_user_id: int | None,
           now: datetime | None = None) -> None:
    conn.execute(
        "INSERT INTO credit_contract_events (contract_id, event_type, reason, actor_user_id, created_at) "
        "VALUES (?,?,?,?,?)",
        (contract_id, event_type, reason, actor_user_id, fmt(_utc(now))),
    )


def contract_dict(conn, row) -> dict:
    data = {k: row[k] for k in row.keys()}
    data.pop("idempotency_key", None)
    data["outstanding_minor"] = outstanding_minor(conn, int(row["id"]))
    data["headroom_minor"] = int(row["limit_minor"]) - data["outstanding_minor"]
    return data


def statement_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


# ---------------------------------------------------------------- contracts
def create_contract(conn: sqlite3.Connection, *, organization_id: int, payload: dict,
                    actor_user_id: int | None, idempotency_key: str,
                    now: datetime | None = None) -> tuple[bool, dict]:
    """Sign a credit contract. Idempotent on idempotency_key. Returns (created, contract)."""
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    existing = conn.execute("SELECT * FROM credit_contracts WHERE idempotency_key = ?",
                            (idempotency_key,)).fetchone()
    if existing is not None:
        if int(existing["organization_id"]) != organization_id:
            raise ConflictError("کلید یکتایی برای سازمان دیگری استفاده شده است", code="idempotency_conflict")
        return False, contract_dict(conn, existing)

    org = conn.execute("SELECT id, status FROM organizations WHERE id = ?", (organization_id,)).fetchone()
    if org is None:
        raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
    funder_type = payload.get("funder_type", "org")
    if funder_type not in FUNDER_TYPES:
        raise ValidationError("نوع تأمین‌کنندهٔ اعتبار نامعتبر است", details={"funder_type": list(FUNDER_TYPES)})
    funder_name = (payload.get("funder_name") or "").strip() or None
    if funder_type != "org" and not funder_name:
        raise ValidationError("نام مؤسسه یا بانک تأمین‌کننده لازم است", details={"funder_name": "لازم"})
    limit_minor = _int(payload.get("limit_minor"), "limit_minor")
    weekday = _int(payload.get("statement_weekday", SATURDAY), "statement_weekday", minimum=0, maximum=6)
    due_days = _int(payload.get("due_days", 7), "due_days", minimum=0, maximum=90)
    if payload.get("cycle", "weekly") != "weekly":
        raise ValidationError("فعلاً فقط دورهٔ هفتگی پشتیبانی می‌شود", details={"cycle": "weekly"})
    starts_at = fmt(parse_ts(payload["starts_at"])) if payload.get("starts_at") else fmt(_utc(now))

    live = conn.execute(
        "SELECT id FROM credit_contracts WHERE organization_id = ? AND status IN ('active','frozen')",
        (organization_id,),
    ).fetchone()
    if live is not None:
        raise ConflictError("این سازمان قرارداد اعتباری فعال دارد", code="credit_contract_exists",
                            details={"contract_id": int(live["id"])})
    stamp = fmt(_utc(now))
    cursor = conn.execute(
        """
        INSERT INTO credit_contracts
            (reference, organization_id, funder_type, funder_name, funder_reference, contract_number,
             limit_minor, cycle, statement_weekday, due_days, status, starts_at, signed_at,
             signed_by_name, idempotency_key, created_by_user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?, 'weekly', ?,?, 'active', ?,?,?,?,?,?,?)
        """,
        (_ref("CC"), organization_id, funder_type, funder_name, payload.get("funder_reference"),
         payload.get("contract_number"), limit_minor, weekday, due_days, starts_at,
         payload.get("signed_at") or stamp, payload.get("signed_by_name"), idempotency_key,
         actor_user_id, stamp, stamp),
    )
    contract_id = int(cursor.lastrowid)
    _event(conn, contract_id, "created", None, actor_user_id, now)
    audit_service.record(conn, action="credit_contract.created", entity_type="credit_contract",
                         entity_id=contract_id, actor_user_id=actor_user_id,
                         metadata={"organization_id": organization_id, "limit_minor": limit_minor,
                                   "funder_type": funder_type})
    return True, contract_dict(conn, _contract_row(conn, contract_id))


def live_contract(conn, organization_id: int):
    return conn.execute(
        "SELECT * FROM credit_contracts WHERE organization_id = ? AND status IN ('active','frozen') "
        "ORDER BY id DESC LIMIT 1",
        (organization_id,),
    ).fetchone()


def list_contracts(conn, organization_id: int | None = None) -> list[dict]:
    if organization_id is None:
        rows = conn.execute("SELECT * FROM credit_contracts ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM credit_contracts WHERE organization_id = ? ORDER BY id DESC",
                            (organization_id,)).fetchall()
    return [contract_dict(conn, r) for r in rows]


def get_contract(conn, contract_id: int, organization_id: int | None = None) -> dict:
    return contract_dict(conn, _contract_row(conn, contract_id, organization_id))


def _set_status(conn, row, status: str, reason: str | None, event: str, actor_user_id: int | None,
                now: datetime | None) -> None:
    stamp = fmt(_utc(now))
    conn.execute(
        "UPDATE credit_contracts SET status = ?, freeze_reason = ?, updated_at = ?, "
        "closed_at = CASE WHEN ? = 'closed' THEN ? ELSE closed_at END WHERE id = ?",
        (status, reason if status == "frozen" else None, stamp, status, stamp, int(row["id"])),
    )
    _event(conn, int(row["id"]), event, reason, actor_user_id, now)
    audit_service.record(conn, action=f"credit_contract.{event}", entity_type="credit_contract",
                         entity_id=int(row["id"]), actor_user_id=actor_user_id,
                         metadata={"organization_id": int(row["organization_id"]), "reason": reason})


def freeze(conn, contract_id: int, *, actor_user_id: int | None, reason: str = "manual",
           now: datetime | None = None) -> dict:
    row = _contract_row(conn, contract_id)
    if row["status"] == "closed":
        raise ConflictError("قرارداد بسته شده است", code="credit_contract_closed")
    if row["status"] != "frozen":
        _set_status(conn, row, "frozen", reason, "frozen", actor_user_id, now)
    return get_contract(conn, contract_id)


def unfreeze(conn, contract_id: int, *, actor_user_id: int | None, now: datetime | None = None) -> dict:
    """Manual unfreeze. Refused while an overdue statement is still unpaid."""
    row = _contract_row(conn, contract_id)
    if row["status"] != "frozen":
        return get_contract(conn, contract_id)
    refresh_statements(conn, contract_id, now)
    if _has_overdue(conn, contract_id):
        raise ConflictError("تا تسویهٔ صورت‌حساب معوق، اعتبار باز نمی‌شود", code="statement_overdue")
    _set_status(conn, row, "active", None, "unfrozen", actor_user_id, now)
    return get_contract(conn, contract_id)


def close(conn, contract_id: int, *, actor_user_id: int | None, now: datetime | None = None) -> dict:
    row = _contract_row(conn, contract_id)
    if row["status"] != "closed":
        # Closing keeps the credit blocked only if something is still owed: the freeze
        # trigger keys on 'frozen', so a closed contract with debt stays frozen instead.
        if outstanding_minor(conn, contract_id) > 0:
            raise ConflictError("قرارداد بدهی باز دارد و قابل بستن نیست", code="credit_contract_has_balance")
        _set_status(conn, row, "closed", None, "closed", actor_user_id, now)
    return get_contract(conn, contract_id)


# ----------------------------------------------------------------- payments
def record_payment(conn, contract_id: int, *, amount_minor: int, idempotency_key: str,
                   actor_user_id: int | None, received_at: str | None = None,
                   external_reference: str | None = None, note: str | None = None,
                   now: datetime | None = None) -> tuple[bool, dict]:
    """Record a funder payment (no money moves here). Unfreezes when overdue debt is cleared."""
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    existing = conn.execute("SELECT * FROM credit_contract_payments WHERE idempotency_key = ?",
                            (idempotency_key,)).fetchone()
    if existing is not None:
        if int(existing["contract_id"]) != contract_id or int(existing["amount_minor"]) != amount_minor:
            raise ConflictError("کلید یکتایی با درخواست دیگری استفاده شده است", code="idempotency_conflict")
        return False, {"payment": dict(existing), "contract": get_contract(conn, contract_id)}
    row = _contract_row(conn, contract_id)
    amount_minor = _int(amount_minor, "amount_minor")
    stamp = fmt(_utc(now))
    received = fmt(parse_ts(received_at)) if received_at else stamp
    cursor = conn.execute(
        """
        INSERT INTO credit_contract_payments
            (reference, contract_id, amount_minor, received_at, external_reference, note,
             idempotency_key, actor_user_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (_ref("CCP"), contract_id, amount_minor, received, external_reference, note,
         idempotency_key, actor_user_id, stamp),
    )
    audit_service.record(conn, action="credit_contract.payment_recorded", entity_type="credit_contract",
                         entity_id=contract_id, actor_user_id=actor_user_id,
                         metadata={"amount_minor": amount_minor, "organization_id": int(row["organization_id"])})
    enforce_contract(conn, contract_id, now)
    payment = conn.execute("SELECT * FROM credit_contract_payments WHERE id = ?",
                           (int(cursor.lastrowid),)).fetchone()
    return True, {"payment": dict(payment), "contract": get_contract(conn, contract_id)}


def _payments_between(conn, contract_id: int, start: str, end: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) AS n FROM credit_contract_payments "
        "WHERE contract_id = ? AND received_at >= ? AND received_at < ?",
        (contract_id, start, end),
    ).fetchone()
    return int(row["n"])


def total_payments(conn, contract_id: int) -> int:
    row = conn.execute("SELECT COALESCE(SUM(amount_minor),0) AS n FROM credit_contract_payments "
                       "WHERE contract_id = ?", (contract_id,)).fetchone()
    return int(row["n"])


def outstanding_minor(conn, contract_id: int, now: datetime | None = None) -> int:
    """Usage since contract start minus every payment. Negative = prepaid."""
    row = _contract_row(conn, contract_id)
    usage = credit_service.organization_usage_minor(
        conn, organization_id=int(row["organization_id"]), period_start=row["starts_at"],
        period_end=fmt(_utc(now) + timedelta(seconds=1)),
    )
    return usage - total_payments(conn, contract_id)


# --------------------------------------------------------------- statements
def issue_due_statements(conn, contract_id: int, now: datetime | None = None) -> list[dict]:
    """Issue every statement whose period has ended (catch-up safe, idempotent)."""
    row = _contract_row(conn, contract_id)
    now = _utc(now)
    org_id = int(row["organization_id"])
    weekday = int(row["statement_weekday"])
    issued: list[dict] = []
    last = conn.execute(
        "SELECT * FROM credit_statements WHERE contract_id = ? ORDER BY period_start DESC LIMIT 1",
        (contract_id,),
    ).fetchone()
    cursor_dt = parse_ts(last["period_end"]) if last else parse_ts(row["starts_at"])
    opening = int(last["closing_minor"]) if last else 0
    boundary = next_statement_boundary(cursor_dt, weekday)
    while boundary <= now:
        start, end = fmt(cursor_dt), fmt(boundary)
        usage = credit_service.organization_usage_minor(conn, organization_id=org_id,
                                                        period_start=start, period_end=end)
        payments = _payments_between(conn, contract_id, start, end)
        closing = opening + usage - payments
        due_at = fmt(boundary + timedelta(days=int(row["due_days"])))
        status = "paid" if closing <= 0 else "open"
        stamp = fmt(now)
        conn.execute(
            """
            INSERT INTO credit_statements
                (reference, contract_id, organization_id, period_start, period_end, opening_minor,
                 usage_minor, payments_minor, closing_minor, due_at, status, paid_at, issued_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (_ref("CST"), contract_id, org_id, start, end, opening, usage, payments, closing, due_at,
             status, stamp if status == "paid" else None, stamp, stamp),
        )
        issued.append(statement_dict(conn.execute(
            "SELECT * FROM credit_statements WHERE contract_id = ? AND period_start = ?",
            (contract_id, start)).fetchone()))
        opening, cursor_dt = closing, boundary
        boundary = next_statement_boundary(cursor_dt, weekday)
    return issued


def refresh_statements(conn, contract_id: int, now: datetime | None = None) -> None:
    """Re-derive open/overdue/paid for every unpaid statement (FIFO against payments)."""
    stamp = fmt(_utc(now))
    paid_total = total_payments(conn, contract_id)
    cumulative = 0
    rows = conn.execute("SELECT * FROM credit_statements WHERE contract_id = ? ORDER BY period_start",
                        (contract_id,)).fetchall()
    for st in rows:
        cumulative += int(st["usage_minor"])
        if st["status"] == "paid":
            continue
        if paid_total >= cumulative:
            new_status = "paid"
        elif stamp >= st["due_at"]:
            new_status = "overdue"
        else:
            new_status = "open"
        if new_status != st["status"]:
            conn.execute(
                "UPDATE credit_statements SET status = ?, paid_at = ?, updated_at = ? WHERE id = ?",
                (new_status, stamp if new_status == "paid" else None, stamp, int(st["id"])),
            )


def _has_overdue(conn, contract_id: int) -> bool:
    return conn.execute("SELECT 1 FROM credit_statements WHERE contract_id = ? AND status = 'overdue'",
                        (contract_id,)).fetchone() is not None


def enforce_contract(conn, contract_id: int, now: datetime | None = None) -> str:
    """Refresh statuses; freeze on overdue, unfreeze an overdue-freeze once cleared."""
    refresh_statements(conn, contract_id, now)
    row = _contract_row(conn, contract_id)
    overdue = _has_overdue(conn, contract_id)
    if row["status"] == "active" and overdue:
        _set_status(conn, row, "frozen", "overdue", "frozen", None, now)
        return "frozen"
    if row["status"] == "frozen" and row["freeze_reason"] == "overdue" and not overdue:
        _set_status(conn, row, "active", None, "unfrozen", None, now)
        return "unfrozen"
    return "unchanged"


def run_weekly_statements(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Cron job body: issue due statements for every live contract."""
    now = _utc(now)
    issued = 0
    contracts = conn.execute(
        "SELECT id FROM credit_contracts WHERE status IN ('active','frozen') AND starts_at <= ?",
        (fmt(now),),
    ).fetchall()
    for c in contracts:
        issued += len(issue_due_statements(conn, int(c["id"]), now))
    return {"contracts": len(contracts), "statements_issued": issued}


def enforce_overdue(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Cron job body: mark overdue statements, freeze/unfreeze contracts."""
    result = {"frozen": 0, "unfrozen": 0}
    for c in conn.execute("SELECT id FROM credit_contracts WHERE status IN ('active','frozen')").fetchall():
        outcome = enforce_contract(conn, int(c["id"]), now)
        if outcome in result:
            result[outcome] += 1
    return result


def list_statements(conn, organization_id: int, contract_id: int | None = None) -> list[dict]:
    if contract_id is None:
        rows = conn.execute("SELECT * FROM credit_statements WHERE organization_id = ? "
                            "ORDER BY period_start DESC", (organization_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM credit_statements WHERE organization_id = ? AND contract_id = ? "
                            "ORDER BY period_start DESC", (organization_id, contract_id)).fetchall()
    return [statement_dict(r) for r in rows]


def get_statement(conn, organization_id: int, statement_id: int) -> dict:
    row = conn.execute("SELECT * FROM credit_statements WHERE id = ? AND organization_id = ?",
                       (statement_id, organization_id)).fetchone()
    if row is None:
        raise NotFoundError("صورت‌حساب یافت نشد", code="statement_not_found")
    return statement_dict(row)
