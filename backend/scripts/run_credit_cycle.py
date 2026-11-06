#!/usr/bin/env python3
"""Phase 4 credit cycle: issue weekly statements, freeze/unfreeze overdue contracts,
flag late installments, expire org/pre-order cash shares left unpaid past
ORG_CASH_DUE_HOURS (releases stock, reverses captured credit). Idempotent; safe to run hourly.

cron (hourly):  0 * * * *  cd /srv/backend && python3 -m scripts.run_credit_cycle
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database, make_backend  # noqa: E402
from app.services import credit_contract_service, installment_service, org_order_service  # noqa: E402


def main() -> int:
    db = make_backend(load_settings().database_url)
    with db.write_transaction() as conn:
        statements = credit_contract_service.run_weekly_statements(conn)
        overdue = credit_contract_service.enforce_overdue(conn)
        late = installment_service.mark_late(conn)
        expired = org_order_service.expire_unpaid(conn)
    print(f"statements={statements} overdue={overdue} installments_late={late} expired={expired['expired']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
