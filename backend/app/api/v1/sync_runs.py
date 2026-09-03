"""Sync Run API — Phase 6.

Read-only access to connector sync run history and per-item results.
Useful for debugging integration issues and monitoring data freshness.

URL structure:
  GET /api/v1/sync-runs                          — list sync runs
  GET /api/v1/sync-runs/<run_id>                 — get run detail
  GET /api/v1/sync-runs/<run_id>/items           — list items in a run
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError
from app.services import sync_engine_service

bp = Blueprint("sync_runs", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/sync-runs")
@require_auth("supplier", "admin")
def list_sync_runs():
    """List sync runs, optionally filtered by connector account."""
    db                   = get_db()
    connector_account_id = request.args.get("connector_account_id", type=int)
    limit                = min(int(request.args.get("limit", "20")), 200)
    offset               = int(request.args.get("offset", "0"))

    with db.read_transaction() as conn:
        results = sync_engine_service.list_sync_runs(
            conn,
            connector_account_id=connector_account_id,
            limit=limit,
            offset=offset,
        )
    return jsonify({"data": results})


@bp.get("/sync-runs/<int:run_id>")
@require_auth("supplier", "admin")
def get_sync_run(run_id: int):
    """Get the full detail of a single sync run."""
    db = get_db()
    with db.read_transaction() as conn:
        result = sync_engine_service.get_sync_run(conn, run_id=run_id)
    if result is None:
        raise NotFoundError("اجرای همگام‌سازی یافت نشد")
    return jsonify({"data": result})


@bp.get("/sync-runs/<int:run_id>/items")
@require_auth("supplier", "admin")
def list_sync_run_items(run_id: int):
    """List individual line-item results for a sync run."""
    db     = get_db()
    limit  = min(int(request.args.get("limit", "100")), 500)
    offset = int(request.args.get("offset", "0"))

    with db.read_transaction() as conn:
        # Verify run exists first
        run = sync_engine_service.get_sync_run(conn, run_id=run_id)
        if run is None:
            raise NotFoundError("اجرای همگام‌سازی یافت نشد")

        items = sync_engine_service.list_sync_run_items(
            conn,
            run_id=run_id,
            limit=limit,
            offset=offset,
        )
    return jsonify({"data": items})
