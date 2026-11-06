#!/usr/bin/env python3
"""Quote every recurring shopping list that is due today (idempotent per list and date). Daily."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import make_backend  # noqa: E402
from app.services import recurring_service  # noqa: E402


def main() -> int:
    db = make_backend(load_settings().database_url)
    with db.write_transaction() as conn:
        r = recurring_service.run_due(conn)
    print(f"recurring quoted={r['quoted']} failed={r['failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
