"""AloPeyk Carrier Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: Not publicly available without partner agreement.
  AloPeyk is an Iranian on-demand logistics platform.
Sandbox availability: Not confirmed without partnership.
Authentication method: Not publicly documented.
Verified endpoints: None (no public API specification).
Rate limits / webhook rules: Not documented publicly.

References (for implementer):
  - https://alopeyk.com/ (vendor homepage)
  - Contact AloPeyk technical team / partner programme for API access.

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


class AloPeykCarrierAdapter(CarrierAdapter):
    """AloPeyk carrier adapter — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No API calls are made. No endpoints are fabricated.
    """

    provider_code = "alopeyk"
    implementation_status = "not_implemented"
    # Phase 5C: carrier status code -> normalized tracking status. PROVISIONAL codes,
    # to be confirmed against official docs; overridable per carrier via
    # logistics_carriers.status_map_json.
    TRACKING_STATUS_MAP: dict[str, str] = {"new": "created", "accepted": "created", "picking": "created", "delivering": "picked_up", "delivered": "delivered", "finished": "delivered", "cancelled": "failed", "returned": "returned"}

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_quotes(self, request: ShipmentQuoteRequest) -> list[ShipmentQuote]:
        raise NotImplementedError(
            "ALOPEYK: get_quotes — REAL PROVIDER: NOT IMPLEMENTED. "
            "مستندات API AloPeyk نیاز به قرارداد شریک دارد."
        )

    def create_shipment(self, request: ShipmentCreateRequest) -> ShipmentCreateResult:
        raise NotImplementedError(
            "ALOPEYK: create_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def cancel_shipment(self, external_shipment_id: str) -> ShipmentCancelResult:
        raise NotImplementedError(
            "ALOPEYK: cancel_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def get_tracking(self, external_shipment_id: str) -> TrackingResult:
        raise NotImplementedError(
            "ALOPEYK: get_tracking — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def normalize_webhook(self, headers: dict, parsed_body: dict) -> VerifiedWebhookEvent:
        raise NotImplementedError(
            "ALOPEYK: normalize_webhook — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def verify_webhook(self, headers: dict[str, Any], raw_body: bytes) -> VerifiedWebhookEvent:
        raise WebhookVerificationError(
            "ALOPEYK: verify_webhook — REAL PROVIDER: NOT IMPLEMENTED. "
            "All webhooks rejected — signature method undocumented.",
            code="not_implemented",
        )
