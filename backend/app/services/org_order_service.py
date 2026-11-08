"""Phase 3 — organization orders (سفارش سازمانی) and Amazon-Business-style buying controls.

An approved purchase request — with buyer-chosen seller offers, or with an awarded supplier quote —
becomes a real `orders` row in ONE write transaction:

    order + order_items + multi-destination allocations
    + supplier stock reserved on every seller offer        (fulfillment_service.reserve_supplier_stock_for_plan)
    + organization credit reserved and captured            (credit_service.reserve → capture)
    + fulfillment orders per seller once fully funded      (fulfillment_service.confirm_fulfillment_orders_from_plan)

Any failure (insufficient credit, stock changed, offer not eligible, guided-buying violation) raises before
commit, so nothing is written. Replaying the same Idempotency-Key returns the same order; reusing the key
with a different body is refused.

Invariants kept identical to checkout_service (which is NOT modified):
    total_minor = subtotal_minor + shipping_fee_minor + tax_minor = credit_minor + cash_minor
    order_items.line_total_minor = unit_price_minor * quantity
    the sales ledger transaction is posted once, when the order is fully paid, and balances.

Payment methods (org_buying_policies / request body):
    credit      — the whole total from the requester's organization credit allocation; order is paid at once.
    prepayment  — prepayment_bps of the total is due in cash (پیش‌پرداخت), the rest is captured from credit;
                  stock is reserved now, fulfillment orders are released when the cash is confirmed.
    cash        — whole total due in cash; same release-on-confirmation rule.

Money is integer minor units (Rial) throughout.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import audit_service, credit_rules, credit_service, fulfillment_service, ledger_service
from app.services import procurement_service as pr_svc

PAYMENT_METHODS = ("credit", "prepayment", "cash")
GUIDED_MODES = ("off", "warn", "enforce")
CONVERTIBLE_PR_STATUSES = ("approved", "sourcing", "quoted", "awarded")
APPROVER_ROLES = ("organization_admin", "organization_finance", "approver")
MAX_MINOR = 9_000_000_000_000_000


# ── small helpers ──────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _sql_now() -> str:
    """Same shape as SQLite datetime('now'), used by payment_intents/orders columns."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _hash(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _int(value, field: str, *, minimum: int = 0, maximum: int = MAX_MINOR, required: bool = True):
    if value is None and not required:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{field} باید عدد صحیح معتبر باشد", details={field: "عدد صحیح لازم است"})
    return value


def _idempotency_key(key) -> str:
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValidationError("سرآیند Idempotency-Key الزامی است", code="idempotency_key_required")
    return key.strip()


def _membership(conn, user_id: int, organization_id: int) -> dict:
    return pr_svc._assert_org_member(conn, user_id, organization_id)


def _is_admin(m: dict) -> bool:
    return m["role"] == "organization_admin"


def _is_finance(m: dict) -> bool:
    return m["role"] in ("organization_admin", "organization_finance")


def _require_admin(conn, user_id: int, organization_id: int) -> dict:
    m = _membership(conn, user_id, organization_id)
    if not _is_admin(m):
        raise PermissionError_("فقط مدیر سازمان می‌تواند این تنظیمات را تغییر دهد")
    return m


def _require_reader(conn, user_id: int, organization_id: int) -> dict:
    m = _membership(conn, user_id, organization_id)
    if not (pr_svc._can_read_org_requests(m) or _is_finance(m)):
        raise PermissionError_("دسترسی مشاهدهٔ سفارش‌های سازمان را ندارید")
    return m


def _new_order_number(conn) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"ORD-{stamp}-{secrets.token_hex(3).upper()}"
        if conn.execute("SELECT 1 FROM orders WHERE order_number = ?", (candidate,)).fetchone() is None:
            return candidate
    raise ConflictError("شمارهٔ سفارش قابل تخصیص نبود؛ دوباره تلاش کنید")


def _tax(conn, subtotal_minor: int, organization_id: int | None) -> tuple[int, int]:
    """(tax_minor, rate_bps) on the merchandise subtotal — same rule as quote_service (shipping exempt)."""
    from app.services.tax_service import calculate_line_tax_with_conn
    if subtotal_minor <= 0:
        return 0, 0
    try:
        result = calculate_line_tax_with_conn(
            conn, subtotal_minor=subtotal_minor, tax_category_code="STANDARD",
            effective_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), organization_id=organization_id)
    except NotFoundError:
        return 0, 0
    return int(result["tax_minor"]), int(result["rate_bps"])


def _clean_address(address) -> dict:
    if not isinstance(address, dict):
        raise ValidationError("آدرس ارسال نامعتبر است")
    out, errors = {}, {}
    for key, limit in (("recipient_name", 200), ("recipient_phone", 30), ("province", 100),
                       ("city", 100), ("line1", 2000)):
        value = address.get(key)
        value = value.strip() if isinstance(value, str) else ""
        if not value or len(value) > limit:
            errors[key] = "این فیلد الزامی است"
        out[key] = value
    if not errors and len(out["recipient_phone"]) < 8:
        errors["recipient_phone"] = "شماره تماس معتبر نیست"
    if errors:
        raise ValidationError("آدرس ارسال ناقص است", details=errors)
    postal = address.get("postal_code")
    out["postal_code"] = postal.strip() if isinstance(postal, str) and postal.strip() else None
    return out


# ── buying policy (payment method, prepayment, guided-buying mode) ─────────────


def get_buying_policy(conn, organization_id: int) -> dict:
    row = conn.execute("SELECT * FROM org_buying_policies WHERE organization_id=?", (organization_id,)).fetchone()
    if row is None:
        return {"organization_id": organization_id, "payment_method": "credit", "prepayment_bps": 0,
                "guided_buying": "off", "updated_at": None}
    return {"organization_id": organization_id, "payment_method": row["payment_method"],
            "prepayment_bps": row["prepayment_bps"], "guided_buying": row["guided_buying"],
            "updated_at": row["updated_at"]}


def read_buying_policy(conn, *, organization_id: int, actor_user_id: int) -> dict:
    _membership(conn, actor_user_id, organization_id)
    return get_buying_policy(conn, organization_id)


def update_buying_policy(conn, *, organization_id: int, actor_user_id: int, data: dict) -> dict:
    _require_admin(conn, actor_user_id, organization_id)
    current = get_buying_policy(conn, organization_id)
    unknown = set(data) - {"payment_method", "prepayment_bps", "guided_buying"}
    if unknown:
        raise ValidationError("فیلد ناشناخته در سیاست خرید", details={"fields": sorted(unknown)})
    method = data.get("payment_method", current["payment_method"])
    if method not in PAYMENT_METHODS:
        raise ValidationError("روش پرداخت باید credit، prepayment یا cash باشد")
    bps = _int(data.get("prepayment_bps", current["prepayment_bps"]), "prepayment_bps", maximum=10000)
    if method == "prepayment" and not 1 <= bps <= 9999:
        raise ValidationError("درصد پیش‌پرداخت باید بین ۰٫۰۱ تا ۹۹٫۹۹ درصد باشد (۱ تا ۹۹۹۹ bps)")
    mode = data.get("guided_buying", current["guided_buying"])
    if mode not in GUIDED_MODES:
        raise ValidationError("حالت خرید هدایت‌شده باید off، warn یا enforce باشد")
    now = _now()
    if conn.execute("SELECT 1 FROM org_buying_policies WHERE organization_id=?", (organization_id,)).fetchone():
        conn.execute("""UPDATE org_buying_policies SET payment_method=?, prepayment_bps=?, guided_buying=?,
                        updated_by_user_id=?, updated_at=? WHERE organization_id=?""",
                     (method, bps, mode, actor_user_id, now, organization_id))
    else:
        conn.execute("""INSERT INTO org_buying_policies
                        (organization_id, payment_method, prepayment_bps, guided_buying, updated_by_user_id, updated_at)
                        VALUES (?,?,?,?,?,?)""", (organization_id, method, bps, mode, actor_user_id, now))
    audit_service.record(conn, action="org.buying_policy_updated", entity_type="organization",
                         entity_id=organization_id, actor_user_id=actor_user_id,
                         metadata={"payment_method": method, "prepayment_bps": bps, "guided_buying": mode})
    return get_buying_policy(conn, organization_id)


def _finance_policy_methods(conn, organization_id: int) -> list[str] | None:
    """Methods of the approved finance policy, or None when no policy is approved (pre-policy behaviour)."""
    from app.services.organization_finance_policy import _effective
    try:
        policy = _effective(conn, organization_id)
    except Exception:  # pragma: no cover - a missing optional module must not block ordering
        return None
    return list(policy["methods"]) if policy else None


def _resolve_payment(conn, organization_id: int, requested) -> tuple[str, int]:
    policy = get_buying_policy(conn, organization_id)
    method = requested if requested is not None else policy["payment_method"]
    if method not in PAYMENT_METHODS:
        raise ValidationError("روش پرداخت باید credit، prepayment یا cash باشد")
    bps = 0
    if method == "prepayment":
        bps = int(policy["prepayment_bps"])
        if not 1 <= bps <= 9999:
            raise ConflictError("درصد پیش‌پرداخت در سیاست خرید سازمان تعریف نشده است",
                                code="prepayment_not_configured")
    allowed = _finance_policy_methods(conn, organization_id)
    if allowed is not None:
        needs = {"credit": {"credit"}, "cash": {"cash"}, "prepayment": {"cash", "credit"}}[method]
        if not needs <= set(allowed):
            raise ConflictError("روش پرداخت انتخاب‌شده در سیاست مالی مصوب سازمان مجاز نیست",
                                code="payment_method_not_allowed", details={"allowed": allowed, "method": method})
    return method, bps


# ── guided buying: preferred sellers / categories ──────────────────────────────


def _pref_dict(row) -> dict:
    return {"id": row["id"], "organization_id": row["organization_id"], "supplier_id": row["supplier_id"],
            "category_id": row["category_id"], "note": row["note"], "created_at": row["created_at"]}


def list_preferred(conn, *, organization_id: int, actor_user_id: int) -> dict:
    _membership(conn, actor_user_id, organization_id)
    rows = conn.execute("SELECT * FROM org_preferred_sellers WHERE organization_id=? ORDER BY id",
                        (organization_id,)).fetchall()
    return {"mode": get_buying_policy(conn, organization_id)["guided_buying"], "items": [_pref_dict(r) for r in rows]}


def add_preferred(conn, *, organization_id: int, actor_user_id: int, data: dict) -> dict:
    _require_admin(conn, actor_user_id, organization_id)
    supplier_id = _int(data.get("supplier_id"), "supplier_id", minimum=1, required=False)
    category_id = _int(data.get("category_id"), "category_id", minimum=1, required=False)
    if supplier_id is None and category_id is None:
        raise ValidationError("فروشنده یا دستهٔ ترجیحی را مشخص کنید")
    if supplier_id is not None and not conn.execute("SELECT 1 FROM suppliers WHERE id=?", (supplier_id,)).fetchone():
        raise NotFoundError("فروشنده یافت نشد")
    if category_id is not None and not conn.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
        raise NotFoundError("دسته یافت نشد")
    dup = conn.execute(
        "SELECT 1 FROM org_preferred_sellers WHERE organization_id=? AND COALESCE(supplier_id,0)=? "
        "AND COALESCE(category_id,0)=?", (organization_id, supplier_id or 0, category_id or 0)).fetchone()
    if dup:
        raise ConflictError("این مورد قبلاً در فهرست ترجیحی ثبت شده است")
    note = pr_svc._text(data.get("note"), "توضیح", 500)
    cur = conn.execute("""INSERT INTO org_preferred_sellers (organization_id, supplier_id, category_id, note,
                          created_by_user_id, created_at) VALUES (?,?,?,?,?,?)""",
                       (organization_id, supplier_id, category_id, note, actor_user_id, _now()))
    row = conn.execute("SELECT * FROM org_preferred_sellers WHERE id=?", (cur.lastrowid,)).fetchone()
    return _pref_dict(row)


def remove_preferred(conn, *, organization_id: int, actor_user_id: int, preferred_id: int) -> None:
    _require_admin(conn, actor_user_id, organization_id)
    cur = conn.execute("DELETE FROM org_preferred_sellers WHERE id=? AND organization_id=?",
                       (preferred_id, organization_id))
    if cur.rowcount != 1:
        raise NotFoundError("مورد ترجیحی یافت نشد")


def guided_check(conn, organization_id: int, *, supplier_id: int, category_id: int | None) -> dict:
    """{'mode', 'preferred': bool}. With an empty list or mode 'off' everything is preferred."""
    mode = get_buying_policy(conn, organization_id)["guided_buying"]
    rows = conn.execute("SELECT supplier_id, category_id FROM org_preferred_sellers WHERE organization_id=?",
                        (organization_id,)).fetchall()
    if mode == "off" or not rows:
        return {"mode": mode, "preferred": True}
    for r in rows:
        sup_ok = r["supplier_id"] is None or r["supplier_id"] == supplier_id
        cat_ok = r["category_id"] is None or r["category_id"] == category_id
        if sup_ok and cat_ok:
            return {"mode": mode, "preferred": True}
    return {"mode": mode, "preferred": False}


def check_offer(conn, *, organization_id: int, actor_user_id: int, offer_id: int) -> dict:
    _membership(conn, actor_user_id, organization_id)
    row = conn.execute("""SELECT o.id, o.supplier_id, p.category_id FROM seller_offers o
                          JOIN products p ON p.id=o.product_id WHERE o.id=?""", (offer_id,)).fetchone()
    if row is None:
        raise NotFoundError("پیشنهاد فروش یافت نشد")
    result = guided_check(conn, organization_id, supplier_id=row["supplier_id"], category_id=row["category_id"])
    result["offer_id"] = offer_id
    result["allowed"] = result["preferred"] or result["mode"] != "enforce"
    return result


# ── approval rules (auto-approve under threshold, multi-level above) ───────────


def _rule_dict(row) -> dict:
    return {"id": row["id"], "organization_id": row["organization_id"], "name": row["name"],
            "min_total_minor": row["min_total_minor"], "max_total_minor": row["max_total_minor"],
            "decision": row["decision"], "required_approvals": row["required_approvals"],
            "approver_role": row["approver_role"], "is_active": bool(row["is_active"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_rules(conn, *, organization_id: int, actor_user_id: int) -> list[dict]:
    _membership(conn, actor_user_id, organization_id)
    rows = conn.execute("SELECT * FROM org_approval_rules WHERE organization_id=? ORDER BY min_total_minor, id",
                        (organization_id,)).fetchall()
    return [_rule_dict(r) for r in rows]


def create_rule(conn, *, organization_id: int, actor_user_id: int, data: dict) -> dict:
    _require_admin(conn, actor_user_id, organization_id)
    name = pr_svc._text(data.get("name"), "نام قاعده", 120, required=True)
    lo = _int(data.get("min_total_minor", 0), "min_total_minor")
    hi = _int(data.get("max_total_minor"), "max_total_minor", required=False)
    if hi is not None and hi <= lo:
        raise ValidationError("سقف بازه باید از کف آن بیشتر باشد")
    decision = data.get("decision")
    if decision not in ("auto_approve", "require_approvals"):
        raise ValidationError("نوع تصمیم باید auto_approve یا require_approvals باشد")
    required = _int(data.get("required_approvals", 1), "required_approvals", minimum=1, maximum=5)
    role = data.get("approver_role")
    if role is not None and role not in APPROVER_ROLES:
        raise ValidationError("نقش تأییدکننده نامعتبر است")
    # Active bands must not overlap: one request total → exactly one rule.
    for r in conn.execute("SELECT * FROM org_approval_rules WHERE organization_id=? AND is_active=1",
                          (organization_id,)).fetchall():
        r_hi = r["max_total_minor"]
        if lo < (r_hi if r_hi is not None else MAX_MINOR + 1) and r["min_total_minor"] < (hi if hi is not None else MAX_MINOR + 1):
            raise ConflictError(f"بازهٔ مبلغ با قاعدهٔ «{r['name']}» هم‌پوشانی دارد", code="approval_rule_overlap")
    now = _now()
    cur = conn.execute("""INSERT INTO org_approval_rules (organization_id, name, min_total_minor, max_total_minor,
                          decision, required_approvals, approver_role, is_active, created_by_user_id, created_at, updated_at)
                          VALUES (?,?,?,?,?,?,?,1,?,?,?)""",
                       (organization_id, name, lo, hi, decision, required, role, actor_user_id, now, now))
    audit_service.record(conn, action="org.approval_rule_created", entity_type="org_approval_rule",
                         entity_id=int(cur.lastrowid), actor_user_id=actor_user_id,
                         metadata={"organization_id": organization_id, "decision": decision})
    return _rule_dict(conn.execute("SELECT * FROM org_approval_rules WHERE id=?", (cur.lastrowid,)).fetchone())


def deactivate_rule(conn, *, organization_id: int, actor_user_id: int, rule_id: int) -> dict:
    _require_admin(conn, actor_user_id, organization_id)
    cur = conn.execute("UPDATE org_approval_rules SET is_active=0, updated_at=? WHERE id=? AND organization_id=?",
                       (_now(), rule_id, organization_id))
    if cur.rowcount != 1:
        raise NotFoundError("قاعدهٔ تأیید یافت نشد")
    return _rule_dict(conn.execute("SELECT * FROM org_approval_rules WHERE id=?", (rule_id,)).fetchone())


def estimated_total(conn, pr_row) -> int | None:
    """Σ quantity × estimated unit price; budget_minor when any line lacks an estimate; None if unknown."""
    rows = conn.execute("SELECT quantity, estimated_unit_price_minor FROM purchase_request_items "
                        "WHERE purchase_request_id=?", (pr_row["id"],)).fetchall()
    if rows and all(r["estimated_unit_price_minor"] is not None for r in rows):
        return sum(int(r["quantity"]) * int(r["estimated_unit_price_minor"]) for r in rows)
    return int(pr_row["budget_minor"]) if pr_row["budget_minor"] is not None else None


def matching_rule(conn, organization_id: int, total: int | None):
    rules = conn.execute("SELECT * FROM org_approval_rules WHERE organization_id=? AND is_active=1 "
                         "ORDER BY min_total_minor DESC, id", (organization_id,)).fetchall()
    if not rules:
        return None
    if total is None:
        # Unknown amount never auto-approves: use the open-ended (highest) band if it needs approvals.
        top = next((r for r in rules if r["max_total_minor"] is None), None)
        return top if top is not None and top["decision"] == "require_approvals" else None
    for r in rules:
        if r["min_total_minor"] <= total and (r["max_total_minor"] is None or total < r["max_total_minor"]):
            return r
    return None


def _pr_row(conn, organization_id: int, pr_id: int):
    row = conn.execute("SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
                       (pr_id, organization_id)).fetchone()
    if row is None:
        raise NotFoundError("درخواست خرید یافت نشد")
    return row


def _approval_state(conn, pr_row, rule) -> dict:
    approvers = [r["approver_user_id"] for r in conn.execute(
        "SELECT DISTINCT approver_user_id FROM procurement_approvals WHERE purchase_request_id=? AND action='approve'",
        (pr_row["id"],)).fetchall()]
    return {"rule": _rule_dict(rule) if rule is not None else None,
            "required_approvals": rule["required_approvals"] if rule is not None and rule["decision"] == "require_approvals" else None,
            "approvals": len(approvers), "status": pr_row["status"]}


def submit_with_rules(conn, *, organization_id: int, pr_id: int, actor_user_id: int) -> dict:
    """Submit (procurement_service rules apply), then auto-approve when the total is under an auto band."""
    pr_svc.submit_purchase_request(conn, pr_id, actor_user_id=actor_user_id, organization_id=organization_id)
    row = _pr_row(conn, organization_id, pr_id)
    total = estimated_total(conn, row)
    rule = matching_rule(conn, organization_id, total)
    decision = "manual"
    if rule is not None and rule["decision"] == "auto_approve":
        conn.execute("UPDATE purchase_requests SET status='approved', updated_at=? WHERE id=?", (_now(), pr_id))
        pr_svc._audit(conn, organization_id=organization_id, actor_user_id=actor_user_id, event_type="pr_approved",
                      entity_type="purchase_request", entity_id=pr_id,
                      details={"auto": True, "rule_id": rule["id"], "estimated_total_minor": total})
        decision = "auto_approved"
    elif rule is not None:
        decision = "requires_approvals"
    row = _pr_row(conn, organization_id, pr_id)
    return {"purchase_request": pr_svc._pr_dict(row), "decision": decision, "estimated_total_minor": total,
            "approval": _approval_state(conn, row, rule)}


def _role_matches(membership: dict, role: str | None) -> bool:
    if role is None:
        return pr_svc._can_approve(membership)
    if role == "approver":
        return membership["procurement_role"] == "approver" or membership["role"] == "organization_admin"
    return membership["role"] == role


def approve_with_rules(conn, *, organization_id: int, pr_id: int, actor_user_id: int, action: str,
                       reason=None) -> dict:
    """One approval step of a multi-level rule. N distinct approvers (never the requester) → approved."""
    membership = _membership(conn, actor_user_id, organization_id)
    row = _pr_row(conn, organization_id, pr_id)
    if row["status"] not in ("submitted", "under_review"):
        raise ConflictError(f"درخواست در وضعیت «{row['status']}» قابل بررسی نیست")
    if action not in ("approve", "reject"):
        raise ValidationError("اقدام باید approve یا reject باشد")
    rule = matching_rule(conn, organization_id, estimated_total(conn, row))
    if rule is None or rule["decision"] != "require_approvals":
        raise ConflictError("قاعدهٔ تأیید چندمرحله‌ای برای این درخواست تعریف نشده است؛ از تأیید معمولی استفاده کنید",
                            code="no_approval_rule")
    if row["requester_user_id"] == actor_user_id:
        raise PermissionError_("درخواست‌دهنده نمی‌تواند درخواست خود را تأیید کند")
    if not _role_matches(membership, rule["approver_role"]):
        raise PermissionError_("نقش شما برای تأیید این بازهٔ مبلغ کافی نیست")
    reason = pr_svc._text(reason, "توضیح", 2000)
    already = conn.execute("SELECT 1 FROM procurement_approvals WHERE purchase_request_id=? AND approver_user_id=? "
                           "AND action='approve'", (pr_id, actor_user_id)).fetchone()
    if already and action == "approve":
        raise ConflictError("شما قبلاً این درخواست را تأیید کرده‌اید؛ تأییدکنندهٔ دیگری لازم است",
                            code="duplicate_approver")
    count = len({r[0] for r in conn.execute("SELECT approver_user_id FROM procurement_approvals WHERE "
                                             "purchase_request_id=? AND action='approve'", (pr_id,)).fetchall()})
    conn.execute("""INSERT INTO procurement_approvals (purchase_request_id, approver_user_id, approver_membership_id,
                    action, reason, level) VALUES (?,?,?,?,?,?)""",
                 (pr_id, actor_user_id, membership["id"], action, reason, count + 1))
    if action == "reject":
        status = "rejected"
    else:
        status = "approved" if count + 1 >= int(rule["required_approvals"]) else "under_review"
    conn.execute("UPDATE purchase_requests SET status=?, updated_at=? WHERE id=?", (status, _now(), pr_id))
    from app.services.enterprise_procurement_service import record_event
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_id, actor_user_id=actor_user_id,
                 event_type="rule_approval_step",
                 payload={"rule_id": rule["id"], "action": action, "level": count + 1, "comment": reason})
    if status in ("approved", "rejected"):
        pr_svc._audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
                      event_type="pr_approved" if status == "approved" else "pr_rejected",
                      entity_type="purchase_request", entity_id=pr_id,
                      details={"reason": reason, "rule_id": rule["id"], "level": count + 1})
    row = _pr_row(conn, organization_id, pr_id)
    return {"purchase_request": pr_svc._pr_dict(row), "approval": _approval_state(conn, row, rule)}


# ── PO / reference number ──────────────────────────────────────────────────────


def _po_reference(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ValidationError("شمارهٔ سفارش خرید (PO) باید متنی حداکثر ۶۴ نویسه باشد")
    return value.strip()


def set_po_reference(conn, *, organization_id: int, pr_id: int, actor_user_id: int, po_reference) -> dict:
    m = _membership(conn, actor_user_id, organization_id)
    row = _pr_row(conn, organization_id, pr_id)
    if row["requester_user_id"] != actor_user_id and not pr_svc._can_procure(m) and not _is_admin(m):
        raise PermissionError_("فقط درخواست‌دهنده یا کارپرداز می‌تواند شمارهٔ PO را ثبت کند")
    if conn.execute("SELECT 1 FROM order_sources WHERE purchase_request_id=?", (pr_id,)).fetchone():
        raise ConflictError("برای این درخواست سفارش ثبت شده و شمارهٔ PO قابل تغییر نیست")
    ref = _po_reference(po_reference)
    conn.execute("UPDATE purchase_requests SET po_reference=?, updated_at=? WHERE id=?", (ref, _now(), pr_id))
    return {"purchase_request_id": pr_id, "po_reference": ref}


# ── order building blocks (shared with brand_service pre-order conversion) ─────


def _offer_row(conn, offer_id: int):
    return conn.execute(
        """SELECT o.*, p.title_fa, p.sku, p.category_id, p.master_product_id AS product_master_id,
                  s.status AS supplier_status, s.health_status, s.provenance AS supplier_provenance,
                  l.status AS location_status
           FROM seller_offers o JOIN products p ON p.id=o.product_id
           JOIN suppliers s ON s.id=o.supplier_id
           JOIN supplier_locations l ON l.id=o.supplier_location_id
           WHERE o.id=?""", (offer_id,)).fetchone()


def assert_offer_sellable(conn, offer, *, channel: str, check_price: bool = True) -> None:
    from app.services.sale_eligibility import allowed_provenance
    title = offer["title_fa"]
    if offer["status"] != "active" or offer["supplier_status"] != "active" or offer["location_status"] != "active":
        raise ConflictError(f"پیشنهاد فروش «{title}» فعال نیست", code="offer_unavailable",
                            details={"offer_id": offer["id"]})
    if offer["health_status"] == "suspended":
        raise ConflictError(f"فروشندهٔ «{title}» به‌دلیل وضعیت حساب معلق است", code="seller_suspended",
                            details={"offer_id": offer["id"]})
    prov = allowed_provenance()
    if offer["provenance"] not in prov or offer["supplier_provenance"] not in prov:
        raise ConflictError(f"پیشنهاد فروش «{title}» واقعی نیست", code="offer_unavailable",
                            details={"offer_id": offer["id"]})
    if offer["channel"] not in (channel, "both"):
        raise ConflictError(f"پیشنهاد «{title}» برای این کانال فروش عرضه نشده است", code="offer_channel_mismatch",
                            details={"offer_id": offer["id"], "channel": channel})
    if offer["valid_until"] and offer["valid_until"] < datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        raise ConflictError(f"اعتبار پیشنهاد «{title}» به پایان رسیده است", code="offer_expired",
                            details={"offer_id": offer["id"]})
    if check_price and (offer["pricing_mode"] not in ("fixed", "bulk") or int(offer["selling_price_minor"]) <= 0):
        raise ConflictError(f"پیشنهاد «{title}» قیمت قطعی ندارد", code="offer_not_priced",
                            details={"offer_id": offer["id"]})
    from app.services.product_channel_policy import require_sku
    require_sku(conn, int(offer["product_id"]), channel)


def plan_item(offer, *, quantity: int, selling_price_minor: int) -> dict:
    """One fulfillment-plan entry in the exact shape fulfillment_service expects."""
    return {
        "product_id": int(offer["product_id"]), "quantity": int(quantity), "title_fa": offer["title_fa"],
        "offer_id": int(offer["id"]), "supplier_id": int(offer["supplier_id"]),
        "location_id": int(offer["supplier_location_id"]), "selling_price_minor": int(selling_price_minor),
        "cost_price_minor": offer["cost_price_minor"], "geo_tier": "selected", "total_score": 0,
        "policy_type": "buyer_selected", "fulfillment_type": offer["fulfillment_type"] or "delivery",
        "prep_time_minutes": int(offer["prep_time_minutes"] or 60),
        "routing_reason": {"source": "buyer_selected_offer"}, "routing_candidates": [],
    }


def create_order_rows(conn, *, user_id: int, organization_id: int | None, actor_user_id: int, lines: list[dict],
                      shipping_minor: int, tax_minor: int, tax_rate_bps: int, address: dict, credit_minor: int,
                      cash_minor: int, allocation_id: int | None, idempotency_key: str, request_hash: str,
                      plan: dict) -> dict:
    """Insert payment intent, order and order items (status pending). Stock must already be reserved.

    lines: [{product_id, title_fa, sku, unit_price_minor, quantity}] — one per product.
    Returns {"order_id", "order_number", "intent_id", "items": {product_id: order_item_id}}.
    """
    subtotal = sum(int(l["unit_price_minor"]) * int(l["quantity"]) for l in lines)
    total = subtotal + shipping_minor + tax_minor
    if credit_minor + cash_minor != total:  # pragma: no cover - guarded by callers
        raise ValidationError("تفکیک پرداخت با جمع سفارش برابر نیست")
    from app.services.payment_service import new_reference, transition
    cur = conn.execute(
        """INSERT INTO payment_intents
               (reference, user_id, idempotency_key, request_hash, status, currency,
                subtotal_minor, shipping_fee_minor, tax_minor, taxable_base_minor, tax_rate_bps,
                total_minor, credit_minor, cash_minor, organization_id, allocation_id,
                recipient_name, recipient_phone, shipping_province, shipping_city, shipping_line1,
                shipping_postal_code, fulfillment_plan_json, created_at, updated_at)
           VALUES (?,?,?,?, 'pending', 'IRR', ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?)""",
        (new_reference(), user_id, idempotency_key, request_hash, subtotal, shipping_minor, tax_minor, subtotal,
         tax_rate_bps, total, credit_minor, cash_minor, organization_id, allocation_id if credit_minor else None,
         address["recipient_name"], address["recipient_phone"], address["province"], address["city"],
         address["line1"], address["postal_code"], json.dumps(plan, ensure_ascii=False), _sql_now(), _sql_now()))
    intent_id = int(cur.lastrowid)
    transition(conn, intent_id, "authorized")
    order_number = _new_order_number(conn)
    cur = conn.execute(
        """INSERT INTO orders (order_number, user_id, status, subtotal_minor, shipping_fee_minor, total_minor,
                               tax_minor, taxable_base_minor, tax_rate_bps, currency, recipient_name, recipient_phone,
                               shipping_province, shipping_city, shipping_line1, shipping_postal_code,
                               organization_id, credit_minor, cash_minor, payment_intent_id, placed_at)
           VALUES (?,?,'pending',?,?,?,?,?,?,'IRR',?,?,?,?,?,?,?,?,?,?,?)""",
        (order_number, user_id, subtotal, shipping_minor, total, tax_minor, subtotal, tax_rate_bps,
         address["recipient_name"], address["recipient_phone"], address["province"], address["city"],
         address["line1"], address["postal_code"], organization_id, credit_minor, cash_minor, intent_id, _sql_now()))
    order_id = int(cur.lastrowid)
    items = {}
    for l in lines:
        qty, unit = int(l["quantity"]), int(l["unit_price_minor"])
        cur = conn.execute("""INSERT INTO order_items (order_id, product_id, title_fa, sku, unit_price_minor, quantity,
                              line_total_minor) VALUES (?,?,?,?,?,?,?)""",
                           (order_id, int(l["product_id"]), l["title_fa"], l["sku"], unit, qty, unit * qty))
        items[int(l["product_id"])] = int(cur.lastrowid)
    conn.execute("UPDATE payment_intents SET order_id=? WHERE id=?", (order_id, intent_id))
    return {"order_id": order_id, "order_number": order_number, "intent_id": intent_id, "items": items,
            "total_minor": total, "subtotal_minor": subtotal}


def finalize_paid(conn, *, order_id: int, actor_user_id: int, provider: str, provider_ref: str) -> list[int]:
    """Fully funded: post the sales ledger, mark paid, capture the intent and release fulfillment orders."""
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    source = conn.execute("SELECT * FROM order_sources WHERE order_id=?", (order_id,)).fetchone()
    if order["status"] == "paid" and source["fulfillment_released"]:
        return []
    credit_minor, cash_minor = int(order["credit_minor"]), int(order["cash_minor"])
    entries = []
    if cash_minor > 0:
        entries.append(ledger_service.Entry(ledger_service.ACCOUNT_PSP_CLEARING, "debit", cash_minor))
    if credit_minor > 0:
        entries.append(ledger_service.Entry(ledger_service.ACCOUNT_ORG_RECEIVABLE, "debit", credit_minor))
    entries.append(ledger_service.Entry(ledger_service.ACCOUNT_SALES_REVENUE, "credit", int(order["subtotal_minor"])))
    if int(order["shipping_fee_minor"]) > 0:
        entries.append(ledger_service.Entry(ledger_service.ACCOUNT_SHIPPING_REVENUE, "credit",
                                            int(order["shipping_fee_minor"])))
    if int(order["tax_minor"]) > 0:
        entries.append(ledger_service.Entry(ledger_service.ACCOUNT_VAT_PAYABLE, "credit", int(order["tax_minor"])))
    ledger_service.post_transaction(conn, reference=f"order:{order['order_number']}",
                                    description=f"فروش سفارش {order['order_number']}", entries=entries,
                                    currency=order["currency"])
    conn.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
    from app.services.payment_service import transition
    transition(conn, int(order["payment_intent_id"]), "captured", provider=provider, provider_ref=provider_ref)
    order_items = [dict(r) for r in conn.execute("SELECT id, product_id FROM order_items WHERE order_id=?",
                                                 (order_id,)).fetchall()]
    fo_ids = fulfillment_service.confirm_fulfillment_orders_from_plan(
        conn, order_id=order_id, order_items=order_items, plan=json.loads(source["fulfillment_plan_json"]),
        actor_user_id=actor_user_id)
    conn.execute("UPDATE order_sources SET fulfillment_released=1, paid_at=?, "
                 "cash_status=CASE WHEN cash_status='due' THEN 'paid' ELSE cash_status END WHERE order_id=?",
                 (_now(), order_id))
    audit_service.record(conn, action="order.placed", entity_type="order", entity_id=order_id,
                         actor_user_id=actor_user_id,
                         metadata={"order_number": order["order_number"], "total_minor": int(order["total_minor"]),
                                   "credit_minor": credit_minor, "cash_minor": cash_minor,
                                   "organization_id": order["organization_id"], "provider": provider})
    return fo_ids


# ── credit selection ───────────────────────────────────────────────────────────


def _choose_allocation(conn, *, organization_id: int, user_id: int, amount_minor: int, lines: list[dict],
                       shipping_minor: int, tax_minor: int, allocation_id=None, actor_membership=None,
                       actor_user_id=None):
    from app.services.quote_service import _period_consumed
    sql = """SELECT a.*, o.status AS organization_status, m.status AS membership_status, m.role AS membership_role
             FROM credit_allocations a JOIN organizations o ON o.id=a.organization_id
             JOIN organization_memberships m ON m.id=a.membership_id
             WHERE a.organization_id=? AND {cond} ORDER BY (a.expires_at IS NULL), a.expires_at, a.id"""
    if allocation_id is not None:
        _int(allocation_id, "allocation_id", minimum=1)
        rows = conn.execute(sql.format(cond="a.id=?"), (organization_id, allocation_id)).fetchall()
        if not rows:
            raise NotFoundError("تخصیص اعتبار در این سازمان یافت نشد", code="allocation_not_found")
        privileged = actor_membership is not None and (_is_finance(actor_membership) or _is_admin(actor_membership))
        owner = actor_user_id if actor_user_id is not None else user_id
        if not privileged and int(rows[0]["user_id"]) != int(owner):
            raise PermissionError_("فقط تخصیص اعتبار خودتان را می‌توانید انتخاب کنید؛ انتخاب تخصیص دیگران با مالی/مدیر است",
                                   code="allocation_not_owned")
    else:
        rows = conn.execute(sql.format(cond="a.user_id=?"), (organization_id, user_id)).fetchall()
    cart_lines = []
    for l in lines:
        slug = conn.execute("SELECT c.slug FROM products p JOIN categories c ON c.id=p.category_id WHERE p.id=?",
                            (l["product_id"],)).fetchone()
        cart_lines.append(credit_rules.CartLine(
            product_id=int(l["product_id"]), title_fa=l["title_fa"], sku=l["sku"],
            category_slug=slug[0] if slug else "", unit_price_minor=int(l["unit_price_minor"]),
            quantity=int(l["quantity"]), line_total_minor=int(l["unit_price_minor"]) * int(l["quantity"])))
    subtotal = sum(c.line_total_minor for c in cart_lines)
    best_usable, reasons = 0, []
    for a in rows:
        state = credit_service.allocation_state(conn, int(a["id"]))
        ctx = credit_rules.CreditContext(
            now=datetime.now(timezone.utc), organization_status=a["organization_status"],
            membership_status=a["membership_status"], membership_role=a["membership_role"],
            allocation_status=a["status"], allocated_minor=state["allocated_minor"],
            available_minor=state["available_minor"], valid_from=a["valid_from"], expires_at=a["expires_at"],
            category_slugs=credit_rules.parse_category_slugs(a["category_slugs_json"]),
            per_transaction_limit_minor=a["per_transaction_limit_minor"], period_limit_minor=a["period_limit_minor"],
            period_consumed_minor=_period_consumed(conn, int(a["id"])), lines=cart_lines,
            shipping_fee_minor=shipping_minor, subtotal_minor=subtotal, tax_minor=tax_minor)
        ev = credit_rules.evaluate(ctx)
        usable = min(ev.usable_minor, state["available_minor"])
        if usable >= amount_minor:
            return a
        best_usable = max(best_usable, usable)
        reasons.extend(r.to_dict() for r in ev.restrictions if r.kind == credit_rules.BLOCK)
    raise ConflictError(
        f"اعتبار سازمانی کافی نیست: مبلغ لازم {amount_minor:,} ریال، قابل استفاده {best_usable:,} ریال. "
        "سفارش ثبت نشد و هیچ موجودی یا اعتباری رزرو نشد.",
        code="insufficient_credit",
        details={"required_minor": amount_minor, "usable_minor": best_usable, "restrictions": reasons[:5]})


# ── conversion: purchase request → order ───────────────────────────────────────


def _lines_from_offers(conn, pr_row, pr_items: list, raw_lines) -> tuple[list[dict], int, int | None]:
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValidationError("برای هر ردیف درخواست یک پیشنهاد فروش (offer_id) انتخاب کنید")
    by_id = {int(i["id"]): i for i in pr_items}
    seen = {}
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise ValidationError("ردیف سفارش نامعتبر است")
        pri = _int(entry.get("purchase_request_item_id"), "purchase_request_item_id", minimum=1)
        offer_id = _int(entry.get("offer_id"), "offer_id", minimum=1)
        if pri not in by_id or pri in seen:
            raise ValidationError("ردیف درخواست نامعتبر یا تکراری است", details={"purchase_request_item_id": pri})
        seen[pri] = offer_id
    missing = sorted(set(by_id) - set(seen))
    if missing:
        raise ValidationError("برای همهٔ ردیف‌های درخواست باید پیشنهاد فروش انتخاب شود",
                              details={"missing_purchase_request_item_ids": missing})
    lines = []
    for pri, offer_id in seen.items():
        item = by_id[pri]
        offer = _offer_row(conn, offer_id)
        if offer is None:
            raise NotFoundError("پیشنهاد فروش یافت نشد", details={"offer_id": offer_id})
        assert_offer_sellable(conn, offer, channel="organization")
        if item["master_product_id"] is not None and offer["product_master_id"] != item["master_product_id"]:
            raise ValidationError(f"پیشنهاد «{offer['title_fa']}» با کالای ردیف درخواست مطابقت ندارد",
                                  details={"purchase_request_item_id": pri, "offer_id": offer_id})
        from app.services.freshness_service import enforce_freshness_for_checkout
        enforce_freshness_for_checkout(conn, offer_id)
        lines.append({"offer": offer, "pr_item_ids": [pri], "quantity": int(item["quantity"]),
                      "unit_price_minor": int(offer["selling_price_minor"]), "vat_bps": None})
    return lines, 0, None


def _lines_from_quote(conn, pr_row, pr_items: list, quote_id) -> tuple[list[dict], int, int]:
    quote_id = _int(quote_id, "supplier_quote_id", minimum=1)
    quote = conn.execute("""SELECT q.*, r.purchase_request_id FROM supplier_quotes q JOIN rfqs r ON r.id=q.rfq_id
                            WHERE q.id=?""", (quote_id,)).fetchone()
    if quote is None or quote["purchase_request_id"] != pr_row["id"]:
        raise NotFoundError("پیش‌فاکتور این درخواست یافت نشد")
    if quote["status"] != "awarded":
        raise ConflictError("فقط پیش‌فاکتور پذیرفته‌شده (awarded) به سفارش تبدیل می‌شود", code="quote_not_awarded")
    if int(quote["discount_minor"] or 0) > 0:
        raise ConflictError("تخفیف کلی پیش‌فاکتور هنوز قابل تبدیل به ردیف سفارش نیست", code="quote_discount_unsupported")
    rows = conn.execute("""SELECT qi.*, ri.purchase_request_item_id, ri.master_product_id, ri.quantity_requested
                           FROM supplier_quote_items qi JOIN rfq_items ri ON ri.id=qi.rfq_item_id
                           WHERE qi.supplier_quote_id=? ORDER BY qi.id""", (quote_id,)).fetchall()
    if not rows:
        raise ValidationError("پیش‌فاکتور ردیفی ندارد")
    lines = []
    for r in rows:
        qty = int(r["quantity_requested"])
        if int(r["quantity_available"]) < qty:
            raise ConflictError("تعداد قابل تأمین پیش‌فاکتور از تعداد درخواست کمتر است",
                                code="quote_quantity_short", details={"rfq_item_id": r["rfq_item_id"]})
        if r["master_product_id"] is None:
            raise ValidationError("ردیف بدون کالای مرجع قابل تبدیل به سفارش نیست",
                                  details={"rfq_item_id": r["rfq_item_id"]})
        offer_ref = conn.execute(
            """SELECT o.id FROM seller_offers o JOIN products p ON p.id=o.product_id
               WHERE o.supplier_id=? AND p.master_product_id=? AND o.status='active'
               ORDER BY (o.stock_quantity - o.stock_reserved) DESC, o.id LIMIT 1""",
            (quote["supplier_id"], r["master_product_id"])).fetchone()
        if offer_ref is None:
            raise ConflictError("تأمین‌کنندهٔ برنده برای این کالا پیشنهاد فروش فعال ندارد",
                                code="quote_offer_missing", details={"rfq_item_id": r["rfq_item_id"]})
        offer = _offer_row(conn, int(offer_ref["id"]))
        assert_offer_sellable(conn, offer, channel="organization", check_price=False)
        gross = int(r["unit_price_minor"]) * qty - int(r["discount_minor"] or 0)
        if gross < 0 or gross % qty:
            raise ConflictError("تخفیف ردیف پیش‌فاکتور بر تعداد بخش‌پذیر نیست", code="quote_discount_unsupported",
                                details={"rfq_item_id": r["rfq_item_id"]})
        lines.append({"offer": offer, "pr_item_ids": [r["purchase_request_item_id"]] if r["purchase_request_item_id"] else [],
                      "quantity": qty, "unit_price_minor": gross // qty, "vat_bps": int(r["vat_rate_bps"])})
    return lines, int(quote["shipping_cost_minor"] or 0), quote_id


def _merge_by_product(lines: list[dict]) -> list[dict]:
    merged: dict[int, dict] = {}
    for l in lines:
        pid = int(l["offer"]["product_id"])
        if pid in merged:
            m = merged[pid]
            if m["offer"]["id"] != l["offer"]["id"] or m["unit_price_minor"] != l["unit_price_minor"]:
                raise ValidationError(f"کالای «{l['offer']['title_fa']}» در دو ردیف با پیشنهاد متفاوت آمده است")
            m["quantity"] += l["quantity"]
            m["pr_item_ids"] += l["pr_item_ids"]
        else:
            merged[pid] = dict(l, pr_item_ids=list(l["pr_item_ids"]))
    for m in merged.values():
        o = m["offer"]
        if m["quantity"] < int(o["min_order_quantity"] or 1) or (o["max_order_quantity"] and m["quantity"] > int(o["max_order_quantity"])):
            raise ValidationError(f"تعداد «{o['title_fa']}» خارج از حداقل/حداکثر سفارش فروشنده است",
                                  details={"offer_id": o["id"], "quantity": m["quantity"]})
    return list(merged.values())


def _address_for(pr_row, data: dict) -> dict:
    if data.get("shipping_address") is not None:
        return _clean_address(data["shipping_address"])
    destinations = json.loads(pr_row["destinations_json"] or "[]")
    first = destinations[0] if destinations else {}
    recipient = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
    return _clean_address({
        "recipient_name": recipient.get("name") or first.get("recipient_name"),
        "recipient_phone": recipient.get("phone") or first.get("recipient_phone"),
        "province": pr_row["delivery_province"] or first.get("province"),
        "city": pr_row["delivery_city"] or first.get("city"),
        "line1": pr_row["delivery_address"] or first.get("address"),
        "postal_code": recipient.get("postal_code"),
    })


def _write_allocations(conn, *, order_id: int, pr_row, pr_items: list, lines: list[dict], items: dict,
                       address: dict) -> None:
    destinations = json.loads(pr_row["destinations_json"] or "[]")
    index_of = {int(it["id"]): idx for idx, it in enumerate(pr_items)}
    for l in lines:
        order_item_id = items[int(l["offer"]["product_id"])]
        for pri in l["pr_item_ids"]:
            idx = index_of.get(int(pri))
            requested = int(pr_items[idx]["quantity"]) if idx is not None else int(l["quantity"])
            allocated = 0
            for d_index, d in enumerate(destinations):
                for a in d.get("allocations", []):
                    if idx is not None and a["item_index"] == idx:
                        conn.execute("""INSERT INTO org_order_allocations (order_id, order_item_id,
                                        purchase_request_item_id, destination_index, destination_label, province, city,
                                        address, recipient_name, recipient_phone, quantity) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                     (order_id, order_item_id, pri, d_index, d.get("label"), d.get("province"),
                                      d.get("city"), d.get("address"), d.get("recipient_name"),
                                      d.get("recipient_phone"), int(a["quantity"])))
                        allocated += int(a["quantity"])
            if requested - allocated > 0:
                conn.execute("""INSERT INTO org_order_allocations (order_id, order_item_id, purchase_request_item_id,
                                destination_index, destination_label, province, city, address, recipient_name,
                                recipient_phone, quantity) VALUES (?,?,?,NULL,?,?,?,?,?,?,?)""",
                             (order_id, order_item_id, pri, "آدرس اصلی", address["province"], address["city"],
                              address["line1"], address["recipient_name"], address["recipient_phone"],
                              requested - allocated))


def approval_tolerance_bps() -> int:
    import os
    try:
        return max(0, int(os.environ.get("ORG_APPROVAL_TOLERANCE_BPS", "0")))
    except ValueError:
        return 0


def _assert_within_approved(conn, pr_row, total_minor: int) -> None:
    """The order total may not exceed the amount that was approved (estimate, else budget) + tolerance."""
    approved = estimated_total(conn, pr_row)
    if approved is None:
        return  # nothing priced at approval; band rules already forced the strictest approval path
    limit = approved + approved * approval_tolerance_bps() // 10000
    if total_minor > limit:
        raise ConflictError(
            f"مبلغ سفارش ({total_minor:,} ریال) از مبلغ تأییدشده ({approved:,} ریال) بیشتر است؛ "
            "درخواست را با مبلغ جدید دوباره برای تأیید بفرستید",
            code="exceeds_approved_amount",
            details={"total_minor": total_minor, "approved_minor": approved, "limit_minor": limit})


def convert_purchase_request(conn, *, organization_id: int, actor_user_id: int, data: dict,
                             idempotency_key) -> tuple[int, dict]:
    """Approved PR (+ chosen offers or awarded quote) → order. Returns (http_status, body)."""
    key = _idempotency_key(idempotency_key)
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    request_hash = _hash(data)
    stored = conn.execute("SELECT order_id, request_hash FROM order_sources WHERE organization_id=? AND idempotency_key=?",
                          (organization_id, key)).fetchone()
    if stored is not None:
        if stored["request_hash"] != request_hash:
            raise ConflictError("این Idempotency-Key قبلاً با درخواست متفاوتی استفاده شده است",
                                code="idempotency_key_reuse")
        _require_reader(conn, actor_user_id, organization_id)
        return 200, dict(order_view(conn, int(stored["order_id"])), replayed=True)

    membership = _membership(conn, actor_user_id, organization_id)
    if not pr_svc._can_procure(membership):
        raise PermissionError_("فقط کارپرداز یا مدیر سازمان می‌تواند درخواست را به سفارش تبدیل کند")
    pr_svc._assert_org_accepts_intake(conn, organization_id)
    pr_id = _int(data.get("purchase_request_id"), "purchase_request_id", minimum=1)
    pr_row = _pr_row(conn, organization_id, pr_id)
    if pr_row["status"] not in CONVERTIBLE_PR_STATUSES:
        raise ConflictError(f"درخواست در وضعیت «{pr_row['status']}» هنوز تأیید نشده و قابل تبدیل به سفارش نیست",
                            code="purchase_request_not_approved")
    if conn.execute("SELECT 1 FROM order_sources WHERE purchase_request_id=?", (pr_id,)).fetchone():
        raise ConflictError("برای این درخواست خرید قبلاً سفارش ثبت شده است", code="org_order_exists")
    pr_items = [dict(r) for r in conn.execute("SELECT * FROM purchase_request_items WHERE purchase_request_id=? "
                                              "ORDER BY id", (pr_id,)).fetchall()]
    if data.get("supplier_quote_id") is not None and data.get("lines") is not None:
        raise ValidationError("یا پیش‌فاکتور پذیرفته‌شده یا پیشنهادهای انتخابی؛ نه هر دو")
    if data.get("supplier_quote_id") is not None:
        raw, shipping_minor, quote_id = _lines_from_quote(conn, pr_row, pr_items, data["supplier_quote_id"])
    else:
        raw, shipping_minor, quote_id = _lines_from_offers(conn, pr_row, pr_items, data.get("lines"))
    lines = _merge_by_product(raw)

    warnings = []
    for l in lines:
        o = l["offer"]
        g = guided_check(conn, organization_id, supplier_id=int(o["supplier_id"]), category_id=o["category_id"])
        if not g["preferred"]:
            if g["mode"] == "enforce":
                raise ConflictError(f"فروشندهٔ «{o['title_fa']}» در فهرست فروشندگان ترجیحی سازمان نیست",
                                    code="preferred_seller_required",
                                    details={"offer_id": o["id"], "supplier_id": o["supplier_id"]})
            warnings.append({"code": "not_preferred_seller", "offer_id": o["id"], "supplier_id": o["supplier_id"],
                             "message": f"«{o['title_fa']}» از فروشندهٔ خارج از فهرست ترجیحی خریداری می‌شود"})

    subtotal = sum(l["unit_price_minor"] * l["quantity"] for l in lines)
    if quote_id is not None:
        tax_minor = sum(l["unit_price_minor"] * l["quantity"] * l["vat_bps"] // 10000 for l in lines)
        rates = {l["vat_bps"] for l in lines}
        tax_rate_bps = rates.pop() if len(rates) == 1 else (tax_minor * 10000 // subtotal if subtotal else 0)
    else:
        tax_minor, tax_rate_bps = _tax(conn, subtotal, organization_id)
    total = subtotal + shipping_minor + tax_minor
    if total <= 0:
        raise ValidationError("جمع سفارش باید بیشتر از صفر باشد")
    _assert_within_approved(conn, pr_row, total)
    # Free-text rows (no master_product_id) are not bound to a catalogue product, so the offer chosen for
    # them must be picked by someone allowed to approve (never the requester) — an explicit approver choice.
    if quote_id is None and any(i["master_product_id"] is None for i in pr_items):
        if not pr_svc._can_approve(membership) or int(pr_row["requester_user_id"]) == actor_user_id:
            raise ConflictError("برای ردیف بدون کالای مرجع، پیشنهاد فروش باید توسط تأییدکنندهٔ سازمان انتخاب شود",
                                code="offer_choice_requires_approver")

    method, bps = _resolve_payment(conn, organization_id, data.get("payment_method"))
    cash_minor = {"credit": 0, "cash": total, "prepayment": total * bps // 10000}[method]
    credit_minor = total - cash_minor
    order_lines = [{"product_id": int(l["offer"]["product_id"]), "title_fa": l["offer"]["title_fa"],
                    "sku": l["offer"]["sku"], "unit_price_minor": l["unit_price_minor"], "quantity": l["quantity"]}
                   for l in lines]
    allocation = None
    if credit_minor > 0:
        allocation = _choose_allocation(conn, organization_id=organization_id, user_id=int(pr_row["requester_user_id"]),
                                        amount_minor=credit_minor, lines=order_lines, shipping_minor=shipping_minor,
                                        tax_minor=tax_minor, allocation_id=data.get("allocation_id"),
                                        actor_membership=membership, actor_user_id=actor_user_id)
    address = _address_for(pr_row, data)
    po_ref = _po_reference(data.get("po_reference")) if data.get("po_reference") is not None else pr_row["po_reference"]

    plan = {"customer_province": address["province"], "customer_city": address["city"],
            "items": [plan_item(l["offer"], quantity=l["quantity"], selling_price_minor=l["unit_price_minor"])
                      for l in lines]}
    # Race-safe under BEGIN IMMEDIATE; raises ConflictError(supplier_stock_changed) → whole transaction rolls back.
    fulfillment_service.reserve_supplier_stock_for_plan(conn, plan=plan)

    created = create_order_rows(
        conn, user_id=int(pr_row["requester_user_id"]), organization_id=organization_id, actor_user_id=actor_user_id,
        lines=order_lines, shipping_minor=shipping_minor, tax_minor=tax_minor, tax_rate_bps=tax_rate_bps,
        address=address, credit_minor=credit_minor, cash_minor=cash_minor,
        allocation_id=int(allocation["id"]) if allocation is not None else None,
        idempotency_key=f"org-order:{organization_id}:{key}", request_hash=request_hash, plan=plan)
    order_id = created["order_id"]
    if credit_minor > 0:
        credit_service.reserve(conn, allocation_id=int(allocation["id"]), amount_minor=credit_minor,
                               payment_intent_id=created["intent_id"], actor_user_id=actor_user_id)
        credit_service.capture(conn, payment_intent_id=created["intent_id"], order_id=order_id,
                               actor_user_id=actor_user_id)
    _write_allocations(conn, order_id=order_id, pr_row=pr_row, pr_items=pr_items, lines=lines,
                       items=created["items"], address=address)
    conn.execute(
        """INSERT INTO order_sources (order_id, source_kind, organization_id, purchase_request_id, supplier_quote_id,
                                      po_reference, payment_method, prepayment_bps, credit_minor, cash_due_minor,
                                      cash_status, payment_intent_id, fulfillment_plan_json, idempotency_key,
                                      request_hash, created_by_user_id, created_at)
           VALUES (?, 'purchase_request', ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, organization_id, pr_id, quote_id, po_ref, method, bps, credit_minor, cash_minor,
         "due" if cash_minor else "none", created["intent_id"], json.dumps(plan, ensure_ascii=False), key,
         request_hash, actor_user_id, _now()))
    if po_ref != pr_row["po_reference"]:
        conn.execute("UPDATE purchase_requests SET po_reference=?, updated_at=? WHERE id=?", (po_ref, _now(), pr_id))
    if cash_minor == 0:
        finalize_paid(conn, order_id=order_id, actor_user_id=actor_user_id, provider="org_credit",
                      provider_ref=f"credit:{created['order_number']}")
    from app.services.enterprise_procurement_service import record_event
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_id, actor_user_id=actor_user_id,
                 event_type="order_created",
                 payload={"order_id": order_id, "order_number": created["order_number"], "payment_method": method,
                          "total_minor": total, "po_reference": po_ref})
    audit_service.record(conn, action="org_order.created", entity_type="order", entity_id=order_id,
                         actor_user_id=actor_user_id,
                         metadata={"organization_id": organization_id, "purchase_request_id": pr_id,
                                   "supplier_quote_id": quote_id, "total_minor": total, "credit_minor": credit_minor,
                                   "cash_due_minor": cash_minor, "payment_method": method})
    return 201, dict(order_view(conn, order_id), warnings=warnings, replayed=False)


def confirm_cash_payment(conn, *, organization_id: int, order_id: int, actor_user_id: int, reference) -> dict:
    """Finance confirms the cash / prepayment share was received → order paid, fulfillment released."""
    m = _membership(conn, actor_user_id, organization_id)
    if not _is_finance(m):
        raise PermissionError_("فقط مالی یا مدیر سازمان می‌تواند دریافت وجه را تأیید کند")
    source = conn.execute("SELECT * FROM order_sources WHERE order_id=? AND organization_id=?",
                          (order_id, organization_id)).fetchone()
    if source is None:
        raise NotFoundError("سفارش سازمانی یافت نشد")
    if source["cash_status"] != "due":
        return order_view(conn, order_id)
    ref = pr_svc._text(reference, "شمارهٔ پیگیری پرداخت", 100, required=True)
    conn.execute("UPDATE order_sources SET cash_reference=? WHERE order_id=?", (ref, order_id))
    finalize_paid(conn, order_id=order_id, actor_user_id=actor_user_id, provider="org_transfer", provider_ref=ref)
    return order_view(conn, order_id)


# ── unpaid cash share: expiry and explicit cancellation ───────────────────────


def cash_due_hours() -> int:
    import os
    try:
        return max(1, int(os.environ.get("ORG_CASH_DUE_HOURS", "72")))
    except ValueError:
        return 72


def _cancel_unpaid(conn, *, order_id: int, actor_user_id: int | None, reason: str, action: str) -> bool:
    """Release reserved stock, give back captured credit (append-only), cancel the order.

    Only for orders whose cash share is still 'due' and whose fulfillment was never released.
    Returns False when the order is not in that state (idempotent no-op).
    """
    src = conn.execute("SELECT * FROM order_sources WHERE order_id=?", (order_id,)).fetchone()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if src is None or order is None or src["cash_status"] != "due" or src["fulfillment_released"] \
            or order["status"] != "pending":
        return False
    fulfillment_service.release_supplier_stock_for_plan(conn, plan_json=src["fulfillment_plan_json"])
    restored = 0
    if int(src["credit_minor"] or 0) > 0 and src["payment_intent_id"] is not None:
        restored = credit_service.reverse_capture(conn, payment_intent_id=int(src["payment_intent_id"]),
                                                  order_id=order_id, actor_user_id=actor_user_id, reason=reason)
    conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    conn.execute("UPDATE order_sources SET cash_status='cancelled' WHERE order_id=?", (order_id,))
    intent = conn.execute("SELECT status FROM payment_intents WHERE id=?", (order["payment_intent_id"],)).fetchone()
    if intent is not None and intent["status"] in ("pending", "authorized"):
        from app.services.payment_service import transition
        transition(conn, int(order["payment_intent_id"]), "cancelled", failure_reason=reason[:200])
    if src["preorder_id"] is not None:
        conn.execute("UPDATE preorders SET status='cancelled', updated_at=? WHERE id=? AND status='converted'",
                     (_now(), int(src["preorder_id"])))
    audit_service.record(conn, action=action, entity_type="order", entity_id=order_id, actor_user_id=actor_user_id,
                         metadata={"reason": reason, "credit_restored_minor": restored,
                                   "cash_due_minor": int(src["cash_due_minor"])})
    return True


def expire_unpaid(conn, now: datetime | None = None) -> dict:
    """Cron body: cancel orders whose cash/prepayment share stayed 'due' longer than ORG_CASH_DUE_HOURS."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = (now - timedelta(hours=cash_due_hours())).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute("SELECT order_id FROM order_sources WHERE cash_status='due' AND fulfillment_released=0 "
                        "AND SUBSTR(REPLACE(created_at, ' ', 'T'), 1, 19) < ? ORDER BY order_id",
                        (cutoff,)).fetchall()
    expired = [int(r["order_id"]) for r in rows
               if _cancel_unpaid(conn, order_id=int(r["order_id"]), actor_user_id=None,
                                 reason="مهلت پرداخت سهم نقدی به پایان رسید", action="org_order.expired")]
    return {"expired": len(expired), "order_ids": expired}


def cancel_org_order(conn, *, organization_id: int, order_id: int, actor_user_id: int, reason=None) -> dict:
    """Finance/admin (or the procurement officer who placed it) cancels an org order before fulfillment."""
    m = _membership(conn, actor_user_id, organization_id)
    src = conn.execute("SELECT * FROM order_sources WHERE order_id=? AND organization_id=?",
                       (order_id, organization_id)).fetchone()
    if src is None:
        raise NotFoundError("سفارش سازمانی یافت نشد", code="order_not_found")
    if not (_is_finance(m) or (pr_svc._can_procure(m) and int(src["created_by_user_id"]) == actor_user_id)):
        raise PermissionError_("فقط مالی/مدیر سازمان یا ثبت‌کنندهٔ سفارش می‌تواند آن را لغو کند")
    text = pr_svc._text(reason, "دلیل لغو", 500) or "لغو توسط سازمان"
    if not _cancel_unpaid(conn, order_id=order_id, actor_user_id=actor_user_id, reason=text,
                          action="org_order.cancelled"):
        raise ConflictError("این سفارش پرداخت شده یا ارسال آن آغاز شده و قابل لغو نیست",
                            code="order_not_cancellable")
    return order_view(conn, order_id)


# ── read models: order, invoice, monthly statement ─────────────────────────────


def order_view(conn, order_id: int) -> dict:
    o = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if o is None:
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    s = conn.execute("SELECT * FROM order_sources WHERE order_id=?", (order_id,)).fetchone()
    items = [dict(r) for r in conn.execute(
        "SELECT id, product_id, title_fa, sku, unit_price_minor, quantity, line_total_minor FROM order_items "
        "WHERE order_id=? ORDER BY id", (order_id,)).fetchall()]
    allocations = [dict(r) for r in conn.execute(
        "SELECT order_item_id, purchase_request_item_id, destination_index, destination_label, province, city, "
        "address, recipient_name, recipient_phone, quantity FROM org_order_allocations WHERE order_id=? ORDER BY id",
        (order_id,)).fetchall()]
    fos = [dict(r) for r in conn.execute("SELECT id, supplier_id, supplier_location_id, status FROM fulfillment_orders "
                                         "WHERE order_id=? ORDER BY id", (order_id,)).fetchall()]
    return {
        "id": o["id"], "order_number": o["order_number"], "status": o["status"], "placed_at": o["placed_at"],
        "organization_id": o["organization_id"], "user_id": o["user_id"], "currency": o["currency"],
        "subtotal_minor": o["subtotal_minor"], "shipping_fee_minor": o["shipping_fee_minor"],
        "tax_minor": o["tax_minor"], "tax_rate_bps": o["tax_rate_bps"], "total_minor": o["total_minor"],
        "credit_minor": o["credit_minor"], "cash_minor": o["cash_minor"],
        "source": None if s is None else {
            "kind": s["source_kind"], "purchase_request_id": s["purchase_request_id"],
            "supplier_quote_id": s["supplier_quote_id"], "preorder_id": s["preorder_id"],
            "po_reference": s["po_reference"], "payment_method": s["payment_method"],
            "prepayment_bps": s["prepayment_bps"], "cash_due_minor": s["cash_due_minor"],
            "cash_status": s["cash_status"], "fulfillment_released": bool(s["fulfillment_released"])},
        "items": items, "allocations": allocations, "fulfillment_orders": fos,
        "shipping": {"recipient_name": o["recipient_name"], "recipient_phone": o["recipient_phone"],
                     "province": o["shipping_province"], "city": o["shipping_city"], "line1": o["shipping_line1"],
                     "postal_code": o["shipping_postal_code"]},
    }


def get_org_order(conn, *, organization_id: int, order_id: int, actor_user_id: int) -> dict:
    m = _membership(conn, actor_user_id, organization_id)
    o = conn.execute("SELECT user_id FROM orders WHERE id=? AND organization_id=?", (order_id, organization_id)).fetchone()
    if o is None:
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    if o["user_id"] != actor_user_id and not (pr_svc._can_read_org_requests(m) or _is_finance(m)):
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    return order_view(conn, order_id)


def list_org_orders(conn, *, organization_id: int, actor_user_id: int) -> list[dict]:
    _require_reader(conn, actor_user_id, organization_id)
    rows = conn.execute("""SELECT o.id, o.order_number, o.status, o.placed_at, o.total_minor, o.credit_minor,
                                  o.cash_minor, s.po_reference, s.payment_method, s.cash_status, s.purchase_request_id
                           FROM orders o LEFT JOIN order_sources s ON s.order_id=o.id
                           WHERE o.organization_id=? ORDER BY o.id DESC LIMIT 500""", (organization_id,)).fetchall()
    return [dict(r) for r in rows]


def invoice(conn, *, organization_id: int, order_id: int, actor_user_id: int) -> dict:
    """Buyer-facing invoice read model (no new storage) carrying the PO reference."""
    view = get_org_order(conn, organization_id=organization_id, order_id=order_id, actor_user_id=actor_user_id)
    org = conn.execute("SELECT id, legal_name, display_name, national_id FROM organizations WHERE id=?",
                       (organization_id,)).fetchone()
    pr_number = None
    if view["source"] and view["source"]["purchase_request_id"]:
        r = conn.execute("SELECT request_number FROM purchase_requests WHERE id=?",
                         (view["source"]["purchase_request_id"],)).fetchone()
        pr_number = r["request_number"] if r else None
    return {"invoice_number": f"INV-{view['order_number']}", "order_number": view["order_number"],
            "issued_at": view["placed_at"], "status": view["status"],
            "buyer": {"organization_id": org["id"], "legal_name": org["legal_name"],
                      "display_name": org["display_name"], "national_id": org["national_id"]},
            "po_reference": view["source"]["po_reference"] if view["source"] else None,
            "purchase_request_number": pr_number, "lines": view["items"],
            "subtotal_minor": view["subtotal_minor"], "shipping_fee_minor": view["shipping_fee_minor"],
            "tax_minor": view["tax_minor"], "tax_rate_bps": view["tax_rate_bps"], "total_minor": view["total_minor"],
            "credit_minor": view["credit_minor"], "cash_minor": view["cash_minor"], "currency": view["currency"]}


def _month_bounds(month) -> tuple[str, str]:
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise ValidationError("ماه باید به شکل YYYY-MM باشد")
    try:
        y, m = int(month[:4]), int(month[5:])
        if not 1 <= m <= 12 or y < 2000:
            raise ValueError
    except ValueError:
        raise ValidationError("ماه باید به شکل YYYY-MM باشد")
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01"


def monthly_statement(conn, *, organization_id: int, actor_user_id: int, month) -> dict:
    """Consolidated statement: every order of the organization placed in the month (any channel)."""
    m = _membership(conn, actor_user_id, organization_id)
    if not (_is_finance(m) or pr_svc._can_procure(m) or pr_svc._can_approve(m)):
        raise PermissionError_("دسترسی صورت‌حساب تجمیعی سازمان را ندارید")
    start, end = _month_bounds(month)
    rows = conn.execute(
        """SELECT o.id, o.order_number, o.status, o.placed_at, o.user_id, o.subtotal_minor, o.shipping_fee_minor,
                  o.tax_minor, o.total_minor, o.credit_minor, o.cash_minor,
                  s.po_reference, s.payment_method, s.cash_status, s.cash_due_minor, s.purchase_request_id
           FROM orders o LEFT JOIN order_sources s ON s.order_id=o.id
           WHERE o.organization_id=? AND o.placed_at>=? AND o.placed_at<?
           ORDER BY o.placed_at, o.id""", (organization_id, start, end)).fetchall()
    orders = [dict(r) for r in rows]
    counted = [o for o in orders if o["status"] not in ("cancelled", "refunded")]
    totals = {k: sum(int(o[k]) for o in counted) for k in
              ("subtotal_minor", "shipping_fee_minor", "tax_minor", "total_minor", "credit_minor")}
    totals["cash_outstanding_minor"] = sum(int(o["cash_due_minor"] or 0) for o in counted if o["cash_status"] == "due")
    totals["orders_count"] = len(counted)
    return {"organization_id": organization_id, "month": month, "period_start": start, "period_end": end,
            "orders": orders, "totals": totals}
