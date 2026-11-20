"""Second factor for admin and staff accounts (ورود دومرحله‌ای مدیران).

TOTP (RFC 6238: HMAC-SHA1, 6 digits, 30-second steps, ±1 step drift) implemented
with the standard library; no new dependency. Any authenticator app works
(Google Authenticator, Microsoft Authenticator, Aegis, ...).

Flow (step-up, not a separate login): password/OTP/SSO login issues the usual
access token. Admin endpoints additionally require a token whose ``mfa`` claim
is true (deps.require_auth). The admin shell sends the user to /admin/mfa, where
``enroll_start``/``enroll_confirm`` (first time) or ``verify`` swap the session
for a new token with ``mfa=true``. The first login after deploy therefore lands
on enrollment, never on a dead end.

Secrets are encrypted at rest with Fernet; the key is derived from SECRET_KEY,
so rotating SECRET_KEY invalidates enrolled authenticators (recovery: another
super-admin resets the factor, or the user signs in with a recovery code).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.errors import ApiError, ConflictError, ValidationError
from app.services import audit_service

ISSUER = "60Online"
STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
MAX_FAILED_ATTEMPTS = 5
LOCK_SECONDS = 15 * 60


class MfaLocked(ApiError):
    status_code = 429
    code = "mfa_locked"


class MfaInvalid(ApiError):
    # Not 401: the browser client treats 401 as "session invalid" and drops the (valid) password session.
    status_code = 422
    code = "mfa_invalid_code"


# ── crypto helpers ──────────────────────────────────────────────────────────

def _fernet(secret_key: str) -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"60online-admin-mfa-v1", info=b"totp-secret").derive(
        secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(secret_key: str, raw: str) -> str:
    return _fernet(secret_key).encrypt(raw.encode("ascii")).decode("ascii")


def _decrypt(secret_key: str, token: str) -> str | None:
    try:
        return _fernet(secret_key).decrypt(token.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError):
        return None


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_at(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def _normalize_code(code) -> str:
    if not isinstance(code, str):
        return ""
    return code.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).replace(" ", "").strip()


def _match_step(secret_b32: str, code: str, now: float, last_used_step: int) -> int | None:
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int(now // STEP_SECONDS)
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if step > last_used_step and hmac.compare_digest(totp_at(secret_b32, step), code):
            return step
    return None


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(("60online-recovery:" + code.upper().replace("-", "")).encode("utf-8")).hexdigest()


# ── state ───────────────────────────────────────────────────────────────────

def status(conn, user_id: int) -> dict:
    row = conn.execute("SELECT status, activated_at FROM admin_mfa WHERE user_id = ?", (user_id,)).fetchone()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM admin_mfa_recovery_codes WHERE user_id = ? AND used_at IS NULL", (user_id,)
    ).fetchone()[0]
    return {
        "enrolled": bool(row and row["status"] == "active"),
        "activated_at": row["activated_at"] if row and row["status"] == "active" else None,
        "recovery_codes_remaining": int(remaining) if row and row["status"] == "active" else 0,
    }


def is_enrolled(conn, user_id: int) -> bool:
    row = conn.execute("SELECT status FROM admin_mfa WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row and row["status"] == "active")


def enroll_start(conn, *, user_id: int, email: str, secret_key: str, ip_address: str | None = None) -> dict:
    """Create (or replace) a PENDING secret. An active factor is never replaced here."""
    row = conn.execute("SELECT status FROM admin_mfa WHERE user_id = ?", (user_id,)).fetchone()
    if row and row["status"] == "active":
        raise ConflictError("ورود دومرحله‌ای برای این حساب فعال است", code="mfa_already_enrolled")
    raw = new_secret()
    enc = _encrypt(secret_key, raw)
    if row:
        conn.execute("UPDATE admin_mfa SET secret_enc = ?, last_used_step = 0, failed_attempts = 0, locked_until = NULL "
                     "WHERE user_id = ? AND status = 'pending'", (enc, user_id))
    else:
        conn.execute("INSERT INTO admin_mfa (user_id, secret_enc, status) VALUES (?, ?, 'pending')", (user_id, enc))
    audit_service.record(conn, action="admin.mfa_enroll_started", entity_type="user", entity_id=user_id,
                         actor_user_id=user_id, ip_address=ip_address)
    label = quote(f"{ISSUER}:{email}")
    uri = f"otpauth://totp/{label}?secret={raw}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    return {"secret": raw, "otpauth_uri": uri, "digits": DIGITS, "period": STEP_SECONDS}


def _check_lock(row, now: float) -> None:
    if row["locked_until"] and int(row["locked_until"]) > now:
        minutes = max(1, int((int(row["locked_until"]) - now + 59) // 60))
        raise MfaLocked(f"به دلیل تلاش‌های ناموفق، تأیید دومرحله‌ای تا {minutes} دقیقهٔ دیگر ممکن نیست",
                        details={"retry_after_seconds": int(int(row["locked_until"]) - now)})


def record_failure(conn, *, user_id: int, ip_address: str | None = None, now: float | None = None) -> None:
    """Count a wrong code. Call in its OWN transaction after MfaInvalid (the failing one rolls back)."""
    now = time.time() if now is None else now
    row = conn.execute("SELECT failed_attempts FROM admin_mfa WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return
    attempts = int(row["failed_attempts"]) + 1
    locked = int(now) + LOCK_SECONDS if attempts >= MAX_FAILED_ATTEMPTS else None
    conn.execute("UPDATE admin_mfa SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                 (0 if locked else attempts, locked, user_id))
    audit_service.record(conn, action="admin.mfa_failed", entity_type="user", entity_id=user_id,
                         actor_user_id=user_id, metadata={"locked": bool(locked)}, ip_address=ip_address)


def _new_recovery_codes(conn, user_id: int) -> list[str]:
    conn.execute("UPDATE admin_mfa_recovery_codes SET used_at = 'superseded' WHERE user_id = ? AND used_at IS NULL",
                 (user_id,))
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(5).upper()
        code = f"{raw[:5]}-{raw[5:]}"
        conn.execute("INSERT INTO admin_mfa_recovery_codes (user_id, code_hash) VALUES (?, ?)",
                     (user_id, _hash_recovery(code)))
        codes.append(code)
    return codes


def enroll_confirm(conn, *, user_id: int, code, secret_key: str, ip_address: str | None = None,
                   now: float | None = None) -> list[str]:
    """Activate the pending secret with a valid code. Returns the recovery codes (shown once)."""
    now = time.time() if now is None else now
    row = conn.execute("SELECT * FROM admin_mfa WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or row["status"] != "pending":
        raise ConflictError("ابتدا فعال‌سازی ورود دومرحله‌ای را شروع کنید", code="mfa_not_pending")
    _check_lock(row, now)
    raw = _decrypt(secret_key, row["secret_enc"])
    step = _match_step(raw, _normalize_code(code), now, int(row["last_used_step"])) if raw else None
    if step is None:
        raise MfaInvalid("کد تأیید نادرست یا منقضی است")
    conn.execute("UPDATE admin_mfa SET status = 'active', last_used_step = ?, failed_attempts = 0, locked_until = NULL, "
                 "activated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE user_id = ?", (step, user_id))
    codes = _new_recovery_codes(conn, user_id)
    audit_service.record(conn, action="admin.mfa_enrolled", entity_type="user", entity_id=user_id,
                         actor_user_id=user_id, ip_address=ip_address)
    return codes


def verify(conn, *, user_id: int, secret_key: str, code=None, recovery_code=None,
           ip_address: str | None = None, now: float | None = None) -> dict:
    """Check a TOTP code (or a one-time recovery code) for an ACTIVE factor."""
    now = time.time() if now is None else now
    row = conn.execute("SELECT * FROM admin_mfa WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or row["status"] != "active":
        raise ConflictError("ورود دومرحله‌ای برای این حساب فعال نشده است", code="mfa_not_enrolled")
    _check_lock(row, now)
    if recovery_code:
        norm = _normalize_code(recovery_code).upper()
        cur = conn.execute(
            "UPDATE admin_mfa_recovery_codes SET used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE user_id = ? AND code_hash = ? AND used_at IS NULL", (user_id, _hash_recovery(norm)))
        if cur.rowcount != 1:
            raise MfaInvalid("کد بازیابی نادرست است یا قبلاً استفاده شده است")
        conn.execute("UPDATE admin_mfa SET failed_attempts = 0, locked_until = NULL WHERE user_id = ?", (user_id,))
        audit_service.record(conn, action="admin.mfa_recovery_code_used", entity_type="user", entity_id=user_id,
                             actor_user_id=user_id, ip_address=ip_address)
        return {"method": "recovery_code", **status(conn, user_id)}
    raw = _decrypt(secret_key, row["secret_enc"])
    step = _match_step(raw, _normalize_code(code), now, int(row["last_used_step"])) if raw else None
    if step is None:
        raise MfaInvalid("کد تأیید نادرست یا منقضی است")
    conn.execute("UPDATE admin_mfa SET last_used_step = ?, failed_attempts = 0, locked_until = NULL WHERE user_id = ?",
                 (step, user_id))
    audit_service.record(conn, action="admin.mfa_verified", entity_type="user", entity_id=user_id,
                         actor_user_id=user_id, ip_address=ip_address)
    return {"method": "totp", **status(conn, user_id)}


def regenerate_recovery_codes(conn, *, user_id: int, ip_address: str | None = None) -> list[str]:
    if not is_enrolled(conn, user_id):
        raise ConflictError("ورود دومرحله‌ای برای این حساب فعال نشده است", code="mfa_not_enrolled")
    codes = _new_recovery_codes(conn, user_id)
    audit_service.record(conn, action="admin.mfa_recovery_codes_regenerated", entity_type="user", entity_id=user_id,
                         actor_user_id=user_id, ip_address=ip_address)
    return codes


def reset(conn, *, user_id: int, actor_user_id: int, reason: str, ip_address: str | None = None) -> None:
    """A super-admin removes another account's factor (lost phone). The user re-enrolls on next admin visit."""
    if user_id == actor_user_id:
        raise ValidationError("بازنشانی ورود دومرحله‌ای حساب خودتان از این مسیر مجاز نیست")
    conn.execute("DELETE FROM admin_mfa WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE admin_mfa_recovery_codes SET used_at = 'reset' WHERE user_id = ? AND used_at IS NULL",
                 (user_id,))
    audit_service.record(conn, action="admin.mfa_reset", entity_type="user", entity_id=user_id,
                         actor_user_id=actor_user_id, metadata={"reason": reason}, ip_address=ip_address)
