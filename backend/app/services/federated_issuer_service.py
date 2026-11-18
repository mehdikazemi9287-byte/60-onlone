"""Federated credit — the ISSUER side that would let VandaPay accept credit issued by 60Online. STUB, flag-off.

Owner decision 2026-11-18 (docs/decisions/2026-11-18-federated-credit-vandapay.md): 60Online (with the
trading company behind it) may contract with organisations and issue its OWN credit / welfare wallets, and may
optionally connect them to VandaPay, which aggregates them (federation). Invariant: ONE owning ledger per
credit program. When VandaPay accepts a 60Online-issued program it does not hold a copy of the balance; it asks
60Online (this connector) to authorize / capture / void / refund against 60Online's own ledger.

Status: interface only. Requests are authenticated and validated; every money-moving or balance-revealing
operation then answers ``501 issuer_not_implemented``. No balance is read and no ledger is touched.
The contract below is 60Online's minimal proposal and MUST be aligned with VandaPay's
``docs/integration-plans/federated-credit/ISSUER-CONNECTOR.md`` (not available when this was written).

Contract (all POST, JSON, integer rial amounts, currency "IRR"):
  /api/v1/federation/issuer/eligibility
        {customer_phone, program_ref, amount, currency, items?} → {eligible, spendable_amount (<= amount)}
        (never the full balance: VandaPay only learns how much of THIS amount can be covered)
  /api/v1/federation/issuer/authorizations
        {authorization_ref, customer_phone, program_ref, amount, currency, order_ref, merchant_ref, items?}
        → 201 {authorization_id, status: "authorized", amount, expires_at}
  /api/v1/federation/issuer/authorizations/<authorization_id>/capture   {amount}
  /api/v1/federation/issuer/authorizations/<authorization_id>/void      {}
  /api/v1/federation/issuer/authorizations/<authorization_id>/refunds   {amount, refund_ref}
Security:
  * ``VandaPay-Signature: t=<unix>,v1=<hex(HMAC_SHA256(FEDERATED_ISSUER_SECRET, t + "." + raw_body))>``
    (same scheme and 300 s tolerance as VandaPay's merchant webhooks; several v1 allowed for rotation).
  * ``Idempotency-Key`` required on every write; same key + same body → same answer.
  * Off unless FEDERATED_ISSUER_ENABLED=1 AND FEDERATED_ISSUER_SECRET is set (otherwise every route is 404).
Outbound (60Online → VandaPay) signed webhooks, header ``SixtyOnline-Signature`` (same scheme, secret
FEDERATED_ISSUER_SECRET): ``issuer.authorization.expired``, ``issuer.authorization.voided``,
``issuer.program.suspended``. Only the envelope builder/signature exists here; nothing is sent.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from app.adapters.payment.vandapay import WebhookSignatureError, compute_signature, verify_signature

OUTBOUND_SIGNATURE_HEADER = "SixtyOnline-Signature"
INBOUND_SIGNATURE_HEADER = "VandaPay-Signature"
OUTBOUND_EVENTS = frozenset({"issuer.authorization.expired", "issuer.authorization.voided",
                             "issuer.program.suspended"})
OPERATIONS = ("eligibility", "authorize", "capture", "void", "refund")
_PHONE_RE = re.compile(r"^09\d{9}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
MAX_AMOUNT = 9007199254740991


class IssuerRequestError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def config(environ=os.environ) -> dict | None:
    """{"secret": ...} when the issuer connector is switched on, else None (default)."""
    if str(environ.get("FEDERATED_ISSUER_ENABLED", "0")).strip().lower() not in ("1", "true", "yes", "on"):
        return None
    secret = (environ.get("FEDERATED_ISSUER_SECRET") or "").strip()
    if len(secret) < 16:
        return None
    return {"secret": secret}


def authenticate(raw_body: bytes, header: str | None, secret: str, *, now: int | None = None) -> dict:
    try:
        verify_signature(raw_body, header, secret, now=now)
    except WebhookSignatureError as exc:
        raise IssuerRequestError(401, "invalid_signature", exc.reason) from exc
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise IssuerRequestError(400, "malformed_body") from exc
    if not isinstance(body, dict):
        raise IssuerRequestError(400, "malformed_body")
    return body


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


def _currency(body: dict) -> None:
    if body.get("currency", "IRR") != "IRR":
        raise IssuerRequestError(422, "unsupported_currency")


def _phone(body: dict) -> str:
    v = body.get("customer_phone")
    if not isinstance(v, str) or not _PHONE_RE.match(v):
        raise IssuerRequestError(422, "invalid_customer_phone")
    return v


def _items(body: dict, amount: int) -> list | None:
    items = body.get("items")
    if items is None:
        return None
    if not isinstance(items, list) or not items:
        raise IssuerRequestError(422, "invalid_items")
    total = 0
    for it in items:
        if not isinstance(it, dict) or type(it.get("amount")) is not int or it["amount"] <= 0 \
                or not isinstance(it.get("category"), str):
            raise IssuerRequestError(422, "invalid_items")
        total += it["amount"]
    if total != amount:
        raise IssuerRequestError(422, "items_total_mismatch")
    return items


def validate(operation: str, body: dict, *, idempotency_key: str | None) -> dict:
    """Schema check for one issuer operation. Returns the cleaned request."""
    if operation not in OPERATIONS:
        raise IssuerRequestError(404, "not_found")
    if operation != "eligibility":
        if not idempotency_key or len(idempotency_key) > 200:
            raise IssuerRequestError(400, "idempotency_key_required")
    if operation == "eligibility":
        _currency(body)
        amount = _amount(body)
        return {"customer_phone": _phone(body), "program_ref": _ref(body, "program_ref"), "amount": amount,
                "items": _items(body, amount)}
    if operation == "authorize":
        _currency(body)
        amount = _amount(body)
        return {"authorization_ref": _ref(body, "authorization_ref"), "customer_phone": _phone(body),
                "program_ref": _ref(body, "program_ref"), "amount": amount, "order_ref": _ref(body, "order_ref"),
                "merchant_ref": _ref(body, "merchant_ref"), "items": _items(body, amount)}
    if operation == "capture":
        return {"amount": _amount(body)}
    if operation == "refund":
        return {"amount": _amount(body), "refund_ref": _ref(body, "refund_ref")}
    return {}  # void


def handle(operation: str, *, raw_body: bytes, signature_header: str | None, idempotency_key: str | None,
           authorization_id: str | None = None, environ=os.environ, now: int | None = None) -> tuple[int, dict]:
    cfg = config(environ)
    if cfg is None:
        return 404, {"error": {"code": "not_found"}}
    try:
        body = authenticate(raw_body, signature_header, cfg["secret"], now=now)
        if authorization_id is not None and not _REF_RE.match(authorization_id):
            raise IssuerRequestError(404, "authorization_not_found")
        validate(operation, body, idempotency_key=idempotency_key)
    except IssuerRequestError as exc:
        return exc.status, {"error": {"code": exc.code, "message": exc.message}}
    # Deliberately not implemented: no balance read, no hold, no ledger entry. See module docstring.
    return 501, {"error": {"code": "issuer_not_implemented",
                           "message": "60Online issuer connector is an interface stub; no credit was checked or moved.",
                           "operation": operation}}


def build_outbound_event(event_type: str, data: dict, *, secret: str, now: int | None = None,
                         event_id: str | None = None) -> tuple[bytes, dict]:
    """(raw_body, headers) for a 60Online → VandaPay issuer webhook. Nothing is sent from here."""
    if event_type not in OUTBOUND_EVENTS:
        raise ValueError(f"unknown issuer event {event_type!r}")
    ts = int(time.time()) if now is None else int(now)
    envelope = {"id": event_id or f"evt_60o_{uuid.uuid4().hex}", "type": event_type, "created": ts,
                "source": "60online", "data": data}
    raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return raw, {"Content-Type": "application/json",
                 OUTBOUND_SIGNATURE_HEADER: f"t={ts},v1={compute_signature(secret, ts, raw)}"}
