"""مدیریت وامبی: launch readiness and usage metrics (admin only, read-only).

  GET /api/v1/admin/vambi/readiness
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from app.core.deps import get_db, require_auth
from app.services import vambi_launch_service as launch

bp = Blueprint("admin_vambi", __name__, url_prefix="/api/v1/admin/vambi")


@bp.get("/readiness")
@require_auth("admin")
def readiness():
    with get_db().read_transaction() as conn:
        return jsonify(launch.readiness(conn))
