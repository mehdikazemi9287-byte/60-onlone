# ConnectorAdapter v2 Contract Specification

## Introduction

The ConnectorAdapter v2 contract defines the interface that every integration adapter must implement in Phase 7. It replaces the informal, per-vendor integration code from earlier phases with a uniform API surface that supports capability declaration, incremental synchronisation, structured errors, and webhook verification.

Any code that depends on an external vendor — ERP, tax authority, logistics carrier, or data registry — must be wrapped in an adapter that conforms to this contract. Simulators (Mock adapters) implement the same interface so that the business logic above them can be tested without live vendor credentials.

---

## CapabilityDeclaration

Each adapter announces its capabilities through a `CapabilityDeclaration` dataclass returned by `get_capabilities()`. The runtime uses this declaration to decide which operations are valid to call on a given connector.

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class CapabilityDeclaration:
    """
    Describes what a connector can do.

    Fields
    ------
    connector_id : str
        Unique slug identifying the connector type (e.g. "sepidar_erp").
    display_name : str
        Human-readable name shown in the admin UI.
    capabilities : List[str]
        List of CAPABILITY_* constants this adapter implements.
    api_version : str
        The vendor API version this adapter targets (e.g. "v3.2").
        Use "simulator" for Mock adapters.
    requires_credentials : bool
        True if the adapter needs a credential_ref to operate.
        Mock adapters set this to False.
    supports_sandbox : bool
        True if the vendor offers a sandbox/test environment.
    documentation_url : str
        URL of the official vendor API documentation.
        Set to "" if no public documentation is available.
    """
    connector_id: str
    display_name: str
    capabilities: List[str]
    api_version: str
    requires_credentials: bool = True
    supports_sandbox: bool = False
    documentation_url: str = ""
```

---

## CAPABILITY_* Constants

The following 14 constants are the complete set recognised by Phase 7. An adapter must not claim a capability it does not implement.

```python
# Inventory / product data synchronisation
CAPABILITY_INVENTORY_READ    = "inventory_read"
CAPABILITY_INVENTORY_WRITE   = "inventory_write"

# Order lifecycle
CAPABILITY_ORDER_READ        = "order_read"
CAPABILITY_ORDER_WRITE       = "order_write"
CAPABILITY_ORDER_STATUS_PUSH = "order_status_push"

# Financial / accounting
CAPABILITY_INVOICE_POST      = "invoice_post"
CAPABILITY_PAYMENT_READ      = "payment_read"

# Tax authority
CAPABILITY_TAX_CALCULATE     = "tax_calculate"
CAPABILITY_TAX_SUBMIT        = "tax_submit"
CAPABILITY_TAX_STATUS_READ   = "tax_status_read"

# Logistics
CAPABILITY_SHIPMENT_CREATE   = "shipment_create"
CAPABILITY_SHIPMENT_TRACK    = "shipment_track"
CAPABILITY_SHIPMENT_CANCEL   = "shipment_cancel"

# Webhook ingestion
CAPABILITY_WEBHOOK_RECEIVE   = "webhook_receive"
```

---

## SyncCursor

`SyncCursor` is an opaque object used to track the position of an incremental synchronisation. Adapters that support `CAPABILITY_INVENTORY_READ` or `CAPABILITY_ORDER_READ` must accept and return a cursor so that the caller can resume from the last successful checkpoint without re-fetching the full dataset.

```python
import json
from dataclasses import dataclass
from typing import Optional

@dataclass
class SyncCursor:
    """
    Opaque cursor for incremental synchronisation.

    The contents of `value` are owned by the adapter implementation.
    Callers must treat it as an opaque string and must not parse or
    mutate it. The cursor is serialised to JSON and stored in the
    connector_accounts.sync_cursor column between sync runs.

    Parameters
    ----------
    value : str
        Adapter-defined cursor payload. Examples: a timestamp string,
        a page token from a vendor API, or a base64-encoded struct.
    is_complete : bool
        True when the adapter has returned all available records up to
        the current point in time. False when more pages remain.
    """
    value: str
    is_complete: bool = False

    def to_json(self) -> str:
        return json.dumps({"value": self.value, "is_complete": self.is_complete})

    @classmethod
    def from_json(cls, raw: str) -> "SyncCursor":
        data = json.loads(raw)
        return cls(value=data["value"], is_complete=data.get("is_complete", False))

    @classmethod
    def initial(cls) -> "SyncCursor":
        """Return a cursor that instructs the adapter to start from the beginning."""
        return cls(value="", is_complete=False)
```

---

## ConnectorError and ConnectorErrorCode

All adapter methods must raise `ConnectorError` on failure. Callers use the `code` field to determine retry semantics. Raising a plain `Exception` is not permitted.

```python
from enum import Enum

class ConnectorErrorCode(Enum):
    """
    Structured error codes for adapter failures.

    Retry semantics
    ---------------
    TRANSIENT        - Safe to retry immediately (network blip, 502/503).
    RATE_LIMITED     - Retry after the duration in retry_after_seconds.
    AUTH_FAILURE     - Do not retry. Credential must be rotated.
    NOT_FOUND        - Do not retry. Resource does not exist on vendor side.
    INVALID_PAYLOAD  - Do not retry. Request payload was rejected by vendor.
    CIRCUIT_OPEN     - Do not retry now. Circuit breaker is OPEN; wait for
                       HALF_OPEN transition.
    NOT_IMPLEMENTED  - Do not retry. Adapter is a stub. This code must never
                       appear in production traffic.
    VENDOR_ERROR     - Retry with backoff. Vendor returned an unexpected 5xx.
    TIMEOUT          - Retry with backoff. Request exceeded timeout threshold.
    """
    TRANSIENT       = "transient"
    RATE_LIMITED    = "rate_limited"
    AUTH_FAILURE    = "auth_failure"
    NOT_FOUND       = "not_found"
    INVALID_PAYLOAD = "invalid_payload"
    CIRCUIT_OPEN    = "circuit_open"
    NOT_IMPLEMENTED = "not_implemented"
    VENDOR_ERROR    = "vendor_error"
    TIMEOUT         = "timeout"


class ConnectorError(Exception):
    """
    Raised by all adapter methods on failure.

    Parameters
    ----------
    code : ConnectorErrorCode
        Machine-readable error category.
    message : str
        Human-readable description for logging.
    retry_after_seconds : int | None
        For RATE_LIMITED errors: the number of seconds the caller must
        wait before retrying. None for all other error codes.
    vendor_error_id : str | None
        If the vendor returned a trace or request ID, record it here
        so it can be included in support requests.
    """
    def __init__(
        self,
        code: ConnectorErrorCode,
        message: str,
        retry_after_seconds: int | None = None,
        vendor_error_id: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        self.vendor_error_id = vendor_error_id
```

### Retry Decision Table

| ConnectorErrorCode | Retry? | Strategy |
|-------------------|--------|----------|
| `TRANSIENT` | Yes | Immediate, up to 3 attempts |
| `RATE_LIMITED` | Yes | Wait `retry_after_seconds`, then retry |
| `AUTH_FAILURE` | No | Alert operator; stop processing |
| `NOT_FOUND` | No | Dead-letter the event |
| `INVALID_PAYLOAD` | No | Dead-letter; inspect payload |
| `CIRCUIT_OPEN` | Deferred | Re-queue; wait for HALF_OPEN |
| `NOT_IMPLEMENTED` | No | Programming error; raise alarm |
| `VENDOR_ERROR` | Yes | Exponential backoff |
| `TIMEOUT` | Yes | Exponential backoff |

---

## WebhookVerificationResult

Adapters that declare `CAPABILITY_WEBHOOK_RECEIVE` must implement `verify_webhook()`, which returns a `WebhookVerificationResult`.

```python
from dataclasses import dataclass

@dataclass
class WebhookVerificationResult:
    """
    Result of webhook signature verification.

    Fields
    ------
    verified : bool
        True only if the HMAC signature matched. When False, the
        caller must return HTTP 401 and discard the payload.
    event_type : str
        Vendor-specific event type string, normalised to lowercase
        with underscores (e.g. "order_status_changed").
    idempotency_key : str
        Unique identifier for this webhook delivery. Used to detect
        duplicate deliveries from the vendor's retry mechanism.
    raw_event : dict
        The parsed JSON body. Only populated when verified is True.
    """
    verified: bool
    event_type: str = ""
    idempotency_key: str = ""
    raw_event: dict = None

    def __post_init__(self):
        if self.raw_event is None:
            self.raw_event = {}
```

---

## Base Adapter Method Signatures

Every adapter must inherit from `ConnectorAdapterBase` and implement the methods appropriate to its declared capabilities.

```python
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Dict, Any


class ConnectorAdapterBase(ABC):
    """
    Abstract base for all Phase 7 connector adapters.

    Subclasses declare capabilities via get_capabilities() and
    implement only the methods corresponding to those capabilities.
    Calling an unimplemented method must raise ConnectorError with
    code=ConnectorErrorCode.NOT_IMPLEMENTED.
    """

    @abstractmethod
    def get_capabilities(self) -> CapabilityDeclaration:
        """Return the capability declaration for this adapter."""
        ...

    def health_check(self) -> bool:
        """
        Perform a lightweight liveness check against the vendor.
        Returns True if the vendor is reachable, False otherwise.
        Must not raise; catch all exceptions internally.
        Default implementation returns True (suitable for simulators).
        """
        return True

    # ------------------------------------------------------------------ #
    # Inventory                                                            #
    # ------------------------------------------------------------------ #

    def fetch_inventory(
        self,
        cursor: SyncCursor,
        page_size: int = 100,
    ) -> Tuple[List[Dict[str, Any]], SyncCursor]:
        """
        Fetch a page of inventory records from the vendor.

        Parameters
        ----------
        cursor : SyncCursor
            Position to resume from. Use SyncCursor.initial() for
            the first call.
        page_size : int
            Maximum number of records to return per call.

        Returns
        -------
        records : list[dict]
            Normalised inventory records. Each dict must contain at
            minimum: sku (str), quantity_on_hand (int), updated_at (str ISO-8601).
        next_cursor : SyncCursor
            Cursor to pass to the next call. is_complete=True when
            there are no further pages.

        Raises
        ------
        ConnectorError
        """
        raise ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, "fetch_inventory not implemented")

    # ------------------------------------------------------------------ #
    # Orders                                                               #
    # ------------------------------------------------------------------ #

    def fetch_orders(
        self,
        cursor: SyncCursor,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], SyncCursor]:
        """Fetch orders from the vendor, resuming from cursor."""
        raise ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, "fetch_orders not implemented")

    def push_order_status(self, order_id: str, status: str, metadata: Dict[str, Any]) -> bool:
        """
        Push an order status update to the vendor.

        Returns True on success. Raises ConnectorError on failure.
        Requires CAPABILITY_ORDER_STATUS_PUSH.
        """
        raise ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, "push_order_status not implemented")

    # ------------------------------------------------------------------ #
    # Invoicing                                                            #
    # ------------------------------------------------------------------ #

    def post_invoice(self, invoice: Dict[str, Any]) -> str:
        """
        Post a sales invoice to the ERP or accounting system.

        Parameters
        ----------
        invoice : dict
            Normalised invoice payload. All amounts in IRR integer rials.
            Must include: invoice_number, invoice_date, supplier_id,
            line_items (list), tax_amount_irr (int), total_irr (int).

        Returns
        -------
        str
            Vendor-assigned document reference (e.g. Sepidar document ID).
            Return a simulated reference for Mock adapters.

        Raises
        ------
        ConnectorError
        """
        raise ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, "post_invoice not implemented")

    # ------------------------------------------------------------------ #
    # Webhooks                                                             #
    # ------------------------------------------------------------------ #

    def verify_webhook(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str,
    ) -> WebhookVerificationResult:
        """
        Verify the authenticity of an incoming webhook payload.

        Default implementation returns verified=False (fail-closed).
        Adapters that declare CAPABILITY_WEBHOOK_RECEIVE must override
        this method with vendor-specific HMAC or signature logic.
        """
        return WebhookVerificationResult(verified=False)

    def normalize_webhook(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a vendor-specific webhook payload into the 60online
        canonical event format.

        Raises ConnectorError(NOT_IMPLEMENTED) by default.
        """
        raise ConnectorError(ConnectorErrorCode.NOT_IMPLEMENTED, "normalize_webhook not implemented")
```

---

## Mock Adapter Pattern

All simulator adapters follow the same pattern: they implement the full interface, return realistic-looking synthetic data, and set `api_version = "simulator"` in their `CapabilityDeclaration`. They do not make any HTTP calls and do not require credentials.

```python
import uuid
from datetime import datetime, timezone

class MockERPAdapter(ConnectorAdapterBase):
    """
    Simulator ERP adapter for development and testing.
    Returns deterministic synthetic data. No network calls.
    """

    def get_capabilities(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            connector_id="mock_erp",
            display_name="Mock ERP (Simulator)",
            capabilities=[
                CAPABILITY_INVENTORY_READ,
                CAPABILITY_INVENTORY_WRITE,
                CAPABILITY_ORDER_READ,
                CAPABILITY_INVOICE_POST,
            ],
            api_version="simulator",
            requires_credentials=False,
            supports_sandbox=False,
            documentation_url="",
        )

    def post_invoice(self, invoice: dict) -> str:
        # Simulate a successful ERP document creation.
        return f"MOCK-DOC-{uuid.uuid4().hex[:8].upper()}"

    def fetch_inventory(self, cursor: SyncCursor, page_size: int = 100):
        records = [
            {"sku": f"SKU-{i:04d}", "quantity_on_hand": i * 10, "updated_at": datetime.now(timezone.utc).isoformat()}
            for i in range(1, min(page_size, 5) + 1)
        ]
        return records, SyncCursor(value="end", is_complete=True)
```
