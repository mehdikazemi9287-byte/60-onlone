from __future__ import annotations

from app.adapters.credit.base import CreditProvider
from app.adapters.credit.mock import MockCreditProvider

_PROVIDERS: dict[str, CreditProvider] = {}


def register(provider: CreditProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get_credit_provider(name: str) -> CreditProvider:
    if name not in _PROVIDERS:
        raise KeyError(f"Unknown credit provider {name!r}. Registered: {sorted(_PROVIDERS)}")
    return _PROVIDERS[name]


def reset_for_tests() -> None:
    _PROVIDERS.clear()
    register(MockCreditProvider())


register(MockCreditProvider())
