"""Organizational Procurement API — Phase 4.

Purchase Requests:
  POST /api/v1/orgs/<org_id>/procurement/requests               — create PR
  GET  /api/v1/orgs/<org_id>/procurement/requests               — list PRs
  GET  /api/v1/orgs/<org_id>/procurement/requests/<pr_id>       — get PR
  POST /api/v1/orgs/<org_id>/procurement/requests/<pr_id>/submit
  POST /api/v1/orgs/<org_id>/procurement/requests/<pr_id>/approve
  POST /api/v1/orgs/<org_id>/procurement/requests/<pr_id>/cancel

RFQs:
  POST /api/v1/orgs/<org_id>/procurement/rfqs                   — create RFQ
  GET  /api/v1/orgs/<org_id>/procurement/rfqs                   — list RFQs
  GET  /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>          — get RFQ
  POST /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>/invite   — invite supplier
  POST /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>/open
  POST /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>/close
  POST /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>/award
  GET  /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>/quotes   — list quotes
  GET  /api/v1/orgs/<org_id>/procurement/rfqs/<rfq_id>/comparison

Purchase Orders:
  POST /api/v1/orgs/<org_id>/procurement/purchase-orders        — create PO
  GET  /api/v1/orgs/<org_id>/procurement/purchase-orders        — list POs
  GET  /api/v1/orgs/<org_id>/procurement/purchase-orders/<po_id>
  POST /api/v1/orgs/<org_id>/procurement/purchase-orders/<po_id>/confirm
  POST /api/v1/orgs/<org_id>/procurement/purchase-orders/<po_id>/send
  POST /api/v1/orgs/<org_id>/procurement/purchase-orders/<po_id>/acknowledge
  POST /api/v1/orgs/<org_id>/procurement/purchase-orders/<po_id>/complete
  POST /api/v1/orgs/<org_id>/procurement/purchase-orders/<po_id>/cancel

Supplier (RFQ response):
  GET  /api/v1/supplier/rfqs                            — list invited RFQs
  POST /api/v1/supplier/rfqs/<rfq_id>/quotes            — submit quote

Connector admin:
  POST /api/v1/admin/connectors                         — create connector account
  GET  /api/v1/admin/connectors                         — list connector accounts
  GET  /api/v1/admin/connectors/<id>                    — get connector account
  POST /api/v1/admin/connectors/<id>/sync/inventory     — simulate inventory sync
  POST /api/v1/admin/connectors/<id>/sync/prices        — simulate price sync

Freshness:
  GET  /api/v1/offers/<offer_id>/freshness              — check offer freshness
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ValidationError, PermissionError_, NotFoundError
import app.services.procurement_service as pr_svc
import app.services.rfq_service as rfq_svc
import app.services.purchase_order_service as po_svc
import app.services.connector_service as conn_svc
import app.services.freshness_service as fresh_svc


def _acting_supplier(conn, user_id):
    from app.services.access_admin_service import current_supplier_id
    sid = current_supplier_id(conn, user_id)
    return {"id": sid} if sid else None

bp = Blueprint("procurement", __name__, url_prefix="/api/v1")


# ── Purchase Requests ─────────────────────────────────────────────────────────


@bp.post("/orgs/<int:org_id>/procurement/requests")
@require_auth()
def create_purchase_request(org_id: int):
    import hashlib, json
    from app.core.errors import ConflictError

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    if any(key in data for key in ("attachments", "uploads", "files", "file")):
        raise ValidationError("بارگذاری امن فایل هنوز فعال نیست")
    key = request.headers.get("Idempotency-Key")
    if key is not None and (not key.strip() or len(key) > 128):
        raise ValidationError("شناسه درخواست نامعتبر است")
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    endpoint = request.path
    db = get_db()
    with db.write_transaction() as conn:
        pr_svc._assert_org_member(conn, current_user()["id"], org_id)
        pr_svc._assert_org_accepts_intake(conn, org_id)
        if key:
            old = conn.execute(
                "SELECT * FROM idempotency_keys WHERE key=? AND user_id=? AND endpoint=?",
                (key, current_user()["id"], endpoint),
            ).fetchone()
            if old:
                if old["request_hash"] != digest:
                    raise ConflictError(
                        "شناسه برای درخواست متفاوت استفاده شده است", code="idempotency_conflict"
                    )
                return jsonify(json.loads(old["response_json"])), 200
        pr = pr_svc.create_purchase_request(
            conn,
            organization_id=org_id,
            requester_user_id=current_user()["id"],
            title=data.get("title", ""),
            description=data.get("description"),
            needed_by_date=data.get("needed_by_date"),
            delivery_province=data.get("delivery_province"),
            delivery_city=data.get("delivery_city"),
            delivery_address=data.get("delivery_address"),
            budget_minor=data.get("budget_minor"),
            cost_center=data.get("cost_center"),
            project_code=data.get("project_code"),
            urgency=data.get("urgency", "normal"),
            notes=data.get("notes"),
            items=data.get("items"),
            destinations=data.get("destinations"),
            substitution_policy=data.get("substitution_policy", "require_approval"),
        )
        if key:
            conn.execute(
                "INSERT INTO idempotency_keys(key,user_id,endpoint,request_hash,status_code,response_json) VALUES (?,?,?,?,?,?)",
                (
                    key,
                    current_user()["id"],
                    endpoint,
                    digest,
                    201,
                    json.dumps({"purchase_request": pr}, ensure_ascii=False),
                ),
            )
    return jsonify({"purchase_request": pr}), 201


@bp.get("/orgs/<int:org_id>/procurement/requests")
@require_auth()
def list_purchase_requests(org_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        prs = pr_svc.list_purchase_requests(
            conn,
            organization_id=org_id,
            actor_user_id=current_user()["id"],
            status=request.args.get("status"),
            requester_user_id=request.args.get("requester_user_id", type=int),
        )
    return jsonify({"items": prs, "total": len(prs)})


@bp.get("/orgs/<int:org_id>/procurement/requests/<int:pr_id>")
@require_auth()
def get_purchase_request(org_id: int, pr_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        pr = pr_svc.get_purchase_request(
            conn, pr_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_request": pr})


@bp.post("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/submit")
@require_auth()
def submit_purchase_request(org_id: int, pr_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        pr = pr_svc.submit_purchase_request(
            conn, pr_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_request": pr})


@bp.post("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/approve")
@require_auth()
def approve_purchase_request(org_id: int, pr_id: int):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("approve", "reject"):
        raise ValidationError("اقدام باید 'approve' یا 'reject' باشد")
    db = get_db()
    with db.write_transaction() as conn:
        pr = pr_svc.approve_purchase_request(
            conn,
            pr_id,
            actor_user_id=current_user()["id"],
            organization_id=org_id,
            action=action,
            reason=data.get("reason"),
        )
    return jsonify({"purchase_request": pr})


@bp.post("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/cancel")
@require_auth()
def cancel_purchase_request(org_id: int, pr_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        pr = pr_svc.cancel_purchase_request(
            conn, pr_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_request": pr})


# ── RFQs ──────────────────────────────────────────────────────────────────────


@bp.post("/orgs/<int:org_id>/procurement/rfqs")
@require_auth()
def create_rfq(org_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    with db.write_transaction() as conn:
        rfq = rfq_svc.create_rfq(
            conn,
            organization_id=org_id,
            purchase_request_id=data.get("purchase_request_id"),
            actor_user_id=current_user()["id"],
            title=data.get("title", ""),
            deadline_at=data.get("deadline_at"),
            notes=data.get("notes"),
            items=data.get("items"),
        )
    return jsonify({"rfq": rfq}), 201


@bp.get("/orgs/<int:org_id>/procurement/rfqs")
@require_auth()
def list_rfqs(org_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        rfqs = rfq_svc.list_rfqs(
            conn,
            organization_id=org_id,
            actor_user_id=current_user()["id"],
            status=request.args.get("status"),
            purchase_request_id=request.args.get("purchase_request_id", type=int),
        )
    return jsonify({"items": rfqs, "total": len(rfqs)})


@bp.get("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>")
@require_auth()
def get_rfq(org_id: int, rfq_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        rfq = rfq_svc.get_rfq(
            conn, rfq_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"rfq": rfq})


@bp.post("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>/invite")
@require_auth()
def invite_supplier_to_rfq(org_id: int, rfq_id: int):
    data = request.get_json(silent=True) or {}
    supplier_id = data.get("supplier_id")
    if not supplier_id:
        raise ValidationError("شناسه تأمین‌کننده الزامی است")
    db = get_db()
    with db.write_transaction() as conn:
        result = rfq_svc.invite_supplier_to_rfq(
            conn,
            rfq_id,
            int(supplier_id),
            actor_user_id=current_user()["id"],
            organization_id=org_id,
        )
    return jsonify(result), 201


@bp.post("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>/open")
@require_auth()
def open_rfq(org_id: int, rfq_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        rfq = rfq_svc.open_rfq(
            conn, rfq_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"rfq": rfq})


@bp.post("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>/close")
@require_auth()
def close_rfq(org_id: int, rfq_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        rfq = rfq_svc.close_rfq(
            conn, rfq_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"rfq": rfq})


@bp.post("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>/award")
@require_auth()
def award_rfq(org_id: int, rfq_id: int):
    data = request.get_json(silent=True) or {}
    winning_quote_id = data.get("winning_quote_id")
    if not winning_quote_id:
        raise ValidationError("شناسه قیمت‌نامه برنده الزامی است")
    db = get_db()
    with db.write_transaction() as conn:
        result = rfq_svc.award_rfq(
            conn,
            rfq_id,
            actor_user_id=current_user()["id"],
            organization_id=org_id,
            winning_quote_id=int(winning_quote_id),
            reason=data.get("reason"),
        )
    return jsonify(result)


@bp.get("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>/quotes")
@require_auth()
def list_rfq_quotes(org_id: int, rfq_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        quotes = rfq_svc.list_supplier_quotes(
            conn, rfq_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"items": quotes, "total": len(quotes)})


@bp.get("/orgs/<int:org_id>/procurement/rfqs/<int:rfq_id>/comparison")
@require_auth()
def get_rfq_comparison(org_id: int, rfq_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        comparison = rfq_svc.get_rfq_comparison(
            conn, rfq_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify(comparison)


# ── Purchase Orders ───────────────────────────────────────────────────────────


def _quote_id(value):
    if isinstance(value,bool) or not isinstance(value,(str,int)) or (isinstance(value,str) and (len(value)>19 or not value.isascii() or not value.isdigit())):raise ValidationError('شناسه قیمت‌نامه نامعتبر است')
    number=int(value)
    if not 0<number<2**63:raise ValidationError('شناسه قیمت‌نامه نامعتبر است')
    return number

@bp.get('/orgs/<int:org_id>/procurement/purchase-orders/allocation-preview')
@require_auth()
def allocation_preview(org_id):
    qid=_quote_id(request.args.get('supplier_quote_id'))
    with get_db().read_transaction() as conn:
        return jsonify(po_svc.allocation_preview(conn,organization_id=org_id,actor_user_id=current_user()['id'],supplier_quote_id=qid))

@bp.post("/orgs/<int:org_id>/procurement/purchase-orders")
@require_auth()
def create_purchase_order(org_id: int):
    data = request.get_json(silent=True) or {}
    if not isinstance(data,dict):raise ValidationError('بدنه درخواست نامعتبر است')
    supplier_quote_id = data.get("supplier_quote_id")
    if not supplier_quote_id:
        raise ValidationError("شناسه قیمت‌نامه الزامی است")
    db = get_db()
    with db.write_transaction() as conn:
        po = po_svc.create_purchase_order(
            conn,
            organization_id=org_id,
            actor_user_id=current_user()["id"],
            supplier_quote_id=_quote_id(supplier_quote_id),
            delivery_address=data.get("delivery_address"),
            notes=data.get("notes"),
            vat_bps=data.get("vat_bps", 900),
            destination_allocations=data.get('destination_allocations'),
        )
    return jsonify({"purchase_order": po}), 201


@bp.get("/orgs/<int:org_id>/procurement/purchase-orders")
@require_auth()
def list_purchase_orders(org_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        pos = po_svc.list_purchase_orders(
            conn,
            organization_id=org_id,
            actor_user_id=current_user()["id"],
            status=request.args.get("status"),
            supplier_id=request.args.get("supplier_id", type=int),
        )
    return jsonify({"items": pos, "total": len(pos)})


@bp.get("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>")
@require_auth()
def get_purchase_order(org_id: int, po_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        po = po_svc.get_purchase_order(
            conn, po_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_order": po})


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/confirm")
@require_auth()
def confirm_purchase_order(org_id: int, po_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        po = po_svc.confirm_purchase_order(
            conn, po_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_order": po})


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/send")
@require_auth()
def send_purchase_order(org_id: int, po_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        po = po_svc.send_purchase_order(
            conn, po_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_order": po})


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/acknowledge")
@require_auth()
def acknowledge_purchase_order(org_id: int, po_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        po = po_svc.acknowledge_purchase_order(
            conn, po_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_order": po})


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/complete")
@require_auth()
def complete_purchase_order(org_id: int, po_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        po = po_svc.complete_purchase_order(
            conn, po_id, actor_user_id=current_user()["id"], organization_id=org_id
        )
    return jsonify({"purchase_order": po})


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/cancel")
@require_auth()
def cancel_purchase_order(org_id: int, po_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    with db.write_transaction() as conn:
        po = po_svc.cancel_purchase_order(
            conn,
            po_id,
            actor_user_id=current_user()["id"],
            organization_id=org_id,
            reason=data.get("reason"),
        )
    return jsonify({"purchase_order": po})


# ── Supplier-facing: view invited RFQs and submit quotes ──────────────────────


@bp.get("/supplier/rfqs")
@require_auth()
def supplier_list_rfqs():
    """Supplier views their invited RFQs. Uses current user's supplier association."""
    db = get_db()
    user_id = current_user()["id"]
    with db.read_transaction() as conn:
        # Find supplier id associated with this user
        sup_row = _acting_supplier(conn, user_id)
        if not sup_row:
            return jsonify({"items": [], "total": 0})
        rfqs = rfq_svc.list_supplier_invited_rfqs(conn, sup_row["id"])
    return jsonify({"items": rfqs, "total": len(rfqs)})


@bp.get("/supplier/quotes/<int:quote_id>")
@require_auth()
def supplier_get_quote(quote_id: int):
    """Supplier views their own quote. Returns 403 if the quote belongs to another supplier."""
    user_id = current_user()["id"]
    db = get_db()
    with db.read_transaction() as conn:
        sup_row = _acting_supplier(conn, user_id)
        if not sup_row:
            raise PermissionError_("حساب تأمین‌کننده برای این کاربر یافت نشد")
        quote = conn.execute(
            "SELECT sq.*, sq.total_items_minor, sq.shipping_cost_minor "
            "FROM supplier_quotes sq WHERE sq.id=?",
            (quote_id,),
        ).fetchone()
        if not quote:
            raise NotFoundError("قیمت‌پیشنهادی یافت نشد")
        if quote["supplier_id"] != sup_row["id"]:
            raise PermissionError_("دسترسی به اطلاعات تأمین‌کننده دیگر مجاز نیست")
        items = conn.execute(
            "SELECT * FROM supplier_quote_items WHERE supplier_quote_id=?", (quote_id,)
        ).fetchall()
    return jsonify({"quote": {**dict(quote), "items": [dict(i) for i in items]}})


@bp.post("/supplier/rfqs/<int:rfq_id>/quotes")
@require_auth()
def supplier_submit_quote(rfq_id: int):
    """Supplier submits a quote for an invited RFQ."""
    import hashlib,json
    from app.core.errors import ConflictError
    data = request.get_json(silent=True)
    if not isinstance(data,dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    key=request.headers.get("Idempotency-Key")
    if key is not None and (not key.strip() or len(key)>128):
        raise ValidationError("شناسه درخواست نامعتبر است")
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    user_id = current_user()["id"]
    db = get_db()
    with db.write_transaction() as conn:
        sup_row = _acting_supplier(conn, user_id)
        if not sup_row:
            raise ValidationError("حساب تأمین‌کننده برای این کاربر یافت نشد")
        if key:
            old=conn.execute("SELECT * FROM idempotency_keys WHERE key=? AND user_id=? AND endpoint=?",(key,user_id,request.path)).fetchone()
            if old:
                if old["request_hash"]!=digest:
                    raise ConflictError("شناسه برای پیشنهاد متفاوت استفاده شده است",code="idempotency_conflict")
                return jsonify(json.loads(old["response_json"])),200
        quote = rfq_svc.submit_supplier_quote(
            conn,
            rfq_id,
            supplier_id=sup_row["id"],
            items=data.get("items", []),
            shipping_cost_minor=data.get("shipping_cost_minor", 0),
            payment_terms=data.get("payment_terms"),
            warranty_terms=data.get("warranty_terms"),
            delivery_lead_days=data.get("delivery_lead_days"),
            validity_days=data.get("validity_days"),
            notes=data.get("notes"),
        )
        if key:
            conn.execute("INSERT INTO idempotency_keys(key,user_id,endpoint,request_hash,status_code,response_json) VALUES (?,?,?,?,?,?)",
                         (key,user_id,request.path,digest,201,json.dumps({"quote":quote},ensure_ascii=False)))
    return jsonify({"quote": quote}), 201


# ── Connector admin ───────────────────────────────────────────────────────────


@bp.post("/admin/connectors")
@require_auth("admin")
def create_connector():
    data = request.get_json(silent=True) or {}
    db = get_db()
    with db.write_transaction() as conn:
        account = conn_svc.create_connector_account(
            conn,
            name=data.get("name", ""),
            connector_type=data.get("connector_type", ""),
            supplier_id=data.get("supplier_id"),
            organization_id=data.get("organization_id"),
            credential_ref=data.get("credential_ref"),
            config=data.get("config"),
        )
    return jsonify(account), 201


@bp.get("/admin/connectors")
@require_auth("admin")
def list_connectors():
    db = get_db()
    with db.read_transaction() as conn:
        accounts = conn_svc.list_connector_accounts(
            conn, supplier_id=request.args.get("supplier_id", type=int)
        )
    return jsonify({"items": accounts, "total": len(accounts)})


@bp.get("/admin/connectors/<int:account_id>")
@require_auth("admin")
def get_connector(account_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        account = conn_svc.get_connector_account(conn, account_id)
    return jsonify(account)


@bp.post("/admin/connectors/<int:account_id>/sync/inventory")
@require_auth("admin")
def simulate_inventory_sync(account_id: int):
    data = request.get_json(silent=True) or {}
    updates = data.get("updates", [])
    if not isinstance(updates, list):
        raise ValidationError("'updates' باید آرایه باشد")
    db = get_db()
    with db.write_transaction() as conn:
        result = conn_svc.simulate_inventory_sync(
            conn, connector_account_id=account_id, updates=updates
        )
    return jsonify(result)


@bp.post("/admin/connectors/<int:account_id>/sync/prices")
@require_auth("admin")
def simulate_price_sync(account_id: int):
    data = request.get_json(silent=True) or {}
    updates = data.get("updates", [])
    if not isinstance(updates, list):
        raise ValidationError("'updates' باید آرایه باشد")
    db = get_db()
    with db.write_transaction() as conn:
        result = conn_svc.simulate_price_sync(
            conn, connector_account_id=account_id, updates=updates
        )
    return jsonify(result)


# ── Freshness ─────────────────────────────────────────────────────────────────


@bp.get("/offers/<int:offer_id>/freshness")
@require_auth()
def check_offer_freshness(offer_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        result = fresh_svc.check_offer_freshness(conn, offer_id)
    return jsonify(
        {
            "offer_id": result.offer_id,
            "status": result.status.value,
            "price_age_seconds": result.price_age_seconds,
            "inventory_age_seconds": result.inventory_age_seconds,
            "policy_name": result.policy_name,
            "stale_action": result.stale_action,
            "expired_action": result.expired_action,
            "message": result.message,
        }
    )
