#!/usr/bin/env python3
"""Retention job (daily): delete personal data past its purpose.

- B2B applications rejected or never answered for 180 days (b2b_service.APPLICATION_RETENTION_DAYS)
- OTP challenges older than 30 days (only needed for rate limits and abuse review)

Run: `python -m scripts.purge_personal_data`. Idempotent.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database, make_backend  # noqa: E402
from app.services import b2b_service  # noqa: E402

OTP_RETENTION_DAYS = 30


def main() -> int:
    db = make_backend(load_settings().database_url)
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=OTP_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db.write_transaction() as conn:
        apps = b2b_service.purge_stale_applications(conn)
        otps = conn.execute("DELETE FROM otp_challenges WHERE created_at < ?", (cutoff,)).rowcount
    print(f"purged b2b_applications={apps} otp_challenges={otps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
