#!/usr/bin/env python3
"""آمادگی راه‌اندازی وامبی — Vambi launch readiness. Read-only: changes nothing, prints no secret value.

Usage (on the server, with the production environment loaded):
    python3 -m scripts.vambi_readiness          # table; exit 0 if every check is ready, else 1
    python3 -m scripts.vambi_readiness --json

The same checks are served to admins at GET /api/v1/admin/vambi/readiness (app/services/vambi_launch_service.py).
SQLite is opened read-only (mode=ro); a missing database file is an error, never created.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import vambi_launch_service as launch  # noqa: E402


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    from app.core.config import load_settings
    return load_settings().database_url


def run(database_url: str) -> dict:
    if database_url.startswith("sqlite:///"):
        path = database_url[len("sqlite:///"):]
        if not os.path.isfile(path):
            raise SystemExit(f"database file not found: {path}")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return launch.readiness(conn)
        finally:
            conn.close()
    from app.core.db import make_backend
    db = make_backend(database_url)
    with db.read_transaction() as conn:
        return launch.readiness(conn)


def table(result: dict) -> str:
    lines = [f"{'':2} {'check':28} {'detail':44} توضیح"]
    for c in result["checks"]:
        lines.append(f"{'OK' if c['ok'] else '--':2} {c['key']:28} {c['detail']:44} {c['label_fa']}")
    lines.append("READY — آماده" if result["ready"] else "NOT READY — آماده نیست")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    result = run(_database_url())
    print(json.dumps(result, ensure_ascii=False, indent=2) if "--json" in argv else table(result))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
