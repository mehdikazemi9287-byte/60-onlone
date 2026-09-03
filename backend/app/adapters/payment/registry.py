from __future__ import annotations

from app.adapters.payment.base import PaymentProvider
from app.adapters.payment.mock import MockPaymentProvider

_PROVIDERS: dict[str, PaymentProvider] = {}


def register(provider: PaymentProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get_payment_provider(name: str) -> PaymentProvider:
    if name not in _PROVIDERS:
        raise KeyError(
            f"Unknown payment provider {name!r}. Registered: {sorted(_PROVIDERS)}"
        )
    return _PROVIDERS[name]


def reset_for_tests() -> None:
    _PROVIDERS.clear()
    register(MockPaymentProvider())


register(MockPaymentProvider())
