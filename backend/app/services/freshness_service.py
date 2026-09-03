"""Offer freshness / staleness service.

Price and inventory data can become stale for volatile products (mobile phones,
electronics). This service checks freshness and enforces policies.

Freshness policies (from freshness_policies table):
- ALWAYS_FRESH: never stale (manual/static offers)
- DAILY: 86400s TTL
- HOURLY: 3600s TTL
- REALTIME: 900s TTL

Stale/expired actions: allow | warn | block_checkout | block_all

Integration with checkout:
- Checkout service calls check_offer_freshness() before placing order.
- If expired and action == 'block_checkout', raises FreshnessError.
- Existing demo offers have no freshness_policy_id → default policy (ALWAYS_FRESH) applies.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.core.errors import ApiError


class FreshnessStatus(Enum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    UNKNOWN = "unknown"   # policy is ALWAYS_FRESH or no timestamps yet


class FreshnessError(ApiError):
    status_code = 409
    code = "offer_freshness_expired"

    def __init__(self, message: str, offer_id: int | None = None):
        super().__init__(message, code="offer_freshness_expired")
        self.offer_id = offer_id


@dataclass
class FreshnessResult:
    offer_id: int
    status: FreshnessStatus
    price_age_seconds: int | None
    inventory_age_seconds: int | None
    policy_name: str
    stale_action: str
    expired_action: str
    message: str


def _age_seconds(confirmed_at: str | None) -> int | None:
    if not confirmed_at:
        return None
    try:
        ts = datetime.datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        return int((now - ts).total_seconds())
    except Exception:
        return None


def check_offer_freshness(conn, offer_id: int) -> FreshnessResult:
    """
    Check the freshness of a single seller offer.
    Returns a FreshnessResult. Does NOT raise — caller decides what to do.
    """
    row = conn.execute(
        """
        SELECT so.id, so.freshness_policy_id,
               so.last_price_confirmed_at, so.last_inventory_confirmed_at,
               fp.name AS policy_name,
               fp.price_ttl_seconds, fp.inventory_ttl_seconds,
               fp.stale_action, fp.expired_action
        FROM seller_offers so
        LEFT JOIN freshness_policies fp ON fp.id = so.freshness_policy_id
        WHERE so.id = ?
        """,
        (offer_id,),
    ).fetchone()

    if not row:
        return FreshnessResult(
            offer_id=offer_id,
            status=FreshnessStatus.UNKNOWN,
            price_age_seconds=None,
            inventory_age_seconds=None,
            policy_name="NONE",
            stale_action="allow",
            expired_action="allow",
            message="پیشنهاد یافت نشد",
        )

    # If no policy assigned, fall back to default (ALWAYS_FRESH)
    if row["freshness_policy_id"] is None or row["price_ttl_seconds"] is None:
        return FreshnessResult(
            offer_id=offer_id,
            status=FreshnessStatus.UNKNOWN,
            price_age_seconds=None,
            inventory_age_seconds=None,
            policy_name=row["policy_name"] or "ALWAYS_FRESH",
            stale_action=row["stale_action"] or "allow",
            expired_action=row["expired_action"] or "allow",
            message="همیشه‌تازه — بدون TTL",
        )

    price_age = _age_seconds(row["last_price_confirmed_at"])
    inv_age = _age_seconds(row["last_inventory_confirmed_at"])
    price_ttl = row["price_ttl_seconds"]
    inv_ttl = row["inventory_ttl_seconds"]
    stale_action = row["stale_action"]
    expired_action = row["expired_action"]

    # Determine status
    # Use 2×TTL as "expired" threshold; within TTL = fresh; between = stale
    status = FreshnessStatus.FRESH
    if price_age is None and inv_age is None:
        # Never been confirmed — treat as stale if TTL exists
        status = FreshnessStatus.STALE
    else:
        worst_age = max(
            (price_age if price_age is not None else 0),
            (inv_age if inv_age is not None else 0),
        )
        if worst_age > price_ttl * 2:
            status = FreshnessStatus.EXPIRED
        elif worst_age > price_ttl:
            status = FreshnessStatus.STALE

    msg_map = {
        FreshnessStatus.FRESH: "اطلاعات به‌روز است",
        FreshnessStatus.STALE: "اطلاعات قدیمی شده — به‌روزرسانی توصیه می‌شود",
        FreshnessStatus.EXPIRED: "اطلاعات منقضی شده — خرید مسدود است",
    }
    return FreshnessResult(
        offer_id=offer_id,
        status=status,
        price_age_seconds=price_age,
        inventory_age_seconds=inv_age,
        policy_name=row["policy_name"],
        stale_action=stale_action,
        expired_action=expired_action,
        message=msg_map.get(status, ""),
    )


def enforce_freshness_for_checkout(conn, offer_id: int) -> None:
    """
    Check freshness and raise FreshnessError if expired AND expired_action == block_checkout/block_all.
    Called by checkout service before reserving supplier stock.
    """
    result = check_offer_freshness(conn, offer_id)
    if result.status == FreshnessStatus.EXPIRED:
        if result.expired_action in ("block_checkout", "block_all"):
            raise FreshnessError(
                f"قیمت/موجودی پیشنهاد {offer_id} منقضی شده است. "
                f"لطفاً ابتدا اطلاعات را به‌روز کنید.",
                offer_id=offer_id,
            )
