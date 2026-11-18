"""Structured JSON logging — Phase 8 Observability.

Configures the root logger and the '60online' logger to emit structured
JSON lines so log aggregators (ELK, CloudWatch, Loki, etc.) can parse them.

Each log line is a single JSON object with these fields:
  timestamp   — ISO 8601 UTC
  level       — DEBUG / INFO / WARNING / ERROR / CRITICAL
  logger      — logger name
  message     — formatted log message
  request_id  — current request correlation ID (when inside a request context)
  exc_info    — exception class:message (when present)

Usage:
    from app.core.logging_config import configure_logging
    configure_logging(level="INFO", json_output=True)
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        # Try to get request_id from Flask's g — silently skip outside request context
        request_id: str | None = None
        try:
            from flask import g
            request_id = getattr(g, "request_id", None)
        except RuntimeError:
            pass

        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exc_info"] = (
                f"{exc_type.__name__}: {exc_value}"
                if exc_type and exc_value
                else traceback.format_exc()
            )
        return json.dumps(payload, ensure_ascii=False)


class _PlainFormatter(logging.Formatter):
    """Plain text formatter — used in development for readability."""

    _FMT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"

    def __init__(self):
        super().__init__(self._FMT, datefmt="%Y-%m-%dT%H:%M:%S")


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure application-wide structured logging.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        json_output: When True, emit JSON lines. When False, emit plain text.
            Typically True in staging/production, False in development.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter: logging.Formatter
    if json_output:
        formatter = _JsonFormatter()
    else:
        formatter = _PlainFormatter()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Configure the application logger
    app_logger = logging.getLogger("60online")
    app_logger.setLevel(numeric_level)
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.propagate = False

    # Suppress noisy third-party loggers in production
    for noisy in ("werkzeug",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
