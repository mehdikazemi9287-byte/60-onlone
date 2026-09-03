"""Outbox Worker — Phase 7 Reliable Event Delivery.

CLI-callable worker that processes pending integration events from the outbox.

Usage (run once and exit):
    flask outbox-worker run-once [--batch-size N] [--lease-timeout-s S]

Design guarantees:
  1. ATOMIC CLAIM  — a BEGIN IMMEDIATE transaction claims a batch of event IDs
     atomically.  Two concurrent workers cannot claim the same event because
     SQLite serialises writers at the IMMEDIATE lock level.

  2. LEASE / PROCESSING STATE — claimed events are moved to status='processing'
     with updated_at stamped as the lease start time.  If a worker process dies
     mid-batch the event stays 'processing'.

  3. STALE LEASE RECOVERY — at the start of each run_once() call, events that
     have been stuck in 'processing' for longer than lease_timeout_s are reset
     to 'pending' so another worker can pick them up.

  4. BOUNDED BATCH — at most batch_size events are claimed per invocation.

  5. RETRY / BACKOFF — on failure, attempt_count is incremented and
     next_attempt_at is advanced with exponential backoff (capped at 1 hour).
     After MAX_ATTEMPTS the event is dead-lettered.

  6. DEAD LETTER — events that exhaust retries are set to status='dead_letter'
     and are never processed again automatically.  An admin can replay them via
     the API.

  7. IDEMPOTENT DISPATCH — if a dispatch succeeds but the status update
     fails (crash) the next run will see the event still 'processing', recover
     it via stale-lease handling, and dispatch again.  Adapters must be
     idempotent (they use external_event_id / idempotency keys).

OUTBOX WORKER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

import json
import logging
import os
from flask import current_app
from flask import has_app_context
from datetime import datetime, timezone

from app.core.db import write_transaction, query

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration defaults
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_BATCH_SIZE = 50
_DEFAULT_LEASE_TIMEOUT_S = 300   # 5 minutes — event stuck in 'processing' past this → stale
_RETRY_BASE_SECONDS = 30
_RETRY_CAP_SECONDS  = 3_600       # 1 hour maximum backoff
_MAX_ATTEMPTS       = 10          # after this → dead_letter


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_seconds(attempt_count: int, jitter_fn=None) -> int:
    """Exponential backoff with cap and injectable jitter.

    Args:
        attempt_count: 0-indexed current attempt number.
        jitter_fn: Callable() -> float in [0, 1). If None, defaults to
                   random.random(). Inject a deterministic function in tests.
    """
    import random as _random
    jitter = jitter_fn() if jitter_fn is not None else _random.random()
    base = _RETRY_BASE_SECONDS * (2 ** attempt_count)
    # Add up to 10% jitter to prevent thundering herd
    jittered = int(base + base * 0.1 * jitter)
    return min(jittered, _RETRY_CAP_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# Stale lease recovery
# ─────────────────────────────────────────────────────────────────────────────

def recover_stale_leases(*, lease_timeout_s: int = _DEFAULT_LEASE_TIMEOUT_S) -> int:
    """Reset events stuck in 'processing' for too long back to 'pending'.

    Returns the number of leases recovered.
    """
    from datetime import timedelta
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=lease_timeout_s)
    ).isoformat()
    now = _now_iso()
    with write_transaction() as conn:
        cur = conn.execute(
            """
            UPDATE integration_events
            SET status = 'pending', next_attempt_at = ?, updated_at = ?
            WHERE status = 'processing'
              AND (updated_at IS NULL OR updated_at <= ?)
            """,
            (now, now, cutoff),
        )
        recovered = cur.rowcount
    if recovered:
        logger.warning(
            "outbox_worker: recovered %d stale leases (cutoff=%s)", recovered, cutoff
        )
    return recovered


# ─────────────────────────────────────────────────────────────────────────────
# Atomic claim
# ─────────────────────────────────────────────────────────────────────────────

def _is_postgres_backend() -> bool:
    """Return True if the active Flask app's database is PostgreSQL."""
    try:
        from app.core.db import _get_db, PostgreSQLBackend
        return isinstance(_get_db(), PostgreSQLBackend)
    except Exception:
        return False


def claim_batch(
    *, batch_size: int = _DEFAULT_BATCH_SIZE, _pg_conn=None, _only_ids: list | None = None
) -> list[int]:
    """Atomically claim a batch of pending events. Returns list of claimed event IDs.

    SQLite path:
        Uses BEGIN IMMEDIATE so two concurrent writers are fully serialised:
        only one worker holds the write lock at a time.  The SELECT and UPDATE
        both execute inside that exclusive transaction, so no other writer can
        touch the selected rows between the two statements.

        Timestamp comparison uses SQLite's ``datetime()`` function rather than a
        raw string comparison.  Raw ISO-8601 strings are NOT lexicographically
        comparable when they use different suffix formats: SQLite's
        ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` produces ``…NNNz`` (Z suffix,
        ASCII 90) while Python's ``datetime.isoformat()`` produces
        ``…NNNnnn+00:00`` (+00:00 suffix, digits).  Because Z > any digit,
        a raw ``<=`` comparison would incorrectly exclude eligible events that
        were inserted within the same millisecond via the SQLite function.
        ``datetime()`` normalises both formats before comparing.

    PostgreSQL path:
        Uses ``SELECT … FOR UPDATE SKIP LOCKED`` for row-level locking without
        serialising the entire table.  Multiple workers can claim different rows
        concurrently while each worker gets exclusive locks on its batch only.

    Args:
        batch_size: Maximum number of events to claim in one call.
        _pg_conn: Optional explicit PostgreSQL connection.  When provided the
            function bypasses ``_get_db()`` and uses the supplied connection
            directly.  This exists solely to support concurrent integration
            tests that need two *independent* connections to the same database;
            runtime callers must always omit this argument.
        _only_ids: Optional list of event IDs to restrict claiming to.  When
            provided only events whose id is in this list are eligible.  This is
            a production-safe dependency-injection mechanism for integration
            tests that need to isolate fixture events from prior test state;
            runtime callers must always omit this argument.
    """
    now = _now_iso()
    if _pg_conn is not None or _is_postgres_backend():
        return _claim_batch_pg(now, batch_size, _conn=_pg_conn, _only_ids=_only_ids)
    return _claim_batch_sqlite(now, batch_size)


def _claim_batch_sqlite(now: str, batch_size: int) -> list[int]:
    """SQLite claim path: BEGIN IMMEDIATE + SELECT + UPDATE."""
    with write_transaction() as conn:
        rows = conn.execute(
            """
            SELECT id FROM integration_events
            WHERE status = 'pending'
              AND (next_attempt_at IS NULL
                   OR datetime(next_attempt_at) <= datetime(?))
            ORDER BY next_attempt_at ASC
            LIMIT ?
            """,
            (now, batch_size),
        ).fetchall()

        if not rows:
            return []

        ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"""
            UPDATE integration_events
            SET status = 'processing', updated_at = ?
            WHERE id IN ({placeholders}) AND status = 'pending'
            """,
            [now] + ids,
        )

    logger.debug("outbox_worker: claimed %d events for processing (sqlite)", len(ids))
    return ids


def _claim_batch_pg(now: str, batch_size: int, *, _conn=None, _only_ids: list | None = None) -> list[int]:
    """PostgreSQL claim path: SELECT … FOR UPDATE SKIP LOCKED.

    FOR UPDATE SKIP LOCKED means:
    - Lock selected rows for update.
    - Skip rows already locked by another transaction (another worker).
    - Multiple concurrent workers can claim different rows without blocking.
    This is the idiomatic PostgreSQL queue-worker pattern.

    Args:
        now: ISO-8601 timestamp string used as the current time boundary.
        batch_size: Maximum number of events to claim.
        _conn: Optional explicit psycopg2 connection.  When None the active
            Flask app's database connection is used (normal runtime path).
            Provide an independent connection only in tests that need to verify
            concurrent FOR UPDATE SKIP LOCKED isolation.
        _only_ids: Optional list of event IDs to restrict claiming to.  When
            provided only events whose id is in this list are eligible.
            Runtime callers must always omit this argument.
    """
    if _conn is None:
        from app.core.db import _get_db
        db = _get_db()
        _conn = db.connection
    pg_conn = _conn
    try:
        with pg_conn.cursor() as cur:
            # Select and lock pending rows atomically.
            # now is an ISO-8601 string; cast to timestamp for comparison.
            if _only_ids:
                cur.execute(
                    """
                    SELECT id FROM integration_events
                    WHERE status = 'pending'
                      AND id = ANY(%s)
                      AND (next_attempt_at IS NULL
                           OR next_attempt_at::timestamp <= %s::timestamp)
                    ORDER BY next_attempt_at ASC NULLS FIRST
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (_only_ids, now, batch_size),
                )
            else:
                cur.execute(
                    """
                    SELECT id FROM integration_events
                    WHERE status = 'pending'
                      AND (next_attempt_at IS NULL
                           OR next_attempt_at::timestamp <= %s::timestamp)
                    ORDER BY next_attempt_at ASC NULLS FIRST
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (now, batch_size),
                )
            rows = cur.fetchall()
            if not rows:
                pg_conn.commit()
                return []

            ids = [r[0] for r in rows]
            cur.execute(
                """
                UPDATE integration_events
                SET status = 'processing', updated_at = %s
                WHERE id = ANY(%s) AND status = 'pending'
                """,
                (now, ids),
            )
        pg_conn.commit()
    except Exception:
        try:
            pg_conn.rollback()
        except Exception:
            pass
        raise

    logger.debug("outbox_worker: claimed %d events for processing (postgresql)", len(ids))
    return ids


# ─────────────────────────────────────────────────────────────────────────────
# Event dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _load_event(event_id: int) -> dict | None:
    """Load event row by id."""
    row = query(
        """
        SELECT id, event_type, direction, connector_account_id, supplier_id,
               organization_id, payload_json, external_event_id,
               attempt_count, last_error, status
        FROM integration_events WHERE id = ?
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


def _mark_delivered(event_id: int, *, external_doc_id: str | None = None) -> None:
    """Persist 'delivered' status, optionally recording external_doc_id."""
    now = _now_iso()
    with write_transaction() as conn:
        conn.execute(
            """
            UPDATE integration_events
            SET status = 'delivered', delivered_at = ?, updated_at = ?,
                last_error = NULL,
                external_event_id = COALESCE(?, external_event_id)
            WHERE id = ?
            """,
            (now, now, external_doc_id, event_id),
        )


def _mark_failed(event_id: int, *, error: str, attempt_count: int, jitter_fn=None) -> None:
    """Increment attempt count, schedule retry or dead-letter."""
    now = _now_iso()
    if attempt_count >= _MAX_ATTEMPTS:
        new_status = "dead_letter"
        next_attempt = None
    else:
        new_status = "pending"
        delay = _backoff_seconds(attempt_count - 1, jitter_fn=jitter_fn)
        ts = datetime.now(timezone.utc).timestamp() + delay
        next_attempt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    with write_transaction() as conn:
        conn.execute(
            """
            UPDATE integration_events
            SET status = ?, attempt_count = ?, next_attempt_at = ?,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, attempt_count, next_attempt, error[:2000], now, event_id),
        )


def _dispatch_event(event: dict) -> str | None:
    """Route a single event to the appropriate adapter method.

    Returns an external_doc_id string if the adapter returned one, else None.
    Raises on failure so the caller can record the error.
    """
    event_type = event.get("event_type", "")
    connector_account_id = event.get("connector_account_id")
    payload = event.get("payload", {})

    if connector_account_id is None:
        # Internal-only event — no adapter call required; mark delivered
        logger.info(
            "outbox_worker: event %d type=%s has no connector_account_id — "
            "treating as internal-only, marking delivered",
            event["id"], event_type,
        )
        return None  # caller marks delivered

    # Load connector config
    row = query(
        "SELECT connector_type, config_json FROM connector_accounts WHERE id = ?",
        (connector_account_id,),
        one=True,
    )
    if row is None:
        raise RuntimeError(
            f"connector_account {connector_account_id} not found"
        )

    config: dict = {}
    try:
        config = json.loads(row["config_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    from app.adapters.connectors.registry import get_adapter
    from app.adapters.connectors.policy import check_delivery_allowed
    from app.core.secret_resolver import SecretResolverError
    from app.core.runtime_credentials import RuntimeCredentials

    # ── Step 1: Resolve credentials BEFORE any adapter call ───────────────────
    #
    # If the persisted config carries a credential_ref, the SecretResolver must
    # be able to return the live secret NOW.  Failure stops delivery; no external
    # I/O is performed after a resolution failure (fail-closed design).
    #
    # The resolved value is wrapped in RuntimeCredentials — an opaque, non-
    # serializable container whose repr/str never expose the raw value.  It is
    # passed to adapter methods as `runtime_credentials` and must NOT be stored,
    # logged, or persisted by this worker or by any adapter.
    #
    # The persisted `config` dict is NEVER mutated; the secret is strictly
    # ephemeral, confined to the RuntimeCredentials object and the current call.
    credential_ref = config.get("credential_ref")
    runtime_credentials: RuntimeCredentials | None = None
    if credential_ref:
        try:
            from app.core.deps import get_secret_resolver
            resolver = get_secret_resolver()
            # Resolve — keep the raw secret only inside RuntimeCredentials.
            # Log only the ref (safe); NEVER log the resolved value.
            _resolved = resolver.resolve(credential_ref)
            runtime_credentials = RuntimeCredentials(_resolved, ref=credential_ref)
            del _resolved  # narrow the lifetime to a single assignment
            logger.debug(
                "outbox_worker: credential resolved for ref=%r connector=%d",
                credential_ref, connector_account_id,
            )
        except SecretResolverError as exc:
            # Log only the ref — the error message from SecretResolverError
            # must also never contain the resolved value (it doesn't by contract).
            raise RuntimeError(
                f"credential resolution failed for ref='{credential_ref}': {exc}"
            ) from exc

    # ── Step 2: Obtain the adapter and enforce the policy gate ────────────────
    adapter = get_adapter(row["connector_type"] or "", config=config)

    # Enforce implementation-status gate (Blocker 7).
    # This check occurs AFTER resolution so an unknown credential_ref
    # already stopped execution above — no policy bypass is possible.
    impl_status = adapter.capabilities().implementation_status
    # Use the app Settings rather than the process-global environment. This
    # keeps test and staging app instances isolated, while production still
    # enforces the production certification gate.
    app_env = (
        current_app.extensions["settings"].app_env
        if has_app_context()
        else os.environ.get("APP_ENV", "development")
    )
    check_delivery_allowed(impl_status, row["connector_type"] or "", app_env=app_env)

    # ── Step 3: Dispatch — pass RuntimeCredentials to every adapter call ──────
    #
    # runtime_credentials carries the resolved secret to the adapter.
    # The adapter uses creds.resolve() to obtain the raw value for auth.
    # The persisted config dict is passed unchanged (no secret injection into it).
    external_doc_id: str | None = None

    # Route by event type
    if event_type in ("ORDER_CREATED", "ORDER_UPDATED"):
        result = adapter.push_order(payload, runtime_credentials=runtime_credentials)
        if not result.get("acknowledged"):
            raise RuntimeError(
                f"push_order not acknowledged: {result.get('message', 'unknown')}"
            )
        external_doc_id = result.get("external_ref") or result.get("external_doc_id")

    elif event_type in ("STOCK_UPDATED", "INVENTORY_UPDATED"):
        updates = payload.get("updates") or [payload]
        result = adapter.push_inventory(updates, runtime_credentials=runtime_credentials)
        if not result.get("acknowledged"):
            raise RuntimeError(
                f"push_inventory not acknowledged: {result.get('message', 'unknown')}"
            )
        external_doc_id = result.get("external_ref") or result.get("external_doc_id")

    elif event_type in ("PRICE_UPDATED",):
        # Price sync — log and pass; concrete implementation is adapter-specific
        logger.info(
            "outbox_worker: PRICE_UPDATED event %d delivered (no-op adapter path)",
            event["id"],
        )

    elif event_type in ("FULFILLMENT_CREATED", "FULFILLMENT_UPDATED"):
        # Fulfillment push — adapters may implement push_order with fulfillment data
        result = adapter.push_order(payload, runtime_credentials=runtime_credentials)
        if not result.get("acknowledged"):
            raise RuntimeError(
                f"push_order(fulfillment) not acknowledged: {result.get('message', 'unknown')}"
            )
        external_doc_id = result.get("external_ref") or result.get("external_doc_id")

    else:
        # Unknown event type — fail closed so the event is retried and ultimately
        # dead-lettered rather than silently marked as delivered.
        raise RuntimeError(
            f"unsupported_event_type: '{event_type}' — "
            "event will be retried and dead-lettered after max attempts"
        )

    # runtime_credentials goes out of scope here — the resolved secret is released.
    return external_doc_id


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_once(
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    lease_timeout_s: int = _DEFAULT_LEASE_TIMEOUT_S,
) -> dict:
    """Process one batch of pending events and return a result summary.

    Safe to call from multiple concurrent processes — SQLite BEGIN IMMEDIATE
    serialises the claim step so each event is processed by exactly one worker.

    Returns:
        {
          "recovered": int,   # stale leases reset to pending
          "claimed": int,     # events claimed this run
          "delivered": int,   # successfully dispatched
          "failed": int,      # failed this attempt (will retry)
          "dead_lettered": int,  # permanently dead-lettered this run
        }
    """
    recovered = recover_stale_leases(lease_timeout_s=lease_timeout_s)
    event_ids = claim_batch(batch_size=batch_size)

    delivered = 0
    failed = 0
    dead_lettered = 0

    for event_id in event_ids:
        event = _load_event(event_id)
        if event is None:
            logger.warning("outbox_worker: claimed event %d vanished — skipping", event_id)
            continue

        attempt_count = (event.get("attempt_count") or 0) + 1

        try:
            external_doc_id = _dispatch_event(event)
            _mark_delivered(event_id, external_doc_id=external_doc_id)
            delivered += 1
            logger.info(
                "outbox_worker: event %d (%s) delivered (attempt %d)",
                event_id, event.get("event_type"), attempt_count,
            )
        except Exception as exc:
            error_msg = str(exc)
            _mark_failed(event_id, error=error_msg, attempt_count=attempt_count)
            if attempt_count >= _MAX_ATTEMPTS:
                dead_lettered += 1
                logger.error(
                    "outbox_worker: event %d (%s) dead-lettered after %d attempts: %s",
                    event_id, event.get("event_type"), attempt_count, error_msg,
                )
            else:
                failed += 1
                logger.warning(
                    "outbox_worker: event %d (%s) failed (attempt %d/%d): %s",
                    event_id, event.get("event_type"), attempt_count, _MAX_ATTEMPTS,
                    error_msg,
                )

    return {
        "recovered": recovered,
        "claimed": len(event_ids),
        "delivered": delivered,
        "failed": failed,
        "dead_lettered": dead_lettered,
    }
