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
_NOT_IMPLEMENTED = ("alopeyk", "post", "tipax", "local_courier")


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
