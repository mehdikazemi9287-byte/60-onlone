"""Request-scoped auth and RBAC."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import abort, current_app, g, jsonify, request

from app.core.errors import AuthenticationError, NotFoundError, PermissionError_
from app.core.security import TokenError, decode_access_token

# Role -> roles it subsumes. `admin` can reach everything.
ROLE_HIERARCHY: dict[str, set[str]] = {
    "admin": {"admin", "org_admin", "supplier", "employee", "customer"},
    "org_admin": {"org_admin", "employee", "customer"},
    "supplier": {"supplier"},
    "employee": {"employee", "customer"},
    "customer": {"customer"},
}


def get_db():
    return current_app.extensions["db"]


def get_settings():
    return current_app.extensions["settings"]


def get_secret_resolver():
    """Return the SecretResolver registered in the current app.

    Raises RuntimeError if not wired (should never happen — create_app()
    always registers at least FailClosedSecretResolver).
    """
    resolver = current_app.extensions.get("secret_resolver")
    if resolver is None:  # pragma: no cover
        raise RuntimeError(
            "secret_resolver not registered in app.extensions. "
            "Ensure create_app() was called with a SecretResolver."
        )
    return resolver


def _bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthenticationError("توکن دسترسی ارسال نشده است")
    token = header[len("Bearer ") :].strip()
    if not token:
        raise AuthenticationError("توکن دسترسی خالی است")
    return token


def authenticate_request() -> None:
    settings = get_settings()
    try:
        claims = decode_access_token(
            _bearer_token(), secret=settings.secret_key, algorithm=settings.jwt_algorithm
        )
    except TokenError as exc:
        raise AuthenticationError(str(exc), code="invalid_token") from exc

    db = get_db()
    row = db.query_one(
        "SELECT id, email, role, is_active FROM users WHERE id = ?", (claims.user_id,)
    )
    if row is None or not row["is_active"]:
        raise AuthenticationError("حساب کاربری معتبر نیست", code="account_disabled")

    # Check JWT revocation (Blocker 4)
    from app.services.revocation_service import is_token_revoked
    if is_token_revoked(db, jti=claims.jti, user_id=claims.user_id, issued_at=claims.issued_at):
        raise AuthenticationError("توکن باطل شده است", code="token_revoked")

    # The DB row is the source of truth for role, not the token: a demotion
    # takes effect immediately instead of waiting for the token to expire.
    g.current_user = {"id": int(row["id"]), "email": row["email"], "role": row["role"]}


def require_auth(*roles: str) -> Callable:
    """Authenticate, then require one of `roles` (empty = any authenticated user)."""
    allowed: Iterable[str] = roles

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate_request()
            if allowed:
                granted = ROLE_HIERARCHY.get(g.current_user["role"], set())
                if not granted.intersection(allowed):
                    raise PermissionError_(
                        "شما به این بخش دسترسی ندارید",
                        details={"required_roles": sorted(allowed)},
                    )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_org_role(*org_roles: str) -> Callable:
    """Authenticate, then require an ACTIVE membership of the organization in
    the URL with one of `org_roles`.

    Tenant isolation lives here. The organization id comes from the route, and
    the membership lookup is keyed on (organization_id, caller). An admin of
    org A calling an org B endpoint has no membership row, so they get 404 --
    not 403, which would confirm that org B exists.

    A platform-level `admin` (the global users.role, distinct from the
    per-organization membership role) bypasses the membership requirement.
    That is deliberate for support and is covered by a test.
    """

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate_request()
            organization_id = kwargs.get("org_id")
            if organization_id is None:
                raise PermissionError_("سازمان مشخص نشده است")

            user = g.current_user
            db = get_db()

            if user["role"] == "admin":
                exists = db.query_one(
                    "SELECT 1 FROM organizations WHERE id = ?", (organization_id,)
                )
                if exists is None:
                    raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
                g.membership = {"role": "organization_admin", "status": "active",
                                "id": None, "platform_admin": True}
                return view(*args, **kwargs)

            row = db.query_one(
                "SELECT id, role, status FROM organization_memberships "
                "WHERE organization_id = ? AND user_id = ?",
                (organization_id, user["id"]),
            )
            if row is None:
                raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
            if row["status"] != "active":
                raise PermissionError_(
                    "عضویت شما در این سازمان فعال نیست", code="membership_inactive"
                )
            if org_roles and row["role"] not in org_roles:
                raise PermissionError_(
                    "برای این عملیات دسترسی لازم را ندارید",
                    code="permission_denied",
                    details={"required_roles": sorted(org_roles), "your_role": row["role"]},
                )
            g.membership = {"id": row["id"], "role": row["role"], "status": row["status"],
                            "platform_admin": False}
            return view(*args, **kwargs)

        return wrapper

    return decorator


def current_membership() -> dict:
    membership = getattr(g, "membership", None)
    if membership is None:
        raise PermissionError_("عضویت سازمانی احراز نشده است")
    return membership


def current_user() -> dict:
    user = getattr(g, "current_user", None)
    if user is None:
        raise AuthenticationError("احراز هویت انجام نشده است")
    return user


def client_ip() -> str | None:
    """The caller's IP for rate limits and audit.

    X-Forwarded-For is client-controlled except for the hops our own proxies append, so only trust the entry
    TRUSTED_PROXY_HOPS from the right (e.g. 1 = nginx only, 2 = CDN + nginx). Default 0 = ignore the header.
    """
    import os
    try:
        hops = max(0, int(os.environ.get("TRUSTED_PROXY_HOPS", "0")))
    except ValueError:
        hops = 0
    forwarded = request.headers.get("X-Forwarded-For")
    if hops and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.remote_addr
