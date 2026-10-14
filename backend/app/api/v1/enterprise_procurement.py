"""Enterprise procurement API (workspace, policy, fulfillment, dashboard).

  GET  /api/v1/orgs/<org>/procurement/policy
  PUT  /api/v1/orgs/<org>/procurement/policy
  GET  /api/v1/orgs/<org>/procurement/dashboard
  GET  /api/v1/orgs/<org>/procurement/suppliers
  GET  /api/v1/orgs/<org>/procurement/requests/<pr>/workspace
  POST /api/v1/orgs/<org>/procurement/requests/<pr>/notes
  POST /api/v1/orgs/<org>/procurement/requests/<pr>/close
  POST /api/v1/orgs/<org>/procurement/purchase-orders/<po>/deliveries/<idx>
  POST /api/v1/orgs/<org>/procurement/purchase-orders/<po>/receipts
  POST /api/v1/orgs/<org>/procurement/purchase-orders/<po>/corrections
  POST /api/v1/orgs/<org>/procurement/purchase-orders/<po>/corrections/<cid>/resolve
  GET  /api/v1/supplier/rfqs/<rfq>            (marks the invitation viewed)
  POST /api/v1/supplier/rfqs/<rfq>/decline
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
import app.services.enterprise_procurement_service as ent
import app.services.procurement_finance_service as fin
import app.services.procurement_service as pr_svc
import app.services.rfq_service as rfq_svc

bp = Blueprint("enterprise_procurement", __name__, url_prefix="/api/v1")


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    return data


def _workspace(conn, org_id: int, pr_id: int):
    return ent.workspace(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=current_user()["id"])


def _pr_of_po(conn, org_id: int, po_id: int) -> int:
    row = conn.execute("SELECT purchase_request_id FROM purchase_orders WHERE id=? AND organization_id=?",
                       (po_id, org_id)).fetchone()
    if not row or not row["purchase_request_id"]:
        raise NotFoundError("سفارش خرید یافت نشد")
    return row["purchase_request_id"]


@bp.get("/orgs/<int:org_id>/procurement/policy")
@require_auth()
def get_policy(org_id: int):
    with get_db().read_transaction() as conn:
        pr_svc._assert_org_member(conn, current_user()["id"], org_id)
        return jsonify({"policy": ent.get_policy(conn, org_id)})


@bp.put("/orgs/<int:org_id>/procurement/policy")
@require_auth()
def put_policy(org_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        policy = ent.update_policy(conn, organization_id=org_id, actor_user_id=current_user()["id"], data=data)
    return jsonify({"policy": policy})


@bp.get("/orgs/<int:org_id>/procurement/dashboard")
@require_auth()
def dashboard(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(ent.dashboard(conn, organization_id=org_id, actor_user_id=current_user()["id"]))


@bp.get("/orgs/<int:org_id>/procurement/suppliers")
@require_auth()
def suppliers(org_id: int):
    with get_db().read_transaction() as conn:
        membership = pr_svc._assert_org_member(conn, current_user()["id"], org_id)
        if not pr_svc._can_procure(membership):
            raise PermissionError_("فهرست تأمین‌کنندگان فقط برای نقش تدارکات است")
        real_org = conn.execute("SELECT provenance FROM organizations WHERE id=?", (org_id,)).fetchone()["provenance"] == "real"
        rows = conn.execute(
            """SELECT id, display_name, supplier_type, rating_x10, provenance,
                      CASE WHEN provenance='real' THEN 0 ELSE 1 END AS is_demo FROM suppliers
               WHERE status='active' AND (provenance='real') = ? ORDER BY is_demo, display_name""", (real_org,)).fetchall()
        cities: dict = {}
        for loc in conn.execute("SELECT supplier_id, city FROM supplier_locations WHERE status='active' ORDER BY id"):
            cities.setdefault(loc["supplier_id"], [])
            if loc["city"] not in cities[loc["supplier_id"]]:
                cities[loc["supplier_id"]].append(loc["city"])
    return jsonify({"items": [dict(r) | {"is_demo": bool(r["is_demo"]), "cities": cities.get(r["id"], [])} for r in rows]})


@bp.get("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/workspace")
@require_auth()
def workspace(org_id: int, pr_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(_workspace(conn, org_id, pr_id))


@bp.post("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/notes")
@require_auth()
def add_note(org_id: int, pr_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        ent.add_note(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=current_user()["id"], text=data.get("text"))
        return jsonify(_workspace(conn, org_id, pr_id)), 201


@bp.post("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/close")
@require_auth()
def close(org_id: int, pr_id: int):
    with get_db().write_transaction() as conn:
        ent.close_request(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=current_user()["id"])
        return jsonify(_workspace(conn, org_id, pr_id))


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/deliveries/<int:idx>")
@require_auth()
def delivery(org_id: int, po_id: int, idx: int):
    data = _body()
    with get_db().write_transaction() as conn:
        ent.update_delivery(conn, organization_id=org_id, po_id=po_id, destination_index=idx,
                            actor_user_id=current_user()["id"], status=data.get("status"),
                            tracking_reference=data.get("tracking_reference"))
        return jsonify(_workspace(conn, org_id, _pr_of_po(conn, org_id, po_id)))


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/receipts")
@require_auth()
def receipt(org_id: int, po_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        ent.record_receipt(conn, organization_id=org_id, po_id=po_id, actor_user_id=current_user()["id"], data=data)
        return jsonify(_workspace(conn, org_id, _pr_of_po(conn, org_id, po_id))), 201


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/corrections")
@require_auth()
def correction(org_id: int, po_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        ent.open_correction(conn, organization_id=org_id, po_id=po_id, actor_user_id=current_user()["id"], data=data)
        return jsonify(_workspace(conn, org_id, _pr_of_po(conn, org_id, po_id))), 201


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/corrections/<int:cid>/resolve")
@require_auth()
def resolve(org_id: int, po_id: int, cid: int):
    data = _body()
    with get_db().write_transaction() as conn:
        ent.resolve_correction(conn, organization_id=org_id, po_id=po_id, correction_id=cid,
                               actor_user_id=current_user()["id"], resolution=data.get("resolution"))
        return jsonify(_workspace(conn, org_id, _pr_of_po(conn, org_id, po_id)))


def _supplier_id(conn) -> int:
    from app.services.access_admin_service import current_supplier_id
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب تأمین‌کننده برای این کاربر یافت نشد")
    return sid


@bp.get("/supplier/rfqs/<int:rfq_id>")
@require_auth()
def supplier_rfq(rfq_id: int):
    with get_db().write_transaction() as conn:
        sid = _supplier_id(conn)
        inv = conn.execute("SELECT * FROM rfq_suppliers WHERE rfq_id=? AND supplier_id=?", (rfq_id, sid)).fetchone()
        if not inv:
            raise NotFoundError("استعلام یافت نشد")
        if inv["status"] == "invited":
            conn.execute("UPDATE rfq_suppliers SET status='viewed', viewed_at=? WHERE id=?", (ent._now(), inv["id"]))
        rfq = next((r for r in rfq_svc.list_supplier_invited_rfqs(conn, sid) if r["id"] == rfq_id), None)
        if rfq:
            for item in rfq["items"]:
                pri = conn.execute(
                    """SELECT pri.target_specification, pri.acceptable_alternative FROM rfq_items ri
                       JOIN purchase_request_items pri ON pri.id=ri.purchase_request_item_id WHERE ri.id=?""",
                    (item["id"],)).fetchone()
                item["target_specification"] = pri["target_specification"] if pri else None
                item["acceptable_alternative"] = pri["acceptable_alternative"] if pri else None
        dest = conn.execute(
            "SELECT pr.destinations_json, pr.needed_by_date FROM rfqs r JOIN purchase_requests pr ON pr.id=r.purchase_request_id WHERE r.id=?",
            (rfq_id,)).fetchone()
        quotes = [rfq_svc._quote_dict(q) for q in conn.execute(
            "SELECT * FROM supplier_quotes WHERE rfq_id=? AND supplier_id=? ORDER BY id DESC", (rfq_id, sid))]
        for q in quotes:
            q["items"] = [rfq_svc._quote_item_dict(i) for i in conn.execute(
                "SELECT * FROM supplier_quote_items WHERE supplier_quote_id=? ORDER BY id", (q["id"],))]
            q["revisions"] = rfq_svc.list_quote_revisions(conn, q["id"])
    import json
    # Suppliers see where and when to deliver, never the organization's budget or internal notes.
    destinations = [{k: d.get(k) for k in ("label", "province", "city", "delivery_window", "allocations")}
                    for d in json.loads(dest["destinations_json"])] if dest else []
    return jsonify({"rfq": rfq, "destinations": destinations,
                    "needed_by_date": dest["needed_by_date"] if dest else None, "quotes": quotes})


@bp.post("/supplier/rfqs/<int:rfq_id>/decline")
@require_auth()
def supplier_decline(rfq_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        sid = _supplier_id(conn)
        inv = conn.execute("SELECT * FROM rfq_suppliers WHERE rfq_id=? AND supplier_id=?", (rfq_id, sid)).fetchone()
        if not inv:
            raise NotFoundError("استعلام یافت نشد")
        if inv["status"] in ("responded", "awarded", "declined"):
            raise ConflictError("امکان رد این استعلام وجود ندارد")
        reason = pr_svc._text(data.get("reason"), "علت", 1000, required=True)
        conn.execute("UPDATE rfq_suppliers SET status='declined', decline_reason=? WHERE id=?", (reason, inv["id"]))
        rfq = conn.execute("SELECT organization_id, purchase_request_id FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
        ent.record_event(conn, organization_id=rfq["organization_id"], purchase_request_id=rfq["purchase_request_id"],
                         actor_user_id=current_user()["id"], event_type="supplier_declined",
                         payload={"rfq_id": rfq_id, "reason": reason})
    return jsonify({"status": "declined"})


# ── Cases list & procurement finance ──────────────────────────────────────

@bp.get("/orgs/<int:org_id>/procurement/cases")
@require_auth()
def cases(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(ent.list_cases(conn, organization_id=org_id, actor_user_id=current_user()["id"],
                                      q=request.args.get("q"), status=request.args.get("status") or None,
                                      stage=request.args.get("stage") or None))


@bp.get("/orgs/<int:org_id>/procurement/finance")
@require_auth()
def finance_summary(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(fin.summary(conn, org=org_id, actor=current_user()["id"]))


def _fin_ws(conn, org_id, po_id):
    return jsonify(_workspace(conn, org_id, _pr_of_po(conn, org_id, po_id)))


def _idempotent(conn, run):
    """Financial POSTs honour Idempotency-Key: a replay returns the stored response, a changed body is rejected."""
    import hashlib, json as _json
    key = request.headers.get("Idempotency-Key")
    if key is not None and (not key.strip() or len(key) > 128):
        raise ValidationError("شناسه درخواست نامعتبر است")
    body = request.get_json(silent=True) or {}
    digest = hashlib.sha256(_json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    uid = current_user()["id"]
    if key:
        old = conn.execute("SELECT * FROM idempotency_keys WHERE key=? AND user_id=? AND endpoint=?", (key, uid, request.path)).fetchone()
        if old:
            if old["request_hash"] != digest:
                raise ConflictError("شناسه برای درخواست متفاوت استفاده شده است", code="idempotency_conflict")
            return jsonify(_json.loads(old["response_json"]))
    resp = run()
    if key:
        conn.execute("INSERT INTO idempotency_keys (key, user_id, endpoint, request_hash, response_json, status_code) VALUES (?,?,?,?,?,?)",
                     (key, uid, request.path, digest, resp.get_data(as_text=True), resp.status_code))
    return resp


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/payment-plan")
@require_auth()
def payment_plan(org_id: int, po_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        def run():
            fin.create_plan(conn, org=org_id, po_id=po_id, actor=current_user()["id"], parts=data.get("parts"))
            return _fin_ws(conn, org_id, po_id)
        return _idempotent(conn, run)


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/payment-plan/submit")
@require_auth()
def payment_plan_submit(org_id: int, po_id: int):
    with get_db().write_transaction() as conn:
        def run():
            fin.submit_plan(conn, org=org_id, po_id=po_id, actor=current_user()["id"])
            return _fin_ws(conn, org_id, po_id)
        return _idempotent(conn, run)


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/payment-plan/decision")
@require_auth()
def payment_plan_decision(org_id: int, po_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        def run():
            fin.decide_plan(conn, org=org_id, po_id=po_id, actor=current_user()["id"], action=data.get("action"), note=data.get("note"))
            return _fin_ws(conn, org_id, po_id)
        return _idempotent(conn, run)


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/payment-parts/<int:part_id>/<action>")
@require_auth()
def payment_part(org_id: int, po_id: int, part_id: int, action: str):
    data = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        def run():
            fin.part_action(conn, org=org_id, po_id=po_id, part_id=part_id, actor=current_user()["id"], action=action,
                            reference=data.get("reference"))
            return _fin_ws(conn, org_id, po_id)
        return _idempotent(conn, run)


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/refunds")
@require_auth()
def refund(org_id: int, po_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        def run():
            fin.record_refund(conn, org=org_id, po_id=po_id, actor=current_user()["id"], amount=data.get("amount_minor"), note=data.get("note"))
            return _fin_ws(conn, org_id, po_id)
        return _idempotent(conn, run)


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/settlement")
@require_auth()
def settlement(org_id: int, po_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        def run():
            fin.record_settlement(conn, org=org_id, po_id=po_id, actor=current_user()["id"], reference=data.get("reference"))
            return _fin_ws(conn, org_id, po_id)
        return _idempotent(conn, run)


# ── Platform admin: all organizations' cases (derived, read-only) ─────────

@bp.get("/admin/procurement/cases")
@require_auth("admin")
def admin_cases():
    org = request.args.get("org")
    with get_db().read_transaction() as conn:
        return jsonify(ent.list_cases(conn, organization_id=int(org) if org and org.isdigit() else None,
                                      actor_user_id=current_user()["id"], q=request.args.get("q"),
                                      status=request.args.get("status") or None, stage=request.args.get("stage") or None,
                                      platform=True))


# ── Supplier operations ───────────────────────────────────────────────────

@bp.get("/supplier/overview")
@require_auth()
def supplier_overview():
    with get_db().read_transaction() as conn:
        return jsonify(ent.supplier_overview(conn, user_id=current_user()["id"]))


@bp.post("/supplier/orders/<int:po_id>/deliveries/<int:idx>")
@require_auth()
def supplier_delivery(po_id: int, idx: int):
    data = _body()
    with get_db().write_transaction() as conn:
        ent.supplier_update_delivery(conn, user_id=current_user()["id"], po_id=po_id, destination_index=idx,
                                     status=data.get("status"), tracking_reference=data.get("tracking_reference"))
        return jsonify(ent.supplier_overview(conn, user_id=current_user()["id"]))


# ── Order documents / delivery evidence ───────────────────────────────────

def _upload_args():
    f = request.files.get("file")
    if f is None:
        raise ValidationError("فایل ارسال نشده است")
    data = f.read(5 * 1024 * 1024 + 1)
    return data, f.filename, request.form.get("kind", "delivery_evidence"), request.form.get("destination_index") or None, request.form.get("note")


@bp.post("/orgs/<int:org_id>/procurement/purchase-orders/<int:po_id>/documents")
@require_auth()
def org_upload_document(org_id: int, po_id: int):
    from app.services import procurement_document_service as docs
    data, name, kind, dest, note = _upload_args()
    with get_db().write_transaction() as conn:
        docs.buyer_can_upload(conn, org_id, current_user()["id"])
        po = ent._po(conn, org_id, po_id)
        doc = docs.save(conn, po=po, actor=current_user()["id"], side="buyer", data=data, filename=name, kind=kind,
                        destination_index=dest, note=note)
        return jsonify({"document": doc}), 201


@bp.post("/supplier/orders/<int:po_id>/documents")
@require_auth()
def supplier_upload_document(po_id: int):
    from app.services import procurement_document_service as docs
    data, name, kind, dest, note = _upload_args()
    with get_db().write_transaction() as conn:
        po = ent._supplier_po(conn, _supplier_id(conn), po_id)
        doc = docs.save(conn, po=po, actor=current_user()["id"], side="supplier", data=data, filename=name, kind=kind,
                        destination_index=dest, note=note)
        return jsonify({"document": doc}), 201


@bp.get("/procurement-documents/<int:doc_id>")
@require_auth()
def download_document(doc_id: int):
    from flask import send_file
    from app.services import procurement_document_service as docs
    with get_db().read_transaction() as conn:
        doc = docs.get(conn, doc_id)
        docs.authorize_read(conn, doc, current_user())
    path = docs.file_path(doc)
    if not path.exists():
        raise NotFoundError("فایل سند در دسترس نیست")
    return send_file(path, mimetype=doc["content_type"], download_name=doc["filename"], as_attachment=doc["content_type"] == "application/pdf")


@bp.put("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/destinations")
@require_auth()
def update_destinations(org_id: int, pr_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        pr_svc.update_destinations(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=current_user()["id"],
                                   destinations=data.get("destinations"), base_hash=data.get("base_hash"))
        return jsonify(_workspace(conn, org_id, pr_id))


@bp.post("/orgs/<int:org_id>/procurement/requests/<int:pr_id>/split")
@require_auth()
def split_request(org_id: int, pr_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        out = pr_svc.split_by_destinations(conn, organization_id=org_id, pr_id=pr_id, actor_user_id=current_user()["id"],
                                           destination_indexes=data.get("destination_indexes"), base_hash=data.get("base_hash"))
        return jsonify(out), 201
