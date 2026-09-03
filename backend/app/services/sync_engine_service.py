"""
sync_engine_service.py
-----------------------
Orchestrates connector sync runs: lifecycle management (start/complete),
per-item result recording, and the top-level run_full_sync that drives
the whole pull → map → update pipeline.

The adapter registry lives at app.adapters.connectors.registry and is
imported lazily inside run_full_sync to avoid circular imports.

All DB access uses the caller-supplied ``conn`` (sqlite3.Connection).
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from app.core.errors import NotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_dict(row: sqlite3.Row) -> dict:
    """Convert a sync_runs row to a plain dict."""
    error_log = row["error_log_json"]
    if isinstance(error_log, str):
        try:
            error_log = json.loads(error_log)
        except (json.JSONDecodeError, TypeError):
            error_log = []
    return {
        "id": row["id"],
        "connector_account_id": row["connector_account_id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "records_processed": row["records_processed"],
        "records_succeeded": row["records_succeeded"],
        "records_failed": row["records_failed"],
        "error_log": error_log,
        "triggered_by": row["triggered_by"],
    }


def _item_dict(row: sqlite3.Row) -> dict:
    """Convert a sync_run_items row to a plain dict."""
    return {
        "id": row["id"],
        "sync_run_id": row["sync_run_id"],
        "external_code": row["external_code"],
        "product_id": row["product_id"],
        "offer_id": row["offer_id"],
        "status": row["status"],
        "action_taken": row["action_taken"],
        "error_msg": row["error_msg"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Sync run lifecycle
# ---------------------------------------------------------------------------


def start_sync_run(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int,
    job_type: str,
    triggered_by: str = "manual",
) -> int:
    """Insert a new sync_runs row with status='running'.

    Returns the new run_id (lastrowid).
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO sync_runs
            (connector_account_id, job_type, status, started_at,
             completed_at, records_processed, records_succeeded,
             records_failed, error_log_json, triggered_by)
        VALUES (?, ?, 'running', ?, NULL, 0, 0, 0, '[]', ?)
        """,
        (connector_account_id, job_type, now, triggered_by),
    )
    return cur.lastrowid


def complete_sync_run(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    status: str,
    records_processed: int = 0,
    records_succeeded: int = 0,
    records_failed: int = 0,
    error_log: list | None = None,
) -> None:
    """Update a sync_runs row to its final status and record totals.

    Also updates connector_accounts.last_sync_at to now.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    error_log_json = json.dumps(error_log or [], ensure_ascii=False)

    conn.execute(
        """
        UPDATE sync_runs
        SET status             = ?,
            completed_at       = ?,
            records_processed  = ?,
            records_succeeded  = ?,
            records_failed     = ?,
            error_log_json     = ?
        WHERE id = ?
        """,
        (
            status,
            now,
            records_processed,
            records_succeeded,
            records_failed,
            error_log_json,
            run_id,
        ),
    )

    # Fetch connector_account_id from the run to update last_sync_at
    row = conn.execute(
        "SELECT connector_account_id FROM sync_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE connector_accounts SET last_sync_at = ? WHERE id = ?",
            (now, row["connector_account_id"]),
        )


def add_sync_run_item(
    conn: sqlite3.Connection,
    *,
    sync_run_id: int,
    external_code: str,
    product_id: int | None = None,
    offer_id: int | None = None,
    status: str,
    action_taken: str = "",
    error_msg: str = "",
) -> None:
    """INSERT a sync_run_items row recording one processed item."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO sync_run_items
            (sync_run_id, external_code, product_id, offer_id,
             status, action_taken, error_msg, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sync_run_id,
            external_code,
            product_id,
            offer_id,
            status,
            action_taken,
            error_msg,
            now,
        ),
    )


def get_sync_run(conn: sqlite3.Connection, run_id: int) -> dict:
    """Return a single sync_runs row.

    Raises NotFoundError if not found.
    """
    row = conn.execute(
        "SELECT * FROM sync_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"اجرای همگام‌سازی با id={run_id} یافت نشد.")
    return _run_dict(row)


def list_sync_runs(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return sync_runs rows, newest first, with optional account filter."""
    query = "SELECT * FROM sync_runs WHERE 1=1"
    params: list = []

    if connector_account_id is not None:
        query += " AND connector_account_id = ?"
        params.append(connector_account_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [_run_dict(r) for r in rows]


def list_sync_run_items(
    conn: sqlite3.Connection,
    run_id: int,
) -> list[dict]:
    """Return all sync_run_items for a given run_id."""
    rows = conn.execute(
        "SELECT * FROM sync_run_items WHERE sync_run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return [_item_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Full orchestrated sync
# ---------------------------------------------------------------------------


def run_full_sync(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int,
    job_type: str = "inventory",
    triggered_by: str = "manual",
) -> dict:
    """Orchestrate a complete pull-map-update sync cycle.

    Steps:
    1. Open a sync run.
    2. Load the connector_account and build its adapter.
    3. Pull data from the adapter (pull_inventory or pull_prices).
    4. For each item, resolve the ERP code via erp_product_mappings.
    5. Update inventory_source_stock or price_source_entries.
    6. Record each item in sync_run_items.
    7. Close the sync run.

    Returns:
        {"run_id", "records_processed", "records_succeeded", "records_failed"}

    Raises ValidationError if the adapter does not support the requested job_type.
    """
    # Lazy import to avoid circular dependencies
    from app.adapters.connectors.registry import get_adapter

    run_id = start_sync_run(
        conn,
        connector_account_id=connector_account_id,
        job_type=job_type,
        triggered_by=triggered_by,
    )

    # ------------------------------------------------------------------
    # Load connector account
    # ------------------------------------------------------------------
    account_row = conn.execute(
        "SELECT * FROM connector_accounts WHERE id = ?",
        (connector_account_id,),
    ).fetchone()
    if account_row is None:
        complete_sync_run(
            conn,
            run_id=run_id,
            status="failed",
            error_log=[f"connector_account id={connector_account_id} یافت نشد."],
        )
        raise NotFoundError(
            f"حساب کانکتور با id={connector_account_id} یافت نشد."
        )

    connector_type = account_row["connector_type"]
    try:
        config = json.loads(account_row["config_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        config = {}

    supplier_id: int = account_row["supplier_id"]

    # ------------------------------------------------------------------
    # Build adapter and pull data
    # ------------------------------------------------------------------
    try:
        adapter = get_adapter(connector_type, config)
    except Exception as exc:
        complete_sync_run(
            conn,
            run_id=run_id,
            status="failed",
            error_log=[f"خطا در ساخت آداپتور: {exc}"],
        )
        raise ValidationError(
            f"آداپتور {connector_type!r} قابل ساخت نیست: {exc}"
        ) from exc

    try:
        if job_type == "inventory":
            items = adapter.pull_inventory()
        elif job_type == "prices":
            items = adapter.pull_prices()
        else:
            raise NotImplementedError(f"job_type نامعتبر: {job_type!r}")
    except NotImplementedError as exc:
        complete_sync_run(
            conn,
            run_id=run_id,
            status="failed",
            error_log=[str(exc)],
        )
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        complete_sync_run(
            conn,
            run_id=run_id,
            status="failed",
            error_log=[f"خطا در دریافت داده: {exc}"],
        )
        raise

    # ------------------------------------------------------------------
    # Resolve inventory/price source for this connector account
    # ------------------------------------------------------------------
    now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    # Find or create the inventory/price source linked to this connector account
    if job_type == "inventory":
        source_row = conn.execute(
            """
            SELECT id FROM inventory_sources
            WHERE connector_account_id = ? AND supplier_id = ?
            LIMIT 1
            """,
            (connector_account_id, supplier_id),
        ).fetchone()
        source_id: int | None = source_row["id"] if source_row else None
    else:
        source_row = conn.execute(
            """
            SELECT id FROM price_sources
            WHERE connector_account_id = ? AND supplier_id = ?
            LIMIT 1
            """,
            (connector_account_id, supplier_id),
        ).fetchone()
        source_id = source_row["id"] if source_row else None

    # ------------------------------------------------------------------
    # Process each item
    # ------------------------------------------------------------------
    processed = 0
    succeeded = 0
    failed = 0
    error_log: list[str] = []

    for item in items:
        processed += 1
        erp_code: str = str(item.get("erp_code") or item.get("code") or "")
        if not erp_code:
            add_sync_run_item(
                conn,
                sync_run_id=run_id,
                external_code="(empty)",
                status="skipped",
                action_taken="کد ERP خالی است",
            )
            failed += 1
            continue

        # Look up active mapping
        mapping_row = conn.execute(
            """
            SELECT product_id FROM erp_product_mappings
            WHERE connector_account_id = ?
              AND erp_product_code      = ?
              AND status                = 'active'
            LIMIT 1
            """,
            (connector_account_id, erp_code),
        ).fetchone()

        if mapping_row is None or mapping_row["product_id"] is None:
            add_sync_run_item(
                conn,
                sync_run_id=run_id,
                external_code=erp_code,
                status="unmapped",
                action_taken="نگاشت ERP فعال یافت نشد",
            )
            failed += 1
            continue

        product_id: int = mapping_row["product_id"]

        # Find the offer for this product + supplier
        offer_row = conn.execute(
            """
            SELECT id FROM seller_offers
            WHERE product_id = ? AND supplier_id = ?
            LIMIT 1
            """,
            (product_id, supplier_id),
        ).fetchone()

        if offer_row is None:
            add_sync_run_item(
                conn,
                sync_run_id=run_id,
                external_code=erp_code,
                product_id=product_id,
                status="error",
                action_taken="پیشنهاد فروش برای محصول+تأمین‌کننده یافت نشد",
            )
            failed += 1
            continue

        offer_id: int = offer_row["id"]

        try:
            if job_type == "inventory" and source_id is not None:
                quantity = int(item.get("quantity", 0))
                version = int(item.get("version", processed))
                source_ref = item.get("source_ref")

                conn.execute(
                    """
                    INSERT INTO inventory_source_stock
                        (inventory_source_id, offer_id, quantity, version,
                         source_ref, synced_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(inventory_source_id, offer_id) DO UPDATE SET
                        quantity   = CASE WHEN excluded.version > version
                                         THEN excluded.quantity ELSE quantity END,
                        version    = CASE WHEN excluded.version > version
                                         THEN excluded.version ELSE version END,
                        source_ref = CASE WHEN excluded.version > version
                                         THEN excluded.source_ref ELSE source_ref END,
                        synced_at  = CASE WHEN excluded.version > version
                                         THEN excluded.synced_at ELSE synced_at END,
                        updated_at = CASE WHEN excluded.version > version
                                         THEN excluded.updated_at ELSE updated_at END
                    """,
                    (source_id, offer_id, quantity, version, source_ref,
                     now_ts, now_ts, now_ts),
                )
                add_sync_run_item(
                    conn,
                    sync_run_id=run_id,
                    external_code=erp_code,
                    product_id=product_id,
                    offer_id=offer_id,
                    status="mapped",
                    action_taken=f"موجودی به‌روزرسانی شد: {quantity}",
                )

            elif job_type == "prices" and source_id is not None:
                price_minor = int(item.get("price_minor", 0))
                if price_minor < 0:
                    raise ValueError(f"price_minor منفی: {price_minor}")
                currency = str(item.get("currency", "IRR"))
                version = int(item.get("version", processed))
                source_ref = item.get("source_ref")

                conn.execute(
                    """
                    INSERT INTO price_source_entries
                        (price_source_id, offer_id, price_minor, currency, version,
                         source_ref, synced_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(price_source_id, offer_id) DO UPDATE SET
                        price_minor = CASE WHEN excluded.version > version
                                          THEN excluded.price_minor ELSE price_minor END,
                        currency    = CASE WHEN excluded.version > version
                                          THEN excluded.currency ELSE currency END,
                        version     = CASE WHEN excluded.version > version
                                          THEN excluded.version ELSE version END,
                        source_ref  = CASE WHEN excluded.version > version
                                          THEN excluded.source_ref ELSE source_ref END,
                        synced_at   = CASE WHEN excluded.version > version
                                          THEN excluded.synced_at ELSE synced_at END,
                        updated_at  = CASE WHEN excluded.version > version
                                          THEN excluded.updated_at ELSE updated_at END
                    """,
                    (source_id, offer_id, price_minor, currency, version,
                     source_ref, now_ts, now_ts, now_ts),
                )
                add_sync_run_item(
                    conn,
                    sync_run_id=run_id,
                    external_code=erp_code,
                    product_id=product_id,
                    offer_id=offer_id,
                    status="mapped",
                    action_taken=f"قیمت به‌روزرسانی شد: {price_minor} {currency}",
                )
            else:
                add_sync_run_item(
                    conn,
                    sync_run_id=run_id,
                    external_code=erp_code,
                    product_id=product_id,
                    offer_id=offer_id,
                    status="skipped",
                    action_taken="منبع یافت نشد، آیتم رد شد",
                )
                failed += 1
                continue

            succeeded += 1

        except Exception as exc:
            err_msg = str(exc)
            error_log.append(f"{erp_code}: {err_msg}")
            add_sync_run_item(
                conn,
                sync_run_id=run_id,
                external_code=erp_code,
                product_id=product_id,
                offer_id=offer_id,
                status="error",
                action_taken="خطا در به‌روزرسانی",
                error_msg=err_msg,
            )
            failed += 1

    # ------------------------------------------------------------------
    # Close the run
    # ------------------------------------------------------------------
    final_status = "completed" if failed == 0 else "completed_with_errors"
    complete_sync_run(
        conn,
        run_id=run_id,
        status=final_status,
        records_processed=processed,
        records_succeeded=succeeded,
        records_failed=failed,
        error_log=error_log,
    )

    return {
        "run_id": run_id,
        "records_processed": processed,
        "records_succeeded": succeeded,
        "records_failed": failed,
    }
