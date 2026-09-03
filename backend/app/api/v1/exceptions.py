"""Exception inbox API — Phase 6 Final.

GET  /api/v1/exceptions            — list with filters
GET  /api/v1/exceptions/<id>       — single exception
POST /api/v1/exceptions/<id>/resolve
POST /api/v1/exceptions/<id>/assign
POST /api/v1/exceptions/bulk-resolve

All endpoints require admin role.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import require_auth, get_db
from app.services import exception_service
from app.core.errors import ValidationError

bp = Blueprint("exceptions", __name__)


@bp.get("/api/v1/exceptions")
@require_auth("admin")
def list_exceptions():
    db = get_db()
    status = request.args.get("status")
    exception_type = request.args.get("type")
    supplier_id = request.args.get("supplier_id", type=int)
    severity = request.args.get("severity")
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    with db.read_transaction() as conn:
        result = exception_service.list_exceptions(
            conn,
            status=status,
            exception_type=exception_type,
            supplier_id=supplier_id,
            severity=severity,
            limit=min(limit, 200),
            offset=offset,
        )
    return jsonify(result), 200


@bp.get("/api/v1/exceptions/<int:exception_id>")
@require_auth("admin")
def get_exception(exception_id: int):
    db = get_db()
    with db.read_transaction() as conn:
        exc = exception_service.get_exception(conn, exception_id)
    return jsonify({"exception": exc}), 200


@bp.post("/api/v1/exceptions/<int:exception_id>/resolve")
@require_auth("admin")
def resolve_exception(exception_id: int):
    from flask import g
    db = get_db()
    data = request.get_json(silent=True) or {}
    with db.write_transaction() as conn:
        exc = exception_service.resolve_exception(
            conn,
            exception_id,
            resolved_by=g.current_user["id"],
            resolution_notes=data.get("resolution_notes"),
        )
    return jsonify({"exception": exc}), 200


@bp.post("/api/v1/exceptions/<int:exception_id>/assign")
@require_auth("admin")
def assign_exception(exception_id: int):
    db = get_db()
    data = request.get_json(silent=True) or {}
    assigned_to = data.get("assigned_to")
    if not assigned_to:
        raise ValidationError("فیلد assigned_to الزامی است")
    with db.write_transaction() as conn:
        exc = exception_service.assign_exception(conn, exception_id, assigned_to=int(assigned_to))
    return jsonify({"exception": exc}), 200


@bp.post("/api/v1/exceptions/bulk-resolve")
@require_auth("admin")
def bulk_resolve_exceptions():
    from flask import g
    db = get_db()
    data = request.get_json(silent=True) or {}
    ids = data.get("exception_ids", [])
    if not isinstance(ids, list):
        raise ValidationError("exception_ids باید یک آرایه باشد")
    with db.write_transaction() as conn:
        result = exception_service.bulk_resolve(
            conn,
            [int(i) for i in ids],
            resolved_by=g.current_user["id"],
            resolution_notes=data.get("resolution_notes"),
        )
    return jsonify(result), 200
