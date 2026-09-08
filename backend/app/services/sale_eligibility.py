"""Shared, fail-closed policy for customer-visible sale eligibility."""
from __future__ import annotations
import sqlite3
import os
try:
    from flask import current_app, has_app_context
except ImportError:  # pragma: no cover
    current_app = None
    has_app_context = lambda: False
from app.core.errors import ConflictError

# Explicit emergency go-live safety lock. Enabling sales requires a separately
# reviewed end-to-end verified-offer binding across cart and fulfillment.
STOREFRONT_SALES_ENABLED = False
MAX_CONFIRMATION_AGE_HOURS = 24
_ELIGIBLE_SQL = """
SELECT so.id, so.selling_price_minor,
       (so.stock_quantity - so.stock_reserved) AS available
FROM seller_offers so
WHERE so.product_id = ?
  AND so.status = 'active'
  AND so.selling_price_minor > 0
  AND so.last_price_confirmed_at IS NOT NULL
  AND so.last_inventory_confirmed_at IS NOT NULL
  AND datetime(so.last_price_confirmed_at) >= datetime('now', '-24 hours')
  AND datetime(so.last_inventory_confirmed_at) >= datetime('now', '-24 hours')
  AND (so.stock_quantity - so.stock_reserved) > 0
ORDER BY so.selling_price_minor ASC, so.id ASC
LIMIT 1
"""

def eligible_offer_conn(conn: sqlite3.Connection, product_id: int):
    test_override = _test_override_enabled()
    if not STOREFRONT_SALES_ENABLED and not test_override:
        return None
    if test_override:
        offer = conn.execute(_ELIGIBLE_SQL, (product_id,)).fetchone()
        if offer is not None:
            return offer
        return conn.execute(
            """SELECT 0 AS id, p.base_price_minor AS selling_price_minor,
                      COALESCE(i.quantity_available, 0) AS available
               FROM products p LEFT JOIN inventory i ON i.product_id=p.id
               WHERE p.id=? AND p.is_active=1 AND p.base_price_minor>0
                 """,
            (product_id,),
        ).fetchone()
    return conn.execute(_ELIGIBLE_SQL, (product_id,)).fetchone()

def _test_override_enabled() -> bool:
    if has_app_context():
        return bool(current_app.config.get("TEST_SALES_OVERRIDE", False))
    return os.environ.get("TEST_SALES_OVERRIDE") == "1"

def eligible_offer_db(db, product_id: int):
    if not STOREFRONT_SALES_ENABLED and not _test_override_enabled():
        return None
    if _test_override_enabled():
        offer = db.query_one(_ELIGIBLE_SQL, (product_id,))
        if offer is not None:
            return offer
        return db.query_one(
            """SELECT 0 AS id, p.base_price_minor AS selling_price_minor,
                      COALESCE(i.quantity_available, 0) AS available
               FROM products p LEFT JOIN inventory i ON i.product_id=p.id
               WHERE p.id=? AND p.is_active=1 AND p.base_price_minor>0
                 """,
            (product_id,),
        )
    return db.query_one(_ELIGIBLE_SQL, (product_id,))

def require_sale_eligible(conn: sqlite3.Connection, product_id: int):
    offer = eligible_offer_conn(conn, product_id)
    if offer is None:
        raise ConflictError(
            "قیمت و موجودی این کالا هنوز برای فروش تأیید نشده است",
            code="product_sale_unverified",
            details={"product_id": product_id},
        )
    return offer
