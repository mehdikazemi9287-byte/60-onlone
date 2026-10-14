"""Supplier catalog bulk-import — manual/CSV path today, same row shape a
future API/ERP connector integration can reuse.

A row that cannot be matched to a real existing master product is ALWAYS
queued for human review (identity_resolution_queue), never turned into a new
product automatically. This is a deliberately separate, stricter pathway
from the pre-existing product_resolution_service.py connector-sync pipeline
elsewhere in this codebase, which (for a different, ERP-connector use case)
can auto-create a placeholder canonical product on no-match — that
pre-existing behavior is untouched by this module and is never called here.

Matching logic below mirrors product_identity_service.resolve_identifier()'s
SELECTs exactly, but runs them against the SAME `conn`/transaction this
whole import batch uses (that service's own helpers open independent
transactions via app.core.db's Flask-app-bound connection, which cannot
safely be nested inside a caller-supplied `conn` write transaction — see
PROJECT_HANDOFF.md for why this file doesn't call through it directly).

Each row must supply at minimum: selling_price_minor, stock_quantity, and
either a barcode or a supplier_sku (usually both).
"""
from __future__ import annotations

import json
import sqlite3

from app.core.errors import ValidationError
from app.services import supplier_service


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _resolve_by_barcode(conn: sqlite3.Connection, barcode: str) -> int | None:
    row = conn.execute(
        """SELECT product_id FROM product_identifiers
               WHERE identifier_type IN ('EAN', 'GTIN13', 'GTIN12', 'GTIN14', 'GTIN8', 'UPC')
                 AND identifier_value = ?
               LIMIT 1""",
        (barcode,),
    ).fetchone()
    return int(row["product_id"]) if row else None


def _resolve_by_supplier_sku(conn: sqlite3.Connection, sku: str, supplier_id: int) -> int | None:
    row = conn.execute(
        """SELECT product_id FROM product_identifiers
               WHERE identifier_type = 'SUPPLIER_SKU' AND identifier_value = ?
                 AND supplier_id = ?
               LIMIT 1""",
        (sku, supplier_id),
    ).fetchone()
    return int(row["product_id"]) if row else None


def _register_supplier_sku(conn: sqlite3.Connection, *, product_id: int, sku: str, supplier_id: int) -> None:
    existing = conn.execute(
        """SELECT 1 FROM product_identifiers
               WHERE identifier_type = 'SUPPLIER_SKU' AND identifier_value = ? AND supplier_id = ?""",
        (sku, supplier_id),
    ).fetchone()
    if existing:
        return
    conn.execute(
        """INSERT INTO product_identifiers
               (product_id, identifier_type, identifier_value, supplier_id, confidence_bps, source, created_at, updated_at)
           VALUES (?, 'SUPPLIER_SKU', ?, ?, 10000, 'supplier_catalog_import', ?, ?)""",
        (product_id, sku, supplier_id, _now(), _now()),
    )


def _queue_for_review(
    conn: sqlite3.Connection, *, identifier_type: str, identifier_value: str,
    supplier_id: int, raw_row: dict,
) -> int:
    cur = conn.execute(
        """INSERT INTO identity_resolution_queue (
               identifier_type, identifier_value, supplier_id,
               raw_product_data_json, resolution_stage, status, priority, attempt_count, created_at
           ) VALUES (?, ?, ?, ?, 'pending', 'open', 5, 0, ?)""",
        (identifier_type, identifier_value, supplier_id,
         json.dumps(raw_row, ensure_ascii=False), _now()),
    )
    return int(cur.lastrowid)


def import_catalog_batch(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    supplier_location_id: int,
    submitted_by_user_id: int | None,
    rows: list[dict],
) -> dict:
    """Process a batch of supplier catalog rows within the caller's
    transaction. Returns the batch summary (also persisted)."""
    if not isinstance(rows, list):
        raise ValidationError("rows باید آرایه‌ای از ردیف‌ها باشد")
    if not rows:
        raise ValidationError("هیچ ردیفی برای وارد کردن ارسال نشده است")

    loc = conn.execute(
        "SELECT supplier_id FROM supplier_locations WHERE id = ?",
        (supplier_location_id,),
    ).fetchone()
    if loc is None or int(loc["supplier_id"]) != supplier_id:
        raise ValidationError("شعبه به این تأمین‌کننده تعلق ندارد")

    cur = conn.execute(
        """INSERT INTO supplier_catalog_import_batches
               (supplier_id, submitted_by_user_id, total_rows)
           VALUES (?,?,?)""",
        (supplier_id, submitted_by_user_id, len(rows)),
    )
    batch_id = int(cur.lastrowid)

    matched = queued = rejected = 0
    for row in rows:
        outcome = _import_one_row(
            conn, supplier_id=supplier_id, supplier_location_id=supplier_location_id,
            batch_id=batch_id, row=row,
        )
        if outcome == "matched":
            matched += 1
        elif outcome == "unresolved":
            queued += 1
        else:
            rejected += 1

    conn.execute(
        """UPDATE supplier_catalog_import_batches
               SET matched_count = ?, queued_count = ?, rejected_count = ? WHERE id = ?""",
        (matched, queued, rejected, batch_id),
    )
    return {
        "batch_id": batch_id, "total_rows": len(rows),
        "matched": matched, "queued_for_review": queued, "rejected": rejected,
    }


def _import_one_row(
    conn: sqlite3.Connection, *, supplier_id: int, supplier_location_id: int,
    batch_id: int, row: dict,
) -> str:
    """Returns one of: matched | duplicate_sku | unresolved | rejected."""
    def _log(match_status: str, **kw) -> None:
        conn.execute(
            """INSERT INTO supplier_catalog_import_rows
                   (batch_id, supplier_id, raw_row_json, match_status,
                    matched_product_id, created_offer_id, resolution_queue_id, error_message)
               VALUES (?,?,?,?,?,?,?,?)""",
            (batch_id, supplier_id, json.dumps(row, ensure_ascii=False), match_status,
             kw.get("matched_product_id"), kw.get("created_offer_id"),
             kw.get("resolution_queue_id"), kw.get("error_message")),
        )

    if not isinstance(row, dict):
        _log("rejected", error_message="ردیف باید یک شیء باشد")
        return "rejected"
    barcode = row.get("barcode")
    supplier_sku = row.get("supplier_sku") or row.get("sku")
    if any(value is not None and not isinstance(value, str) for value in (barcode, row.get("supplier_sku"), row.get("sku"))):
        _log("rejected", error_message="بارکد و کد کالا باید متن باشند")
        return "rejected"
    barcode = (barcode or "").strip()
    supplier_sku = (supplier_sku or "").strip()
    price_minor = row.get("selling_price_minor")
    stock_quantity = row.get("stock_quantity", 0)
    try:
        price_minor = supplier_service.exact_nonnegative_integer(price_minor, "قیمت")
        stock_quantity = supplier_service.exact_nonnegative_integer(stock_quantity, "موجودی")
    except ValidationError as exc:
        _log("rejected", error_message=str(exc))
        return "rejected"
    if not barcode and not supplier_sku:
        _log("rejected", error_message="بارکد یا کد کالای تأمین‌کننده الزامی است")
        return "rejected"

    # Duplicate supplier_sku guard: same supplier, same SKU, would-be
    # DIFFERENT product than what this row resolves to.
    existing_offer_for_sku = None
    if supplier_sku:
        existing_offer_for_sku = conn.execute(
            "SELECT product_id FROM seller_offers WHERE supplier_id = ? AND supplier_sku = ?",
            (supplier_id, supplier_sku),
        ).fetchone()

    product_id = _resolve_by_barcode(conn, barcode) if barcode else None
    if product_id is None and supplier_sku:
        product_id = _resolve_by_supplier_sku(conn, supplier_sku, supplier_id)

    if product_id is None:
        qid = _queue_for_review(
            conn,
            identifier_type="SUPPLIER_SKU" if supplier_sku else "EAN",
            identifier_value=supplier_sku or barcode,
            supplier_id=supplier_id, raw_row=row,
        )
        _log("unresolved", resolution_queue_id=qid)
        return "unresolved"

    if existing_offer_for_sku and int(existing_offer_for_sku["product_id"]) != product_id:
        _log(
            "duplicate_sku", matched_product_id=product_id,
            error_message=f"کد کالای «{supplier_sku}» قبلاً برای محصول دیگری توسط همین تأمین‌کننده ثبت شده است",
        )
        return "duplicate_sku"

    already = conn.execute(
        """SELECT id, stock_reserved FROM seller_offers
               WHERE product_id = ? AND supplier_id = ? AND supplier_location_id = ?""",
        (product_id, supplier_id, supplier_location_id),
    ).fetchone()
    if already:
        # Reject the complete row before touching price/history when stock is invalid.
        if stock_quantity < int(already["stock_reserved"]):
            _log("rejected", matched_product_id=product_id,
                 error_message="موجودی جدید کمتر از موجودی رزرو شده است")
            return "rejected"
        supplier_service.update_offer_price(
            conn, offer_id=int(already["id"]), supplier_id=supplier_id,
            selling_price_minor=int(price_minor),
        )
        offer = supplier_service.update_offer_stock(
            conn, offer_id=int(already["id"]), supplier_id=supplier_id,
            stock_quantity=int(stock_quantity),
        )
    else:
        offer = supplier_service.create_offer(
            conn, product_id=product_id, supplier_id=supplier_id,
            supplier_location_id=supplier_location_id,
            selling_price_minor=int(price_minor), stock_quantity=int(stock_quantity),
            supplier_sku=supplier_sku or None,
        )

    if supplier_sku:
        _register_supplier_sku(conn, product_id=product_id, sku=supplier_sku, supplier_id=supplier_id)

    _log("matched", matched_product_id=product_id, created_offer_id=offer["id"])
    return "matched"
