"""Procurement finance on the purchase-order chain.

Everything is gated by the organization's approved payment policy
(customer_payment_policies). Without a policy nothing can be created. Every
plan, part, settlement and ledger event carries the policy's environment
('test' or 'production'), so QA fixtures can never be mistaken for real money.
No gateway, bank or credit-bureau integration exists here: rows are records of
what finance confirmed, not transactions this system performs.
"""
from __future__ import annotations

import datetime
import json

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import procurement_service as pr_svc

METHODS = ("cash", "cheque", "credit", "bill")
METHOD_FA = {"cash": "نقدی", "cheque": "چکی", "credit": "اعتباری", "bill": "برات/تعهد"}
NEEDS_INSTRUMENT = ("cheque", "bill")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _member(conn, org: int, user: int) -> dict:
    return pr_svc._assert_org_member(conn, user, org)


def _is_finance(m: dict) -> bool:
    return m["role"] in ("organization_finance", "organization_admin")


def policy(conn, org: int) -> dict | None:
    from app.services.payment_policy_service import effective_policy_id
    pid = effective_policy_id(conn, org)
    row = conn.execute("SELECT * FROM customer_payment_policies WHERE id=?", (pid,)).fetchone() if pid else None
    if not row:
        return None
    try:
        rules = json.loads(row["rules_json"])
    except ValueError:
        rules = {}
    methods = [m for m in rules.get("methods", []) if m in METHODS] if isinstance(rules, dict) else []
    return {"id": row["id"], "version": row["version"], "contract_reference": row["contract_reference"],
            "environment": row["environment"], "methods": methods,
            "credit_limit_minor": rules.get("credit_limit_minor") if isinstance(rules.get("credit_limit_minor"), int) else None,
            "max_parts": rules.get("max_parts") if isinstance(rules.get("max_parts"), int) else 12,
            "max_term_days": rules.get("max_term_days") if isinstance(rules.get("max_term_days"), int) else None,
            "dual_approval_threshold_minor": rules.get("dual_approval_threshold_minor")
            if isinstance(rules.get("dual_approval_threshold_minor"), int) else None,
            "effective_from": rules.get("effective_from")}


def _event(conn, org, po_id, env, kind, actor, amount=0, plan_id=None, part_id=None, note=None):
    conn.execute(
        """INSERT INTO procurement_finance_events (organization_id, purchase_order_id, plan_id, part_id, environment, kind,
               amount_minor, actor_user_id, note) VALUES (?,?,?,?,?,?,?,?,?)""",
        (org, po_id, plan_id, part_id, env, kind, amount, actor, note))


def _po(conn, org: int, po_id: int):
    po = conn.execute("SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, org)).fetchone()
    if not po:
        raise NotFoundError("سفارش خرید یافت نشد")
    return po


def _plan(conn, po_id: int):
    return conn.execute("SELECT * FROM procurement_payment_plans WHERE purchase_order_id=?", (po_id,)).fetchone()


def credit_usage(conn, org: int, env: str) -> int:
    return conn.execute(
        """SELECT COALESCE(SUM(pp.amount_minor),0) FROM procurement_payment_parts pp
           JOIN procurement_payment_plans p ON p.id=pp.plan_id
           JOIN purchase_orders o ON o.id=p.purchase_order_id
           WHERE o.organization_id=? AND p.environment=? AND pp.method='credit'
             AND p.status IN ('submitted','approved') AND pp.status NOT IN ('cancelled','bounced')""",
        (org, env)).fetchone()[0]


def po_finance(conn, org: int, po_id: int) -> dict:
    """Brief used by the case workspace, next-action and closure rules."""
    pol = policy(conn, org)
    plan = _plan(conn, po_id)
    parts = [dict(r) for r in conn.execute(
        "SELECT * FROM procurement_payment_parts WHERE plan_id=? ORDER BY id", (plan["id"],))] if plan else []
    refunds = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) FROM procurement_finance_events WHERE purchase_order_id=? AND kind='refund_recorded'",
        (po_id,)).fetchone()[0]
    collected = sum(p["amount_minor"] for p in parts
                    if p["status"] == "cleared" or (p["status"] == "received" and p["method"] not in NEEDS_INSTRUMENT))
    settlement = conn.execute("SELECT * FROM procurement_supplier_settlements WHERE purchase_order_id=?", (po_id,)).fetchone()
    events = [dict(r) for r in conn.execute(
        """SELECT e.kind, e.amount_minor, e.environment, e.note, e.created_at, u.full_name AS actor
           FROM procurement_finance_events e LEFT JOIN users u ON u.id=e.actor_user_id
           WHERE e.purchase_order_id=? ORDER BY e.id""", (po_id,))]
    fully_paid = bool(plan and plan["status"] == "approved" and parts and all(
        p["status"] == "cleared" or (p["status"] == "received" and p["method"] not in NEEDS_INSTRUMENT) for p in parts))
    return {
        "policy": pol,
        "plan": ({k: plan[k] for k in ("id", "status", "environment", "total_minor", "decision_note", "created_at",
                                       "submitted_at", "decided_at")} | {"parts": parts}) if plan else None,
        "approvals": [dict(r) for r in conn.execute(
            """SELECT a.round, a.created_at, u.full_name AS actor FROM procurement_plan_approvals a
               JOIN users u ON u.id=a.actor_user_id WHERE a.plan_id=? ORDER BY a.created_at""", (plan["id"],))] if plan else [],
        "collected_minor": collected, "refunded_minor": refunds,
        "fully_paid": fully_paid,
        "settlement": dict(settlement) if settlement else None,
        "ledger": events,
    }


def _validate_parts(conn, org: int, pol: dict, total: int, parts) -> list[dict]:
    max_parts = min(pol.get("max_parts") or 12, 12)
    if not isinstance(parts, list) or not 1 <= len(parts) <= max_parts:
        raise ValidationError(f"برنامه پرداخت طبق سیاست باید ۱ تا {max_parts} بخش داشته باشد")
    horizon = None
    if pol.get("max_term_days") is not None:
        horizon = (datetime.datetime.now(datetime.timezone.utc).date()
                   + datetime.timedelta(days=pol["max_term_days"])).isoformat()
    clean = []
    for p in parts:
        if not isinstance(p, dict):
            raise ValidationError("بخش پرداخت نامعتبر است")
        method, amount = p.get("method"), p.get("amount_minor")
        if method not in pol["methods"]:
            raise ValidationError(f"روش «{METHOD_FA.get(method, method)}» در سیاست پرداخت سازمان مجاز نیست")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValidationError("مبلغ هر بخش باید عدد صحیح مثبت باشد")
        due = pr_svc._date(p.get("due_date"))
        ref = pr_svc._text(p.get("reference"), "مرجع", 200)
        if method in NEEDS_INSTRUMENT and (not due or not ref):
            raise ValidationError("برای چک/برات، تاریخ سررسید و شماره/مرجع الزامی است")
        if due and horizon and due > horizon:
            raise ValidationError(f"سررسید از حداکثر مدت مجاز سیاست ({pol['max_term_days']} روز) فراتر است")
        clean.append({"method": method, "amount_minor": amount, "due_date": due, "reference": ref})
    if sum(p["amount_minor"] for p in clean) != total:
        raise ValidationError("جمع بخش‌های پرداخت باید دقیقاً برابر مبلغ سفارش باشد")
    credit = sum(p["amount_minor"] for p in clean if p["method"] == "credit")
    if credit:
        limit = pol["credit_limit_minor"]
        if limit is None:
            raise ValidationError("سقف اعتبار در سیاست مصوب تعریف نشده است")
        if credit_usage(conn, org, pol["environment"]) + credit > limit:
            raise ConflictError("مبلغ اعتباری از مانده سقف اعتبار مصوب سازمان بیشتر است")
    return clean


def create_plan(conn, *, org: int, po_id: int, actor: int, parts) -> dict:
    m = _member(conn, org, actor)
    po = _po(conn, org, po_id)
    if not (pr_svc._can_procure(m) or _is_finance(m)):
        raise PermissionError_("تعیین برنامه پرداخت برای نقش تدارکات یا مالی مجاز است")
    pol = policy(conn, org)
    if not pol:
        raise ConflictError("سیاست پرداخت سازمان تصویب نشده است؛ ثبت برنامه پرداخت ممکن نیست", code="policy_required")
    if po["status"] not in ("confirmed", "sent", "partially_received", "received"):
        raise ConflictError("برنامه پرداخت پس از تأیید سفارش قابل ثبت است")
    existing = _plan(conn, po_id)
    if existing and existing["status"] not in ("draft", "rejected"):
        raise ConflictError("برنامه پرداخت این سفارش ارسال یا تأیید شده است")
    total = po["grand_total_minor_snapshot"] or 0
    clean = _validate_parts(conn, org, pol, total, parts)
    if existing:
        conn.execute("DELETE FROM procurement_payment_parts WHERE plan_id=?", (existing["id"],))
        conn.execute("""UPDATE procurement_payment_plans SET status='draft', policy_id=?, environment=?, total_minor=?,
                        created_by_user_id=?, decided_by_user_id=NULL, decision_note=NULL, decided_at=NULL, submitted_at=NULL
                        WHERE id=?""", (pol["id"], pol["environment"], total, actor, existing["id"]))
        plan_id = existing["id"]
    else:
        plan_id = conn.execute(
            """INSERT INTO procurement_payment_plans (purchase_order_id, policy_id, environment, total_minor, created_by_user_id)
               VALUES (?,?,?,?,?)""", (po_id, pol["id"], pol["environment"], total, actor)).lastrowid
    for p in clean:
        conn.execute("""INSERT INTO procurement_payment_parts (plan_id, method, amount_minor, due_date, reference)
                        VALUES (?,?,?,?,?)""", (plan_id, p["method"], p["amount_minor"], p["due_date"], p["reference"]))
    _event(conn, org, po_id, pol["environment"], "plan_created", actor, total, plan_id,
           note="، ".join(f"{METHOD_FA[p['method']]} {p['amount_minor']}" for p in clean))
    return po_finance(conn, org, po_id)


def submit_plan(conn, *, org: int, po_id: int, actor: int) -> dict:
    _member(conn, org, actor)
    plan = _plan(conn, po_id)
    if not plan or plan["status"] != "draft":
        raise ConflictError("برنامه پرداخت پیش‌نویسی برای ارسال وجود ندارد")
    conn.execute("UPDATE procurement_payment_plans SET status='submitted', submitted_at=? WHERE id=?", (_now(), plan["id"]))
    _event(conn, org, po_id, plan["environment"], "plan_submitted", actor, plan["total_minor"], plan["id"])
    return po_finance(conn, org, po_id)


def decide_plan(conn, *, org: int, po_id: int, actor: int, action: str, note: str | None) -> dict:
    m = _member(conn, org, actor)
    if not _is_finance(m):
        raise PermissionError_("تأیید مالی فقط برای نقش مالی یا مدیر سازمان است")
    plan = _plan(conn, po_id)
    if not plan or plan["status"] != "submitted":
        raise ConflictError("برنامه پرداختی در انتظار تأیید مالی نیست")
    if plan["created_by_user_id"] == actor:
        raise PermissionError_("ثبت‌کننده برنامه پرداخت نمی‌تواند همان را تأیید کند (تفکیک وظایف)")
    if action not in ("approve", "reject"):
        raise ValidationError("اقدام باید تأیید یا رد باشد")
    note = pr_svc._text(note, "توضیح", 1000)
    if action == "reject" and not note:
        raise ValidationError("علت رد الزامی است")
    status = "approved" if action == "approve" else "rejected"
    pol = policy(conn, org)
    threshold = (pol or {}).get("dual_approval_threshold_minor")
    if action == "approve" and threshold is not None and plan["total_minor"] >= threshold:
        rnd = conn.execute("""SELECT COUNT(*) FROM procurement_finance_events WHERE plan_id=? AND kind='plan_submitted'""",
                           (plan["id"],)).fetchone()[0]
        prior = [r[0] for r in conn.execute("SELECT actor_user_id FROM procurement_plan_approvals WHERE plan_id=? AND round=?",
                                            (plan["id"], rnd))]
        if actor in prior:
            raise ConflictError("شما قبلاً این برنامه را تأیید کرده‌اید؛ تأیید دوم باید توسط فرد دیگری باشد", code="second_approver_required")
        conn.execute("INSERT INTO procurement_plan_approvals (plan_id, actor_user_id, round) VALUES (?,?,?)", (plan["id"], actor, rnd))
        if not prior:
            return po_finance(conn, org, po_id)
    conn.execute("""UPDATE procurement_payment_plans SET status=?, decided_by_user_id=?, decision_note=?, decided_at=?
                    WHERE id=?""", (status, actor, note, _now(), plan["id"]))
    _event(conn, org, po_id, plan["environment"], f"plan_{status}", actor, plan["total_minor"], plan["id"], note=note)
    return po_finance(conn, org, po_id)


PART_FLOW = {"received": ("pending",), "cleared": ("received",), "bounced": ("received",)}


def part_action(conn, *, org: int, po_id: int, part_id: int, actor: int, action: str, reference: str | None) -> dict:
    m = _member(conn, org, actor)
    if not _is_finance(m):
        raise PermissionError_("ثبت دریافت و وصول فقط برای نقش مالی است")
    plan = _plan(conn, po_id)
    if not plan or plan["status"] != "approved":
        raise ConflictError("برنامه پرداخت تأییدشده‌ای برای این سفارش وجود ندارد")
    part = conn.execute("SELECT * FROM procurement_payment_parts WHERE id=? AND plan_id=?", (part_id, plan["id"])).fetchone()
    if not part:
        raise NotFoundError("بخش پرداخت یافت نشد")
    if action not in PART_FLOW or part["status"] not in PART_FLOW[action]:
        raise ConflictError("این تغییر وضعیت برای بخش پرداخت مجاز نیست")
    if action in ("cleared", "bounced") and part["method"] not in NEEDS_INSTRUMENT:
        raise ConflictError("وصول/برگشت فقط برای چک یا برات است")
    reference = pr_svc._text(reference, "مرجع", 200)
    if action == "received" and part["method"] == "cash" and not reference:
        raise ValidationError("برای دریافت نقدی، شماره پیگیری/مرجع بانکی الزامی است")
    conn.execute("UPDATE procurement_payment_parts SET status=?, reference=COALESCE(?, reference), updated_at=? WHERE id=?",
                 (action, reference, _now(), part_id))
    _event(conn, org, po_id, plan["environment"], f"part_{action}", actor, part["amount_minor"], plan["id"], part_id,
           note=f"{METHOD_FA[part['method']]}{' · ' + reference if reference else ''}")
    return po_finance(conn, org, po_id)


def record_refund(conn, *, org: int, po_id: int, actor: int, amount, note) -> dict:
    m = _member(conn, org, actor)
    if not _is_finance(m):
        raise PermissionError_("ثبت بازپرداخت فقط برای نقش مالی است")
    fin = po_finance(conn, org, po_id)
    if not fin["plan"] or fin["plan"]["status"] != "approved":
        raise ConflictError("بدون برنامه پرداخت تأییدشده، بازپرداخت قابل ثبت نیست")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValidationError("مبلغ بازپرداخت نامعتبر است")
    if amount > fin["collected_minor"] - fin["refunded_minor"]:
        raise ConflictError("مبلغ بازپرداخت از مبلغ وصول‌شده بیشتر است")
    note = pr_svc._text(note, "علت", 1000, required=True)
    _event(conn, org, po_id, fin["plan"]["environment"], "refund_recorded", actor, amount, fin["plan"]["id"], note=note)
    return po_finance(conn, org, po_id)


def record_settlement(conn, *, org: int, po_id: int, actor: int, reference) -> dict:
    m = _member(conn, org, actor)
    if not _is_finance(m):
        raise PermissionError_("تسویه با تأمین‌کننده فقط برای نقش مالی است")
    po = _po(conn, org, po_id)
    fin = po_finance(conn, org, po_id)
    if fin["settlement"]:
        raise ConflictError("تسویه این سفارش قبلاً ثبت شده است")
    if not fin["fully_paid"]:
        raise ConflictError("تا وصول کامل بخش‌های پرداخت، تسویه ممکن نیست")
    open_corr = conn.execute("SELECT 1 FROM procurement_corrections WHERE purchase_order_id=? AND status='open'", (po_id,)).fetchone()
    if open_corr:
        raise ConflictError("مرجوعی/اصلاحیه باز وجود دارد")
    from app.services.procurement_coverage import deliveries_complete
    if not deliveries_complete(conn,po):
        raise ConflictError("تسویه پس از تحویل همه مقصدهای این سفارش قابل ثبت است")
    reference = pr_svc._text(reference, "مرجع تسویه", 200, required=True)
    amount = (po["grand_total_minor_snapshot"] or 0) - fin["refunded_minor"]
    env = fin["plan"]["environment"]
    conn.execute("""INSERT INTO procurement_supplier_settlements (purchase_order_id, environment, amount_minor, reference,
                    created_by_user_id) VALUES (?,?,?,?,?)""", (po_id, env, amount, reference, actor))
    _event(conn, org, po_id, env, "settlement_recorded", actor, amount, fin["plan"]["id"], note=reference)
    return po_finance(conn, org, po_id)


def summary(conn, *, org: int, actor: int) -> dict:
    m = _member(conn, org, actor)
    if not (_is_finance(m) or pr_svc._can_procure(m)):
        raise PermissionError_("خلاصه مالی برای نقش مالی، تدارکات یا مدیر سازمان است")
    pol = policy(conn, org)
    env = pol["environment"] if pol else None
    plans = [dict(r) for r in conn.execute(
        """SELECT p.*, o.po_number, o.purchase_request_id, o.grand_total_minor_snapshot AS po_total
           FROM procurement_payment_plans p JOIN purchase_orders o ON o.id=p.purchase_order_id
           WHERE o.organization_id=? ORDER BY p.id DESC""", (org,))]
    for p in plans:
        f = po_finance(conn, org, p["purchase_order_id"])
        p["collected_minor"], p["refunded_minor"], p["settled"] = f["collected_minor"], f["refunded_minor"], bool(f["settlement"])
    instruments = [dict(r) for r in conn.execute(
        """SELECT pp.*, o.po_number, p.environment FROM procurement_payment_parts pp
           JOIN procurement_payment_plans p ON p.id=pp.plan_id JOIN purchase_orders o ON o.id=p.purchase_order_id
           WHERE o.organization_id=? AND pp.method IN ('cheque','bill') AND pp.status IN ('pending','received')
           ORDER BY pp.due_date""", (org,))]
    receivable = sum(p["amount_minor"] for p in conn.execute(
        """SELECT pp.amount_minor FROM procurement_payment_parts pp JOIN procurement_payment_plans p ON p.id=pp.plan_id
           JOIN purchase_orders o ON o.id=p.purchase_order_id
           WHERE o.organization_id=? AND p.status='approved' AND pp.status IN ('pending','received')""", (org,)))
    ledger = [dict(r) for r in conn.execute(
        """SELECT e.kind, e.amount_minor, e.environment, e.note, e.created_at, o.po_number, u.full_name AS actor
           FROM procurement_finance_events e JOIN purchase_orders o ON o.id=e.purchase_order_id
           LEFT JOIN users u ON u.id=e.actor_user_id WHERE e.organization_id=? ORDER BY e.id DESC LIMIT 60""", (org,))]
    used = credit_usage(conn, org, env) if env else 0
    limit = pol["credit_limit_minor"] if pol else None
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    parts = [dict(r) for r in conn.execute(
        """SELECT pp.*, o.po_number, o.purchase_request_id, p.environment, p.status AS plan_status
           FROM procurement_payment_parts pp JOIN procurement_payment_plans p ON p.id=pp.plan_id
           JOIN purchase_orders o ON o.id=p.purchase_order_id WHERE o.organization_id=? ORDER BY pp.due_date, pp.id""", (org,))]
    for x in parts:
        x["overdue"] = bool(x["due_date"] and x["due_date"] < today and x["status"] in ("pending", "received")
                            and x["plan_status"] == "approved"
                            and not (x["status"] == "received" and x["method"] not in NEEDS_INSTRUMENT))
    payables, reconciliation = [], []
    for p in plans:
        if p["status"] != "approved":
            continue
        f = po_finance(conn, org, p["purchase_order_id"])
        po = conn.execute("SELECT status, grand_total_minor_snapshot FROM purchase_orders WHERE id=?", (p["purchase_order_id"],)).fetchone()
        from app.services.procurement_coverage import deliveries_complete
        delivered=deliveries_complete(conn,po)
        open_corr = conn.execute("SELECT COUNT(*) FROM procurement_corrections WHERE purchase_order_id=? AND status='open'",
                                 (p["purchase_order_id"],)).fetchone()[0]
        supplier = conn.execute("""SELECT s.display_name, s.provenance FROM purchase_orders o
                                   JOIN supplier_quotes q ON q.id=o.awarded_supplier_quote_id JOIN suppliers s ON s.id=q.supplier_id
                                   WHERE o.id=?""", (p["purchase_order_id"],)).fetchone()
        due = (po["grand_total_minor_snapshot"] or 0) - f["refunded_minor"]
        state = ("settled" if f["settlement"] else
                 "ready" if f["fully_paid"] and delivered and not open_corr else
                 "blocked_correction" if open_corr else
                 "awaiting_delivery" if f["fully_paid"] else "awaiting_collection")
        payables.append({"po_number": p["po_number"], "purchase_order_id": p["purchase_order_id"],
                         "purchase_request_id": p["purchase_request_id"], "environment": p["environment"],
                         "supplier": supplier["display_name"] if supplier else None,
                         "supplier_is_demo": bool(supplier and supplier["provenance"] != "real"),
                         "amount_minor": due, "state": state, "settlement": f["settlement"]})
        net = f["collected_minor"] - f["refunded_minor"]
        recon = ("reconciled" if f["settlement"] and f["settlement"]["amount_minor"] == net else
                 "mismatch" if f["settlement"] else
                 "collected" if f["fully_paid"] else
                 "partial" if f["collected_minor"] else "open")
        reconciliation.append({"po_number": p["po_number"], "purchase_request_id": p["purchase_request_id"],
                               "environment": p["environment"], "total_minor": p["total_minor"],
                               "collected_minor": f["collected_minor"], "refunded_minor": f["refunded_minor"],
                               "settled_minor": f["settlement"]["amount_minor"] if f["settlement"] else 0, "state": recon})
    refunds = [dict(r) for r in conn.execute(
        """SELECT e.amount_minor, e.environment, e.note, e.created_at, o.po_number, o.purchase_request_id, u.full_name AS actor
           FROM procurement_finance_events e JOIN purchase_orders o ON o.id=e.purchase_order_id
           LEFT JOIN users u ON u.id=e.actor_user_id WHERE e.organization_id=? AND e.kind='refund_recorded'
           ORDER BY e.id DESC""", (org,))]
    return {
        "today": today,
        "pending_approvals": [p for p in plans if p["status"] == "submitted"],
        "expected": [x for x in parts if x["plan_status"] == "approved" and x["status"] == "pending"],
        "received": [x for x in parts if x["status"] in ("received", "cleared")],
        "overdue": [x for x in parts if x["overdue"]],
        "refunds": refunds, "payables": payables, "reconciliation": reconciliation,
        "bank_integration": False,
        "policy": pol, "role": m["role"],
        "credit": {"limit_minor": limit, "used_minor": used, "remaining_minor": (limit - used) if limit is not None else None},
        "receivable_minor": receivable, "plans": plans, "instruments": instruments, "ledger": ledger,
    }
