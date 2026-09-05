"""Shared, fail-closed policy for customer-visible sale eligibility."""
from __future__ import annotations
import sqlite3
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
    if not STOREFRONT_SALES_ENABLED:
        return None
    return conn.execute(_ELIGIBLE_SQL, (product_id,)).fetchone()

def eligible_offer_db(db, product_id: int):
    if not STOREFRONT_SALES_ENABLED:
        return None
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
