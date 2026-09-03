"""Universal Integration Gateway — Connector Adapter v2.

Every external data source (ERP, chain-store, wholesaler, CSV, webhook,
SFTP, carrier, accounting system) MUST implement this interface.

PHASE 7 EXTENSIONS over Phase 6:
  - push_inventory(), pull_orders(), pull_invoices(), acknowledge()
  - handle_webhook(), verify_webhook_signature()
  - incremental / cursor-based sync
  - pagination contract
  - error classification (ConnectorError / ConnectorErrorCode)
  - capabilities() returns structured CapabilityDeclaration

SECURITY:
  - Credentials are received as a reference key ONLY (credential_ref).
  - Adapters MUST NOT log, store, or return raw credential values.
  - Default behaviour for unimplemented methods: raise ConnectorError
    with code=NOT_IMPLEMENTED (fail-closed design).

REAL PROVIDER INTEGRATIONS — NOT IMPLEMENTED:
  Holo, Sepidar, Rahkaran, SAP, Odoo, AloPeyk, Post, Tipax, Chapar,
  Moadian and similar external systems are represented by
  NotYetImplementedAdapter stubs. This module provides only the abstract
  contract that all of them must satisfy.

CONNECTOR CONTRACT VERSION: 2.0
"""
from __future__ import annotations

import enum
import hashlib
import hmac
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.runtime_credentials import RuntimeCredentials


# ─────────────────────────────────────────────────────────────────────────────
# Error classification
# ─────────────────────────────────────────────────────────────────────────────

class ConnectorErrorCode(str, enum.Enum):
    """Stable error codes for connector failures.

    Services and circuit breakers use these codes to decide retry / escalation
    policy rather than inspecting raw exception messages.
    """
    AUTH_FAILED        = "AUTH_FAILED"        # credential rejected
    AUTH_EXPIRED       = "AUTH_EXPIRED"       # token/session expired → refresh
    RATE_LIMITED       = "RATE_LIMITED"       # 429 / quota exhausted
    TIMEOUT            = "TIMEOUT"            # network / response timeout
    CONNECTION_REFUSED = "CONNECTION_REFUSED" # can't reach host
    INVALID_RESPONSE   = "INVALID_RESPONSE"   # unexpected payload shape
    SERVER_ERROR       = "SERVER_ERROR"       # 5xx from external system
    NOT_FOUND          = "NOT_FOUND"          # resource absent
    VALIDATION_ERROR   = "VALIDATION_ERROR"   # our request was malformed
    NOT_IMPLEMENTED    = "NOT_IMPLEMENTED"    # adapter stub — not yet built
    UNKNOWN            = "UNKNOWN"            # unclassified


class ConnectorError(Exception):
    """Raised by adapter implementations when an operation fails.

    Use ``code`` for programmatic handling; use str(e) for logging.
    ``retryable`` means it is safe to retry after a delay.
    """

    def __init__(
        self,
        message: str,
        code: ConnectorErrorCode = ConnectorErrorCode.UNKNOWN,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        raw: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status
        # raw may contain response body; do NOT log credentials inside it
        self.raw = raw


# ─────────────────────────────────────────────────────────────────────────────
# Capability constants
# ─────────────────────────────────────────────────────────────────────────────

CAPABILITY_PULL_PRODUCTS   = "pull_products"
CAPABILITY_PULL_PRICES     = "pull_prices"
CAPABILITY_PULL_INVENTORY  = "pull_inventory"
CAPABILITY_PUSH_INVENTORY  = "push_inventory"
CAPABILITY_PULL_ORDERS     = "pull_orders"
CAPABILITY_PUSH_ORDERS     = "push_orders"
CAPABILITY_PULL_INVOICES   = "pull_invoices"
CAPABILITY_PUSH_INVOICES   = "push_invoices"
CAPABILITY_ACKNOWLEDGE     = "acknowledge"
CAPABILITY_WEBHOOK         = "webhook"
CAPABILITY_CURSOR_SYNC     = "cursor_sync"
CAPABILITY_HEALTH_CHECK    = "health_check"
CAPABILITY_RESOLVE_PRODUCT = "resolve_product"

ALL_KNOWN_CAPABILITIES = frozenset({
    CAPABILITY_PULL_PRODUCTS,
    CAPABILITY_PULL_PRICES,
    CAPABILITY_PULL_INVENTORY,
    CAPABILITY_PUSH_INVENTORY,
    CAPABILITY_PULL_ORDERS,
    CAPABILITY_PUSH_ORDERS,
    CAPABILITY_PULL_INVOICES,
    CAPABILITY_PUSH_INVOICES,
    CAPABILITY_ACKNOWLEDGE,
    CAPABILITY_WEBHOOK,
    CAPABILITY_CURSOR_SYNC,
    CAPABILITY_HEALTH_CHECK,
    CAPABILITY_RESOLVE_PRODUCT,
})


# ─────────────────────────────────────────────────────────────────────────────
# Capability declaration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CapabilityDeclaration:
    """Structured declaration of what a connector can do."""
    connector_type: str
    adapter_name: str
    version: str = "2.0"
    supported: list[str] = field(default_factory=list)
    transport: str = "PULL"
    # PULL | PUSH | WEBHOOK | FILE | HYBRID
    rate_limit_rps: float | None = None
    supports_cursor_sync: bool = False
    supports_pagination: bool = True
    max_page_size: int = 500
    implementation_status: str = "not_implemented"
    # not_implemented | simulator | verified | production
    verified_docs_url: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "connector_type": self.connector_type,
            "adapter_name": self.adapter_name,
            "version": self.version,
            "supported": self.supported,
            "transport": self.transport,
            "rate_limit_rps": self.rate_limit_rps,
            "supports_cursor_sync": self.supports_cursor_sync,
            "supports_pagination": self.supports_pagination,
            "max_page_size": self.max_page_size,
            "implementation_status": self.implementation_status,
            "verified_docs_url": self.verified_docs_url,
            "notes": self.notes,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Sync cursor
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SyncCursor:
    """Opaque incremental sync position.

    Adapters that support cursor sync store per-entity cursors so that
    only records changed since the last successful sync are pulled.
    """
    product: str | None = None
    price: str | None = None
    inventory: str | None = None
    order: str | None = None
    invoice: str | None = None
    raw: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "product": self.product,
            "price": self.price,
            "inventory": self.inventory,
            "order": self.order,
            "invoice": self.invoice,
            **self.raw,
        }

    @classmethod
    def from_json(cls, d: dict | None) -> "SyncCursor":
        if not d:
            return cls()
        return cls(
            product=d.get("product"),
            price=d.get("price"),
            inventory=d.get("inventory"),
            order=d.get("order"),
            invoice=d.get("invoice"),
            raw={k: v for k, v in d.items()
                 if k not in ("product", "price", "inventory", "order", "invoice")},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Webhook verification result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WebhookVerificationResult:
    """Result of inbound webhook verification."""
    verified: bool
    event_type: str = ""
    external_event_id: str = ""
    payload: dict = field(default_factory=dict)
    rejection_reason: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Abstract connector adapter — v2
# ─────────────────────────────────────────────────────────────────────────────

class ConnectorAdapter:
    """Universal connector adapter interface — contract version 2.0.

    Design rules:
    1. All methods MUST raise ConnectorError on failure (not raw exceptions).
    2. Adapters MUST declare their capabilities via capabilities().
    3. Credentials MUST NOT be logged or returned.
    4. Default behaviour for unimplemented methods: raise ConnectorError
       with code=NOT_IMPLEMENTED (fail-closed, not fail-open).
    5. Pagination: all list-returning methods accept limit + offset.
    6. Cursor sync: methods accepting cursor return an updated cursor.
    7. No business service may depend directly on a specific vendor adapter.
    """

    #: Human-readable adapter name (used in error messages and logs)
    adapter_name: str = "base"

    # ── Capability declaration ────────────────────────────────────────────────

    def capabilities(self) -> CapabilityDeclaration:
        """Return structured capability declaration.

        Every concrete adapter MUST override this to declare which operations
        it actually implements.
        """
        return CapabilityDeclaration(
            connector_type=self.adapter_name,
            adapter_name=self.adapter_name,
            supported=[],
            implementation_status="not_implemented",
        )

    # ── Health check ─────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Return {"healthy": bool, "message": str, "latency_ms": int|None}"""
        return {
            "healthy": False,
            "message": f"{self.adapter_name}: سلامت‌سنجی پیاده‌سازی نشده",
            "latency_ms": None,
        }

    # ── Product / catalogue operations ────────────────────────────────────────

    def pull_products(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        cursor: SyncCursor | None = None,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> tuple[list[dict], SyncCursor | None]:
        """Pull external product records.

        Returns (records, updated_cursor). Cursor is None if not supported.

        Record schema (required: code, name; all others optional):
            code, name, description, unit, price_minor, currency,
            stock_quantity, barcode, sku, gtin, mpn, brand,
            weight_g, attributes_json, synced_at

        Args:
            runtime_credentials: Transiently resolved credential material.
                Passed by the outbox worker immediately before an external
                operation.  MUST NOT be stored, logged, or persisted.
        """
        raise ConnectorError(
            f"{self.adapter_name}: pull_products پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def pull_prices(
        self,
        *,
        product_codes: list[str] | None = None,
        limit: int = 500,
        offset: int = 0,
        cursor: SyncCursor | None = None,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> tuple[list[dict], SyncCursor | None]:
        """Pull price records.

        Record schema: {code, price_minor, currency, updated_at}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: pull_prices پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def pull_inventory(
        self,
        *,
        product_codes: list[str] | None = None,
        limit: int = 500,
        offset: int = 0,
        cursor: SyncCursor | None = None,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> tuple[list[dict], SyncCursor | None]:
        """Pull inventory / stock records.

        Record schema: {code, stock_quantity, location_id, updated_at}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: pull_inventory پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def push_inventory(
        self,
        inventory_updates: list[dict],
        *,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> dict:
        """Push inventory adjustments to the external system.

        Each update: {code, delta_quantity, location_id, reason}
        Returns: {acknowledged: bool, failed: list[dict], message: str}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: push_inventory پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    # ── Order operations ──────────────────────────────────────────────────────

    def push_order(
        self,
        order_data: dict,
        *,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> dict:
        """Push a confirmed purchase order to the external system.

        Returns: {"acknowledged": bool, "external_ref": str|None, "message": str}

        Args:
            runtime_credentials: Transiently resolved credential material.
                The adapter uses this to authenticate the outbound request.
                MUST NOT be stored, logged, or persisted.
        """
        raise ConnectorError(
            f"{self.adapter_name}: push_order پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def pull_orders(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        cursor: SyncCursor | None = None,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> tuple[list[dict], SyncCursor | None]:
        """Pull orders from the external system.

        Record schema: {external_order_id, status, items, total_minor, ...}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: pull_orders پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    # ── Invoice / accounting operations ───────────────────────────────────────

    def pull_invoices(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        cursor: SyncCursor | None = None,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> tuple[list[dict], SyncCursor | None]:
        """Pull invoices from the external accounting system.

        Record schema: {doc_id, doc_number, doc_type, total_minor, ...}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: pull_invoices پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def push_invoice(
        self,
        invoice_data: dict,
        *,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> dict:
        """Push a sales/purchase invoice to the external accounting system.

        Returns: {acknowledged: bool, external_doc_id: str|None, message: str}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: push_invoice پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    def acknowledge(
        self,
        *,
        event_type: str,
        external_ref: str,
        payload: dict,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> dict:
        """Acknowledge receipt of an external event (push / webhook flows).

        Returns: {acknowledged: bool, message: str}

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: acknowledge پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    # ── Product identity resolution ───────────────────────────────────────────

    def resolve_product(
        self,
        *,
        identifier_type: str,
        identifier_value: str,
        runtime_credentials: "RuntimeCredentials | None" = None,
    ) -> dict | None:
        """Resolve a product by identifier (barcode, SKU, ERP code, GTIN, etc.).

        Returns external product dict or None if not found.

        Args:
            runtime_credentials: Transiently resolved credential material.
        """
        raise ConnectorError(
            f"{self.adapter_name}: resolve_product پیاده‌سازی نشده",
            code=ConnectorErrorCode.NOT_IMPLEMENTED,
        )

    # ── Webhook handling ──────────────────────────────────────────────────────

    def verify_webhook_signature(
        self,
        headers: dict[str, str],
        raw_body: bytes,
        secret: str,
    ) -> bool:
        """Verify an inbound webhook signature using HMAC-SHA256.

        Default implementation: REJECT (fail-closed).
        Subclasses that support webhooks MUST override this.
        """
        return False

    def handle_webhook(
        self,
        headers: dict[str, str],
        raw_body: bytes,
        *,
        secret: str | None = None,
    ) -> WebhookVerificationResult:
        """Parse and verify an inbound webhook payload.

        Default: reject all webhooks.
        Subclasses with CAPABILITY_WEBHOOK MUST override this.
        """
        return WebhookVerificationResult(
            verified=False,
            rejection_reason=f"{self.adapter_name}: webhook processing not implemented",
        )

    # ── HMAC helpers (available to all subclasses) ────────────────────────────

    @staticmethod
    def _hmac_sha256(secret: str, body: bytes) -> str:
        """Compute HMAC-SHA256 of body. Returns lower-case hex digest."""
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _constant_time_compare(a: str, b: str) -> bool:
        """Compare two strings in constant time to prevent timing attacks."""
        return hmac.compare_digest(a, b)
