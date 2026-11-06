"""Phase 5C — multi-seller shipment orchestration.

Each fulfillment order (one per seller) gets its own logistics shipment: rate
shopped quote (persisted on the shipment plan), label data (sender/receiver,
barcode = tracking number, Code128-B payload), pickup request, SLA dates and
normalized tracking. Delivery is applied through the existing
fulfillment_service transitions so supplier payables/escrow start as before.
Return shipments are created for approved order_return_requests.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.adapters.logistics import registry
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import fulfillment_service, shipping_rate_service

STATUSES = registry.NORMALIZED_TRACKING_STATUSES
_RANK = {"created": 0, "picked_up": 1, "in_transit": 2, "out_for_delivery": 3, "delivered": 4}
TERMINAL = {"delivered", "returned"}
LABEL_ALLOWED_FO = ("accepted", "preparing", "ready")
DEFAULT_LEAD_DAYS = 1
IRAN_WEEKEND = 4  # Friday (datetime.weekday)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def add_business_days(start: datetime, days: int) -> datetime:
    """Add working days, skipping Fridays (Iranian weekend)."""
    d = start
    left = int(days)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() != IRAN_WEEKEND:
            left -= 1
    while d.weekday() == IRAN_WEEKEND:
        d += timedelta(days=1)
    return d


# ----------------------------------------------------------------- barcodes / labels
def tracking_check_digit(digits: str) -> int:
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def make_tracking_number(prefix: str, shipment_id: int, direction: str = "forward") -> str:
    body = f"{shipment_id:09d}"
    return f"{prefix}{'R' if direction == 'return' else ''}{body}{tracking_check_digit(body)}"


def code128_payload(data: str) -> dict:
    """Code128 code-set B payload with its mod-103 checksum (start B = 104)."""
    if not data or any(not 32 <= ord(c) <= 126 for c in data):
        raise ValidationError("داده بارکد Code128 نامعتبر است", code="invalid_barcode_data")
    total = 104 + sum((i + 1) * (ord(c) - 32) for i, c in enumerate(data))
    return {"symbology": "code128", "code_set": "B", "data": data, "checksum": total % 103}


def _fo_context(conn, fo_id: int) -> dict:
    row = conn.execute(
        "SELECT fo.*, o.order_number, o.user_id AS customer_user_id, o.recipient_name, o.recipient_phone, "
        "o.shipping_province, o.shipping_city, o.shipping_line1, o.shipping_postal_code, "
        "s.display_name AS supplier_name, sl.province AS origin_province, sl.city AS origin_city, "
        "sl.address AS origin_address "
        "FROM fulfillment_orders fo JOIN orders o ON o.id = fo.order_id "
        "JOIN suppliers s ON s.id = fo.supplier_id "
        "JOIN supplier_locations sl ON sl.id = fo.supplier_location_id WHERE fo.id = ?",
        (fo_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("سفارش تأمین یافت نشد", code="fulfillment_order_not_found")
    return dict(row)


def _fo_items(conn, fo_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT foi.product_id, foi.seller_offer_id, foi.quantity, foi.line_selling_minor, so.lead_time_days "
        "FROM fulfillment_order_items foi LEFT JOIN seller_offers so ON so.id = foi.seller_offer_id "
        "WHERE foi.fulfillment_order_id = ?", (fo_id,))]


def _shipment(conn, shipment_id: int) -> dict:
    row = conn.execute("SELECT * FROM logistics_shipments WHERE id=?", (shipment_id,)).fetchone()
    if row is None:
        raise NotFoundError("مرسوله یافت نشد", code="shipment_not_found")
    d = dict(row)
    d["label"] = json.loads(d.pop("label_json") or "{}")
    return d


# ----------------------------------------------------------------- SLA
def compute_sla(conn, fo_id: int, eta_days_max: int, *, now: datetime | None = None) -> dict:
    items = _fo_items(conn, fo_id)
    leads = [int(i["lead_time_days"]) for i in items if i["lead_time_days"] is not None]
    lead = max(leads) if leads else DEFAULT_LEAD_DAYS
    start = _now(now)
    ship_by = add_business_days(start, lead) if lead > 0 else start.replace(hour=23, minute=59, second=59, microsecond=0)
    deliver_by = add_business_days(ship_by, eta_days_max)
    return {"lead_time_days": lead, "ship_by_at": _iso(ship_by), "deliver_by_at": _iso(deliver_by)}


def _apply_promised_prep(conn, fo_id: int, ship_by: str) -> None:
    """Additive: fill promised_prep_at only when empty (phase-1 late-shipment metric)."""
    conn.execute(
        "UPDATE fulfillment_orders SET promised_prep_at = ? "
        "WHERE id = ? AND (promised_prep_at IS NULL OR promised_prep_at = '')",
        (ship_by, fo_id),
    )


# ----------------------------------------------------------------- forward shipment
def create_shipment_for_fo(conn: sqlite3.Connection, fo_id: int, *, supplier_id: int | None = None,
                           strategy: str = "cheapest", service_level: str | None = None,
                           provider_code: str | None = None, cod: bool = False,
                           insurance_value_minor: int | None = None,
                           live_quoter: Callable | None = None, now: datetime | None = None) -> dict:
    """Create (idempotently) the forward shipment + label for one seller's FO."""
    ctx = _fo_context(conn, fo_id)
    if supplier_id is not None and int(ctx["supplier_id"]) != int(supplier_id):
        raise NotFoundError("سفارش تأمین یافت نشد", code="fulfillment_order_not_found")
    key = f"fwd:{fo_id}"
    existing = conn.execute("SELECT id FROM logistics_shipments WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        return _shipment(conn, int(existing["id"]))
    if ctx["status"] not in LABEL_ALLOWED_FO:
        raise ConflictError("صدور برچسب ارسال در این وضعیت سفارش ممکن نیست", code="fo_not_shippable")
    if ctx["fulfillment_type"] == "pickup":
        raise ConflictError("این سفارش تحویل حضوری است و ارسال ندارد", code="pickup_only")
    items = _fo_items(conn, fo_id)
    goods_value = sum(int(i["line_selling_minor"]) for i in items)
    insurance = goods_value if insurance_value_minor is None else int(insurance_value_minor)
    parcels = [{"product_id": i["product_id"], "seller_offer_id": i["seller_offer_id"],
                "quantity": int(i["quantity"])} for i in items]
    origin = {"province": ctx["origin_province"], "city": ctx["origin_city"]}
    dest = {"province": ctx["shipping_province"], "city": ctx["shipping_city"]}
    result = shipping_rate_service.quote_shipping(
        conn, origin, dest, parcels, cod_value_minor=goods_value if cod else 0,
        insurance_value_minor=insurance, strategy=strategy,
        service_levels=[service_level] if service_level else None,
        live_quoter=live_quoter, persist=True, fulfillment_order_id=fo_id,
    )
    options = [o for o in result["options"] if not provider_code or o["provider_code"] == provider_code]
    if not options:
        raise NotFoundError("شرکت حمل انتخاب‌شده برای این مسیر در دسترس نیست", code="no_carrier_available")
    chosen = options[0]
    shipping_rate_service.persist_selected_quote_on_plan(conn, fo_id, chosen["quote_id"])
    sla = compute_sla(conn, fo_id, chosen["eta_days_max"], now=now)
    carrier = conn.execute("SELECT * FROM logistics_carriers WHERE provider_code=?",
                           (chosen["provider_code"],)).fetchone()
    cur = conn.execute(
        "INSERT INTO logistics_shipments (idempotency_key, direction, fulfillment_order_id, order_id, supplier_id, "
        "provider_code, service_level, quote_id, tracking_number, cod_amount_minor, insurance_value_minor, "
        "ship_by_at, deliver_by_at) VALUES (?, 'forward', ?,?,?,?,?,?,?,?,?,?,?)",
        (key, fo_id, ctx["order_id"], ctx["supplier_id"], chosen["provider_code"], chosen["service_level"],
         chosen["quote_id"], f"TMP-{key}", goods_value if cod else 0, insurance,
         sla["ship_by_at"], sla["deliver_by_at"]),
    )
    sid = int(cur.lastrowid)
    tracking = make_tracking_number(carrier["tracking_prefix"], sid)
    label = {
        "carrier": {"provider_code": carrier["provider_code"], "name_fa": carrier["name_fa"],
                    "service_level": chosen["service_level"]},
        "sender": {"name": ctx["supplier_name"], "province": ctx["origin_province"],
                   "city": ctx["origin_city"], "address": ctx["origin_address"] or ""},
        "receiver": {"name": ctx["recipient_name"], "phone": ctx["recipient_phone"],
                     "province": ctx["shipping_province"], "city": ctx["shipping_city"],
                     "address": ctx["shipping_line1"], "postal_code": ctx["shipping_postal_code"] or ""},
        "reference": {"order_number": ctx["order_number"], "fulfillment_order_id": fo_id},
        "parcel_count": sum(p["quantity"] for p in parcels),
        "billable_weight_g": chosen["billable_weight_g"],
        "cod_amount_minor": goods_value if cod else 0,
        "barcode": code128_payload(tracking),
        "tracking_number": tracking,
    }
    conn.execute("UPDATE logistics_shipments SET tracking_number=?, label_json=? WHERE id=?",
                 (tracking, json.dumps(label, ensure_ascii=False), sid))
    _apply_promised_prep(conn, fo_id, sla["ship_by_at"])
    return _shipment(conn, sid)


def request_pickup(conn: sqlite3.Connection, shipment_id: int, *, supplier_id: int | None,
                   window_start: str, window_end: str, now: datetime | None = None) -> dict:
    s = _shipment(conn, shipment_id)
    if supplier_id is not None and int(s["supplier_id"]) != int(supplier_id):
        raise NotFoundError("مرسوله یافت نشد", code="shipment_not_found")
    if s["status"] != "created":
        raise ConflictError("درخواست جمع‌آوری فقط پیش از تحویل به حامل ممکن است", code="pickup_not_allowed")
    try:
        ws = datetime.fromisoformat(str(window_start).replace("Z", "+00:00"))
        we = datetime.fromisoformat(str(window_end).replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("بازه زمانی جمع‌آوری نامعتبر است", code="invalid_pickup_window")
    if we <= ws:
        raise ValidationError("پایان بازه جمع‌آوری باید بعد از شروع آن باشد", code="invalid_pickup_window")
    conn.execute("UPDATE logistics_shipments SET pickup_requested_at=?, pickup_window_start=?, "
                 "pickup_window_end=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                 (_iso(_now(now)), window_start, window_end, shipment_id))
    return _shipment(conn, shipment_id)


# ----------------------------------------------------------------- tracking
def normalize_status(conn, carrier: str, raw_code) -> str:
    mapping = registry.get_tracking_status_map(carrier)
    row = conn.execute("SELECT status_map_json FROM logistics_carriers WHERE provider_code=?",
                       (carrier,)).fetchone()
    if row:
        mapping.update(json.loads(row["status_map_json"] or "{}"))
    status = mapping.get(str(raw_code))
    if status not in STATUSES:
        raise ValidationError("کد وضعیت رهگیری این شرکت حمل ناشناخته است", code="unknown_tracking_status")
    return status


def _allowed(current: str, new: str) -> bool:
    if current in TERMINAL or new == current:
        return False
    if new in ("failed", "returned"):
        return True
    if current == "failed":
        return new in _RANK
    return _RANK.get(new, -1) > _RANK.get(current, -1)


def _advance_fo(conn, shipment: dict, status: str) -> None:
    """Reuse fulfillment_service transitions (no duplication of payable logic)."""
    if shipment["direction"] != "forward":
        return
    fo = conn.execute("SELECT status, supplier_id FROM fulfillment_orders WHERE id=?",
                      (shipment["fulfillment_order_id"],)).fetchone()
    if fo is None:
        return
    fo_id, sup = int(shipment["fulfillment_order_id"]), int(fo["supplier_id"])
    if status in ("picked_up", "in_transit", "out_for_delivery") and fo["status"] == "ready":
        fulfillment_service.supplier_mark_dispatched(conn, fulfillment_order_id=fo_id, supplier_id=sup)
    elif status == "delivered" and fo["status"] in ("ready", "dispatched"):
        fulfillment_service.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=None,
                                                    actor_type="system")


def apply_tracking_event(conn: sqlite3.Connection, carrier: str, payload: dict) -> dict:
    """Idempotent tracking webhook handler (endpoint is owned by phase 5A).

    payload: tracking_number, status (carrier code), event_id (optional),
             occurred_at (optional ISO), location (optional).
    """
    if not isinstance(payload, dict):
        raise ValidationError("بدنه رویداد رهگیری نامعتبر است", code="invalid_tracking_payload")
    tracking = str(payload.get("tracking_number") or "").strip()
    raw = payload.get("status")
    if not tracking or raw in (None, ""):
        raise ValidationError("شماره رهگیری و وضعیت الزامی است", code="invalid_tracking_payload")
    row = conn.execute("SELECT id FROM logistics_shipments WHERE tracking_number=? AND provider_code=?",
                       (tracking, carrier)).fetchone()
    if row is None:
        raise NotFoundError("مرسوله‌ای با این شماره رهگیری یافت نشد", code="shipment_not_found")
    status = normalize_status(conn, carrier, raw)
    occurred = str(payload.get("occurred_at") or _iso(_now(None)))
    event_id = str(payload.get("event_id") or hashlib.sha256(
        f"{tracking}|{raw}|{payload.get('occurred_at') or ''}".encode()).hexdigest()[:32])
    if conn.execute("SELECT 1 FROM logistics_tracking_events WHERE provider_code=? AND provider_event_id=?",
                    (carrier, event_id)).fetchone():
        return {"duplicate": True, "applied": False, "shipment": _shipment(conn, int(row["id"]))}
    shipment = _shipment(conn, int(row["id"]))
    applied = _allowed(shipment["status"], status)
    conn.execute(
        "INSERT INTO logistics_tracking_events (shipment_id, provider_code, provider_event_id, raw_status, "
        "status, occurred_at, location, applied) VALUES (?,?,?,?,?,?,?,?)",
        (shipment["id"], carrier, event_id, str(raw), status, occurred,
         str(payload.get("location") or ""), 1 if applied else 0),
    )
    if applied:
        conn.execute("UPDATE logistics_shipments SET status=?, delivered_at=CASE WHEN ?='delivered' THEN ? "
                     "ELSE delivered_at END, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                     (status, status, occurred, shipment["id"]))
        _advance_fo(conn, shipment, status)
    return {"duplicate": False, "applied": applied, "shipment": _shipment(conn, shipment["id"])}


# ----------------------------------------------------------------- returns
def create_return_shipments(conn: sqlite3.Connection, return_request_id: int, *,
                            now: datetime | None = None) -> list[dict]:
    """Reverse shipment (customer → seller) per FO touched by an approved return."""
    rr = conn.execute("SELECT * FROM order_return_requests WHERE id=?", (return_request_id,)).fetchone()
    if rr is None:
        raise NotFoundError("درخواست مرجوعی یافت نشد", code="return_not_found")
    if rr["status"] != "approved":
        raise ConflictError("ارسال مرجوعی فقط برای درخواست تأییدشده ممکن است", code="return_not_approved")
    wanted = {int(i["product_id"]): int(i["quantity"]) for i in json.loads(rr["items_json"])}
    fos = conn.execute(
        "SELECT DISTINCT fo.id FROM fulfillment_orders fo JOIN fulfillment_order_items foi "
        "ON foi.fulfillment_order_id = fo.id WHERE fo.order_id=? AND fo.status IN ('dispatched','delivered') "
        "ORDER BY fo.id", (rr["order_id"],)).fetchall()
    out = []
    for f in fos:
        fo_id = int(f["id"])
        items = [i for i in _fo_items(conn, fo_id) if int(i["product_id"]) in wanted]
        if not items:
            continue
        key = f"ret:{return_request_id}:{fo_id}"
        ex = conn.execute("SELECT id FROM logistics_shipments WHERE idempotency_key=?", (key,)).fetchone()
        if ex:
            out.append(_shipment(conn, int(ex["id"])))
            continue
        ctx = _fo_context(conn, fo_id)
        fwd = conn.execute("SELECT provider_code FROM logistics_shipments WHERE idempotency_key=?",
                           (f"fwd:{fo_id}",)).fetchone()
        parcels = [{"product_id": i["product_id"], "seller_offer_id": i["seller_offer_id"],
                    "quantity": min(int(i["quantity"]), wanted[int(i["product_id"])])} for i in items]
        res = shipping_rate_service.quote_shipping(
            conn, {"province": ctx["shipping_province"], "city": ctx["shipping_city"]},
            {"province": ctx["origin_province"], "city": ctx["origin_city"]}, parcels,
            persist=True, fulfillment_order_id=fo_id)
        opts = [o for o in res["options"] if fwd and o["provider_code"] == fwd["provider_code"]] or res["options"]
        chosen = opts[0]
        carrier = conn.execute("SELECT * FROM logistics_carriers WHERE provider_code=?",
                               (chosen["provider_code"],)).fetchone()
        cur = conn.execute(
            "INSERT INTO logistics_shipments (idempotency_key, direction, fulfillment_order_id, order_id, "
            "supplier_id, return_request_id, provider_code, service_level, quote_id, tracking_number, "
            "deliver_by_at) VALUES (?, 'return', ?,?,?,?,?,?,?,?,?)",
            (key, fo_id, ctx["order_id"], ctx["supplier_id"], return_request_id, chosen["provider_code"],
             chosen["service_level"], chosen["quote_id"], f"TMP-{key}",
             _iso(add_business_days(_now(now), chosen["eta_days_max"] + 1))),
        )
        sid = int(cur.lastrowid)
        tracking = make_tracking_number(carrier["tracking_prefix"], sid, "return")
        label = {
            "carrier": {"provider_code": carrier["provider_code"], "name_fa": carrier["name_fa"]},
            "sender": {"name": ctx["recipient_name"], "phone": ctx["recipient_phone"],
                       "province": ctx["shipping_province"], "city": ctx["shipping_city"],
                       "address": ctx["shipping_line1"]},
            "receiver": {"name": ctx["supplier_name"], "province": ctx["origin_province"],
                         "city": ctx["origin_city"], "address": ctx["origin_address"] or ""},
            "reference": {"order_number": ctx["order_number"], "return_request_id": return_request_id},
            "barcode": code128_payload(tracking), "tracking_number": tracking,
        }
        conn.execute("UPDATE logistics_shipments SET tracking_number=?, label_json=? WHERE id=?",
                     (tracking, json.dumps(label, ensure_ascii=False), sid))
        out.append(_shipment(conn, sid))
    if not out:
        raise ConflictError("هیچ مرسوله ارسال‌شده‌ای برای اقلام مرجوعی یافت نشد", code="nothing_to_return")
    return out


# ----------------------------------------------------------------- reads
def list_supplier_shipments(conn, supplier_id: int) -> list[dict]:
    return [_shipment(conn, int(r["id"])) for r in conn.execute(
        "SELECT id FROM logistics_shipments WHERE supplier_id=? ORDER BY id DESC LIMIT 200", (supplier_id,))]


def get_order_tracking(conn, order_id: int, *, user_id: int | None) -> dict:
    o = conn.execute("SELECT id, order_number, user_id FROM orders WHERE id=?", (order_id,)).fetchone()
    if o is None or (user_id is not None and int(o["user_id"]) != int(user_id)):
        raise NotFoundError("سفارش یافت نشد", code="order_not_found")
    shipments = []
    for r in conn.execute("SELECT * FROM logistics_shipments WHERE order_id=? ORDER BY id", (order_id,)):
        events = [dict(e) for e in conn.execute(
            "SELECT status, occurred_at, location FROM logistics_tracking_events "
            "WHERE shipment_id=? AND applied=1 ORDER BY occurred_at, id", (r["id"],))]
        shipments.append({
            "tracking_number": r["tracking_number"], "direction": r["direction"],
            "provider_code": r["provider_code"], "service_level": r["service_level"],
            "status": r["status"], "deliver_by_at": r["deliver_by_at"],
            "delivered_at": r["delivered_at"], "events": events,
        })
    return {"order_number": o["order_number"], "shipments": shipments}
