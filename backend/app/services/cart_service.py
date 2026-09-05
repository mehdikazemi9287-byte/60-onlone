"""Server-side cart.

The cart is authoritative on the server: quantities are validated against live
inventory and unit prices are re-read from the catalog on every mutation, so a
client cannot post its own price.
"""
from __future__ import annotations

import json
import sqlite3

from app.core.db import Database
from app.core.errors import NotFoundError, OutOfStockError, ValidationError
from app.core.money import format_minor
from app.services import sale_eligibility

MAX_LINE_QUANTITY = 20
SHIPPING_FLAT_MINOR = 350_000  # 35,000 Toman expressed in IRR minor units
FREE_SHIPPING_THRESHOLD_MINOR = 20_000_000


def _first_image_url(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        urls = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return urls[0] if isinstance(urls, list) and urls else None


def get_or_create_active_cart_id(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM carts WHERE user_id = ? AND status = 'active'", (user_id,)
    ).fetchone()
    if row is not None:
        return int(row["id"])
    cursor = conn.execute("INSERT INTO carts (user_id, status) VALUES (?, 'active')", (user_id,))
    return int(cursor.lastrowid)


def _load_product(conn: sqlite3.Connection, product_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT p.id, p.title_fa, p.sku, p.base_price_minor, p.is_active,
               COALESCE(i.quantity_available, 0) AS quantity_available
        FROM products p LEFT JOIN inventory i ON i.product_id = p.id
        WHERE p.id = ?
        """,
        (product_id,),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise NotFoundError("محصول یافت نشد", code="product_not_found")
    sale_eligibility.require_sale_eligible(conn, product_id)
    return row


def add_item(db: Database, *, user_id: int, product_id: int, quantity: int) -> dict:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ValidationError("تعداد باید عدد صحیح و حداقل ۱ باشد")
    with db.write_transaction() as conn:
        product = _load_product(conn, product_id)
        cart_id = get_or_create_active_cart_id(conn, user_id)
        existing = conn.execute(
            "SELECT quantity FROM cart_items WHERE cart_id = ? AND product_id = ?",
            (cart_id, product_id),
        ).fetchone()
        new_quantity = (int(existing["quantity"]) if existing else 0) + quantity
        if new_quantity > MAX_LINE_QUANTITY:
            raise ValidationError(f"حداکثر {MAX_LINE_QUANTITY} عدد از هر کالا در سبد مجاز است")
        if new_quantity > product["quantity_available"]:
            raise OutOfStockError(
                f"موجودی کافی نیست (موجود: {product['quantity_available']})",
                details={"available": product["quantity_available"]},
            )
        conn.execute(
            """
            INSERT INTO cart_items (cart_id, product_id, quantity, unit_price_minor)
            VALUES (?,?,?,?)
            ON CONFLICT (cart_id, product_id)
            DO UPDATE SET quantity = excluded.quantity, unit_price_minor = excluded.unit_price_minor
            """,
            (cart_id, product_id, new_quantity, product["base_price_minor"]),
        )
        conn.execute("UPDATE carts SET updated_at = datetime('now') WHERE id = ?", (cart_id,))
    return get_cart(db, user_id=user_id)


def set_item_quantity(db: Database, *, user_id: int, product_id: int, quantity: int) -> dict:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
        raise ValidationError("تعداد باید عدد صحیح و غیرمنفی باشد")
    with db.write_transaction() as conn:
        cart_id = get_or_create_active_cart_id(conn, user_id)
        if quantity == 0:
            conn.execute(
                "DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, product_id)
            )
        else:
            product = _load_product(conn, product_id)
            if quantity > MAX_LINE_QUANTITY:
                raise ValidationError(f"حداکثر {MAX_LINE_QUANTITY} عدد از هر کالا در سبد مجاز است")
            if quantity > product["quantity_available"]:
                raise OutOfStockError(
                    f"موجودی کافی نیست (موجود: {product['quantity_available']})",
                    details={"available": product["quantity_available"]},
                )
            updated = conn.execute(
                "UPDATE cart_items SET quantity = ?, unit_price_minor = ? WHERE cart_id = ? AND product_id = ?",
                (quantity, product["base_price_minor"], cart_id, product_id),
            )
            if updated.rowcount == 0:
                raise NotFoundError("این کالا در سبد شما نیست", code="cart_item_not_found")
        conn.execute("UPDATE carts SET updated_at = datetime('now') WHERE id = ?", (cart_id,))
    return get_cart(db, user_id=user_id)


def remove_item(db: Database, *, user_id: int, product_id: int) -> dict:
    return set_item_quantity(db, user_id=user_id, product_id=product_id, quantity=0)


def clear_cart(db: Database, *, user_id: int) -> dict:
    with db.write_transaction() as conn:
        cart_id = get_or_create_active_cart_id(conn, user_id)
        conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
    return get_cart(db, user_id=user_id)


def shipping_fee_minor(subtotal_minor: int) -> int:
    if subtotal_minor <= 0:
        return 0
    return 0 if subtotal_minor >= FREE_SHIPPING_THRESHOLD_MINOR else SHIPPING_FLAT_MINOR


def read_cart(conn: sqlite3.Connection, user_id: int, exponent: int = 0) -> dict:
    """Cart projection. Totals are integer sums -- no float anywhere."""
    cart_id = get_or_create_active_cart_id(conn, user_id)
    rows = conn.execute(
        """
        SELECT ci.product_id, ci.quantity, ci.unit_price_minor,
               p.title_fa, p.slug, p.sku, p.image_emoji, mp.image_urls_json,
               COALESCE(i.quantity_available, 0) AS quantity_available
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        LEFT JOIN inventory i ON i.product_id = p.id
        LEFT JOIN master_products mp ON mp.id = p.master_product_id
        WHERE ci.cart_id = ?
        ORDER BY ci.id
        """,
        (cart_id,),
    ).fetchall()

    items = []
    subtotal = 0
    for r in rows:
        sale_eligibility.require_sale_eligible(conn, int(r["product_id"]))
        line_total = int(r["unit_price_minor"]) * int(r["quantity"])
        subtotal += line_total
        items.append(
            {
                "product_id": r["product_id"],
                "slug": r["slug"],
                "title_fa": r["title_fa"],
                "sku": r["sku"],
                "image_emoji": r["image_emoji"],
                "image_url": _first_image_url(r["image_urls_json"]),
                "quantity": r["quantity"],
                "quantity_available": r["quantity_available"],
                "unit_price": format_minor(r["unit_price_minor"], exponent),
                "unit_price_minor": r["unit_price_minor"],
                "line_total": format_minor(line_total, exponent),
                "line_total_minor": line_total,
            }
        )
    shipping = shipping_fee_minor(subtotal)
    return {
        "cart_id": cart_id,
        "items": items,
        "item_count": sum(int(r["quantity"]) for r in rows),
        "subtotal": format_minor(subtotal, exponent),
        "subtotal_minor": subtotal,
        "shipping_fee": format_minor(shipping, exponent),
        "shipping_fee_minor": shipping,
        "total": format_minor(subtotal + shipping, exponent),
        "total_minor": subtotal + shipping,
        "currency": "IRR",
    }


def get_cart(db: Database, *, user_id: int, exponent: int = 0) -> dict:
    with db.write_transaction() as conn:
        return read_cart(conn, user_id, exponent)
