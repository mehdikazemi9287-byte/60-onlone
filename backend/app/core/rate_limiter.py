"""Rate limiting — Blocker 1.

Provides a RateLimiter interface with two implementations:
  - InMemoryRateLimiter: sliding-window counter using a dict of deques.
    Deterministic and suitable for single-process development/test.
  - FailClosedRateLimiter: wraps a real implementation; if the real limiter
    throws an unexpected exception, the request is DENIED (fail-closed).

The production path requires a shared counter store (e.g. Redis) for
horizontal scaling. Until that dependency is provided, the fail-closed
stub rejects all requests when configured to do so.

Usage in Flask middleware:
    limiter = current_app.extensions.get("rate_limiter")
    if limiter is not None:
        key = f"ip:{client_ip()}"
        if not limiter.is_allowed(key):
            abort(429)
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Callable


class RateLimiter(ABC):
    """Abstract rate-limiter interface."""

    @abstractmethod
    def is_allowed(self, key: str) -> bool:
        """Return True if the request identified by *key* is within limit."""

    @abstractmethod
    def retry_after(self, key: str) -> int:
        """Return seconds until the oldest request in window expires."""


class InMemoryRateLimiter(RateLimiter):
    """Sliding-window rate limiter backed by an in-process dict.

    Thread-safe for single-process deployments. Not suitable for multi-process
    or multi-instance production deployments — use a Redis-backed limiter there.

    Args:
        requests_per_window: Maximum requests allowed in the window.
        window_seconds: Length of the sliding window in seconds.
        clock: Callable returning current time as float (seconds). Defaults to
               time.monotonic. Inject a deterministic clock in tests.
    """

    def __init__(
        self,
        requests_per_window: int,
        window_seconds: int = 60,
        clock: Callable[[], float] | None = None,
    ):
        if requests_per_window < 1:
            raise ValueError("requests_per_window must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._limit = requests_per_window
        self._window = window_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        # key -> deque of request timestamps (oldest at left)
        self._windows: dict[str, deque] = {}

    def _evict_old(self, dq: deque, now: float) -> None:
        cutoff = now - self._window
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def is_allowed(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            dq = self._windows.setdefault(key, deque())
            self._evict_old(dq, now)
            if len(dq) >= self._limit:
                return False
            dq.append(now)
            return True

    def retry_after(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            dq = self._windows.get(key)
            if not dq:
                return 0
            self._evict_old(dq, now)
            if not dq:
                return 0
            oldest = dq[0]
            remaining = (oldest + self._window) - now
            return max(0, int(remaining) + 1)

    def reset(self, key: str) -> None:
        """Remove all recorded requests for *key*. Useful in tests."""
        with self._lock:
            self._windows.pop(key, None)


class FailClosedRateLimiter(RateLimiter):
    """Wraps a delegate limiter; denies on exception (fail-closed).

    If the underlying limiter raises, is_allowed returns False so the
    request is rejected rather than silently allowed through.
    """

    def __init__(self, delegate: RateLimiter):
        self._delegate = delegate

    def is_allowed(self, key: str) -> bool:
        try:
            return self._delegate.is_allowed(key)
        except Exception:
            # Fail closed: unknown limiter state → deny the request.
            return False

    def retry_after(self, key: str) -> int:
        try:
            return self._delegate.retry_after(key)
        except Exception:
            return 60  # Default backoff when limiter is unavailable.


class NoOpRateLimiter(RateLimiter):
    """Always allows. Used when rate limiting is disabled (e.g. APP_ENV=test)."""

    def is_allowed(self, key: str) -> bool:  # noqa: ARG002
        return True

    def retry_after(self, key: str) -> int:  # noqa: ARG002
        return 0
