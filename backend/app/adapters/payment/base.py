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
