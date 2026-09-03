"""Accounting Connectors API — Phase 7 (Security Repaired).

Endpoints:
  GET  /api/v1/accounting-connectors            List connectors (scoped by role)
  POST /api/v1/accounting-connectors            Create connector account
  GET  /api/v1/accounting-connectors/<id>       Get single connector
  GET  /api/v1/accounting-connectors/<id>/health  Health check
  POST /api/v1/accounting-connectors/<id>/export-invoice  Export order invoice
  POST /api/v1/accounting-connectors/<id>/export-payment  Export order payment
  GET  /api/v1/accounting-connectors/<id>/documents  List accounting documents
  GET  /api/v1/accounting-systems               List supported accounting systems

SECURITY:
  - supplier_id is ALWAYS derived server-side from the authenticated user record.
    body/query supplier_id is IGNORED for suppliers.
  - Platform admin may access all connectors.
  - Supplier may only access connectors whose supplier_id == their server-derived id.
  - Customer role cannot administer connectors (403).
  - Cross-tenant access returns 404 (not 403, to avoid existence leakage).
  - credential_ref and secret-bearing config fields are NEVER returned in responses.
  - implementation_status is derived from the adapter registry — never hardcoded 'simulator'.
  - Unimplemented adapters (Sepidar, Rahkaran, Holo, SAP, Odoo) are created with
    implementation_status='not_implemented' and status='disabled'.
"""
from __future__ import annotations

import json
from flask import Blueprint, g, jsonify, request

from app.core.deps import require_auth, get_db
from app.services import accounting_service
from app.adapters.accounting.registry import (
    get_accounting_adapter, list_accounting_systems, _REGISTRY,
)
from app.adapters.accounting.mock import MockAccountingAdapter
from app.adapters.accounting.csv_export import CsvAccountingExportAdapter
from app.core.errors import NotFoundError, ValidationError, PermissionError_
from app.core.db import write_transaction
from datetime import datetime, timezone

bp = Blueprint("accounting_connectors", __name__, url_prefix="/api/v1")

# Fields that must never appear in API responses
_SECRET_FIELDS = frozenset({
    "credential_ref", "password", "api_key", "secret", "token",
    "bearer_token", "private_key", "rsa_key", "webhook_secret",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_caller_supplier_id(db) -> int | None:
    """Return server-derived supplier_id for authenticated supplier user; None otherwise."""
    if g.current_user["role"] != "supplier":
        return None
    with db.read_transaction() as conn:
        row = conn.execute(
            "SELECT id FROM suppliers WHERE user_id = ?", (g.current_user["id"],)
        ).fetchone()
    return int(row["id"]) if row else None


def _require_supplier_id(db) -> int:
    """Derive supplier_id from auth. Raises ValidationError if not found."""
    sid = _get_caller_supplier_id(db)
    if sid is None:
        raise ValidationError("حساب تأمین‌کننده یافت نشد")
    return sid


def _require_not_customer() -> None:
    """Customers cannot administer connectors."""
    role = g.current_user["role"]
    if role == "customer":
        raise PermissionError_("مشتریان به مدیریت اتصال‌ها دسترسی ندارند")


def _redact(connector: dict) -> dict:
    """Remove secret-bearing fields from a connector dict before returning."""
    result = {}
    for k, v in connector.items():
        if k in _SECRET_FIELDS:
            result[k] = None  # redacted
        elif k == "config_json" and v:
            # Parse and redact secret keys from config
            try:
                cfg = json.loads(v)
                cfg_clean = {ck: (None if ck in _SECRET_FIELDS else cv) for ck, cv in cfg.items()}
                result["config"] = cfg_clean
            except (json.JSONDecodeError, TypeError):
                result["config"] = {}
        else:
            result[k] = v
    # Remove raw config_json — callers get "config" dict instead
    result.pop("config_json", None)
    return result


def _derive_implementation_status(accounting_system: str) -> tuple[str, str]:
    """Return (implementation_status, initial_status) derived from the adapter registry.

    MOCK and CSV adapters are simulators and start 'active'.
    All real-provider adapters (Sepidar, Rahkaran, Holo, SAP, Odoo) are
    'not_implemented' and start 'disabled'.
    """
    key = accounting_system.upper().strip()
    cls = _REGISTRY.get(key)
    if cls is None:
        return "not_implemented", "disabled"
    if cls in (MockAccountingAdapter, CsvAccountingExportAdapter):
        return "simulator", "active"
    # Real providers that are not yet implemented
    return "not_implemented", "disabled"


def _assert_connector_access(connector: dict) -> None:
    """Raise NotFoundError (not 403) if caller cannot access this connector.

    - admin can access all
    - supplier: connector.supplier_id must match server-derived id
    - customer: blocked at route level
    """
    role = g.current_user["role"]
    if role == "admin":
        return
    if role == "supplier":
        db = get_db()
        caller_sid = _get_caller_supplier_id(db)
        if caller_sid is None or connector.get("supplier_id") != caller_sid:
            raise NotFoundError("اتصال یافت نشد")
        return
    # employee / anything else: block
    raise PermissionError_("شما به این بخش دسترسی ندارید")


# ─────────────────────────────────────────────────────────────────────────────
# Connector account CRUD
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/accounting-connectors", methods=["GET"])
@require_auth("admin", "supplier")
def list_connectors():
    """List connectors. Admin sees all; supplier sees only theirs."""
    db = get_db()
    role = g.current_user["role"]

    if role == "admin":
        supplier_id = request.args.get("supplier_id", type=int)
        organization_id = request.args.get("organization_id", type=int)
    else:
        # supplier — always derive from auth, ignore query params
        supplier_id = _require_supplier_id(db)
        organization_id = None

    connectors = accounting_service.list_accounting_connectors(
        supplier_id=supplier_id,
        organization_id=organization_id,
    )
    return jsonify({
        "accounting_connectors": [_redact(c) for c in connectors],
        "count": len(connectors),
    })


@bp.route("/accounting-connectors", methods=["POST"])
@require_auth("admin", "supplier")
def create_connector():
    """Create connector account. supplier_id derived from auth for supplier role."""
    _require_not_customer()
    db = get_db()
    data = request.get_json(force=True) or {}
    name = data.get("name", "").strip()
    accounting_system = data.get("accounting_system", "").upper().strip()
    if not name or not accounting_system:
        return jsonify({"error": {"code": "validation_error",
                                   "message": "name و accounting_system الزامی است"}}), 422

    # Validate accounting_system is known
    try:
        get_accounting_adapter(accounting_system)
    except ValidationError as exc:
        return jsonify({"error": {"code": "validation_error", "message": str(exc)}}), 422

    role = g.current_user["role"]
    if role == "supplier":
        # Server-side: ignore body.supplier_id entirely
        supplier_id = _require_supplier_id(db)
        organization_id = None
    else:
        # admin: trust body
        supplier_id = data.get("supplier_id")
        organization_id = data.get("organization_id")

    # Derive truthful implementation_status from adapter registry
    impl_status, initial_status = _derive_implementation_status(accounting_system)

    # Never store raw secrets — only credential_ref (an opaque reference key)
    credential_ref = data.get("credential_ref", "") or ""

    # Sanitize config: strip any secret-bearing keys before storing
    raw_config = data.get("config", {}) or {}
    safe_config = {k: v for k, v in raw_config.items() if k not in _SECRET_FIELDS}

    now = _now()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO accounting_connector_accounts
                (name, accounting_system, implementation_status,
                 supplier_id, organization_id, credential_ref, config_json,
                 environment, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, accounting_system, impl_status,
                supplier_id, organization_id,
                credential_ref,
                json.dumps(safe_config, ensure_ascii=False),
                data.get("environment", "test"),
                initial_status,
                now, now,
            ),
        )
        connector_id = cur.lastrowid

    try:
        connector = accounting_service.get_accounting_connector(connector_id)
    except NotFoundError:
        connector = {"id": connector_id}
    return jsonify(_redact(connector)), 201


@bp.route("/accounting-connectors/<int:connector_id>", methods=["GET"])
@require_auth("admin", "supplier")
def get_connector(connector_id: int):
    try:
        connector = accounting_service.get_accounting_connector(connector_id)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
    try:
        _assert_connector_access(connector)
    except (NotFoundError, PermissionError_):
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
    return jsonify(_redact(connector))


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/accounting-connectors/<int:connector_id>/health", methods=["GET"])
@require_auth("admin", "supplier")
def health_check(connector_id: int):
    try:
        connector = accounting_service.get_accounting_connector(connector_id)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
    try:
        _assert_connector_access(connector)
    except (NotFoundError, PermissionError_):
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404

    # Unimplemented adapters fail closed — no health check performed
    if connector.get("implementation_status") == "not_implemented":
        return jsonify({
            "connector_id": connector_id,
            "health": {
                "healthy": False,
                "message": "این اتصال‌دهنده پیاده‌سازی نشده است — غیرفعال",
                "latency_ms": None,
            },
            "capabilities": {
                "implementation_status": "not_implemented",
                "supported": [],
            },
        })

    config = {}
    try:
        raw = connector.get("config_json") or "{}"
        cfg = json.loads(raw)
        # Never pass secret keys to adapter calls
        config = {k: v for k, v in cfg.items() if k not in _SECRET_FIELDS}
    except (json.JSONDecodeError, TypeError):
        pass

    adapter = get_accounting_adapter(connector["accounting_system"], config=config)
    result = adapter.health_check()
    caps = adapter.capabilities()
    return jsonify({"connector_id": connector_id, "health": result, "capabilities": caps})


# ─────────────────────────────────────────────────────────────────────────────
# Export operations
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/accounting-connectors/<int:connector_id>/export-invoice", methods=["POST"])
@require_auth("admin", "supplier")
def export_invoice(connector_id: int):
    data = request.get_json(force=True) or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": {"code": "validation_error",
                                   "message": "order_id الزامی است"}}), 422
    try:
        connector = accounting_service.get_accounting_connector(connector_id)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
    try:
        _assert_connector_access(connector)
    except (NotFoundError, PermissionError_):
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404

    if connector.get("implementation_status") == "not_implemented":
        return jsonify({"error": {"code": "not_implemented",
                                   "message": "این اتصال‌دهنده پیاده‌سازی نشده است"}}), 501

    try:
        result = accounting_service.export_order_invoice(
            int(order_id), connector_account_id=connector_id
        )
    except NotFoundError as exc:
        return jsonify({"error": {"code": "not_found", "message": str(exc)}}), 404
    except Exception as exc:
        return jsonify({"error": {"code": "export_error", "message": str(exc)}}), 500
    return jsonify(result)


@bp.route("/accounting-connectors/<int:connector_id>/export-payment", methods=["POST"])
@require_auth("admin", "supplier")
def export_payment(connector_id: int):
    data = request.get_json(force=True) or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": {"code": "validation_error",
                                   "message": "order_id الزامی است"}}), 422
    try:
        connector = accounting_service.get_accounting_connector(connector_id)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
    try:
        _assert_connector_access(connector)
    except (NotFoundError, PermissionError_):
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404

    if connector.get("implementation_status") == "not_implemented":
        return jsonify({"error": {"code": "not_implemented",
                                   "message": "این اتصال‌دهنده پیاده‌سازی نشده است"}}), 501

    try:
        result = accounting_service.export_order_payment(
            int(order_id), connector_account_id=connector_id
        )
    except NotFoundError as exc:
        return jsonify({"error": {"code": "not_found", "message": str(exc)}}), 404
    except Exception as exc:
        return jsonify({"error": {"code": "export_error", "message": str(exc)}}), 500
    return jsonify(result)


# ─────────────────────────────────────────────────────────────────────────────
# Documents
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/accounting-connectors/<int:connector_id>/documents", methods=["GET"])
@require_auth("admin", "supplier")
def list_documents(connector_id: int):
    try:
        connector = accounting_service.get_accounting_connector(connector_id)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404
    try:
        _assert_connector_access(connector)
    except (NotFoundError, PermissionError_):
        return jsonify({"error": {"code": "not_found", "message": "اتصال یافت نشد"}}), 404

    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    docs = accounting_service.list_accounting_documents(
        connector_account_id=connector_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return jsonify({"accounting_documents": docs, "count": len(docs)})


# ─────────────────────────────────────────────────────────────────────────────
# System listing
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/accounting-systems", methods=["GET"])
@require_auth()
def list_systems():
    """List all supported accounting systems."""
    systems = list_accounting_systems()
    return jsonify({"accounting_systems": systems})
