"""Carrier adapter registry.

Maps provider_code → CarrierAdapter instance.

REAL carrier integrations are NOT IMPLEMENTED:
  - Real AloPeyk: NOT IMPLEMENTED
  - Real Iran Post: NOT IMPLEMENTED
  - Real Tipax: NOT IMPLEMENTED
  - Real local_courier: NOT IMPLEMENTED

The mock adapter is used for all tests and demo.
"""
from __future__ import annotations

from app.adapters.logistics.base import CarrierAdapter
from app.adapters.logistics.mock import MockCarrierAdapter

_ADAPTERS: dict[str, CarrierAdapter] = {
    "mock": MockCarrierAdapter(),
}

# Placeholder entries — future implementations will replace these.
# Accessing them raises NotImplementedError from the base class.
_NOT_IMPLEMENTED = ("alopeyk", "post", "tipax", "local_courier", "chapar")


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
