from __future__ import annotations

import abc

GROUP_BUSINESSES = ("60online", "karenseir", "giftasan", "shadshahr", "padvira")


class GroupPlatform(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def get_account(self, conn, user_id: int) -> dict | None:
        """The user's group-wide account, or None when not enrolled."""

    @abc.abstractmethod
    def enroll(self, conn, user_id: int, businesses: list[str] | None = None) -> dict:
        """Create (idempotently) the group account and link businesses."""

    @abc.abstractmethod
    def summary(self, conn, user_id: int) -> dict:
        """Wallet / coins / credit summary for /api/v1/me/group."""
