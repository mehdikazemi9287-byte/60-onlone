"""Platform access administration: organization roles, operations mandates and supplier users.

Every change is made by a platform admin, carries a reason, and is written to the
append-only role_assignment_events table in the same transaction. Safe defaults:
nothing is granted implicitly, customers are never silently converted, the last
organization admin cannot be removed, and suppliers resolve only through active
supplier_users rows.
"""
from __future__ import annotations

import json

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError

MEMBER_ROLES = ("employee", "organization_admin", "procurement_agent", "organization_finance")
PROCUREMENT_ROLES = (None, "requester", "approver", "procurement_officer")
OPS_CAPABILITIES = ("case_manager", "case_agent")
SUPPLIER_USER_ROLES = ("owner", "operator")
# Internal operations mandates are for platform staff only, never customers or suppliers.
OPS_ELIGIBLE_PLATFORM_ROLES = ("employee", "admin")


def _j(v) -> str | None:
    return None if v is None else json.dumps(v, ensure_ascii=False, sort_keys=True)


def _reason(value) -> str:
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 1000:
        raise ValidationError("دلیل تغییر دسترسی الزامی است (۳ تا ۱۰۰۰ نویسه)")
    return value.strip()


def _audit(conn, *, scope, subject, action, before, after, reason, actor, org=None, supplier=None):
    conn.execute(
        """INSERT INTO role_assignment_events (scope, organization_id, supplier_id, subject_user_id, action,
               before_json, after_json, reason, actor_user_id) VALUES (?,?,?,?,?,?,?,?,?)""",
        (scope, org, supplier, subject, action, _j(before), _j(after), reason, actor))


def _user(conn, user_id):
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ValidationError("شناسه کاربر نامعتبر است")
    row = conn.execute("SELECT id, email, full_name, role, is_active FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise NotFoundError("کاربر یافت نشد")
    return row


def find_users(conn, q: str | None) -> list[dict]:
    like = f"%{(q or '').strip()}%"
    return [dict(r) for r in conn.execute(
        """SELECT id, email, full_name, role, is_active FROM users
           WHERE email LIKE ? OR full_name LIKE ? ORDER BY id LIMIT 25""", (like, like))]


# ── Organization membership roles ─────────────────────────────────────────────

def change_member(conn, *, org: int, membership_id: int, actor: int, data: dict) -> dict:
    reason = _reason(data.get("reason"))
    row = conn.execute("SELECT * FROM organization_memberships WHERE id=? AND organization_id=?",
                       (membership_id, org)).fetchone()
    if not row:
        raise NotFoundError("عضویت یافت نشد")
    before = {k: row[k] for k in ("role", "procurement_role", "status")}
    after = dict(before)
    if "role" in data:
        if data["role"] not in MEMBER_ROLES:
            raise ValidationError("نقش سازمانی نامعتبر است")
        after["role"] = data["role"]
    if "procurement_role" in data:
        if data["procurement_role"] not in PROCUREMENT_ROLES:
            raise ValidationError("نقش تدارکاتی نامعتبر است")
        after["procurement_role"] = data["procurement_role"]
    if "status" in data:
        if data["status"] not in ("active", "inactive"):
            raise ValidationError("وضعیت عضویت نامعتبر است")
        after["status"] = data["status"]
    if after == before:
        raise ConflictError("تغییری برای ثبت وجود ندارد")
    if before["role"] == "organization_admin" and before["status"] == "active" and \
            (after["role"] != "organization_admin" or after["status"] != "active"):
        admins = conn.execute("""SELECT COUNT(*) FROM organization_memberships WHERE organization_id=?
                                 AND role='organization_admin' AND status='active'""", (org,)).fetchone()[0]
        if admins <= 1:
            raise ConflictError("آخرین مدیر فعال سازمان را نمی‌توان حذف یا تنزل داد")
    conn.execute("""UPDATE organization_memberships SET role=?, procurement_role=?, status=?, updated_at=datetime('now')
                    WHERE id=?""", (after["role"], after["procurement_role"], after["status"], membership_id))
    _audit(conn, scope="organization_member", subject=row["user_id"], action="change", before=before, after=after,
           reason=reason, actor=actor, org=org)
    return after


# ── Operations mandates (case_manager / case_agent) ───────────────────────────

def grant_operations(conn, *, org: int, actor: int, data: dict) -> dict:
    reason = _reason(data.get("reason"))
    user = _user(conn, data.get("user_id"))
    cap = data.get("capability")
    if cap not in OPS_CAPABILITIES:
        raise ValidationError("مجوز عملیات نامعتبر است")
    if user["role"] not in OPS_ELIGIBLE_PLATFORM_ROLES or not user["is_active"]:
        raise ConflictError("مجوز عملیات فقط به کارکنان فعال پلتفرم (نقش employee یا admin) داده می‌شود")
    mandate = data.get("mandate_reference")
    if not isinstance(mandate, str) or not 1 <= len(mandate.strip()) <= 500:
        raise ValidationError("مرجع حکم/قرارداد مأموریت الزامی است")
    org_row = conn.execute("SELECT id FROM organizations WHERE id=? AND status='active'", (org,)).fetchone()
    if not org_row:
        raise NotFoundError("سازمان فعال یافت نشد")
    old = conn.execute("SELECT * FROM organization_operations_grants WHERE organization_id=? AND user_id=? AND capability=?",
                       (org, user["id"], cap)).fetchone()
    if old and old["status"] == "active":
        raise ConflictError("این مجوز از قبل فعال است")
    if old:
        conn.execute("""UPDATE organization_operations_grants SET status='active', mandate_reference=?
                        WHERE organization_id=? AND user_id=? AND capability=?""", (mandate.strip(), org, user["id"], cap))
    else:
        conn.execute("""INSERT INTO organization_operations_grants (organization_id, user_id, capability, status, mandate_reference)
                        VALUES (?,?,?,'active',?)""", (org, user["id"], cap, mandate.strip()))
    after = {"capability": cap, "status": "active", "mandate_reference": mandate.strip()}
    _audit(conn, scope="operations_grant", subject=user["id"], action="grant",
           before=dict(old) if old else None, after=after, reason=reason, actor=actor, org=org)
    return after


def revoke_operations(conn, *, org: int, actor: int, data: dict) -> dict:
    reason = _reason(data.get("reason"))
    user = _user(conn, data.get("user_id"))
    cap = data.get("capability")
    old = conn.execute("""SELECT * FROM organization_operations_grants WHERE organization_id=? AND user_id=?
                          AND capability=? AND status='active'""", (org, user["id"], cap)).fetchone()
    if not old:
        raise ConflictError("مجوز فعالی برای لغو وجود ندارد")
    conn.execute("""UPDATE organization_operations_grants SET status='revoked'
                    WHERE organization_id=? AND user_id=? AND capability=?""", (org, user["id"], cap))
    _audit(conn, scope="operations_grant", subject=user["id"], action="revoke", before=dict(old),
           after={"capability": cap, "status": "revoked"}, reason=reason, actor=actor, org=org)
    return {"capability": cap, "status": "revoked"}


# ── Supplier operational users ───────────────────────────────────────────────

def supplier_accounts(conn, user_id: int) -> list[dict]:
    # Active supplier_users rows, plus the legacy suppliers.user_id owner link unless explicitly revoked
    # (revocation also clears that link).
    return [dict(r) for r in conn.execute(
        """SELECT s.id, s.display_name, s.status, s.provenance, su.role FROM supplier_users su
           JOIN suppliers s ON s.id=su.supplier_id WHERE su.user_id=? AND su.status='active'
           UNION
           SELECT s.id, s.display_name, s.status, s.provenance, 'owner' FROM suppliers s
           WHERE s.user_id=? AND NOT EXISTS (SELECT 1 FROM supplier_users x WHERE x.supplier_id=s.id AND x.user_id=s.user_id)
           ORDER BY 5 DESC, 1""", (user_id, user_id))]


def acting_supplier_id(conn, user_id: int, requested=None) -> int | None:
    """The supplier this user acts for. With several accounts, `requested` (X-Supplier-Id) selects one."""
    accounts = supplier_accounts(conn, user_id)
    if not accounts:
        return None
    # A stale or foreign selection never widens access: it falls back to the user's own first account.
    try:
        requested = int(requested) if requested not in (None, "") else None
    except (TypeError, ValueError):
        requested = None
    ids = [a["id"] for a in accounts]
    return requested if requested in ids else ids[0]


def grant_supplier_user(conn, *, supplier_id: int, actor: int, data: dict) -> dict:
    reason = _reason(data.get("reason"))
    user = _user(conn, data.get("user_id"))
    role = data.get("role")
    if role not in SUPPLIER_USER_ROLES:
        raise ValidationError("نقش کاربر تأمین‌کننده نامعتبر است")
    sup = conn.execute("SELECT id, user_id FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if not sup:
        raise NotFoundError("تأمین‌کننده یافت نشد")
    if not user["is_active"]:
        raise ConflictError("کاربر غیرفعال است")
    converted = False
    if user["role"] != "supplier":
        if user["role"] != "customer" or data.get("convert_customer") is not True:
            raise ConflictError("فقط کاربر با نقش supplier قابل اتصال است؛ تبدیل مشتری باید صریحاً تأیید شود")
        if conn.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND status='active'", (user["id"],)).fetchone():
            raise ConflictError("این کاربر عضو فعال یک سازمان است و نمی‌تواند کاربر تأمین‌کننده شود")
        conn.execute("UPDATE users SET role='supplier' WHERE id=?", (user["id"],))
        converted = True
    old = conn.execute("SELECT * FROM supplier_users WHERE supplier_id=? AND user_id=?", (supplier_id, user["id"])).fetchone()
    if old and old["status"] == "active" and old["role"] == role:
        raise ConflictError("این دسترسی از قبل فعال است")
    if old:
        conn.execute("""UPDATE supplier_users SET role=?, status='active', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                        WHERE supplier_id=? AND user_id=?""", (role, supplier_id, user["id"]))
    else:
        conn.execute("INSERT INTO supplier_users (supplier_id, user_id, role, status) VALUES (?,?,?,'active')",
                     (supplier_id, user["id"], role))
    if role == "owner" and sup["user_id"] is None:
        conn.execute("UPDATE suppliers SET user_id=?, updated_at=datetime('now') WHERE id=?", (user["id"], supplier_id))
    after = {"role": role, "status": "active", "converted_from_customer": converted}
    _audit(conn, scope="supplier_user", subject=user["id"], action="grant" if not old else "change",
           before=dict(old) if old else None, after=after, reason=reason, actor=actor, supplier=supplier_id)
    return after


def revoke_supplier_user(conn, *, supplier_id: int, actor: int, data: dict) -> dict:
    reason = _reason(data.get("reason"))
    user = _user(conn, data.get("user_id"))
    old = conn.execute("SELECT * FROM supplier_users WHERE supplier_id=? AND user_id=? AND status='active'",
                       (supplier_id, user["id"])).fetchone()
    if not old:
        raise ConflictError("دسترسی فعالی برای لغو وجود ندارد")
    conn.execute("""UPDATE supplier_users SET status='revoked', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE supplier_id=? AND user_id=?""", (supplier_id, user["id"]))
    # The legacy primary link must not keep granting access.
    conn.execute("UPDATE suppliers SET user_id=NULL, updated_at=datetime('now') WHERE id=? AND user_id=?",
                 (supplier_id, user["id"]))
    _audit(conn, scope="supplier_user", subject=user["id"], action="revoke", before=dict(old),
           after={"status": "revoked"}, reason=reason, actor=actor, supplier=supplier_id)
    return {"status": "revoked"}


# ── Overview for the admin console ───────────────────────────────────────────

def overview(conn) -> dict:
    orgs = []
    for o in conn.execute("SELECT id, display_name, status, provenance FROM organizations ORDER BY id"):
        orgs.append({
            **dict(o),
            "members": [dict(r) for r in conn.execute(
                """SELECT m.id, m.user_id, u.full_name, u.email, m.role, m.procurement_role, m.status
                   FROM organization_memberships m JOIN users u ON u.id=m.user_id
                   WHERE m.organization_id=? ORDER BY m.role, u.full_name""", (o["id"],))],
            "operations": [dict(r) for r in conn.execute(
                """SELECT g.user_id, u.full_name, u.email, g.capability, g.status, g.mandate_reference
                   FROM organization_operations_grants g JOIN users u ON u.id=g.user_id
                   WHERE g.organization_id=? ORDER BY g.status, g.capability""", (o["id"],))],
        })
    suppliers = []
    for s in conn.execute("""SELECT id, display_name, status, onboarding_stage, provenance FROM suppliers
                             ORDER BY provenance='real' DESC, id"""):
        suppliers.append({**dict(s), "is_demo": s["provenance"] != "real", "users": [dict(r) for r in conn.execute(
            """SELECT su.user_id, u.full_name, u.email, su.role, su.status FROM supplier_users su
               JOIN users u ON u.id=su.user_id WHERE su.supplier_id=? ORDER BY su.status, su.role""", (s["id"],))]})
    events = [dict(r) for r in conn.execute(
        """SELECT e.*, a.full_name AS actor, s.full_name AS subject FROM role_assignment_events e
           JOIN users a ON a.id=e.actor_user_id JOIN users s ON s.id=e.subject_user_id ORDER BY e.id DESC LIMIT 100""")]
    for e in events:
        e["before"], e["after"] = json.loads(e.pop("before_json") or "null"), json.loads(e.pop("after_json") or "null")
    return {"organizations": orgs, "suppliers": suppliers, "events": events,
            "defaults": {"ops_eligible_platform_roles": list(OPS_ELIGIBLE_PLATFORM_ROLES)}}


def current_supplier_id(conn, user_id: int) -> int | None:
    """acting_supplier_id using the X-Supplier-Id request header when called inside a request."""
    requested = None
    try:
        from flask import has_request_context, request
        if has_request_context():
            requested = request.headers.get("X-Supplier-Id")
    except ImportError:  # pragma: no cover
        pass
    return acting_supplier_id(conn, user_id, requested)
