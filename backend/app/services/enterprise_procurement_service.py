"""Enterprise procurement layer.

Builds on procurement_service (requests/approvals), rfq_service (RFQ/quotes)
and purchase_order_service (orders with immutable price snapshots):

  * configurable organization policy: employee submit rights + approval chain
  * procurement workspace (command-center projection of one request)
  * per-destination fulfillment, append-only receipts, returns/corrections
  * closure, internal notes, append-only timeline (procurement_events)
  * executive dashboard counters and "needs your action" items

No money moves here. Finance is a read-only projection of order snapshots and
the organization's (unapproved) payment policy; nothing is posted.
"""
from __future__ import annotations
from app.services import procurement_coverage

import datetime
import json

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import procurement_service as pr_svc
from app.services import procurement_finance_service as fin_svc

MEMBER_ROLES = ("employee", "organization_admin", "procurement_agent", "organization_finance")
PROCUREMENT_ROLES = ("requester", "approver", "procurement_officer")
DELIVERY_FLOW = ("confirmed", "preparing", "ready", "shipped", "partially_delivered", "delivered")
RECEIPT_KINDS = ("full", "partial", "shortage", "damaged", "mismatch")
PAYMENT_METHODS = (
    ("cash", "نقدی"), ("cheque", "چک"), ("organization_credit", "اعتبار سازمانی"), ("bill", "برات/تعهد"),
)
PO_AUDIT_TYPES = {"pr_created": "po_created", "pr_approved": "po_confirmed", "pr_submitted": "po_sent",
                  "pr_cancelled": "po_cancelled", "pr_completed": "po_completed"}
OPEN_PR = ("draft", "submitted", "under_review", "approved", "sourcing", "quoted", "awarded")
ACTIVE_PO = ("confirmed", "sent", "partially_received")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def record_event(conn, *, organization_id, purchase_request_id, actor_user_id, event_type,
                 payload=None, visibility="organization") -> None:
    conn.execute(
        """INSERT INTO procurement_events
           (organization_id, purchase_request_id, actor_user_id, event_type, visibility, payload_json)
           VALUES (?,?,?,?,?,?)""",
        (organization_id, purchase_request_id, actor_user_id, event_type, visibility,
         json.dumps(payload or {}, ensure_ascii=False)),
    )
    from app.services import procurement_notify
    procurement_notify.on_event(conn, organization_id=organization_id, purchase_request_id=purchase_request_id,
                                actor_user_id=actor_user_id, event_type=event_type, payload=payload)


# ── Policy ─────────────────────────────────────────────────────────────────────


def get_policy(conn, organization_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM organization_procurement_policies WHERE organization_id=?", (organization_id,)
    ).fetchone()
    if not row:
        # Defaults preserve pre-policy behaviour: employees may submit, single approval.
        return {"organization_id": organization_id, "employee_submit_allowed": True,
                "approval_chain": [], "version": 0, "updated_at": None}
    return {"organization_id": organization_id, "employee_submit_allowed": bool(row["employee_submit_allowed"]),
            "approval_chain": json.loads(row["approval_chain_json"]), "version": row["version"],
            "updated_at": row["updated_at"]}


def _validate_chain(chain) -> list[dict]:
    if not isinstance(chain, list) or len(chain) > 6:
        raise ValidationError("زنجیره تأیید باید حداکثر ۶ مرحله داشته باشد")
    clean, keys = [], set()
    for step in chain:
        if not isinstance(step, dict):
            raise ValidationError("مرحله تأیید نامعتبر است")
        key = pr_svc._text(step.get("key"), "کلید مرحله", 40, required=True)
        label = pr_svc._text(step.get("label"), "عنوان مرحله", 80, required=True)
        role, prole = step.get("role"), step.get("procurement_role")
        if (role is None) == (prole is None):
            raise ValidationError("هر مرحله دقیقاً یک نقش سازمانی یا نقش تدارکاتی لازم دارد")
        if role is not None and role not in MEMBER_ROLES:
            raise ValidationError("نقش سازمانی مرحله نامعتبر است")
        if prole is not None and prole not in PROCUREMENT_ROLES:
            raise ValidationError("نقش تدارکاتی مرحله نامعتبر است")
        if key in keys:
            raise ValidationError("کلید مرحله تکراری است")
        keys.add(key)
        clean.append({"key": key, "label": label, "role": role, "procurement_role": prole})
    return clean


def update_policy(conn, *, organization_id: int, actor_user_id: int, data: dict) -> dict:
    membership = pr_svc._get_membership(conn, actor_user_id, organization_id)
    if membership["role"] != "organization_admin":
        raise PermissionError_("فقط مدیر سازمان می‌تواند سیاست خرید را تغییر دهد")
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    current = get_policy(conn, organization_id)
    allowed = data.get("employee_submit_allowed", current["employee_submit_allowed"])
    if not isinstance(allowed, bool):
        raise ValidationError("مجوز ارسال کارمند باید بولی باشد")
    chain = _validate_chain(data.get("approval_chain", current["approval_chain"]))
    expected = data.get("version")
    if expected is not None and expected != current["version"]:
        raise ConflictError("سیاست توسط کاربر دیگری تغییر کرده است؛ صفحه را تازه کنید")
    version = current["version"] + 1
    conn.execute(
        """INSERT INTO organization_procurement_policies
           (organization_id, employee_submit_allowed, approval_chain_json, version, updated_by_user_id, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(organization_id) DO UPDATE SET employee_submit_allowed=excluded.employee_submit_allowed,
             approval_chain_json=excluded.approval_chain_json, version=excluded.version,
             updated_by_user_id=excluded.updated_by_user_id, updated_at=excluded.updated_at""",
        (organization_id, int(allowed), json.dumps(chain, ensure_ascii=False), version, actor_user_id, _now()),
    )
    record_event(conn, organization_id=organization_id, purchase_request_id=None, actor_user_id=actor_user_id,
                 event_type="policy_updated", payload={"version": version, "employee_submit_allowed": allowed,
                                                        "steps": [s["label"] for s in chain]})
    return get_policy(conn, organization_id)


def assert_submit_allowed(conn, organization_id: int, membership: dict) -> None:
    if get_policy(conn, organization_id)["employee_submit_allowed"]:
        return
    if membership["role"] == "employee" and membership.get("procurement_role") not in ("approver", "procurement_officer"):
        raise PermissionError_("طبق سیاست سازمان، کارمند نمی‌تواند درخواست را مستقیم ارسال کند؛ "
                               "پیش‌نویس ذخیره شد و مدیر سازمان می‌تواند آن را ارسال کند")


# ── Approval chain ─────────────────────────────────────────────────────────────


def _step_matches(step: dict, membership: dict) -> bool:
    return (membership["role"] == "organization_admin"
            or (step.get("role") is not None and membership["role"] == step["role"])
            or (step.get("procurement_role") is not None and membership.get("procurement_role") == step["procurement_role"]))


def _approvals(conn, pr_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT a.*, u.full_name AS approver_name FROM procurement_approvals a
           LEFT JOIN users u ON u.id=a.approver_user_id WHERE a.purchase_request_id=? ORDER BY a.id""",
        (pr_id,))]


def chain_progress(conn, pr_row, chain: list[dict]) -> list[dict]:
    approvals = _approvals(conn, pr_row["id"])
    done = [a for a in approvals if a["action"] == "approve"]
    rejected = next((a for a in approvals if a["action"] == "reject"), None)
    steps = chain or [{"key": "approval", "label": "تأیید سازمان", "role": None, "procurement_role": "approver"}]
    out = []
    for i, step in enumerate(steps):
        a = done[i] if i < len(done) else None
        if a:
            state = "approved"
        elif rejected and i == len(done):
            state, a = "rejected", rejected
        elif pr_row["status"] in ("submitted", "under_review") and i == len(done):
            state = "pending"
        else:
            state = "upcoming"
        out.append({"key": step["key"], "label": step["label"], "state": state,
                    "actor": a["approver_name"] if a else None, "at": a["approved_at"] if a else None,
                    "comment": a["reason"] if a else None})
    return out


def approve_with_chain(conn, pr_row, *, membership: dict, actor_user_id: int, organization_id: int,
                       action: str, reason: str | None, chain: list[dict]) -> None:
    if pr_row["status"] not in ("submitted", "under_review"):
        raise ConflictError(f"درخواست در وضعیت '{pr_row['status']}' قابل بررسی نیست")
    if action not in ("approve", "reject"):
        raise ValidationError("اقدام باید 'approve' یا 'reject' باشد")
    level = sum(1 for a in _approvals(conn, pr_row["id"]) if a["action"] == "approve")
    if level >= len(chain):
        raise ConflictError("همه مراحل تأیید انجام شده است")
    step = chain[level]
    if not _step_matches(step, membership):
        raise PermissionError_(f"این مرحله («{step['label']}») نیازمند نقش مربوط است")
    reason = pr_svc._text(reason, "توضیح", 2000)
    conn.execute(
        """INSERT INTO procurement_approvals
           (purchase_request_id, approver_user_id, approver_membership_id, action, reason, level)
           VALUES (?,?,?,?,?,?)""",
        (pr_row["id"], actor_user_id, membership["id"], action, reason, level + 1),
    )
    final = action == "reject" or level + 1 == len(chain)
    status = "rejected" if action == "reject" else ("approved" if final else "under_review")
    conn.execute("UPDATE purchase_requests SET status=?, updated_at=? WHERE id=?", (status, _now(), pr_row["id"]))
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_row["id"], actor_user_id=actor_user_id,
                 event_type="approval_step", payload={"step": step["label"], "action": action, "comment": reason})
    if final:
        pr_svc._audit(conn, organization_id=organization_id, actor_user_id=actor_user_id,
                      event_type="pr_approved" if action == "approve" else "pr_rejected",
                      entity_type="purchase_request", entity_id=pr_row["id"], details={"reason": reason})


# ── Workspace ──────────────────────────────────────────────────────────────────


def _pr_row(conn, organization_id: int, pr_id: int):
    row = conn.execute("SELECT * FROM purchase_requests WHERE id=? AND organization_id=?",
                       (pr_id, organization_id)).fetchone()
    if not row:
        raise NotFoundError("درخواست خرید یافت نشد")
    return row


def _can_read(membership: dict, pr_row, actor_user_id: int) -> bool:
    return pr_row["requester_user_id"] == actor_user_id or pr_svc._can_read_org_requests(membership)


def _item_details(conn, pr_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT i.*, mp.canonical_name_fa, mp.brand, mp.image_urls_json,
                  (SELECT p.sku FROM products p WHERE p.master_product_id=i.master_product_id AND p.is_active=1
                   ORDER BY p.id LIMIT 1) AS sku
           FROM purchase_request_items i LEFT JOIN master_products mp ON mp.id=i.master_product_id
           WHERE i.purchase_request_id=? ORDER BY i.id""", (pr_id,)).fetchall()
    out = []
    for r in rows:
        try:
            images = json.loads(r["image_urls_json"] or "[]")
        except ValueError:
            images = []
        out.append({"id": r["id"], "master_product_id": r["master_product_id"],
                    "name": r["canonical_name_fa"] or r["free_text_description"], "brand": r["brand"],
                    "image_url": images[0] if images else None, "sku": r["sku"], "quantity": r["quantity"],
                    "unit": r["unit"], "target_unit_price_minor": r["estimated_unit_price_minor"],
                    "target_specification": r["target_specification"], "acceptable_alternative": r["acceptable_alternative"],
                    "notes": r["notes"]})
    return out


def _supplier_state(inv, quote, rfq_items: int, rfq_row) -> str:
    if rfq_row["status"] == "draft":
        return "draft"
    if inv["status"] == "declined":
        return "declined"
    if quote:
        return "quoted" if quote["items_quoted"] >= rfq_items and not quote["short"] else "partially_quoted"
    if rfq_row["deadline_at"] and rfq_row["deadline_at"] < _now():
        return "expired"
    return "viewed" if inv["status"] == "viewed" else "sent"


def _rfqs(conn, pr_id: int) -> list[dict]:
    out = []
    for rfq in conn.execute("SELECT * FROM rfqs WHERE purchase_request_id=? ORDER BY id", (pr_id,)).fetchall():
        items = conn.execute("SELECT id, quantity_requested FROM rfq_items WHERE rfq_id=?", (rfq["id"],)).fetchall()
        wanted = {r["id"]: r["quantity_requested"] for r in items}
        suppliers = []
        for inv in conn.execute(
                """SELECT rs.*, s.display_name FROM rfq_suppliers rs JOIN suppliers s ON s.id=rs.supplier_id
                   WHERE rs.rfq_id=? ORDER BY rs.id""", (rfq["id"],)).fetchall():
            q = conn.execute(
                """SELECT * FROM supplier_quotes WHERE rfq_id=? AND supplier_id=?
                   ORDER BY id DESC LIMIT 1""", (rfq["id"], inv["supplier_id"])).fetchone()
            quote = None
            if q:
                qi = conn.execute("SELECT rfq_item_id, quantity_available FROM supplier_quote_items WHERE supplier_quote_id=?",
                                  (q["id"],)).fetchall()
                quote = {"id": q["id"], "quote_number": q["quote_number"], "status": q["status"],
                         "revision": q["revision"], "grand_total_minor": q["grand_total_minor"],
                         "items_quoted": len(qi),
                         "short": any(r["quantity_available"] < wanted.get(r["rfq_item_id"], 0) for r in qi)}
            suppliers.append({"supplier_id": inv["supplier_id"], "name": inv["display_name"],
                              "invited_at": inv["invited_at"], "viewed_at": inv["viewed_at"],
                              "decline_reason": inv["decline_reason"],
                              "state": _supplier_state(inv, quote, len(items), rfq), "quote": quote})
        out.append({"id": rfq["id"], "rfq_number": rfq["rfq_number"], "title": rfq["title"], "status": rfq["status"],
                    "deadline_at": rfq["deadline_at"], "notes": rfq["notes"], "items": len(items),
                    "suppliers": suppliers,
                    "quotes_received": sum(1 for s in suppliers if s["quote"])})
    return out


def _orders(conn, pr_id: int, destinations: list) -> list[dict]:
    out = []
    for po in conn.execute("SELECT * FROM purchase_orders WHERE purchase_request_id=? ORDER BY id", (pr_id,)).fetchall():
        sup = conn.execute("""SELECT s.display_name FROM supplier_quotes q JOIN suppliers s ON s.id=q.supplier_id
                              WHERE q.id=?""", (po["awarded_supplier_quote_id"],)).fetchone()
        states = {r["destination_index"]: dict(r) for r in conn.execute(
            "SELECT * FROM procurement_deliveries WHERE purchase_order_id=?", (po["id"],))}
        receipts = [dict(r) for r in conn.execute(
            "SELECT * FROM procurement_receipts WHERE purchase_order_id=? ORDER BY id", (po["id"],))]
        for r in receipts:
            r["quantities"] = json.loads(r.pop("quantities_json"))
        corrections = [dict(r) for r in conn.execute(
            "SELECT * FROM procurement_corrections WHERE purchase_order_id=? ORDER BY id", (po["id"],))]
        destinations = _destinations_for(conn, po)
        count = max(1, len(destinations))
        deliveries = []
        for idx in range(count):
            d = destinations[idx] if idx < len(destinations) else {}
            if po["destinations_json_snapshot"] is not None and destinations and not any(a["quantity"]>0 for a in d.get("allocations",[])):continue
            st = states.get(idx)
            deliveries.append({"destination_index": idx, "label": d.get("label") or d.get("city"),
                               "city": d.get("city"), "allocations": d.get("allocations",[]), "status": st["status"] if st else "confirmed" if po["status"] != "draft" else None,
                               "tracking_reference": st["tracking_reference"] if st else None,
                               "updated_at": st["updated_at"] if st else None,
                               "receipts": [r for r in receipts if r["destination_index"] == idx]})
        out.append({"id": po["id"], "po_number": po["po_number"], "status": po["status"],
                    "supplier": sup["display_name"] if sup else None, "rfq_id": po["rfq_id"],
                    "grand_total_minor": po["grand_total_minor_snapshot"],
                    "items_total_minor": po["total_items_minor_snapshot"],
                    "shipping_minor": po["shipping_cost_minor_snapshot"], "vat_minor": po["vat_amount_minor_snapshot"],
                    "discount_minor": po["discount_minor_snapshot"],
                    "items": [dict(i) for i in conn.execute(
                        """SELECT id, master_product_id, free_text_description, quantity, unit, unit_price_minor_snapshot,
                                  total_minor_snapshot FROM purchase_order_items WHERE purchase_order_id=? ORDER BY id""",
                        (po["id"],))],
                    "deliveries": deliveries, "corrections": corrections,
                    "documents": _documents(conn, po["id"]),
                    "finance": fin_svc.po_finance(conn, po["organization_id"], po["id"])})
    return out


def _documents(conn, po_id: int) -> list[dict]:
    from app.services import procurement_document_service as docs
    return docs.list_for_po(conn, po_id)


def _case(conn, pr_id: int):
    case = conn.execute(
        """SELECT c.*, u.full_name AS assignee_name FROM organization_operations_cases c
           LEFT JOIN users u ON u.id=c.assignee_user_id WHERE c.purchase_request_id=? ORDER BY c.id DESC LIMIT 1""",
        (pr_id,)).fetchone()
    if not case:
        return None
    wf = conn.execute("SELECT * FROM customer_workflows WHERE case_id=?", (case["id"],)).fetchone() \
        if _table_exists(conn, "customer_workflows") else None
    return {"id": case["id"], "status": case["status"], "assignee": case["assignee_name"],
            "next_action": wf["next_action"] if wf else None, "due_at": wf["due_at"] if wf else None,
            "blocked_reason": (wf["blocked_reason"] or None) if wf else None}


def _timeline(conn, pr_row, rfq_ids: list[int], po_ids: list[int], internal: bool) -> list[dict]:
    rows = []
    groups = [("purchase_request", [pr_row["id"]]), ("rfq", rfq_ids), ("purchase_order", po_ids), ("po", po_ids)]
    for entity, ids in groups:
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        for r in conn.execute(
                f"""SELECT l.event_type, l.details_json, l.occurred_at AS created_at, u.full_name FROM procurement_audit_log l
                    LEFT JOIN users u ON u.id=l.actor_user_id
                    WHERE l.organization_id=? AND l.entity_type=? AND l.entity_id IN ({marks})""",
                (pr_row["organization_id"], entity, *ids)):
            etype = r["event_type"]
            if entity in ("purchase_order", "po"):
                # purchase_order_service logs PO steps with pr_* types (audit CHECK constraint).
                etype = PO_AUDIT_TYPES.get(etype, etype)
            rows.append({"type": etype, "at": r["created_at"], "actor": r["full_name"],
                         "details": json.loads(r["details_json"] or "{}"), "source": "audit"})
    vis = "" if internal else "AND e.visibility='organization'"
    for r in conn.execute(
            f"""SELECT e.event_type, e.payload_json, e.visibility, e.created_at, u.full_name FROM procurement_events e
                LEFT JOIN users u ON u.id=e.actor_user_id WHERE e.purchase_request_id=? {vis}""", (pr_row["id"],)):
        rows.append({"type": r["event_type"], "at": r["created_at"], "actor": r["full_name"],
                     "details": json.loads(r["payload_json"]), "source": "event", "internal": r["visibility"] == "internal"})
    rows.sort(key=lambda e: e["at"] or "")
    return rows


def _next_action(pr_row, progress, rfqs, orders) -> dict:
    s = pr_row["status"]
    pending = next((p for p in progress if p["state"] == "pending"), None)
    if s in ('sourcing','quoted','awarded') and any(sp.get('quote') and sp['quote']['status']=='awarded' and not any(o['rfq_id']==r['id'] for o in orders) for r in rfqs for sp in r['suppliers']):
        return {'key':'create_order','label':'صدور سفارش از پیشنهاد منتخب باقیمانده','owner':'تدارکات'}
    if s == "draft":
        return {"key": "submit", "label": "ارسال درخواست برای بررسی", "owner": "درخواست‌دهنده"}
    if s in ("submitted", "under_review"):
        return {"key": "approve", "label": f"تأیید: {pending['label'] if pending else 'سازمان'}", "owner": pending["label"] if pending else "تأییدکننده"}
    if s == "approved":
        return {"key": "create_rfq", "label": "ایجاد استعلام از تأمین‌کنندگان", "owner": "تدارکات"}
    if s in ("sourcing", "quoted"):
        pending_rfqs=[r for r in rfqs if r['status'] not in ('awarded','cancelled')]
        if not pending_rfqs:
            return {'key':'create_rfq','label':'استعلام اقلام باقیمانده درخواست','owner':'تدارکات'}
        open_rfq = next((r for r in pending_rfqs if r["status"] in ("draft", "open")), None)
        if open_rfq and not open_rfq["suppliers"]:
            return {"key": "invite", "label": "دعوت از تأمین‌کنندگان", "owner": "تدارکات"}
        if any(r["quotes_received"] for r in pending_rfqs):
            return {"key": "compare", "label": "مقایسه و انتخاب پیشنهاد", "owner": "تدارکات"}
        return {"key": "await_quotes", "label": "در انتظار پیشنهاد تأمین‌کنندگان", "owner": "تأمین‌کننده"}
    if s == "awarded":
        if not orders:
            return {"key": "create_order", "label": "صدور سفارش از پیشنهاد منتخب", "owner": "تدارکات"}
        for po in (o for o in orders if o["status"] != "cancelled"):
            if po["status"] == "draft":
                return {"key": "confirm_order", "label": "تأیید سفارش", "owner": "تدارکات"}
            if po["status"] == "confirmed":
                return {"key": "send_order", "label": "ارسال سفارش به تأمین‌کننده", "owner": "تدارکات"}
            if any(c["status"] == "open" for c in po["corrections"]):
                return {"key": "resolve_correction", "label": "رسیدگی به مرجوعی/اصلاحیه", "owner": "تدارکات"}
            f = po["finance"]
            plan = f["plan"]
            if f["policy"] and not plan:
                return {"key": "payment_plan", "label": "تعیین برنامه پرداخت", "owner": "تدارکات/مالی"}
            if plan and plan["status"] in ("draft", "rejected"):
                return {"key": "payment_plan", "label": "ارسال برنامه پرداخت برای تأیید مالی", "owner": "تدارکات"}
            if plan and plan["status"] == "submitted":
                return {"key": "finance_approval", "label": "تأیید مالی برنامه پرداخت", "owner": "مالی"}
            if any(d["status"] != "delivered" for d in po["deliveries"]):
                return {"key": "fulfillment", "label": "پیگیری تحویل مقصدها", "owner": "تدارکات/تأمین‌کننده"}
            if f["policy"] and not f["fully_paid"]:
                return {"key": "collection", "label": "ثبت دریافت و وصول پرداخت", "owner": "مالی"}
            if f["policy"] and not f["settlement"]:
                return {"key": "settlement", "label": "تسویه با تأمین‌کننده", "owner": "مالی"}
        return {"key": "close", "label": "بستن پرونده", "owner": "تدارکات"}
    return {"key": "none", "label": "اقدامی باقی نمانده", "owner": None}


def _finance(conn, organization_id: int, orders: list[dict]) -> dict:
    pol = fin_svc.policy(conn, organization_id) if _table_exists(conn, "customer_payment_policies") else None
    status = "not_approved" if not pol else ("approved" if pol["environment"] == "production" else "test")
    total = sum(o["grand_total_minor"] or 0 for o in orders if o["status"] != "cancelled") if orders else None
    methods = []
    for k, label in PAYMENT_METHODS:
        key = "bill" if k == "bill" else k
        allowed = bool(pol and key in pol["methods"])
        methods.append({"key": k, "label": label, "enabled": allowed,
                        "reason": ("مجاز طبق سیاست" + (" (محیط آزمایشی)" if pol and pol["environment"] == "test" else "")) if allowed
                        else ("سیاست مالی سازمان هنوز تصویب نشده است" if not pol else "در سیاست مصوب مجاز نیست")})
    return {"policy_status": status, "environment": pol["environment"] if pol else None, "methods": methods,
            "order_total_minor": total, "posting": "records_only" if pol else "disabled",
            "note": ("ثبت‌ها صرفاً سابقهٔ تأیید مالی‌اند؛ هیچ درگاه یا تراکنش بانکی در این سامانه اجرا نمی‌شود."
                     + (" محیط آزمایشی (TEST) — بدون اثر مالی واقعی." if pol and pol["environment"] == "test" else ""))
            if pol else "هیچ تراکنش، مصرف اعتبار یا ثبت مالی واقعی انجام نمی‌شود."}


def workspace(conn, *, organization_id: int, pr_id: int, actor_user_id: int, _operations: bool = False) -> dict:
    # _operations: read-only view for holders of an internal operations mandate (checked by internal_workspace).
    membership = {"role": "operations", "procurement_role": None} if _operations else \
        pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    row = _pr_row(conn, organization_id, pr_id)
    if not _operations and not _can_read(membership, row, actor_user_id):
        raise NotFoundError("درخواست خرید یافت نشد")
    pr = pr_svc._pr_dict(row)
    org = conn.execute("SELECT display_name, currency FROM organizations WHERE id=?", (organization_id,)).fetchone()
    requester = conn.execute("SELECT full_name FROM users WHERE id=?", (row["requester_user_id"],)).fetchone()
    policy = get_policy(conn, organization_id)
    progress = chain_progress(conn, row, policy["approval_chain"])
    rfqs = _rfqs(conn, pr_id)
    orders = _orders(conn, pr_id, pr["destinations"])
    case = _case(conn, pr_id)
    internal = _operations or pr_svc._can_read_org_requests(membership)
    pending = next((p for p in progress if p["state"] == "pending"), None)
    chain = policy["approval_chain"] or [{"key": "approval", "label": "تأیید سازمان", "role": None, "procurement_role": "approver"}]
    step = chain[[p["key"] for p in progress].index(pending["key"])] if pending else None
    is_admin = membership["role"] == "organization_admin"
    return {
        "request": pr, "organization": {"id": organization_id, "name": org["display_name"], "currency": org["currency"]},
        "requester": requester["full_name"] if requester else None,
        "owner": (case or {}).get("assignee") or (requester["full_name"] if requester else None),
        "items": _item_details(conn, pr_id),
        "coverage": procurement_coverage.summary(conn,pr_id),
        "unallocated": pr_svc.unallocated(pr["destinations"], _item_details(conn, pr_id)),
        "allocation": pr_svc.allocation_summary(pr["destinations"], _item_details(conn, pr_id)),
        "destinations_hash": pr_svc.destinations_hash(conn.execute("SELECT destinations_json FROM purchase_requests WHERE id=?", (pr_id,)).fetchone()[0]),
        "approval": {"steps": progress, "configured": bool(policy["approval_chain"])},
        "rfqs": rfqs, "orders": orders, "case": case, "finance": _finance(conn, organization_id, orders),
        "next_action": _next_action(row, progress, rfqs, orders),
        "sla": {"needed_by_date": row["needed_by_date"],
                "rfq_deadline": min((r["deadline_at"] for r in rfqs if r["deadline_at"] and r["status"] == "open"), default=None),
                "case_due_at": (case or {}).get("due_at")},
        "documents": {"uploads_enabled": True, "reason": "PDF، JPEG، PNG یا WebP تا ۵ مگابایت"},
        "timeline": _timeline(conn, row, [r["id"] for r in rfqs], [o["id"] for o in orders], internal),
        "permissions": {
            "role": membership["role"], "procurement_role": membership.get("procurement_role"),
            "can_submit": row["status"] == "draft" and (row["requester_user_id"] == actor_user_id or is_admin),
            "can_approve": bool(step and _step_matches(step, membership)),
            "can_procure": pr_svc._can_procure(membership), "can_read_internal": internal,
            "can_receive": row["requester_user_id"] == actor_user_id or pr_svc._can_procure(membership) or is_admin,
            "can_cancel": row["status"] not in ("awarded", "completed", "cancelled")
                          and (row["requester_user_id"] == actor_user_id or is_admin),
        },
    }


# ── Notes ──────────────────────────────────────────────────────────────────────


def add_note(conn, *, organization_id: int, pr_id: int, actor_user_id: int, text: str) -> None:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    _pr_row(conn, organization_id, pr_id)
    if not pr_svc._can_read_org_requests(membership):
        raise PermissionError_("یادداشت داخلی فقط برای نقش‌های تدارکات، مالی و مدیر سازمان است")
    text = pr_svc._text(text, "یادداشت", 2000, required=True)
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_id, actor_user_id=actor_user_id,
                 event_type="note", payload={"text": text}, visibility="internal")


# ── Fulfillment / receipt / correction / closure ───────────────────────────────


def _po(conn, organization_id: int, po_id: int):
    po = conn.execute("SELECT * FROM purchase_orders WHERE id=? AND organization_id=?", (po_id, organization_id)).fetchone()
    if not po:
        raise NotFoundError("سفارش خرید یافت نشد")
    return po


def _destinations_for(conn, po) -> list:
    from app.services.procurement_coverage import order_destinations
    return order_destinations(conn,po)


def _dest_index(conn, po, idx) -> int:
    count = max(1, len(_destinations_for(conn, po)))
    if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < count:
        raise ValidationError("مقصد نامعتبر است")
    from app.services.procurement_coverage import delivery_indexes
    if po["destinations_json_snapshot"] is not None and idx not in delivery_indexes(_destinations_for(conn,po)):raise ValidationError("این مقصد در این سفارش قلمی ندارد")
    return idx


def update_delivery(conn, *, organization_id: int, po_id: int, destination_index, actor_user_id: int,
                    status: str, tracking_reference: str | None = None) -> None:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    if not pr_svc._can_procure(membership):
        raise PermissionError_("به‌روزرسانی ارسال فقط برای نقش تدارکات مجاز است")
    po = _po(conn, organization_id, po_id)
    if po["status"] not in ACTIVE_PO:
        raise ConflictError("وضعیت ارسال فقط برای سفارش تأییدشده قابل تغییر است")
    idx = _dest_index(conn, po, destination_index)
    if status not in DELIVERY_FLOW:
        raise ValidationError("وضعیت ارسال نامعتبر است")
    tracking_reference = pr_svc._text(tracking_reference, "کد رهگیری", 120)
    cur = conn.execute("SELECT status FROM procurement_deliveries WHERE purchase_order_id=? AND destination_index=?",
                       (po_id, idx)).fetchone()
    before = cur["status"] if cur else "confirmed"
    if DELIVERY_FLOW.index(status) < DELIVERY_FLOW.index(before):
        raise ConflictError("وضعیت ارسال نمی‌تواند به عقب برگردد")
    conn.execute(
        """INSERT INTO procurement_deliveries (purchase_order_id, destination_index, status, tracking_reference,
               updated_by_user_id, updated_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(purchase_order_id, destination_index) DO UPDATE SET status=excluded.status,
               tracking_reference=COALESCE(excluded.tracking_reference, procurement_deliveries.tracking_reference),
               updated_by_user_id=excluded.updated_by_user_id, updated_at=excluded.updated_at""",
        (po_id, idx, status, tracking_reference, actor_user_id, _now()))
    record_event(conn, organization_id=organization_id, purchase_request_id=po["purchase_request_id"],
                 actor_user_id=actor_user_id, event_type="delivery_status",
                 payload={"po": po["po_number"], "destination_index": idx, "from": before, "to": status,
                          "tracking_reference": tracking_reference})


def record_receipt(conn, *, organization_id: int, po_id: int, actor_user_id: int, data: dict) -> dict:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    po = _po(conn, organization_id, po_id)
    pr_row = _pr_row(conn, organization_id, po["purchase_request_id"]) if po["purchase_request_id"] else None
    if not (pr_svc._can_procure(membership) or membership["role"] == "organization_admin"
            or (pr_row and pr_row["requester_user_id"] == actor_user_id)):
        raise PermissionError_("ثبت رسید برای این سفارش مجاز نیست")
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    idx = _dest_index(conn, po, data.get("destination_index"))
    kind = data.get("kind")
    if kind not in RECEIPT_KINDS:
        raise ValidationError("نوع رسید نامعتبر است")
    cur = conn.execute("SELECT status FROM procurement_deliveries WHERE purchase_order_id=? AND destination_index=?",
                       (po_id, idx)).fetchone()
    if not cur or cur["status"] not in ("shipped", "partially_delivered", "delivered"):
        raise ConflictError("رسید فقط پس از ارسال محموله این مقصد قابل ثبت است")
    receiver = pr_svc._text(data.get("receiver_name"), "نام تحویل‌گیرنده", 200, required=True)
    notes = pr_svc._text(data.get("notes"), "توضیح", 2000)
    if kind != "full" and not notes:
        raise ValidationError("برای تحویل ناقص، کسری، آسیب یا مغایرت توضیح الزامی است")
    quantities = data.get("quantities") or []
    if not isinstance(quantities, list) or any(
            not isinstance(q, dict) or type(q.get("item_index")) is not int or type(q.get("quantity")) is not int
            or q["quantity"] < 0 for q in quantities):
        raise ValidationError("تعداد دریافتی نامعتبر است")
    destinations=_destinations_for(conn,po)
    expected={a['item_index']:a['quantity'] for a in (destinations[idx].get('allocations',[]) if destinations else [])}
    if not destinations and po['purchase_request_id']:
        from app.services.procurement_coverage import requested,quote_lines,link
        original=requested(conn,po['purchase_request_id']);indexes={p['id']:i for i,p in enumerate(original)}
        expected={indexes[link(line,original)['id']]:line['committed_quantity'] for line in quote_lines(conn,po['awarded_supplier_quote_id'])}
    seen=set()
    for q in quantities:
        if q['item_index'] in seen or q['item_index'] not in expected or q['quantity']>expected[q['item_index']]:
            raise ValidationError('قلم تکراری، خارج از سفارش یا مقدار بیش از تخصیص مقصد است')
        seen.add(q['item_index'])
    if kind=='full' and quantities and ({q['item_index']:q['quantity'] for q in quantities}!=expected):
        raise ValidationError('مقدار رسید کامل باید با تخصیص واقعی این سفارش و مقصد برابر باشد')

    rid = conn.execute(
        """INSERT INTO procurement_receipts (purchase_order_id, destination_index, kind, receiver_name,
               quantities_json, notes, created_by_user_id) VALUES (?,?,?,?,?,?,?)""",
        (po_id, idx, kind, receiver, json.dumps(quantities), notes, actor_user_id)).lastrowid
    new_status = "delivered" if kind == "full" else "partially_delivered"
    if DELIVERY_FLOW.index(new_status) > DELIVERY_FLOW.index(cur["status"]):
        conn.execute("""UPDATE procurement_deliveries SET status=?, updated_by_user_id=?, updated_at=?
                        WHERE purchase_order_id=? AND destination_index=?""", (new_status, actor_user_id, _now(), po_id, idx))
    if po["status"] == "sent":
        conn.execute("UPDATE purchase_orders SET status='partially_received', updated_at=? WHERE id=?", (_now(), po_id))
    record_event(conn, organization_id=organization_id, purchase_request_id=po["purchase_request_id"],
                 actor_user_id=actor_user_id, event_type="receipt",
                 payload={"po": po["po_number"], "destination_index": idx, "kind": kind, "receiver": receiver, "notes": notes})
    return {"id": rid}


def open_correction(conn, *, organization_id: int, po_id: int, actor_user_id: int, data: dict) -> dict:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    po = _po(conn, organization_id, po_id)
    pr_row = _pr_row(conn, organization_id, po["purchase_request_id"]) if po["purchase_request_id"] else None
    if not (pr_svc._can_procure(membership) or membership["role"] == "organization_admin"
            or (pr_row and pr_row["requester_user_id"] == actor_user_id)):
        raise PermissionError_("ثبت مرجوعی/اصلاحیه برای این سفارش مجاز نیست")
    if not isinstance(data, dict) or data.get("kind") not in ("return", "correction"):
        raise ValidationError("نوع درخواست باید مرجوعی یا اصلاحیه باشد")
    receipt_id = data.get("receipt_id")
    if receipt_id is not None and not conn.execute(
            "SELECT 1 FROM procurement_receipts WHERE id=? AND purchase_order_id=?", (receipt_id, po_id)).fetchone():
        raise ValidationError("رسید مرتبط یافت نشد")
    reason = pr_svc._text(data.get("reason"), "علت", 2000, required=True)
    cid = conn.execute(
        """INSERT INTO procurement_corrections (purchase_order_id, receipt_id, kind, reason, created_by_user_id)
           VALUES (?,?,?,?,?)""", (po_id, receipt_id, data["kind"], reason, actor_user_id)).lastrowid
    record_event(conn, organization_id=organization_id, purchase_request_id=po["purchase_request_id"],
                 actor_user_id=actor_user_id, event_type="correction_opened",
                 payload={"po": po["po_number"], "kind": data["kind"], "reason": reason})
    return {"id": cid}


def resolve_correction(conn, *, organization_id: int, po_id: int, correction_id: int, actor_user_id: int,
                       resolution: str) -> None:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    if not pr_svc._can_procure(membership):
        raise PermissionError_("رسیدگی به مرجوعی فقط برای نقش تدارکات مجاز است")
    po = _po(conn, organization_id, po_id)
    row = conn.execute("SELECT * FROM procurement_corrections WHERE id=? AND purchase_order_id=?",
                       (correction_id, po_id)).fetchone()
    if not row:
        raise NotFoundError("مرجوعی/اصلاحیه یافت نشد")
    if row["status"] != "open":
        raise ConflictError("این مورد قبلاً رسیدگی شده است")
    resolution = pr_svc._text(resolution, "نتیجه رسیدگی", 2000, required=True)
    conn.execute("""UPDATE procurement_corrections SET status='resolved', resolution=?, resolved_by_user_id=?,
                    resolved_at=? WHERE id=?""", (resolution, actor_user_id, _now(), correction_id))
    record_event(conn, organization_id=organization_id, purchase_request_id=po["purchase_request_id"],
                 actor_user_id=actor_user_id, event_type="correction_resolved",
                 payload={"po": po["po_number"], "kind": row["kind"], "resolution": resolution})


def close_request(conn, *, organization_id: int, pr_id: int, actor_user_id: int) -> None:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    if not (pr_svc._can_procure(membership) or membership["role"] == "organization_admin"):
        raise PermissionError_("بستن پرونده فقط برای تدارکات یا مدیر سازمان مجاز است")
    row = _pr_row(conn, organization_id, pr_id)
    if row["status"] != "awarded":
        raise ConflictError("فقط پرونده دارای سفارش صادرشده قابل بستن است")
    from app.services.procurement_coverage import assert_complete_orders
    assert_complete_orders(conn,pr_id)
    orders = _orders(conn, pr_id, json.loads(row["destinations_json"]))
    live = [o for o in orders if o["status"] != "cancelled"]
    if not live:
        raise ConflictError("سفارشی برای بستن پرونده وجود ندارد")
    for o in live:
        if any(d["status"] != "delivered" for d in o["deliveries"]):
            raise ConflictError("همه مقصدها باید تحویل کامل شده باشند")
        if any(c["status"] == "open" for c in o["corrections"]):
            raise ConflictError("مرجوعی/اصلاحیه باز وجود دارد")
        if o["finance"]["policy"] and not o["finance"]["settlement"]:
            raise ConflictError("تا تسویه مالی سفارش، پرونده قابل بستن نیست")
    now = _now()
    for o in live:
        if o["status"] != "received":
            conn.execute("UPDATE purchase_orders SET status='received', updated_at=? WHERE id=?", (now, o["id"]))
    conn.execute("UPDATE purchase_requests SET status='completed', updated_at=? WHERE id=?", (now, pr_id))
    record_event(conn, organization_id=organization_id, purchase_request_id=pr_id, actor_user_id=actor_user_id,
                 event_type="closed", payload={"orders": [o["po_number"] for o in live],
                                               "finance": "settled" if all(o["finance"]["settlement"] for o in live)
                                               else "untracked_no_policy"})


# ── Dashboard ──────────────────────────────────────────────────────────────────


def dashboard(conn, *, organization_id: int, actor_user_id: int) -> dict:
    membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
    wide = pr_svc._can_read_org_requests(membership)
    scope, params = ("", [organization_id]) if wide else (" AND requester_user_id=?", [organization_id, actor_user_id])
    reqs = conn.execute(f"SELECT * FROM purchase_requests WHERE organization_id=?{scope} ORDER BY id DESC", params).fetchall()
    ids = [r["id"] for r in reqs]
    marks = ",".join("?" * len(ids)) or "NULL"
    rfqs = conn.execute(f"SELECT * FROM rfqs WHERE purchase_request_id IN ({marks})", ids).fetchall() if ids else []
    rfq_ids = [r["id"] for r in rfqs]
    rmarks = ",".join("?" * len(rfq_ids)) or "NULL"
    quotes = conn.execute(
        f"""SELECT COUNT(*) FROM supplier_quotes WHERE status='submitted' AND rfq_id IN ({rmarks})""",
        rfq_ids).fetchone()[0] if rfq_ids else 0
    pos = conn.execute(f"SELECT * FROM purchase_orders WHERE purchase_request_id IN ({marks})", ids).fetchall() if ids else []
    po_ids = [p["id"] for p in pos if p["status"] in ACTIVE_PO]
    undelivered = 0
    for p in pos:
        if p["status"] in ACTIVE_PO:
            dests = max(1, len(json.loads(next((r["destinations_json"] for r in reqs if r["id"] == p["purchase_request_id"]), "[]"))))
            done = conn.execute("""SELECT COUNT(*) FROM procurement_deliveries WHERE purchase_order_id=?
                                   AND status='delivered'""", (p["id"],)).fetchone()[0]
            undelivered += dests - done
    policy = get_policy(conn, organization_id)
    chain = policy["approval_chain"] or [{"key": "approval", "label": "تأیید سازمان", "role": None, "procurement_role": "approver"}]
    actions = []
    for r in reqs:
        if r["status"] in ("submitted", "under_review"):
            done = sum(1 for a in _approvals(conn, r["id"]) if a["action"] == "approve")
            if done < len(chain) and _step_matches(chain[done], membership):
                actions.append({"request_id": r["id"], "request_number": r["request_number"], "title": r["title"],
                                "action": f"تأیید: {chain[done]['label']}", "needed_by_date": r["needed_by_date"]})
        elif r["status"] == "draft" and r["requester_user_id"] == actor_user_id:
            actions.append({"request_id": r["id"], "request_number": r["request_number"], "title": r["title"],
                            "action": "ارسال پیش‌نویس", "needed_by_date": r["needed_by_date"]})
        elif pr_svc._can_procure(membership) and r["status"] in ("approved", "sourcing", "quoted", "awarded"):
            ws_rfqs = _rfqs(conn, r["id"])
            nxt = _next_action(r, chain_progress(conn, r, policy["approval_chain"]), ws_rfqs,
                               _orders(conn, r["id"], json.loads(r["destinations_json"])))
            if nxt["key"] not in ("await_quotes", "none"):
                actions.append({"request_id": r["id"], "request_number": r["request_number"], "title": r["title"],
                                "action": nxt["label"], "needed_by_date": r["needed_by_date"]})
    actions.sort(key=lambda a: a["needed_by_date"] or "9999")
    return {
        "counts": {
            "open_requests": sum(1 for r in reqs if r["status"] in OPEN_PR),
            "awaiting_quotes": sum(1 for r in rfqs if r["status"] == "open"),
            "quotes_received": quotes,
            "needs_approval": sum(1 for r in reqs if r["status"] in ("submitted", "under_review")),
            "active_orders": len(po_ids),
            "awaiting_delivery": undelivered,
        },
        "finance": {"policy_status": _finance(conn, organization_id, [])["policy_status"], "due_items": None},
        "actions": actions[:8], "scope": "organization" if wide else "own",
    }


# ── Case list (search / filter) ────────────────────────────────────────────

def list_cases(conn, *, organization_id: int | None, actor_user_id: int, q: str | None = None, status: str | None = None,
               stage: str | None = None, platform: bool = False) -> dict:
    """Case rows derived from the authoritative request/RFQ/order/finance records (no separate status store).
    platform=True is only reachable through the platform-admin endpoint."""
    if platform:
        wide = True
        where, params = ["1=1"], []
        if organization_id:
            where.append("pr.organization_id=?"); params.append(organization_id)
    else:
        membership = pr_svc._assert_org_member(conn, actor_user_id, organization_id)
        wide = pr_svc._can_read_org_requests(membership)
        where, params = ["pr.organization_id=?"], [organization_id]
    if not wide:
        where.append("pr.requester_user_id=?"); params.append(actor_user_id)
    if status:
        where.append("pr.status=?"); params.append(status)
    if q and q.strip():
        like = "%" + q.strip() + "%"
        where.append("(pr.request_number LIKE ? OR pr.title LIKE ?)"); params += [like, like]
    rows = conn.execute(f"""SELECT pr.*, u.full_name AS requester, o.display_name AS organization_name FROM purchase_requests pr
                            LEFT JOIN users u ON u.id=pr.requester_user_id JOIN organizations o ON o.id=pr.organization_id
                            WHERE {' AND '.join(where)} ORDER BY pr.id DESC LIMIT 200""", params).fetchall()
    policies = {}
    out = []
    for r in rows:
        dests = json.loads(r["destinations_json"])
        rfqs, orders = _rfqs(conn, r["id"]), _orders(conn, r["id"], dests)
        policy = policies.setdefault(r["organization_id"], get_policy(conn, r["organization_id"]))
        nxt = _next_action(r, chain_progress(conn, r, policy["approval_chain"]), rfqs, orders)
        po = next((o for o in orders if o["status"] != "cancelled"), None)
        case = _case(conn, r["id"])
        blocked = None
        if r["status"] == "rejected":
            blocked = "درخواست رد شده است"
        elif po and any(c["status"] == "open" for c in po["corrections"]):
            blocked = "مرجوعی/اصلاحیه باز"
        elif po and po["finance"]["plan"] and po["finance"]["plan"]["status"] == "rejected":
            blocked = "برنامه پرداخت رد شده است"
        elif r["status"] in ("sourcing", "quoted") and rfqs and not any(x["quotes_received"] for x in rfqs) and \
                all(x["deadline_at"] and x["deadline_at"] < _now() for x in rfqs):
            blocked = "مهلت استعلام بدون پیشنهاد گذشت"
        item = {
            "id": r["id"], "organization_id": r["organization_id"], "organization": r["organization_name"],
            "suppliers": sorted({sp["name"] for x in rfqs for sp in x["suppliers"]}),
            "request_number": r["request_number"], "title": r["title"], "status": r["status"],
            "requester": r["requester"], "owner": (case or {}).get("assignee") or r["requester"],
            "created_at": r["created_at"],
            "needed_by_date": r["needed_by_date"], "urgency": r["urgency"], "updated_at": r["updated_at"],
            "next_action": nxt, "blocked_reason": blocked,
            "rfqs": len(rfqs), "quotes": sum(x["quotes_received"] for x in rfqs),
            "order": {"po_number": po["po_number"], "status": po["status"], "supplier": po["supplier"],
                      "delivered": sum(1 for d in po["deliveries"] if d["status"] == "delivered"),
                      "destinations": len(po["deliveries"]),
                      "payment": (po["finance"]["plan"] or {}).get("status"),
                      "settled": bool(po["finance"]["settlement"])} if po else None,
        }
        if stage and nxt["key"] != stage and not (stage == "blocked" and blocked):
            continue
        out.append(item)
    return {"items": out, "scope": "organization" if wide else "own"}


# ── Supplier side: identity, RFQ/quote outcomes, orders, fulfillment, receivable ──

SUPPLIER_DELIVERY_STEPS = ("preparing", "ready", "shipped")


def _supplier(conn, user_id: int):
    from app.services.access_admin_service import current_supplier_id
    sid = current_supplier_id(conn, user_id)
    row = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone() if sid else None
    if not row:
        raise PermissionError_("حساب تأمین‌کننده برای این کاربر یافت نشد")
    return row


def _supplier_po(conn, supplier_id: int, po_id: int):
    po = conn.execute(
        """SELECT o.* FROM purchase_orders o JOIN supplier_quotes q ON q.id=o.awarded_supplier_quote_id
           WHERE o.id=? AND q.supplier_id=?""", (po_id, supplier_id)).fetchone()
    if not po:
        raise NotFoundError("سفارش یافت نشد")
    return po


def supplier_overview(conn, *, user_id: int) -> dict:
    sup = _supplier(conn, user_id)
    rfqs = [dict(r) for r in conn.execute(
        """SELECT r.id, r.rfq_number, r.title, r.status AS rfq_status, r.deadline_at, rs.status AS invitation,
                  q.status AS quote_status, q.revision, q.grand_total_minor
           FROM rfq_suppliers rs JOIN rfqs r ON r.id=rs.rfq_id
           LEFT JOIN supplier_quotes q ON q.rfq_id=r.id AND q.supplier_id=rs.supplier_id
           WHERE rs.supplier_id=? ORDER BY r.id DESC""", (sup["id"],))]
    orders = []
    for po in conn.execute(
            """SELECT o.* FROM purchase_orders o JOIN supplier_quotes q ON q.id=o.awarded_supplier_quote_id
               WHERE q.supplier_id=? ORDER BY o.id DESC""", (sup["id"],)).fetchall():
        dests = _destinations_for(conn, po)
        states = {r["destination_index"]: dict(r) for r in conn.execute(
            "SELECT * FROM procurement_deliveries WHERE purchase_order_id=?", (po["id"],))}
        org = conn.execute("SELECT display_name FROM organizations WHERE id=?", (po["organization_id"],)).fetchone()
        settlement = conn.execute("SELECT amount_minor, reference, environment, created_at FROM procurement_supplier_settlements WHERE purchase_order_id=?",
                                  (po["id"],)).fetchone()
        orders.append({
            "id": po["id"], "po_number": po["po_number"], "status": po["status"], "organization": org["display_name"] if org else None,
            "grand_total_minor": po["grand_total_minor_snapshot"],
            "deliveries": [{"destination_index": i, "label": (dests[i].get("label") or dests[i].get("city")) if i < len(dests) else None,
                            "city": dests[i].get("city") if i < len(dests) else None,
                            "status": (states.get(i) or {}).get("status") or ("confirmed" if po["status"] != "draft" else None),
                            "tracking_reference": (states.get(i) or {}).get("tracking_reference")}
                           for i in range(max(1, len(dests)))],
            "receivable": {"settled": bool(settlement), **(dict(settlement) if settlement else {"amount_minor": po["grand_total_minor_snapshot"]})},
            "documents": _documents(conn, po["id"]),
            "receipts": [dict(r) for r in conn.execute(
                "SELECT destination_index, kind, receiver_name, created_at FROM procurement_receipts WHERE purchase_order_id=? ORDER BY id",
                (po["id"],))],
            "disputes": [dict(r) for r in conn.execute(
                """SELECT id, kind, reason, status, resolution, created_at, resolved_at FROM procurement_corrections
                   WHERE purchase_order_id=? ORDER BY id DESC""", (po["id"],))],
        })
    from app.services.access_admin_service import supplier_accounts
    q = lambda sql: conn.execute(sql, (sup["id"],)).fetchone()[0]
    readiness = [
        {"key": "status", "label": "وضعیت فعال", "ok": sup["status"] == "active"},
        {"key": "onboarding", "label": "تأیید احراز/قرارداد", "ok": sup["onboarding_stage"] == "approved"},
        {"key": "users", "label": "کاربر عملیاتی فعال",
         "ok": q("SELECT COUNT(*) FROM supplier_users WHERE supplier_id=? AND status='active'") > 0},
        {"key": "locations", "label": "انبار/محل ارسال فعال",
         "ok": q("SELECT COUNT(*) FROM supplier_locations WHERE supplier_id=? AND status='active'") > 0},
        {"key": "bank", "label": "اطلاعات بانکی ثبت‌شده", "ok": bool(sup["sheba"])},
        {"key": "offers", "label": "پیشنهاد کالا با قیمت و موجودی تأییدشده (۲۴ ساعت)",
         "ok": q("""SELECT COUNT(*) FROM seller_offers WHERE supplier_id=? AND status='active'
                    AND last_price_confirmed_at >= datetime('now','-24 hours')
                    AND last_inventory_confirmed_at >= datetime('now','-24 hours')""") > 0},
    ]
    return {"supplier": {"id": sup["id"], "name": sup["display_name"], "status": sup["status"],
                         "onboarding_stage": sup["onboarding_stage"], "provenance": sup["provenance"],
                         "is_demo": sup["provenance"] != "real"},
            "accounts": supplier_accounts(conn, user_id), "readiness": readiness,
            "offers": {"total": q("SELECT COUNT(*) FROM seller_offers WHERE supplier_id=?"),
                       "confirmed": q("""SELECT COUNT(*) FROM seller_offers WHERE supplier_id=?
                                         AND last_price_confirmed_at IS NOT NULL AND last_inventory_confirmed_at IS NOT NULL""")},
            "rfqs": rfqs, "orders": orders}


def supplier_update_delivery(conn, *, user_id: int, po_id: int, destination_index, status: str,
                             tracking_reference: str | None) -> None:
    """Supplier reports preparation/dispatch for its own order; delivery acceptance stays with the buyer."""
    sup = _supplier(conn, user_id)
    po = _supplier_po(conn, sup["id"], po_id)
    if status not in SUPPLIER_DELIVERY_STEPS:
        raise ValidationError("تأمین‌کننده فقط آماده‌سازی، آماده ارسال یا ارسال را ثبت می‌کند")
    if po["status"] not in ("sent", "partially_received"):
        raise ConflictError("سفارش هنوز برای تأمین‌کننده ارسال نشده است")
    idx = _dest_index(conn, po, destination_index)
    cur = conn.execute("SELECT status FROM procurement_deliveries WHERE purchase_order_id=? AND destination_index=?",
                       (po_id, idx)).fetchone()
    before = cur["status"] if cur else "confirmed"
    if DELIVERY_FLOW.index(status) <= DELIVERY_FLOW.index(before):
        raise ConflictError("وضعیت ارسال نمی‌تواند تکرار شود یا به عقب برگردد")
    tracking_reference = pr_svc._text(tracking_reference, "کد رهگیری", 120)
    if status == "shipped" and not tracking_reference:
        raise ValidationError("برای ثبت ارسال، کد رهگیری الزامی است")
    conn.execute(
        """INSERT INTO procurement_deliveries (purchase_order_id, destination_index, status, tracking_reference,
               updated_by_user_id, updated_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(purchase_order_id, destination_index) DO UPDATE SET status=excluded.status,
               tracking_reference=COALESCE(excluded.tracking_reference, procurement_deliveries.tracking_reference),
               updated_by_user_id=excluded.updated_by_user_id, updated_at=excluded.updated_at""",
        (po_id, idx, status, tracking_reference, user_id, _now()))
    record_event(conn, organization_id=po["organization_id"], purchase_request_id=po["purchase_request_id"],
                 actor_user_id=user_id, event_type="delivery_status",
                 payload={"po": po["po_number"], "destination_index": idx, "from": before, "to": status,
                          "tracking_reference": tracking_reference, "by": "supplier"})


def internal_workspace(conn, *, organization_id: int, pr_id: int, actor_user_id: int) -> dict:
    """Operations staff view of a case: managers see any case of their organizations, agents only assigned ones."""
    from app.services import organization_operations_service as ops
    caps = ops.authorize(conn, organization_id, actor_user_id)
    case = conn.execute("SELECT * FROM organization_operations_cases WHERE organization_id=? AND purchase_request_id=?",
                        (organization_id, pr_id)).fetchone()
    if "case_manager" not in caps and (not case or case["assignee_user_id"] != actor_user_id):
        raise NotFoundError("درخواست خرید یافت نشد")
    ws = workspace(conn, organization_id=organization_id, pr_id=pr_id, actor_user_id=actor_user_id, _operations=True)
    ws["operations"] = {"capabilities": sorted(caps), "case": dict(case) if case else None}
    return ws
