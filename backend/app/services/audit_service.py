"""Append-only audit trail.

This is a real mechanism, not just a table: every state-changing service call in
Flow 1 records an entry, and the table rejects UPDATE/DELETE at the storage
layer (see migrations/0001_initial.sql).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

REDACTED_KEYS = {"password", "password_hash", "token", "authorization", "secret"}


def _scrub(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ("[redacted]" if k.lower() in REDACTED_KEYS else v) for k, v in metadata.items()
    }


def record(
    conn: sqlite3.Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    actor_user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id, metadata_json, ip_address)
        VALUES (?,?,?,?,?,?)
        """,
        (
            actor_user_id,
            action,
            entity_type,
            None if entity_id is None else str(entity_id),
            json.dumps(_scrub(metadata or {}), ensure_ascii=False, sort_keys=True),
            ip_address,
        ),
    )
    return int(cursor.lastrowid)


def list_for_actor(conn: sqlite3.Connection, actor_user_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, action, entity_type, entity_id, metadata_json, created_at
        FROM audit_logs WHERE actor_user_id = ?
        ORDER BY id DESC LIMIT ?
        """,
        (actor_user_id, limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "action": r["action"],
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "metadata": json.loads(r["metadata_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
