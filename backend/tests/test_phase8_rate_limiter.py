"""Phase 8 — Blocker 1: Rate Limiting tests.

Tests:
  - InMemoryRateLimiter allows up to limit requests per window
  - InMemoryRateLimiter blocks requests over the limit
  - retry_after returns correct wait time
  - Sliding window: old requests expire and new ones are allowed
  - FailClosedRateLimiter denies when delegate throws
  - NoOpRateLimiter always allows
  - Deterministic clock injection for tests (no sleep)
  - Flask middleware returns 429 with Retry-After header when limit exceeded
  - Multiple keys are tracked independently
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.rate_limiter import (
    FailClosedRateLimiter,
    InMemoryRateLimiter,
    NoOpRateLimiter,
    RateLimiter,
)
from tests.base import AppTestCase


# ─── Unit tests ───────────────────────────────────────────────────────────────

class TestInMemoryRateLimiter(unittest.TestCase):

    def _make_clock(self, start: float = 0.0):
        """Return a mutable clock and an advance function."""
        state = [start]

        def clock():
            return state[0]

        def advance(seconds: float):
            state[0] += seconds

        return clock, advance

    def test_allows_within_limit(self):
        clock, _ = self._make_clock()
        limiter = InMemoryRateLimiter(3, window_seconds=60, clock=clock)
        for _ in range(3):
            self.assertTrue(limiter.is_allowed("key"))

    def test_blocks_over_limit(self):
        clock, _ = self._make_clock()
        limiter = InMemoryRateLimiter(3, window_seconds=60, clock=clock)
        for _ in range(3):
            limiter.is_allowed("key")
        self.assertFalse(limiter.is_allowed("key"))

    def test_sliding_window_expires_old_requests(self):
        clock, advance = self._make_clock()
        limiter = InMemoryRateLimiter(3, window_seconds=60, clock=clock)
        # Fill the window
        for _ in range(3):
            limiter.is_allowed("key")
        # Blocked now
        self.assertFalse(limiter.is_allowed("key"))
        # Advance past window
        advance(61)
        # All 3 requests have expired; new requests are allowed
        self.assertTrue(limiter.is_allowed("key"))

    def test_independent_keys(self):
        clock, _ = self._make_clock()
        limiter = InMemoryRateLimiter(1, window_seconds=60, clock=clock)
        self.assertTrue(limiter.is_allowed("key_a"))
        self.assertFalse(limiter.is_allowed("key_a"))  # blocked
        self.assertTrue(limiter.is_allowed("key_b"))   # independent key

    def test_retry_after_returns_wait_time(self):
        clock, advance = self._make_clock(start=100.0)
        limiter = InMemoryRateLimiter(1, window_seconds=60, clock=clock)
        limiter.is_allowed("key")   # uses up the slot at t=100
        self.assertFalse(limiter.is_allowed("key"))
        wait = limiter.retry_after("key")
        # Oldest request at t=100, window=60, so expires at t=160, current=100 → ~60s
        self.assertGreater(wait, 0)
        self.assertLessEqual(wait, 61)

    def test_retry_after_zero_when_allowed(self):
        clock, _ = self._make_clock()
        limiter = InMemoryRateLimiter(10, window_seconds=60, clock=clock)
        wait = limiter.retry_after("key")
        self.assertEqual(wait, 0)

    def test_reset_clears_state(self):
        clock, _ = self._make_clock()
        limiter = InMemoryRateLimiter(1, window_seconds=60, clock=clock)
        limiter.is_allowed("key")
        self.assertFalse(limiter.is_allowed("key"))
        limiter.reset("key")
        self.assertTrue(limiter.is_allowed("key"))

    def test_invalid_limit_raises(self):
        with self.assertRaises(ValueError):
            InMemoryRateLimiter(0)

    def test_invalid_window_raises(self):
        with self.assertRaises(ValueError):
            InMemoryRateLimiter(10, window_seconds=0)

    def test_is_abstract_interface(self):
        self.assertTrue(issubclass(InMemoryRateLimiter, RateLimiter))


class TestFailClosedRateLimiter(unittest.TestCase):

    def test_delegates_to_inner_limiter(self):
        inner = InMemoryRateLimiter(5)
        wrapped = FailClosedRateLimiter(inner)
        self.assertTrue(wrapped.is_allowed("key"))

    def test_denies_when_inner_raises(self):
        class BrokenLimiter(RateLimiter):
            def is_allowed(self, key):
                raise RuntimeError("redis is down")
            def retry_after(self, key):
                raise RuntimeError("redis is down")

        wrapped = FailClosedRateLimiter(BrokenLimiter())
        self.assertFalse(wrapped.is_allowed("key"))

    def test_retry_after_returns_default_when_inner_raises(self):
        class BrokenLimiter(RateLimiter):
            def is_allowed(self, key):
                raise RuntimeError("redis is down")
            def retry_after(self, key):
                raise RuntimeError("redis is down")

        wrapped = FailClosedRateLimiter(BrokenLimiter())
        self.assertEqual(wrapped.retry_after("key"), 60)


class TestNoOpRateLimiter(unittest.TestCase):

    def test_always_allows(self):
        limiter = NoOpRateLimiter()
        for _ in range(1000):
            self.assertTrue(limiter.is_allowed("key"))

    def test_retry_after_zero(self):
        limiter = NoOpRateLimiter()
        self.assertEqual(limiter.retry_after("key"), 0)


# ─── Flask integration test ───────────────────────────────────────────────────

class TestRateLimitingMiddleware(AppTestCase):
    """Test that the Flask middleware correctly enforces rate limits."""

    def _make_app_with_limit(self, limit: int):
        """Create a test app with a 1-request-per-minute rate limit."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        from app.core.config import Settings
        from app.core.db import Database
        from app.main import create_app
        import tempfile, os

        tmpdir = tempfile.mkdtemp()
        settings = Settings(
            secret_key="test-secret-key-for-rate-limit-testing-xxxxx",
            database_url=f"sqlite:///{tmpdir}/rl.db",
            app_env="test",
            jwt_algorithm="HS256",
            access_token_ttl_seconds=3600,
            currency="IRR",
            currency_exponent=0,
            payment_provider="mock",
            credit_provider="mock",
            cors_origins=("http://localhost:3000",),
            rate_limit_per_minute=limit,
        )
        app = create_app(settings=settings)
        # Migrate
        with app.app_context():
            from app.core.migrator import upgrade
            from app.core.db import _get_db
            upgrade(_get_db())
        return app.test_client()

    def test_requests_within_limit_are_allowed(self):
        client = self._make_app_with_limit(10)
        resp = client.get("/api/v1/health/live")
        self.assertEqual(resp.status_code, 200)

    def test_requests_over_limit_get_429(self):
        client = self._make_app_with_limit(2)
        # First two are allowed
        client.get("/api/v1/health/live")
        client.get("/api/v1/health/live")
        # Third exceeds the limit
        resp = client.get("/api/v1/health/live")
        self.assertEqual(resp.status_code, 429)
        body = resp.get_json()
        self.assertEqual(body["error"]["code"], "rate_limit_exceeded")

    def test_429_includes_retry_after_header(self):
        client = self._make_app_with_limit(1)
        client.get("/api/v1/health/live")
        resp = client.get("/api/v1/health/live")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)
        retry_after = int(resp.headers["Retry-After"])
        self.assertGreater(retry_after, 0)

    def test_zero_limit_means_no_rate_limiting(self):
        client = self._make_app_with_limit(0)
        for _ in range(100):
            resp = client.get("/api/v1/health/live")
            self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
