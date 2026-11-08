#!/usr/bin/env python3
"""Create (or promote) the first platform admin.  python -m scripts.create_admin <email> "<full name>"
The password is asked interactively (never on the command line, so it stays out of shell history)."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import make_backend  # noqa: E402
from app.core.errors import ConflictError  # noqa: E402
from app.services import auth_service  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    email, name = argv
    db = make_backend(load_settings().database_url)
    pw = getpass.getpass("رمز (حداقل ۱۲ نویسه): ")
    if len(pw) < 12 or pw != getpass.getpass("تکرار رمز: "):
        print("رمز کوتاه است یا تکرار آن یکی نیست")
        return 1
    try:
        auth_service.register(db, email=email, password=pw, full_name=name, role="admin")
    except ConflictError:
        with db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='admin' WHERE email_normalized=?", (auth_service.normalize_email(email),))
        print("کاربر موجود بود؛ به مدیر ارتقا یافت (رمز قبلی او تغییر نکرد)")
        return 0
    print("مدیر ساخته شد")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
