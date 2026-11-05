#!/usr/bin/env python3
"""Free stock and credit held by customers who left the bank page without paying.

Checkout already does this opportunistically; run this every few minutes from cron as well so
holds are freed even when nobody is checking out:  `python -m scripts.release_abandoned_payments`.
Safe to run repeatedly; a payment completed by the bank meanwhile is left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.services import checkout_service  # noqa: E402


def main() -> int:
    settings = load_settings()
    db = Database(settings.sqlite_path)
    released = checkout_service.release_abandoned_redirects(db, limit=500)
    print(f"released {released} abandoned payment(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
