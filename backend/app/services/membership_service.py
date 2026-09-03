"""Organization membership: who belongs to which organization, in what role.

A user with no row here is an ordinary retail customer and Flow 1 behaves for
them exactly as it did in Phase 1.
"""
from __future__ import annotations

import sqlite3

from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import audit_service, auth_service

ROLES = ("employee", "organization_admin", "procurement_agent", "organization_finance")
STATUSES = ("invited", "active", "inactive")

# Which membership roles may administer the organization itself.
ADMIN_ROLES = ("organization_admin",)
# Which may move money (allocate/adjust credit).
FINANCE_ROLES = ("organization_admin", "organization_finance")
# Which may spend organizational credit on a purchase.
SPENDING_ROLES = ("employee", "organization_admin", "procurement_agent", "organization_finance")


def get_membership(conn: sqlite3.Connection, *, organization_id: int, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM organization_memberships WHERE organization_id = ? AND user_id = ?",
        (organization_id, user_id),
    ).fetchone()


def active_memberships_for_user(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT m.*, o.display_name, o.status AS organization_status, o.credit_policy
        FROM organization_memberships m
        JOIN organizations o ON o.id = m.organization_id
        WHERE m.user_id = ? AND m.status = 'active'
        ORDER BY o.display_name
        """,
        (user_id,),
    ).fetchall()


def add_member(
    db: Database,
    *,
    organization_id: int,
    actor_user_id: int,
    email: str,
    role: str = "employee",
    employee_code: str | None = None,
    department: str | None = None,
    status: str = "active",
    ip_address: str | None = None,
) -> dict:
    """Attach an existing user account to the organization.

    MVP-compatible invite: the person must already have a 70online account.
    A full email-invitation flow (token, acceptance page, expiry) is NOT
    implemented in Phase 2 — see AUDIT_EVIDENCE.md.
    """
    if role not in ROLES:
        raise ValidationError(f"نقش نامعتبر. مقادیر مجاز: {', '.join(ROLES)}", details={"role": role})
    if status not in ("invited", "active"):
        raise ValidationError("وضعیت اولیه فقط می‌تواند invited یا active باشد")

    normalized = auth_service.normalize_email(email)
    with db.write_transaction() as conn:
        org = conn.execute(
            "SELECT id, status FROM organizations WHERE id = ?", (organization_id,)
        ).fetchone()
        if org is None:
            raise NotFoundError("سازمان یافت نشد", code="organization_not_found")

        user = conn.execute(
            "SELECT id, full_name, email FROM users WHERE email_normalized = ?", (normalized,)
        ).fetchone()
        if user is None:
            raise NotFoundError(
                "کاربری با این ایمیل در ۷۰آنلاین ثبت‌نام نکرده است. "
                "ابتدا باید حساب بسازد، سپس او را اضافه کنید.",
                code="user_not_registered",
            )
        try:
            cursor = conn.execute(
                """
                INSERT INTO organization_memberships
                    (organization_id, user_id, role, status, employee_code, department, invited_by_user_id)
                VALUES (?,?,?,?,?,?,?)
                """,
                (organization_id, int(user["id"]), role, status,
                 (employee_code or "").strip() or None, (department or "").strip() or None, actor_user_id),
            )
        except sqlite3.IntegrityError as exc:
            if "employee_code" in str(exc):
                raise ConflictError("این کد پرسنلی قبلاً استفاده شده است", code="employee_code_taken") from exc
            raise ConflictError(
                "این کاربر از قبل عضو این سازمان است", code="membership_exists"
            ) from exc
        membership_id = int(cursor.lastrowid)
        audit_service.record(
            conn, action="membership.added", entity_type="organization_membership",
            entity_id=membership_id, actor_user_id=actor_user_id,
            metadata={"organization_id": organization_id, "user_id": int(user["id"]),
                      "role": role, "status": status},
            ip_address=ip_address,
        )
    return get_member(db, organization_id=organization_id, membership_id=membership_id)


def update_member(
    db: Database,
    *,
    organization_id: int,
    membership_id: int,
    actor_user_id: int,
    role: str | None = None,
    status: str | None = None,
    ip_address: str | None = None,
) -> dict:
    if role is None and status is None:
        raise ValidationError("هیچ تغییری ارسال نشده است")
    if role is not None and role not in ROLES:
        raise ValidationError(f"نقش نامعتبر. مقادیر مجاز: {', '.join(ROLES)}", details={"role": role})
    if status is not None and status not in STATUSES:
        raise ValidationError(f"وضعیت نامعتبر. مقادیر مجاز: {', '.join(STATUSES)}")

    with db.write_transaction() as conn:
        # organization_id is in the WHERE clause: an admin of org A editing an
        # id that belongs to org B gets a 404, not someone else's record.
        row = conn.execute(
            "SELECT * FROM organization_memberships WHERE id = ? AND organization_id = ?",
            (membership_id, organization_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("عضویت یافت نشد", code="membership_not_found")

        if row["user_id"] == actor_user_id and status == "inactive":
            raise ValidationError(
                "نمی‌توانید عضویت خودتان را غیرفعال کنید", code="cannot_deactivate_self"
            )
        if row["user_id"] == actor_user_id and role is not None and role != row["role"]:
            raise PermissionError_(
                "نمی‌توانید نقش خودتان را تغییر دهید", code="cannot_change_own_role"
            )
        if row["role"] == "organization_admin" and (role not in (None, "organization_admin")
                                                    or status == "inactive"):
            remaining = conn.execute(
                """
                SELECT COUNT(*) AS n FROM organization_memberships
                WHERE organization_id = ? AND role = 'organization_admin'
                  AND status = 'active' AND id <> ?
                """,
                (organization_id, membership_id),
            ).fetchone()["n"]
            if remaining == 0:
                raise ConflictError(
                    "سازمان باید حداقل یک مدیر فعال داشته باشد", code="last_admin"
                )

        updates, params = [], []
        if role is not None:
            updates.append("role = ?")
            params.append(role)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        conn.execute(
            f"UPDATE organization_memberships SET {', '.join(updates)}, updated_at = datetime('now')"
            " WHERE id = ? AND organization_id = ?",
            (*params, membership_id, organization_id),
        )
        audit_service.record(
            conn, action="membership.updated", entity_type="organization_membership",
            entity_id=membership_id, actor_user_id=actor_user_id,
            metadata={"organization_id": organization_id, "role": role, "status": status,
                      "previous_role": row["role"], "previous_status": row["status"]},
            ip_address=ip_address,
        )
    return get_member(db, organization_id=organization_id, membership_id=membership_id)


def _member_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "organization_id": row["organization_id"],
        "user_id": row["user_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "status": row["status"],
        "employee_code": row["employee_code"],
        "department": row["department"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


MEMBER_SELECT = """
    SELECT m.*, u.full_name, u.email
    FROM organization_memberships m JOIN users u ON u.id = m.user_id
"""


def get_member(db: Database, *, organization_id: int, membership_id: int) -> dict:
    with db.read_transaction() as conn:
        row = conn.execute(
            f"{MEMBER_SELECT} WHERE m.id = ? AND m.organization_id = ?",
            (membership_id, organization_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("عضویت یافت نشد", code="membership_not_found")
        return _member_dict(row)


def list_members(db: Database, *, organization_id: int) -> dict:
    with db.read_transaction() as conn:
        rows = conn.execute(
            f"{MEMBER_SELECT} WHERE m.organization_id = ? ORDER BY u.full_name",
            (organization_id,),
        ).fetchall()
    return {"items": [_member_dict(r) for r in rows], "total": len(rows)}
