from __future__ import annotations

from contextlib import contextmanager

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
        lockout_threshold=settings.login_lockout_threshold,
        lockout_seconds=settings.login_lockout_seconds,
        lockout_max_seconds=settings.login_lockout_max_seconds,
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
        lockout_threshold=settings.login_lockout_threshold,
        lockout_seconds=settings.login_lockout_seconds,
        lockout_max_seconds=settings.login_lockout_max_seconds,
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
    return jsonify({"user": auth_service.get_user(get_db(), current_user()["id"]), "admin_access": _admin_access()})


# ── Admin / staff second factor (TOTP step-up; see mfa_service) ──

def _admin_access() -> dict:
    from flask import g
    from app.core import staff_access
    from app.services import mfa_service
    user = current_user()
    with get_db().read_transaction() as conn:
        roles = staff_access.active_staff_roles(conn, user["id"])
        mfa = mfa_service.status(conn, user["id"])
    out = staff_access.summary(user["role"], roles)
    mode = get_settings().admin_mfa_enforce
    out["mfa_required"] = out["is_staff"] and (mode == "all" or (mode == "super_admin" and out["super_admin"]))
    out["mfa_enrolled"] = mfa["enrolled"]
    out["mfa_verified"] = bool(getattr(g, "token_mfa", False))
    out["recovery_codes_remaining"] = mfa["recovery_codes_remaining"]
    return out


def _require_staff_account() -> dict:
    from app.core.errors import PermissionError_
    access = _admin_access()
    if not access["is_staff"]:
        raise PermissionError_("ورود دومرحله‌ای فقط برای حساب‌های مدیریت و کارکنان است")
    return access


def _step_up_token() -> str:
    """Issue a token with mfa=true and revoke the one used for this request."""
    from app.core.security import create_access_token
    settings = get_settings()
    user = auth_service.get_user(get_db(), current_user()["id"])
    token = create_access_token(user_id=user["id"], email=user["email"], role=user["role"], secret=settings.secret_key,
                                algorithm=settings.jwt_algorithm, ttl_seconds=settings.access_token_ttl_seconds,
                                mfa=True)
    try:
        old = decode_access_token(_bearer_token(), secret=settings.secret_key, algorithm=settings.jwt_algorithm)
        revoke_token(get_db(), jti=old.jti, user_id=old.user_id, expires_at=old.expires_at)
    except Exception:  # the new token is valid either way; the old one simply expires
        pass
    return token


@contextmanager
def _mfa_attempt():
    """A wrong code rolls back its transaction; count the failure in a separate, committed one."""
    from app.services import mfa_service
    try:
        yield
    except mfa_service.MfaInvalid:
        with get_db().write_transaction() as conn:
            mfa_service.record_failure(conn, user_id=current_user()["id"], ip_address=client_ip())
        raise


@bp.get("/mfa/status")
@require_auth()
def mfa_status():
    return jsonify({"admin_access": _admin_access()})


@bp.post("/mfa/enroll/start")
@require_auth()
def mfa_enroll_start():
    from app.services import mfa_service
    _require_staff_account()
    user = current_user()
    with get_db().write_transaction() as conn:
        out = mfa_service.enroll_start(conn, user_id=user["id"], email=user["email"],
                                       secret_key=get_settings().secret_key, ip_address=client_ip())
    return jsonify(out)


@bp.post("/mfa/enroll/confirm")
@require_auth()
def mfa_enroll_confirm():
    from app.services import mfa_service
    _require_staff_account()
    body = _json_body()
    with _mfa_attempt():
        with get_db().write_transaction() as conn:
            codes = mfa_service.enroll_confirm(conn, user_id=current_user()["id"], code=body.get("code"),
                                               secret_key=get_settings().secret_key, ip_address=client_ip())
    token = _step_up_token()
    return jsonify({"access_token": token, "token_type": "Bearer",
                    "expires_in": get_settings().access_token_ttl_seconds, "recovery_codes": codes,
                    "user": auth_service.get_user(get_db(), current_user()["id"])})


@bp.post("/mfa/verify")
@require_auth()
def mfa_verify():
    from app.services import mfa_service
    _require_staff_account()
    body = _json_body()
    with _mfa_attempt():
        with get_db().write_transaction() as conn:
            out = mfa_service.verify(conn, user_id=current_user()["id"], secret_key=get_settings().secret_key,
                                     code=body.get("code"), recovery_code=body.get("recovery_code"),
                                     ip_address=client_ip())
    token = _step_up_token()
    return jsonify({"access_token": token, "token_type": "Bearer",
                    "expires_in": get_settings().access_token_ttl_seconds, "method": out["method"],
                    "recovery_codes_remaining": out["recovery_codes_remaining"],
                    "user": auth_service.get_user(get_db(), current_user()["id"])})


@bp.post("/mfa/recovery-codes")
@require_auth()
def mfa_recovery_codes():
    from flask import g
    from app.core.errors import PermissionError_
    from app.services import mfa_service
    _require_staff_account()
    if not getattr(g, "token_mfa", False):
        raise PermissionError_("ابتدا تأیید دومرحله‌ای را انجام دهید", code="mfa_required")
    with get_db().write_transaction() as conn:
        codes = mfa_service.regenerate_recovery_codes(conn, user_id=current_user()["id"], ip_address=client_ip())
    return jsonify({"recovery_codes": codes})


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
    """Swap a one-time code for an ordinary session token, issued exactly like OTP login does, plus the user's
    pricing eligibility (memberships with role and entitlements, wholesale/B2B flag; no secrets) and a user_ref."""
    from app.services import sso_service
    from app.services.vambi_feed_service import pricing_context
    body = _json_body()
    settings = get_settings()
    uid = sso_service.claim(get_db(), code=body.get("code"), state=body.get("state"),
                            request_origin=request.headers.get("Origin"), ip_address=client_ip())
    token, user = _otp_token(uid)
    from app.services.vambi_feed_service import user_ref
    with get_db().read_transaction() as conn:
        ctx = pricing_context(conn, uid)
    # user_ref: stable reference for the server-to-server entitlement refresh (/api/v1/sso/vambi/entitlements).
    return jsonify({"access_token": token, "token_type": "Bearer", "expires_in": settings.access_token_ttl_seconds,
                    "user": user, "user_ref": user_ref(uid, settings.secret_key), "pricing_context": ctx})
