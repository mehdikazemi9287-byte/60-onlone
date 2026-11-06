"""Settlement API — supplier payable entries and settlement batch management.

URL structure:
  /api/v1/admin/suppliers/:supplier_id/payables           GET    admin only
  /api/v1/admin/suppliers/:supplier_id/payables/summary   GET    admin only
  /api/v1/admin/settlement-batches                        POST   admin only
  /api/v1/admin/settlement-batches                        GET    admin only
  /api/v1/admin/settlement-batches/:batch_id              GET    admin only
  /api/v1/admin/settlement-batches/:batch_id/complete     POST   admin only
  /api/v1/supplier/payables                               GET    supplier self-service
  /api/v1/supplier/payables/summary                       GET    supplier self-service

Architecture:
  - All settlement arithmetic is integer (no floats) — BLOCKER 5
  - Batches are idempotent via idempotency_key — BLOCKER 7
  - Payments are append-only — BLOCKER 8
  - Shipping payer is explicit — BLOCKER 9
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import fulfillment_service, settlement_service, supplier_ledger_service

bp = Blueprint("settlement", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_supplier_id_for_user(db, user_id: int) -> int:
    """Resolve supplier_id for an authenticated supplier user. 404 if none."""
    with db.read_transaction() as conn:
        sup = fulfillment_service.get_supplier_for_user(conn, user_id)
    if sup is None:
        raise NotFoundError(
            "حساب تأمین‌کننده یافت نشد. با پشتیبان تماس بگیرید.",
            code="supplier_not_linked",
        )
    return int(sup["id"])


def _int_body(data: dict, key: str, required: bool = True, default=None):
    val = data.get(key, default)
    if val is None:
        if required:
            raise ValidationError(f"فیلد '{key}' الزامی است")
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValidationError(f"فیلد '{key}' باید عدد صحیح باشد")


# ---------------------------------------------------------------------------
# ADMIN — payable entry queries
# ---------------------------------------------------------------------------

@bp.route("/api/v1/admin/suppliers/<int:supplier_id>/payables", methods=["GET"])
@require_auth("admin")
def admin_list_payables(supplier_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        entries = supplier_ledger_service.get_unbatched_payables(conn, supplier_id)
    return jsonify({"payables": entries}), 200


@bp.route("/api/v1/admin/suppliers/<int:supplier_id>/payables/summary", methods=["GET"])
@require_auth("admin")
def admin_payable_summary(supplier_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        summary = supplier_ledger_service.get_supplier_payable_summary(conn, supplier_id)
    return jsonify(summary), 200


# ---------------------------------------------------------------------------
# ADMIN — settlement batch management
# ---------------------------------------------------------------------------

@bp.route("/api/v1/admin/settlement-batches", methods=["POST"])
@require_auth("admin")
def admin_create_settlement_batch():
    db = get_db()
    data = request.get_json(silent=True) or {}

    supplier_id = _int_body(data, "supplier_id")
    idempotency_key = (data.get("idempotency_key") or "").strip()
    if not idempotency_key:
        raise ValidationError("فیلد 'idempotency_key' الزامی است")

    payable_entry_ids_raw = data.get("payable_entry_ids", [])
    if not isinstance(payable_entry_ids_raw, list) or not payable_entry_ids_raw:
        raise ValidationError("فیلد 'payable_entry_ids' باید یک لیست غیرخالی باشد")
    try:
        payable_entry_ids = [int(x) for x in payable_entry_ids_raw]
    except (TypeError, ValueError):
        raise ValidationError("تمام مقادیر 'payable_entry_ids' باید عدد صحیح باشند")

    # Omit to use each sale's snapshotted commission (category/channel rules).
    commission_rate_bps = _int_body(data, "commission_rate_bps", required=False, default=None) if "commission_rate_bps" in data else None
    release_held = data.get("release_held") is True
    if release_held:
        from app.core.deps import current_user
        with db.write_transaction() as conn:
            conn.execute("INSERT INTO audit_logs(actor_user_id, action, entity_type, entity_id, metadata_json) VALUES (?,?,?,?,?)",
                         (current_user()["id"], "settlement_release_held", "supplier", str(supplier_id), "{}"))
    shipping_charge_minor = _int_body(data, "shipping_charge_minor", required=False, default=0)
    shipping_payer = (data.get("shipping_payer") or "customer").strip()

    with db.write_transaction() as conn:
        batch = settlement_service.create_settlement_batch(
            conn,
            supplier_id=supplier_id,
            payable_entry_ids=payable_entry_ids,
            idempotency_key=idempotency_key,
            commission_rate_bps=commission_rate_bps,
            shipping_charge_minor=shipping_charge_minor,
            shipping_payer=shipping_payer,
            release_held=release_held,
        )
    return jsonify({"batch": batch}), 201


@bp.route("/api/v1/admin/settlement-batches", methods=["GET"])
@require_auth("admin")
def admin_list_settlement_batches():
    db = get_db()
    supplier_id_raw = request.args.get("supplier_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ValidationError("limit و offset باید عدد صحیح باشند")

    supplier_id = int(supplier_id_raw) if supplier_id_raw else None

    with db.read_transaction() as conn:
        batches = settlement_service.list_settlement_batches(
            conn,
            supplier_id=supplier_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    return jsonify({"batches": batches}), 200


@bp.route("/api/v1/admin/settlement-batches/<int:batch_id>", methods=["GET"])
@require_auth("admin")
def admin_get_settlement_batch(batch_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        result = settlement_service.get_settlement_batch(conn, batch_id)
    return jsonify(result), 200


@bp.route("/api/v1/admin/settlement-batches/<int:batch_id>/complete", methods=["POST"])
@require_auth("admin")
def admin_complete_settlement_batch(batch_id: int):
    db = get_db()
    data = request.get_json(silent=True) or {}
    payment_reference = data.get("payment_reference")
    external_reference = data.get("external_reference")

    with db.write_transaction() as conn:
        result = settlement_service.complete_settlement_batch(
            conn,
            batch_id=batch_id,
            payment_reference=payment_reference,
            external_reference=external_reference,
        )
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# SUPPLIER SELF-SERVICE — read own payables
# ---------------------------------------------------------------------------

@bp.route("/api/v1/supplier/payables", methods=["GET"])
@require_auth()  # seller access = active supplier membership
def supplier_list_payables():
    db = get_db()
    user = g.current_user
    supplier_id = _resolve_supplier_id_for_user(db, user["id"])
    with db.read_transaction() as conn:
        entries = supplier_ledger_service.get_unbatched_payables(conn, supplier_id)
    return jsonify({"payables": entries}), 200


@bp.route("/api/v1/supplier/payables/summary", methods=["GET"])
@require_auth()  # seller access = active supplier membership
def supplier_payable_summary():
    db = get_db()
    user = g.current_user
    supplier_id = _resolve_supplier_id_for_user(db, user["id"])
    with db.read_transaction() as conn:
        summary = supplier_ledger_service.get_supplier_payable_summary(conn, supplier_id)
    return jsonify(summary), 200
