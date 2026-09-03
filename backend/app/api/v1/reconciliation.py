"""Reconciliation API — Phase 6 Final.

POST /api/v1/reconciliation/batches         — create batch
GET  /api/v1/reconciliation/batches         — list batches
GET  /api/v1/reconciliation/batches/<id>    — get batch
POST /api/v1/reconciliation/batches/<id>/run — run matching

Admin only.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import require_auth, get_db
from app.core.errors import ValidationError
from app.services import reconciliation_service

bp = Blueprint("reconciliation", __name__)


@bp.post("/api/v1/reconciliation/batches")
@require_auth("admin")
def create_batch():
    db = get_db()
    data = request.get_json(silent=True) or {}

    batch_ref = data.get("batch_ref")
    if not batch_ref:
        raise ValidationError("batch_ref الزامی است")
    source_type = data.get("source_type")
    if source_type not in ("psp_statement", "bank_statement", "manual"):
        raise ValidationError("source_type نامعتبر است")
    period_start = data.get("period_start")
    period_end = data.get("period_end")
    if not period_start or not period_end:
        raise ValidationError("period_start و period_end الزامی هستند")

    with db.write_transaction() as conn:
        batch = reconciliation_service.create_batch(
            conn,
            batch_ref=batch_ref,
            source_type=source_type,
            period_start=period_start,
            period_end=period_end,
            created_by=g.current_user["id"],
            supplier_id=data.get("supplier_id"),
        )

        # Import items if provided
        items = data.get("items", [])
        if items:
            # Validate no float money
            for item in items:
                if isinstance(item.get("amount_minor"), float):
                    raise ValidationError("مقدار amount_minor باید عدد صحیح (ریال) باشد")
            reconciliation_service.import_items(conn, batch["id"], items)

    return jsonify({"batch": batch}), 201


@bp.get("/api/v1/reconciliation/batches")
@require_auth("admin")
def list_batches():
    db = get_db()
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    with db.read_transaction() as conn:
        result = reconciliation_service.list_batches(
            conn, status=status, limit=min(limit, 200), offset=offset
        )
    return jsonify(result), 200


@bp.get("/api/v1/reconciliation/batches/<int:batch_id>")
@require_auth("admin")
def get_batch(batch_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        batch = reconciliation_service.get_batch(conn, batch_id)
    return jsonify({"batch": batch}), 200


@bp.post("/api/v1/reconciliation/batches/<int:batch_id>/run")
@require_auth("admin")
def run_matching(batch_id: int):
    db = get_db()
    with db.write_transaction() as conn:
        result = reconciliation_service.run_matching(conn, batch_id=batch_id)
    return jsonify(result), 200
