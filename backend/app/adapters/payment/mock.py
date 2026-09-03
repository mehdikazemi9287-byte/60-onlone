"""In-process mock PSP used for the demo.

Behaviour is deterministic so integration tests can assert on it:
  * a repeated idempotency_key returns the identical stored result
  * an amount whose minor value ends in 13 is declined (test hook for the
    failure path) -- see MockPaymentProvider.DECLINE_SUFFIX
"""
from __future__ import annotations

import hashlib
import threading

from app.adapters.payment.base import (
    PaymentProvider,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    RefundResult,
)


class MockPaymentProvider(PaymentProvider):
    name = "mock"
    DECLINE_SUFFIX = 13

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._charges: dict[str, PaymentResult] = {}
        self._refunds: dict[str, RefundResult] = {}

    @staticmethod
    def _ref(prefix: str, key: str) -> str:
        return f"{prefix}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]}"

    def charge(self, request: PaymentRequest) -> PaymentResult:
        with self._lock:
            cached = self._charges.get(request.idempotency_key)
            if cached is not None:
                return cached
            if request.amount_minor <= 0:
                result = PaymentResult(
                    status=PaymentStatus.FAILED,
                    provider=self.name,
                    provider_ref=self._ref("mockfail", request.idempotency_key),
                    amount_minor=request.amount_minor,
                    currency=request.currency,
                    failure_reason="amount must be positive",
                )
            elif request.amount_minor % 100 == self.DECLINE_SUFFIX:
                result = PaymentResult(
                    status=PaymentStatus.FAILED,
                    provider=self.name,
                    provider_ref=self._ref("mockfail", request.idempotency_key),
                    amount_minor=request.amount_minor,
                    currency=request.currency,
                    failure_reason="card declined by issuer (mock rule)",
                )
            else:
                result = PaymentResult(
                    status=PaymentStatus.CAPTURED,
                    provider=self.name,
                    provider_ref=self._ref("mockpay", request.idempotency_key),
                    amount_minor=request.amount_minor,
                    currency=request.currency,
                )
            self._charges[request.idempotency_key] = result
            return result

    def refund(self, provider_ref: str, amount_minor: int, idempotency_key: str) -> RefundResult:
        with self._lock:
            cached = self._refunds.get(idempotency_key)
            if cached is not None:
                return cached
            result = RefundResult(
                status=PaymentStatus.REFUNDED,
                provider=self.name,
                provider_ref=self._ref("mockref", idempotency_key),
                amount_minor=amount_minor,
            )
            self._refunds[idempotency_key] = result
            return result
