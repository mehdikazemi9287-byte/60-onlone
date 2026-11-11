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


# ── OTP (SMS one-time code) ──

def _otp_token(user_id: int) -> tuple[str, dict]:
    from app.core.security import create_access_token
    settings = get_settings()
    user = auth_service.get_user(get_db(), user_id)
    token = create_access_token(user_id=user_id, email=user["email"], role=user["role"], secret=settings.secret_key,
                                algorithm=settings.jwt_algorithm, ttl_seconds=settings.access_token_ttl_seconds)
    return token, user


def _otp_verify(phone, purpose: str, user_id, fn):
    """Spend the attempt in its own committed transaction first, then compare the code (race-proof limit)."""
    from app.services import otp_service
    with get_db().write_transaction() as conn:
        challenge_id = otp_service.claim_attempt(conn, phone=phone, purpose=purpose, user_id=user_id)
    with get_db().write_transaction() as conn:
        return fn(conn, challenge_id)


@bp.post("/otp/request")
def otp_request():
    from app.services import otp_service
    body = _json_body()
    settings = get_settings()
    with get_db().write_transaction() as conn:
        out = otp_service.request_code(conn, phone=body.get("phone"), secret=settings.secret_key, ip_address=client_ip(),
                                       production=settings.is_production)
    return jsonify(out)


@bp.post("/otp/verify")
def otp_verify():
    from app.services import otp_service
    body = _json_body()
    settings = get_settings()
    uid, created = _otp_verify(body.get("phone"), "login", None, lambda conn, cid: otp_service.verify_login(
        conn, challenge_id=cid, phone=body.get("phone"), code=body.get("code"), secret=settings.secret_key,
        full_name=body.get("full_name") if isinstance(body.get("full_name"), str) else None,
        accept_terms=body.get("accept_terms") is True, ip_address=client_ip()))
    token, user = _otp_token(uid)
    return jsonify({"access_token": token, "token_type": "Bearer", "expires_in": settings.access_token_ttl_seconds,
                    "user": user, "created": created}), (201 if created else 200)


@bp.post("/phone/request")
@require_auth()
def phone_link_request():
    from app.services import otp_service
    body = _json_body()
    settings = get_settings()
    with get_db().write_transaction() as conn:
        out = otp_service.request_code(conn, phone=body.get("phone"), secret=settings.secret_key, purpose="link",
                                       user_id=current_user()["id"], ip_address=client_ip(), production=settings.is_production)
    return jsonify(out)


@bp.post("/phone/verify")
@require_auth()
def phone_link_verify():
    from app.services import otp_service
    body = _json_body()
    settings = get_settings()
    uid = current_user()["id"]
    phone = _otp_verify(body.get("phone"), "link", uid, lambda conn, cid: otp_service.verify_link(
        conn, challenge_id=cid, user_id=uid, phone=body.get("phone"), code=body.get("code"),
        secret=settings.secret_key, ip_address=client_ip()))
    return jsonify({"phone_verified": phone})


# ── Shared login with sister sites (vambi.ir ↔ 60online.ir) ──

@bp.post("/sso/issue")
@require_auth()
def sso_issue():
    """A signed-in 60online user gets a 60-second one-time code for an allow-listed origin (see sso_service)."""
    from app.services import sso_service
    body = _json_body()
    settings = get_settings()
    with get_db().write_transaction() as conn:
        out = sso_service.issue(conn, user_id=current_user()["id"], target_origin=body.get("target_origin"),
                                state=body.get("state"), production=settings.is_production, ip_address=client_ip())
    return jsonify(out)


@bp.post("/sso/exchange")
def sso_exchange():
    """Swap a one-time code for an ordinary session token, issued exactly like OTP login does."""
    from app.services import sso_service
    body = _json_body()
    settings = get_settings()
    uid = sso_service.claim(get_db(), code=body.get("code"), state=body.get("state"),
                            request_origin=request.headers.get("Origin"), ip_address=client_ip())
    token, user = _otp_token(uid)
    return jsonify({"access_token": token, "token_type": "Bearer", "expires_in": settings.access_token_ttl_seconds,
                    "user": user})
