#!/usr/bin/env python3
"""Tiered price alerts: check every active watch at its owner's level, sellers' best-offer status, daily price
history, in-site notifications and batched digest SMS. Hourly; idempotent within the same hour."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import make_backend  # noqa: E402
from app.services import price_alert_service  # noqa: E402


def main() -> int:
    db = make_backend(load_settings().database_url)
    r = price_alert_service.run(db)
    w, s, m = r["watches"], r["sellers"], r["sms"]
    print(f"price_alerts watches={w['checked']} alerts={w['alerts'] + s['alerts']} products={s['products']} "
          f"errors={w['errors'] + s['errors']} deferred={w['deferred'] + s['deferred'] + m['deferred']} "
          f"sms_sent={m['sent']} sms_failed={m['failed']} sms_capped={m['skipped_cap']} sms_held={m['held']} "
          f"sms_unavailable={m['unavailable']} cleaned={sum(r['cleanup'].values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
