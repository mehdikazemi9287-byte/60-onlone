"""Shared, fail-closed policy for customer-visible sale eligibility.

A SKU is sellable only through a verified seller offer: active supplier, fixed/bulk pricing on the
retail channel, price and stock confirmed within 24 hours, stock > 0, not expired — and REAL
provenance for both offer and supplier. TEST offers count only in an isolated COMMERCE_TEST_MODE.
Cart prices come from that offer (with quantity tiers), never from products.base_price_minor.
"""
from __future__ import annotations

import os
import sqlite3

try:
    from flask import current_app, has_app_context
except ImportError:  # pragma: no cover
    current_app = None
    has_app_context = lambda: False

from app.core.errors import ConflictError
from app.services import product_channel_policy as policy

# Explicit go-live lock. Real sales additionally need a real payment gateway (see checkout_service).
STOREFRONT_SALES_ENABLED = False
MAX_CONFIRMATION_AGE_HOURS = 24

_ELIGIBLE_SQL = """
SELECT so.id, so.selling_price_minor,
       (so.stock_quantity - so.stock_reserved) AS available,
       so.min_order_quantity, so.max_order_quantity, so.lead_time_days, so.supplier_id, so.provenance
FROM seller_offers so
JOIN suppliers s ON s.id = so.supplier_id AND s.status = 'active'
WHERE so.product_id = ?
  AND so.status = 'active'
  AND so.pricing_mode IN ('fixed', 'bulk')
  AND so.channel IN ('retail', 'both')
  AND so.provenance IN ({prov}) AND s.provenance IN ({prov})
  AND (so.valid_until IS NULL OR so.valid_until >= date('now'))
  AND so.selling_price_minor > 0
  AND so.last_price_confirmed_at IS NOT NULL
  AND so.last_inventory_confirmed_at IS NOT NULL
  AND datetime(so.last_price_confirmed_at) >= datetime('now', '-24 hours')
  AND datetime(so.last_inventory_confirmed_at) >= datetime('now', '-24 hours')
  AND (so.stock_quantity - so.stock_reserved) > 0
ORDER BY so.selling_price_minor ASC, so.id ASC
LIMIT 1
"""


def _flag(name: str) -> bool:
    if has_app_context() and current_app.config.get(name) is not None:
        return bool(current_app.config.get(name))
    return os.environ.get(name) == "1"


def test_mode() -> bool:
    """Isolated E2E only: TEST suppliers/offers become sellable. Never set in production."""
    return _flag("COMMERCE_TEST_MODE")


def allowed_provenance() -> tuple[str, ...]:
    return ("real", "test") if test_mode() else ("real",)


def sales_enabled() -> bool:
    return STOREFRONT_SALES_ENABLED or _flag("STOREFRONT_SALES_ENABLED") or test_mode()


def _sql() -> str:
    return _ELIGIBLE_SQL.format(prov=",".join(f"'{p}'" for p in allowed_provenance())).replace("so.channel IN ('retail', 'both')", policy.offer_sql("so.product_id","so.channel","retail"))


def _test_override_enabled() -> bool:
    if has_app_context():
        return bool(current_app.config.get("TEST_SALES_OVERRIDE", False))
    return os.environ.get("TEST_SALES_OVERRIDE") == "1"


_LEGACY_OVERRIDE_SQL = """SELECT 0 AS id, p.base_price_minor AS selling_price_minor,
       COALESCE(i.quantity_available, 0) AS available, 1 AS min_order_quantity, NULL AS max_order_quantity,
       NULL AS lead_time_days, NULL AS supplier_id, 'test' AS provenance
FROM products p LEFT JOIN inventory i ON i.product_id=p.id
WHERE p.id=? AND p.is_active=1 AND p.base_price_minor>0"""


def eligible_offer_conn(conn: sqlite3.Connection, product_id: int):
    override = _test_override_enabled()
    if not sales_enabled() and not override:
        return None
    offer = conn.execute(_sql(), (product_id,)).fetchone()
    if offer is None and override:
        # Unit-test harness only (TEST_SALES_OVERRIDE): legacy base price + inventory.
        return conn.execute(_LEGACY_OVERRIDE_SQL + " AND " + policy.product_sql("p.id","retail"), (product_id,)).fetchone()
    return offer


def eligible_offer_db(db, product_id: int):
    override = _test_override_enabled()
    if not sales_enabled() and not override:
        return None
    offer = db.query_one(_sql(), (product_id,))
    if offer is None and override:
        return db.query_one(_LEGACY_OVERRIDE_SQL + " AND " + policy.product_sql("p.id","retail"), (product_id,))
    return offer



def catalog_price_sql(product_expression: str) -> str:
    """Internal SQL expression for ordering only; expression is never user input.

    Reuse the exact eligibility predicate rather than a separate price policy.
    The returned page still resolves full offers before serializing prices.
    """
    override = _test_override_enabled()
    if not sales_enabled() and not override:
        return "NULL"
    source = _sql()
    source = "SELECT so.selling_price_minor " + source[source.index("FROM seller_offers"):]
    source = source.replace("so.product_id = ?", f"so.product_id = {product_expression}", 1)
    expression = f"({source})"
    if override:
        fallback = f"""(SELECT fallback_product.base_price_minor FROM products fallback_product
            WHERE fallback_product.id={product_expression}
            AND fallback_product.is_active=1 AND fallback_product.base_price_minor>0
            AND {policy.product_sql('fallback_product.id', 'retail')})"""
        expression = f"COALESCE({expression}, {fallback})"
    return expression


def eligible_offers_db(db, product_ids) -> dict:
    """Resolve catalog offers in bounded batches with the same fail-closed policy.

    Keep price/provenance/channel checks identical to the single-product path.
    No result cache: price and stock remain authoritative on every request.
    """
    ids = list(dict.fromkeys(int(pid) for pid in product_ids))
    override = _test_override_enabled()
    if not ids or (not sales_enabled() and not override):
        return {}
    result = {}
    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        placeholders = ",".join("?" for _ in batch)
        sql = _sql().replace("SELECT so.id,", "SELECT so.product_id, so.id,", 1)
        sql = sql.replace("so.product_id = ?", f"so.product_id IN ({placeholders})", 1)
        sql = sql.replace("LIMIT 1", "")
        for row in db.query(sql, batch):
            # Ordered by price then id, as in eligible_offer_db.
            result.setdefault(int(row["product_id"]), row)
        if override:
            missing = [pid for pid in batch if pid not in result]
            if missing:
                marks = ",".join("?" for _ in missing)
                fallback = _LEGACY_OVERRIDE_SQL.replace("SELECT 0 AS id,", "SELECT p.id AS product_id, 0 AS id,", 1)
                fallback = fallback.replace("p.id=?", f"p.id IN ({marks})", 1)
                for row in db.query(fallback + " AND " + policy.product_sql("p.id", "retail"), missing):
                    result[int(row["product_id"])] = row
    return result


def unit_price(conn: sqlite3.Connection, offer, quantity: int, channel: str = "retail",
               organization_id: int | None = None) -> int:
    """Offer price for a quantity: the matching confirmed tier (organization contract first), else base."""
    if not offer["id"]:
        return int(offer["selling_price_minor"])
    live=conn.execute("SELECT product_id,channel FROM seller_offers WHERE id=?",(offer["id"],)).fetchone()
    if not live or channel not in policy.channels(policy.effective(conn,live["product_id"],live["channel"])):
        raise ConflictError("نوع عرضه Offer این قیمت‌گذاری را مجاز نمی‌کند",code="product_channel_unavailable")
    row = conn.execute(
        """SELECT unit_price_minor FROM offer_price_tiers
           WHERE offer_id=? AND channel=? AND min_qty<=? AND (max_qty IS NULL OR max_qty>=?)
             AND (organization_id IS NULL OR organization_id=?)
             AND datetime(confirmed_at) >= datetime('now', '-24 hours')
           ORDER BY organization_id IS NULL, min_qty DESC LIMIT 1""",
        (offer["id"], channel, quantity, quantity, organization_id)).fetchone()
    return int(row["unit_price_minor"]) if row else int(offer["selling_price_minor"])


def require_sale_eligible(conn: sqlite3.Connection, product_id: int):
    offer = eligible_offer_conn(conn, product_id)
    if offer is None:
        raise ConflictError(
            "قیمت و موجودی این کالا هنوز برای فروش تأیید نشده است",
            code="product_sale_unverified",
            details={"product_id": product_id},
        )
    return offer
