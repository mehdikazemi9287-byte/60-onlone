"""ورود مشترک vambi.ir ↔ 60online.ir with one-time codes.

Flow: a signed-in 60online user asks for a code for an allow-listed sister origin (issue); the browser is sent to
<origin>/sso/callback?code=..&state=..; that origin swaps the code for an ordinary session token (exchange).

- Allowed targets come only from server config: SSO_ALLOWED_ORIGINS (comma-separated, exact origins), defaulting to
  https://<VAMBI_DOMAIN> and https://www.<VAMBI_DOMAIN> (VAMBI_DOMAIN defaults to vambi.ir). In production only https origins
  are ever honoured, even if listed.
  http://localhost / http://127.0.0.1 (any port) are accepted only with SSO_ALLOW_LOCALHOST=1 AND outside production.
- Only SHA-256 hashes of the code and the state are stored. Codes live CODE_TTL_SECONDS and are single-use: the
  exchange marks the row used with UPDATE ... WHERE used_at IS NULL AND expires_at > now and checks rowcount, then
  commits before checking state/origin/user, so any misuse burns the code.
- Every failure of the exchange answers with the same error, so a caller cannot tell unknown, expired, used,
  wrong-state and wrong-origin codes apart.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import re
import secrets
from urllib.parse import urlencode, urlsplit

from app.core.errors import ApiError, AuthenticationError, PermissionError_, ValidationError
from app.services import audit_service

CODE_TTL_SECONDS = 60
ISSUE_PER_USER_10_MIN = 20
_STATE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_CODE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


class SsoRateLimited(ApiError):
    status_code = 429
    code = "sso_rate_limited"


def _invalid() -> AuthenticationError:
    return AuthenticationError("لینک ورود نامعتبر یا منقضی شده است؛ دوباره امتحان کن.", code="sso_invalid")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _normalize_origin(raw) -> str | None:
    """scheme://host[:port] in lower case, or None if `raw` is not exactly an origin (no path, query, user info)."""
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        return None
    if parts.path not in ("",) or parts.query or parts.fragment or raw.endswith("?") or raw.endswith("#"):
        return None
    host = parts.hostname.lower()
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def allowed_origins(production: bool) -> set[str]:
    raw = os.environ.get("SSO_ALLOWED_ORIGINS", "").strip()
    if raw:
        listed = [o.strip() for o in raw.split(",") if o.strip()]
    else:
        domain = (os.environ.get("VAMBI_DOMAIN", "").strip() or "vambi.ir").lower()
        listed = [f"https://{domain}", f"https://www.{domain}"]
    out = set()
    for item in listed:
        origin = _normalize_origin(item)
        if origin and (origin.startswith("https://") or not production):
            out.add(origin)
    return out


def is_allowed_origin(origin: str, production: bool) -> bool:
    if origin in allowed_origins(production):
        return True
    if production or os.environ.get("SSO_ALLOW_LOCALHOST", "").strip() != "1":
        return False
    host = urlsplit(origin).hostname or ""
    return origin.startswith("http://") and host in _LOCAL_HOSTS


def issue(conn, *, user_id: int, target_origin, state, production: bool, ip_address: str | None = None,
          now: _dt.datetime | None = None) -> dict:
    origin = _normalize_origin(target_origin)
    # Exact match only: a normalized-but-different spelling (e.g. upper case) is refused too.
    if origin is None or origin != target_origin or not is_allowed_origin(origin, production):
        raise ValidationError("مقصد ورود مجاز نیست.", code="sso_origin_not_allowed")
    if not isinstance(state, str) or not _STATE.match(state):
        raise ValidationError("پارامتر state نامعتبر است.", code="sso_invalid_state")
    row = conn.execute("SELECT is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not row["is_active"]:
        raise PermissionError_("حساب کاربری غیرفعال است.", code="account_disabled")
    now = now or _now()
    recent = conn.execute("SELECT COUNT(*) FROM sso_codes WHERE user_id = ? AND created_at > ?",
                          (user_id, _iso(now - _dt.timedelta(minutes=10)))).fetchone()[0]
    if recent >= ISSUE_PER_USER_10_MIN:
        raise SsoRateLimited("درخواست‌های ورود زیاد بود؛ چند دقیقهٔ دیگر امتحان کن.")
    # Housekeeping: codes are useless a minute after issue; keep a day for audit correlation.
    conn.execute("DELETE FROM sso_codes WHERE expires_at < ?", (_iso(now - _dt.timedelta(days=1)),))
    code = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sso_codes (code_hash, user_id, target_origin, state_hash, ip_address, created_at, expires_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (_sha(code), user_id, origin, _sha(state), ip_address, _iso(now),
         _iso(now + _dt.timedelta(seconds=CODE_TTL_SECONDS))),
    )
    audit_service.record(conn, action="auth.sso_issued", entity_type="user", entity_id=user_id, actor_user_id=user_id,
                         metadata={"target_origin": origin}, ip_address=ip_address)
    return {"redirect_url": f"{origin}/sso/callback?" + urlencode({"code": code, "state": state}),
            "expires_in": CODE_TTL_SECONDS}


def claim(db, *, code, state, request_origin: str | None, ip_address: str | None = None,
          now: _dt.datetime | None = None) -> int:
    """Burn the code (committed), then validate it. Returns the user id or raises the uniform sso_invalid error."""
    if not isinstance(code, str) or not _CODE.match(code) or not isinstance(state, str) or not _STATE.match(state):
        raise _invalid()
    now = now or _now()
    code_hash = _sha(code)
    with db.write_transaction() as conn:
        cur = conn.execute("UPDATE sso_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
                           (_iso(now), code_hash, _iso(now)))
        if cur.rowcount != 1:
            raise _invalid()
        row = conn.execute("SELECT s.user_id, s.target_origin, s.state_hash, u.is_active FROM sso_codes s"
                           " JOIN users u ON u.id = s.user_id WHERE s.code_hash = ?", (code_hash,)).fetchone()
    reason = None
    if row is None:
        reason = "missing"
    elif not hmac.compare_digest(row["state_hash"], _sha(state)):
        reason = "state_mismatch"
    elif request_origin is not None and request_origin != row["target_origin"]:
        reason = "origin_mismatch"
    elif not row["is_active"]:
        reason = "account_disabled"
    with db.write_transaction() as conn:
        audit_service.record(conn, action="auth.sso_exchange_failed" if reason else "auth.sso_exchanged",
                             entity_type="user", entity_id=row["user_id"] if row else None,
                             actor_user_id=row["user_id"] if row else None,
                             metadata={"target_origin": row["target_origin"] if row else None,
                                       **({"reason": reason} if reason else {})},
                             ip_address=ip_address)
    if reason:
        raise _invalid()
    return int(row["user_id"])
