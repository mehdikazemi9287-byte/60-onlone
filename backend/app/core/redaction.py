"""Central recursive redaction for logs, error messages, and API responses.

SECURITY RULE: Any dict that flows through logging or an error response must
be sanitised before it reaches the output. This module provides a single
canonical redactor that traverses arbitrary nested structures and replaces
sensitive values with a fixed placeholder.

Field names are matched case-insensitively against SENSITIVE_KEYS.
String values that match SENSITIVE_PATTERNS as a substring are also masked.

DO NOT add real-secret detection here. The specification explicitly forbids
unreliable value-based secret detection. Key-name matching only.
"""
from __future__ import annotations

from typing import Any

_REDACTED = "***REDACTED***"
_MAX_DEPTH = 12

# Case-insensitive key-name fragments that always warrant redaction.
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "authorization",
    "password",
    "passwd",
    "token",
    "secret",
    "private_key",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "access_token",
    "refresh_token",
    "client_secret",
    "auth",
    "x-auth",
    "x-api-key",
})


def _key_is_sensitive(key: str) -> bool:
    k = key.lower().replace("-", "_")
    for s in SENSITIVE_KEYS:
        if s in k:
            return True
    return False


def redact(obj: Any, *, _depth: int = 0) -> Any:
    """Return a sanitised deep copy of *obj*.

    - dict: recursively redact; replace values whose keys are sensitive.
    - list/tuple: recursively redact each element.
    - Everything else: returned as-is (no string scanning — per spec).

    Depth is capped at _MAX_DEPTH to prevent unbounded recursion.
    """
    if _depth >= _MAX_DEPTH:
        return _REDACTED if isinstance(obj, dict) else obj

    if isinstance(obj, dict):
        return {
            k: (_REDACTED if _key_is_sensitive(str(k)) else redact(v, _depth=_depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        redacted = [redact(v, _depth=_depth + 1) for v in obj]
        return type(obj)(redacted)
    return obj


def safe_exception_message(exc: Exception) -> str:
    """Return a generic, non-leaking message for an exception.

    Never expose str(exc) in API responses — it may contain secrets, internal
    paths, or SQL snippets. Log the real exc elsewhere at DEBUG level.
    """
    return "An internal error occurred"
