"""Partner API-key authentication, HMAC signing and per-key rate limiting.

Key format sent by partners:   X-Api-Key: <prefix>.<secret>
  * prefix  — public, unique, shown in admin lists (e.g. ``pk_3f9a1c2b7d``)
  * secret  — 32 random bytes (url-safe); only sha256(secret) is stored.

Signing secrets (inbound HMAC + outbound webhooks) are never stored either:
they are derived as HMAC-SHA256(server_secret_key, "partner-signing:" + salt),
so a database dump alone cannot forge signatures. Rotating the server
secret_key therefore invalidates every signing secret (documented).

Signature header (both directions):
    X-60Online-Signature: t=<unix-ts>,v1=<hex hmac_sha256(secret, f"{t}.{raw_body}")>
Replay window: 300 seconds.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Callable

from flask import current_app, g, request

from app.core.errors import ApiError, AuthenticationError, PermissionError_
from app.core.rate_limiter import InMemoryRateLimiter

SCOPES: tuple[str, ...] = (
    "catalog:read", "offers:write", "orders:read", "orders:write",
    "shipments:write", "invoices:read", "credit:read",
)
SIGNATURE_HEADER = "X-60Online-Signature"
SIGNATURE_TOLERANCE_SECONDS = 300
_DUMMY_HASH = hashlib.sha256(b"partner-dummy").hexdigest()


class RateLimitedError(ApiError):
    status_code = 429
    code = "rate_limited"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ----------------------------------------------------------------- key material
def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (prefix, plaintext_key). The caller stores only hash_secret(secret)."""
    prefix = "pk_" + secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return prefix, f"{prefix}.{secret}"


def split_key(raw: str) -> tuple[str, str] | None:
    raw = (raw or "").strip()
    if raw.count(".") != 1:
        return None
    prefix, secret = raw.split(".", 1)
    if not prefix.startswith("pk_") or len(prefix) > 40 or not secret or len(secret) > 200:
        return None
    return prefix, secret


def new_salt() -> str:
    return secrets.token_hex(16)


def derive_signing_secret(master_key: str, salt: str) -> str:
    digest = hmac.new(master_key.encode("utf-8"), f"partner-signing:{salt}".encode(), hashlib.sha256)
    return "whsec_" + digest.hexdigest()


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ signatures
def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else int(timestamp)
    mac = hmac.new(secret.encode("utf-8"), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secret: str, header: str | None, body: bytes, *, now: int | None = None,
                     tolerance: int = SIGNATURE_TOLERANCE_SECONDS) -> bool:
    if not header:
        return False
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        k, _, v = item.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        ts = int(parts.get("t", [""])[0])
    except ValueError:
        return False
    current = int(time.time()) if now is None else int(now)
    if abs(current - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode("utf-8"), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    ok = False
    for candidate in parts.get("v1", []):
        ok = hmac.compare_digest(expected, candidate) or ok
    return ok


# ------------------------------------------------------------------ rate limit
_limiters: dict[tuple[int, int, int], InMemoryRateLimiter] = {}
_limiters_lock = threading.Lock()


def _limiter_for(app_key: int, client_id: int, per_minute: int) -> InMemoryRateLimiter:
    key = (app_key, client_id, per_minute)
    with _limiters_lock:
        limiter = _limiters.get(key)
        if limiter is None:
            limiter = InMemoryRateLimiter(per_minute, 60)
            _limiters[key] = limiter
        return limiter


# --------------------------------------------------------------- authentication
def authenticate_api_key(conn, raw_key: str | None) -> dict:
    parsed = split_key(raw_key or "")
    row = None
    if parsed:
        row = conn.execute(
            """SELECT k.id AS key_id, k.prefix, k.secret_hash, k.status AS key_status,
                      c.id AS client_id, c.name, c.owner_type, c.owner_user_id, c.organization_id,
                      c.supplier_id, c.scopes_json, c.status AS client_status, c.rate_limit_per_minute,
                      c.signing_salt
               FROM partner_api_keys k JOIN partner_api_clients c ON c.id = k.client_id
               WHERE k.prefix = ?""", (parsed[0],)).fetchone()
    presented = hash_secret(parsed[1]) if parsed else _DUMMY_HASH
    stored = row["secret_hash"] if row else _DUMMY_HASH
    if not hmac.compare_digest(presented, stored) or row is None or not parsed:
        raise AuthenticationError("کلید API نامعتبر است", code="invalid_api_key")
    if row["key_status"] != "active":
        raise AuthenticationError("کلید API باطل شده است", code="api_key_revoked")
    if row["client_status"] != "active":
        raise AuthenticationError("دسترسی این مشتری API غیرفعال است", code="client_inactive")
    client = dict(row)
    client.pop("secret_hash", None)
    client["scopes"] = json.loads(client.pop("scopes_json") or "[]")
    return client


def require_api_key(*scopes: str) -> Callable:
    """Authenticate X-Api-Key, enforce per-key rate limit, then require every scope."""
    for s in scopes:
        if s not in SCOPES:
            raise ValueError(f"unknown scope {s}")

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            db = current_app.extensions["db"]
            with db.read_transaction() as conn:
                client = authenticate_api_key(conn, request.headers.get("X-Api-Key"))
            limiter = _limiter_for(id(current_app), client["client_id"], int(client["rate_limit_per_minute"]))
            bucket = f"partner:{client['client_id']}"
            if not limiter.is_allowed(bucket):
                g.partner_retry_after = limiter.retry_after(bucket)
                raise RateLimitedError("تعداد درخواست‌ها از سقف مجاز بیشتر است",
                                       details={"retry_after": g.partner_retry_after})
            missing = [s for s in scopes if s not in client["scopes"]]
            if missing:
                raise PermissionError_("این کلید مجوز لازم را ندارد", code="insufficient_scope",
                                       details={"required_scopes": list(scopes)})
            stamp = now_iso()
            with db.write_transaction() as conn:
                conn.execute("UPDATE partner_api_keys SET last_used_at=? WHERE id=?", (stamp, client["key_id"]))
                conn.execute("UPDATE partner_api_clients SET last_used_at=? WHERE id=?", (stamp, client["client_id"]))
            g.partner = client
            return view(*args, **kwargs)

        return wrapper

    return decorator
