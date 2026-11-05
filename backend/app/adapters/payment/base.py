"""Payment provider port.

Checkout depends on this interface only, never on a concrete PSP. Adding
Zarinpal / IPG / a BNPL later means adding one module that implements
`PaymentProvider` and registering it in `app.adapters.payment.registry`.
No call site changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class PaymentStatus(str, Enum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class PaymentRequest:
    amount_minor: int
    currency: str
    order_reference: str
    idempotency_key: str
    customer_email: str
    method: str = "card"
    metadata: dict | None = None


@dataclass(frozen=True)
class PaymentResult:
    status: PaymentStatus
    provider: str
    provider_ref: str
    amount_minor: int
    currency: str
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED)


@dataclass(frozen=True)
class RefundResult:
    status: PaymentStatus
    provider: str
    provider_ref: str
    amount_minor: int


class PaymentProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def charge(self, request: PaymentRequest) -> PaymentResult:
        """Authorize+capture in one step. MUST be idempotent on idempotency_key."""

    @abc.abstractmethod
    def refund(self, provider_ref: str, amount_minor: int, idempotency_key: str) -> RefundResult:
        """Refund a previous charge. MUST be idempotent on idempotency_key."""


@dataclass(frozen=True)
class RedirectInstruction:
    """Where the browser must go to pay: a URL plus the form fields to POST (or GET) there."""
    url: str
    method: str
    fields: dict
    provider: str
    provider_ref: str  # the gateway's session handle (e.g. a token), kept on the intent

    def to_dict(self) -> dict:
        return {"url": self.url, "method": self.method, "fields": dict(self.fields),
                "provider": self.provider}


class GatewayError(Exception):
    """The gateway could not be reached or refused the request. No money moved."""


class RedirectPaymentProvider(PaymentProvider):
    """A gateway where the customer pays on the bank's page (every Iranian IPG / Shaparak PSP).

    Flow: ``initiate`` (server→gateway, get a session) → browser goes to the gateway →
    gateway returns the browser to our callback → ``verify`` (server→gateway) settles it.
    Money moves only on the gateway page; ``verify`` is what makes it final for us.
    """

    def charge(self, request: PaymentRequest) -> PaymentResult:  # pragma: no cover - contract
        raise NotImplementedError(f"{self.name} is a redirect gateway; use initiate/verify")

    @abc.abstractmethod
    def initiate(self, request: PaymentRequest, *, invoice_id: int, callback_url: str) -> RedirectInstruction:
        """Open a payment session. Raises GatewayError if the gateway refuses."""

    @abc.abstractmethod
    def verify(self, callback: dict, *, expected_amount_minor: int, currency: str) -> PaymentResult:
        """Check a callback with the gateway and confirm the exact amount. Never trusts the callback alone."""

    @abc.abstractmethod
    def reverse(self, callback: dict) -> bool:
        """Return money already taken for a payment we cannot honour. True if the gateway confirmed it."""

    @staticmethod
    @abc.abstractmethod
    def invoice_id_of(callback: dict) -> int | None:
        """Our invoice id (the payment intent id) as echoed back by the gateway, or None."""
