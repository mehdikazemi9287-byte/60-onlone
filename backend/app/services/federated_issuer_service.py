"""Federated credit — 60Online as an ISSUER whose credit VandaPay can accept. Flag-off, protocol-conformant stub.

Owner decision 2026-11-18 (docs/decisions/2026-11-18-federated-credit-vandapay.md): 60Online (with the trading
company behind it) may contract with organisations and issue its OWN credit / welfare wallets, and may optionally
connect them to VandaPay (federation). Invariant: ONE owning ledger per credit program — 60Online's. VandaPay keeps
no balance; it asks this connector to authorize / capture / void / refund against 60Online's ledger.

Contract: VandaPay "Issuer Connector v1" (vandapay repo, docs/integration-plans/federated-credit/ISSUER-CONNECTOR.md;
reference implementation backend/app/federated/protocol.py). This module implements its WIRE side faithfully:
  * every call ``POST {api_base}/v1/<op>``, op ∈ eligibility | authorize | capture | void | refund | status;
    60Online's api_base is ``https://<host>/api/v1/federation/issuer``;
  * request headers ``VandaPay-Signature`` (HMAC-SHA256 over the raw body, 300 s, several v1), ``Idempotency-Key``,
    ``VandaPay-Issuer``; bodies carry ``protocol: "1"`` and ``mode: "test"|"live"``; amounts integer rial, IRR;
  * invalid signature → 401 and nothing changes; every accepted answer is HTTP 200 with a JSON ``status`` and the
    response signature ``VandaPay-Issuer-Signature`` over the raw response body.

What is NOT implemented (stub): there is no federated program, no hold and no ledger entry yet. The connector
therefore answers truthfully as an issuer that has no credit for anyone — eligibility ``eligible:false``,
authorize ``declined/no_credit_account``, void/status ``not_found`` (nothing was ever held), capture/refund
``declined``. Nothing is read from or written to any balance. VandaPay is fail-closed, so this can never be
mistaken for a successful payment.

Off unless FEDERATED_ISSUER_ENABLED=1 AND FEDERATED_ISSUER_SECRET (>= 16 chars) are set → every route 404.
Optional FEDERATED_ISSUER_ID: when set, the ``VandaPay-Issuer`` header must match it.
FEDERATED_ISSUER_LIVE=1 is required before a ``mode: "live"`` request is even answered (default: 403).

Outbound events (60Online → VandaPay): ``POST {VANDAPAY_API}/api/v1/federated/issuers/{issuer_id}/events`` with
``VandaPay-Issuer-Signature``; types balance.changed | authorization.voided | authorization.expired |
authorization.captured. Only the envelope builder/signature exists here; nothing is sent.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

from app.adapters.payment.vandapay import WebhookSignatureError, compute_signature, verify_signature

PROTOCOL_VERSION = "1"
INBOUND_SIGNATURE_HEADER = "VandaPay-Signature"
RESPONSE_SIGNATURE_HEADER = "VandaPay-Issuer-Signature"
ISSUER_HEADER = "VandaPay-Issuer"
OPS = ("eligibility", "authorize", "capture", "void", "refund", "status")
# Allowed answer statuses per op (mirror of VandaPay protocol.STATUSES).
STATUSES = {
    "eligibility": ("ok",),
    "authorize": ("authorized", "declined"),
    "capture": ("captured", "declined"),
    "void": ("voided", "not_found", "already_captured"),
    "refund": ("refunded", "declined", "pending"),
    "status": ("authorized", "declined", "captured", "voided", "expired", "not_found"),
}
OUTBOUND_EVENTS = frozenset({"balance.changed", "authorization.voided", "authorization.expired",
                             "authorization.captured"})
_PHONE_RE = re.compile(r"^\+989\d{9}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
MAX_AMOUNT = 9007199254740991


class IssuerRequestError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def config(environ=os.environ) -> dict | None:
    if str(environ.get("FEDERATED_ISSUER_ENABLED", "0")).strip().lower() not in ("1", "true", "yes", "on"):
        return None
    secret = (environ.get("FEDERATED_ISSUER_SECRET") or "").strip()
    if len(secret) < 16:
        return None
    return {"secret": secret, "issuer_id": (environ.get("FEDERATED_ISSUER_ID") or "").strip() or None,
            "live": str(environ.get("FEDERATED_ISSUER_LIVE", "0")).strip().lower() in ("1", "true", "yes", "on")}


# ------------------------------------------------------------------ validation
def _amount(body: dict, key: str = "amount") -> int:
    v = body.get(key)
    if type(v) is not int or v <= 0 or v > MAX_AMOUNT:
        raise IssuerRequestError(422, "invalid_amount", f"{key} must be a positive integer (rial)")
    return v


def _ref(body: dict, key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not _REF_RE.match(v):
        raise IssuerRequestError(422, f"invalid_{key}")
    return v


def _phone(body: dict) -> str:
    v = body.get("phone")
    if not isinstance(v, str) or not _PHONE_RE.match(v):
        raise IssuerRequestError(422, "invalid_phone")
    return v


def _consent(body: dict) -> dict:
    c = body.get("consent")
    if not isinstance(c, dict) or not isinstance(c.get("consent_ref"), str) or not _REF_RE.match(c["consent_ref"]):
        raise IssuerRequestError(422, "consent_required")  # phone is only sent with explicit customer consent
    return c


def _merchant(body: dict) -> dict:
    m = body.get("merchant")
    if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not _REF_RE.match(m["id"]):
        raise IssuerRequestError(422, "invalid_merchant")
    return m


def _category(body: dict) -> str | None:
    v = body.get("category")
    if v is None:
        return None
    if not isinstance(v, str) or not _CATEGORY_RE.match(v):
        raise IssuerRequestError(422, "invalid_category")
    return v


def validate(op: str, body: dict, *, idempotency_key: str | None) -> dict:
    """Schema check of one issuer operation (Issuer Connector v1 §4). Returns the cleaned request."""
    if op not in OPS:
        raise IssuerRequestError(404, "not_found")
    if body.get("protocol") != PROTOCOL_VERSION:
        raise IssuerRequestError(422, "unsupported_protocol")
    if body.get("mode") not in ("test", "live"):
        raise IssuerRequestError(422, "invalid_mode")
    if op in ("authorize", "capture", "void", "refund") and (not idempotency_key or len(idempotency_key) > 200):
        raise IssuerRequestError(400, "idempotency_key_required")
    out: dict = {"mode": body["mode"]}
    if op in ("eligibility", "authorize"):
        if body.get("currency", "IRR") != "IRR":
            raise IssuerRequestError(422, "unsupported_currency")
        out.update(phone=_phone(body), amount=_amount(body), merchant=_merchant(body), category=_category(body),
                   consent=_consent(body))
    if op == "eligibility":
        out["request_ref"] = _ref(body, "request_ref")
    elif op == "authorize":
        out.update(authorization_ref=_ref(body, "authorization_ref"), intent_id=_ref(body, "intent_id"),
                   order_ref=_ref(body, "order_ref"))
        exp = body.get("expires_in_seconds")
        if exp is not None and (type(exp) is not int or not 60 <= exp <= 86_400):
            raise IssuerRequestError(422, "invalid_expires_in_seconds")
    elif op == "capture":
        out.update(authorization_ref=_ref(body, "authorization_ref"), capture_ref=_ref(body, "capture_ref"),
                   amount=_amount(body))
    elif op == "refund":
        out.update(authorization_ref=_ref(body, "authorization_ref"), refund_ref=_ref(body, "refund_ref"),
                   amount=_amount(body))
    elif op in ("void", "status"):
        out["authorization_ref"] = _ref(body, "authorization_ref")
    return out


# --------------------------------------------------------------------- answers
def _stub_answer(op: str, req: dict) -> dict:
    """Truthful answers of an issuer that has no federated credit yet. Never moves or reveals anything."""
    if op == "eligibility":
        return {"status": "ok", "eligible": False, "max_amount": 0, "label_fa": "اعتبار سازمانی شصت‌آنلاین",
                "reasons": [{"code": "no_credit_account"}]}
    if op == "authorize":
        return {"status": "declined", "authorization_ref": req["authorization_ref"], "decline_code": "no_credit_account"}
    if op == "capture":
        return {"status": "declined", "authorization_ref": req["authorization_ref"],
                "decline_code": "authorization_not_found"}
    if op == "refund":  # nothing was ever captured, so any refund exceeds it
        return {"status": "declined", "authorization_ref": req["authorization_ref"], "decline_code": "refund_exceeds"}
    return {"status": "not_found", "authorization_ref": req["authorization_ref"]}  # void / status: nothing held


def signed_response(secret: str, payload: dict, *, now: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = int(time.time()) if now is None else int(now)
    return raw, {"Content-Type": "application/json; charset=utf-8",
                 RESPONSE_SIGNATURE_HEADER: f"t={ts},v1={compute_signature(secret, ts, raw)}"}


def handle(op: str, *, raw_body: bytes, signature_header: str | None, idempotency_key: str | None,
           issuer_header: str | None, environ=os.environ, now: int | None = None) -> tuple[int, bytes, dict]:
    """Returns (http_status, raw_body, headers). 200 answers are signed; errors are not (VandaPay fails closed)."""
    def err(status: int, code: str, message: str = "") -> tuple[int, bytes, dict]:
        return status, json.dumps({"error": {"code": code, "message": message}}).encode("utf-8"), \
            {"Content-Type": "application/json"}

    cfg = config(environ)
    if cfg is None:
        return err(404, "not_found")
    try:
        verify_signature(raw_body, signature_header, cfg["secret"], now=now)
    except WebhookSignatureError as exc:
        return err(401, "invalid_signature", exc.reason)  # nothing changes
    if cfg["issuer_id"] and issuer_header != cfg["issuer_id"]:
        return err(401, "unknown_issuer")
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else None
    except (ValueError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict):
        return err(400, "malformed_body")
    try:
        req = validate(op, body, idempotency_key=idempotency_key)
    except IssuerRequestError as exc:
        return err(exc.status, exc.code, exc.message)
    if req["mode"] == "live" and not cfg["live"]:
        return err(403, "live_mode_not_enabled")
    answer = _stub_answer(op, req)
    if answer["status"] not in STATUSES[op]:  # never send a status VandaPay does not know
        return err(500, "internal_error")
    raw, headers = signed_response(cfg["secret"], answer, now=now)
    return 200, raw, headers


def build_outbound_event(event_type: str, data: dict, *, secret: str, now: int | None = None,
                         event_id: str | None = None) -> tuple[bytes, dict]:
    """(raw_body, headers) for ``POST {VANDAPAY_API}/api/v1/federated/issuers/{issuer_id}/events``. Not sent here."""
    if event_type not in OUTBOUND_EVENTS:
        raise ValueError(f"unknown issuer event {event_type!r}")
    ts = int(time.time()) if now is None else int(now)
    envelope = {"id": event_id or f"evt-60o-{uuid.uuid4().hex}", "type": event_type,
                "created_at": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data}
    raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return raw, {"Content-Type": "application/json",
                 RESPONSE_SIGNATURE_HEADER: f"t={ts},v1={compute_signature(secret, ts, raw)}"}
