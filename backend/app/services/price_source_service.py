"""
price_source_service.py
------------------------
Manages price sources and per-source price entries (price_source_entries).

Out-of-order update protection mirrors inventory_source_service: if the stored
version >= incoming version the update is silently skipped.

All prices are stored as integers in the minor unit of the currency
(e.g. IRR rials — no floats ever).

All DB access uses the caller-supplied ``conn`` (sqlite3.Connection).
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from app.core.errors import NotFoundError, ValidationError
from app.services.integration_event_service import fan_out_business_event

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _psrc_dict(row: sqlite3.Row) -> dict:
    """Convert a price_sources row to a plain dict."""
    config = row["config_json"]
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            config = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "source_type": row["source_type"],
        "supplier_id": row["supplier_id"],
        "priority": row["priority"],
        "connector_account_id": row["connector_account_id"],
        "is_active": bool(row["is_active"]),
        "config": config,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _entry_dict(row: sqlite3.Row) -> dict:
    """Convert a price_source_entries row to a plain dict."""
    return {
        "id": row["id"],
        "price_source_id": row["price_source_id"],
        "offer_id": row["offer_id"],
        "price_minor": row["price_minor"],
        "currency": row["currency"],
        "version": row["version"],
        "source_ref": row["source_ref"],
        "synced_at": row["synced_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Price source CRUD
# ---------------------------------------------------------------------------


def create_price_source(
    conn: sqlite3.Connection,
    *,
    name: str,
    source_type: str,
    supplier_id: int,
    priority: int = 0,
    connector_account_id: int | None = None,
    config: dict | None = None,
) -> dict:
    """Create a new price_sources record.

    Returns the created row as a dict.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    config_json = json.dumps(config or {}, ensure_ascii=False)

    cur = conn.execute(
        """
        INSERT INTO price_sources
            (name, source_type, supplier_id, priority, connector_account_id,
             is_active, config_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            name,
            source_type,
            supplier_id,
            priority,
            connector_account_id,
            config_json,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM price_sources WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _psrc_dict(row)


def list_price_sources(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    active_only: bool = True,
) -> list[dict]:
    """Return price_sources rows with optional filters.

    Results ordered by priority DESC, then id ASC.
    """
    query = "SELECT * FROM price_sources WHERE 1=1"
    params: list = []

    if supplier_id is not None:
        query += " AND supplier_id = ?"
        params.append(supplier_id)
    if active_only:
        query += " AND is_active = 1"

    query += " ORDER BY priority DESC, id ASC"
    rows = conn.execute(query, params).fetchall()
    return [_psrc_dict(r) for r in rows]


def get_price_source(conn: sqlite3.Connection, source_id: int) -> dict:
    """Return a single price_sources row.

    Raises NotFoundError if not found.
    """
    row = conn.execute(
        "SELECT * FROM price_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"منبع قیمت با id={source_id} یافت نشد.")
    return _psrc_dict(row)


# ---------------------------------------------------------------------------
# Price UPSERT with out-of-order protection
# ---------------------------------------------------------------------------


def update_price(
    conn: sqlite3.Connection,
    *,
    price_source_id: int,
    offer_id: int,
    price_minor: int,
    currency: str = "IRR",
    version: int,
    source_ref: str | None = None,
) -> dict:
    """UPSERT a price_source_entries row.

    price_minor must be a non-negative integer (no floats).

    If the stored version >= incoming version, the update is skipped
    (out-of-order / stale message protection) and the existing row is returned.

    Returns the final row dict (either updated or unchanged).

    Raises ValidationError if price_minor is negative or not an integer.
    """
    if not isinstance(price_minor, int) or isinstance(price_minor, bool):
        raise ValidationError(
            "price_minor باید یک عدد صحیح باشد (نه اعشاری)."
        )
    if price_minor < 0:
        raise ValidationError(
            f"price_minor نمی‌تواند منفی باشد (دریافتی: {price_minor})."
        )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    existing = conn.execute(
        """
        SELECT * FROM price_source_entries
        WHERE price_source_id = ? AND offer_id = ?
        """,
        (price_source_id, offer_id),
    ).fetchone()

    if existing is not None and existing["version"] >= version:
        # Stale or duplicate message — return existing row unchanged
        return _entry_dict(existing)

    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO price_source_entries
                (price_source_id, offer_id, price_minor, currency, version,
                 source_ref, synced_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                price_source_id,
                offer_id,
                price_minor,
                currency,
                version,
                source_ref,
                now,
                now,
                now,
            ),
        )
        row_id = cur.lastrowid
    else:
        conn.execute(
            """
            UPDATE price_source_entries
            SET price_minor  = ?,
                currency     = ?,
                version      = ?,
                source_ref   = ?,
                synced_at    = ?,
                updated_at   = ?
            WHERE price_source_id = ? AND offer_id = ?
            """,
            (
                price_minor,
                currency,
                version,
                source_ref,
                now,
                now,
                price_source_id,
                offer_id,
            ),
        )
        row_id = existing["id"]

    row = conn.execute(
        "SELECT * FROM price_source_entries WHERE id = ?", (row_id,)
    ).fetchone()
    entry = _entry_dict(row)

    # Outbox: fan-out PRICE_UPDATED to connectors belonging to the supplier
    # that owns this price source.
    ps_row = conn.execute(
        "SELECT supplier_id FROM price_sources WHERE id = ?",
        (price_source_id,),
    ).fetchone()
    _price_supplier_id = ps_row["supplier_id"] if ps_row else None

    fan_out_business_event(
        conn,
        event_type="PRICE_UPDATED",
        supplier_id=_price_supplier_id,
        payload={
            "price_source_id": price_source_id,
            "offer_id": offer_id,
            "price_minor": price_minor,
            "currency": currency,
            "version": version,
        },
        base_idempotency_key=f"price_updated:{price_source_id}:{offer_id}:{version}",
    )

    return entry


def get_authoritative_price(
    conn: sqlite3.Connection,
    offer_id: int,
) -> dict | None:
    """Return the price from the highest-priority active price source.

    Joins price_sources + price_source_entries + seller_offers to
    filter by the offer's supplier_id.

    Returns dict with keys:
        offer_id, price_minor, currency, price_source_id, source_name,
        priority, synced_at
    or None if no price entry exists.
    """
    row = conn.execute(
        """
        SELECT
            pse.offer_id,
            pse.price_minor,
            pse.currency,
            pse.price_source_id,
            ps.name     AS source_name,
            ps.priority,
            pse.synced_at
        FROM price_source_entries pse
        JOIN price_sources        ps  ON ps.id  = pse.price_source_id
        JOIN seller_offers        so  ON so.id  = pse.offer_id
        WHERE pse.offer_id   = ?
          AND ps.supplier_id  = so.supplier_id
          AND ps.is_active    = 1
        ORDER BY ps.priority DESC
        LIMIT 1
        """,
        (offer_id,),
    ).fetchone()

    if row is None:
        return None

    return {
        "offer_id": row["offer_id"],
        "price_minor": row["price_minor"],
        "currency": row["currency"],
        "price_source_id": row["price_source_id"],
        "source_name": row["source_name"],
        "priority": row["priority"],
        "synced_at": row["synced_at"],
    }


def list_prices_by_source(
    conn: sqlite3.Connection,
    price_source_id: int,
) -> list[dict]:
    """Return all price_source_entries rows for a given price source."""
    rows = conn.execute(
        """
        SELECT * FROM price_source_entries
        WHERE price_source_id = ?
        ORDER BY offer_id
        """,
        (price_source_id,),
    ).fetchall()
    return [_entry_dict(r) for r in rows]
