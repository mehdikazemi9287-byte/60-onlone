#!/usr/bin/env python3
"""Preview or import a 60Online catalogue CSV."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings
from app.core.db import Database
from app.services.catalog_bulk_import_service import import_catalog_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="60Online safe catalogue bulk importer")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--confirm", action="store_true", help="write valid rows")
    args = parser.parse_args()
    settings = load_settings()
    db = Database(settings.sqlite_path)
    text = args.csv_file.read_text(encoding="utf-8-sig")
    with (db.write_transaction() if args.confirm else db.read_transaction()) as conn:
        result = import_catalog_csv(conn, text, confirm=args.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
