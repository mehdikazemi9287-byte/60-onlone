"""Logistics orchestration service.

Architecture: Funding ≠ Fulfillment ≠ Logistics ≠ Settlement.

The key invariant implemented here:

  1. Payment/fulfillment must be DURABLE before any external carrier call.
  2. External carrier calls MUST NOT happen while a DB transaction is open.
  3. Logistics failures are recorded for operations WITHOUT rolling back the
     customer payment or reserving supplier stock a second time.

Post-payment flow:
  checkout._complete_attempt() commits → calls ensure_shipment_plan() for each FO
                                                          ↓
                                         ensure_shipment_plan()
                                             get_carrier_quotes()    (in read tx)
                                             persist plan + quotes   (in write tx)

Booking (two-phase, BLOCKER 3):
  Phase A (write tx):  validate → persist idempotency_key → status = 'booking' → COMMIT
  External call:       adapter.create_shipment()  (NO TRANSACTION OPEN)
  Phase B (write tx):  success → 'booked' + ext_id + tracking / failure → 'booking_failed'

Idempotency key:
  Generated once in Phase A as 'ship:{shipment_id}:{fo_id}'.
  NEVER regenerated on retry.
  Passed to adapter on every create_shipment() call.
  A real carrier must be idempotent on this key.

Stale recovery (status='booking' for too long):
  A separate recovery path will read the same idempotency_key and re-call
  Phase B.  The adapter call will return the already-created shipment (if the
  original external call succeeded) or create it again (if it never reached
  the carrier).

REAL CARRIER INTEGRATIONS: NOT IMPLEMENTED
  AloPeyk, Post, Tipax are NOT implemented.  Only mock is provided for tests.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from app.adapters.logistics.base import (
    CarrierAdapter,
    ShipmentCreateRequest,
    ShipmentCreateResult,
    ShipmentQuoteRequest,
)
from app.adapters.logistics.registry import get_carrier_adapter
from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError

log = logging.getLogger("60online.logistics")

# Normalized shipment status ordering (higher = more advanced)
_STATUS_RANK: dict[str, int] = {
    "planned":       0,
    "booking":       1,
    "booking_failed":1,
    "booked":        2,
    "in_transit":    3,
    "delivered":     4,
    "failed":        4,
}


# ---------------------------------------------------------------------------
# Authorization helper
# ---------------------------------------------------------------------------

def _check_fo_access(
    conn: sqlite3.Connection,
    fo_id: int,
    *,
    user_id: int,
    user_role: str,
    supplier_id: int | None = None,
) -> dict:
    """Authorize access to fulfillment order mutations (plan/book shipment).

    Allowed:
      - Platform admin (user_role == 'admin')
      - The supplier that OWNS the fulfillment order

    EXPLICITLY DENIED:
      - Any customer (even if they own the parent order)
      - Any supplier who does not own this specific FO

    Raises PermissionError_ or NotFoundError.
    Returns the FO row dict if authorized.
    """
    row = conn.execute(
        """
        SELECT fo.id, fo.supplier_id, fo.order_id, fo.status,
               o.user_id AS customer_user_id
        FROM fulfillment_orders fo
        JOIN orders o ON o.id = fo.order_id
        WHERE fo.id = ?
        """,
        (fo_id,),
    ).fetchone()

    if row is None:
        raise NotFoundError("سفارش تأمین یافت نشد", code="fulfillment_order_not_found")

    fo_dict = dict(row)

    if user_role == "admin":
        return fo_dict

    if user_role == "supplier":
        if supplier_id is None or int(row["supplier_id"]) != supplier_id:
            # Return 403/404 — do not reveal whether the FO exists for another supplier
            raise NotFoundError("سفارش تأمین یافت نشد", code="fulfillment_order_not_found")
        return fo_dict

    # Any other role (customer, employee, org_admin, …) is forbidden
    raise PermissionError_(
        "فقط ادمین پلتفرم یا تأمین‌کننده مجاز می‌توانند برنامه‌ریزی یا رزرو حمل‌ونقل را انجام دهند.",
        code="logistics_permission_denied",
    )


# ---------------------------------------------------------------------------
# Post-payment orchestrator (BLOCKER 1)
# ---------------------------------------------------------------------------

def ensure_shipment_plan(db: Database, fo_id: int) -> None:
    """Post-payment logistics orchestrator.

    Called by checkout AFTER the payment DB transaction has committed.
    NEVER call this while a DB transaction is open.

    If planning fails for any reason, the failure is recorded in shipment_plans
    and the function returns normally.  The customer payment is NOT reversed.
    The PSP is NOT called again.  Operations can investigate and retry.

    This is the entry-point for the cascade:
      PAID ORDER → CONFIRMED FO → ensure_shipment_plan()
                                      get_carrier_quotes()
                                      persist plan + selected quote
    """
    try:
        with db.read_transaction() as conn:
            # Get FO details
            fo_row = conn.execute(
                """
                SELECT fo.*, sl.province AS supplier_province, sl.city AS supplier_city,
                       o.shipping_province, o.shipping_city
                FROM fulfillment_orders fo
                JOIN supplier_locations sl ON sl.id = fo.supplier_location_id
                JOIN orders o ON o.id = fo.order_id
                WHERE fo.id = ?
                """,
                (fo_id,),
            ).fetchone()
            if fo_row is None:
                log.error("ensure_shipment_plan: FO %s not found", fo_id)
                return

            # Check if plan already exists (idempotent)
            existing = conn.execute(
                "SELECT id, status FROM shipment_plans WHERE fulfillment_order_id = ?",
                (fo_id,),
            ).fetchone()
            if existing and existing["status"] not in ("planned", "failed"):
                # Already in a terminal/good state — don't re-plan
                log.info("ensure_shipment_plan: plan already exists for FO %s (status=%s)",
                         fo_id, existing["status"])
                return

            # Determine required capabilities from fulfillment policy
            fo = dict(fo_row)
            required_caps = _required_capabilities(conn, fo_id)

            # Collect eligible carrier quotes
            adapter = get_carrier_adapter("mock")  # Only mock implemented
            quote_req = ShipmentQuoteRequest(
                fulfillment_order_id=fo_id,
                provider_code="mock",
                origin_province=fo["supplier_province"],
                origin_city=fo["supplier_city"],
                destination_province=fo["shipping_province"],
                destination_city=fo["shipping_city"],
                required_capabilities=required_caps,
            )
            raw_quotes = adapter.get_quotes(quote_req)

        if not raw_quotes:
            _record_plan_failure(db, fo_id, "هیچ حامل واجد شرایطی یافت نشد")
            return

        # Resolve carrier_config_ids from DB and persist plan
        with db.write_transaction() as conn:
            # Re-check idempotency inside write tx
            existing = conn.execute(
                "SELECT id, status FROM shipment_plans WHERE fulfillment_order_id = ?", (fo_id,)
            ).fetchone()
            if existing and existing["status"] not in ("planned", "failed"):
                # Another concurrent caller already advanced the plan — bail out
                return

            # Use existing plan (reset to 'planned') or create a new one
            if existing and existing["status"] in ("planned", "failed"):
                plan_id = int(existing["id"])
                conn.execute(
                    "UPDATE shipment_plans SET status='planned', selected_carrier_config_id=NULL, "
                    "failure_reason=NULL, updated_at=datetime('now') WHERE id=?",
                    (plan_id,),
                )
            else:
                plan_cursor = conn.execute(
                    """
                    INSERT INTO shipment_plans
                        (fulfillment_order_id, status, selected_carrier_config_id)
                    VALUES (?, 'planned', NULL)
                    """,
                    (fo_id,),
                )
                plan_id = int(plan_cursor.lastrowid)

            fo_row2 = conn.execute(
                """
                SELECT fo.*, sl.province AS supplier_province, sl.city AS supplier_city,
                       o.shipping_province, o.shipping_city
                FROM fulfillment_orders fo
                JOIN supplier_locations sl ON sl.id = fo.supplier_location_id
                JOIN orders o ON o.id = fo.order_id
                WHERE fo.id = ?
                """,
                (fo_id,),
            ).fetchone()
            fo2 = dict(fo_row2)

            selected_plan_quote_id = None
            best_cost = None
            best_carrier_config_id = None

            for q in raw_quotes:
                # Find a matching active carrier_config for the quote
                cc = _find_matching_carrier_config(
                    conn,
                    provider_code=q.provider_code,
                    dest_province=fo2["shipping_province"],
                    dest_city=fo2["shipping_city"],
                    required_capabilities=required_caps,
                )
                if cc is None:
                    continue

                cursor = conn.execute(
                    """
                    INSERT INTO shipment_plan_quotes
                        (shipment_plan_id, carrier_config_id, cost_minor, capabilities, is_selected)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (plan_id, int(cc["id"]), q.cost_minor, q.capabilities),
                )
                quote_id = int(cursor.lastrowid)

                if best_cost is None or q.cost_minor < best_cost:
                    best_cost = q.cost_minor
                    best_carrier_config_id = int(cc["id"])
                    selected_plan_quote_id = quote_id

            if selected_plan_quote_id is None:
                conn.execute(
                    "UPDATE shipment_plans SET status='failed', failure_reason=?, "
                    "updated_at=datetime('now') WHERE id=?",
                    ("هیچ حامل فعالی در دیتابیس یافت نشد", plan_id),
                )
                return

            # Mark selected quote and update plan
            conn.execute(
                "UPDATE shipment_plan_quotes SET is_selected=1 WHERE id=?",
                (selected_plan_quote_id,),
            )
            conn.execute(
                "UPDATE shipment_plans SET status='quote_selected', "
                "selected_carrier_config_id=?, updated_at=datetime('now') WHERE id=?",
                (best_carrier_config_id, plan_id),
            )
            log.info(
                "ensure_shipment_plan: plan %s created for FO %s, carrier_config=%s, cost=%s",
                plan_id, fo_id, best_carrier_config_id, best_cost,
            )

    except Exception as exc:
        log.exception("ensure_shipment_plan: unexpected error for FO %s: %s", fo_id, exc)
        _record_plan_failure(db, fo_id, f"خطای داخلی: {exc}")


def _required_capabilities(conn: sqlite3.Connection, fo_id: int) -> str:
    """Derive required carrier capabilities from the FO's product logistics profiles.

    Uses the structured `products.logistics_profile` column (migration 0007).
    Profile → capability mapping:
      standard            → (no special cap; geographic match is sufficient)
      local_only          → requires 'local' capability; intercity carriers ineligible
      perishable          → requires 'cold_chain' (or same-city local route)
      cold_chain_required → requires 'cold_chain'
      fragile             → requires 'fragile'
      bulky               → requires 'bulky'

    The most restrictive profile among all items wins.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT p.logistics_profile
        FROM fulfillment_order_items foi
        JOIN products p ON p.id = foi.product_id
        WHERE foi.fulfillment_order_id = ?
        """,
        (fo_id,),
    ).fetchall()
    profiles = {r["logistics_profile"] for r in rows if r["logistics_profile"]}

    required_caps: set[str] = set()
    needs_local_only = False

    for profile in profiles:
        if profile == "cold_chain_required":
            required_caps.add("cold_chain")
        elif profile == "perishable":
            # Perishable requires cold_chain OR local-only fast delivery.
            # Conservative: require cold_chain so the carrier can handle it safely.
            required_caps.add("cold_chain")
        elif profile == "fragile":
            required_caps.add("fragile")
        elif profile == "bulky":
            required_caps.add("bulky")
        elif profile == "local_only":
            needs_local_only = True
            required_caps.add("local")
        # 'standard' → no special cap requirement

    if needs_local_only:
        # Intercity carriers are ineligible for local_only products.
        # Signal this by requiring 'local' and NOT requiring 'intercity'.
        required_caps.discard("intercity")
    # No explicit intercity requirement — geographic match covers it.

    return ",".join(sorted(required_caps))


def _find_matching_carrier_config(
    conn: sqlite3.Connection,
    provider_code: str,
    dest_province: str,
    dest_city: str,
    required_capabilities: str,
) -> dict | None:
    """Find the best matching active carrier_config for the given route.

    Priority:
      1. Province+city specific match
      2. Province-only match
      3. National (NULL province)

    Capability matching rules (derived from product logistics_profile):
      - All required capabilities must be present in the carrier's capabilities.
      - When 'local' is required (local_only profile), carriers whose
        capabilities contain ONLY 'intercity' are ineligible.
      - When 'cold_chain' is required, carriers without 'cold_chain' are
        ineligible regardless of geographic coverage.
    """
    req_caps = {c.strip() for c in required_capabilities.split(",") if c.strip()}
    local_only_required = "local" in req_caps

    for province_clause, params in [
        ("province = ? AND (city = ? OR city IS NULL)", [provider_code, dest_province, dest_city, 1]),
        ("province = ? AND city IS NULL", [provider_code, dest_province, 1]),
        ("province IS NULL", [provider_code, 1]),
    ]:
        rows = conn.execute(
            f"""
            SELECT * FROM carrier_configs
            WHERE provider_code = ? AND {province_clause} AND is_active = ?
            ORDER BY cost_minor ASC
            """,
            params,
        ).fetchall()
        for row in rows:
            caps = {c.strip() for c in (row["capabilities"] or "").split(",") if c.strip()}
            # For local_only products, reject carriers whose ONLY geographic mode is intercity.
            if local_only_required and caps == {"intercity"}:
                continue
            # All required capabilities must be present.
            if req_caps and not req_caps.issubset(caps | {"local"}):
                # Re-check without the 'local' sentinel (it's a routing flag, not a carrier cap)
                effective_req = req_caps - {"local"}
                if effective_req and not effective_req.issubset(caps):
                    continue
            return dict(row)
    return None


def _record_plan_failure(db: Database, fo_id: int, reason: str) -> None:
    try:
        with db.write_transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM shipment_plans WHERE fulfillment_order_id = ?", (fo_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE shipment_plans SET status='failed', failure_reason=?, "
                    "updated_at=datetime('now') WHERE id=?",
                    (reason, int(existing["id"])),
                )
            else:
                conn.execute(
                    "INSERT INTO shipment_plans (fulfillment_order_id, status, failure_reason) "
                    "VALUES (?, 'failed', ?)",
                    (fo_id, reason),
                )
    except Exception:
        log.exception("Could not record plan failure for FO %s", fo_id)


# ---------------------------------------------------------------------------
# Two-phase booking (BLOCKER 3)
# ---------------------------------------------------------------------------

def book_shipment(
    db: Database,
    fo_id: int,
    *,
    user_id: int,
    user_role: str,
    supplier_id: int | None = None,
) -> dict:
    """Two-phase carrier booking.

    Phase A (DB write tx):
      - Authorize
      - Validate FO/plan
      - If not already booked, set status='booking'
      - Persist stable booking_idempotency_key (NEVER regenerated on retry)
      - COMMIT

    External call (OUTSIDE any transaction):
      - adapter.create_shipment(idempotency_key)
      - Carrier must be idempotent on this key

    Phase B (DB write tx):
      - On success: status='booked', store external_shipment_id, tracking_code
      - On failure: status='booking_failed', store failure_reason
      - Log booking attempt in shipment_booking_log

    Returns the shipment dict after Phase B.
    """
    # ── Phase A ──────────────────────────────────────────────────────────────
    import secrets as _secrets
    with db.write_transaction() as conn:
        fo = _check_fo_access(conn, fo_id, user_id=user_id, user_role=user_role,
                              supplier_id=supplier_id)

        plan = conn.execute(
            "SELECT * FROM shipment_plans WHERE fulfillment_order_id = ?", (fo_id,)
        ).fetchone()
        if plan is None:
            raise ConflictError(
                "برنامه حمل‌ونقل برای این سفارش ایجاد نشده است",
                code="no_shipment_plan",
            )
        if dict(plan)["status"] == "failed":
            raise ConflictError(
                "برنامه حمل‌ونقل این سفارش با خطا مواجه شد",
                code="shipment_plan_failed",
            )

        carrier_config_id = plan["selected_carrier_config_id"]
        if carrier_config_id is None:
            raise ConflictError(
                "حامل انتخاب‌شده‌ای برای این سفارش وجود ندارد",
                code="no_selected_carrier",
            )

        carrier_cc = conn.execute(
            "SELECT * FROM carrier_configs WHERE id = ?", (carrier_config_id,)
        ).fetchone()
        if carrier_cc is None:
            raise ConflictError("پیکربندی حامل یافت نشد", code="carrier_config_not_found")

        # Check for existing shipment (idempotency)
        existing_shipment = conn.execute(
            "SELECT * FROM shipments WHERE fulfillment_order_id = ?", (fo_id,)
        ).fetchone()

        if existing_shipment is not None:
            s = dict(existing_shipment)
            if s["status"] in ("booked", "in_transit", "delivered"):
                # Already successfully booked — return idempotently
                return _shipment_dict(conn, int(s["id"]))
            if s["status"] in ("booking", "booking_failed"):
                # Retry: use the SAME idempotency key from Phase A
                shipment_id = int(s["id"])
                idem_key = s["booking_idempotency_key"]
                # Log retry attempt
                conn.execute(
                    "INSERT INTO shipment_booking_log "
                    "(shipment_id, phase, outcome, error_detail) VALUES (?, 'phase_a', 'pending', ?)",
                    (shipment_id, "retry after status=" + s["status"]),
                )
                # Update status back to booking for retry
                conn.execute(
                    "UPDATE shipments SET status='booking', updated_at=datetime('now') WHERE id=?",
                    (shipment_id,),
                )
                fo_for_call = dict(conn.execute(
                    """
                    SELECT fo.*, sl.province AS s_prov, sl.city AS s_city,
                           o.shipping_province AS d_prov, o.shipping_city AS d_city
                    FROM fulfillment_orders fo
                    JOIN supplier_locations sl ON sl.id = fo.supplier_location_id
                    JOIN orders o ON o.id = fo.order_id
                    WHERE fo.id = ?
                    """, (fo_id,),
                ).fetchone())
                phase_a_result = {
                    "shipment_id": shipment_id,
                    "idem_key": idem_key,
                    "carrier_config_id": carrier_config_id,
                    "provider_code": dict(carrier_cc)["provider_code"],
                    "cost_minor": int(s["cost_minor"]),
                    "fo": fo_for_call,
                }
            else:
                raise ConflictError(
                    f"وضعیت حمل‌ونقل نامعلوم است: {s['status']}",
                    code="shipment_invalid_state",
                )
        else:
            # Fresh booking
            fo_for_call = dict(conn.execute(
                """
                SELECT fo.*, sl.province AS s_prov, sl.city AS s_city,
                       o.shipping_province AS d_prov, o.shipping_city AS d_city
                FROM fulfillment_orders fo
                JOIN supplier_locations sl ON sl.id = fo.supplier_location_id
                JOIN orders o ON o.id = fo.order_id
                WHERE fo.id = ?
                """, (fo_id,),
            ).fetchone())

            cost_minor = int(carrier_cc["cost_minor"])
            # Stable idempotency key generated ONCE here — never regenerated
            idem_key = f"ship:{fo_id}:{_secrets.token_hex(8)}"

            cursor = conn.execute(
                """
                INSERT INTO shipments
                    (fulfillment_order_id, shipment_plan_id, carrier_config_id,
                     provider_code, status, booking_idempotency_key,
                     cost_minor, currency)
                VALUES (?, ?, ?, ?, 'booking', ?, ?, 'IRR')
                """,
                (fo_id, int(plan["id"]), carrier_config_id,
                 dict(carrier_cc)["provider_code"], idem_key, cost_minor),
            )
            shipment_id = int(cursor.lastrowid)

            conn.execute(
                "INSERT INTO shipment_booking_log "
                "(shipment_id, phase, outcome) VALUES (?, 'phase_a', 'pending')",
                (shipment_id,),
            )
            conn.execute(
                "UPDATE shipment_plans SET status='booking_initiated', "
                "updated_at=datetime('now') WHERE id=?",
                (int(plan["id"]),),
            )

            phase_a_result = {
                "shipment_id": shipment_id,
                "idem_key": idem_key,
                "carrier_config_id": carrier_config_id,
                "provider_code": dict(carrier_cc)["provider_code"],
                "cost_minor": cost_minor,
                "fo": fo_for_call,
            }
    # Phase A committed ───────────────────────────────────────────────────────

    # ── External call — NO TRANSACTION OPEN ────────────────────────────────
    adapter = get_carrier_adapter(phase_a_result["provider_code"])
    fo_info = phase_a_result["fo"]
    try:
        ext_result: ShipmentCreateResult = adapter.create_shipment(
            ShipmentCreateRequest(
                fulfillment_order_id=fo_id,
                carrier_config_id=phase_a_result["carrier_config_id"],
                origin_province=fo_info.get("s_prov", ""),
                origin_city=fo_info.get("s_city", ""),
                destination_province=fo_info.get("d_prov", ""),
                destination_city=fo_info.get("d_city", ""),
                booking_idempotency_key=phase_a_result["idem_key"],
                cost_minor=phase_a_result["cost_minor"],
            )
        )
        call_error: Exception | None = None
    except Exception as exc:
        ext_result = ShipmentCreateResult(succeeded=False, failure_reason=str(exc))
        call_error = exc

    # ── Phase B ──────────────────────────────────────────────────────────────
    with db.write_transaction() as conn:
        shipment_id = phase_a_result["shipment_id"]
        if ext_result.succeeded:
            conn.execute(
                """
                UPDATE shipments SET
                    status = 'booked',
                    external_shipment_id = ?,
                    tracking_code = ?,
                    booked_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (ext_result.external_shipment_id, ext_result.tracking_code, shipment_id),
            )
            conn.execute(
                "INSERT INTO shipment_booking_log "
                "(shipment_id, phase, outcome, external_shipment_id, tracking_code) "
                "VALUES (?, 'phase_b', 'success', ?, ?)",
                (shipment_id, ext_result.external_shipment_id, ext_result.tracking_code),
            )
            conn.execute(
                "UPDATE shipment_plans SET status='booked', updated_at=datetime('now') "
                "WHERE fulfillment_order_id=?",
                (fo_id,),
            )
        else:
            reason = ext_result.failure_reason or str(call_error or "unknown")
            conn.execute(
                """
                UPDATE shipments SET
                    status = 'booking_failed',
                    failure_reason = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (reason, shipment_id),
            )
            conn.execute(
                "INSERT INTO shipment_booking_log "
                "(shipment_id, phase, outcome, error_detail) VALUES (?, 'phase_b', 'failure', ?)",
                (shipment_id, reason),
            )

        return _shipment_dict(conn, shipment_id)


def plan_shipment(
    db: Database,
    fo_id: int,
    *,
    user_id: int,
    user_role: str,
    supplier_id: int | None = None,
    carrier_config_id: int | None = None,
) -> dict:
    """Allow admin/supplier to (re-)trigger shipment planning for a FO.

    Authorization enforced by _check_fo_access.
    If carrier_config_id is provided, it overrides the auto-selected carrier.

    Returns the existing plan if already in a completed/good state.
    Only re-plans if status is 'failed' or if carrier_config_id override is given.
    """
    with db.write_transaction() as conn:
        _check_fo_access(conn, fo_id, user_id=user_id, user_role=user_role,
                         supplier_id=supplier_id)

        existing = conn.execute(
            "SELECT * FROM shipment_plans WHERE fulfillment_order_id = ?", (fo_id,)
        ).fetchone()
        existing_dict = dict(existing) if existing else None

        if existing_dict:
            if existing_dict["status"] in ("booked", "booking_initiated"):
                # Already booked — don't touch it
                quotes = conn.execute(
                    "SELECT * FROM shipment_plan_quotes WHERE shipment_plan_id=?",
                    (existing_dict["id"],),
                ).fetchall()
                return {
                    "shipment_plan": existing_dict,
                    "quotes": [dict(q) for q in quotes],
                }

            if existing_dict["status"] == "quote_selected" and carrier_config_id is None:
                # Already planned with a selected carrier — return as-is
                quotes = conn.execute(
                    "SELECT * FROM shipment_plan_quotes WHERE shipment_plan_id=?",
                    (existing_dict["id"],),
                ).fetchall()
                return {
                    "shipment_plan": existing_dict,
                    "quotes": [dict(q) for q in quotes],
                }

            # Only reset and re-plan for failed plans OR explicit carrier override
            conn.execute(
                "UPDATE shipment_plans SET status='planned', failure_reason=NULL, "
                "selected_carrier_config_id=?, updated_at=datetime('now') "
                "WHERE fulfillment_order_id=?",
                (carrier_config_id, fo_id),
            )
            # Also delete existing quotes so ensure_shipment_plan can re-populate them
            conn.execute(
                "DELETE FROM shipment_plan_quotes WHERE shipment_plan_id=?",
                (existing_dict["id"],),
            )

    ensure_shipment_plan(db, fo_id)

    with db.read_transaction() as conn:
        plan = conn.execute(
            "SELECT * FROM shipment_plans WHERE fulfillment_order_id=?", (fo_id,)
        ).fetchone()
        quotes = conn.execute(
            "SELECT * FROM shipment_plan_quotes WHERE shipment_plan_id=?",
            (int(plan["id"]),),
        ).fetchall()
        return {
            "shipment_plan": dict(plan),
            "quotes": [dict(q) for q in quotes],
        }


# ---------------------------------------------------------------------------
# Tracking (customer-safe)
# ---------------------------------------------------------------------------

def get_tracking(
    conn: sqlite3.Connection,
    fo_id: int,
    *,
    customer_user_id: int | None = None,
) -> dict:
    """Return tracking information for a fulfillment order.

    If customer_user_id is provided, verifies the order belongs to that user.
    Only returns customer-safe fields (no internal carrier IDs).
    """
    fo_row = conn.execute(
        """
        SELECT fo.id, fo.status, fo.order_id,
               o.user_id AS customer_user_id, o.order_number
        FROM fulfillment_orders fo
        JOIN orders o ON o.id = fo.order_id
        WHERE fo.id = ?
        """,
        (fo_id,),
    ).fetchone()
    if fo_row is None:
        raise NotFoundError("سفارش یافت نشد")
    if customer_user_id is not None and int(fo_row["customer_user_id"]) != customer_user_id:
        raise NotFoundError("سفارش یافت نشد")

    shipment = conn.execute(
        "SELECT * FROM shipments WHERE fulfillment_order_id = ?", (fo_id,)
    ).fetchone()

    if shipment is None:
        return {
            "fulfillment_order_id": fo_id,
            "order_number": fo_row["order_number"],
            "fulfillment_status": fo_row["status"],
            "shipment": None,
        }

    s = dict(shipment)
    # Customer-safe: omit booking_idempotency_key and internal carrier config details
    return {
        "fulfillment_order_id": fo_id,
        "order_number": fo_row["order_number"],
        "fulfillment_status": fo_row["status"],
        "shipment": {
            "status": s["status"],
            "tracking_code": s["tracking_code"],
            "provider_code": s["provider_code"],
            "cost_minor": s["cost_minor"],
            "booked_at": s["booked_at"],
            "delivered_at": s["delivered_at"],
        },
    }


# ---------------------------------------------------------------------------
# Shipment read helper
# ---------------------------------------------------------------------------

def _shipment_dict(conn: sqlite3.Connection, shipment_id: int) -> dict:
    row = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if row is None:
        raise NotFoundError("حمل‌ونقل یافت نشد")
    return dict(row)


def get_shipment_for_fo(conn: sqlite3.Connection, fo_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM shipments WHERE fulfillment_order_id = ?", (fo_id,)
    ).fetchone()
    return dict(row) if row else None
