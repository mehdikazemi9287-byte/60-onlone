"""Integration Event Service — Phase 7 Outbox / Inbox Pattern.

Provides durable event delivery for all connector integrations:

  OUTBOX (60online → external system):
    - Events written to integration_events (status='pending') before any
      external call. If the process crashes, the retry loop picks them up.
    - Exactly-once delivery to external systems via idempotency keys.

  FAN-OUT (business events → tenant-scoped connectors):
    - fan_out_business_event() is the correct entry point for all business
      events (ORDER_CREATED, FULFILLMENT_CREATED, STOCK_UPDATED, PRICE_UPDATED).
    - Eligible connector accounts are determined server-side from
      supplier_id / organization_id — never from browser input.
    - One independently retryable row is created per eligible connector.
    - An event with no eligible connector is recorded with status='no_subscriber'
      and is never marked as externally delivered.
    - Unknown event types are dead-lettered immediately with
      last_error='unsupported_event_type'.
    - Each per-connector row carries a stable idempotency_key so that adapter
      retries are safe to re-dispatch.

  INBOX (external system → 60online):
    - Incoming webhook events written to integration_events (direction='inbound')
      before processing. Unique index on (connector_account_id, external_event_id)
      prevents duplicate processing even if the provider sends the same event twice.

  RETRY:
    - Exponential backoff: attempt N waits min(base * 2^(N-1), cap) seconds.
    - Dead-letter after max_attempts: status='dead_letter'.

  CONSUMER:
    - event_consumers table tracks which service has processed each event.
    - Unique index on (event_id, consumer_name) — idempotent.

INTEGRATION EVENT CONTRACT VERSION: 2.0
"""
from __future__ import annotations

import json
import math
import uuid as _uuid_module
from datetime import datetime, timezone

from app.core.db import write_transaction, query

# ─────────────────────────────────────────────────────────────────────────────
# Supported business event types — fail closed for anything not listed here.
# ─────────────────────────────────────────────────────────────────────────────

_BUSINESS_EVENT_TYPES: frozenset[str] = frozenset({
    "ORDER_CREATED",
    "FULFILLMENT_CREATED",
    "STOCK_UPDATED",
    "PRICE_UPDATED",
})


# ─────────────────────────────────────────────────────────────────────────────
# Retry configuration
# ─────────────────────────────────────────────────────────────────────────────

_RETRY_BASE_SECONDS = 30
_RETRY_CAP_SECONDS  = 3_600   # 1 hour maximum backoff
_MAX_ATTEMPTS       = 10      # after this → dead_letter


def _backoff_seconds(attempt_count: int) -> int:
    """Exponential backoff with cap. attempt_count is 0-indexed current attempt."""
    delay = _RETRY_BASE_SECONDS * (2 ** attempt_count)
    return min(delay, _RETRY_CAP_SECONDS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Outbox — write event before external call
# ─────────────────────────────────────────────────────────────────────────────

def enqueue_outbound_event(
    *,
    event_type: str,
    connector_account_id: int | None = None,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    payload: dict,
    external_event_id: str | None = None,
) -> int:
    """Write an outbound event to the outbox. Returns new event ID.

    Caller writes this BEFORE making the external API call so that if the
    process crashes mid-flight the retry loop can replay.
    """
    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO integration_events (
                event_type, direction, connector_account_id, supplier_id,
                organization_id, payload_json, external_event_id, status,
                attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (?, 'outbound', ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                event_type,
                connector_account_id,
                supplier_id,
                organization_id,
                json.dumps(payload, ensure_ascii=False),
                external_event_id,
                now,  # next_attempt_at = now (ready immediately)
                now,
                now,
            ),
        )
        return cur.lastrowid


def enqueue_inbound_event(
    *,
    event_type: str,
    connector_account_id: int,
    external_event_id: str,
    payload: dict,
    supplier_id: int | None = None,
    organization_id: int | None = None,
) -> int | None:
    """Write an inbound webhook event. Returns new event ID, or None if duplicate.

    The UNIQUE index on (connector_account_id, external_event_id) WHERE
    direction='inbound' prevents duplicate rows — this is the idempotency guard.
    """
    now = _now_iso()
    try:
        with write_transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO integration_events (
                    event_type, direction, connector_account_id, supplier_id,
                    organization_id, payload_json, external_event_id, status,
                    attempt_count, next_attempt_at, created_at, updated_at
                ) VALUES (?, 'inbound', ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (
                    event_type,
                    connector_account_id,
                    supplier_id,
                    organization_id,
                    json.dumps(payload, ensure_ascii=False),
                    external_event_id,
                    now,
                    now,
                    now,
                ),
            )
            return cur.lastrowid
    except Exception as exc:
        # UNIQUE constraint violation → duplicate event
        if "UNIQUE" in str(exc).upper():
            return None
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Status updates
# ─────────────────────────────────────────────────────────────────────────────

def mark_event_delivered(event_id: int, *, external_doc_id: str | None = None) -> None:
    """Mark an event as successfully delivered."""
    now = _now_iso()
    with write_transaction() as conn:
        conn.execute(
            """
            UPDATE integration_events
            SET status='delivered', delivered_at=?, updated_at=?,
                last_error=NULL
            WHERE id=?
            """,
            (now, now, event_id),
        )


def mark_event_failed(event_id: int, *, error: str) -> None:
    """Record a delivery failure. Increments attempt_count; schedules retry or dead-letters."""
    now = _now_iso()
    row = query(
        "SELECT attempt_count FROM integration_events WHERE id=?",
        (event_id,),
        one=True,
    )
    if row is None:
        return

    attempt_count = (row["attempt_count"] or 0) + 1
    if attempt_count >= _MAX_ATTEMPTS:
        new_status = "dead_letter"
        next_attempt = None
    else:
        new_status = "pending"
        delay = _backoff_seconds(attempt_count - 1)
        # next_attempt_at = now + delay (stored as ISO string; worker compares with strftime)
        import time
        ts = datetime.now(timezone.utc).timestamp() + delay
        next_attempt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    with write_transaction() as conn:
        conn.execute(
            """
            UPDATE integration_events
            SET status=?, attempt_count=?, next_attempt_at=?, last_error=?, updated_at=?
            WHERE id=?
            """,
            (new_status, attempt_count, next_attempt, error[:2000], now, event_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Consumer tracking
# ─────────────────────────────────────────────────────────────────────────────

def mark_consumed(event_id: int, *, consumer_name: str) -> bool:
    """Record that consumer_name has processed event_id. Returns True if newly recorded.

    Idempotent — second call for (event_id, consumer_name) returns False.
    """
    now = _now_iso()
    try:
        with write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO event_consumers (
                    event_id, consumer_name, status, attempt_count, consumed_at, created_at
                ) VALUES (?, ?, 'consumed', 1, ?, ?)
                """,
                (event_id, consumer_name, now, now),
            )
        return True
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            return False
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Retry queue fetch (for background worker)
# ─────────────────────────────────────────────────────────────────────────────

def get_event_by_id(event_id: int) -> dict | None:
    """Return a single integration event by ID, or None if not found."""
    row = query(
        """
        SELECT id, event_type, direction, connector_account_id, supplier_id,
               organization_id, payload_json, external_event_id,
               attempt_count, last_error, status, created_at, updated_at
        FROM integration_events WHERE id=?
        """,
        (event_id,),
        one=True,
    )
    if row is None:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["payload"] = {}
    return d


def fetch_events_admin(
    *,
    connector_account_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return events for admin — all tenants, optional filters applied in DB query."""
    where_parts = []
    params: list = []
    if connector_account_id is not None:
        where_parts.append("connector_account_id = ?")
        params.append(connector_account_id)
    if status is not None:
        where_parts.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    params.extend([limit, offset])
    rows = query(
        f"""
        SELECT id, event_type, direction, connector_account_id, supplier_id,
               organization_id, payload_json, external_event_id,
               attempt_count, last_error, status, created_at
        FROM integration_events
        {where}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
        result.append(d)
    return result


def fetch_events_for_supplier(
    *,
    supplier_id: int,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return events for a specific supplier — scoped inside DB query (not post-filter)."""
    params: list = [supplier_id]
    extra = ""
    if status is not None:
        extra = " AND status = ?"
        params.append(status)
    params.extend([limit, offset])
    rows = query(
        f"""
        SELECT id, event_type, direction, connector_account_id, supplier_id,
               organization_id, payload_json, external_event_id,
               attempt_count, last_error, status, created_at
        FROM integration_events
        WHERE supplier_id = ?{extra}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
        result.append(d)
    return result


def fetch_dead_letter_events_for_supplier(
    *,
    supplier_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Dead-letter events scoped to supplier_id — enforced in DB query."""
    rows = query(
        """
        SELECT id, event_type, direction, connector_account_id,
               supplier_id, payload_json, external_event_id,
               attempt_count, last_error, created_at, updated_at
        FROM integration_events
        WHERE status = 'dead_letter' AND supplier_id = ?
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (supplier_id, limit, offset),
    )
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Atomic outbox — use caller's existing connection (same transaction)
# ─────────────────────────────────────────────────────────────────────────────

def _get_eligible_connectors(
    conn,
    *,
    supplier_id: int | None,
    organization_id: int | None,
) -> list[dict]:
    """Server-side lookup of active connector accounts for the given owner.

    SECURITY: supplier_id and organization_id are always derived from the
    business context (e.g. a fulfillment_order row), never from browser input.

    Only connectors with status='active' are returned. Disabled/inactive/error
    connectors are excluded.
    """
    clauses: list[str] = []
    params: list = []
    if supplier_id is not None:
        clauses.append("supplier_id = ?")
        params.append(supplier_id)
    if organization_id is not None:
        clauses.append("organization_id = ?")
        params.append(organization_id)
    if not clauses:
        return []

    where = " OR ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT id, connector_type
        FROM connector_accounts
        WHERE ({where}) AND status = 'active'
        ORDER BY id
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def fan_out_business_event(
    conn,
    *,
    event_type: str,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    payload: dict,
    base_idempotency_key: str | None = None,
) -> list[int]:
    """Fan out a business event to all eligible, active connector accounts.

    Must be called with the caller's open connection so the fan-out rows
    commit or roll back together with the parent business mutation.

    Returns a list of inserted integration_events row IDs.

    Status semantics:
      pending          — event queued for external delivery to a connector.
      no_subscriber    — no active connector found; truthfully recorded,
                         NOT marked as externally delivered.
      dead_letter      — unknown event_type; fail-closed with
                         last_error='unsupported_event_type'.
    """
    now = _now_iso()
    ikey_base = base_idempotency_key or str(_uuid_module.uuid4())
    payload_json = json.dumps(payload, ensure_ascii=False)

    # ── Unknown event types: fail closed ────────────────────────────────────
    if event_type not in _BUSINESS_EVENT_TYPES:
        cur = conn.execute(
            """
            INSERT INTO integration_events (
                event_type, direction, connector_account_id, supplier_id,
                organization_id, payload_json, idempotency_key, status,
                attempt_count, last_error, next_attempt_at, created_at, updated_at
            ) VALUES (?, 'outbound', NULL, ?, ?, ?, ?, 'dead_letter', 0,
                      'unsupported_event_type', NULL, ?, ?)
            """,
            (
                event_type, supplier_id, organization_id,
                payload_json, f"{ikey_base}:dead",
                now, now,
            ),
        )
        return [cur.lastrowid]

    # ── Determine eligible connectors server-side ───────────────────────────
    connectors = _get_eligible_connectors(
        conn, supplier_id=supplier_id, organization_id=organization_id
    )

    # ── No subscribers ───────────────────────────────────────────────────────
    if not connectors:
        cur = conn.execute(
            """
            INSERT INTO integration_events (
                event_type, direction, connector_account_id, supplier_id,
                organization_id, payload_json, idempotency_key, status,
                attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (?, 'outbound', NULL, ?, ?, ?, ?, 'no_subscriber', 0,
                      NULL, ?, ?)
            """,
            (
                event_type, supplier_id, organization_id,
                payload_json, f"{ikey_base}:no_sub",
                now, now,
            ),
        )
        return [cur.lastrowid]

    # ── Fan out — one independently retryable row per connector ─────────────
    event_ids: list[int] = []
    for connector in connectors:
        ikey = f"{ikey_base}:{connector['id']}"
        cur = conn.execute(
            """
            INSERT INTO integration_events (
                event_type, direction, connector_account_id, supplier_id,
                organization_id, payload_json, idempotency_key, status,
                attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (?, 'outbound', ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            """,
            (
                event_type, connector["id"], supplier_id, organization_id,
                payload_json, ikey,
                now,  # next_attempt_at = now (ready immediately)
                now, now,
            ),
        )
        event_ids.append(cur.lastrowid)

    return event_ids


def insert_outbox_event(
    conn,
    *,
    event_type: str,
    connector_account_id: int | None = None,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    payload: dict,
    external_event_id: str | None = None,
) -> int:
    """Insert an outbound event using the CALLER's open connection/transaction.

    This is the correct atomic pattern: the business mutation and the event
    insertion commit or roll back together.  Never open an independent
    write_transaction() for outbox events.

    Returns the new event ID.
    """
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO integration_events (
            event_type, direction, connector_account_id, supplier_id,
            organization_id, payload_json, external_event_id, status,
            attempt_count, next_attempt_at, created_at, updated_at
        ) VALUES (?, 'outbound', ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
        """,
        (
            event_type,
            connector_account_id,
            supplier_id,
            organization_id,
            json.dumps(payload, ensure_ascii=False),
            external_event_id,
            now,  # next_attempt_at = now (ready immediately)
            now,
            now,
        ),
    )
    return cur.lastrowid


def fetch_pending_events(*, limit: int = 50) -> list[dict]:
    """Return pending events whose next_attempt_at is in the past.

    The background worker calls this, processes each event, then calls
    mark_event_delivered() or mark_event_failed().
    """
    now = _now_iso()
    rows = query(
        """
        SELECT id, event_type, direction, connector_account_id, supplier_id,
               organization_id, payload_json, external_event_id,
               attempt_count, last_error
        FROM integration_events
        WHERE status = 'pending'
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY next_attempt_at ASC
        LIMIT ?
        """,
        (now, limit),
    )
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
        result.append(d)
    return result


def fetch_dead_letter_events(
    *,
    connector_account_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return dead-lettered events for admin review / manual replay."""
    params: list = []
    where = "WHERE status = 'dead_letter'"
    if connector_account_id is not None:
        where += " AND connector_account_id = ?"
        params.append(connector_account_id)
    params.extend([limit, offset])
    rows = query(
        f"""
        SELECT id, event_type, direction, connector_account_id,
               supplier_id, payload_json, external_event_id,
               attempt_count, last_error, created_at, updated_at
        FROM integration_events
        {where}
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
        result.append(d)
    return result


def replay_dead_letter_event(event_id: int, *, actor_user_id: int | None = None) -> bool:
    """Reset a dead-letter event to pending for re-delivery.

    Idempotent: replaying a non-dead-letter event is a no-op (returns False).
    Audited: writes an audit_log row recording the replay action.

    Returns True if the event was reset; False if it was not in dead_letter state.
    """
    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            UPDATE integration_events
            SET status='pending', attempt_count=0, next_attempt_at=?,
                last_error=NULL, updated_at=?
            WHERE id=? AND status='dead_letter'
            """,
            (now, now, event_id),
        )
        replayed = cur.rowcount > 0
        if replayed and actor_user_id is not None:
            from app.services import audit_service
            audit_service.record(
                conn,
                action="outbox.dead_letter_replayed",
                entity_type="integration_event",
                entity_id=event_id,
                actor_user_id=actor_user_id,
                metadata={"event_id": event_id},
            )
    return replayed
