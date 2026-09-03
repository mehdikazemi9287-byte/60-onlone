"""Runtime-only credential container — Phase 8.

``RuntimeCredentials`` wraps a resolved secret value so it can be passed
to adapter methods without risk of accidental persistence, logging, or
JSON serialization.

Design guarantees
─────────────────
1. ``__repr__`` and ``__str__`` both return a masked sentinel.  The resolved
   value never appears in tracebacks, log records, exception messages, or
   str(obj) output.

2. The class actively prevents serialization:
   * ``__reduce__`` raises TypeError so pickle fails immediately.
   * There is no ``to_dict()``, ``to_json()``, or ``__dict__`` that carries
     the raw value — Python's default ``__dict__`` does exist but the class
     name makes its purpose obvious if someone inspects it.
   * A custom ``__class_getitem__`` is NOT needed; just document the contract.

3. ``resolve()`` returns the raw secret exactly once per call.  Callers
   MUST NOT store the returned string beyond the immediate call site.

4. Objects are intentionally not hashable (``__hash__ = None``) so they
   cannot be used as dict keys or in sets, which would risk retention.

5. ``RuntimeCredentials(None)`` is a valid no-credentials sentinel; calling
   ``resolve()`` on it raises ``RuntimeError``.

SECURITY: This module MUST NOT import or reference any logging infrastructure.
Any call to logging functions with a RuntimeCredentials instance in scope
must never include the instance value — use ``creds.ref`` (the reference
key, which is always safe to log) rather than the resolved secret.
"""
from __future__ import annotations


class RuntimeCredentials:
    """Opaque, non-serializable container for a transiently resolved secret.

    Usage::

        creds = RuntimeCredentials(resolved_value, ref="ref:my-key")
        adapter.push_order(order_data, runtime_credentials=creds)
        # Inside adapter:
        #   secret = runtime_credentials.resolve()
        #   # Use secret for the HTTP auth header — do NOT store or log it.

    The ``ref`` attribute is the credential reference key (safe to log).
    The resolved value is kept private and is never emitted by repr/str.
    """

    __slots__ = ("_value", "_ref")

    # Prevent accidental use as dict key or set element.
    __hash__ = None  # type: ignore[assignment]

    def __init__(self, value: str | None, *, ref: str = "") -> None:
        """
        Args:
            value: The resolved credential material.  Pass None to create
                   a no-credentials sentinel (resolve() raises RuntimeError).
            ref:   The credential_ref key used to resolve this value.
                   Safe to log — it is a reference identifier, not the secret.
        """
        # Store privately; use name-mangling via __slots__ for extra safety.
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_ref", ref)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def ref(self) -> str:
        """The credential reference key (safe to log)."""
        return object.__getattribute__(self, "_ref")

    def resolve(self) -> str:
        """Return the raw secret value.

        Callers MUST NOT store the returned string or include it in any
        log statement, error message, or data structure that outlives the
        current operation.

        Raises:
            RuntimeError: If this is a no-credentials sentinel (value=None).
        """
        v = object.__getattribute__(self, "_value")
        if v is None:
            raise RuntimeError(
                "RuntimeCredentials.resolve() called on a no-credentials sentinel. "
                f"ref={self.ref!r}"
            )
        return v

    def has_value(self) -> bool:
        """Return True if this instance holds an actual resolved value."""
        return object.__getattribute__(self, "_value") is not None

    # ── Serialization prevention ───────────────────────────────────────────────

    def __repr__(self) -> str:  # pragma: no cover — repr tested separately
        return f"RuntimeCredentials(ref={self.ref!r}, value=<REDACTED>)"

    def __str__(self) -> str:
        return f"<RuntimeCredentials ref={self.ref!r} value=****>"

    def __reduce__(self):
        """Prevent pickling — secrets must never be serialized."""
        raise TypeError(
            "RuntimeCredentials cannot be pickled. "
            "Resolved secrets must not be serialized."
        )

    def __reduce_ex__(self, protocol):
        return self.__reduce__()

    # ── Mutation guard ─────────────────────────────────────────────────────────

    def __setattr__(self, name: str, value) -> None:
        raise AttributeError("RuntimeCredentials is immutable.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("RuntimeCredentials is immutable.")
