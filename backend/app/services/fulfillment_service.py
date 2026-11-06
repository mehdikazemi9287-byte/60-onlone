"""FulfillmentOrder lifecycle service.

Responsibilities:
  * Create fulfillment orders after a customer order is paid (called from checkout)
  * Manage state transitions (supplier accept/reject, preparing, ready, etc.)
  * Reserve and release supplier stock (race-safe via BEGIN IMMEDIATE)
  * Handle rejection → fallback routing
  * Record routing audit trail

This service assumes it will always be called inside `db.write_transaction()`.
All helpers that take a `conn` argument expect an open, uncommitted transaction.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.errors import ConflictError, FulfillmentUnavailableError, NotFoundError, ValidationError
from app.services import fulfillment_engine as engine
from app.services.integration_event_service import fan_out_business_event


# ---------------------------------------------------------------------------
# Stock reservation
# ---------------------------------------------------------------------------

def _reserve_stock(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    quantity: int,
    check_available: bool = True,
) -> None:
    """Reserve `quantity` units on a seller_offer. Race-safe: guarded by
    the conditional UPDATE under BEGIN IMMEDIATE."""
    if check_available:
        result = conn.execute(
            """
            UPDATE seller_offers
            SET stock_reserved = stock_reserved + ?,
                updated_at     = datetime('now')
            WHERE id = ?
              AND (stock_quantity - stock_reserved) >= ?
            """,
            (quantity, offer_id, quantity),
        )
        if result.rowcount != 1:
            raise ConflictError(
                "موجودی تأمین‌کننده تغییر کرد. لطفاً سفارش را مجدداً ثبت کنید.",
                code="supplier_stock_changed",
            )
    else:
        conn.execute(
            "UPDATE seller_offers SET stock_reserved = stock_reserved + ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (quantity, offer_id),
        )


def _consume_stock(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    quantity: int,
) -> None:
    """Convert a reservation into a final deduction."""
    conn.execute(
        """
        UPDATE seller_offers
        SET stock_quantity  = stock_quantity  - ?,
            stock_reserved  = stock_reserved  - ?,
            updated_at      = datetime('now')
        WHERE id = ?
        """,
        (quantity, quantity, offer_id),
    )


def _release_stock(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    quantity: int,
) -> None:
    """Release a reservation without consuming stock."""
    conn.execute(
        """
        UPDATE seller_offers
        SET stock_reserved = MAX(0, stock_reserved - ?),
            updated_at     = datetime('now')
        WHERE id = ?
        """,
        (quantity, offer_id),
    )


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def _transition(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    to_status: str,
    actor_type: str = "system",
    actor_user_id: int | None = None,
    reason: str | None = None,
    extra_updates: dict | None = None,
) -> None:
    """Apply a state transition. Validates against VALID_TRANSITIONS."""
    row = conn.execute(
        "SELECT status FROM fulfillment_orders WHERE id = ?",
        (fulfillment_order_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("سفارش تأمین یافت نشد", code="fulfillment_order_not_found")

    from_status = row["status"]
    allowed = engine.VALID_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ConflictError(
            f"انتقال از «{from_status}» به «{to_status}» مجاز نیست",
            code="invalid_fulfillment_transition",
        )

    # Timestamp columns per status
    ts_col = {
        "accepted":   "accepted_at",
        "preparing":  None,
        "ready":      "prepared_at",
        "dispatched": "dispatched_at",
        "delivered":  "delivered_at",
    }.get(to_status)

    set_clauses = ["status = ?", "updated_at = datetime('now')"]
    params: list[Any] = [to_status]

    if ts_col:
        set_clauses.append(f"{ts_col} = datetime('now')")

    if extra_updates:
        for col, val in extra_updates.items():
            set_clauses.append(f"{col} = ?")
            params.append(val)

    params.append(fulfillment_order_id)
    conn.execute(
        f"UPDATE fulfillment_orders SET {', '.join(set_clauses)} WHERE id = ?",
        params,
    )

    # Append to state log
    conn.execute(
        """
        INSERT INTO fulfillment_state_log
            (fulfillment_order_id, from_status, to_status, actor_type, actor_user_id, reason)
        VALUES (?,?,?,?,?,?)
        """,
        (fulfillment_order_id, from_status, to_status, actor_type, actor_user_id, reason),
    )
    _notify_customer(conn, fulfillment_order_id, to_status)


FO_NOTICE = {"dispatched": "مرسوله سفارش {n} ارسال شد", "delivered": "مرسوله سفارش {n} تحویل شد"}


def _notify_customer(conn: sqlite3.Connection, fulfillment_order_id: int, to_status: str) -> None:
    """Tell the customer when a shipment of their order leaves or arrives (in-app; same transaction)."""
    if to_status not in FO_NOTICE:
        return
    o = conn.execute("""SELECT o.user_id, o.order_number FROM fulfillment_orders fo JOIN orders o ON o.id = fo.order_id
                        WHERE fo.id = ?""", (fulfillment_order_id,)).fetchone()
    if o and o["user_id"]:
        from app.services.commerce_ops_service import notify
        notify(conn, o["user_id"], "order_status", FO_NOTICE[to_status].format(n=o["order_number"]), None,
               f"/orders/{o['order_number']}")


# ---------------------------------------------------------------------------
# Creating fulfillment orders
# ---------------------------------------------------------------------------

def create_fulfillment_orders(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    customer_province: str,
    customer_city: str,
    actor_user_id: int | None = None,
) -> list[int]:
    """Route all order items and create fulfillment orders.

    Returns a list of created fulfillment_order IDs.

    Algorithm:
      1. Fetch all order items.
      2. Group them by the best supplier/location from the routing engine.
      3. For each group, create one FulfillmentOrder + items + reserve stock.
      4. Write routing audit.

    Items for which no valid supplier is found are assigned to a special
    "failed" fulfillment order so they do not disappear.
    """
    items = conn.execute(
        """
        SELECT oi.id, oi.product_id, oi.title_fa, oi.quantity,
               oi.unit_price_minor, oi.line_total_minor
        FROM order_items oi WHERE oi.order_id = ?
        """,
        (order_id,),
    ).fetchall()

    if not items:
        return []

    # Route each item
    routing_results: dict[int, engine.RoutingResult] = {}
    for item in items:
        routing_results[int(item["product_id"])] = engine.route(
            conn,
            product_id        = int(item["product_id"]),
            quantity_needed   = int(item["quantity"]),
            customer_province = customer_province,
            customer_city     = customer_city,
        )

    # Group items by (supplier_id, location_id) → so one multi-item order to the
    # same supplier/location becomes a single FulfillmentOrder.
    groups: dict[tuple[int, int] | None, list] = {}
    for item in items:
        res = routing_results[int(item["product_id"])]
        if res.selected:
            key: tuple | None = (res.selected.supplier_id, res.selected.location_id)
        else:
            key = None  # unroutable
        groups.setdefault(key, []).append((item, res))

    created_ids = []
    for group_key, group_items in groups.items():
        if group_key is None:
            # Record routing exceptions without a fake FO FK
            _record_routing_exceptions(
                conn,
                order_id    = order_id,
                group_items = group_items,
            )
            continue

        supplier_id, location_id = group_key
        # All items in this group have the same selected candidate
        _item, sample_res = group_items[0]
        selected = sample_res.selected  # type: ignore

        # Compute gross payable (FOUNDATION ONLY — not settled)
        gross_payable = 0
        for item, res in group_items:
            s = res.selected
            if s and s.cost_price_minor is not None:
                gross_payable += s.cost_price_minor * int(item["quantity"])

        # Estimate promised prep time
        prep_minutes = selected.prep_time_minutes
        promised_prep_at = (
            datetime.now(timezone.utc) + timedelta(minutes=prep_minutes)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.execute(
            """
            INSERT INTO fulfillment_orders
                (order_id, supplier_id, supplier_location_id, status,
                 routing_score, routing_reason_json, routing_candidates_json,
                 fulfillment_type, gross_payable_minor, promised_prep_at, routing_history_json,
                 affiliate_bonus_bps)
            VALUES (?,?,?, 'assigned', ?,?,?, ?,?,?, '[]',
                    (SELECT COALESCE(affiliate_bonus_bps, 0) FROM suppliers WHERE id=?))
            """,
            (
                order_id, supplier_id, location_id,
                selected.total_score,
                sample_res.to_reason_json(),
                sample_res.to_audit_json(),
                selected.fulfillment_type,
                gross_payable,
                promised_prep_at, supplier_id,
            ),
        )
        fo_id = int(cursor.lastrowid)

        # Initial state log entry
        conn.execute(
            """
            INSERT INTO fulfillment_state_log
                (fulfillment_order_id, from_status, to_status, actor_type, actor_user_id, reason)
            VALUES (?, 'pending_assignment', 'assigned', 'system', ?, 'routing engine assigned')
            """,
            (fo_id, actor_user_id),
        )

        # Items + stock reservation
        for item, res in group_items:
            s = res.selected
            if s is None:
                continue  # shouldn't happen for this group
            line_selling = s.selling_price_minor * int(item["quantity"])
            line_cost    = (s.cost_price_minor * int(item["quantity"])) if s.cost_price_minor is not None else None

            conn.execute(
                """
                INSERT INTO fulfillment_order_items
                    (fulfillment_order_id, order_item_id, seller_offer_id, product_id,
                     title_fa, quantity, selling_price_minor, cost_price_minor,
                     line_selling_minor, line_cost_minor)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (fo_id, int(item["id"]), s.offer_id, int(item["product_id"]),
                 item["title_fa"], int(item["quantity"]),
                 s.selling_price_minor, s.cost_price_minor,
                 line_selling, line_cost),
            )

            _reserve_stock(conn, offer_id=s.offer_id, quantity=int(item["quantity"]))

        # Routing audit
        conn.execute(
            """
            INSERT INTO routing_audit
                (fulfillment_order_id, event_type, selected_supplier_id,
                 selected_supplier_location_id, candidates_json, reason, actor_type, actor_user_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (fo_id, "initial_routing", supplier_id, location_id,
             sample_res.to_audit_json(),
             f"اتوماتیک: سیاست={sample_res.policy_type}، geo={selected.geo_tier}",
             "system", actor_user_id),
        )

        created_ids.append(fo_id)

    return created_ids


def _record_routing_exceptions(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    group_items: list,
) -> None:
    """Persist unroutable items to routing_exceptions table (proper FK to orders).

    This replaces the old _create_failed_fulfillment_order hack which tried to
    insert into routing_audit with a fake fulfillment_order_id FK.  The
    routing_exceptions table is tied to the customer order, which always exists.
    """
    for item, res in group_items:
        # order_item_id may be available if item came from order_items JOIN
        order_item_id = item.get("id") if isinstance(item, dict) else None
        conn.execute(
            """
            INSERT INTO routing_exceptions
                (order_id, order_item_id, product_id, policy_type, reason, candidates_json)
            VALUES (?,?,?,?,?,?)
            """,
            (
                order_id,
                order_item_id,
                int(item["product_id"]),
                res.policy_type,
                res.unavailable_reason or "تأمین‌کننده‌ای یافت نشد",
                res.to_audit_json(),
            ),
        )


# ---------------------------------------------------------------------------
# Pre-payment fulfillment planning (Fulfillment-First checkout)
# ---------------------------------------------------------------------------

def plan_fulfillment(
    conn: sqlite3.Connection,
    *,
    cart_items: list[dict],
    customer_province: str,
    customer_city: str,
) -> dict:
    """Route all cart items and return a fulfillment plan.

    MUST be called BEFORE any PSP charge.  Raises FulfillmentUnavailableError
    if ANY item cannot be routed — this is a hard failure that prevents checkout.

    Returns a plan dict that can be serialised to payment_intents.fulfillment_plan_json.
    """
    plan_items = []
    for item in cart_items:
        res = engine.route(
            conn,
            product_id        = int(item["product_id"]),
            quantity_needed   = int(item["quantity"]),
            customer_province = customer_province,
            customer_city     = customer_city,
            offer_id          = item.get("offer_id"),
        )
        if not res.selected:
            raise FulfillmentUnavailableError(
                f"تأمین‌کننده‌ای برای «{item.get('title_fa', str(item['product_id']))}» "
                f"در منطقه شما یافت نشد: {res.unavailable_reason}",
                details={
                    "product_id":          int(item["product_id"]),
                    "reason":              res.unavailable_reason,
                    "policy_type":         res.policy_type,
                    "customer_province":   customer_province,
                    "customer_city":       customer_city,
                },
            )
        s = res.selected
        plan_items.append({
            "product_id":              int(item["product_id"]),
            "quantity":                int(item["quantity"]),
            "title_fa":                item.get("title_fa", ""),
            "offer_id":                s.offer_id,
            "supplier_id":             s.supplier_id,
            "location_id":             s.location_id,
            "selling_price_minor":     s.selling_price_minor,
            "cost_price_minor":        s.cost_price_minor,
            "geo_tier":                s.geo_tier,
            "total_score":             s.total_score,
            "policy_type":             res.policy_type,
            "fulfillment_type":        s.fulfillment_type,
            "prep_time_minutes":       s.prep_time_minutes,
            "routing_reason":          json.loads(res.to_reason_json()),
            "routing_candidates":      json.loads(res.to_audit_json()),
        })

    return {
        "customer_province": customer_province,
        "customer_city":     customer_city,
        "items":             plan_items,
    }


def reserve_supplier_stock_for_plan(
    conn: sqlite3.Connection,
    *,
    plan: dict,
) -> None:
    """Reserve supplier stock for each item in the plan (race-safe BEGIN IMMEDIATE).

    Called in the same transaction as inventory reservation and credit reservation
    — BEFORE the PSP call.  If any reservation fails, the whole transaction
    rolls back and no money moves.
    """
    for item in plan["items"]:
        _reserve_stock(conn, offer_id=item["offer_id"], quantity=item["quantity"])


def release_supplier_stock_for_plan(
    conn: sqlite3.Connection,
    *,
    plan_json: str | None,
) -> None:
    """Release all supplier-stock reservations from a stored plan.

    Called by _fail_attempt (PSP declined after plan was committed) and by
    stale-intent reclamation.  Safe to call with plan_json=None (no-op).
    """
    if not plan_json:
        return
    try:
        plan = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return
    for item in plan.get("items", []):
        try:
            _release_stock(conn, offer_id=int(item["offer_id"]), quantity=int(item["quantity"]))
        except Exception:
            # Best-effort: log but do not stop the compensation flow
            import logging
            logging.getLogger("70online").warning(
                "Could not release supplier stock for offer_id=%s qty=%s",
                item.get("offer_id"), item.get("quantity"), exc_info=True,
            )


def confirm_fulfillment_orders_from_plan(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    order_items: list[dict],
    plan: dict,
    actor_user_id: int | None = None,
) -> list[int]:
    """Create fulfillment orders from a pre-approved, pre-stock-reserved plan.

    Unlike create_fulfillment_orders (which re-routes and re-reserves), this
    function trusts the plan produced in phase 1 and does NOT reserve stock
    again (stock was already reserved before the PSP charge).

    Returns a list of created fulfillment_order IDs.
    """
    # Map product_id → order_item row
    product_to_oi: dict[int, dict] = {int(oi["product_id"]): oi for oi in order_items}

    # Group plan items by (supplier_id, location_id) — one FO per supplier location
    groups: dict[tuple[int, int], list[dict]] = {}
    for pi in plan["items"]:
        key = (int(pi["supplier_id"]), int(pi["location_id"]))
        groups.setdefault(key, []).append(pi)

    created_ids: list[int] = []
    for (supplier_id, location_id), group_items in groups.items():
        sample = group_items[0]

        gross_payable = sum(
            (int(pi.get("cost_price_minor") or 0)) * int(pi["quantity"])
            for pi in group_items
        )
        prep_minutes = int(sample.get("prep_time_minutes", 60))
        promised_prep_at = (
            datetime.now(timezone.utc) + timedelta(minutes=prep_minutes)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor = conn.execute(
            """
            INSERT INTO fulfillment_orders
                (order_id, supplier_id, supplier_location_id, status,
                 routing_score, routing_reason_json, routing_candidates_json,
                 fulfillment_type, gross_payable_minor, promised_prep_at, routing_history_json,
                 affiliate_bonus_bps)
            VALUES (?,?,?, 'assigned', ?,?,?, ?,?,?, '[]',
                    (SELECT COALESCE(affiliate_bonus_bps, 0) FROM suppliers WHERE id=?))
            """,
            (
                order_id, supplier_id, location_id,
                int(sample["total_score"]),
                json.dumps(sample.get("routing_reason", {}), ensure_ascii=False),
                json.dumps(sample.get("routing_candidates", []), ensure_ascii=False),
                sample.get("fulfillment_type", "delivery"),
                gross_payable,
                promised_prep_at, supplier_id,
            ),
        )
        fo_id = int(cursor.lastrowid)

        conn.execute(
            """
            INSERT INTO fulfillment_state_log
                (fulfillment_order_id, from_status, to_status, actor_type, actor_user_id, reason)
            VALUES (?, 'pending_assignment', 'assigned', 'system', ?, 'plan confirmed at checkout')
            """,
            (fo_id, actor_user_id),
        )

        for pi in group_items:
            oi = product_to_oi.get(int(pi["product_id"]))
            if oi is None:
                continue
            order_item_id = int(oi["id"])
            qty = int(pi["quantity"])
            sell = int(pi["selling_price_minor"])
            cost = int(pi["cost_price_minor"]) if pi.get("cost_price_minor") is not None else None
            conn.execute(
                """
                INSERT INTO fulfillment_order_items
                    (fulfillment_order_id, order_item_id, seller_offer_id, product_id,
                     title_fa, quantity, selling_price_minor, cost_price_minor,
                     line_selling_minor, line_cost_minor)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fo_id, order_item_id, int(pi["offer_id"]), int(pi["product_id"]),
                    pi.get("title_fa", ""), qty, sell, cost,
                    sell * qty,
                    (cost * qty) if cost is not None else None,
                ),
            )
            # NOTE: Stock is already reserved (done in _begin_attempt). Do NOT re-reserve.

        conn.execute(
            """
            INSERT INTO routing_audit
                (fulfillment_order_id, event_type, selected_supplier_id,
                 selected_supplier_location_id, candidates_json, reason, actor_type, actor_user_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                fo_id, "initial_routing", supplier_id, location_id,
                json.dumps(sample.get("routing_candidates", []), ensure_ascii=False),
                f"از برنامه تأیید شده: policy={sample.get('policy_type')}, geo={sample.get('geo_tier')}",
                "system", actor_user_id,
            ),
        )

        # Outbox: fan-out FULFILLMENT_CREATED to connectors belonging to the
        # fulfillment supplier so they can push the order to their ERP.
        fan_out_business_event(
            conn,
            event_type="FULFILLMENT_CREATED",
            supplier_id=supplier_id,
            payload={
                "fulfillment_order_id": fo_id,
                "order_id": order_id,
                "supplier_id": supplier_id,
                "status": "assigned",
            },
            base_idempotency_key=f"fulfillment_created:{fo_id}",
        )

        created_ids.append(fo_id)

    return created_ids


# ---------------------------------------------------------------------------
# Supplier actions
# ---------------------------------------------------------------------------

def supplier_accept(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int,
    actor_user_id: int | None = None,
) -> None:
    """Supplier accepts an assigned fulfillment order."""
    _assert_supplier_owns(conn, fulfillment_order_id, supplier_id)
    _transition(
        conn, fulfillment_order_id=fulfillment_order_id, to_status="accepted",
        actor_type="supplier", actor_user_id=actor_user_id,
        reason="تأمین‌کننده پذیرفت",
    )


def supplier_reject(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int,
    reason: str,
    actor_user_id: int | None = None,
    db=None,
) -> None:
    """Supplier rejects. Triggers fallback routing."""
    _assert_supplier_owns(conn, fulfillment_order_id, supplier_id)

    fo = conn.execute(
        "SELECT order_id, supplier_location_id FROM fulfillment_orders WHERE id = ?",
        (fulfillment_order_id,),
    ).fetchone()
    order_id    = int(fo["order_id"])
    location_id = int(fo["supplier_location_id"])

    # Release stock reserved for this FO's items
    items = conn.execute(
        "SELECT seller_offer_id, quantity FROM fulfillment_order_items WHERE fulfillment_order_id = ?",
        (fulfillment_order_id,),
    ).fetchall()
    for it in items:
        _release_stock(conn, offer_id=int(it["seller_offer_id"]), quantity=int(it["quantity"]))

    _transition(
        conn, fulfillment_order_id=fulfillment_order_id, to_status="rejected",
        actor_type="supplier", actor_user_id=actor_user_id,
        reason=reason,
        extra_updates={"rejection_reason": reason},
    )

    # Append to routing history
    _append_routing_history(
        conn, fulfillment_order_id,
        {"event": "rejected", "supplier_id": supplier_id, "reason": reason},
    )

    # Attempt fallback routing
    _attempt_fallback(
        conn,
        original_fo_id    = fulfillment_order_id,
        order_id          = order_id,
        excluded_location = location_id,
        actor_user_id     = actor_user_id,
    )


def supplier_start_preparing(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int,
    actor_user_id: int | None = None,
) -> None:
    _assert_supplier_owns(conn, fulfillment_order_id, supplier_id)
    _transition(
        conn, fulfillment_order_id=fulfillment_order_id, to_status="preparing",
        actor_type="supplier", actor_user_id=actor_user_id,
        reason="شروع آماده‌سازی",
    )


def supplier_mark_ready(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int,
    actor_user_id: int | None = None,
) -> None:
    _assert_supplier_owns(conn, fulfillment_order_id, supplier_id)
    _transition(
        conn, fulfillment_order_id=fulfillment_order_id, to_status="ready",
        actor_type="supplier", actor_user_id=actor_user_id,
        reason="آماده تحویل",
    )


def supplier_mark_dispatched(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int,
    actor_user_id: int | None = None,
) -> None:
    _assert_supplier_owns(conn, fulfillment_order_id, supplier_id)
    _transition(
        conn, fulfillment_order_id=fulfillment_order_id, to_status="dispatched",
        actor_type="supplier", actor_user_id=actor_user_id,
        reason="ارسال شد",
    )

    # Consume supplier stock (reservation → permanent deduction)
    items = conn.execute(
        "SELECT seller_offer_id, quantity FROM fulfillment_order_items WHERE fulfillment_order_id = ?",
        (fulfillment_order_id,),
    ).fetchall()
    for it in items:
        _consume_stock(conn, offer_id=int(it["seller_offer_id"]), quantity=int(it["quantity"]))


def supplier_mark_delivered(
    conn: sqlite3.Connection,
    *,
    fulfillment_order_id: int,
    supplier_id: int | None = None,
    actor_user_id: int | None = None,
    actor_type: str = "supplier",
) -> None:
    """Mark delivered. Supplier_id=None allows admin to mark.

    Stock consumption depends on the preceding state:
      - dispatched → delivered (delivery path): stock was already consumed at dispatch.
      - ready → delivered (pickup path): stock must be consumed now.

    BLOCKER 6: After successful delivery, record supplier payable from the
    IMMUTABLE fulfillment_order_items snapshot.  Called inside the same
    write transaction so the delivery + payable are atomic.
    """
    if supplier_id is not None:
        _assert_supplier_owns(conn, fulfillment_order_id, supplier_id)

    # Read from_status and supplier_id BEFORE the transition.
    fo_row = conn.execute(
        "SELECT status, supplier_id FROM fulfillment_orders WHERE id = ?",
        (fulfillment_order_id,),
    ).fetchone()
    from_status = fo_row["status"] if fo_row else None
    actual_supplier_id = int(fo_row["supplier_id"]) if fo_row else supplier_id

    _transition(
        conn, fulfillment_order_id=fulfillment_order_id, to_status="delivered",
        actor_type=actor_type, actor_user_id=actor_user_id,
        reason="تحویل داده شد",
    )

    # Pickup path: ready → delivered (stock was NOT consumed at any prior step).
    # Delivery path: dispatched → delivered (stock was already consumed at dispatch).
    if from_status == "ready":
        items = conn.execute(
            "SELECT seller_offer_id, quantity FROM fulfillment_order_items "
            "WHERE fulfillment_order_id = ?",
            (fulfillment_order_id,),
        ).fetchall()
        for it in items:
            _consume_stock(conn, offer_id=int(it["seller_offer_id"]), quantity=int(it["quantity"]))

    # BLOCKER 6: Record supplier payable from immutable snapshot.
    # This is the ONLY place payable is created — NOT at payment time.
    # Supplier A who was rejected does NOT get payable.
    # Only the supplier who ACTUALLY delivered this FO earns payable.
    #
    # ATOMICITY REQUIREMENT: payable creation and delivered status are in
    # the SAME database transaction (same `conn`).  If record_sale_payable
    # raises, the entire write transaction rolls back — the FO is NOT
    # committed as delivered.  Do NOT swallow the exception here.
    if actual_supplier_id is not None:
        from app.services import supplier_ledger_service  # avoid circular import at module level
        supplier_ledger_service.record_sale_payable(
            conn,
            fulfillment_order_id=fulfillment_order_id,
            supplier_id=actual_supplier_id,
        )


# ---------------------------------------------------------------------------
# Fallback routing
# ---------------------------------------------------------------------------

def _attempt_fallback(
    conn: sqlite3.Connection,
    *,
    original_fo_id: int,
    order_id: int,
    excluded_location: int,
    actor_user_id: int | None,
) -> None:
    """Try to re-route rejected items to another supplier. If found, create
    a new FulfillmentOrder and record the fallback in routing_audit."""
    # Get rejected FO items
    items = conn.execute(
        """
        SELECT foi.product_id, foi.title_fa, foi.quantity, foi.order_item_id,
               oi.unit_price_minor, oi.line_total_minor
        FROM fulfillment_order_items foi
        JOIN order_items oi ON oi.id = foi.order_item_id
        WHERE foi.fulfillment_order_id = ?
        """,
        (original_fo_id,),
    ).fetchall()

    # Get customer delivery address from the parent order
    order_row = conn.execute(
        "SELECT shipping_province, shipping_city FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if not order_row:
        return

    customer_province = order_row["shipping_province"]
    customer_city     = order_row["shipping_city"]

    for item in items:
        res = engine.route(
            conn,
            product_id        = int(item["product_id"]),
            quantity_needed   = int(item["quantity"]),
            customer_province = customer_province,
            customer_city     = customer_city,
        )

        # Exclude the previously rejected location
        eligible = [c for c in res.candidates if c.eligible and c.location_id != excluded_location]

        if not eligible:
            # Mark routing exception in audit
            conn.execute(
                """
                INSERT INTO routing_audit
                    (fulfillment_order_id, event_type, candidates_json, reason, actor_type, actor_user_id)
                VALUES (?,?,?,?,?,?)
                """,
                (original_fo_id, "exception", res.to_audit_json(),
                 f"بازتوزیع ناموفق: محصول {item['product_id']}",
                 "system", actor_user_id),
            )
            continue

        new_selected = eligible[0]
        # Create new FO
        cursor = conn.execute(
            """
            INSERT INTO fulfillment_orders
                (order_id, supplier_id, supplier_location_id, status,
                 routing_score, routing_reason_json, routing_candidates_json,
                 fulfillment_type, gross_payable_minor,
                 routing_history_json)
            VALUES (?,?,?, 'assigned', ?,?,?, ?,?,
                    ?)
            """,
            (
                order_id, new_selected.supplier_id, new_selected.location_id,
                new_selected.total_score,
                res.to_reason_json(), res.to_audit_json(),
                new_selected.fulfillment_type,
                (new_selected.cost_price_minor or 0) * int(item["quantity"]),
                json.dumps([{
                    "event": "rerouted_from",
                    "original_fo_id": original_fo_id,
                    "excluded_location": excluded_location,
                }], ensure_ascii=False),
            ),
        )
        new_fo_id = int(cursor.lastrowid)

        conn.execute(
            "INSERT INTO fulfillment_state_log "
            "(fulfillment_order_id, from_status, to_status, actor_type, actor_user_id, reason) "
            "VALUES (?, 'pending_assignment', 'assigned', 'system', ?, ?)",
            (new_fo_id, actor_user_id, f"بازتوزیع پس از رد شدن توسط سفارش {original_fo_id}"),
        )

        conn.execute(
            """
            INSERT INTO fulfillment_order_items
                (fulfillment_order_id, order_item_id, seller_offer_id, product_id,
                 title_fa, quantity, selling_price_minor, cost_price_minor,
                 line_selling_minor, line_cost_minor)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_fo_id, int(item["order_item_id"]), new_selected.offer_id, int(item["product_id"]),
                item["title_fa"], int(item["quantity"]),
                new_selected.selling_price_minor, new_selected.cost_price_minor,
                new_selected.selling_price_minor * int(item["quantity"]),
                (new_selected.cost_price_minor * int(item["quantity"])) if new_selected.cost_price_minor else None,
            ),
        )
        _reserve_stock(conn, offer_id=new_selected.offer_id, quantity=int(item["quantity"]))

        conn.execute(
            """
            INSERT INTO routing_audit
                (fulfillment_order_id, event_type, selected_supplier_id,
                 selected_supplier_location_id, candidates_json, reason, actor_type, actor_user_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (new_fo_id, "fallback", new_selected.supplier_id, new_selected.location_id,
             res.to_audit_json(),
             f"بازتوزیع از سفارش {original_fo_id}",
             "system", actor_user_id),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_supplier_owns(
    conn: sqlite3.Connection,
    fulfillment_order_id: int,
    supplier_id: int,
) -> None:
    row = conn.execute(
        "SELECT 1 FROM fulfillment_orders WHERE id = ? AND supplier_id = ?",
        (fulfillment_order_id, supplier_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("سفارش تأمین یافت نشد", code="fulfillment_order_not_found")


def _append_routing_history(
    conn: sqlite3.Connection,
    fulfillment_order_id: int,
    event: dict,
) -> None:
    row = conn.execute(
        "SELECT routing_history_json FROM fulfillment_orders WHERE id = ?",
        (fulfillment_order_id,),
    ).fetchone()
    history = json.loads(row["routing_history_json"] or "[]")
    event["ts"] = datetime.now(timezone.utc).isoformat()
    history.append(event)
    conn.execute(
        "UPDATE fulfillment_orders SET routing_history_json = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(history, ensure_ascii=False), fulfillment_order_id),
    )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def read_fulfillment_order(conn: sqlite3.Connection, *, fo_id: int) -> dict:
    row = conn.execute(
        """
        SELECT fo.*, s.display_name AS supplier_name, s.supplier_type,
               sl.province, sl.city, sl.address
        FROM fulfillment_orders fo
        JOIN suppliers            s  ON s.id  = fo.supplier_id
        JOIN supplier_locations   sl ON sl.id = fo.supplier_location_id
        WHERE fo.id = ?
        """,
        (fo_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("سفارش تأمین یافت نشد")
    items = conn.execute(
        "SELECT * FROM fulfillment_order_items WHERE fulfillment_order_id = ?",
        (fo_id,),
    ).fetchall()
    d = dict(row)
    d["items"] = [dict(i) for i in items]
    return d


def list_fulfillment_orders_for_supplier(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    sql = """
        SELECT fo.*, o.order_number, o.shipping_city, o.shipping_province,
               o.total_minor, o.currency,
               s.display_name AS supplier_name
        FROM fulfillment_orders fo
        JOIN orders   o ON o.id = fo.order_id
        JOIN suppliers s ON s.id = fo.supplier_id
        WHERE fo.supplier_id = ?
    """
    params: list = [supplier_id]
    if status:
        sql += " AND fo.status = ?"
        params.append(status)
    sql += " ORDER BY fo.created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_fulfillment_orders_for_order(
    conn: sqlite3.Connection,
    *,
    order_id: int,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT fo.*, s.display_name AS supplier_name, sl.city, sl.province
        FROM fulfillment_orders fo
        JOIN suppliers          s  ON s.id  = fo.supplier_id
        JOIN supplier_locations sl ON sl.id = fo.supplier_location_id
        WHERE fo.order_id = ?
        ORDER BY fo.created_at ASC
        """,
        (order_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_supplier_for_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    from app.services.access_admin_service import current_supplier_id
    sid = current_supplier_id(conn, user_id)
    row = conn.execute("SELECT * FROM suppliers WHERE id = ? AND status = 'active'", (sid,)).fetchone() if sid else None
    return dict(row) if row else None
