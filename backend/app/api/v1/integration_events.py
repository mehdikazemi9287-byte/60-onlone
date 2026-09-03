"""Integration Events API — Phase 7 (Security Repaired).

Endpoints:
  GET  /api/v1/integration-events           List events (admin global / supplier scoped)
  GET  /api/v1/integration-events/<id>      Get single event
  POST /api/v1/integration-events/<id>/replay  Replay dead-letter event (admin / connector owner)
  GET  /api/v1/integration-events/dead-letter  List dead-letter events
  GET  /api/v1/circuit-breakers             List connector circuit breaker states
  POST /api/v1/circuit-breakers/<id>/reset  Manually reset circuit breaker
  GET  /api/v1/circuit-breakers/<id>        Get single circuit breaker state

SECURITY:
  - Platform admin may list/replay/reset globally.
  - Supplier may only inspect events and circuit breakers belonging to their
    server-derived supplier_id.  supplier_id is NEVER taken from query/body.
  - Supplier must never access another supplier's resources (returns 404).
  - Customer cannot access any operational integration endpoints (403).
  - Dead-letter replay and circuit-breaker reset require admin or explicitly
    authorized owner of that connector.
  - Filters are enforced inside database queries, not merely after fetching rows.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import require_auth, get_db
from app.services import integration_event_service as ev_svc
from app.services import circuit_breaker_service as cb_svc
from app.core.errors import NotFoundError, PermissionError_
from app.core.db import query

bp = Blueprint("integration_events", __name__, url_prefix="/api/v1")


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_caller_supplier_id(db) -> int | None:
    """Server-derived supplier_id; None if caller is not supplier role."""
    if g.current_user["role"] != "supplier":
        return None
    with db.read_transaction() as conn:
        row = conn.execute(
            "SELECT id FROM suppliers WHERE user_id = ?", (g.current_user["id"],)
        ).fetchone()
    return int(row["id"]) if row else None


def _require_not_customer() -> None:
    if g.current_user["role"] == "customer":
        raise PermissionError_("مشتریان به رویدادهای یکپارچه‌سازی دسترسی ندارند")


def _require_admin() -> None:
    if g.current_user["role"] != "admin":
        raise PermissionError_("این عملیات فقط برای مدیر پلتفرم مجاز است")


# ─────────────────────────────────────────────────────────────────────────────
# Integration events
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/integration-events", methods=["GET"])
@require_auth("admin", "supplier")
def list_events():
    """List integration events. Admins see all; suppliers see only theirs (scoped in DB query)."""
    _require_not_customer()
    db = get_db()
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    status_filter = request.args.get("status")

    role = g.current_user["role"]
    if role == "admin":
        connector_account_id = request.args.get("connector_account_id", type=int)
        events = ev_svc.fetch_events_admin(
            connector_account_id=connector_account_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    else:
        # Supplier — always scope to server-derived supplier_id (filter inside DB query)
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None:
            return jsonify({"integration_events": [], "limit": limit, "offset": offset})
        events = ev_svc.fetch_events_for_supplier(
            supplier_id=caller_sid,
            status=status_filter,
            limit=limit,
            offset=offset,
        )

    return jsonify({"integration_events": events, "limit": limit, "offset": offset})


@bp.route("/integration-events/dead-letter", methods=["GET"])
@require_auth("admin", "supplier")
def list_dead_letter():
    """List dead-lettered events. Admin sees all; supplier sees only theirs."""
    _require_not_customer()
    db = get_db()
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))

    role = g.current_user["role"]
    if role == "admin":
        connector_account_id = request.args.get("connector_account_id", type=int)
        events = ev_svc.fetch_dead_letter_events(
            connector_account_id=connector_account_id,
            limit=limit,
            offset=offset,
        )
    else:
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None:
            return jsonify({"dead_letter_events": [], "count": 0})
        events = ev_svc.fetch_dead_letter_events_for_supplier(
            supplier_id=caller_sid,
            limit=limit,
            offset=offset,
        )

    return jsonify({"dead_letter_events": events, "count": len(events)})


@bp.route("/integration-events/<int:event_id>/replay", methods=["POST"])
@require_auth("admin", "supplier")
def replay_event(event_id: int):
    """Replay dead-letter event. Admin: any event. Supplier: only their own."""
    _require_not_customer()
    db = get_db()
    role = g.current_user["role"]

    if role != "admin":
        # Verify ownership before replaying
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None:
            return jsonify({"error": {"code": "not_found",
                                       "message": f"رویداد #{event_id} یافت نشد"}}), 404
        event = ev_svc.get_event_by_id(event_id)
        if event is None or event.get("supplier_id") != caller_sid:
            return jsonify({"error": {"code": "not_found",
                                       "message": f"رویداد #{event_id} یافت نشد"}}), 404

    actor_user_id = g.current_user.get("id")
    replayed = ev_svc.replay_dead_letter_event(event_id, actor_user_id=actor_user_id)
    if not replayed:
        return jsonify({"error": {"code": "not_found",
                                   "message": f"رویداد #{event_id} یافت نشد یا dead_letter نیست"}}), 404
    return jsonify({"replayed": True, "event_id": event_id})


# ─────────────────────────────────────────────────────────────────────────────
# Circuit breakers
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/circuit-breakers", methods=["GET"])
@require_auth("admin", "supplier")
def list_circuit_breakers():
    """Return circuit breaker states. Admin: all; supplier: only their connectors."""
    _require_not_customer()
    db = get_db()
    role = g.current_user["role"]

    if role == "admin":
        summary = cb_svc.get_health_summary()
    else:
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None:
            return jsonify({"circuit_breakers": [], "count": 0})
        summary = cb_svc.get_health_summary_for_supplier(caller_sid)

    return jsonify({"circuit_breakers": summary, "count": len(summary)})


@bp.route("/circuit-breakers/<int:connector_account_id>/reset", methods=["POST"])
@require_auth("admin", "supplier")
def reset_circuit_breaker(connector_account_id: int):
    """Manually reset a circuit breaker. Admin: any; supplier: only their own."""
    _require_not_customer()
    db = get_db()
    role = g.current_user["role"]

    if role != "admin":
        # Verify supplier owns the connector_account
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None:
            return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
        if not cb_svc.connector_belongs_to_supplier(connector_account_id, caller_sid):
            return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404

    cb_svc.reset(connector_account_id)
    state = cb_svc.get_state(connector_account_id)
    return jsonify({"reset": True, "connector_account_id": connector_account_id, "state": state})


@bp.route("/circuit-breakers/<int:connector_account_id>", methods=["GET"])
@require_auth("admin", "supplier")
def get_circuit_breaker(connector_account_id: int):
    """Get circuit breaker state. Admin: any; supplier: only their own."""
    _require_not_customer()
    db = get_db()
    role = g.current_user["role"]

    if role != "admin":
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None:
            return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
        if not cb_svc.connector_belongs_to_supplier(connector_account_id, caller_sid):
            return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404

    state = cb_svc.get_state(connector_account_id)
    return jsonify({"connector_account_id": connector_account_id, **state})


# ─────────────────────────────────────────────────────────────────────────────
# Outbox health / metrics (Phase 8 — Workstream D & E)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/outbox/metrics", methods=["GET"])
@require_auth("admin")
def outbox_metrics():
    """Outbox depth metrics by status — admin only.

    Returns counts per status plus a total, useful for dashboards and
    alerting on outbox depth.
    """
    from app.core.db import query as _query
    rows = _query(
        """
        SELECT status, COUNT(*) AS cnt
        FROM integration_events
        GROUP BY status
        """,
    )
    by_status: dict[str, int] = {r["status"]: r["cnt"] for r in (rows or [])}
    total = sum(by_status.values())
    return jsonify({
        "by_status": by_status,
        "total": total,
        "pending": by_status.get("pending", 0),
        "processing": by_status.get("processing", 0),
        "delivered": by_status.get("delivered", 0),
        "dead_letter": by_status.get("dead_letter", 0),
        "no_subscriber": by_status.get("no_subscriber", 0),
    })
