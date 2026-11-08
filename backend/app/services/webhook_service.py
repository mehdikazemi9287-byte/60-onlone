"""Inbound carrier webhook processing (BLOCKER 4).

Security model:
  1. Every webhook MUST be verified by the carrier-specific adapter before
     any DB mutation occurs.
  2. Unknown provider_code → reject immediately.
  3. Missing provider_event_id → reject (cannot deduplicate without it).
  4. Invalid signature → reject (WebhookVerificationError raised by adapter).
  5. provider_event_id duplicate → return 'duplicate' (process exactly once).
  6. Provider A MUST NOT update Provider B shipment.
  7. Out-of-order status MUST NOT regress shipment state.
  8. Raw payload is retained ONLY for verified events (security: do not store
     attacker-supplied payloads for rejected webhooks).
  9. An invalid webhook MUST NOT mutate any shipment or shipment_plan row.

The verify_webhook() method on each adapter is the sole authentication gate.
Idempotency keys from URL parameters are NOT authentication.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from app.adapters.logistics.base import VerifiedWebhookEvent, WebhookVerificationError
from app.adapters.logistics.registry import get_carrier_adapter, list_provider_codes
from app.core.db import Database

log = logging.getLogger("60online.webhook")

# Shipment status progression rank (used to prevent regression).
# out_for_delivery sits between in_transit and delivered.
# returned and failed are terminal (same rank as delivered so they don't
# regress delivered, but can be reached from any earlier state).
_STATUS_RANK: dict[str, int] = {
    "planned":          0,
    "booking":          1,
    "booking_failed":   1,
    "booked":           2,
    "in_transit":       3,
    "out_for_delivery": 4,
    "delivered":        5,
    "returned":         5,
    "failed":           5,
}

KNOWN_PROVIDERS = set(list_provider_codes())


def process_webhook(
    db: Database,
    provider_code: str,
    headers: dict,
    raw_body: bytes,
) -> dict:
    """Entry point for inbound carrier webhooks.

    Returns a result dict with 'outcome' key:
      'accepted'  — processed successfully
      'duplicate' — already processed (idempotent response)
      'rejected'  — verification failed or invalid payload

    NEVER raises an exception to the caller: HTTP 200 is always returned to
    prevent the carrier from retrying indefinitely.  Failures are logged.
    """
    # 1. Unknown provider — reject before touching DB
    if provider_code not in KNOWN_PROVIDERS:
        log.warning("webhook: unknown provider_code=%r", provider_code)
        return {"outcome": "rejected", "reason": "unknown_provider"}

    # 2. Get adapter and verify
    adapter = get_carrier_adapter(provider_code)
    try:
        event: VerifiedWebhookEvent = adapter.verify_webhook(headers, raw_body)
    except WebhookVerificationError as exc:
        log.warning("webhook: verification failed provider=%s code=%s: %s",
                    provider_code, exc.code, exc)
        # DO NOT store rejected webhooks — attacker-supplied data
        return {"outcome": "rejected", "reason": exc.code}
    except Exception as exc:
        log.exception("webhook: unexpected error during verification provider=%s", provider_code)
        return {"outcome": "rejected", "reason": "verification_exception"}

    # 3. Require stable provider_event_id
    if not event.provider_event_id:
        log.warning("webhook: empty provider_event_id after verification provider=%s", provider_code)
        return {"outcome": "rejected", "reason": "missing_event_id"}

    # 4. Process in DB — dedup and apply status update
    try:
        result = _apply_verified_event(db, provider_code, event, raw_body)
        return result
    except Exception as exc:
        log.exception("webhook: error applying event provider=%s event_id=%s",
                      provider_code, event.provider_event_id)
        return {"outcome": "error", "reason": str(exc)}


def _apply_verified_event(
    db: Database,
    provider_code: str,
    event: VerifiedWebhookEvent,
    raw_body: bytes,
) -> dict:
    with db.write_transaction() as conn:
        # 5. Deduplication — exactly once per (provider_code, provider_event_id)
        existing = conn.execute(
            "SELECT id, outcome FROM webhook_events WHERE provider_code=? AND provider_event_id=?",
            (provider_code, event.provider_event_id),
        ).fetchone()
        if existing:
            log.info("webhook: duplicate event_id=%s provider=%s",
                     event.provider_event_id, provider_code)
            return {"outcome": "duplicate", "webhook_event_id": int(existing["id"])}

        # 6. Look up shipment by external_shipment_id + provider_code
        shipment = conn.execute(
            "SELECT * FROM shipments WHERE external_shipment_id=? AND provider_code=?",
            (event.external_shipment_id, provider_code),
        ).fetchone()
        if shipment is None:
            # Event verified but no matching shipment — record as accepted (not our shipment yet)
            log.warning(
                "webhook: verified event but no shipment found ext_id=%s provider=%s",
                event.external_shipment_id, provider_code,
            )
            we_cursor = conn.execute(
                """
                INSERT INTO webhook_events
                    (provider_code, provider_event_id, shipment_id, raw_payload, outcome)
                VALUES (?, ?, NULL, ?, 'accepted')
                """,
                (provider_code, event.provider_event_id, raw_body.decode("utf-8", errors="replace")),
            )
            return {"outcome": "accepted", "webhook_event_id": int(we_cursor.lastrowid),
                    "note": "no matching shipment found"}

        s = dict(shipment)

        # 7. Out-of-order protection — never regress shipment status
        current_rank = _STATUS_RANK.get(s["status"], 0)
        new_rank = _STATUS_RANK.get(event.new_status, 0)
        if new_rank <= current_rank and s["status"] != event.new_status:
            log.info(
                "webhook: out-of-order event ignored shipment_id=%s current=%s new=%s",
                s["id"], s["status"], event.new_status,
            )
            we_cursor = conn.execute(
                """
                INSERT INTO webhook_events
                    (provider_code, provider_event_id, shipment_id, raw_payload, outcome)
                VALUES (?, ?, ?, ?, 'accepted')
                """,
                (provider_code, event.provider_event_id, int(s["id"]),
                 raw_body.decode("utf-8", errors="replace")),
            )
            return {"outcome": "accepted", "webhook_event_id": int(we_cursor.lastrowid),
                    "note": "out_of_order_ignored"}

        # 8. Apply status update
        update_cols = ["status = ?", "updated_at = datetime('now')"]
        update_params: list = [event.new_status]
        if event.new_status == "delivered":
            update_cols.append("delivered_at = datetime('now')")
        conn.execute(
            f"UPDATE shipments SET {', '.join(update_cols)} WHERE id=?",
            update_params + [int(s["id"])],
        )

        # 9. Store verified event (raw payload retained for audit)
        we_cursor = conn.execute(
            """
            INSERT INTO webhook_events
                (provider_code, provider_event_id, shipment_id, raw_payload, outcome)
            VALUES (?, ?, ?, ?, 'accepted')
            """,
            (provider_code, event.provider_event_id, int(s["id"]),
             raw_body.decode("utf-8", errors="replace")),
        )
        log.info(
            "webhook: applied status update shipment_id=%s %s→%s event_id=%s",
            s["id"], s["status"], event.new_status, event.provider_event_id,
        )
        return {
            "outcome": "accepted",
            "webhook_event_id": int(we_cursor.lastrowid),
            "shipment_id": int(s["id"]),
            "old_status": s["status"],
            "new_status": event.new_status,
        }
