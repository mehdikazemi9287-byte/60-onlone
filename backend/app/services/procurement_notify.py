"""In-app notifications for organization procurement and supplier events.

One fan-out point, called from the procurement audit/event writers, so every recorded transition that needs
someone's action (approve, quote, ship) or changes their case reaches them in /notifications. Notifications are
written in the same transaction as the event: if the business change rolls back, so does the notice. The actor
is never notified about their own action. Text only states recorded facts; links point to the real pages.
"""
from __future__ import annotations

from app.services.commerce_ops_service import notify


def _pr(conn, pr_id):
    return conn.execute("SELECT id, organization_id, requester_user_id, request_number, title FROM purchase_requests WHERE id=?",
                        (pr_id,)).fetchone() if pr_id else None


def _approvers(conn, org_id) -> set[int]:
    rows = conn.execute("""SELECT user_id FROM organization_memberships WHERE organization_id=? AND status='active'
                           AND (role='organization_admin' OR procurement_role='approver')""", (org_id,)).fetchall()
    return {r["user_id"] for r in rows}


def _buyers(conn, org_id) -> set[int]:
    rows = conn.execute("""SELECT user_id FROM organization_memberships WHERE organization_id=? AND status='active'
                           AND (role IN ('organization_admin','procurement_agent') OR procurement_role='procurement_officer')""",
                        (org_id,)).fetchall()
    return {r["user_id"] for r in rows}


def _supplier_users(conn, supplier_id) -> set[int]:
    users = {r["user_id"] for r in conn.execute("SELECT user_id FROM supplier_users WHERE supplier_id=? AND status='active'", (supplier_id,))}
    legacy = conn.execute("SELECT user_id FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if legacy and legacy["user_id"]:
        users.add(legacy["user_id"])
    return users


def _send(conn, users, actor, kind, title, body, link):
    for uid in sorted(u for u in users if u and u != actor):
        notify(conn, uid, kind, title, body, link)


def _org_link(pr):
    return f"/organization/requests/{pr['id']}?org={pr['organization_id']}"


def on_audit(conn, *, organization_id, actor_user_id, event_type, entity_type, entity_id, details=None) -> None:
    details = details or {}
    if entity_type == "purchase_request":
        pr = _pr(conn, entity_id)
        if not pr:
            return
        if event_type == "pr_submitted":
            _send(conn, _approvers(conn, organization_id), actor_user_id, "procurement", f"درخواست {pr['request_number']} منتظر تأیید است",
                  pr["title"], _org_link(pr))
        elif event_type == "pr_approved":
            _send(conn, {pr["requester_user_id"]} | _buyers(conn, organization_id), actor_user_id, "procurement",
                  f"درخواست {pr['request_number']} تأیید شد", pr["title"], _org_link(pr))
        elif event_type == "pr_cancelled":
            _send(conn, {pr["requester_user_id"]}, actor_user_id, "procurement", f"درخواست {pr['request_number']} لغو یا رد شد",
                  details.get("reason") or pr["title"], _org_link(pr))
    elif entity_type == "rfq":
        rfq = conn.execute("SELECT id, rfq_number, purchase_request_id FROM rfqs WHERE id=?", (entity_id,)).fetchone()
        if not rfq:
            return
        pr = _pr(conn, rfq["purchase_request_id"])
        if event_type == "supplier_invited" and details.get("supplier_id"):
            _send(conn, _supplier_users(conn, details["supplier_id"]), actor_user_id, "supplier_rfq",
                  f"استعلام جدید {rfq['rfq_number']}", "برای ثبت پیشنهاد قیمت، استعلام را باز کنید.", f"/supplier/rfqs/{rfq['id']}")
        elif event_type == "quote_awarded" and details.get("winning_quote_id"):
            quotes = conn.execute("SELECT id, supplier_id, status FROM supplier_quotes WHERE rfq_id=?", (rfq["id"],)).fetchall()
            for q in quotes:
                if q["id"] == details["winning_quote_id"]:
                    _send(conn, _supplier_users(conn, q["supplier_id"]), actor_user_id, "supplier_rfq",
                          f"پیشنهاد شما برای {rfq['rfq_number']} انتخاب شد", "سفارش خرید پس از صدور برای شما ارسال می‌شود.", f"/supplier/rfqs/{rfq['id']}")
                elif q["status"] in ("submitted", "rejected"):
                    _send(conn, _supplier_users(conn, q["supplier_id"]), actor_user_id, "supplier_rfq",
                          f"پیشنهاد شما برای {rfq['rfq_number']} انتخاب نشد", None, f"/supplier/rfqs/{rfq['id']}")
            if pr:
                _send(conn, {pr["requester_user_id"]}, actor_user_id, "procurement", f"تأمین‌کننده درخواست {pr['request_number']} انتخاب شد",
                      pr["title"], _org_link(pr))
    elif entity_type == "purchase_order":
        po = conn.execute("""SELECT po.id, po.po_number, po.purchase_request_id, q.supplier_id FROM purchase_orders po
                             JOIN supplier_quotes q ON q.id = po.awarded_supplier_quote_id WHERE po.id=?""", (entity_id,)).fetchone()
        if not po:
            return
        pr = _pr(conn, po["purchase_request_id"])
        if event_type == "pr_submitted":  # purchase order sent to the supplier
            _send(conn, _supplier_users(conn, po["supplier_id"]), actor_user_id, "supplier_order",
                  f"سفارش خرید {po['po_number']} برای شما ارسال شد", "آماده‌سازی و ارسال را در پنل تأمین‌کننده ثبت کنید.", "/supplier")
            if pr:
                _send(conn, {pr["requester_user_id"]}, actor_user_id, "procurement", f"سفارش خرید {po['po_number']} صادر شد",
                      pr["title"], _org_link(pr))
        elif event_type == "pr_cancelled":
            _send(conn, _supplier_users(conn, po["supplier_id"]), actor_user_id, "supplier_order",
                  f"سفارش خرید {po['po_number']} لغو شد", details.get("reason"), "/supplier")
            if pr:
                _send(conn, {pr["requester_user_id"]}, actor_user_id, "procurement", f"سفارش خرید {po['po_number']} لغو شد",
                      details.get("reason") or pr["title"], _org_link(pr))


EVENT_TEXT = {
    "delivery_status": "وضعیت تحویل درخواست {n} به‌روز شد",
    "receipt": "دریافت کالای درخواست {n} ثبت شد",
    "closed": "درخواست {n} بسته شد",
    "request_split": "درخواست {n} برای تأمین محلی تقسیم شد",
}


def on_event(conn, *, organization_id, purchase_request_id, actor_user_id, event_type, payload=None) -> None:
    if event_type not in EVENT_TEXT:
        return
    pr = _pr(conn, purchase_request_id)
    if pr:
        _send(conn, {pr["requester_user_id"]}, actor_user_id, "procurement", EVENT_TEXT[event_type].format(n=pr["request_number"]),
              pr["title"], _org_link(pr))


def on_quote_submitted(conn, *, rfq_id, supplier_id) -> None:
    rfq = conn.execute("SELECT id, organization_id, rfq_number, purchase_request_id FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    pr = _pr(conn, rfq["purchase_request_id"]) if rfq else None
    if not pr:
        return
    name = conn.execute("SELECT display_name FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    actors = _supplier_users(conn, supplier_id)
    for uid in sorted(_buyers(conn, rfq["organization_id"]) - actors):
        notify(conn, uid, "procurement", f"پیشنهاد قیمت جدید برای {rfq['rfq_number']}",
               f"{name['display_name'] if name else 'تأمین‌کننده'} برای «{pr['title']}» پیشنهاد ثبت کرد.", _org_link(pr))
