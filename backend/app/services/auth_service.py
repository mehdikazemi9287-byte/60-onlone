"""Registration and login."""
from __future__ import annotations

import re
import sqlite3

from app.core.db import Database
from app.core.errors import AuthenticationError, ConflictError, ValidationError
from app.core.security import create_access_token, hash_password, verify_password
from app.services import audit_service

# Persian/Arabic-Indic digits typed on mobile keyboards are stored as ASCII digits.
_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MIN_PASSWORD_LENGTH = 8
VALID_ROLES = {"customer", "employee", "supplier", "org_admin", "admin"}


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
    if not verify_password(password, row["password_hash"]):
        with db.write_transaction() as conn:
            audit_service.record(
                conn,
                action="user.login_failed",
                entity_type="user",
                entity_id=row["id"],
                actor_user_id=row["id"],
                metadata={"email": normalized},
                ip_address=ip_address,
            )
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
