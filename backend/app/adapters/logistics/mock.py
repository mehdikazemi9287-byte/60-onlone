"""Mock carrier adapter for tests and demo.

This adapter:
  - Returns deterministic quotes based on capability requirements.
  - Creates shipments with a deterministic external_shipment_id derived from
    the booking_idempotency_key — so retries with the same key always return
    the same external ID (idempotent).
  - Verifies webhooks using a deterministic HMAC-SHA256 signature:
      X-Mock-Signature: hmac_sha256(raw_body, MOCK_WEBHOOK_SECRET)
    The test-only secret value is defined in this module as MOCK_WEBHOOK_SECRET.

IMPORTANT: This adapter is for testing and development only.  It does NOT
call any real carrier network.  Real carrier integrations are NOT IMPLEMENTED.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from app.adapters.logistics.base import (
    CarrierAdapter,
    ShipmentCancelResult,
    ShipmentCreateRequest,
    ShipmentCreateResult,
    ShipmentQuote,
    ShipmentQuoteRequest,
    TrackingEvent,
    TrackingResult,
    VerifiedWebhookEvent,
    WebhookVerificationError,
)

# Stable test secret; never used outside tests.
MOCK_WEBHOOK_SECRET = b"mock-webhook-secret-test-only"

# Status map: incoming mock event type → normalized status.
# 'out_for_delivery' is now a first-class status (migration 0008).
# 'returned' maps to 'returned' (not 'failed') — distinct terminal state.
_MOCK_STATUS_MAP = {
    "picked_up":        "in_transit",
    "in_transit":       "in_transit",
    "out_for_delivery": "out_for_delivery",
    "delivered":        "delivered",
    "failed":           "failed",
    "returned":         "returned",
}

# Shipment state progression rank (mirrors webhook_service._STATUS_RANK).
# Kept here for documentation; enforcement lives in webhook_service.
_STATUS_RANK = {
    "planned": 0, "booking": 1, "booking_failed": 1, "booked": 2,
    "in_transit": 3, "out_for_delivery": 4,
    "delivered": 5, "returned": 5, "failed": 5,
}


class MockCarrierAdapter(CarrierAdapter):
    """Deterministic mock carrier for tests and demo."""

    provider_code = "mock"

    def get_quotes(self, request: ShipmentQuoteRequest) -> list[ShipmentQuote]:
        """Return cheap, mid-price and expensive quotes based on required_capabilities."""
        req_caps = {c.strip() for c in (request.required_capabilities or "").split(",") if c.strip()}

        # All mock quotes that satisfy the capability requirements
        # Costs are fixed so tests can assert exact values.
        all_options = [
            # (capabilities_set, cost_minor)
            ({"local"},                      50_000),
            ({"local", "intercity"},        120_000),
            ({"local", "cold_chain"},        80_000),
            ({"local", "intercity"},        150_000),
        ]
        quotes = []
        for idx, (caps, cost) in enumerate(all_options):
            if req_caps and not req_caps.issubset(caps):
                continue  # doesn't satisfy requirement
            quotes.append(ShipmentQuote(
                carrier_config_id=0,   # 0 = resolved by logistics_service from DB
                provider_code="mock",
                cost_minor=cost,
                capabilities=",".join(sorted(caps)),
                quote_metadata={"mock_option_idx": idx},
            ))
        return quotes

    def create_shipment(self, request: ShipmentCreateRequest) -> ShipmentCreateResult:
        """Return a deterministic shipment ID and tracking code.

        The external_shipment_id is derived from the booking_idempotency_key so
        retries with the same key return the exact same result — the carrier
        never creates a second shipment.
        """
        key_hash = hashlib.sha256(request.booking_idempotency_key.encode()).hexdigest()[:12].upper()
        external_id = f"MOCK-{key_hash}"
        tracking   = f"TRK-{key_hash}"
        return ShipmentCreateResult(
            succeeded=True,
            external_shipment_id=external_id,
            tracking_code=tracking,
        )

    def verify_webhook(self, headers: dict, raw_body: bytes) -> VerifiedWebhookEvent:
        """Verify mock webhook signature.

        Expected request headers:
          X-Mock-Signature: <hex HMAC-SHA256(raw_body, MOCK_WEBHOOK_SECRET)>
          X-Mock-Event-Id: <stable event ID>
          X-Mock-Shipment-Id: <external_shipment_id>
          X-Mock-Event-Type: <picked_up|in_transit|delivered|failed>

        Verification failure raises WebhookVerificationError.
        """
        # 1. Signature
        sig_header = headers.get("X-Mock-Signature") or headers.get("x-mock-signature") or ""
        if not sig_header:
            raise WebhookVerificationError(
                "Missing X-Mock-Signature header", code="missing_signature"
            )
        expected_sig = hmac.new(MOCK_WEBHOOK_SECRET, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_header.lower(), expected_sig.lower()):
            raise WebhookVerificationError(
                "Invalid mock webhook signature", code="invalid_signature"
            )

        # 2. Event ID (stable, provider-assigned)
        event_id = (headers.get("X-Mock-Event-Id") or headers.get("x-mock-event-id") or "").strip()
        if not event_id:
            raise WebhookVerificationError(
                "Missing X-Mock-Event-Id header — cannot deduplicate", code="missing_event_id"
            )

        # 3. External shipment ID
        ext_id = (headers.get("X-Mock-Shipment-Id") or headers.get("x-mock-shipment-id") or "").strip()
        if not ext_id:
            raise WebhookVerificationError(
                "Missing X-Mock-Shipment-Id header", code="missing_shipment_id"
            )

        # 4. Event type → normalized status
        event_type = (headers.get("X-Mock-Event-Type") or headers.get("x-mock-event-type") or "").strip()
        new_status = _MOCK_STATUS_MAP.get(event_type)
        if new_status is None:
            raise WebhookVerificationError(
                f"Unknown mock event type '{event_type}'", code="unknown_event_type"
            )

        # 5. Parse body for metadata (best-effort, already verified above)
        try:
            metadata = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else {}
        except (json.JSONDecodeError, ValueError):
            metadata = {}

        return VerifiedWebhookEvent(
            provider_event_id=event_id,
            event_type=event_type,
            external_shipment_id=ext_id,
            new_status=new_status,
            raw_metadata=metadata,
        )


    def cancel_shipment(self, external_shipment_id: str) -> ShipmentCancelResult:
        """Mock cancel — always succeeds for MOCK- prefixed IDs."""
        if not external_shipment_id.startswith("MOCK-"):
            return ShipmentCancelResult(
                succeeded=False,
                external_shipment_id=external_shipment_id,
                failure_reason="Unknown shipment ID in mock adapter",
            )
        return ShipmentCancelResult(
            succeeded=True,
            external_shipment_id=external_shipment_id,
            message="مرسوله در سیستم mock لغو شد",
        )

    def get_tracking(self, external_shipment_id: str) -> TrackingResult:
        """Mock tracking — returns a static 'in_transit' result."""
        return TrackingResult(
            external_shipment_id=external_shipment_id,
            tracking_code=external_shipment_id.replace("MOCK-", "TRK-"),
            current_status="in_transit",
            events=[
                TrackingEvent(
                    timestamp="2026-01-01T08:00:00+03:30",
                    status="created",
                    location="انبار مبدأ",
                    description="مرسوله ثبت شد",
                ),
                TrackingEvent(
                    timestamp="2026-01-01T10:00:00+03:30",
                    status="in_transit",
                    location="مرکز توزیع",
                    description="در حال حمل",
                ),
            ],
            estimated_delivery="2026-01-02",
        )

    def normalize_webhook(self, headers: dict, parsed_body: dict) -> VerifiedWebhookEvent:
        """Normalize mock webhook body to VerifiedWebhookEvent (post-signature-check)."""
        event_type = parsed_body.get("event_type", "")
        new_status = _MOCK_STATUS_MAP.get(event_type, "in_transit")
        return VerifiedWebhookEvent(
            provider_event_id=parsed_body.get("event_id", ""),
            event_type=event_type,
            external_shipment_id=parsed_body.get("shipment_id", ""),
            new_status=new_status,
            raw_metadata=parsed_body,
        )


def _hmac_sha256_hex(body: bytes, secret: bytes = MOCK_WEBHOOK_SECRET) -> str:
    """Helper for test code to generate a valid mock signature."""
    return hmac.new(secret, body, hashlib.sha256).hexdigest()
