"""ورود با کد یک‌بارمصرف (OTP پیامکی).

- Codes: 6 digits, valid 2 minutes, stored only as HMAC-SHA256(secret, phone|code); max 5 wrong tries per code.
- Sending limits live in the database (safe across workers): 1 per phone per 60 s, 5 per phone per hour, 20 per IP per hour.
- No account enumeration: requesting a code answers the same for known and unknown numbers.
- OTP login trusts only users.phone_verified. A free-text users.phone is never linked automatically; a signed-in user
  proves their number with purpose='link'. An unknown verified number creates a customer account (name required).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import re
import secrets
import sqlite3

from app.adapters.sms import ConsoleSms, SmsError, sender_from_env
from app.core.errors import ApiError, AuthenticationError, ConflictError, ValidationError
from app.core.security import hash_password
from app.services import audit_service

CODE_TTL_SECONDS = 120
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
PER_PHONE_HOUR = 5
PER_IP_HOUR = 20
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MOBILE = re.compile(r"^09\d{9}$")


class RateLimited(ApiError):
    status_code = 429
    code = "otp_rate_limited"


class OtpWrong(AuthenticationError):
    """Wrong code for a live challenge. The caller rolls back, then counts the attempt via count_attempt()."""
    def __init__(self, challenge_id: int):
        super().__init__("کد واردشده درست نیست یا منقضی شده است", code="otp_invalid")
        self.challenge_id = challenge_id


def count_attempt(conn, challenge_id: int) -> None:
    conn.execute("UPDATE otp_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))


class SmsUnavailable(ApiError):
    status_code = 503
    code = "sms_unavailable"


def normalize_phone(raw) -> str:
    """Iranian mobile → 09xxxxxxxxx. Accepts +98 / 0098 / 98 / 9xxxxxxxxx and Persian digits."""
    s = re.sub(r"[\s\-()]", "", str(raw or "").translate(_DIGITS))
    for p in ("+98", "0098"):
        if s.startswith(p):
            s = "0" + s[len(p):]
    if s.startswith("98") and len(s) == 12:
        s = "0" + s[2:]
    if len(s) == 10 and s.startswith("9"):
        s = "0" + s
    if not _MOBILE.match(s):
        raise ValidationError("شمارهٔ موبایل معتبر نیست (مثل ۰۹۱۲۱۲۳۴۵۶۷)", code="invalid_phone")
    return s


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(secret: str, phone: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{phone}|{code}".encode(), hashlib.sha256).hexdigest()


def request_code(conn: sqlite3.Connection, *, phone: str, secret: str, purpose: str = "login", user_id: int | None = None,
                 ip_address: str | None = None, production: bool = False, sender=None, now: _dt.datetime | None = None) -> dict:
    phone = normalize_phone(phone)
    t = now or _now()
    hour_ago, minute_ago = _iso(t - _dt.timedelta(hours=1)), _iso(t - _dt.timedelta(seconds=RESEND_SECONDS))
    last = conn.execute("SELECT created_at FROM otp_challenges WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,)).fetchone()
    if last and last["created_at"] > minute_ago:
        raise RateLimited("کمی صبر کن و دوباره درخواست کد بده", details={"retry_after_seconds": RESEND_SECONDS})
    if conn.execute("SELECT COUNT(*) FROM otp_challenges WHERE phone=? AND created_at>?", (phone, hour_ago)).fetchone()[0] >= PER_PHONE_HOUR:
        raise RateLimited("تعداد درخواست کد برای این شماره زیاد بوده؛ یک ساعت دیگر امتحان کن")
    if ip_address and conn.execute("SELECT COUNT(*) FROM otp_challenges WHERE ip_address=? AND created_at>?",
                                   (ip_address, hour_ago)).fetchone()[0] >= PER_IP_HOUR:
        raise RateLimited("تعداد درخواست‌ها زیاد بوده؛ بعداً امتحان کن")
    if purpose == "link":
        owner = conn.execute("SELECT id FROM users WHERE phone_verified=?", (phone,)).fetchone()
        if owner and owner["id"] != user_id:
            raise ConflictError("این شماره به حساب دیگری متصل است", code="phone_taken")
    try:
        sender = sender or sender_from_env()
    except SmsError as exc:
        raise SmsUnavailable(str(exc)) from exc
    if production and isinstance(sender, ConsoleSms):
        raise SmsUnavailable("سرویس پیامک روی سرور تنظیم نشده است")
    code = f"{secrets.randbelow(1_000_000):06d}"
    # Earlier unused codes for this phone stop working once a new one is issued.
    conn.execute("UPDATE otp_challenges SET consumed_at=? WHERE phone=? AND consumed_at IS NULL", (_iso(t), phone))
    conn.execute("INSERT INTO otp_challenges (phone, purpose, user_id, code_hash, ip_address, expires_at, created_at) VALUES (?,?,?,?,?,?,?)",
                 (phone, purpose, user_id, _hash(secret, phone, code), ip_address, _iso(t + _dt.timedelta(seconds=CODE_TTL_SECONDS)), _iso(t)))
    try:
        sender.send_code(phone, code)
    except SmsError as exc:
        raise SmsUnavailable(str(exc)) from exc
    return {"sent": True, "expires_in_seconds": CODE_TTL_SECONDS, "resend_in_seconds": RESEND_SECONDS}


def _check(conn, *, phone: str, code: str, secret: str, purpose: str, user_id: int | None, now) -> sqlite3.Row:
    code = str(code or "").translate(_DIGITS).strip()
    bad = AuthenticationError("کد واردشده درست نیست یا منقضی شده است", code="otp_invalid")
    ch = conn.execute("SELECT * FROM otp_challenges WHERE phone=? AND purpose=? AND consumed_at IS NULL ORDER BY id DESC LIMIT 1",
                      (phone, purpose)).fetchone()
    if ch is None or ch["expires_at"] <= _iso(now) or ch["attempts"] >= MAX_ATTEMPTS or (purpose == "link" and ch["user_id"] != user_id):
        raise bad
    if not re.fullmatch(r"\d{6}", code) or not hmac.compare_digest(ch["code_hash"], _hash(secret, phone, code)):
        raise OtpWrong(ch["id"])
    return ch


def verify_login(conn: sqlite3.Connection, *, phone: str, code: str, secret: str, full_name: str | None = None,
                 ip_address: str | None = None, now: _dt.datetime | None = None) -> tuple[int, bool]:
    """→ (user_id, created). Raises OtpWrong on a wrong code (see count_attempt)."""
    phone = normalize_phone(phone)
    t = now or _now()
    ch = _check(conn, phone=phone, code=code, secret=secret, purpose="login", user_id=None, now=t)
    row = conn.execute("SELECT id, is_active FROM users WHERE phone_verified=?", (phone,)).fetchone()
    created = False
    if row is None:
        name = (full_name or "").strip()
        if not 2 <= len(name) <= 120:
            # Code stays valid: the client asks for the name and verifies again.
            raise ValidationError("برای ساخت حساب، نام و نام خانوادگی را وارد کن", code="full_name_required")
        email = f"{phone}@phone.60online.ir"
        uid = conn.execute("INSERT INTO users (email, email_normalized, password_hash, full_name, phone, phone_verified, role) "
                           "VALUES (?,?,?,?,?,?, 'customer')",
                           (email, email, hash_password(secrets.token_urlsafe(24)), name, phone, phone)).lastrowid
        created = True
        audit_service.record(conn, action="user.registered", entity_type="user", entity_id=uid, actor_user_id=uid,
                             metadata={"method": "otp", "role": "customer"}, ip_address=ip_address)
    else:
        uid = row["id"]
        if not row["is_active"]:
            raise AuthenticationError("حساب کاربری غیرفعال است", code="account_disabled")
    conn.execute("UPDATE otp_challenges SET consumed_at=? WHERE id=?", (_iso(t), ch["id"]))
    audit_service.record(conn, action="user.logged_in", entity_type="user", entity_id=uid, actor_user_id=uid,
                         metadata={"method": "otp"}, ip_address=ip_address)
    return int(uid), created


def verify_link(conn: sqlite3.Connection, *, user_id: int, phone: str, code: str, secret: str,
                ip_address: str | None = None, now: _dt.datetime | None = None) -> str:
    phone = normalize_phone(phone)
    t = now or _now()
    ch = _check(conn, phone=phone, code=code, secret=secret, purpose="link", user_id=user_id, now=t)
    owner = conn.execute("SELECT id FROM users WHERE phone_verified=?", (phone,)).fetchone()
    if owner and owner["id"] != user_id:
        raise ConflictError("این شماره به حساب دیگری متصل است", code="phone_taken")
    conn.execute("UPDATE users SET phone=?, phone_verified=? WHERE id=?", (phone, phone, user_id))
    conn.execute("UPDATE otp_challenges SET consumed_at=? WHERE id=?", (_iso(t), ch["id"]))
    audit_service.record(conn, action="user.phone_verified", entity_type="user", entity_id=user_id, actor_user_id=user_id,
                         metadata={"phone_tail": phone[-4:]}, ip_address=ip_address)
    return phone
