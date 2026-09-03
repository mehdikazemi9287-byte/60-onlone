#!/usr/bin/env python3
"""Process due 60Coin expiration for every user with an expirable balance.

No scheduler exists in this project (see entrypoint.sh — it only runs
migrations, then serves). Run this manually or wire it to a real cron/task
runner: `python -m scripts.expire_loyalty_coins`.

Idempotent per user per day (see loyalty_service.expire_due_coins).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.services import loyalty_service  # noqa: E402


def main() -> int:
    settings = load_settings()
    db = Database(settings.sqlite_path)

    with db.read_transaction() as conn:
        user_ids = [
            int(r["user_id"]) for r in conn.execute(
                "SELECT DISTINCT user_id FROM loyalty_ledger_entries "
                "WHERE entry_type = 'earn' AND expires_at IS NOT NULL"
            ).fetchall()
        ]

    total_expired = 0
    users_affected = 0
    for user_id in user_ids:
        result = loyalty_service.expire_due_coins(db, user_id=user_id)
        if result["created"]:
            users_affected += 1
            total_expired += result["expired_coins"]
            print(f"user_id={user_id} expired={result['expired_coins']} "
                  f"new_balance={result['balance_coins']}")

    print(f"done: {users_affected} users affected, {total_expired} coins expired total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
