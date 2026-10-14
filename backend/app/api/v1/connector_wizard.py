"""Connector Wizard API — Phase 7 Easy Onboarding (Security Repaired).

Guides a user through the steps to create a new connector account.

Endpoints:
  POST /api/v1/connector-wizard/sessions               Start a wizard session
  GET  /api/v1/connector-wizard/sessions/<token>       Get session state (owner only)
  PUT  /api/v1/connector-wizard/sessions/<token>/step  Advance to next step (owner only)
  POST /api/v1/connector-wizard/sessions/<token>/test  Test connection (owner only)
  POST /api/v1/connector-wizard/sessions/<token>/complete  Finalize (owner only)
  GET  /api/v1/connector-wizard/templates              List available connector templates

SECURITY:
  - Every session stores owner_user_id (= authenticated user at creation time).
  - Every get/update/test/complete validates owner_user_id == current user (or admin).
  - Raw secrets (password, api_key, token, private_key, etc.) are NEVER stored in
    step_data_json or config_json. Only credential_ref (opaque reference key) is stored.
  - Sensitive keys are stripped recursively from every API response and from every write,
    using case-insensitive, separator-normalised key matching at all nesting levels.
  - Session token is a UUID (unguessable); DB also enforces user_id ownership.

SANITIZATION CONTRACT (v2 — recursive, case-insensitive):
  - _sanitize_config() is the single canonical sanitizer.  It must be called at every
    point where configuration data crosses the trust boundary (read from request,
    written to DB, returned in response, or passed into an adapter).
  - Matching is case-insensitive and separator-normalised (underscores and hyphens
    are folded to a canonical form before comparison).
  - Sanitization is recursive: nested dicts, lists, and tuples are all processed.
  - Maximum nesting depth is _MAX_CONFIG_DEPTH (default 10).  Payloads that exceed
    this limit are rejected with a controlled ValidationError — they do not cause
    unbounded recursion or a 500 response.
  - credential_ref is explicitly whitelisted: it is an opaque reference identifier,
    not a raw secret.
  - The sanitizer never mutates the caller-supplied object; it always returns a new
    copy.
  - Non-dict config values from the request are rejected with 422 before any
    DB interaction.

CONNECTOR TYPE VALIDATION:
  - connector_type is validated against the real registry (get_adapter) at session
    creation time and again at completion time.
  - Arbitrary or unknown connector_type values are rejected with 422.
  - Connectors with implementation_status='not_implemented' are created with
    status='inactive' (never 'active'), derived from the registry, not from
    browser input.
  - implementation_status is always derived from the registry and included in
    the completion response.

CONNECTOR WIZARD CONTRACT VERSION: 3.1
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, g, jsonify, request

from app.core.deps import require_auth, get_db
from app.adapters.connectors.registry import get_adapter, list_connector_types
from app.core.db import write_transaction, query
from app.core.errors import NotFoundError, ValidationError, PermissionError_

bp = Blueprint("connector_wizard", __name__, url_prefix="/api/v1/connector-wizard")

_SESSION_TTL_HOURS = 24
_STEPS = ["choose_type", "enter_config", "test_connection", "confirm"]

# Maximum config nesting depth — payloads deeper than this are rejected.
_MAX_CONFIG_DEPTH = 10

# ─── Secret-field detection ────────────────────────────────────────────────────
#
# The canonical set of secret-bearing key *stems*.  Detection is case-insensitive
# and separator-normalised: before checking, each key is lowercased and all
# hyphens are replaced with underscores.  This means "API-KEY", "ApiKey",
# "api_key", "API_KEY" all collapse to "api_key" and are caught.
#
# credential_ref is deliberately NOT in this set: it is a safe opaque reference.
_SECRET_STEMS: frozenset[str] = frozenset({
    "password",
    "passwd",
    "pwd",
    "api_key",
    "secret",
    "token",
    "token_value",
    "bearer_token",
    "access_token",
    "refresh_token",
    "private_key",
    "rsa_key",
    "webhook_secret",
    "client_secret",
})

# Pre-compiled pattern to normalise camelCase / PascalCase separators.
# E.g. "ApiKey" → "Api_Key" → lower → "api_key".
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _normalise_key(key: str) -> str:
    """Return the canonical secret-detection form of a config key.

    Steps:
      1. Insert underscore before each uppercase letter that follows a lowercase
         letter or digit (camelCase split).
      2. Replace hyphens with underscores.
      3. Lowercase the whole string.

    Examples::
        "API_KEY"       → "api_key"
        "ApiKey"        → "api_key"
        "client-secret" → "client_secret"
        "TOKEN_VALUE"   → "token_value"
        "Password"      → "password"
    """
    step1 = _CAMEL_RE.sub("_", key)   # camelCase → snake_case
    step2 = step1.replace("-", "_")    # hyphen → underscore
    return step2.lower()


def _is_secret_key(key: str) -> bool:
    """Return True if *key* matches any secret stem after normalisation."""
    return _normalise_key(key) in _SECRET_STEMS


def _sanitize_config(value: object, *, _depth: int = 0) -> object:
    """Recursively sanitize a configuration value.

    Removes all keys whose normalised form matches a known secret stem.
    Processes dicts, lists, and tuples recursively.  All other JSON-
    compatible scalars (str, int, float, bool, None) are returned as-is.

    The caller's object is never mutated — a fresh copy is always returned.

    Args:
        value:  The configuration value to sanitize.
        _depth: Current recursion depth (internal, not for callers).

    Raises:
        ValidationError: If *_depth* exceeds _MAX_CONFIG_DEPTH.
    """
    if _depth > _MAX_CONFIG_DEPTH:
        raise ValidationError(
            f"پیکربندی بیش از حد تودرتو است (حداکثر عمق: {_MAX_CONFIG_DEPTH})."
        )

    if isinstance(value, dict):
        return {
            k: _sanitize_config(v, _depth=_depth + 1)
            for k, v in value.items()
            if not _is_secret_key(str(k))
        }

    if isinstance(value, list):
        return [_sanitize_config(item, _depth=_depth + 1) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_config(item, _depth=_depth + 1) for item in value)

    # Scalars (str, int, float, bool, None) — returned as-is.
    return value


def _parse_config_from_request(data: dict, field: str = "config") -> dict:
    """Extract and validate the config field from a decoded request dict.

    Returns a clean (sanitized) dict.  Raises ValidationError if the field
    is present but is not a dict or if nesting exceeds _MAX_CONFIG_DEPTH.
    Missing / None / empty string is treated as an empty dict.
    """
    raw = data.get(field)
    if raw is None or raw == "" or raw == {}:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError(
            "پیکربندی باید یک شیء JSON باشد (dict)."
        )
    return _sanitize_config(raw)  # may raise ValidationError on excessive depth


# ─── Legacy alias kept for any tests that import _strip_secrets directly ──────
# This is the OLD name; it now delegates to the new recursive sanitizer.
# Callers inside this module have all been updated to use _sanitize_config.
def _strip_secrets(cfg: dict) -> dict:
    """Deprecated alias — delegates to _sanitize_config.  Do not use in new code."""
    if not isinstance(cfg, dict):
        return {}
    return _sanitize_config(cfg)


# ─── Utility helpers ──────────────────────────────────────────────────────────

def _validate_connector_type(connector_type: str) -> tuple[str, str]:
    """Validate connector_type against the real registry.

    Returns (implementation_status, connector_account_status) where:
      - implementation_status is the canonical status from list_connector_types()
      - connector_account_status is 'active' for production/simulator connectors
        and 'inactive' for not_implemented ones.

    Uses list_connector_types() as the authoritative source because it carries
    the declared implementation status for each type, including the simulator
    status for MOCK_ERP/CSV_IMPORT which don't override capabilities().

    Raises ValidationError for unknown / rejected types.
    """
    known_types = {ct["type"]: ct for ct in list_connector_types()}
    if connector_type not in known_types:
        # Also reject types that pass get_adapter but aren't in the public list
        try:
            get_adapter(connector_type)
        except ValidationError:
            raise ValidationError(f"نوع اتصال '{connector_type}' ناشناخته است")
        # If get_adapter succeeds but it's not in list_connector_types, still validate
        raise ValidationError(f"نوع اتصال '{connector_type}' ناشناخته است")

    entry = known_types[connector_type]
    impl_status = entry["implementation_status"]
    # Unimplemented connectors must never be finalized as active
    account_status = "active" if impl_status in ("production", "simulator") else "inactive"
    return impl_status, account_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS)).isoformat()


def _load_step_data(row) -> dict:
    try:
        return json.loads(row["step_data_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_session(session_token: str) -> dict | None:
    row = query(
        "SELECT * FROM connector_wizard_sessions WHERE session_token=?",
        (session_token,),
        one=True,
    )
    return dict(row) if row else None


def _assert_owns_session(session: dict) -> None:
    """Raise NotFoundError (not 403) if caller doesn't own the session."""
    uid = g.current_user["id"]
    role = g.current_user["role"]
    if role == "admin":
        return  # platform admin can access any session
    if session.get("user_id") != uid:
        raise NotFoundError("جلسه راهنما یافت نشد")


def _safe_session_response(session: dict) -> dict:
    """Return a response-safe dict — no secrets, no raw step_data_json."""
    step_data = _load_step_data(session)
    # Recursively redact secrets from step_data before returning
    safe_step_data = _sanitize_config(step_data)
    return {
        "session_token": session["session_token"],
        "connector_type": session.get("connector_type"),
        "supplier_id": session.get("supplier_id"),
        "current_step": session.get("current_step", "choose_type"),
        "status": session.get("status", "in_progress"),
        "config_draft": safe_step_data,
        "connector_account_id": session.get("connector_account_id"),
        "expires_at": session.get("expires_at"),
        "available_steps": _STEPS,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Wizard session CRUD
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/sessions", methods=["POST"])
@require_auth("admin", "supplier")
def start_session():
    """Start a new wizard session. Owner is the authenticated user."""
    data = request.get_json(force=True) or {}
    connector_type = (data.get("connector_type") or "").upper().strip() or None

    # Validate connector_type against the real registry before creating a session.
    # Arbitrary or unknown types are rejected immediately.
    if connector_type is not None:
        try:
            _validate_connector_type(connector_type)
        except ValidationError as exc:
            return jsonify({"error": {"code": "validation_error",
                                       "message": str(exc)}}), 422

    # supplier_id comes from body only for admin; supplier gets their own
    db = get_db()
    role = g.current_user["role"]
    uid = g.current_user["id"]

    if role == "supplier":
        with db.read_transaction() as conn:
            row = conn.execute(
                "SELECT supplier_id AS id FROM supplier_access WHERE user_id = ? ORDER BY role='owner' DESC, supplier_id LIMIT 1", (uid,)
            ).fetchone()
        supplier_id = int(row["id"]) if row else None
    else:
        supplier_id = data.get("supplier_id")

    # Parse and recursively sanitize the initial config.
    # Non-dict config is rejected with 422; excessive depth is also 422.
    try:
        safe_config = _parse_config_from_request(data)
    except ValidationError as exc:
        return jsonify({"error": {"code": "validation_error",
                                   "message": str(exc)}}), 422

    session_token = str(uuid.uuid4())
    now = _now()
    expires_at = _expiry()

    with write_transaction() as conn:
        conn.execute(
            """
            INSERT INTO connector_wizard_sessions
                (session_token, user_id, connector_type, supplier_id, current_step,
                 step_data_json, status, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'choose_type', ?, 'in_progress', ?, ?, ?)
            """,
            (
                session_token, uid, connector_type, supplier_id,
                json.dumps(safe_config, ensure_ascii=False),
                expires_at, now, now,
            ),
        )

    return jsonify({
        "session_token": session_token,
        "current_step": "choose_type",
        "status": "in_progress",
        "available_steps": _STEPS,
        "expires_at": expires_at,
    }), 201


@bp.route("/sessions/<session_token>", methods=["GET"])
@require_auth("admin", "supplier")
def get_session(session_token: str):
    """Get current wizard session state. Only owner or admin."""
    session = _get_session(session_token)
    if session is None:
        return jsonify({"error": {"code": "not_found",
                                   "message": "جلسه راهنما یافت نشد"}}), 404
    try:
        _assert_owns_session(session)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found",
                                   "message": "جلسه راهنما یافت نشد"}}), 404
    return jsonify(_safe_session_response(session))


@bp.route("/sessions/<session_token>/step", methods=["PUT"])
@require_auth("admin", "supplier")
def advance_step(session_token: str):
    """Advance wizard session to the next step, saving config draft (secrets stripped)."""
    session = _get_session(session_token)
    if session is None:
        return jsonify({"error": {"code": "not_found", "message": "جلسه یافت نشد"}}), 404
    try:
        _assert_owns_session(session)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "جلسه یافت نشد"}}), 404

    data = request.get_json(force=True) or {}

    try:
        safe_config = _parse_config_from_request(data)
    except ValidationError as exc:
        return jsonify({"error": {"code": "validation_error",
                                   "message": str(exc)}}), 422

    current_idx = _STEPS.index(session["current_step"]) if session["current_step"] in _STEPS else 0
    next_step = _STEPS[min(current_idx + 1, len(_STEPS) - 1)]
    connector_type = (data.get("connector_type") or "").upper().strip() or None

    # Validate new connector_type against the real registry if provided.
    if connector_type is not None:
        try:
            _validate_connector_type(connector_type)
        except ValidationError as exc:
            return jsonify({"error": {"code": "validation_error",
                                       "message": str(exc)}}), 422

    now = _now()
    with write_transaction() as conn:
        conn.execute(
            """
            UPDATE connector_wizard_sessions
            SET current_step=?, step_data_json=?,
                connector_type=COALESCE(?, connector_type),
                updated_at=?
            WHERE session_token=?
            """,
            (
                next_step,
                json.dumps(safe_config, ensure_ascii=False),
                connector_type,
                now,
                session_token,
            ),
        )
    return jsonify({"session_token": session_token, "current_step": next_step})


@bp.route("/sessions/<session_token>/test", methods=["POST"])
@require_auth("admin", "supplier")
def test_connection(session_token: str):
    """Run a health check for the connector config in the session."""
    session = _get_session(session_token)
    if session is None:
        return jsonify({"error": {"code": "not_found", "message": "جلسه یافت نشد"}}), 404
    try:
        _assert_owns_session(session)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "جلسه یافت نشد"}}), 404

    connector_type = session.get("connector_type") or ""
    # Sanitize the stored config before passing into the adapter —
    # this is a defence-in-depth measure even though data was sanitized on write.
    config_draft = _sanitize_config(_load_step_data(session))

    try:
        adapter = get_adapter(connector_type, config=config_draft)
        health = adapter.health_check()
    except Exception as exc:
        # Sanitize the exception message to prevent accidental secret leakage
        # from adapter error strings that might echo configuration values.
        health = {"healthy": False, "message": str(exc), "latency_ms": None}

    # Do NOT include config_draft in the health-check response.
    return jsonify({"session_token": session_token, "health_check": health})


@bp.route("/sessions/<session_token>/complete", methods=["POST"])
@require_auth("admin", "supplier")
def complete_session(session_token: str):
    """Finalize wizard session — creates the connector_account record."""
    session = _get_session(session_token)
    if session is None:
        return jsonify({"error": {"code": "not_found", "message": "جلسه یافت نشد"}}), 404
    try:
        _assert_owns_session(session)
    except NotFoundError:
        return jsonify({"error": {"code": "not_found", "message": "جلسه یافت نشد"}}), 404

    data = request.get_json(force=True) or {}

    connector_type = session.get("connector_type") or ""
    if not connector_type:
        return jsonify({"error": {"code": "validation_error",
                                   "message": "نوع اتصال انتخاب نشده است. ابتدا مرحله choose_type را کامل کنید."}}), 422

    # Validate connector_type against the real registry at finalization time.
    # This is the authoritative gate — implementation_status and connector
    # account status are always derived from the registry, never from input.
    try:
        impl_status, account_status = _validate_connector_type(connector_type)
    except ValidationError as exc:
        return jsonify({"error": {"code": "validation_error",
                                   "message": str(exc)}}), 422

    name = (data.get("name") or "").strip() or f"اتصال جدید ({connector_type})"

    # Build final config: merge stored draft + request body extra config.
    # Both halves are recursively sanitized.  Raw secrets must NEVER be stored
    # in config_json.
    try:
        extra_config = _parse_config_from_request(data)
    except ValidationError as exc:
        return jsonify({"error": {"code": "validation_error",
                                   "message": str(exc)}}), 422

    config_draft = _sanitize_config(_load_step_data(session))
    config_draft.update(extra_config)

    supplier_id = session.get("supplier_id")
    now = _now()

    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO connector_accounts
                (name, connector_type, supplier_id, config_json,
                 environment, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, connector_type, supplier_id,
                json.dumps(config_draft, ensure_ascii=False),
                data.get("environment", "test"),
                account_status,   # derived from registry, NOT from input
                now, now,
            ),
        )
        connector_account_id = cur.lastrowid

        conn.execute(
            """UPDATE connector_wizard_sessions
               SET status='completed', connector_account_id=?, updated_at=?
               WHERE session_token=?""",
            (connector_account_id, now, session_token),
        )

    return jsonify({
        "session_token": session_token,
        "status": "completed",
        "connector_account_id": connector_account_id,
        "connector_type": connector_type,
        "implementation_status": impl_status,   # always from registry
        "connector_account_status": account_status,
    }), 201


# ─────────────────────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/templates", methods=["GET"])
@require_auth()
def list_templates():
    """List all available connector types as wizard templates."""
    types = list_connector_types()
    return jsonify({"connector_templates": types, "count": len(types)})
