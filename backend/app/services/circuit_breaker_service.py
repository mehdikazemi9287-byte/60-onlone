"""Circuit Breaker Service — Phase 7 Connector Reliability.

Implements the classic three-state circuit breaker pattern for connector accounts:

  CLOSED   → normal operation; failures are counted
  OPEN     → connector is blocked; all calls fail fast without hitting external API
  HALF_OPEN → probe state; one call allowed through to test recovery

State is persisted in connector_accounts.circuit_breaker_state so it survives
process restarts.

Thresholds (defaults, per connector_account config):
  failure_threshold  : open circuit after N consecutive failures (default: 5)
  recovery_window_s  : OPEN → HALF_OPEN after N seconds (default: 300 = 5 min)
  probe_success      : HALF_OPEN success → CLOSED
  probe_failure      : HALF_OPEN failure → OPEN again (reset window)

CIRCUIT BREAKER CONTRACT VERSION: 1.0
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.db import write_transaction, query


# ─────────────────────────────────────────────────────────────────────────────
# State constants
# ─────────────────────────────────────────────────────────────────────────────

STATE_CLOSED    = "CLOSED"
STATE_OPEN      = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"

_DEFAULT_FAILURE_THRESHOLD = 5
_DEFAULT_RECOVERY_WINDOW_S = 300   # 5 minutes


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Read state
# ─────────────────────────────────────────────────────────────────────────────

def get_state(connector_account_id: int) -> dict:
    """Return current circuit breaker state for a connector account.

    Returns:
        {
          "state": "CLOSED" | "OPEN" | "HALF_OPEN",
          "failure_count": int,
          "circuit_breaker_until": str | None,  # ISO-8601 if OPEN
          "is_open": bool,
        }
    """
    row = query(
        """
        SELECT circuit_breaker_state, failure_count, circuit_breaker_until
        FROM connector_accounts
        WHERE id = ?
        """,
        (connector_account_id,),
        one=True,
    )
    if row is None:
        return {"state": STATE_CLOSED, "failure_count": 0,
                "circuit_breaker_until": None, "is_open": False}

    state = (row["circuit_breaker_state"] or STATE_CLOSED).upper()
    until = row["circuit_breaker_until"]
    now = _now_iso()

    # Automatic transition: OPEN → HALF_OPEN if recovery window has elapsed
    if state == STATE_OPEN and until and until <= now:
        _set_state(connector_account_id, STATE_HALF_OPEN, until=None, failure_count=None)
        state = STATE_HALF_OPEN
        until = None

    return {
        "state": state,
        "failure_count": row["failure_count"] or 0,
        "circuit_breaker_until": until,
        "is_open": state == STATE_OPEN,
    }


def is_open(connector_account_id: int) -> bool:
    """True if the circuit is OPEN and calls should be rejected fast."""
    return get_state(connector_account_id)["is_open"]


# ─────────────────────────────────────────────────────────────────────────────
# Record outcomes
# ─────────────────────────────────────────────────────────────────────────────

def record_success(
    connector_account_id: int,
    *,
    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    recovery_window_s: int = _DEFAULT_RECOVERY_WINDOW_S,
) -> str:
    """Record a successful call. Transitions HALF_OPEN → CLOSED.

    Returns the new state string.
    """
    current = get_state(connector_account_id)
    if current["state"] == STATE_HALF_OPEN:
        # Probe succeeded — fully close the circuit
        _set_state(connector_account_id, STATE_CLOSED, until=None, failure_count=0)
        return STATE_CLOSED
    elif current["state"] == STATE_CLOSED:
        # Reset failure count on success
        _set_state(connector_account_id, STATE_CLOSED, until=None, failure_count=0)
        return STATE_CLOSED
    # OPEN — success during OPEN is ignored (should not happen in correct usage)
    return current["state"]


def record_failure(
    connector_account_id: int,
    *,
    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    recovery_window_s: int = _DEFAULT_RECOVERY_WINDOW_S,
) -> str:
    """Record a failed call. May transition CLOSED → OPEN or HALF_OPEN → OPEN.

    Returns the new state string.
    """
    import time
    current = get_state(connector_account_id)
    state = current["state"]
    failure_count = current["failure_count"] + 1

    if state == STATE_HALF_OPEN or (state == STATE_CLOSED and failure_count >= failure_threshold):
        # Open the circuit
        ts = datetime.now(timezone.utc).timestamp() + recovery_window_s
        until = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        _set_state(connector_account_id, STATE_OPEN, until=until, failure_count=failure_count)
        return STATE_OPEN
    else:
        # Increment failure count, remain CLOSED
        _set_state(connector_account_id, STATE_CLOSED, until=None, failure_count=failure_count)
        return STATE_CLOSED


# ─────────────────────────────────────────────────────────────────────────────
# Manual reset
# ─────────────────────────────────────────────────────────────────────────────

def reset(connector_account_id: int) -> None:
    """Manually reset the circuit breaker to CLOSED (admin action)."""
    _set_state(connector_account_id, STATE_CLOSED, until=None, failure_count=0)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _set_state(
    connector_account_id: int,
    state: str,
    *,
    until: str | None,
    failure_count: int | None,
) -> None:
    now = _now_iso()
    if failure_count is not None:
        with write_transaction() as conn:
            conn.execute(
                """
                UPDATE connector_accounts
                SET circuit_breaker_state=?, circuit_breaker_until=?,
                    failure_count=?, updated_at=?
                WHERE id=?
                """,
                (state, until, failure_count, now, connector_account_id),
            )
    else:
        with write_transaction() as conn:
            conn.execute(
                """
                UPDATE connector_accounts
                SET circuit_breaker_state=?, circuit_breaker_until=?, updated_at=?
                WHERE id=?
                """,
                (state, until, now, connector_account_id),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Bulk health summary (for admin dashboard)
# ─────────────────────────────────────────────────────────────────────────────

def connector_belongs_to_supplier(connector_account_id: int, supplier_id: int) -> bool:
    """True if the connector_account is owned by the given supplier."""
    row = query(
        "SELECT 1 FROM connector_accounts WHERE id=? AND supplier_id=?",
        (connector_account_id, supplier_id),
        one=True,
    )
    return row is not None


def get_health_summary_for_supplier(supplier_id: int) -> list[dict]:
    """Return circuit breaker states for connector accounts owned by this supplier."""
    rows = query(
        """
        SELECT id, name, connector_type, circuit_breaker_state,
               failure_count, circuit_breaker_until
        FROM connector_accounts
        WHERE supplier_id = ?
        ORDER BY id
        """,
        (supplier_id,),
    )
    now = _now_iso()
    result = []
    for row in rows:
        state = (row["circuit_breaker_state"] or STATE_CLOSED).upper()
        until = row["circuit_breaker_until"]
        if state == STATE_OPEN and until and until <= now:
            state = STATE_HALF_OPEN
        result.append({
            "connector_account_id": row["id"],
            "name": row["name"],
            "connector_type": row["connector_type"],
            "state": state,
            "failure_count": row["failure_count"] or 0,
            "circuit_breaker_until": until,
            "is_open": state == STATE_OPEN,
        })
    return result


def get_health_summary() -> list[dict]:
    """Return circuit breaker state for all connector accounts."""
    rows = query(
        """
        SELECT id, name, connector_type, circuit_breaker_state,
               failure_count, circuit_breaker_until
        FROM connector_accounts
        ORDER BY id
        """,
        (),
    )
    now = _now_iso()
    result = []
    for row in rows:
        state = (row["circuit_breaker_state"] or STATE_CLOSED).upper()
        until = row["circuit_breaker_until"]
        if state == STATE_OPEN and until and until <= now:
            state = STATE_HALF_OPEN
        result.append({
            "connector_account_id": row["id"],
            "name": row["name"],
            "connector_type": row["connector_type"],
            "state": state,
            "failure_count": row["failure_count"] or 0,
            "circuit_breaker_until": until,
            "is_open": state == STATE_OPEN,
        })
    return result
