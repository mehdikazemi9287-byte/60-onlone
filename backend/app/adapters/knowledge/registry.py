"""Product knowledge source registry.

Maps adapter_key strings to knowledge source classes.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
GS1, Digikala, manufacturer feeds are registered as stubs only.
"""
from __future__ import annotations

from app.adapters.knowledge.base import ProductKnowledgeSource
from app.adapters.knowledge.mock_catalogue import MockCatalogueKnowledgeSource


class _NotYetImplemented(ProductKnowledgeSource):
    """Placeholder for knowledge sources not yet implemented."""

    def __init__(self, key: str):
        self.adapter_key = key

    def lookup_by_identifier(self, identifier_type: str, identifier_value: str) -> dict | None:
        return None  # Gracefully returns None — not implemented

    def health_check(self) -> dict:
        return {
            "healthy": False,
            "message": f"منبع دانش '{self.adapter_key}' هنوز پیاده‌سازی نشده — REAL PROVIDER: NOT IMPLEMENTED",
            "latency_ms": None,
        }


KNOWLEDGE_ADAPTERS: dict[str, ProductKnowledgeSource] = {
    "mock_catalogue": MockCatalogueKnowledgeSource(),
    "gs1_member": _NotYetImplemented("gs1_member"),
    "digikala": _NotYetImplemented("digikala"),
    "manufacturer_feed": _NotYetImplemented("manufacturer_feed"),
}


def get_knowledge_source(adapter_key: str) -> ProductKnowledgeSource | None:
    """Return a knowledge source adapter by key, or None if unknown."""
    return KNOWLEDGE_ADAPTERS.get(adapter_key)


def list_knowledge_adapters() -> list[dict]:
    """Return list of all registered knowledge adapters with status."""
    return [
        {
            "adapter_key": key,
            "implemented": isinstance(adapter, MockCatalogueKnowledgeSource),
            "healthy": adapter.health_check()["healthy"],
        }
        for key, adapter in KNOWLEDGE_ADAPTERS.items()
    ]
