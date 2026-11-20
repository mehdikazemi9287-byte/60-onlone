"""Registration and login."""
from __future__ import annotations

import re
import sqlite3
import time

from app.core.db import Database
from app.core.errors import ApiError, AuthenticationError, ConflictError, ValidationError
from app.core.security import create_access_token, hash_password, verify_password
from app.services import audit_service

# Persian/Arabic-Indic digits typed on mobile keyboards are stored as ASCII digits.
_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MIN_PASSWORD_LENGTH = 8
VALID_ROLES = {"customer", "employee", "supplier", "org_admin", "admin"}


class AccountLocked(ApiError):
    status_code = 429
    code = "account_locked"


def _lock_message(seconds_left: int) -> str:
    minutes = max(1, (seconds_left + 59) // 60)
    return (f"به دلیل چند تلاش ناموفق، ورود با رمز عبور به این حساب تا {minutes} دقیقهٔ دیگر ممکن نیست. "
            "می‌توانید با کد پیامکی وارد شوید یا از پشتیبانی بخواهید حساب را باز کند.")


def _check_lockout(db: Database, user_id: int, now: int) -> None:
    row = db.query_one("SELECT locked_until FROM login_lockouts WHERE user_id = ?", (user_id,))
    if row is not None and row["locked_until"] and int(row["locked_until"]) > now:
        left = int(row["locked_until"]) - now
        raise AccountLocked(_lock_message(left), details={"retry_after_seconds": left})


def _locked_seconds_left(conn, user_id: int, now: int) -> int | None:
    row = conn.execute("SELECT locked_until FROM login_lockouts WHERE user_id = ?", (user_id,)).fetchone()
    if row is not None and row["locked_until"] and int(row["locked_until"]) > now:
        return int(row["locked_until"]) - now
    return None


def _register_failure(conn, *, user_id: int, now: int, threshold: int, base_seconds: int, max_seconds: int,
                      ip_address: str | None) -> int | None:
    """Count a failed password; lock after `threshold` in a row. Lock time doubles per repeat lock."""
    row = conn.execute("SELECT failed_count, lock_level FROM login_lockouts WHERE user_id = ?", (user_id,)).fetchone()
    failed = (int(row["failed_count"]) if row else 0) + 1
    level = int(row["lock_level"]) if row else 0
    locked_until = None
    if failed >= threshold:
        level += 1
        duration = min(max_seconds, base_seconds * (2 ** min(level - 1, 20)))
        locked_until = now + duration
        failed = 0
    if row is None:
        conn.execute("INSERT INTO login_lockouts (user_id, failed_count, lock_level, locked_until, last_failed_at) "
                     "VALUES (?,?,?,?,?)", (user_id, failed, level, locked_until, now))
    else:
        conn.execute("UPDATE login_lockouts SET failed_count = ?, lock_level = ?, last_failed_at = ?"
                     + (", locked_until = ?" if locked_until else "") + " WHERE user_id = ?",
                     (failed, level, now, *((locked_until,) if locked_until else ()), user_id))
    if locked_until:
        audit_service.record(conn, action="user.login_locked", entity_type="user", entity_id=user_id,
                             actor_user_id=None, metadata={"lock_level": level, "locked_seconds": locked_until - now},
                             ip_address=ip_address)
    return locked_until


def lockout_status(conn, user_id: int, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    row = conn.execute("SELECT failed_count, lock_level, locked_until FROM login_lockouts WHERE user_id = ?",
                       (user_id,)).fetchone()
    locked = bool(row and row["locked_until"] and int(row["locked_until"]) > now)
    return {"locked": locked, "locked_until": int(row["locked_until"]) if locked else None,
            "failed_count": int(row["failed_count"]) if row else 0}


def unlock(conn, *, user_id: int, actor_user_id: int, reason: str, ip_address: str | None = None) -> dict:
    """Admin unlock: clears the lock and the counters; recorded in the audit log."""
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        from app.core.errors import NotFoundError
        raise NotFoundError("کاربر یافت نشد")
    before = lockout_status(conn, user_id)
    conn.execute("UPDATE login_lockouts SET failed_count = 0, lock_level = 0, locked_until = NULL WHERE user_id = ?",
                 (user_id,))
    audit_service.record(conn, action="user.login_unlocked", entity_type="user", entity_id=user_id,
                         actor_user_id=actor_user_id, metadata={"reason": reason, "was_locked": before["locked"]},
                         ip_address=ip_address)
    return lockout_status(conn, user_id)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_registration(email: str, password: str, full_name: str) -> None:
    errors: dict[str, str] = {}
    if not EMAIL_RE.match(normalize_email(email)) or normalize_email(email).endswith(("@users.60online.invalid", "@phone.60online.ir")):
        errors["email"] = "ایمیل معتبر نیست"
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        errors["password"] = f"رمز عبور باید حداقل {MIN_PASSWORD_LENGTH} کاراکتر باشد"
    elif password.isdigit():
        errors["password"] = "رمز عبور نباید فقط عدد باشد"
    if not (full_name or "").strip():
        errors["full_name"] = "نام و نام خانوادگی الزامی است"
    if errors:
        raise ValidationError("اطلاعات ثبت‌نام نامعتبر است", details=errors)


def register(
    db: Database,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None = None,
    role: str = "customer",
    ip_address: str | None = None,
) -> dict:
    validate_registration(email, password, full_name)
    if role not in VALID_ROLES:
        raise ValidationError(f"نقش نامعتبر: {role}")

    normalized = normalize_email(email)
    digest = hash_password(password)  # plaintext never leaves this frame

    with db.write_transaction() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (email, email_normalized, password_hash, full_name, phone, role)
                VALUES (?,?,?,?,?,?)
                """,
                (email.strip(), normalized, digest, full_name.strip(), (phone or "").translate(_LATIN_DIGITS).strip() or None, role),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("این ایمیل قبلاً ثبت شده است", code="email_taken") from exc
        user_id = int(cursor.lastrowid)
        audit_service.record(
            conn,
            action="user.registered",
            entity_type="user",
            entity_id=user_id,
            actor_user_id=user_id,
            metadata={"email": normalized, "role": role},
            ip_address=ip_address,
        )
    return get_user(db, user_id)


def authenticate(
    db: Database,
    *,
    email: str,
    password: str,
    secret: str,
    algorithm: str,
    ttl_seconds: int,
    ip_address: str | None = None,
    lockout_threshold: int = 5,
    lockout_seconds: int = 900,
    lockout_max_seconds: int = 86400,
) -> tuple[str, dict]:
    normalized = normalize_email(email)
    row = db.query_one(
        "SELECT id, email, password_hash, full_name, role, is_active FROM users WHERE email_normalized = ?",
        (normalized,),
    )
    # Identical error for unknown-user and wrong-password: no account enumeration.
    generic = AuthenticationError("ایمیل یا رمز عبور اشتباه است", code="invalid_credentials")
    if row is None:
        # Still burn the CPU cost so timing does not leak account existence.
        verify_password(password, "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA$AAAA")
        raise generic
    now = int(time.time())
    # A locked account is refused before the password is checked, so guessing cannot continue.
    _check_lockout(db, int(row["id"]), now)
    password_ok = verify_password(password, row["password_hash"])
    # Re-check inside the (serialised) write transaction: a lock set by a parallel request while this
    # password was being verified must hold too, so parallel guessing gets no more than `threshold`
    # answers per lock window and a correct guess is not revealed while the account is locked.
    if not password_ok:
        locked_left = None
        with db.write_transaction() as conn:
            locked_left = _locked_seconds_left(conn, int(row["id"]), int(time.time()))
            audit_service.record(
                conn,
                action="user.login_failed",
                entity_type="user",
                entity_id=row["id"],
                actor_user_id=row["id"],
                metadata={"email": normalized},
                ip_address=ip_address,
            )
            locked_until = None if locked_left else _register_failure(
                conn, user_id=int(row["id"]), now=now, threshold=lockout_threshold,
                base_seconds=lockout_seconds, max_seconds=lockout_max_seconds, ip_address=ip_address)
        if locked_left:
            raise AccountLocked(_lock_message(locked_left), details={"retry_after_seconds": locked_left})
        if locked_until:
            raise AccountLocked(_lock_message(locked_until - now), details={"retry_after_seconds": locked_until - now})
        raise generic
    if not row["is_active"]:
        raise AuthenticationError("حساب کاربری غیرفعال است", code="account_disabled")

    token = create_access_token(
        user_id=int(row["id"]),
        email=row["email"],
        role=row["role"],
        secret=secret,
        algorithm=algorithm,
        ttl_seconds=ttl_seconds,
    )
    with db.write_transaction() as conn:
        locked_left = _locked_seconds_left(conn, int(row["id"]), int(time.time()))
        if locked_left:
            raise AccountLocked(_lock_message(locked_left), details={"retry_after_seconds": locked_left})
        conn.execute("UPDATE login_lockouts SET failed_count = 0, lock_level = 0, locked_until = NULL "
                     "WHERE user_id = ? AND (failed_count > 0 OR lock_level > 0)", (int(row["id"]),))
        audit_service.record(
            conn,
            action="user.logged_in",
            entity_type="user",
            entity_id=row["id"],
            actor_user_id=int(row["id"]),
            metadata={"email": normalized},
            ip_address=ip_address,
        )
    return token, get_user(db, int(row["id"]))


def get_user(db: Database, user_id: int) -> dict:
    row = db.query_one(
        "SELECT id, email, full_name, phone, role, is_active, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    if row is None:
        raise AuthenticationError("کاربر یافت نشد")
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }
