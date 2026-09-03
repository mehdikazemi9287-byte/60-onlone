"""Auto Discovery API — Phase 6 Final.

POST /api/v1/discovery/run — trigger zero-touch discovery sync

Admin only. Must own the connector_account.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import require_auth, get_db
from app.core.errors import ValidationError, PermissionError_
from app.services import auto_discovery_service

bp = Blueprint("discovery", __name__)


@bp.post("/api/v1/discovery/run")
@require_auth("admin")
def run_discovery():
    db = get_db()
    data = request.get_json(silent=True) or {}

    connector_account_id = data.get("connector_account_id")
    if not connector_account_id:
        raise ValidationError("connector_account_id الزامی است")

    batch_size = int(data.get("batch_size", 100))

    with db.read_transaction() as conn:
        ca = conn.execute(
            "SELECT * FROM connector_accounts WHERE id = ?",
            (int(connector_account_id),)
        ).fetchone()
        if not ca:
            raise ValidationError(f"حساب اتصال {connector_account_id} یافت نشد")

    # Use a single connection for the entire discovery run
    conn = db.connection
    result = auto_discovery_service.run_discovery_sync(
        conn,
        connector_account_id=int(connector_account_id),
        triggered_by=f"api:user:{g.current_user['id']}",
        batch_size=batch_size,
    )
    return jsonify(result), 200
