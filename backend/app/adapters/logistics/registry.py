"""Carrier adapter registry.

Maps provider_code → CarrierAdapter instance.

REAL carrier integrations are NOT IMPLEMENTED:
  - Real AloPeyk: NOT IMPLEMENTED
  - Real Iran Post: NOT IMPLEMENTED
  - Real Tipax: NOT IMPLEMENTED
  - Real local_courier: NOT IMPLEMENTED

The mock adapter exists for automated tests and local development only.
It is registered only when:
  - APP_ENV is "test" or "development", or
  - ALLOW_MOCK_CARRIER=1 is set explicitly (and, in production, DEMO_MODE=1 too).
When it is not registered, "mock" is an unknown provider everywhere (quotes,
booking and the inbound webhook endpoint all reject it).

Its inbound webhooks additionally need a secret:
  - MOCK_CARRIER_WEBHOOK_SECRET (>= 32 characters) from the environment, or
  - the built-in test secret, ONLY when APP_ENV=test.
Without a secret the adapter rejects every webhook.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from app.adapters.logistics.base import CarrierAdapter
from app.adapters.logistics.mock import MOCK_WEBHOOK_SECRET, MockCarrierAdapter

log = logging.getLogger(__name__)

MIN_MOCK_WEBHOOK_SECRET_LENGTH = 32
_MOCK_ENVIRONMENTS = ("test", "development")

_ADAPTERS: dict[str, CarrierAdapter] = {}

# Placeholder entries — future implementations will replace these.
# Accessing them raises NotImplementedError from the base class.
_NOT_IMPLEMENTED = ("alopeyk", "post", "tipax", "local_courier", "chapar")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def mock_carrier_allowed(app_env: str, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    if app_env in _MOCK_ENVIRONMENTS:
        return True
    if not _truthy(env.get("ALLOW_MOCK_CARRIER")):
        return False
    if app_env == "production" and not _truthy(env.get("DEMO_MODE")):
        return False
    return True


def _mock_webhook_secret(app_env: str, environ: Mapping[str, str]) -> bytes | None:
    raw = (environ.get("MOCK_CARRIER_WEBHOOK_SECRET") or "").strip()
    if raw:
        if len(raw) < MIN_MOCK_WEBHOOK_SECRET_LENGTH:
            log.warning("MOCK_CARRIER_WEBHOOK_SECRET is shorter than %d characters; "
                        "mock carrier webhooks stay disabled", MIN_MOCK_WEBHOOK_SECRET_LENGTH)
            return None
        return raw.encode("utf-8")
    if app_env == "test":
        return MOCK_WEBHOOK_SECRET
    return None


def configure(app_env: str, environ: Mapping[str, str] | None = None) -> None:
    """(Re)build the adapter table for an environment.  Called by create_app()."""
    env = os.environ if environ is None else environ
    _ADAPTERS.clear()
    if mock_carrier_allowed(app_env, env):
        _ADAPTERS["mock"] = MockCarrierAdapter(webhook_secret=_mock_webhook_secret(app_env, env))
        if app_env not in _MOCK_ENVIRONMENTS:
            log.warning("mock carrier enabled explicitly (ALLOW_MOCK_CARRIER) in APP_ENV=%s", app_env)


def mock_carrier_status() -> dict:
    """Non-secret summary for health/preflight output."""
    adapter = _ADAPTERS.get("mock")
    return {
        "enabled": adapter is not None,
        "webhooks_enabled": bool(adapter is not None and getattr(adapter, "_webhook_secret", None)),
    }


# Import-time default (before create_app runs): follow APP_ENV, default development.
configure(os.environ.get("APP_ENV", "development"))


def get_carrier_adapter(provider_code: str) -> CarrierAdapter:
    """Return the adapter for the given provider_code.

    Raises ValueError for unknown provider codes.
    Returns a NOT-IMPLEMENTED adapter for real carriers (which will raise
    NotImplementedError when any method is called).
    """
    if provider_code in _ADAPTERS:
        return _ADAPTERS[provider_code]
    if provider_code in _NOT_IMPLEMENTED:
        # Instantiate a stub that will raise NotImplementedError on use
        stub = CarrierAdapter()
        stub.provider_code = provider_code
        return stub
    raise ValueError(f"Unknown carrier provider code: {provider_code!r}")


def list_provider_codes() -> list[str]:
    return list(_ADAPTERS) + list(_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Phase 5C: tracking status maps + tracking-event handler registry entry.
# ---------------------------------------------------------------------------

NORMALIZED_TRACKING_STATUSES = (
    "created", "picked_up", "in_transit", "out_for_delivery", "delivered", "failed", "returned",
)


def get_tracking_status_map(provider_code: str) -> dict[str, str]:
    """Carrier code -> normalized status, from the adapter's TRACKING_STATUS_MAP."""
    from app.adapters.logistics.alopeyk import AloPeykCarrierAdapter
    from app.adapters.logistics.chapar import ChaparCarrierAdapter
    from app.adapters.logistics.post import IranPostCarrierAdapter
    from app.adapters.logistics.tipax import TipaxCarrierAdapter

    classes = {"tipax": TipaxCarrierAdapter, "chapar": ChaparCarrierAdapter,
               "post": IranPostCarrierAdapter, "post_ir": IranPostCarrierAdapter,
               "alopeyk": AloPeykCarrierAdapter}
    cls = classes.get(provider_code)
    base = {s: s for s in NORMALIZED_TRACKING_STATUSES}
    return {**base, **dict(getattr(cls, "TRACKING_STATUS_MAP", {}) or {})}


def get_tracking_event_handler():
    """Inbound tracking webhooks (phase 5A endpoint) call this handler:
    handler(conn, carrier, payload) -> dict."""
    from app.services.shipment_orchestrator import apply_tracking_event
    return apply_tracking_event
