"""Connector abstraction layer.

70online will connect to ERP systems, chain stores, wholesalers, etc.
This module defines:
- The abstract Connector interface (pull_products, pull_prices, pull_inventory, push_order, health_check)
- The MANUAL connector (static data, always healthy) — used for demo/offline offers
- Connector account CRUD and sync run tracking

Production connectors (Holo, Sepidar, Rahkaran) are NOT implemented here.
They will be registered as named connector types in the registry when ready.

SECURITY: credential_ref stores a reference key only — never plaintext credentials.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.core.errors import NotFoundError, ValidationError

# ── Abstract Connector Interface ───────────────────────────────────────────────

class ConnectorBase(ABC):
    """Abstract interface every connector must implement."""

    @abstractmethod
    def health_check(self) -> dict:
        """Return {"healthy": bool, "message": str}"""

    @abstractmethod
    def pull_products(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        """Return list of external product records."""

    @abstractmethod
    def pull_prices(self, *, product_codes: list[str] | None = None) -> list[dict]:
        """Return list of {code, price_minor, currency, updated_at}"""

    @abstractmethod
    def pull_inventory(self, *, product_codes: list[str] | None = None) -> list[dict]:
        """Return list of {code, quantity, location_id, updated_at}"""

    @abstractmethod
    def push_order(self, order_data: dict) -> dict:
        """Push a confirmed PO to the external system. Return acknowledgement."""


class ManualConnector(ConnectorBase):
    """Manual / static connector — always healthy; no external sync needed."""

    def health_check(self) -> dict:
        return {"healthy": True, "message": "اتصال دستی — نیاز به همگام‌سازی ندارد"}

    def pull_products(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        return []

    def pull_prices(self, *, product_codes: list[str] | None = None) -> list[dict]:
        return []

    def pull_inventory(self, *, product_codes: list[str] | None = None) -> list[dict]:
        return []

    def push_order(self, order_data: dict) -> dict:
        return {"acknowledged": True, "external_ref": None}


class NotYetImplementedConnector(ConnectorBase):
    """Placeholder for connector types not yet implemented (Holo, Sepidar, etc.)."""

    def __init__(self, connector_type: str):
        self.connector_type = connector_type

    def health_check(self) -> dict:
        return {"healthy": False, "message": f"اتصال '{self.connector_type}' هنوز پیاده‌سازی نشده"}

    def pull_products(self, **_):
        raise NotImplementedError(f"اتصال '{self.connector_type}' پیاده‌سازی نشده")

    def pull_prices(self, **_):
        raise NotImplementedError

    def pull_inventory(self, **_):
        raise NotImplementedError

    def push_order(self, _):
        raise NotImplementedError


_CONNECTOR_REGISTRY: dict[str, type[ConnectorBase]] = {
    "MANUAL": ManualConnector,
    "CSV_IMPORT": NotYetImplementedConnector,
    "REST_API": NotYetImplementedConnector,
    "WEBHOOK": NotYetImplementedConnector,
    "SFTP": NotYetImplementedConnector,
    "HOLO_ERP": NotYetImplementedConnector,
    "SEPIDAR_ERP": NotYetImplementedConnector,
    "RAHKARAN_ERP": NotYetImplementedConnector,
    "CUSTOM_ERP": NotYetImplementedConnector,
    "OTHER": NotYetImplementedConnector,
}


def get_connector(connector_type: str, config: dict | None = None) -> ConnectorBase:
    """Instantiate the correct connector by type."""
    cls = _CONNECTOR_REGISTRY.get(connector_type.upper())
    if cls is None:
        raise ValidationError(f"نوع اتصال '{connector_type}' ناشناخته است")
    if cls is NotYetImplementedConnector:
        return cls(connector_type)
    return cls()


# ── Connector Account CRUD ─────────────────────────────────────────────────────

def _ca_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "connector_type": row["connector_type"],
        "supplier_id": row["supplier_id"],
        "organization_id": row["organization_id"],
        "credential_ref": row["credential_ref"],
        "config": json.loads(row["config_json"] or "{}"),
        "status": row["status"],
        "last_sync_at": row["last_sync_at"],
        "last_successful_sync_at": row["last_successful_sync_at"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
    }


def create_connector_account(
    conn,
    *,
    name: str,
    connector_type: str,
    supplier_id: int | None = None,
    organization_id: int | None = None,
    credential_ref: str | None = None,
    config: dict | None = None,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValidationError("نام اتصال نمی‌تواند خالی باشد")
    connector_type = connector_type.upper()
    if connector_type not in _CONNECTOR_REGISTRY:
        raise ValidationError(f"نوع اتصال '{connector_type}' نامعتبر است")

    cur = conn.execute(
        """INSERT INTO connector_accounts
           (name, connector_type, supplier_id, organization_id,
            credential_ref, config_json)
           VALUES (?,?,?,?,?,?)""",
        (name, connector_type, supplier_id, organization_id,
         credential_ref, json.dumps(config or {}, ensure_ascii=False)),
    )
    row = conn.execute("SELECT * FROM connector_accounts WHERE id=?", (cur.lastrowid,)).fetchone()
    return _ca_dict(row)


def get_connector_account(conn, account_id: int) -> dict:
    row = conn.execute("SELECT * FROM connector_accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        raise NotFoundError("حساب اتصال یافت نشد")
    return _ca_dict(row)


def list_connector_accounts(conn, *, supplier_id: int | None = None) -> list[dict]:
    if supplier_id:
        rows = conn.execute(
            "SELECT * FROM connector_accounts WHERE supplier_id=? ORDER BY id",
            (supplier_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM connector_accounts ORDER BY id").fetchall()
    return [_ca_dict(r) for r in rows]


# ── Sync Run Tracking ──────────────────────────────────────────────────────────

def start_sync_run(conn, *, connector_account_id: int, job_type: str, triggered_by: str = "manual") -> int:
    cur = conn.execute(
        """INSERT INTO sync_runs
           (connector_account_id, job_type, status, triggered_by)
           VALUES (?, ?, 'running', ?)""",
        (connector_account_id, job_type, triggered_by),
    )
    return cur.lastrowid


def complete_sync_run(
    conn,
    *,
    run_id: int,
    status: str,
    records_processed: int = 0,
    records_succeeded: int = 0,
    records_failed: int = 0,
    error_log: list | None = None,
) -> None:
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    conn.execute(
        """UPDATE sync_runs
           SET status=?, completed_at=?,
               records_processed=?, records_succeeded=?, records_failed=?,
               error_log_json=?
           WHERE id=?""",
        (
            status, now,
            records_processed, records_succeeded, records_failed,
            json.dumps(error_log or [], ensure_ascii=False),
            run_id,
        ),
    )
    if status == "completed":
        conn.execute(
            "UPDATE connector_accounts SET last_successful_sync_at=?, last_sync_at=?, updated_at=? WHERE id=("
            "SELECT connector_account_id FROM sync_runs WHERE id=?)",
            (now, now, now, run_id),
        )
    else:
        conn.execute(
            "UPDATE connector_accounts SET last_sync_at=?, updated_at=? WHERE id=("
            "SELECT connector_account_id FROM sync_runs WHERE id=?)",
            (now, now, run_id),
        )


def simulate_inventory_sync(
    conn,
    *,
    connector_account_id: int,
    updates: list[dict],  # [{offer_id, new_stock_quantity}]
) -> dict:
    """
    Simulate a connector pushing updated inventory quantities.
    Updates seller_offers.stock_quantity and last_inventory_confirmed_at.
    Does NOT touch master_product definitions.
    Returns summary.
    """
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    run_id = start_sync_run(
        conn,
        connector_account_id=connector_account_id,
        job_type="inventory",
        triggered_by="manual",
    )
    succeeded = 0
    failed = 0
    errors = []
    for u in updates:
        offer_id = u.get("offer_id")
        qty = u.get("new_stock_quantity")
        if offer_id is None or qty is None or qty < 0:
            errors.append(f"ردیف نامعتبر: {u}")
            failed += 1
            continue
        row = conn.execute("SELECT id FROM seller_offers WHERE id=?", (offer_id,)).fetchone()
        if not row:
            errors.append(f"پیشنهاد {offer_id} یافت نشد")
            failed += 1
            continue
        conn.execute(
            "UPDATE seller_offers SET stock_quantity=?, last_inventory_confirmed_at=? WHERE id=?",
            (int(qty), now, offer_id),
        )
        succeeded += 1

    complete_sync_run(
        conn,
        run_id=run_id,
        status="completed" if not failed else "failed",
        records_processed=len(updates),
        records_succeeded=succeeded,
        records_failed=failed,
        error_log=errors,
    )
    return {
        "run_id": run_id,
        "records_processed": len(updates),
        "records_succeeded": succeeded,
        "records_failed": failed,
        "errors": errors,
    }


def simulate_price_sync(
    conn,
    *,
    connector_account_id: int,
    updates: list[dict],  # [{offer_id, new_selling_price_minor}]
) -> dict:
    """Simulate a connector updating offer prices. Does NOT change master_product or historical orders."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    run_id = start_sync_run(
        conn,
        connector_account_id=connector_account_id,
        job_type="prices",
        triggered_by="manual",
    )
    succeeded = 0
    failed = 0
    errors = []
    for u in updates:
        offer_id = u.get("offer_id")
        price = u.get("new_selling_price_minor")
        if offer_id is None or price is None or price < 0:
            errors.append(f"ردیف نامعتبر: {u}")
            failed += 1
            continue
        row = conn.execute("SELECT id FROM seller_offers WHERE id=?", (offer_id,)).fetchone()
        if not row:
            errors.append(f"پیشنهاد {offer_id} یافت نشد")
            failed += 1
            continue
        conn.execute(
            "UPDATE seller_offers SET selling_price_minor=?, last_price_confirmed_at=? WHERE id=?",
            (int(price), now, offer_id),
        )
        succeeded += 1

    complete_sync_run(
        conn,
        run_id=run_id,
        status="completed" if not failed else "failed",
        records_processed=len(updates),
        records_succeeded=succeeded,
        records_failed=failed,
        error_log=errors,
    )
    return {
        "run_id": run_id,
        "records_processed": len(updates),
        "records_succeeded": succeeded,
        "records_failed": failed,
        "errors": errors,
    }
