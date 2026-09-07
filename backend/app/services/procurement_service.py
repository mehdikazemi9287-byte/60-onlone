"""Organizational Procurement Service.

Manages Purchase Requests and their approval lifecycle.

State machine:
  draft → submitted → under_review → approved → sourcing → quoted → awarded → completed
                                   └→ rejected
  Any state → cancelled (with restrictions)

Roles:
  - requester / employee: can create, edit draft, submit, cancel own draft
  - approver / organization_admin: can approve or reject submitted PRs
  - procurement_officer / procurement_agent: can move to sourcing, manage RFQs
  - organization_admin: has all permissions within their org

Tenant isolation: every operation asserts organization_id matches the actor's membership.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from app.core.errors import ConflictError, PermissionError_, NotFoundError, ValidationError


# ── Number generation ──────────────────────────────────────────────────────────


def _next_pr_number(conn, organization_id: int) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    count = conn.execute(
        "SELECT COUNT(*) FROM purchase_requests WHERE organization_id=?",
        (organization_id,),
    ).fetchone()[0]
    return f"PR-{today}-{count + 1:04d}"


def _next_rfq_number(conn, organization_id: int) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    count = conn.execute(
        "SELECT COUNT(*) FROM rfqs WHERE organization_id=?",
        (organization_id,),
    ).fetchone()[0]
    return f"RFQ-{today}-{count + 1:04d}"


def _next_po_number(conn, organization_id: int) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    count = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE organization_id=?",
        (organization_id,),
    ).fetchone()[0]
    return f"PO-{today}-{count + 1:04d}"


# ── Membership helpers ─────────────────────────────────────────────────────────


def _get_membership(conn, user_id: int, organization_id: int) -> dict:
    row = conn.execute(
        """SELECT id, role, procurement_role, status
           FROM organization_memberships
           WHERE user_id=? AND organization_id=? AND status='active'""",
        (user_id, organization_id),
    ).fetchone()
    if not row:
        raise PermissionError_("عضویت فعال در این سازمان ندارید")
    return dict(row)


def _assert_org_member(conn, user_id: int, organization_id: int) -> dict:
    return _get_membership(conn, user_id, organization_id)


def _can_approve(membership: dict) -> bool:
    return (
        membership["role"] in ("organization_admin",)
        or membership["procurement_role"] == "approver"
    )


def _can_procure(membership: dict) -> bool:
    return (
        membership["role"] in ("organization_admin", "procurement_agent")
        or membership["procurement_role"] == "procurement_officer"
    )


# ── Serialisation ──────────────────────────────────────────────────────────────


def _pr_dict(row) -> dict:
    return {
        "id": row["id"],
        "organization_id": row["organization_id"],
        "requester_user_id": row["requester_user_id"],
        "request_number": row["request_number"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "needed_by_date": row["needed_by_date"],
        "delivery_province": row["delivery_province"],
        "delivery_city": row["delivery_city"],
        "delivery_address": row["delivery_address"],
        "budget_minor": row["budget_minor"],
        "cost_center": row["cost_center"],
        "project_code": row["project_code"],
        "urgency": row["urgency"],
        "notes": row["notes"],
        "submitted_at": row["submitted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _pri_dict(row) -> dict:
    return {
        "id": row["id"],
        "purchase_request_id": row["purchase_request_id"],
        "master_product_id": row["master_product_id"],
        "free_text_description": row["free_text_description"],
        "quantity": row["quantity"],
        "unit": row["unit"],
        "estimated_unit_price_minor": row["estimated_unit_price_minor"],
        "notes": row["notes"],
    }


# ── Audit log ──────────────────────────────────────────────────────────────────


def _audit(
    conn,
    *,
    organization_id: int,
    actor_user_id: int,
    event_type: str,
    entity_type: str,
    entity_id: int,
    details: dict | None = None,
) -> None:
    conn.execute(
        """INSERT INTO procurement_audit_log
           (organization_id, actor_user_id, event_type, entity_type, entity_id, details_json)
           VALUES (?,?,?,?,?,?)""",
        (
            organization_id,
            actor_user_id,
            event_type,
            entity_type,
            entity_id,
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )


# ── Purchase Request CRUD ──────────────────────────────────────────────────────


def create_purchase_request(
    conn,
    *,
    organization_id: int,
    requester_user_id: int,
    title: str,
    description: str | None = None,
    needed_by_date: str | None = None,
    delivery_province: str | None = None,
    delivery_city: str | None = None,
    delivery_address: str | None = None,
    budget_minor: int | None = None,
    cost_center: str | None = None,
    project_code: str | None = None,
    urgency: str = "normal",
    notes: str | None = None,
    items: list[dict] | None = None,
) -> dict:
    """Create a draft purchase request. Actor must be org member."""
    membership = _assert_org_member(conn, requester_user_id, organization_id)
    if not isinstance(title, str) or len(title) > 200:
        raise ValidationError("عنوان درخواست خرید نامعتبر است")
    if items is not None and (
        not isinstance(items, list)
        or len(items) > 50
        or any(not isinstance(i, dict) for i in items)
    ):
        raise ValidationError("اقلام درخواست نامعتبر است")
    title = title.strip()
    if not title:
        raise ValidationError("عنوان درخواست خرید الزامی است")
    if urgency not in ("low", "normal", "high", "urgent"):
        raise ValidationError("فوریت نامعتبر است")
    if budget_minor is not None and budget_minor < 0:
        raise ValidationError("بودجه نمی‌تواند منفی باشد")

    req_number = _next_pr_number(conn, organization_id)
    cur = conn.execute(
        """INSERT INTO purchase_requests
           (organization_id, requester_user_id, requester_membership_id,
            request_number, title, description, needed_by_date,
            delivery_province, delivery_city, delivery_address,
            budget_minor, cost_center, project_code, urgency, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            organization_id,
            requester_user_id,
            membership["id"],
            req_number,
            title,
            description,
            needed_by_date,
            delivery_province,
            delivery_city,
            delivery_address,
            budget_minor,
            cost_center,
            project_code,
            urgency,
            notes,
        ),
    )
    pr_id = cur.lastrowid

    for item in items or []:
        _add_pr_item(conn, pr_id, item)

    _audit(
        conn,
        organization_id=organization_id,
        actor_user_id=requester_user_id,
        event_type="pr_created",
        entity_type="purchase_request",
        entity_id=pr_id,
        details={"request_number": req_number, "title": title},
    )

    return get_purchase_request(
        conn, pr_id, actor_user_id=requester_user_id, organization_id=organization_id
    )


def _add_pr_item(conn, pr_id: int, item: dict) -> None:
    qty = item.get("quantity", 0)
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1 or qty > 100000:
        raise ValidationError("تعداد باید عدد صحیح مثبت باشد")
    if not item.get("master_product_id") and not item.get("free_text_description"):
        raise ValidationError("هر ردیف باید شناسه محصول یا توضیح متنی داشته باشد")
    mid = item.get("master_product_id")
    if mid is not None:
        if (
            isinstance(mid, bool)
            or not isinstance(mid, int)
            or not conn.execute("SELECT 1 FROM master_products WHERE id=?", (mid,)).fetchone()
        ):
            raise ValidationError("شناسه کالای مرجع نامعتبر است")
    description = item.get("free_text_description")
    if description is not None and (not isinstance(description, str) or len(description) > 2000):
        raise ValidationError("شرح قلم نامعتبر است")
    conn.execute(
        """INSERT INTO purchase_request_items
           (purchase_request_id, master_product_id, free_text_description,
            quantity, unit, estimated_unit_price_minor, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (
            pr_id,
            item.get("master_product_id"),
            item.get("free_text_description"),
            qty,
            item.get("unit"),
            item.get("estimated_unit_price_minor"),
            item.get("notes"),
        ),
    )


def get_purchase_request(conn, pr_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
        (pr_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("درخواست خرید یافت نشد")
    pr = _pr_dict(row)
    items = conn.execute(
        "SELECT * FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id",
        (pr_id,),
    ).fetchall()
    pr["items"] = [_pri_dict(i) for i in items]
    return pr


def list_purchase_requests(
    conn,
    *,
    organization_id: int,
    actor_user_id: int,
    status: str | None = None,
    requester_user_id: int | None = None,
) -> list[dict]:
    _assert_org_member(conn, actor_user_id, organization_id)
    where = ["organization_id=?"]
    params: list = [organization_id]
    if status:
        where.append("status=?")
        params.append(status)
    if requester_user_id:
        where.append("requester_user_id=?")
        params.append(requester_user_id)
    rows = conn.execute(
        f"SELECT * FROM purchase_requests WHERE {' AND '.join(where)} ORDER BY id DESC",
        params,
    ).fetchall()
    return [_pr_dict(r) for r in rows]


def submit_purchase_request(conn, pr_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
        (pr_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("درخواست خرید یافت نشد")
    if row["status"] != "draft":
        raise ConflictError(f"درخواست در وضعیت '{row['status']}' قابل ارسال نیست")
    if row["requester_user_id"] != actor_user_id:
        # Allow org admin to submit on behalf
        m = _get_membership(conn, actor_user_id, organization_id)
        if m["role"] != "organization_admin":
            raise PermissionError_("فقط درخواست‌دهنده یا مدیر سازمان می‌تواند درخواست را ارسال کند")

    # Must have at least one item
    count = conn.execute(
        "SELECT COUNT(*) FROM purchase_request_items WHERE purchase_request_id=?", (pr_id,)
    ).fetchone()[0]
    if count == 0:
        raise ValidationError("درخواست خرید باید حداقل یک ردیف داشته باشد")

    now = _now()
    conn.execute(
        "UPDATE purchase_requests SET status='submitted', submitted_at=?, updated_at=? WHERE id=?",
        (now, now, pr_id),
    )
    _audit(
        conn,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="pr_submitted",
        entity_type="purchase_request",
        entity_id=pr_id,
    )
    return get_purchase_request(
        conn, pr_id, actor_user_id=actor_user_id, organization_id=organization_id
    )


def approve_purchase_request(
    conn,
    pr_id: int,
    *,
    actor_user_id: int,
    organization_id: int,
    action: str,  # 'approve' | 'reject'
    reason: str | None = None,
) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    if not _can_approve(membership):
        raise PermissionError_("دسترسی تأیید درخواست خرید ندارید")

    row = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
        (pr_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("درخواست خرید یافت نشد")
    if row["status"] not in ("submitted", "under_review"):
        raise ConflictError(f"درخواست در وضعیت '{row['status']}' قابل بررسی نیست")
    if action not in ("approve", "reject"):
        raise ValidationError("اقدام باید 'approve' یا 'reject' باشد")

    new_status = "approved" if action == "approve" else "rejected"
    now = _now()
    conn.execute(
        "UPDATE purchase_requests SET status=?, updated_at=? WHERE id=?",
        (new_status, now, pr_id),
    )
    conn.execute(
        """INSERT INTO procurement_approvals
           (purchase_request_id, approver_user_id, approver_membership_id, action, reason)
           VALUES (?,?,?,?,?)""",
        (pr_id, actor_user_id, membership["id"], action, reason),
    )
    event = "pr_approved" if action == "approve" else "pr_rejected"
    _audit(
        conn,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=event,
        entity_type="purchase_request",
        entity_id=pr_id,
        details={"reason": reason},
    )
    return get_purchase_request(
        conn, pr_id, actor_user_id=actor_user_id, organization_id=organization_id
    )


def cancel_purchase_request(conn, pr_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
        (pr_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("درخواست خرید یافت نشد")
    if row["status"] in ("awarded", "completed", "cancelled"):
        raise ConflictError(f"درخواست در وضعیت '{row['status']}' قابل لغو نیست")
    # Only requester or admin can cancel
    if row["requester_user_id"] != actor_user_id and membership["role"] != "organization_admin":
        raise PermissionError_("فقط درخواست‌دهنده یا مدیر سازمان می‌تواند لغو کند")
    now = _now()
    conn.execute(
        "UPDATE purchase_requests SET status='cancelled', updated_at=? WHERE id=?",
        (now, pr_id),
    )
    _audit(
        conn,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="pr_cancelled",
        entity_type="purchase_request",
        entity_id=pr_id,
    )
    return get_purchase_request(
        conn, pr_id, actor_user_id=actor_user_id, organization_id=organization_id
    )


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
