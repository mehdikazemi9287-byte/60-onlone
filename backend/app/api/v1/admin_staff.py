"""Internal staff roles, login unlock and second-factor reset (super-admin console).

Super-admin = users.role 'admin' (unchanged). Staff roles live in staff_role_assignments and are
granted/revoked here with a reason; every change is written to audit_logs in the same transaction.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core import staff_access
from app.core.deps import client_ip, current_user, get_db, require_auth, still_authorized
from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import audit_service, auth_service, mfa_service

bp = Blueprint("admin_staff", __name__, url_prefix="/api/v1/admin")

STAFF_ELIGIBLE_PLATFORM_ROLES = ("customer", "employee")


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    return d


def _reason(d: dict) -> str:
    r = d.get("reason")
    if not isinstance(r, str) or not 3 <= len(r.strip()) <= 500:
        raise ValidationError("دلیل تغییر الزامی است (۳ تا ۵۰۰ نویسه)")
    return r.strip()


def _user(conn, uid: int):
    row = conn.execute("SELECT id, email, full_name, role, is_active FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None:
        raise NotFoundError("کاربر یافت نشد")
    return row


def _detail(conn, row) -> dict:
    uid = int(row["id"])
    return {
        "user": {k: row[k] for k in ("id", "email", "full_name", "role")} | {"is_active": bool(row["is_active"])},
        "staff_roles": staff_access.active_staff_roles(conn, uid),
        "super_admin": row["role"] == "admin",
        "mfa": mfa_service.status(conn, uid),
        "login_lockout": auth_service.lockout_status(conn, uid),
    }


@bp.get("/staff")
@require_auth("admin")
def staff_overview():
    with get_db().read_transaction() as conn:
        admins = conn.execute("SELECT id, email, full_name, role, is_active FROM users WHERE role = 'admin' "
                              "ORDER BY full_name").fetchall()
        staff = conn.execute(
            "SELECT u.id, u.email, u.full_name, u.role, u.is_active FROM users u WHERE EXISTS ("
            "SELECT 1 FROM staff_role_assignments s WHERE s.user_id = u.id AND s.revoked_at IS NULL) "
            "ORDER BY u.full_name").fetchall()
        return jsonify({
            "roles": [{"code": k, "label": v} for k, v in staff_access.STAFF_ROLES.items()],
            "super_admin_label": staff_access.SUPER_ADMIN_LABEL,
            "super_admins": [_detail(conn, r) for r in admins],
            "staff": [_detail(conn, r) for r in staff],
        })


@bp.get("/staff/users/<int:uid>")
@require_auth("admin")
def staff_user(uid: int):
    with get_db().read_transaction() as conn:
        return jsonify(_detail(conn, _user(conn, uid)))


@bp.put("/staff/users/<int:uid>/roles")
@require_auth("admin")
def staff_set_roles(uid: int):
    d = _body()
    reason = _reason(d)
    roles = d.get("roles")
    if not isinstance(roles, list) or any(r not in staff_access.STAFF_ROLES for r in roles):
        raise ValidationError("فهرست نقش‌ها نامعتبر است", details={"allowed": list(staff_access.STAFF_ROLES)})
    if d.get("confirm_scope") is not True:
        raise ValidationError("تأیید محدودهٔ دسترسی لازم است")
    wanted = set(roles)
    actor = current_user()["id"]
    with get_db().write_transaction() as conn:
        if not still_authorized(conn):
            raise PermissionError_("مجوز مدیریت دیگر فعال نیست")
        row = _user(conn, uid)
        if uid == actor:
            raise ConflictError("تغییر نقش‌های حساب جاری از این صفحه مجاز نیست")
        current = set(staff_access.active_staff_roles(conn, uid))
        expected = d.get("expected_roles")
        if not isinstance(expected, list) or set(expected) != current:
            raise ConflictError("نقش‌های این کاربر تغییر کرده است؛ دوباره بارگذاری کنید")
        if wanted and row["role"] not in STAFF_ELIGIBLE_PLATFORM_ROLES:
            raise ValidationError("نقش کارکنان فقط به حساب مشتری یا کارمند داده می‌شود (مدیر ارشد همه‌چیز را دارد)")
        if wanted and not row["is_active"]:
            raise ValidationError("حساب غیرفعال نقش نمی‌گیرد")
        for role in sorted(wanted - current):
            conn.execute("INSERT INTO staff_role_assignments (user_id, role, granted_by, reason) VALUES (?,?,?,?)",
                         (uid, role, actor, reason))
        for role in sorted(current - wanted):
            conn.execute("UPDATE staff_role_assignments SET revoked_by = ?, revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                         "WHERE user_id = ? AND role = ? AND revoked_at IS NULL", (actor, uid, role))
        if wanted != current:
            audit_service.record(conn, action="user.staff_roles_changed", entity_type="user", entity_id=uid,
                                 actor_user_id=actor, ip_address=client_ip(),
                                 metadata={"before": sorted(current), "after": sorted(wanted), "reason": reason})
        return jsonify(_detail(conn, row))


@bp.post("/users/<int:uid>/unlock")
@require_auth("admin")  # super-admin or support staff (core.staff_access)
def user_unlock(uid: int):
    reason = _reason(_body())
    with get_db().write_transaction() as conn:
        if not still_authorized(conn):
            raise PermissionError_("مجوز مدیریت دیگر فعال نیست")
        out = auth_service.unlock(conn, user_id=uid, actor_user_id=current_user()["id"], reason=reason,
                                  ip_address=client_ip())
    return jsonify({"login_lockout": out})


@bp.post("/users/<int:uid>/mfa/reset")
@require_auth("admin")
def user_mfa_reset(uid: int):
    d = _body()
    reason = _reason(d)
    if d.get("confirm_scope") is not True:
        raise ValidationError("تأیید بازنشانی لازم است")
    with get_db().write_transaction() as conn:
        if not still_authorized(conn):
            raise PermissionError_("مجوز مدیریت دیگر فعال نیست")
        _user(conn, uid)
        mfa_service.reset(conn, user_id=uid, actor_user_id=current_user()["id"], reason=reason, ip_address=client_ip())
        return jsonify({"mfa": mfa_service.status(conn, uid)})
