"""SecretResolver — Blocker 2.

The ONLY approved runtime path for credential access is:
    resolved_secret = resolver.resolve(credential_ref)

Rules enforced here:
  1. Resolved values are NEVER logged, persisted, or returned in API responses.
  2. credential_ref is a reference identifier — it is safe to log/store.
  3. The FailClosedSecretResolver raises on every call — it is the default
     production stub until a real Vault/KMS integration is provided.
  4. InMemorySecretResolver holds secrets in a plain dict — suitable for
     tests only; never use in production.

Adding a real Vault/KMS resolver: implement SecretResolver, override resolve(),
and wire it into create_app() via app.extensions["secret_resolver"].
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SecretResolverError(RuntimeError):
    """Raised when a credential_ref cannot be resolved."""


class SecretResolver(ABC):
    """Abstract interface for credential resolution."""

    @abstractmethod
    def resolve(self, credential_ref: str) -> str:
        """Return the secret value for *credential_ref*.

        Args:
            credential_ref: An opaque reference identifier (safe to log).

        Returns:
            The resolved secret value (NEVER log, store, or return this).

        Raises:
            SecretResolverError: If the ref cannot be resolved.
        """


class InMemorySecretResolver(SecretResolver):
    """Test-only in-memory resolver.

    DO NOT use in production. Secrets live in process memory with no
    protection beyond Python's normal memory model.
    """

    def __init__(self, secrets: dict[str, str] | None = None):
        # Internal map from ref → secret value.
        # The dict itself is private; resolved values must not leak.
        self._secrets: dict[str, str] = dict(secrets or {})

    def register(self, credential_ref: str, secret_value: str) -> None:
        """Register a mapping. For test setup only."""
        self._secrets[credential_ref] = secret_value

    def resolve(self, credential_ref: str) -> str:
        if credential_ref not in self._secrets:
            raise SecretResolverError(
                f"credential_ref '{credential_ref}' not found in InMemorySecretResolver"
            )
        return self._secrets[credential_ref]


class FailClosedSecretResolver(SecretResolver):
    """Production stub — always raises until a real resolver is configured.

    Deployed as the default so that any code path that calls resolve()
    without a real backend configured fails loudly instead of silently
    skipping credential lookup.
    """

    def resolve(self, credential_ref: str) -> str:
        raise SecretResolverError(
            f"No SecretResolver configured. credential_ref='{credential_ref}' "
            "cannot be resolved. Configure a Vault/KMS resolver via "
            "app.extensions['secret_resolver'] before enabling real connectors."
        )
