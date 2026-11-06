"""Chapar Carrier Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: Not publicly available.
  Chapar (چاپار) is an Iranian courier and logistics company.
Sandbox availability: Not confirmed.
Authentication method: Not documented publicly.
Verified endpoints: None.
Rate limits / webhook rules: Not documented.

References (for implementer):
  - https://www.chapar.com/ (vendor homepage)
  - Contact Chapar technical team for API access and documentation.

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


class ChaparCarrierAdapter(CarrierAdapter):
    """Chapar carrier adapter — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No API calls are made. No endpoints are fabricated.
    """

    provider_code = "chapar"
    implementation_status = "not_implemented"
    # Phase 5C: carrier status code -> normalized tracking status. PROVISIONAL codes,
    # to be confirmed against official docs; overridable per carrier via
    # logistics_carriers.status_map_json.
    TRACKING_STATUS_MAP: dict[str, str] = {"1": "created", "2": "picked_up", "3": "in_transit", "4": "out_for_delivery", "5": "delivered", "6": "failed", "7": "returned"}

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_quotes(self, request: ShipmentQuoteRequest) -> list[ShipmentQuote]:
        raise NotImplementedError(
            "CHAPAR: get_quotes — REAL PROVIDER: NOT IMPLEMENTED. "
            "مستندات رسمی API چاپار در دسترس عموم نیست."
        )

    def create_shipment(self, request: ShipmentCreateRequest) -> ShipmentCreateResult:
        raise NotImplementedError(
            "CHAPAR: create_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def cancel_shipment(self, external_shipment_id: str) -> ShipmentCancelResult:
        raise NotImplementedError(
            "CHAPAR: cancel_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def get_tracking(self, external_shipment_id: str) -> TrackingResult:
        raise NotImplementedError(
            "CHAPAR: get_tracking — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def normalize_webhook(self, headers: dict, parsed_body: dict) -> VerifiedWebhookEvent:
        raise NotImplementedError(
            "CHAPAR: normalize_webhook — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def verify_webhook(self, headers: dict[str, Any], raw_body: bytes) -> VerifiedWebhookEvent:
        raise WebhookVerificationError(
            "CHAPAR: verify_webhook — REAL PROVIDER: NOT IMPLEMENTED. "
            "All webhooks rejected — signature method undocumented.",
            code="not_implemented",
        )
