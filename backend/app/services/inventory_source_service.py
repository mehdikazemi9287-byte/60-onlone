"""
inventory_source_service.py
----------------------------
Manages inventory sources (manual, connector, CSV import, ERP sync) and the
per-source stock records stored in inventory_source_stock.

Out-of-order update protection: if the stored version >= incoming version,
the update is silently skipped and the existing row is returned.

All quantities are plain Python integers (no floats).
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


def _src_dict(row: sqlite3.Row) -> dict:
    """Convert an inventory_sources row to a plain dict."""
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


def _stock_dict(row: sqlite3.Row) -> dict:
    """Convert an inventory_source_stock row to a plain dict."""
    return {
        "id": row["id"],
        "inventory_source_id": row["inventory_source_id"],
        "offer_id": row["offer_id"],
        "quantity": row["quantity"],
        "version": row["version"],
        "source_ref": row["source_ref"],
        "synced_at": row["synced_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Inventory source CRUD
# ---------------------------------------------------------------------------


def create_inventory_source(
    conn: sqlite3.Connection,
    *,
    name: str,
    source_type: str,
    supplier_id: int,
    priority: int = 0,
    connector_account_id: int | None = None,
    config: dict | None = None,
) -> dict:
    """Create a new inventory_sources record.

    Returns the created row as a dict.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    config_json = json.dumps(config or {}, ensure_ascii=False)

    cur = conn.execute(
        """
        INSERT INTO inventory_sources
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
        "SELECT * FROM inventory_sources WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _src_dict(row)


def list_inventory_sources(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    active_only: bool = True,
) -> list[dict]:
    """Return inventory_sources rows with optional filters.

    Results ordered by priority DESC, then id ASC.
    """
    query = "SELECT * FROM inventory_sources WHERE 1=1"
    params: list = []

    if supplier_id is not None:
        query += " AND supplier_id = ?"
        params.append(supplier_id)
    if active_only:
        query += " AND is_active = 1"

    query += " ORDER BY priority DESC, id ASC"
    rows = conn.execute(query, params).fetchall()
    return [_src_dict(r) for r in rows]


def get_inventory_source(conn: sqlite3.Connection, source_id: int) -> dict:
    """Return a single inventory_sources row.

    Raises NotFoundError if not found.
    """
    row = conn.execute(
        "SELECT * FROM inventory_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"منبع موجودی با id={source_id} یافت نشد.")
    return _src_dict(row)


# ---------------------------------------------------------------------------
# Stock UPSERT with out-of-order protection
# ---------------------------------------------------------------------------


def update_stock(
    conn: sqlite3.Connection,
    *,
    inventory_source_id: int,
    offer_id: int,
    quantity: int,
    version: int,
    source_ref: str | None = None,
) -> dict:
    """UPSERT an inventory_source_stock row.

    If the stored version >= incoming version, the update is skipped
    (out-of-order / stale message protection) and the existing row is returned.

    Returns the final row dict (either updated or unchanged).
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    existing = conn.execute(
        """
        SELECT * FROM inventory_source_stock
        WHERE inventory_source_id = ? AND offer_id = ?
        """,
        (inventory_source_id, offer_id),
    ).fetchone()

    if existing is not None and existing["version"] >= version:
        # Stale or duplicate message — return existing row unchanged
        return _stock_dict(existing)

    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO inventory_source_stock
                (inventory_source_id, offer_id, quantity, version, source_ref,
                 synced_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inventory_source_id,
                offer_id,
                quantity,
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
            UPDATE inventory_source_stock
            SET quantity   = ?,
                version    = ?,
                source_ref = ?,
                synced_at  = ?,
                updated_at = ?
            WHERE inventory_source_id = ? AND offer_id = ?
            """,
            (quantity, version, source_ref, now, now, inventory_source_id, offer_id),
        )
        row_id = existing["id"]

    row = conn.execute(
        "SELECT * FROM inventory_source_stock WHERE id = ?", (row_id,)
    ).fetchone()
    stock = _stock_dict(row)

    # Outbox: fan-out STOCK_UPDATED to connectors belonging to the supplier
    # that owns this inventory source.
    src_row = conn.execute(
        "SELECT supplier_id FROM inventory_sources WHERE id = ?",
        (inventory_source_id,),
    ).fetchone()
    _stock_supplier_id = src_row["supplier_id"] if src_row else None

    fan_out_business_event(
        conn,
        event_type="STOCK_UPDATED",
        supplier_id=_stock_supplier_id,
        payload={
            "inventory_source_id": inventory_source_id,
            "offer_id": offer_id,
            "quantity": quantity,
            "version": version,
        },
        base_idempotency_key=f"stock_updated:{inventory_source_id}:{offer_id}:{version}",
    )

    return stock


def get_authoritative_stock(
    conn: sqlite3.Connection,
    offer_id: int,
) -> dict | None:
    """Return the stock quantity from the highest-priority active inventory source.

    Joins inventory_sources + inventory_source_stock + seller_offers to
    filter by the offer's supplier_id.

    Returns dict with keys:
        offer_id, quantity, inventory_source_id, source_name, priority, synced_at
    or None if no stock record exists.
    """
    row = conn.execute(
        """
        SELECT
            iss.offer_id,
            iss.quantity,
            iss.inventory_source_id,
            src.name      AS source_name,
            src.priority,
            iss.synced_at
        FROM inventory_source_stock iss
        JOIN inventory_sources      src ON src.id = iss.inventory_source_id
        JOIN seller_offers          so  ON so.id  = iss.offer_id
        WHERE iss.offer_id   = ?
          AND src.supplier_id = so.supplier_id
          AND src.is_active   = 1
        ORDER BY src.priority DESC
        LIMIT 1
        """,
        (offer_id,),
    ).fetchone()

    if row is None:
        return None

    return {
        "offer_id": row["offer_id"],
        "quantity": row["quantity"],
        "inventory_source_id": row["inventory_source_id"],
        "source_name": row["source_name"],
        "priority": row["priority"],
        "synced_at": row["synced_at"],
    }


def list_stock_by_source(
    conn: sqlite3.Connection,
    inventory_source_id: int,
) -> list[dict]:
    """Return all inventory_source_stock rows for a given source."""
    rows = conn.execute(
        """
        SELECT * FROM inventory_source_stock
        WHERE inventory_source_id = ?
        ORDER BY offer_id
        """,
        (inventory_source_id,),
    ).fetchall()
    return [_stock_dict(r) for r in rows]
