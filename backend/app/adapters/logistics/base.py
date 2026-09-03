"""Abstract carrier adapter contract — Phase 7 extended.

All concrete carrier adapters MUST implement this interface.

Phase 7 additions (v2):
  - cancel_shipment() — cancel a booking before pickup
  - get_tracking()    — poll current tracking status
  - normalize_webhook() — decode provider-specific webhook body into normalized event

IMPORTANT — verify_webhook default behaviour:
  The base class REJECTS all webhooks unless the subclass explicitly overrides
  verify_webhook().  This is a deliberate fail-safe: shipping a new carrier
  without implementing signature verification would silently accept fabricated
  callbacks.

Real carrier integrations (AloPeyk, Iran Post, Tipax, Chapar) are NOT IMPLEMENTED.
Only the MockCarrierAdapter (for testing) is provided.  Real implementations
will be built from official provider documentation when those integrations are
scoped.

CARRIER ADAPTER CONTRACT VERSION: 2.0
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass
class ShipmentQuoteRequest:
    fulfillment_order_id: int
    provider_code: str
    origin_province: str
    origin_city: str
    destination_province: str
    destination_city: str
    # Comma-separated capability requirements, e.g. 'cold_chain' for perishables
    required_capabilities: str = ""
    metadata: dict | None = None


@dataclass
class ShipmentQuote:
    carrier_config_id: int
    provider_code: str
    cost_minor: int
    capabilities: str
    quote_metadata: dict | None = None


@dataclass
class ShipmentCreateRequest:
    fulfillment_order_id: int
    carrier_config_id: int
    origin_province: str
    origin_city: str
    destination_province: str
    destination_city: str
    # Stable, never-regenerated idempotency key for this booking
    booking_idempotency_key: str
    cost_minor: int
    metadata: dict | None = None


@dataclass
class ShipmentCreateResult:
    succeeded: bool
    external_shipment_id: str | None = None
    tracking_code: str | None = None
    failure_reason: str | None = None


@dataclass
class ShipmentCancelResult:
    """Result of a cancel_shipment() call."""
    succeeded: bool
    external_shipment_id: str
    message: str = ""
    failure_reason: str | None = None


@dataclass
class TrackingEvent:
    """One tracking event in a shipment's history."""
    timestamp: str             # ISO-8601
    status: str                # normalized: created, picked_up, in_transit, out_for_delivery, delivered, failed, returned
    location: str = ""
    description: str = ""


@dataclass
class TrackingResult:
    """Full tracking status for a shipment."""
    external_shipment_id: str
    tracking_code: str
    current_status: str
    events: list[TrackingEvent]
    estimated_delivery: str | None = None


@dataclass
class VerifiedWebhookEvent:
    """Returned by verify_webhook on success."""
    provider_event_id: str     # stable, provider-assigned event ID
    event_type: str            # e.g. 'status_update', 'delivered'
    external_shipment_id: str  # links to shipments.external_shipment_id
    new_status: str            # normalized status: in_transit, delivered, failed
    raw_metadata: dict         # parsed event body (safe to log)


class WebhookVerificationError(Exception):
    """Raised when webhook verification fails.  Contains a machine-readable code."""
    def __init__(self, message: str, code: str = "verification_failed"):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------

class CarrierAdapter:
    """Base class for all carrier adapters.

    Subclasses MUST:
      - Set provider_code (class attribute)
      - Override get_quotes()
      - Override create_shipment()
      - Override verify_webhook()

    The default verify_webhook raises WebhookVerificationError unconditionally
    so that an unimplemented adapter cannot accidentally accept fabricated events.
    """

    provider_code: str = "unknown"

    def get_quotes(self, request: ShipmentQuoteRequest) -> list[ShipmentQuote]:
        raise NotImplementedError(f"{type(self).__name__}.get_quotes is not implemented")

    def create_shipment(self, request: ShipmentCreateRequest) -> ShipmentCreateResult:
        raise NotImplementedError(f"{type(self).__name__}.create_shipment is not implemented")

    def cancel_shipment(self, external_shipment_id: str) -> ShipmentCancelResult:
        """Cancel a shipment booking before pickup.

        Raises NotImplementedError if the provider does not support cancellation.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.cancel_shipment is not implemented"
        )

    def get_tracking(self, external_shipment_id: str) -> TrackingResult:
        """Poll current tracking status from the carrier.

        Returns a TrackingResult with the full event history.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.get_tracking is not implemented"
        )

    def normalize_webhook(
        self, headers: dict[str, Any], parsed_body: dict
    ) -> VerifiedWebhookEvent:
        """Decode a provider-specific webhook body into a normalized VerifiedWebhookEvent.

        Called AFTER verify_webhook() has confirmed the signature.
        Default: raise NotImplementedError — must be overridden.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.normalize_webhook is not implemented"
        )

    def verify_webhook(
        self, headers: dict[str, Any], raw_body: bytes
    ) -> VerifiedWebhookEvent:
        """Default: reject everything.

        This must be overridden by every concrete adapter.  A carrier adapter
        that reaches this default in production is a bug.
        """
        raise WebhookVerificationError(
            f"Webhook verification not implemented for provider '{self.provider_code}'. "
            "All webhooks are rejected until signature verification is implemented "
            "from the provider's official documentation.",
            code="not_implemented",
        )
