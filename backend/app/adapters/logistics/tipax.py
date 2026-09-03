"""Tipax Carrier Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: Not publicly available.
  Tipax (تیپاکس) is an Iranian express delivery company.
Sandbox availability: Not confirmed.
Authentication method: Not documented publicly.
Verified endpoints: None.
Rate limits / webhook rules: Not documented.

References (for implementer):
  - https://www.tipax.com/ (vendor homepage)
  - Contact Tipax technical team for API access and documentation.

CARRIER ADAPTER CONTRACT VERSION: 2.0
"""
from __future__ import annotations

from typing import Any

from app.adapters.logistics.base import (
    CarrierAdapter,
    ShipmentCancelResult,
    ShipmentCreateRequest,
    ShipmentCreateResult,
    ShipmentQuote,
    ShipmentQuoteRequest,
    TrackingResult,
    VerifiedWebhookEvent,
    WebhookVerificationError,
)


class TipaxCarrierAdapter(CarrierAdapter):
    """Tipax carrier adapter — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No API calls are made. No endpoints are fabricated.
    """

    provider_code = "tipax"
    implementation_status = "not_implemented"

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_quotes(self, request: ShipmentQuoteRequest) -> list[ShipmentQuote]:
        raise NotImplementedError(
            "TIPAX: get_quotes — REAL PROVIDER: NOT IMPLEMENTED. "
            "مستندات رسمی API تیپاکس در دسترس عموم نیست."
        )

    def create_shipment(self, request: ShipmentCreateRequest) -> ShipmentCreateResult:
        raise NotImplementedError(
            "TIPAX: create_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def cancel_shipment(self, external_shipment_id: str) -> ShipmentCancelResult:
        raise NotImplementedError(
            "TIPAX: cancel_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def get_tracking(self, external_shipment_id: str) -> TrackingResult:
        raise NotImplementedError(
            "TIPAX: get_tracking — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def normalize_webhook(self, headers: dict, parsed_body: dict) -> VerifiedWebhookEvent:
        raise NotImplementedError(
            "TIPAX: normalize_webhook — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def verify_webhook(self, headers: dict[str, Any], raw_body: bytes) -> VerifiedWebhookEvent:
        raise WebhookVerificationError(
            "TIPAX: verify_webhook — REAL PROVIDER: NOT IMPLEMENTED. "
            "All webhooks rejected — signature method undocumented.",
            code="not_implemented",
        )
