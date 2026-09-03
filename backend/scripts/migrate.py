#!/usr/bin/env python3
"""Apply pending migrations. Usage: python -m scripts.migrate"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.core.migrator import current_version, upgrade  # noqa: E402


def main() -> int:
    settings = load_settings()
    db = Database(settings.sqlite_path)
    applied = upgrade(db)
    if applied:
        print(f"applied migrations: {', '.join(applied)}")
    else:
        print("no pending migrations")
    print(f"schema version: {current_version(db)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
