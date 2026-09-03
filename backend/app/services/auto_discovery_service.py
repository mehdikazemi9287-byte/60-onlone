"""Auto Discovery Service — Zero-Touch Pipeline.

Pulls ALL products from a connector adapter (paginated), resolves each one
through the product resolution service, and records results.

Key features:
- Memory-bounded: processes products in batches, no full dataset in RAM
- Idempotent: second run matches instead of creating duplicates
- Isolated failures: one bad row does not stop the pipeline
- Creates exceptions for AMBIGUOUS/CONFLICT results
- Commits every batch_size rows to avoid huge transactions

All money as INTEGER. No REAL/FLOAT.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import time

from app.adapters.connectors import registry as connector_registry
from app.adapters.connectors.mock_erp_v2 import ConnectorOutageError
from app.services import product_resolution_service as prs
from app.services import exception_service


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _get_connector_account(conn: sqlite3.Connection, connector_account_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM connector_accounts WHERE id = ?", (connector_account_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"حساب اتصال {connector_account_id} یافت نشد")
    return dict(row)


def _start_sync_run(
    conn: sqlite3.Connection,
    connector_account_id: int,
    triggered_by: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO sync_runs
           (connector_account_id, job_type, status, started_at,
            records_processed, records_succeeded, records_failed,
            error_log_json, triggered_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (connector_account_id, "discovery", "running", _now(), 0, 0, 0, "[]", triggered_by),
    )
    return int(cur.lastrowid)


def _finish_sync_run(
    conn: sqlite3.Connection,
    sync_run_id: int,
    *,
    processed: int,
    succeeded: int,
    failed: int,
    errors: list[str],
    status: str = "completed",
) -> None:
    conn.execute(
        """UPDATE sync_runs
           SET status = ?, completed_at = ?,
               records_processed = ?, records_succeeded = ?, records_failed = ?,
               error_log_json = ?
           WHERE id = ?""",
        (status, _now(), processed, succeeded, failed, json.dumps(errors[:100]), sync_run_id),
    )


def _process_one_product(
    conn: sqlite3.Connection,
    *,
    external: dict,
    connector_account_id: int,
    supplier_id: int,
    sync_run_id: int,
) -> dict:
    """
    Resolve one external product. Returns summary dict.
    Raises on hard error (caller isolates).
    """
    result = prs.resolve_product(
        conn,
        external=external,
        connector_account_id=connector_account_id,
        supplier_id=supplier_id,
        sync_run_id=sync_run_id,
    )

    # Create exception for ambiguous/conflict results
    if result["result"] in ("ambiguous", "conflict"):
        try:
            exception_service.create_exception(
                conn,
                exception_type="ambiguous_match" if result["result"] == "ambiguous" else "identifier_conflict",
                severity="medium",
                supplier_id=supplier_id,
                connector_account_id=connector_account_id,
                sync_run_id=sync_run_id,
                title=f"تعارض شناسه محصول: {external.get('code', '')}",
                detail={
                    "external": external,
                    "resolution_result": result,
                },
            )
        except Exception:
            pass  # Don't let exception creation failure stop the pipeline

    return result


def run_discovery_sync(
    conn: sqlite3.Connection,
    *,
    connector_account_id: int,
    triggered_by: str = "manual",
    batch_size: int = 100,
) -> dict:
    """
    Pull ALL products from connector (paginated), resolve each one.

    - MATCHED → update price/inventory
    - NEW_CANONICAL → create product+offer+price+inventory
    - AMBIGUOUS/CONFLICT → create exception, record as unmapped

    Returns full summary dict with timing.
    """
    start_time = time.time()

    # Get connector account
    ca = _get_connector_account(conn, connector_account_id)
    connector_type = ca["connector_type"]
    config_raw = ca.get("config_json") or "{}"
    try:
        config = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
    except Exception:
        config = {}

    # Add dataset info from mock_erp_dataset column
    mock_dataset = ca.get("mock_erp_dataset", "products")
    if "mock_erp_dataset" not in config:
        config["mock_erp_dataset"] = mock_dataset

    supplier_id = ca.get("supplier_id")
    if not supplier_id:
        raise ValueError("حساب اتصال باید به یک تأمین‌کننده متصل باشد")

    # Start sync run
    with conn:
        conn.execute("BEGIN")
        sync_run_id = _start_sync_run(conn, connector_account_id, triggered_by)
        conn.execute("COMMIT")

    # Get adapter
    try:
        adapter = connector_registry.get_adapter(connector_type, config=config)
    except Exception as exc:
        with conn:
            conn.execute("BEGIN")
            _finish_sync_run(conn, sync_run_id, processed=0, succeeded=0, failed=0,
                           errors=[str(exc)], status="failed")
            conn.execute("COMMIT")
        return {
            "sync_run_id": sync_run_id,
            "status": "failed",
            "processed": 0,
            "matched": 0,
            "new_canonical": 0,
            "conflict": 0,
            "failed": 0,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "error": str(exc),
        }

    # Check outage
    try:
        health = adapter.health_check()
        if not health.get("healthy", True):
            exc_msg = health.get("message", "connector unhealthy")
            try:
                conn.execute("BEGIN")
                exception_service.create_exception(
                    conn,
                    exception_type="connector_outage",
                    severity="high",
                    supplier_id=supplier_id,
                    connector_account_id=connector_account_id,
                    title=f"اختلال اتصال: {ca['name']}",
                    detail={"health": health},
                )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            conn.execute("BEGIN")
            _finish_sync_run(conn, sync_run_id, processed=0, succeeded=0, failed=0,
                           errors=[exc_msg], status="failed")
            conn.execute("COMMIT")
            return {
                "sync_run_id": sync_run_id,
                "status": "failed",
                "processed": 0,
                "matched": 0,
                "new_canonical": 0,
                "conflict": 0,
                "failed": 0,
                "elapsed_seconds": round(time.time() - start_time, 2),
                "error": exc_msg,
            }
    except ConnectorOutageError as exc:
        try:
            conn.execute("BEGIN")
            exception_service.create_exception(
                conn,
                exception_type="connector_outage",
                severity="high",
                supplier_id=supplier_id,
                connector_account_id=connector_account_id,
                title=f"اختلال اتصال: {ca['name']}",
                detail={"error": str(exc)},
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        conn.execute("BEGIN")
        _finish_sync_run(conn, sync_run_id, processed=0, succeeded=0, failed=0,
                       errors=[str(exc)], status="failed")
        conn.execute("COMMIT")
        return {
            "sync_run_id": sync_run_id,
            "status": "failed",
            "processed": 0,
            "matched": 0,
            "new_canonical": 0,
            "conflict": 0,
            "failed": 0,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "error": str(exc),
        }

    # Pull products (paginated)
    total_processed = 0
    total_matched = 0
    total_new = 0
    total_conflict = 0
    total_failed = 0
    errors: list[str] = []

    batch: list[dict] = []

    def _process_batch(items: list[dict]) -> None:
        nonlocal total_processed, total_matched, total_new, total_conflict, total_failed

        conn.execute("BEGIN")
        try:
            for external in items:
                try:
                    result = _process_one_product(
                        conn,
                        external=external,
                        connector_account_id=connector_account_id,
                        supplier_id=supplier_id,
                        sync_run_id=sync_run_id,
                    )
                    r = result["result"]
                    if r == "matched":
                        total_matched += 1
                    elif r == "new_canonical":
                        total_new += 1
                    elif r in ("conflict", "ambiguous"):
                        total_conflict += 1
                    total_processed += 1
                except Exception as exc:
                    total_failed += 1
                    total_processed += 1
                    err_msg = f"Product {external.get('code', '?')}: {exc}"
                    errors.append(err_msg)
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass

    # Use generator if available (MockErpV2), else paginate
    if hasattr(adapter, "pull_products_all"):
        gen = adapter.pull_products_all()
        batch = []
        for product in gen:
            batch.append(product)
            if len(batch) >= batch_size:
                _process_batch(batch)
                batch = []
        if batch:
            _process_batch(batch)
    else:
        offset = 0
        while True:
            page = adapter.pull_products(limit=batch_size, offset=offset)
            if isinstance(page, dict):
                items = page.get("items", [])
                total_in_source = page.get("total", 0)
            else:
                items = list(page)
                total_in_source = 0

            if not items:
                break
            _process_batch(items)
            offset += len(items)
            if total_in_source and offset >= total_in_source:
                break

    # Finish sync run
    final_status = "completed" if total_failed == 0 else "completed_with_errors"
    conn.execute("BEGIN")
    _finish_sync_run(
        conn,
        sync_run_id,
        processed=total_processed,
        succeeded=total_matched + total_new,
        failed=total_failed,
        errors=errors,
        status=final_status,
    )
    conn.execute("COMMIT")

    elapsed = round(time.time() - start_time, 2)
    return {
        "sync_run_id": sync_run_id,
        "status": final_status,
        "processed": total_processed,
        "matched": total_matched,
        "new_canonical": total_new,
        "conflict": total_conflict,
        "failed": total_failed,
        "elapsed_seconds": elapsed,
        "errors": errors[:20],  # Return first 20 errors for inspection
    }
