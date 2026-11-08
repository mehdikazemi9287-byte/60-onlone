"""Local implementation: reads this database's credit, welfare, installments and 60 coins."""
from __future__ import annotations

import json
import secrets

from app.adapters.group_platform.base import GROUP_BUSINESSES, GroupPlatform
from app.core.errors import ValidationError
from app.services import credit_service, installment_service, loyalty_service, welfare_wallet_service


class LocalGroupPlatform(GroupPlatform):
    name = "local"

    def get_account(self, conn, user_id: int) -> dict | None:
        row = conn.execute("SELECT * FROM group_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["linked_businesses"] = json.loads(data.pop("linked_businesses_json") or "[]")
        return data

    def enroll(self, conn, user_id: int, businesses: list[str] | None = None) -> dict:
        wanted = list(dict.fromkeys(["60online", *(businesses or [])]))
        bad = [b for b in wanted if b not in GROUP_BUSINESSES]
        if bad:
            raise ValidationError("کسب‌وکار گروه نامعتبر است", details={"businesses": list(GROUP_BUSINESSES)})
        current = self.get_account(conn, user_id)
        if current is None:
            conn.execute("INSERT INTO group_accounts (user_id, group_uid, linked_businesses_json, provider) "
                         "VALUES (?,?,?, 'local')",
                         (user_id, f"G-{secrets.token_hex(8).upper()}", json.dumps(wanted)))
        else:
            merged = list(dict.fromkeys([*current["linked_businesses"], *wanted]))
            conn.execute("UPDATE group_accounts SET linked_businesses_json = ?, updated_at = datetime('now') "
                         "WHERE user_id = ?", (json.dumps(merged), user_id))
        return self.get_account(conn, user_id)

    def summary(self, conn, user_id: int) -> dict:
        allocations = conn.execute("SELECT id FROM credit_allocations WHERE user_id = ? AND status = 'active'",
                                   (user_id,)).fetchall()
        credit_available = sum(credit_service.allocation_state(conn, int(a["id"]))["available_minor"]
                               for a in allocations)
        return {
            "provider": self.name,
            "group_account": self.get_account(conn, user_id),
            "businesses": list(GROUP_BUSINESSES),
            # No stored-value cash wallet exists yet; a shared platform would supply it.
            "wallet": {"balance_minor": None, "available": False},
            "coins": {"balance_coins": loyalty_service.balance(conn, user_id)},
            "credit": {"available_minor": credit_available},
            "welfare": welfare_wallet_service.member_summary(conn, user_id),
            "installments": installment_service.user_summary(conn, user_id),
            "currency": "IRR",
        }
