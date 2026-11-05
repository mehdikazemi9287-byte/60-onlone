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
    # request_number is globally UNIQUE, not scoped to an organization.
    # Called inside the serialized SQLite write transaction.
    candidate = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM purchase_requests").fetchone()[0]
    while conn.execute("SELECT 1 FROM purchase_requests WHERE request_number=?",
                       (f"PR-{today}-{candidate:04d}",)).fetchone():
        candidate += 1
    return f"PR-{today}-{candidate:04d}"


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


def _assert_org_accepts_intake(conn, organization_id: int) -> None:
    row = conn.execute("SELECT status FROM organizations WHERE id=?", (organization_id,)).fetchone()
    if not row or row["status"] != "active":
        raise PermissionError_("ثبت یا ارسال درخواست برای سازمان غیرفعال مجاز نیست")


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


def _can_read_org_requests(membership: dict) -> bool:
    return (_can_approve(membership) or _can_procure(membership)
            or membership["role"] == "organization_finance")


def _text(value, field: str, limit: int, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValidationError(f"{field} نامعتبر است")
    return value.strip()


def _money(value, field: str):
    if value is not None and (type(value) is not int or value < 0 or value > 9_000_000_000_000_000):
        raise ValidationError(f"{field} باید مبلغ صحیح غیرمنفی باشد")
    return value


def _date(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or datetime.date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError("تاریخ باید به صورت YYYY-MM-DD باشد")
    return value


def _destinations(value, items):
    if value is None:
        return []
    if not isinstance(value, list) or not 1 <= len(value) <= 20 or not items:
        raise ValidationError("مقصدها نامعتبر است")
    totals = [0] * len(items)
    result = []
    places = set()
    for destination in value:
        if not isinstance(destination, dict):
            raise ValidationError("مقصد نامعتبر است")
        clean = {key: _text(destination.get(key), key, limit, required=True)
                 for key, limit in (("province", 100), ("city", 100), ("address", 2000))}
        place = (clean["province"].strip(), clean["city"].strip(), " ".join(clean["address"].split()))
        if place in places:
            raise ValidationError("مقصد تکراری؛ مقدار را در همان مقصد اضافه کنید", details={"city": clean["city"]})
        places.add(place)
        clean["label"] = _text(destination.get("label"), "نام مقصد", 100)
        clean["needed_by_date"] = _date(destination.get("needed_by_date"))
        clean["recipient_name"] = _text(destination.get("recipient_name"), "گیرنده", 200)
        clean["recipient_phone"] = _text(destination.get("recipient_phone"), "تلفن گیرنده", 30)
        clean["delivery_window"] = _text(destination.get("delivery_window"), "بازه تحویل", 100)
        clean["notes"] = _text(destination.get("notes"), "توضیح مقصد", 1000)
        allocations = destination.get("allocations")
        if not isinstance(allocations, list) or not 1 <= len(allocations) <= len(items):
            raise ValidationError("تخصیص اقلام مقصد نامعتبر است")
        seen = set()
        clean["allocations"] = []
        for allocation in allocations:
            if not isinstance(allocation, dict):
                raise ValidationError("تخصیص نامعتبر است")
            index, qty = allocation.get("item_index"), allocation.get("quantity")
            if (type(index) is not int or not 0 <= index < len(items) or index in seen
                    or type(qty) is not int or not 1 <= qty <= 100000):
                raise ValidationError("ردیف یا تعداد تخصیص نامعتبر است")
            seen.add(index)
            totals[index] += qty
            clean["allocations"].append({"item_index": index, "quantity": qty})
        result.append(clean)
    # A destination share may stay unknown (e.g. 430 of 1000 packs not yet assigned) — never auto-filled.
    # Over-allocation is refused; completeness is enforced before a purchase order is issued.
    if any(t > (item.get("quantity") or 0) for t, item in zip(totals, items)):
        raise ValidationError("جمع تخصیص یک قلم از تعداد درخواست بیشتر است")
    return result


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
        "substitution_policy": row["substitution_policy"],
        "destinations": json.loads(row["destinations_json"]),
        "next_action": {"draft": "submit_request", "submitted": "wait_for_review",
                        "under_review": "wait_for_review"}.get(row["status"], "view_request"),
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
        "target_specification": row["target_specification"] if "target_specification" in row.keys() else None,
        "acceptable_alternative": row["acceptable_alternative"] if "acceptable_alternative" in row.keys() else None,
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
    from app.services import procurement_notify
    procurement_notify.on_audit(conn, organization_id=organization_id, actor_user_id=actor_user_id, event_type=event_type,
                                entity_type=entity_type, entity_id=entity_id, details=details)


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
    destinations: list[dict] | None = None,
    substitution_policy: str = "require_approval",
) -> dict:
    """Create a draft purchase request. Actor must be org member."""
    membership = _assert_org_member(conn, requester_user_id, organization_id)
    _assert_org_accepts_intake(conn, organization_id)
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
    budget_minor = _money(budget_minor, "بودجه")
    needed_by_date = _date(needed_by_date)
    description = _text(description, "شرح", 4000)
    notes = _text(notes, "یادداشت", 4000)
    delivery_province = _text(delivery_province, "استان", 100)
    delivery_city = _text(delivery_city, "شهر", 100)
    delivery_address = _text(delivery_address, "نشانی", 2000)
    cost_center = _text(cost_center, "مرکز هزینه", 100)
    project_code = _text(project_code, "کد پروژه", 100)
    if substitution_policy not in ("disallow", "require_approval"):
        raise ValidationError("سیاست جایگزینی نامعتبر است")
    destinations = _destinations(destinations, items)

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
    conn.execute(
        "UPDATE purchase_requests SET substitution_policy=?, destinations_json=? WHERE id=?",
        (substitution_policy, json.dumps(destinations, ensure_ascii=False), pr_id),
    )

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
    if any(key in item for key in ("attachments", "uploads", "files", "file")):
        raise ValidationError("بارگذاری امن فایل هنوز فعال نیست")
    qty = item.get("quantity", 0)
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1 or qty > 100000:
        raise ValidationError("تعداد باید عدد صحیح مثبت باشد")
    description = _text(item.get("free_text_description"), "شرح قلم", 2000)
    if not item.get("master_product_id") and not description:
        raise ValidationError("هر ردیف باید شناسه محصول یا توضیح متنی داشته باشد")
    mid = item.get("master_product_id")
    if mid is not None:
        if (
            isinstance(mid, bool)
            or not isinstance(mid, int)
            or not conn.execute("SELECT 1 FROM master_products WHERE id=?", (mid,)).fetchone()
        ):
            raise ValidationError("شناسه کالای مرجع نامعتبر است")
    from app.services import product_channel_policy as product_policy
    product_policy.require_master(conn,mid,"organization")
    if isinstance(item.get("unit"), str) and not item["unit"].strip():
        raise ValidationError("واحد خالی باید null باشد")
    unit = _text(item.get("unit"), "واحد", 50)
    notes = _text(item.get("notes"), "مشخصات قلم", 4000)
    estimate = _money(item.get("estimated_unit_price_minor"), "قیمت تخمینی")
    spec = _text(item.get("target_specification"), "مشخصات هدف", 2000)
    alternative = _text(item.get("acceptable_alternative"), "جایگزین قابل قبول", 2000)
    cur = conn.execute(
        """INSERT INTO purchase_request_items
           (purchase_request_id, master_product_id, free_text_description,
            quantity, unit, estimated_unit_price_minor, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (
            pr_id,
            item.get("master_product_id"),
            description,
            qty,
            unit,
            estimate,
            notes,
        ),
    )
    if spec or alternative:
        conn.execute(
            "UPDATE purchase_request_items SET target_specification=?, acceptable_alternative=? WHERE id=?",
            (spec, alternative, cur.lastrowid),
        )


def get_purchase_request(conn, pr_id: int, *, actor_user_id: int, organization_id: int) -> dict:
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    row = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
        (pr_id, organization_id),
    ).fetchone()
    if not row:
        raise NotFoundError("درخواست خرید یافت نشد")
    if row["requester_user_id"] != actor_user_id and not _can_read_org_requests(membership):
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
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    where = ["organization_id=?"]
    params: list = [organization_id]
    if not _can_read_org_requests(membership):
        where.append("requester_user_id=?")
        params.append(actor_user_id)
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
    from app.services import enterprise_procurement_service as ent
    ent.assert_submit_allowed(conn, organization_id, _assert_org_member(conn, actor_user_id, organization_id))
    _assert_org_accepts_intake(conn, organization_id)
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

    from app.services.product_channel_policy import require_references
    require_references(conn,"purchase_request_items","purchase_request_id",pr_id)
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
    # Phase-3 amount-band rules take precedence: a band that requires N approvals must never be
    # satisfied by this single-step endpoint. Delegate to the rule-based (multi-approver) flow.
    from app.services import org_order_service as _org
    ruled = conn.execute(
        "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?", (pr_id, organization_id)
    ).fetchone()
    if ruled is not None:
        rule = _org.matching_rule(conn, organization_id, _org.estimated_total(conn, ruled))
        if rule is not None and rule["decision"] == "require_approvals":
            _org.approve_with_rules(conn, organization_id=organization_id, pr_id=pr_id,
                                    actor_user_id=actor_user_id, action=action, reason=reason)
            return get_purchase_request(conn, pr_id, actor_user_id=actor_user_id, organization_id=organization_id)
    from app.services import enterprise_procurement_service as ent
    chain = ent.get_policy(conn, organization_id)["approval_chain"]
    if chain:
        chained = conn.execute(
            "SELECT * FROM purchase_requests WHERE id=? AND organization_id=?", (pr_id, organization_id)
        ).fetchone()
        if not chained:
            raise NotFoundError("درخواست خرید یافت نشد")
        ent.approve_with_chain(conn, chained, membership=membership, actor_user_id=actor_user_id,
                               organization_id=organization_id, action=action, reason=reason, chain=chain)
        return get_purchase_request(conn, pr_id, actor_user_id=actor_user_id, organization_id=organization_id)
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
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_orders'").fetchone():
        linked = conn.execute("SELECT 1 FROM customer_orders o JOIN organization_operations_cases ca ON ca.id=o.case_id WHERE ca.purchase_request_id=? LIMIT 1", (pr_id,)).fetchone()
        if linked:
            raise ConflictError("درخواست به سفارش مشتری متصل است؛ لغو باید از گردش سفارش انجام شود")
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


def unallocated(destinations: list, items: list) -> list[dict]:
    """Per item: requested quantity not yet assigned to any destination."""
    totals = [0] * len(items)
    for d in destinations or []:
        for a in d.get("allocations", []):
            if 0 <= a["item_index"] < len(totals):
                totals[a["item_index"]] += a["quantity"]
    return [{"item_index": i, "quantity": (it.get("quantity") or 0) - totals[i]} for i, it in enumerate(items)
            if destinations and (it.get("quantity") or 0) > totals[i]]


def destinations_hash(destinations_json: str | None) -> str:
    import hashlib
    return hashlib.sha256((destinations_json or "[]").encode()).hexdigest()[:16]


def allocation_summary(destinations: list, items: list) -> list[dict]:
    """Per item: total requested, allocated to destinations, and the explicit unallocated remainder."""
    allocated = [0] * len(items)
    for d in destinations or []:
        for a in d.get("allocations", []):
            if 0 <= a["item_index"] < len(items):
                allocated[a["item_index"]] += a["quantity"]
    return [{"item_index": i, "total": it.get("quantity") or 0, "allocated": allocated[i],
             "unallocated": (it.get("quantity") or 0) - allocated[i]} for i, it in enumerate(items)]


FREE_EDIT_STATUSES = ("draft",)


def _locked_by_po(conn, pr_id):
    return conn.execute("""SELECT 1 FROM purchase_orders o JOIN rfqs r ON r.id=o.rfq_id WHERE r.purchase_request_id=? AND o.status<>'cancelled'""",
                        (pr_id,)).fetchone()


def _completion_only(current: list, new: list) -> bool:
    """True when `new` only ADDS allocation: existing destinations unchanged except increased quantities; new ones appended."""
    if len(new) < len(current):
        return False
    for old, nxt in zip(current, new):
        if {k: v for k, v in old.items() if k != "allocations"} != {k: v for k, v in nxt.items() if k != "allocations"}:
            return False
        before = {a["item_index"]: a["quantity"] for a in old["allocations"]}
        after = {a["item_index"]: a["quantity"] for a in nxt["allocations"]}
        if any(after.get(i, 0) < q for i, q in before.items()):
            return False
    return True


def update_destinations(conn, *, organization_id: int, pr_id: int, actor_user_id: int, destinations, base_hash=None) -> dict:
    """Edit / increase / decrease / complete destination allocation with a version guard and audit.

    Draft: free edit. After submission: completion only (more allocation into the unknown share), because approvers
    already saw the allocation; reducing or moving it needs a new request. After a PO: frozen.
    """
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    pr = conn.execute("SELECT * FROM purchase_requests WHERE id=? AND organization_id=?", (pr_id, organization_id)).fetchone()
    if not pr:
        raise NotFoundError("درخواست خرید یافت نشد")
    if not (pr["requester_user_id"] == actor_user_id or _can_procure(membership) or membership["role"] == "organization_admin"):
        raise PermissionError_("ویرایش مقصدها برای درخواست‌دهنده، تدارکات یا مدیر سازمان است")
    if pr["status"] in ("completed", "cancelled", "rejected"):
        raise ConflictError("مقصد درخواست بسته‌شده قابل تغییر نیست")
    if _locked_by_po(conn, pr_id):
        raise ConflictError("پس از صدور سفارش خرید، مقصدها از طریق اصلاحیه تغییر می‌کنند", code="destinations_frozen")
    if base_hash is not None and base_hash != destinations_hash(pr["destinations_json"]):
        raise ConflictError("تخصیص مقصدها همزمان تغییر کرده است؛ صفحه را تازه کنید", code="stale_version")
    items = [dict(r) for r in conn.execute("SELECT quantity FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id", (pr_id,))]
    clean = _destinations(destinations, items)
    current = _destinations(json.loads(pr["destinations_json"]), items) if pr["destinations_json"] and json.loads(pr["destinations_json"]) else []
    if pr["status"] not in FREE_EDIT_STATUSES and not _completion_only(current, clean):
        raise ConflictError("پس از ارسال برای تأیید، فقط تکمیل تخصیص (افزایش یا مقصد جدید) مجاز است؛ کاهش یا جابه‌جایی نیازمند درخواست جدید است",
                            code="destinations_frozen")
    new_json = json.dumps(clean, ensure_ascii=False)
    changed = conn.execute("UPDATE purchase_requests SET destinations_json=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND destinations_json IS ?",
                           (new_json, pr_id, pr["destinations_json"]))
    if changed.rowcount != 1:
        raise ConflictError("تخصیص مقصدها همزمان تغییر کرده است؛ صفحه را تازه کنید", code="stale_version")
    from app.services.enterprise_procurement_service import record_event
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_id, actor_user_id=actor_user_id, event_type="destinations_updated",
                 payload={"before": allocation_summary(current, items), "after": allocation_summary(clean, items),
                          "destinations_before": len(current), "destinations_after": len(clean)})
    return {"destinations": clean, "allocation": allocation_summary(clean, items), "unallocated": unallocated(clean, items),
            "destinations_hash": destinations_hash(new_json)}


def split_by_destinations(conn, *, organization_id: int, pr_id: int, actor_user_id: int, destination_indexes, base_hash=None) -> dict:
    """Local sourcing: move chosen destinations (and exactly their allocated quantities) into a NEW draft request that
    runs its own approval/RFQ with local suppliers. Allowed before any RFQ exists; the original keeps the rest."""
    membership = _assert_org_member(conn, actor_user_id, organization_id)
    pr = conn.execute("SELECT * FROM purchase_requests WHERE id=? AND organization_id=?", (pr_id, organization_id)).fetchone()
    if not pr:
        raise NotFoundError("درخواست خرید یافت نشد")
    if not (_can_procure(membership) or membership["role"] == "organization_admin"):
        raise PermissionError_("تقسیم درخواست برای تدارکات یا مدیر سازمان است")
    if pr["status"] in ("completed", "cancelled", "rejected") or conn.execute("SELECT 1 FROM rfqs WHERE purchase_request_id=?", (pr_id,)).fetchone():
        raise ConflictError("تقسیم فقط پیش از ایجاد استعلام مجاز است", code="split_not_allowed")
    if base_hash is not None and base_hash != destinations_hash(pr["destinations_json"]):
        raise ConflictError("تخصیص مقصدها همزمان تغییر کرده است؛ صفحه را تازه کنید", code="stale_version")
    dests = json.loads(pr["destinations_json"] or "[]")
    if not isinstance(destination_indexes, list) or not destination_indexes or \
            any(type(i) is not int or not 0 <= i < len(dests) for i in destination_indexes) or len(set(destination_indexes)) != len(destination_indexes):
        raise ValidationError("مقصدهای انتخابی نامعتبر است")
    if len(destination_indexes) == len(dests):
        raise ValidationError("حداقل یک مقصد باید در درخواست اصلی بماند")
    rows = [dict(r) for r in conn.execute("SELECT * FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id", (pr_id,))]
    moving = [dests[i] for i in destination_indexes]
    staying = [d for i, d in enumerate(dests) if i not in destination_indexes]
    moved_qty = [0] * len(rows)
    for d in moving:
        for a in d["allocations"]:
            moved_qty[a["item_index"]] += a["quantity"]
    keep = [i for i, q in enumerate(moved_qty) if q > 0]
    new_index = {old: new for new, old in enumerate(keep)}
    child_items = []
    for i in keep:
        r = rows[i]
        child_items.append({k: r[k] for k in ("master_product_id", "free_text_description", "unit", "notes", "target_specification",
                                               "acceptable_alternative", "estimated_unit_price_minor") if k in r and r[k] is not None} | {"quantity": moved_qty[i]})
    child_dests = [d | {"allocations": [{"item_index": new_index[a["item_index"]], "quantity": a["quantity"]} for a in d["allocations"]]} for d in moving]
    child = create_purchase_request(conn, organization_id=organization_id, requester_user_id=pr["requester_user_id"] if pr["requester_user_id"] else actor_user_id,
                                    title=f"{pr['title']} — {'، '.join(d['city'] for d in moving)}"[:200], description=f"جداشده از {pr['request_number']} برای تأمین محلی",
                                    needed_by_date=pr["needed_by_date"], urgency=pr["urgency"], items=child_items, destinations=child_dests)
    # Remaining quantities; an item fully moved to the new request leaves the original and indexes are re-mapped.
    remap, k = {}, 0
    for i, r in enumerate(rows):
        left = r["quantity"] - moved_qty[i]
        if left <= 0:
            conn.execute("DELETE FROM purchase_request_items WHERE id=?", (r["id"],))
            continue
        if moved_qty[i]:
            conn.execute("UPDATE purchase_request_items SET quantity=? WHERE id=?", (left, r["id"]))
        remap[i] = k
        k += 1
    if not remap:
        raise ValidationError("پس از تقسیم، درخواست اصلی قلمی ندارد")
    staying = [d | {"allocations": [{"item_index": remap[a["item_index"]], "quantity": a["quantity"]} for a in d["allocations"] if a["item_index"] in remap]}
               for d in staying]
    conn.execute("UPDATE purchase_requests SET destinations_json=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                 (json.dumps(staying, ensure_ascii=False), pr_id))
    from app.services.enterprise_procurement_service import record_event
    child_id = child["id"] if isinstance(child, dict) else child
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_id, actor_user_id=actor_user_id, event_type="request_split",
                 payload={"child_request_id": child_id, "moved_destinations": [d["city"] for d in moving], "moved_quantity": moved_qty})
    return {"child_request_id": child_id}

