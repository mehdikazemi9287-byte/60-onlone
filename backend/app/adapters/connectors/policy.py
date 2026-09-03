"""Connector Implementation-Status Policy — Blocker 7.

Enforces executable policy rules about which connectors may deliver events
to real external systems based on their implementation_status.

Policy:
  - production_verified: may deliver in any environment.
  - sandbox_verified:    may deliver in development/staging/test, NOT production.
  - simulator/mock:      may deliver in development/test ONLY; fails closed otherwise.
  - manual/stub:         may deliver in development/test ONLY; fails closed otherwise.
  - not_implemented:     NEVER delivers (always fails closed).

This policy is checked in the outbox worker before any adapter call and is
not bypassable by request body, connector config, or client parameters.

The implementation_status is derived from the adapter's capabilities() method,
which is always registry-derived and never client-supplied.
"""
from __future__ import annotations

import os

# Sorted by trust level (lowest = 0)
_STATUS_RANK: dict[str, int] = {
    "not_implemented": 0,
    "stub": 1,
    "manual": 2,
    "mock": 2,
    "simulator": 2,
    "sandbox_verified": 3,
    "production_verified": 4,
    "production": 4,  # legacy alias used by MANUAL adapter
}

# Minimum status required per environment for a real delivery to proceed.
_REQUIRED_RANK: dict[str, int] = {
    "production": _STATUS_RANK["production_verified"],
    "staging": _STATUS_RANK["sandbox_verified"],
    "development": _STATUS_RANK["simulator"],
    "test": _STATUS_RANK["simulator"],
}


class ConnectorPolicyViolation(RuntimeError):
    """Raised when a connector may not deliver in the current environment."""


def check_delivery_allowed(
    implementation_status: str,
    connector_type: str,
    app_env: str | None = None,
) -> None:
    """Raise ConnectorPolicyViolation if this connector must not deliver.

    Args:
        implementation_status: The status from adapter.capabilities().implementation_status
        connector_type: Human-readable name for error messages.
        app_env: Current APP_ENV value. Defaults to os.environ['APP_ENV'].

    Raises:
        ConnectorPolicyViolation: If delivery is not allowed in the current env.
    """
    if app_env is None:
        app_env = os.environ.get("APP_ENV", "development")

    status_rank = _STATUS_RANK.get(implementation_status, 0)
    required_rank = _REQUIRED_RANK.get(app_env, _STATUS_RANK["sandbox_verified"])

    if status_rank < required_rank:
        env_requirement = {v: k for k, v in _STATUS_RANK.items()}.get(required_rank, "unknown")
        raise ConnectorPolicyViolation(
            f"Connector '{connector_type}' has implementation_status='{implementation_status}' "
            f"which is not sufficient for APP_ENV='{app_env}'. "
            f"Required: {env_requirement!r} or higher. "
            f"This connector may not deliver events in this environment. "
            f"Achieve '{env_requirement}' certification before enabling in {app_env!r}."
        )


def is_delivery_allowed(
    implementation_status: str,
    connector_type: str,
    app_env: str | None = None,
) -> bool:
    """Return True if delivery is allowed; False otherwise (no exception)."""
    try:
        check_delivery_allowed(implementation_status, connector_type, app_env)
        return True
    except ConnectorPolicyViolation:
        return False
