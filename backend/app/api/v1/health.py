"""Health, liveness, and readiness endpoints — Phase 8 Observability.

Three endpoints:
  GET /api/v1/health         — combined liveness + readiness (backward compat)
  GET /api/v1/health/live    — liveness probe: is the process alive?
  GET /api/v1/health/ready   — readiness probe: can the service handle traffic?
                               Checks DB reachability and migration version.
  GET /api/v1/metrics        — admin-only Prometheus-compatible text metrics

Readiness correctness (Blocker 5):
  - Determines the expected migration head from the migration directory.
  - Returns 503 if DB schema is behind expected head.
  - Returns 503 if migration metadata is corrupt or DB is unreachable.
  - NEVER exposes raw exception text in responses.
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.migrator import MIGRATIONS_DIR, current_version, discover

logger = logging.getLogger(__name__)

bp = Blueprint("health", __name__, url_prefix="/api/v1")


def _expected_head() -> str | None:
    """Return the highest migration version from the migrations directory.

    Returns None if the directory is empty or an error occurs.
    Raises on truly unexpected errors so readiness can return 503.
    """
    migrations = discover(MIGRATIONS_DIR)
    if not migrations:
        return None
    # discover() returns sorted list; last element is highest version
    return migrations[-1][0]


@bp.get("/health")
def health():
    """Combined health check — backward compatible."""
    try:
        db = get_db()
        db.query_one("SELECT 1")
        schema_version = current_version(db)
        return jsonify(
            {
                "status": "ok",
                "database": "reachable",
                "schema_version": schema_version,
            }
        )
    except Exception:
        logger.exception("health check failed")
        return jsonify({"status": "error", "database": "unreachable"}), 503


@bp.get("/health/live")
def liveness():
    """Liveness probe.

    Returns 200 if the process is alive and Flask is responding.
    Does NOT check the database — a DB outage should not cause a container restart.
    """
    return jsonify({"status": "alive"})


@bp.get("/health/ready")
def readiness():
    """Readiness probe.

    Returns 200 only when the service is ready to handle traffic:
      - Database is reachable
      - Schema is at the expected migration head (not behind)

    Returns 503 if:
      - DB is unreachable
      - Schema version is behind expected head
      - Migration metadata is corrupt or missing
      - Expected head cannot be determined

    NEVER exposes raw exception text (Blocker 3).
    """
    try:
        db = get_db()
        # Verify DB is reachable
        try:
            db.query_one("SELECT 1")
        except Exception:
            logger.exception("readiness: DB unreachable")
            return jsonify({"status": "not_ready", "reason": "database_unreachable"}), 503

        # Determine expected head from migration directory
        try:
            expected = _expected_head()
        except Exception:
            logger.exception("readiness: failed to discover migration head")
            return jsonify({"status": "not_ready", "reason": "migration_discovery_failed"}), 503

        if expected is None:
            logger.error("readiness: no migrations found in directory")
            return jsonify({"status": "not_ready", "reason": "no_migrations_found"}), 503

        # Get current applied version
        try:
            actual = current_version(db)
        except Exception:
            logger.exception("readiness: failed to read schema_migrations")
            return jsonify({"status": "not_ready", "reason": "migration_metadata_corrupt"}), 503

        if actual is None or actual < expected:
            logger.warning(
                "readiness: schema behind — actual=%s expected=%s", actual, expected
            )
            return jsonify({
                "status": "not_ready",
                "reason": "schema_behind",
                "schema_version": actual,
                "expected_version": expected,
            }), 503

        return jsonify({
            "status": "ready",
            "schema_version": actual,
            "expected_version": expected,
        })

    except Exception:
        logger.exception("readiness: unexpected error")
        return jsonify({"status": "not_ready", "reason": "internal_error"}), 503


@bp.get("/metrics")
@require_auth("admin")
def metrics_endpoint():
    """Prometheus-compatible text metrics — admin only.

    Sensitive operational data. Protected by admin role requirement.
    """
    m = current_app.extensions.get("metrics")
    if m is None:
        return "# no metrics collector configured\n", 200, {"Content-Type": "text/plain; charset=utf-8"}
    return m.text_export(), 200, {"Content-Type": "text/plain; charset=utf-8"}
