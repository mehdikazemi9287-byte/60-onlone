from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import _bearer_token, client_ip, current_user, get_db, get_settings, require_auth
from app.core.errors import ValidationError
from app.core.security import decode_access_token
from app.services import auth_service
from app.services.revocation_service import revoke_token

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    return body


@bp.post("/register")
def register():
    body = _json_body()
    user = auth_service.register(
        get_db(),
        email=body.get("email", ""),
        password=body.get("password", ""),
        full_name=body.get("full_name", ""),
        phone=body.get("phone"),
        ip_address=client_ip(),
    )
    settings = get_settings()
    token, user = auth_service.authenticate(
        get_db(),
        email=body.get("email", ""),
        password=body.get("password", ""),
        secret=settings.secret_key,
        algorithm=settings.jwt_algorithm,
        ttl_seconds=settings.access_token_ttl_seconds,
        ip_address=client_ip(),
    )
    return jsonify({"access_token": token, "token_type": "Bearer", "user": user}), 201


@bp.post("/login")
def login():
    body = _json_body()
    settings = get_settings()
    token, user = auth_service.authenticate(
        get_db(),
        email=body.get("email", ""),
        password=body.get("password", ""),
        secret=settings.secret_key,
        algorithm=settings.jwt_algorithm,
        ttl_seconds=settings.access_token_ttl_seconds,
        ip_address=client_ip(),
    )
    return jsonify(
        {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": settings.access_token_ttl_seconds,
            "user": user,
        }
    )


@bp.post("/logout")
@require_auth()
def logout():
    """Revoke the current access token (logout)."""
    settings = get_settings()
    try:
        token = _bearer_token()
        claims = decode_access_token(
            token, secret=settings.secret_key, algorithm=settings.jwt_algorithm
        )
        revoke_token(
            get_db(),
            jti=claims.jti,
            user_id=claims.user_id,
            expires_at=claims.expires_at,
        )
    except Exception:
        # Even if revocation fails, return success — the client will discard the token.
        pass
    return jsonify({"message": "خروج موفق"}), 200


@bp.get("/me")
@require_auth()
def me():
    return jsonify({"user": auth_service.get_user(get_db(), current_user()["id"])})
