# Logistics Connector Guide

## Introduction

The Phase 7 logistics layer enables 60online to create shipments, retrieve tracking events, and receive delivery status webhooks from external carriers. The design follows the same adapter pattern as the ERP connectors: a `CarrierAdapterBase` defines the contract, simulator adapters implement it for development and testing, and real carrier adapters are implemented only when official API documentation is available.

As of Phase 7, only the Mock carrier adapter is in production use. AloPeyk, Post.ir, Tipax, and Chapar are all `NOT IMPLEMENTED` because their APIs are either partner-only, undocumented, or require a signed agreement that has not been obtained.

---

## CarrierAdapter v2 Contract

The carrier adapter contract is a specialised extension of the base ConnectorAdapter contract. It exposes logistics-specific operations in addition to the generic capability declarations.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..connector_base import (
    ConnectorAdapterBase,
    CapabilityDeclaration,
    ConnectorError,
    ConnectorErrorCode,
    WebhookVerificationResult,
    CAPABILITY_SHIPMENT_CREATE,
    CAPABILITY_SHIPMENT_TRACK,
    CAPABILITY_SHIPMENT_CANCEL,
    CAPABILITY_WEBHOOK_RECEIVE,
)


@dataclass
class ShipmentQuote:
    """
    A shipping rate quote from a carrier.

    Attributes
    ----------
    carrier_service_code : str
        Carrier-specific service identifier (e.g. "express_24h").
    display_name : str
        Human-readable service name (e.g. "AloPeyk Express").
    price_irr : int
        Shipping price in integer Iranian Rials (minor units).
    estimated_delivery_days : int
        Estimated transit time in calendar days.
    currency : str
        Always "IRR" for Iranian carriers in Phase 7.
    """
    carrier_service_code: str
    display_name: str
    price_irr: int
    estimated_delivery_days: int
    currency: str = "IRR"


@dataclass
class ShipmentRecord:
    """
    The result of a successful shipment creation.

    Attributes
    ----------
    shipment_id : str
        60online internal shipment UUID.
    carrier_tracking_number : str
        The tracking number assigned by the carrier.
    carrier_label_url : str
        URL to download the shipping label PDF or image.
        Empty string if the carrier does not provide labels.
    carrier_reference : str
        The carrier's internal order/booking reference.
    """
    shipment_id: str
    carrier_tracking_number: str
    carrier_label_url: str
    carrier_reference: str


@dataclass
class TrackingEvent:
    """
    A single tracking event in a shipment's history.

    Attributes
    ----------
    event_at : str
        ISO-8601 timestamp of the event in UTC.
    status_code : str
        Normalised status code from the carrier normalisation layer.
        One of: picked_up, in_transit, out_for_delivery, delivered,
        exception, returned, cancelled.
    description : str
        Human-readable event description in the carrier's language.
    location : str
        Location name or facility code where the event occurred.
    """
    event_at: str
    status_code: str
    description: str
    location: str = ""
```

### Method Signatures

```python
class CarrierAdapterBase(ConnectorAdapterBase, ABC):
    """
    Abstract base for all Phase 7 carrier (logistics) adapters.
    """

    @abstractmethod
    def get_quotes(
        self,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        parcels: List[Dict[str, Any]],
    ) -> List[ShipmentQuote]:
        """
        Retrieve shipping rate quotes from the carrier.

        Parameters
        ----------
        origin : dict
            Sender address. Required keys: city, province, postal_code,
            address_line1. Optional: lat, lon.
        destination : dict
            Recipient address. Same structure as origin.
        parcels : list[dict]
            List of parcel specs. Each dict must include:
            weight_grams (int), length_cm (int), width_cm (int),
            height_cm (int).

        Returns
        -------
        list[ShipmentQuote]
            Available rate options. Empty list if no services are
            available for the origin/destination pair.

        Raises
        ------
        ConnectorError
        """
        ...

    @abstractmethod
    def create_shipment(
        self,
        quote_service_code: str,
        origin: Dict[str, Any],
        destination: Dict[str, Any],
        parcels: List[Dict[str, Any]],
        booking_idempotency_key: str,
    ) -> ShipmentRecord:
        """
        Book a shipment with the carrier.

        Parameters
        ----------
        quote_service_code : str
            The service code from a ShipmentQuote returned by get_quotes().
        origin, destination, parcels
            Same as get_quotes().
        booking_idempotency_key : str
            A UUID that uniquely identifies this booking attempt.
            The carrier adapter must pass this key to the vendor
            (as a header or request field) if the vendor supports it.
            If the vendor does not support idempotency keys, the adapter
            must use it locally to detect and suppress duplicate calls.

        Returns
        -------
        ShipmentRecord

        Raises
        ------
        ConnectorError
        """
        ...

    @abstractmethod
    def cancel_shipment(self, carrier_reference: str) -> bool:
        """
        Request cancellation of a booked shipment.

        Returns True if the cancellation was accepted. Returns False if
        the carrier indicates the shipment cannot be cancelled (e.g.
        already picked up). Raises ConnectorError for network or auth errors.
        """
        ...

    @abstractmethod
    def get_tracking(self, carrier_tracking_number: str) -> List[TrackingEvent]:
        """
        Retrieve the full tracking history for a shipment.

        Returns a list of TrackingEvent objects in ascending chronological
        order (oldest event first).
        """
        ...

    def normalize_webhook(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a carrier-specific webhook payload into the 60online
        canonical tracking event format.

        The normalised dict must contain:
          carrier_tracking_number (str)
          status_code (str) — one of the normalised status codes
          event_at (str ISO-8601)
          raw_payload (dict) — the unmodified vendor payload
        """
        raise ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, "normalize_webhook not implemented")

    def verify_webhook(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
    ) -> WebhookVerificationResult:
        """
        Verify webhook authenticity. Default is fail-closed (rejected).
        Adapters declaring CAPABILITY_WEBHOOK_RECEIVE must override this.
        """
        return WebhookVerificationResult(verified=False)
```

---

## Idempotency via booking_idempotency_key

Every call to `create_shipment()` must include a `booking_idempotency_key`. This is a UUID generated by the 60online business layer before the first booking attempt and stored in the `shipments.idempotency_key` column.

The purpose of the idempotency key is to handle the case where the carrier's HTTP response is lost in transit. Without it, a retry would create a duplicate shipment and bill the merchant twice. With it, the carrier (if it supports idempotency) can recognise the repeated request and return the original booking instead of creating a new one.

For carriers that do not support server-side idempotency (which is the common case for Iranian carriers), the adapter must maintain a local check:

```python
def create_shipment(self, ..., booking_idempotency_key: str) -> ShipmentRecord:
    # Check the local idempotency cache before calling the carrier API.
    cached = self._idempotency_store.get(booking_idempotency_key)
    if cached is not None:
        return cached

    result = self._call_carrier_api(...)

    self._idempotency_store.set(booking_idempotency_key, result)
    return result
```

In the 60online deployment, the `shipments` table itself acts as the idempotency store. The outbox worker checks for an existing `shipments` row with the matching `idempotency_key` before dispatching a `create_shipment` event.

---

## Webhook Security

All carrier webhook endpoints must implement `verify_webhook()`. The default behaviour of `CarrierAdapterBase` is to return `WebhookVerificationResult(verified=False)`, which causes the HTTP handler to return `401 Unauthorized` and discard the payload.

This is the **fail-closed** design: a webhook that cannot be verified is treated as malicious or corrupt, not as a valid update. Failing open (accepting unverified webhooks) would allow any party to forge delivery status updates and mark orders as delivered without carrier confirmation.

The standard verification method is HMAC-SHA256 over the raw request body using a shared secret stored as a `credential_ref`. The computed digest is compared against the signature provided in the request header. The comparison must be done using `hmac.compare_digest()` to prevent timing attacks.

```python
import hashlib
import hmac

def verify_webhook(self, headers, raw_body, secret):
    carrier_sig = headers.get("X-Carrier-Signature", "")
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if hmac.compare_digest(carrier_sig, expected):
        payload = json.loads(raw_body)
        return WebhookVerificationResult(
            verified=True,
            event_type=payload.get("event_type", ""),
            idempotency_key=payload.get("event_id", ""),
            raw_event=payload,
        )
    return WebhookVerificationResult(verified=False)
```

---

## Current Carrier Status Matrix

| Carrier | Type | Status | Official Docs | Notes |
|---------|------|--------|---------------|-------|
| Mock Carrier | Simulator | Production | — | Returns synthetic tracking data; no network calls |
| AloPeyk (الوپیک) | On-demand / same-day | NOT IMPLEMENTED | Partner agreement required | REST API exists but requires a signed partnership agreement with AloPeyk. No public documentation. |
| Post.ir (پست ایران) | National postal | NOT IMPLEMENTED | No public API docs found | Iran Post does not publish a machine-readable API. Integration would require an official business agreement. |
| Tipax (تیپاکس) | Express parcel | NOT IMPLEMENTED | No public API docs found | Tipax does not publish API documentation publicly. |
| Chapar (چاپار) | Express parcel | NOT IMPLEMENTED | No public API docs found | Chapar does not publish API documentation publicly. |

### Notes on Iranian Carrier APIs

Iranian logistics companies generally do not publish public API documentation. Integration typically requires:

1. A signed business agreement (قرارداد همکاری) with the carrier.
2. A dedicated API account or client ID issued by the carrier's technical team.
3. A private API specification document distributed after the agreement is signed.

Until such agreements are in place and documentation is obtained, all Iranian carrier adapters remain `NOT IMPLEMENTED`. Attempting to implement these adapters based on reverse-engineered endpoints from network captures would create maintenance risk and may violate the carrier's terms of service.

---

## Mock Carrier Adapter

The `MockCarrierAdapter` is the only carrier adapter in production use as of Phase 7. It provides full capability coverage for development and testing:

- `get_quotes()` returns two synthetic rate options: `standard_5day` (200,000 IRR) and `express_2day` (500,000 IRR).
- `create_shipment()` returns a synthetic tracking number in the format `MOCK-TRACK-XXXXXXXX`.
- `get_tracking()` returns a simulated 3-event history: `picked_up` → `in_transit` → `delivered`.
- `verify_webhook()` accepts all requests where the `X-Mock-Signature` header matches `sha256(secret + body)`.

The mock adapter is sufficient for end-to-end integration testing of the order fulfilment flow, including outbox dispatch, circuit breaker state transitions, and webhook ingestion.
