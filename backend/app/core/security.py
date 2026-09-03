"""Password hashing and JWT issuance.

Password storage uses scrypt (RFC 7914) from the Python standard library with a
per-password random salt. Plaintext passwords are never written anywhere.

NOTE on the algorithm choice: the project brief asked for bcrypt or Argon2.
Neither is installable in the build environment used to produce this commit
(no access to a package index), so scrypt -- a memory-hard KDF from hashlib --
is used instead. The interface below is deliberately algorithm-agnostic
(`hash_password`/`verify_password`, self-describing `scrypt$...` digests) so a
swap to Argon2id is a single-module change with no call-site edits.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

SCHEME = "scrypt"
SALT_BYTES = 16
KEY_LENGTH = 64
# Cost parameters: ~16 MiB of memory per hash.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
MAX_PASSWORD_BYTES = 1024


class PasswordError(ValueError):
    pass


class TokenError(ValueError):
    pass


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str) -> str:
    """Return a self-describing digest. Never returns the password."""
    if not isinstance(password, str):
        raise PasswordError("password must be a string")
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise PasswordError("password is too long")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        encoded, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LENGTH
    )
    return f"{SCHEME}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64e(salt)}${_b64e(derived)}"


def verify_password(password: str, digest: str) -> bool:
    """Constant-time verification. Malformed digests verify as False."""
    if not isinstance(password, str) or not isinstance(digest, str):
        return False
    parts = digest.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = _b64d(parts[4])
        expected = _b64d(parts[5])
    except (ValueError, TypeError):
        return False
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        candidate = hashlib.scrypt(
            encoded, salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(candidate, expected)


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    email: str
    role: str
    jti: str
    expires_at: int
    issued_at: int = 0


def create_access_token(
    *, user_id: int, email: str, role: str, secret: str, algorithm: str, ttl_seconds: int
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str) -> TokenClaims:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token is invalid") from exc
    if payload.get("typ") != "access":
        raise TokenError("token is not an access token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("token subject is invalid") from exc
    return TokenClaims(
        user_id=user_id,
        email=payload.get("email", ""),
        role=payload.get("role", ""),
        jti=payload["jti"],
        expires_at=int(payload["exp"]),
        issued_at=int(payload.get("iat", 0)),
    )
