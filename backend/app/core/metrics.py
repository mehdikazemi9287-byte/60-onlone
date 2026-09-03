"""MetricsCollector — Blocker 8.

A vendor-neutral observability abstraction. All instrumentation calls go
through MetricsCollector so the backend can be swapped (Prometheus,
StatsD, OpenTelemetry, etc.) without touching business code.

InMemoryMetricsCollector:
  - Suitable for tests and single-process development.
  - Thread-safe; counters and histograms stored as dicts.
  - Exposes a snapshot() method for assertions.

The text_export() method produces a Prometheus-compatible text format
so metrics can be scraped by any compatible system without a dependency
on the prometheus_client library.

Sensitive operational metrics (e.g. revenue figures) should NOT be exposed
on the public-facing metrics endpoint — only the admin-scoped endpoint
should expose them. The endpoint itself must be protected (see health.py).

Standard metric names used across the codebase:
  http_requests_total{method, endpoint, status}
  http_request_duration_ms{method, endpoint}
  checkout_success_total
  checkout_failure_total{reason}
  payment_failure_total{reason}
  fulfillment_failure_total{reason}
  inventory_reservation_conflict_total
  outbox_queue_depth
  outbox_retry_total
  outbox_dead_letter_total
  connector_health{connector_type, status}
  import_processed_total{source}
  import_failure_total{source}
  reconciliation_mismatch_total
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import defaultdict


class MetricsCollector(ABC):
    """Abstract metrics interface."""

    @abstractmethod
    def increment(self, name: str, value: int = 1, labels: dict | None = None) -> None:
        """Increment a counter."""

    @abstractmethod
    def record(self, name: str, value: float, labels: dict | None = None) -> None:
        """Record a value (histogram/gauge observation)."""

    @abstractmethod
    def gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        """Set a gauge to an absolute value."""

    @abstractmethod
    def text_export(self) -> str:
        """Return all metrics in Prometheus text format."""


def _label_str(labels: dict | None) -> str:
    if not labels:
        return ""
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + parts + "}"


def _metric_key(name: str, labels: dict | None) -> str:
    return name + _label_str(labels)


class InMemoryMetricsCollector(MetricsCollector):
    """Thread-safe in-memory implementation for tests and development.

    Exposes snapshot() for test assertions.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # counter_name+labels -> int
        self._counters: dict[str, int] = defaultdict(int)
        # gauge_name+labels -> float
        self._gauges: dict[str, float] = {}
        # histogram_name+labels -> list[float]
        self._histograms: dict[str, list] = defaultdict(list)

    def increment(self, name: str, value: int = 1, labels: dict | None = None) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def record(self, name: str, value: float, labels: dict | None = None) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self._histograms[key].append(value)

    def gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        key = _metric_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def snapshot(self) -> dict:
        """Return a copy of all current metric values for assertions."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: list(v) for k, v in self._histograms.items()},
            }

    def get_counter(self, name: str, labels: dict | None = None) -> int:
        key = _metric_key(name, labels)
        with self._lock:
            return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict | None = None) -> float | None:
        key = _metric_key(name, labels)
        with self._lock:
            return self._gauges.get(key)

    def text_export(self) -> str:
        with self._lock:
            lines = []
            for key, val in sorted(self._counters.items()):
                lines.append(f"{key} {val}")
            for key, val in sorted(self._gauges.items()):
                lines.append(f"{key} {val}")
            for key, values in sorted(self._histograms.items()):
                if values:
                    lines.append(f"{key}_count {len(values)}")
                    lines.append(f"{key}_sum {sum(values)}")
            return "\n".join(lines) + "\n" if lines else ""

    def reset(self) -> None:
        """Clear all metrics. Useful between test cases."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


class NoOpMetricsCollector(MetricsCollector):
    """Discards all metrics. Used when no metrics backend is configured."""

    def increment(self, name: str, value: int = 1, labels: dict | None = None) -> None:
        pass

    def record(self, name: str, value: float, labels: dict | None = None) -> None:
        pass

    def gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        pass

    def text_export(self) -> str:
        return ""
