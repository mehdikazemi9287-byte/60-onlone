"""Inbound VandaPay webhooks (POST /api/v1/payments/vandapay/webhook).

Order of checks — nothing changes before all of them pass:
  1. Signature on the RAW body (HMAC-SHA256, constant-time, 5-minute tolerance, any v1 may match) → 400.
  2. Event id required; an event id already handled → 200 "duplicate" (VandaPay may resend / reorder).
  3. The VandaPay intent id in the event is matched to OUR payment intent through the provider_ref we
     stored when the redirect was opened; event data (status, amount, metadata) is never trusted.
  4. The intent is re-read from the VandaPay API; then the same idempotent ``complete_redirect_payment``
     as the browser return runs (it re-fetches and checks status/amount/mode/currency again).
  5. Transient problems (API unreachable, a "succeeded" event the API does not confirm yet) → 503
     without recording the event, so VandaPay retries with back-off.

Handled events are logged in the existing ``webhook_events`` table (provider_code='vandapay',
UNIQUE(provider_code, provider_event_id)) with a minimal payload — no customer data is stored.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from app.adapters.payment.base import GatewayError
from app.adapters.payment.registry import get_payment_provider
from app.adapters.payment.vandapay import (
    FAILED_STATUSES, NAME, PAID_STATUSES, VandaPayAPIError, VandaPayProvider, WebhookSignatureError,
)
from app.core.db import Database
from app.services import checkout_service

log = logging.getLogger("60online.vandapay_webhook")


def _seen(db: Database, event_id: str) -> bool:
    with db.read_transaction() as conn:
        return conn.execute(
            "SELECT 1 FROM webhook_events WHERE provider_code = ? AND provider_event_id = ?", (NAME, event_id),
        ).fetchone() is not None


def _record(db: Database, event_id: str, summary: dict) -> None:
    try:
        with db.write_transaction() as conn:
            conn.execute(
                "INSERT INTO webhook_events (provider_code, provider_event_id, shipment_id, raw_payload, outcome) "
                "VALUES (?, ?, NULL, ?, 'accepted')",
                (NAME, event_id, json.dumps(summary, ensure_ascii=False)),
            )
    except sqlite3.IntegrityError:  # a concurrent delivery of the same event got there first
        pass


def _intent_id_of(event: dict) -> str | None:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    etype = str(event.get("type") or "")
    if etype.startswith("payment_intent."):
        raw = data.get("id")
    else:  # refund.* carries the intent as intent_id / payment_intent
        raw = data.get("intent_id") or data.get("payment_intent")
    return raw if isinstance(raw, str) and raw else None


REFUND_REVIEW_DUE_HOURS = 24


def _open_refund_review(db: Database, *, event_id: str, etype: str, vp_intent_id: str, local_id, status, data: dict) -> None:
    import datetime as _dt
    amount = data.get("amount")
    due = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=REFUND_REVIEW_DUE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db.write_transaction() as conn:
        conn.execute(
            "INSERT INTO external_refund_reviews (provider, event_id, event_type, provider_intent_ref, payment_intent_id, "
            "provider_status, amount_minor, owner_role, due_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'finance', ?) "
            "ON CONFLICT (provider, event_id) DO NOTHING",
            (NAME, event_id, etype, vp_intent_id, local_id, status, int(amount) if isinstance(amount, int) else None, due),
        )


def handle(db: Database, *, raw_body: bytes, signature_header: str | None, exponent: int = 0,
           ip_address: str | None = None, now: int | None = None) -> tuple[int, dict]:
    provider = get_payment_provider(NAME)
    if not isinstance(provider, VandaPayProvider):  # pragma: no cover - route checks enablement
        return 404, {"error": {"code": "not_found"}}
    try:
        event = provider.verify_webhook(raw_body, signature_header, now=now)
    except WebhookSignatureError as exc:
        log.warning("vandapay webhook rejected: %s", exc.reason)
        return 400, {"error": {"code": "invalid_signature", "reason": exc.reason}}

    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        return 400, {"error": {"code": "missing_event_id"}}
    if _seen(db, event_id):
        return 200, {"received": True, "outcome": "duplicate"}
    etype = str(event.get("type") or "")
    summary = {"type": etype}

    vp_intent_id = _intent_id_of(event)
    if etype == "webhook.test" or not vp_intent_id:
        _record(db, event_id, summary)
        return 200, {"received": True, "outcome": "ignored"}
    summary["intent_id"] = vp_intent_id

    with db.read_transaction() as conn:
        local = conn.execute(
            "SELECT id FROM payment_intents WHERE provider = ? AND provider_ref = ?", (NAME, vp_intent_id),
        ).fetchone()
    if local is None:  # not one of ours (another shop on the same merchant account, or never opened here)
        _record(db, event_id, {**summary, "result": "unknown_intent"})
        return 200, {"received": True, "outcome": "unknown_intent"}

    try:
        live = provider.retrieve(vp_intent_id)  # re-read before changing any order
    except VandaPayAPIError as exc:
        log.error("vandapay webhook: intent %s lookup refused (%s)", vp_intent_id, exc.code)
        return 503, {"error": {"code": "intent_lookup_failed"}}
    except GatewayError:
        return 503, {"error": {"code": "vandapay_unreachable"}}
    status = live.get("status")
    summary["status"] = status
    if status not in PAID_STATUSES and status not in FAILED_STATUSES:
        # Still pending at VandaPay. A "succeeded" event the API does not confirm yet → retry later.
        if etype == "payment_intent.succeeded":
            return 503, {"error": {"code": "not_final_yet"}}
        return 200, {"received": True, "outcome": "pending"}
    if etype.startswith("refund."):
        # Refunds made in the VandaPay panel do not adjust the shop order/ledger automatically yet. SO-4 (review
        # 2026-11-12): each event opens ONE tracked review item for finance with a deadline (not just a log line);
        # stock is never released automatically because money came back.
        log.warning("vandapay refund event %s for intent %s (status %s): manual review", event_id, vp_intent_id, status)
        _open_refund_review(db, event_id=event_id, etype=etype, vp_intent_id=vp_intent_id, local_id=local["id"],
                            status=status, data=event.get("data") if isinstance(event.get("data"), dict) else {})
        _record(db, event_id, {**summary, "result": "refund_review_opened"})
        return 200, {"received": True, "outcome": "refund_review_opened"}

    outcome = checkout_service.complete_redirect_payment(
        db, provider_name=NAME, callback={"invoice_id": str(local["id"])}, exponent=exponent, ip_address=ip_address,
    )
    if not outcome.get("ok") and outcome.get("reason") == "verify_unavailable":
        return 503, {"error": {"code": "verify_unavailable"}}
    _record(db, event_id, {**summary, "result": "ok" if outcome.get("ok") else outcome.get("reason")})
    return 200, {"received": True, "outcome": "ok" if outcome.get("ok") else outcome.get("reason")}
