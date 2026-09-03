"""Organization domain.

Tenant isolation rule for this whole module: every read that is scoped to a
caller takes the caller's identity as a parameter and puts it in the WHERE
clause. There is no "load then check" path, because that pattern leaks
existence through timing and through 403-vs-404.
"""
from __future__ import annotations

import re
import sqlite3

from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.money import format_minor
from app.services import audit_service

VALID_STATUSES = ("pending", "active", "suspended", "inactive")
VALID_POLICIES = ("employer_funded", "platform_funded", "external_provider", "none")
# Iranian شناسه ملی for legal entities is 11 digits; we accept 10-14 to stay
# usable for test data and foreign registrations without becoming a free text field.
NATIONAL_ID_RE = re.compile(r"^\d{10,14}$")

# Only this policy is implemented in Phase 2. The others exist in the schema so
# the column does not need widening, but the service refuses to pretend.
IMPLEMENTED_POLICIES = ("employer_funded",)


def _validate(payload: dict, *, partial: bool = False) -> dict:
    errors: dict[str, str] = {}
    cleaned: dict = {}

    def text(field: str, required: bool, max_len: int = 255) -> None:
        if field not in payload and partial:
            return
        value = (payload.get(field) or "").strip()
        if not value:
            if required:
                errors[field] = "این فیلد الزامی است"
            else:
                cleaned[field] = None
            return
        if len(value) > max_len:
            errors[field] = f"حداکثر {max_len} کاراکتر"
            return
        cleaned[field] = value

    text("legal_name", not partial)
    text("display_name", not partial)
    text("billing_email", False)
    text("billing_phone", False)
    text("billing_address", False, 1000)
    text("economic_code", False)

    if "national_id" in payload or not partial:
        national_id = (payload.get("national_id") or "").strip()
        if not NATIONAL_ID_RE.match(national_id):
            errors["national_id"] = "شناسه ملی باید بین ۱۰ تا ۱۴ رقم باشد"
        else:
            cleaned["national_id"] = national_id

    if "status" in payload:
        if payload["status"] not in VALID_STATUSES:
            errors["status"] = f"مقدار مجاز: {', '.join(VALID_STATUSES)}"
        else:
            cleaned["status"] = payload["status"]

    if "credit_policy" in payload:
        policy = payload["credit_policy"]
        if policy not in VALID_POLICIES:
            errors["credit_policy"] = f"مقدار مجاز: {', '.join(VALID_POLICIES)}"
        elif policy not in IMPLEMENTED_POLICIES:
            errors["credit_policy"] = (
                f"سیاست {policy} در این نسخه پیاده‌سازی نشده است "
                f"(پیاده‌شده: {', '.join(IMPLEMENTED_POLICIES)})"
            )
        else:
            cleaned["credit_policy"] = policy

    if "credit_limit_minor" in payload:
        limit = payload["credit_limit_minor"]
        if isinstance(limit, bool) or not isinstance(limit, int):
            errors["credit_limit_minor"] = "باید عدد صحیح باشد (واحد فرعی ارز)"
        elif limit < 0:
            errors["credit_limit_minor"] = "نمی‌تواند منفی باشد"
        else:
            cleaned["credit_limit_minor"] = limit

    if errors:
        raise ValidationError("اطلاعات سازمان نامعتبر است", details=errors)
    return cleaned


def create_organization(db: Database, *, actor_user_id: int, payload: dict, ip_address: str | None = None) -> dict:
    """Platform-admin operation. Organizations are not self-service in Phase 2."""
    cleaned = _validate(payload)
    cleaned.setdefault("credit_policy", "employer_funded")
    cleaned.setdefault("credit_limit_minor", 0)
    cleaned.setdefault("status", "pending")

    with db.write_transaction() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO organizations
                    (legal_name, display_name, national_id, status, credit_policy,
                     credit_limit_minor, billing_email, billing_phone, billing_address,
                     economic_code, created_by_user_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cleaned["legal_name"], cleaned["display_name"], cleaned["national_id"],
                    cleaned["status"], cleaned["credit_policy"], cleaned["credit_limit_minor"],
                    cleaned.get("billing_email"), cleaned.get("billing_phone"),
                    cleaned.get("billing_address"), cleaned.get("economic_code"), actor_user_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "سازمانی با این شناسه ملی از قبل ثبت شده است", code="organization_exists"
            ) from exc
        org_id = int(cursor.lastrowid)
        audit_service.record(
            conn, action="organization.created", entity_type="organization", entity_id=org_id,
            actor_user_id=actor_user_id,
            metadata={"national_id": cleaned["national_id"], "display_name": cleaned["display_name"]},
            ip_address=ip_address,
        )
    return get_organization(db, organization_id=org_id)


def update_organization(
    db: Database, *, organization_id: int, actor_user_id: int, payload: dict, ip_address: str | None = None
) -> dict:
    cleaned = _validate(payload, partial=True)
    if not cleaned:
        raise ValidationError("هیچ فیلد قابل تغییری ارسال نشده است")

    columns = ", ".join(f"{k} = ?" for k in cleaned)
    with db.write_transaction() as conn:
        before = conn.execute(
            "SELECT status, credit_limit_minor FROM organizations WHERE id = ?", (organization_id,)
        ).fetchone()
        if before is None:
            raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
        try:
            conn.execute(
                f"UPDATE organizations SET {columns}, updated_at = datetime('now') WHERE id = ?",
                (*cleaned.values(), organization_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("شناسه ملی تکراری است", code="organization_exists") from exc
        audit_service.record(
            conn, action="organization.updated", entity_type="organization", entity_id=organization_id,
            actor_user_id=actor_user_id,
            metadata={"changed": sorted(cleaned), "previous_status": before["status"]},
            ip_address=ip_address,
        )
    return get_organization(db, organization_id=organization_id)


def _row_to_dict(row: sqlite3.Row, exponent: int = 0) -> dict:
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "display_name": row["display_name"],
        "national_id": row["national_id"],
        "status": row["status"],
        "credit_policy": row["credit_policy"],
        "credit_limit": format_minor(row["credit_limit_minor"], exponent),
        "credit_limit_minor": row["credit_limit_minor"],
        "currency": row["currency"],
        "billing": {
            "email": row["billing_email"],
            "phone": row["billing_phone"],
            "address": row["billing_address"],
            "economic_code": row["economic_code"],
        },
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def read_organization(conn: sqlite3.Connection, organization_id: int, exponent: int = 0) -> dict:
    row = conn.execute("SELECT * FROM organizations WHERE id = ?", (organization_id,)).fetchone()
    if row is None:
        raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
    data = _row_to_dict(row, exponent)
    data.update(credit_utilisation(conn, organization_id, exponent))
    return data


def get_organization(db: Database, *, organization_id: int, exponent: int = 0) -> dict:
    with db.read_transaction() as conn:
        return read_organization(conn, organization_id, exponent)


def credit_utilisation(conn: sqlite3.Connection, organization_id: int, exponent: int = 0) -> dict:
    """Derived, never stored.

    `available_credit` is the organization's headroom: its limit minus what it
    has already committed to employees and not yet had released.
    """
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN entry_type IN ('allocation','adjustment') THEN amount_minor ELSE 0 END), 0) AS allocated,
          COALESCE(SUM(CASE WHEN entry_type = 'reservation' THEN amount_minor ELSE 0 END), 0)
            - COALESCE(SUM(CASE WHEN entry_type IN ('release','capture') THEN amount_minor ELSE 0 END), 0) AS reserved,
          COALESCE(SUM(CASE WHEN entry_type = 'capture' THEN amount_minor ELSE 0 END), 0) AS consumed
        FROM credit_ledger_entries WHERE organization_id = ?
        """,
        (organization_id,),
    ).fetchone()
    limit_row = conn.execute(
        "SELECT credit_limit_minor FROM organizations WHERE id = ?", (organization_id,)
    ).fetchone()
    limit = int(limit_row["credit_limit_minor"]) if limit_row else 0

    allocated = int(row["allocated"])
    reserved = int(row["reserved"])
    consumed = int(row["consumed"])
    # Outstanding = credit handed out that has not yet been spent or returned.
    outstanding = allocated - consumed
    available = max(0, limit - outstanding)
    return {
        "allocated_total": format_minor(allocated, exponent),
        "allocated_total_minor": allocated,
        "reserved_total": format_minor(reserved, exponent),
        "reserved_total_minor": reserved,
        "consumed_total": format_minor(consumed, exponent),
        "consumed_total_minor": consumed,
        "outstanding_minor": outstanding,
        "available_credit": format_minor(available, exponent),
        "available_credit_minor": available,
    }


def list_organizations_for_user(db: Database, *, user_id: int, exponent: int = 0) -> list[dict]:
    """Only organizations the caller actually belongs to. Tenant scope is the JOIN."""
    with db.read_transaction() as conn:
        rows = conn.execute(
            """
            SELECT o.*, m.role AS membership_role, m.status AS membership_status, m.id AS membership_id
            FROM organizations o
            JOIN organization_memberships m ON m.organization_id = o.id
            WHERE m.user_id = ?
            ORDER BY o.display_name
            """,
            (user_id,),
        ).fetchall()
        result = []
        for row in rows:
            data = _row_to_dict(row, exponent)
            data["membership"] = {
                "id": row["membership_id"],
                "role": row["membership_role"],
                "status": row["membership_status"],
            }
            result.append(data)
        return result


def organization_summary(db: Database, *, organization_id: int, exponent: int = 0) -> dict:
    """Utilisation report for the org admin dashboard."""
    with db.read_transaction() as conn:
        org = read_organization(conn, organization_id, exponent)
        members = conn.execute(
            """
            SELECT status, COUNT(*) AS n FROM organization_memberships
            WHERE organization_id = ? GROUP BY status
            """,
            (organization_id,),
        ).fetchall()
        allocations = conn.execute(
            "SELECT COUNT(*) AS n FROM credit_allocations WHERE organization_id = ? AND status = 'active'",
            (organization_id,),
        ).fetchone()
        orders = conn.execute(
            """
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(total_minor), 0) AS total,
                   COALESCE(SUM(credit_minor), 0) AS credit,
                   COALESCE(SUM(cash_minor), 0) AS cash
            FROM orders WHERE organization_id = ?
            """,
            (organization_id,),
        ).fetchone()
    return {
        "organization": org,
        "members": {row["status"]: row["n"] for row in members},
        "member_total": sum(row["n"] for row in members),
        "active_allocations": int(allocations["n"]),
        "orders": {
            "count": int(orders["n"]),
            "total_minor": int(orders["total"]),
            "total": format_minor(int(orders["total"]), exponent),
            "funded_by_credit_minor": int(orders["credit"]),
            "funded_by_credit": format_minor(int(orders["credit"]), exponent),
            "funded_by_cash_minor": int(orders["cash"]),
            "funded_by_cash": format_minor(int(orders["cash"]), exponent),
        },
    }


def list_organization_orders(
    db: Database, *, organization_id: int, page: int = 1, page_size: int = 20, exponent: int = 0
) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValidationError("پارامترهای صفحه‌بندی نامعتبر است")
    with db.read_transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE organization_id = ?", (organization_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            """
            SELECT o.id, o.order_number, o.status, o.total_minor, o.credit_minor, o.cash_minor,
                   o.currency, o.placed_at, u.full_name AS employee_name, u.email AS employee_email
            FROM orders o JOIN users u ON u.id = o.user_id
            WHERE o.organization_id = ?
            ORDER BY o.id DESC LIMIT ? OFFSET ?
            """,
            (organization_id, page_size, (page - 1) * page_size),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "order_number": r["order_number"],
                "status": r["status"],
                "employee_name": r["employee_name"],
                "employee_email": r["employee_email"],
                "total": format_minor(r["total_minor"], exponent),
                "total_minor": r["total_minor"],
                "credit": format_minor(r["credit_minor"], exponent),
                "credit_minor": r["credit_minor"],
                "cash": format_minor(r["cash_minor"], exponent),
                "cash_minor": r["cash_minor"],
                "currency": r["currency"],
                "placed_at": r["placed_at"],
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "total_pages": (int(total) + page_size - 1) // page_size,
    }
