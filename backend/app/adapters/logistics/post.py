"""Iran Post (پست ایران) Carrier Adapter — NOT IMPLEMENTED STUB.

REAL PROVIDER: NOT IMPLEMENTED
==============================
Official documentation: Not publicly available.
  Iran Post (شرکت پست جمهوری اسلامی ایران) has not published a REST API spec.
Sandbox availability: Not confirmed.
Authentication method: Not documented publicly.
Verified endpoints: None.
Rate limits / webhook rules: Not documented.

References (for implementer):
  - https://www.post.ir/ (vendor homepage)
  - Contact Iran Post IT department for API agreement and documentation.

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


class IranPostCarrierAdapter(CarrierAdapter):
    """Iran Post carrier adapter — NOT IMPLEMENTED.

    PRODUCTION READINESS: NOT IMPLEMENTED
    No API calls are made. No endpoints are fabricated.
    """

    provider_code = "post_ir"
    implementation_status = "not_implemented"

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_quotes(self, request: ShipmentQuoteRequest) -> list[ShipmentQuote]:
        raise NotImplementedError(
            "POST_IR: get_quotes — REAL PROVIDER: NOT IMPLEMENTED. "
            "مستندات رسمی API پست ایران در دسترس عموم نیست."
        )

    def create_shipment(self, request: ShipmentCreateRequest) -> ShipmentCreateResult:
        raise NotImplementedError(
            "POST_IR: create_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def cancel_shipment(self, external_shipment_id: str) -> ShipmentCancelResult:
        raise NotImplementedError(
            "POST_IR: cancel_shipment — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def get_tracking(self, external_shipment_id: str) -> TrackingResult:
        raise NotImplementedError(
            "POST_IR: get_tracking — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def normalize_webhook(self, headers: dict, parsed_body: dict) -> VerifiedWebhookEvent:
        raise NotImplementedError(
            "POST_IR: normalize_webhook — REAL PROVIDER: NOT IMPLEMENTED."
        )

    def verify_webhook(self, headers: dict[str, Any], raw_body: bytes) -> VerifiedWebhookEvent:
        raise WebhookVerificationError(
            "POST_IR: verify_webhook — REAL PROVIDER: NOT IMPLEMENTED. "
            "All webhooks rejected — signature method undocumented.",
            code="not_implemented",
        )
