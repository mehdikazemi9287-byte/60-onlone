"""Order reads. Every accessor is scoped to the owning user."""
from __future__ import annotations

import sqlite3

from app.core.db import Database
from app.core.errors import NotFoundError, ValidationError
from app.core.money import format_minor

MAX_PAGE_SIZE = 50


def read_order(conn: sqlite3.Connection, *, order_id: int, user_id: int | None, exponent: int = 0) -> dict:
    sql = "SELECT * FROM orders WHERE id = ?"
    params: list = [order_id]
    if user_id is not None:
        # Ownership is a WHERE clause, not a post-hoc check: a non-owner gets
        # an ordinary 404 and learns nothing about the order's existence.
        sql += " AND user_id = ?"
        params.append(user_id)
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")

    items = conn.execute(
        """
        SELECT oi.*, p.slug, p.image_emoji
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ? ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    payment = conn.execute(
        "SELECT provider, provider_ref, method, amount_minor, status, created_at "
        "FROM payments WHERE order_id = ? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    organization = None
    if row["organization_id"] is not None:
        org_row = conn.execute(
            "SELECT id, display_name FROM organizations WHERE id = ?", (row["organization_id"],)
        ).fetchone()
        if org_row is not None:
            organization = {"id": org_row["id"], "display_name": org_row["display_name"]}

    return {
        "id": row["id"],
        "order_number": row["order_number"],
        "status": row["status"],
        "placed_at": row["placed_at"],
        "currency": row["currency"],
        "subtotal": format_minor(row["subtotal_minor"], exponent),
        "subtotal_minor": row["subtotal_minor"],
        "shipping_fee": format_minor(row["shipping_fee_minor"], exponent),
        "shipping_fee_minor": row["shipping_fee_minor"],
        "total": format_minor(row["total_minor"], exponent),
        "total_minor": row["total_minor"],
        # VAT breakdown (v6): taxable_base = subtotal (shipping excluded from VAT)
        "taxable_base_minor": row["taxable_base_minor"] if row["taxable_base_minor"] is not None else row["subtotal_minor"],
        "tax_rate_bps": row["tax_rate_bps"] if row["tax_rate_bps"] is not None else 0,
        "tax": format_minor(row["tax_minor"] if row["tax_minor"] is not None else 0, exponent),
        "tax_minor": row["tax_minor"] if row["tax_minor"] is not None else 0,
        # Phase 2: how the order was funded. Zero credit means a plain
        # Flow 1 card purchase, which is what every retail order still is.
        "credit": format_minor(row["credit_minor"] or 0, exponent),
        "credit_minor": row["credit_minor"] or 0,
        "cash": format_minor(row["cash_minor"] or 0, exponent),
        "cash_minor": row["cash_minor"] or 0,
        "welfare_minor": (row["welfare_minor"] or 0) if "welfare_minor" in row.keys() else 0,
        "recurring_discount_minor": (row["recurring_discount_minor"] or 0) if "recurring_discount_minor" in row.keys() else 0,
        "redeem_coins": row["redeem_coins"] if "redeem_coins" in row.keys() else 0,
        "redeem_discount": format_minor(
            row["redeem_discount_minor"] if "redeem_discount_minor" in row.keys() else 0, exponent
        ),
        "redeem_discount_minor": row["redeem_discount_minor"] if "redeem_discount_minor" in row.keys() else 0,
        "organization_id": row["organization_id"],
        "is_split_payment": bool((row["credit_minor"] or 0) > 0 and (row["cash_minor"] or 0) > 0),
        "shipping_address": {
            "recipient_name": row["recipient_name"],
            "recipient_phone": row["recipient_phone"],
            "province": row["shipping_province"],
            "city": row["shipping_city"],
            "line1": row["shipping_line1"],
            "postal_code": row["shipping_postal_code"],
        },
        "items": [
            {
                "product_id": i["product_id"],
                "slug": i["slug"],
                "image_emoji": i["image_emoji"],
                "title_fa": i["title_fa"],
                "sku": i["sku"],
                "quantity": i["quantity"],
                "unit_price": format_minor(i["unit_price_minor"], exponent),
                "unit_price_minor": i["unit_price_minor"],
                "line_total": format_minor(i["line_total_minor"], exponent),
                "line_total_minor": i["line_total_minor"],
            }
            for i in items
        ],
        "organization": organization,
        "payment": None
        if payment is None
        else {
            "provider": payment["provider"],
            "provider_ref": payment["provider_ref"],
            "method": payment["method"],
            "amount": format_minor(payment["amount_minor"], exponent),
            "status": payment["status"],
            "created_at": payment["created_at"],
        },
    }


def get_order(db: Database, *, order_id: int, user_id: int | None, exponent: int = 0) -> dict:
    with db.read_transaction() as conn:
        return read_order(conn, order_id=order_id, user_id=user_id, exponent=exponent)


def get_order_by_number(db: Database, *, order_number: str, user_id: int | None, exponent: int = 0) -> dict:
    with db.read_transaction() as conn:
        row = conn.execute("SELECT id FROM orders WHERE order_number = ?", (order_number,)).fetchone()
        if row is None:
            raise NotFoundError("سفارش یافت نشد", code="order_not_found")
        return read_order(conn, order_id=int(row["id"]), user_id=user_id, exponent=exponent)


def list_orders(db: Database, *, user_id: int, page: int = 1, page_size: int = 10, exponent: int = 0) -> dict:
    if page < 1:
        raise ValidationError("page باید بزرگتر از صفر باشد")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValidationError(f"page_size باید بین ۱ و {MAX_PAGE_SIZE} باشد")
    with db.read_transaction() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            """
            SELECT o.id, o.order_number, o.status, o.total_minor, o.currency, o.placed_at,
                   o.credit_minor, o.cash_minor, o.organization_id,
                   (SELECT COALESCE(SUM(quantity),0) FROM order_items oi WHERE oi.order_id = o.id) AS item_count
            FROM orders o WHERE o.user_id = ?
            ORDER BY o.id DESC LIMIT ? OFFSET ?
            """,
            (user_id, page_size, (page - 1) * page_size),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "order_number": r["order_number"],
                "status": r["status"],
                "total": format_minor(r["total_minor"], exponent),
                "total_minor": r["total_minor"],
                "credit": format_minor(r["credit_minor"] or 0, exponent),
                "credit_minor": r["credit_minor"] or 0,
                "cash": format_minor(r["cash_minor"] or 0, exponent),
                "cash_minor": r["cash_minor"] or 0,
                "organization_id": r["organization_id"],
                "currency": r["currency"],
                "placed_at": r["placed_at"],
                "item_count": r["item_count"],
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "total_pages": (int(total) + page_size - 1) // page_size,
    }
