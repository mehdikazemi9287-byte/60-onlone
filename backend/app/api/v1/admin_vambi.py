"""مدیریت وامبی: launch readiness and usage metrics (admin only, read-only).

  GET /api/v1/admin/vambi/readiness
  GET /api/v1/admin/vambi/metrics?days=30   (1..365)
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import ValidationError
from app.services import vambi_launch_service as launch

bp = Blueprint("admin_vambi", __name__, url_prefix="/api/v1/admin/vambi")


@bp.get("/readiness")
@require_auth("admin")
def readiness():
    with get_db().read_transaction() as conn:
        return jsonify(launch.readiness(conn))


@bp.get("/metrics")
@require_auth("admin")
def metrics():
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        raise ValidationError("بازهٔ روز نامعتبر است") from None
    if not 1 <= days <= launch.MAX_DAYS:
        raise ValidationError("بازهٔ روز باید بین ۱ و ۳۶۵ باشد")
    with get_db().read_transaction() as conn:
        return jsonify(launch.metrics(conn, days=days))
