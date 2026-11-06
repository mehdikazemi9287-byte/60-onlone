#!/usr/bin/env python3
"""Deliver partner webhooks: bridge checkout events, then send what is due (retries with backoff).

cron (every minute):  * * * * *  cd /srv/backend && python3 -m scripts.run_partner_webhooks
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database, make_backend  # noqa: E402
from app.services import partner_webhook_service  # noqa: E402


def main() -> int:
    settings = load_settings()
    stats = partner_webhook_service.run_once(make_backend(settings.database_url), master_key=settings.secret_key)
    print(" ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
