"""ProductKnowledgeSource ABC.

All real sources (GS1, Digikala, manufacturer feeds, etc.)
remain NOT IMPLEMENTED in this build. Only the mock catalogue adapter is functional.

REAL PROVIDER INTEGRATIONS: NOT IMPLEMENTED
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ProductKnowledgeSource(ABC):
    """Abstract base for product knowledge sources."""

    adapter_key: str = "base"

    @abstractmethod
    def lookup_by_identifier(self, identifier_type: str, identifier_value: str) -> dict | None:
        """
        Return enriched product data dict or None if not found.
        Never raises on not-found — only raises on hard errors.

        Returns dict with keys:
          barcode, sku, name_fa, brand_fa, category_hint, price_minor (optional)
        """
        ...

    @abstractmethod
    def health_check(self) -> dict:
        """Return {"healthy": bool, "message": str, "latency_ms": int|None}"""
        ...

    def capabilities(self) -> list[str]:
        """Return list of capabilities supported by this source."""
        return ["lookup_by_identifier"]
