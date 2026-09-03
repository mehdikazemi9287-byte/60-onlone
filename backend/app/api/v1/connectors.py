"""Connector Account API — Phase 6.

Manages third-party connector accounts (ERP integrations, marketplace feeds,
etc.) and exposes health-check + sync-trigger endpoints.

SECURITY: credential_ref is NEVER returned in any response — only the
connector account metadata is exposed.

URL structure:
  GET  /api/v1/connector-types               — public connector type registry
  GET  /api/v1/connectors                    — list accounts (auth required)
  GET  /api/v1/connectors/<id>               — get one account (no credentials)
  POST /api/v1/connectors/<id>/health        — run live health check via adapter
  POST /api/v1/connectors/<id>/sync          — trigger a full sync job
"""
from __future__ import annotations

import json

from flask import Blueprint, g, jsonify, request

from app.adapters.connectors.registry import get_adapter, list_connector_types
from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import sync_engine_service

bp = Blueprint("connectors_v6", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin() -> bool:
    return g.current_user.get("role") == "admin"


def _safe_account(row: dict) -> dict:
    """Strip credential_ref before returning to caller."""
    result = dict(row)
    result.pop("credential_ref", None)
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/connector-types")
def list_types():
    """Return all registered connector type descriptors. No auth required."""
    types = list_connector_types()
    return jsonify({"data": types})


@bp.get("/connectors")
@require_auth("supplier", "admin")
def list_connectors():
    """List connector accounts visible to the caller.

    Admins see all accounts. Suppliers see only their own.
    """
    db = get_db()
    supplier_id = request.args.get("supplier_id", type=int)

    # Supplier isolation: non-admins can only query their own supplier_id
    if not _is_admin():
        # supplier_id filter is ignored for non-admins; they get their own data
        # The service must enforce this via the user's linked supplier.
        pass

    with db.read_transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, name, connector_type, supplier_id, is_active,
                   config_json, last_synced_at, created_at, updated_at
            FROM connector_accounts
            WHERE (:supplier_id IS NULL OR supplier_id = :supplier_id)
              AND (:admin = 1 OR supplier_id IN (
                    SELECT id FROM suppliers WHERE user_id = :user_id
                  ))
            ORDER BY created_at DESC
            """,
            {
                "supplier_id": supplier_id,
                "admin": 1 if _is_admin() else 0,
                "user_id": g.current_user["id"],
            },
        ).fetchall()
    return jsonify({"data": [_safe_account(dict(r)) for r in rows]})


@bp.get("/connectors/<int:account_id>")
@require_auth("supplier", "admin")
def get_connector(account_id: int):
    """Get connector account detail. credential_ref is never returned."""
    db = get_db()
    with db.read_transaction() as conn:
        row = conn.execute(
            """
            SELECT id, name, connector_type, supplier_id, is_active,
                   config_json, last_synced_at, created_at, updated_at
            FROM connector_accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()

    if row is None:
        raise NotFoundError("حساب کانکتور یافت نشد")

    account = _safe_account(dict(row))

    # Supplier isolation: non-admins may only see their own supplier's accounts
    if not _is_admin():
        db2 = get_db()
        with db2.read_transaction() as conn2:
            sup = conn2.execute(
                "SELECT id FROM suppliers WHERE user_id = ?",
                (g.current_user["id"],),
            ).fetchone()
        if sup is None or int(account.get("supplier_id", -1)) != sup["id"]:
            raise NotFoundError("حساب کانکتور یافت نشد")

    return jsonify({"data": account})


@bp.post("/connectors/<int:account_id>/health")
@require_auth("supplier", "admin")
def connector_health(account_id: int):
    """Run a live health check against the connector's remote endpoint."""
    db = get_db()
    with db.read_transaction() as conn:
        row = conn.execute(
            "SELECT id, connector_type, config_json FROM connector_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()

    if row is None:
        raise NotFoundError("حساب کانکتور یافت نشد")

    connector_type = row["connector_type"]
    try:
        config = json.loads(row["config_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        config = {}

    adapter = get_adapter(connector_type, config=config)
    health  = adapter.health_check()
    return jsonify({"data": health})


@bp.post("/connectors/<int:account_id>/sync")
@require_auth("supplier", "admin")
def trigger_sync(account_id: int):
    """Trigger a full sync job for this connector account."""
    db   = get_db()
    body = request.get_json(silent=True) or {}
    job_type = (body.get("job_type") or "inventory").strip()

    with db.read_transaction() as conn:
        row = conn.execute(
            "SELECT id, supplier_id FROM connector_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()

    if row is None:
        raise NotFoundError("حساب کانکتور یافت نشد")

    with db.write_transaction() as conn:
        result = sync_engine_service.run_full_sync(
            conn,
            connector_account_id=account_id,
            job_type=job_type,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": result}), 201
