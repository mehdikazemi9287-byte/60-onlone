"""Phase 8 — Blocker 8: Observability / MetricsCollector tests.

Tests:
  - InMemoryMetricsCollector increments counters
  - InMemoryMetricsCollector records histograms
  - InMemoryMetricsCollector sets gauges
  - Thread-safety of increment
  - text_export() produces Prometheus-like output
  - HTTP request metrics are incremented per request
  - Metrics endpoint is admin-only (403 for non-admin, 200 for admin)
  - Metrics output does not contain secret/sensitive data
  - NoOpMetricsCollector accepts all calls silently
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.metrics import InMemoryMetricsCollector, NoOpMetricsCollector, MetricsCollector
from tests.base import AppTestCase


class TestInMemoryMetricsCollector(unittest.TestCase):

    def setUp(self):
        self.m = InMemoryMetricsCollector()

    def test_increment_counter(self):
        self.m.increment("requests_total")
        self.assertEqual(self.m.get_counter("requests_total"), 1)

    def test_increment_with_value(self):
        self.m.increment("bytes_sent", value=1024)
        self.assertEqual(self.m.get_counter("bytes_sent"), 1024)

    def test_increment_accumulates(self):
        for _ in range(5):
            self.m.increment("hits")
        self.assertEqual(self.m.get_counter("hits"), 5)

    def test_increment_with_labels(self):
        self.m.increment("http_requests_total", labels={"method": "GET", "status": "200"})
        self.m.increment("http_requests_total", labels={"method": "POST", "status": "201"})
        self.assertEqual(self.m.get_counter("http_requests_total", labels={"method": "GET", "status": "200"}), 1)
        self.assertEqual(self.m.get_counter("http_requests_total", labels={"method": "POST", "status": "201"}), 1)

    def test_record_histogram(self):
        self.m.record("latency_ms", 42.5)
        self.m.record("latency_ms", 100.0)
        snap = self.m.snapshot()
        self.assertIn(42.5, snap["histograms"].get("latency_ms", []))
        self.assertIn(100.0, snap["histograms"]["latency_ms"])

    def test_gauge(self):
        self.m.gauge("queue_depth", 17)
        self.assertEqual(self.m.get_gauge("queue_depth"), 17)

    def test_gauge_overwrites(self):
        self.m.gauge("depth", 5)
        self.m.gauge("depth", 10)
        self.assertEqual(self.m.get_gauge("depth"), 10)

    def test_unknown_counter_returns_zero(self):
        self.assertEqual(self.m.get_counter("nonexistent"), 0)

    def test_unknown_gauge_returns_none(self):
        self.assertIsNone(self.m.get_gauge("nonexistent"))

    def test_thread_safety(self):
        """Concurrent increments must not lose updates."""
        def worker():
            for _ in range(100):
                self.m.increment("concurrent_counter")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.m.get_counter("concurrent_counter"), 1000)

    def test_text_export_contains_counters(self):
        self.m.increment("checkout_success_total", 3)
        text = self.m.text_export()
        self.assertIn("checkout_success_total", text)
        self.assertIn("3", text)

    def test_text_export_newline_terminated(self):
        self.m.increment("x")
        text = self.m.text_export()
        self.assertTrue(text.endswith("\n"))

    def test_reset_clears_all(self):
        self.m.increment("x", 5)
        self.m.gauge("y", 3)
        self.m.reset()
        self.assertEqual(self.m.get_counter("x"), 0)
        self.assertIsNone(self.m.get_gauge("y"))

    def test_is_abstract_interface(self):
        self.assertIsInstance(self.m, MetricsCollector)


class TestNoOpMetricsCollector(unittest.TestCase):

    def test_accepts_all_calls(self):
        m = NoOpMetricsCollector()
        m.increment("x")
        m.record("y", 1.0)
        m.gauge("z", 5)
        # No exception

    def test_text_export_empty(self):
        m = NoOpMetricsCollector()
        self.assertEqual(m.text_export(), "")


class TestHTTPMetricsInstrumentation(AppTestCase):
    """HTTP request metrics must be incremented by the middleware."""

    def _get_metrics(self):
        return self.app.extensions.get("metrics")

    def test_metrics_collector_is_registered(self):
        m = self._get_metrics()
        self.assertIsNotNone(m)
        self.assertIsInstance(m, InMemoryMetricsCollector)

    def test_successful_request_increments_counter(self):
        m = self._get_metrics()
        m.reset()
        self.client.get("/api/v1/health/live")
        snap = m.snapshot()
        total = sum(
            v for k, v in snap["counters"].items()
            if "http_requests_total" in k
        )
        self.assertGreaterEqual(total, 1)

    def test_duration_is_recorded(self):
        m = self._get_metrics()
        m.reset()
        self.client.get("/api/v1/health/live")
        snap = m.snapshot()
        has_duration = any("http_request_duration" in k for k in snap["histograms"])
        self.assertTrue(has_duration)

    def test_metrics_endpoint_requires_admin(self):
        # Without auth → 401
        resp = self.client.get("/api/v1/metrics")
        self.assertEqual(resp.status_code, 401)

    def test_metrics_endpoint_admin_only(self):
        # Customer cannot access metrics
        email, pw, _ = self.register("metrics_customer@example.com")
        token = self.login(email, pw)
        resp = self.client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_metrics_endpoint_accessible_by_admin(self):
        email, pw, _ = self.register("metrics_admin@example.com")
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='admin' WHERE email_normalized=?", (email,))
        token = self.login(email, pw)
        resp = self.client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.content_type)

    def test_metrics_output_does_not_contain_secrets(self):
        """The text_export output must not contain any sensitive values."""
        m = self._get_metrics()
        m.increment("test_counter", labels={"endpoint": "/api/v1/auth/login"})
        text = m.text_export()
        # No secret fragments should appear in metric output
        forbidden = ["password", "secret", "Bearer ", "token="]
        for f in forbidden:
            self.assertNotIn(f, text.lower() if f.islower() else text)


if __name__ == "__main__":
    unittest.main()
