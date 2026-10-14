"""Offer / pricing engine — the data layer behind the existing Product UI.

This module is deliberately read-only and additive: it computes a
deterministic "best offer" (buy box) over the REAL seller_offers rows for a
product, and a per-offer availability state, without touching
`products.base_price_minor` (the field the storefront currently displays) or
any existing checkout/fulfillment code path. `fulfillment_engine.route()`
remains the authority for actual order-time routing/reservation — this
module is for browse-time "what offers exist / what would the best price be"
queries, and is not wired into any UI this pass (see PROJECT_HANDOFF.md).

Nothing here ever fabricates a price or availability value: a product with
zero real seller_offers returns best_offer=None, and callers must keep
falling back to the existing base_price_minor display exactly as today.
"""
from __future__ import annotations

import sqlite3
from app.services import product_channel_policy as policy


def _availability_state(offer_row: dict, supplier_status: str) -> str:
    """One of: available | out_of_stock | offer_disabled | supplier_disabled."""
    if supplier_status != "active":
        return "supplier_disabled"
    if offer_row["status"] != "active":
        return "offer_disabled"
    if int(offer_row["stock_quantity"]) - int(offer_row["stock_reserved"]) <= 0:
        return "out_of_stock"
    return "available"


def list_offers_for_product(conn: sqlite3.Connection, *, product_id: int) -> list[dict]:
    """Every real seller_offer for this product, each annotated with a
    deterministic availability_state. Never invents an offer that doesn't
    exist in seller_offers."""
    rows = conn.execute(
        """
        SELECT so.*, s.display_name AS supplier_name, s.status AS supplier_status,
               sl.city, sl.province
        FROM seller_offers so
        JOIN suppliers s           ON s.id  = so.supplier_id
        JOIN supplier_locations sl ON sl.id = so.supplier_location_id
        WHERE so.product_id = ?
        ORDER BY so.selling_price_minor ASC
        """,
        (product_id,),
    ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d.update(policy.offer_fields(conn,product_id,d["channel"]))
        d["availability_state"] = _availability_state(d, d["supplier_status"]) if d["effective_channel"] else "product_disabled"
        if d["effective_channel"] is None:continue
        d["channel"]=d["effective_channel"]
        result.append(d)
    return result


def get_best_offer(conn: sqlite3.Connection, *, product_id: int) -> dict | None:
    """Deterministic lowest-price eligible offer (available only). Returns
    None when there are zero eligible real offers — callers must not
    substitute a fabricated price in that case, only fall back to whatever
    the product's own base_price_minor already shows today."""
    offers = list_offers_for_product(conn, product_id=product_id)
    eligible = [o for o in offers if o["availability_state"] == "available" and "retail" in o["allowed_channels"]]
    if not eligible:
        return None
    # Already sorted by selling_price_minor ASC; tie-break deterministically
    # by offer id so repeated calls against unchanged data always agree.
    eligible.sort(key=lambda o: (o["selling_price_minor"], o["id"]))
    return eligible[0]


def get_offer_summary(conn: sqlite3.Connection, *, product_id: int) -> dict:
    """Compact summary for a storefront product-detail 'offers' panel,
    prepared for future UI use — not wired into any page this pass."""
    offers = list_offers_for_product(conn, product_id=product_id)
    best = get_best_offer(conn, product_id=product_id)
    return {
        "offer_count": len(offers),
        "available_offer_count": sum(1 for o in offers if o["availability_state"] == "available" and "retail" in o["allowed_channels"]),
        "best_offer": best,
        "offers": offers,
    }
