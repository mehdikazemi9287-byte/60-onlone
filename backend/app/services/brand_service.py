"""Phase 3 — brand zone (محوطهٔ برندها): brand verification, official badge, pre-orders (پیش‌سفارش).

Brands are suppliers with seller_kind='brand'. The "official" badge is shown only while the brand is active
AND holds a verified brand_registrations row. Pre-orders snapshot price and deposit WITHOUT reserving stock;
conversion (seller/admin, after the deposit is paid) reserves stock and creates a real order.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import audit_service, fulfillment_service
from app.services import org_order_service as orders

REG_FIELDS = {"brand_name": 120, "trademark_number": 40, "document_url": 500}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(data: dict, key: str, limit: int) -> str:
    v = data.get(key)
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > limit:
        raise ValidationError(f"{key} الزامی است (حداکثر {limit} نویسه)", details={key: "نامعتبر"})
    return v.strip()


def _ts(value, key: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValidationError(f"{key} باید تاریخ/زمان ISO باشد")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── verification ───────────────────────────────────────────────────────────────


def _reg(row) -> dict:
    return {k: row[k] for k in ("id", "supplier_id", "brand_name", "trademark_number", "document_url", "status",
                                "review_note", "reviewed_at", "created_at")}


def is_official(conn, supplier_id: int) -> bool:
    return conn.execute(
        """SELECT 1 FROM suppliers s JOIN brand_registrations b ON b.supplier_id=s.id AND b.status='verified'
           WHERE s.id=? AND s.seller_kind='brand' AND s.status='active'""", (supplier_id,)).fetchone() is not None


def submit_registration(conn, *, supplier_id: int, user_id: int, data: dict) -> dict:
    s = conn.execute("SELECT seller_kind FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if s is None or s["seller_kind"] != "brand":
        raise PermissionError_("ثبت برند فقط برای حساب‌های نوع «برند» ممکن است")
    clean = {k: _text(data, k, n) for k, n in REG_FIELDS.items()}
    if not clean["document_url"].startswith("https://"):
        raise ValidationError("نشانی مدرک باید با https:// شروع شود")
    if conn.execute("SELECT 1 FROM brand_registrations WHERE supplier_id=? AND status='pending'", (supplier_id,)).fetchone():
        raise ConflictError("درخواست قبلی شما هنوز در حال بررسی است", code="registration_pending")
    taken = conn.execute("SELECT 1 FROM brand_registrations WHERE trademark_number=? AND supplier_id<>? "
                         "AND status IN ('pending','verified')", (clean["trademark_number"], supplier_id)).fetchone()
    if taken:
        raise ConflictError("این شمارهٔ ثبت علامت تجاری برای برند دیگری ثبت شده است", code="trademark_taken")
    now = _now()
    cur = conn.execute("""INSERT INTO brand_registrations (supplier_id, brand_name, trademark_number, document_url,
                          status, submitted_by_user_id, created_at, updated_at) VALUES (?,?,?,?, 'pending', ?,?,?)""",
                       (supplier_id, clean["brand_name"], clean["trademark_number"], clean["document_url"],
                        user_id, now, now))
    return _reg(conn.execute("SELECT * FROM brand_registrations WHERE id=?", (cur.lastrowid,)).fetchone())


def my_registrations(conn, *, supplier_id: int) -> dict:
    rows = conn.execute("SELECT * FROM brand_registrations WHERE supplier_id=? ORDER BY id DESC", (supplier_id,))
    return {"official": is_official(conn, supplier_id), "items": [_reg(r) for r in rows.fetchall()]}


def admin_list(conn, *, status: str = "pending") -> list[dict]:
    if status not in ("pending", "verified", "rejected"):
        raise ValidationError("وضعیت نامعتبر است")
    return [_reg(r) for r in conn.execute("SELECT * FROM brand_registrations WHERE status=? ORDER BY id",
                                          (status,)).fetchall()]


def review(conn, *, registration_id: int, admin_user_id: int, decision, note=None) -> dict:
    if decision not in ("verified", "rejected"):
        raise ValidationError("تصمیم باید verified یا rejected باشد")
    if decision == "rejected" and not (isinstance(note, str) and note.strip()):
        raise ValidationError("دلیل رد الزامی است")
    row = conn.execute("SELECT * FROM brand_registrations WHERE id=?", (registration_id,)).fetchone()
    if row is None:
        raise NotFoundError("درخواست ثبت برند یافت نشد")
    if row["status"] != "pending":
        raise ConflictError("این درخواست قبلاً بررسی شده است")
    now = _now()
    if decision == "verified":  # one verified registration per brand at a time
        conn.execute("UPDATE brand_registrations SET status='rejected', review_note='جایگزین با ثبت جدید', "
                     "updated_at=? WHERE supplier_id=? AND status='verified'", (now, row["supplier_id"]))
    conn.execute("""UPDATE brand_registrations SET status=?, reviewer_user_id=?, review_note=?, reviewed_at=?,
                    updated_at=? WHERE id=?""",
                 (decision, admin_user_id, (note or "").strip()[:1000] or None, now, now, registration_id))
    audit_service.record(conn, action=f"brand.{decision}", entity_type="brand_registration", entity_id=registration_id,
                         actor_user_id=admin_user_id, metadata={"supplier_id": row["supplier_id"]})
    return _reg(conn.execute("SELECT * FROM brand_registrations WHERE id=?", (registration_id,)).fetchone())


def list_brands(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT s.id, COALESCE(s.shop_title, s.display_name) AS title, s.shop_slug, s.shop_logo_url, s.rating_x10,
                  b.brand_name, b.trademark_number
           FROM suppliers s JOIN brand_registrations b ON b.supplier_id=s.id AND b.status='verified'
           WHERE s.seller_kind='brand' AND s.status='active' AND s.provenance='real'
           ORDER BY s.rating_x10 DESC, s.id LIMIT 200""").fetchall()
    return [dict(r, official=True) for r in rows]


def brand_page(conn, supplier_id: int) -> dict:
    if not is_official(conn, supplier_id):
        raise NotFoundError("برند رسمی یافت نشد")
    brand = next((b for b in list_brands(conn) if b["id"] == supplier_id), None)
    if brand is None:
        raise NotFoundError("برند رسمی یافت نشد")
    now = _now()
    rows = conn.execute(
        """SELECT o.id AS offer_id, p.slug, p.title_fa, o.selling_price_minor, o.pricing_mode,
                  o.stock_quantity - o.stock_reserved AS available,
                  w.expected_ship_date, w.deposit_bps, w.unit_price_minor AS preorder_price_minor, w.ends_at
           FROM seller_offers o JOIN products p ON p.id=o.product_id
           LEFT JOIN offer_preorder_windows w ON w.offer_id=o.id AND w.status='open' AND w.starts_at<=? AND w.ends_at>=?
           WHERE o.supplier_id=? AND o.status='active' AND p.is_active=1 ORDER BY o.id LIMIT 200""",
        (now, now, supplier_id)).fetchall()
    products = [{"offer_id": r["offer_id"], "slug": r["slug"], "title": r["title_fa"],
                 "price_minor": r["selling_price_minor"] if r["pricing_mode"] == "fixed" else None,
                 "in_stock": (r["available"] or 0) > 0,
                 "preorder": None if r["expected_ship_date"] is None else {
                     "unit_price_minor": r["preorder_price_minor"], "deposit_bps": r["deposit_bps"],
                     "expected_ship_date": r["expected_ship_date"], "ends_at": r["ends_at"]}} for r in rows]
    return {"brand": brand, "products": products}


# ── pre-orders ─────────────────────────────────────────────────────────────────


def set_window(conn, *, supplier_id: int, user_id: int, offer_id: int, data: dict) -> dict:
    offer = conn.execute("SELECT id, supplier_id FROM seller_offers WHERE id=?", (offer_id,)).fetchone()
    if offer is None or offer["supplier_id"] != supplier_id:
        raise NotFoundError("پیشنهاد فروش یافت نشد")
    starts, ends = _ts(data.get("starts_at"), "starts_at"), _ts(data.get("ends_at"), "ends_at")
    if ends <= starts:
        raise ValidationError("پایان بازهٔ پیش‌سفارش باید بعد از شروع آن باشد")
    ship = data.get("expected_ship_date")
    try:
        if not isinstance(ship, str) or datetime.fromisoformat(ship).date().isoformat() != ship:
            raise ValueError
    except ValueError:
        raise ValidationError("تاریخ ارسال پیش‌بینی‌شده باید YYYY-MM-DD باشد")
    deposit = orders._int(data.get("deposit_bps"), "deposit_bps", maximum=10000)
    price = orders._int(data.get("unit_price_minor"), "unit_price_minor", minimum=1)
    cap = orders._int(data.get("max_quantity"), "max_quantity", minimum=1, required=False)
    status = data.get("status", "open")
    if status not in ("open", "closed"):
        raise ValidationError("وضعیت پیش‌سفارش باید open یا closed باشد")
    now = _now()
    conn.execute("DELETE FROM offer_preorder_windows WHERE offer_id=?", (offer_id,))
    conn.execute("""INSERT INTO offer_preorder_windows (offer_id, starts_at, ends_at, expected_ship_date, deposit_bps,
                    unit_price_minor, max_quantity, status, updated_by_user_id, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 (offer_id, starts, ends, ship, deposit, price, cap, status, user_id, now, now))
    return dict(conn.execute("SELECT * FROM offer_preorder_windows WHERE offer_id=?", (offer_id,)).fetchone())


def _preorder(row) -> dict:
    return dict(row)


def create_preorder(conn, *, user_id: int, data: dict, idempotency_key) -> tuple[int, dict]:
    key = orders._idempotency_key(idempotency_key)
    done = conn.execute("SELECT * FROM preorders WHERE user_id=? AND idempotency_key=?", (user_id, key)).fetchone()
    if done is not None:
        return 200, _preorder(done)
    offer_id = orders._int(data.get("offer_id"), "offer_id", minimum=1)
    qty = orders._int(data.get("quantity"), "quantity", minimum=1, maximum=100000)
    address = orders._clean_address(data.get("shipping_address"))
    w = conn.execute("SELECT * FROM offer_preorder_windows WHERE offer_id=?", (offer_id,)).fetchone()
    now = _now()
    if w is None or w["status"] != "open" or not w["starts_at"] <= now <= w["ends_at"]:
        raise ConflictError("پیش‌سفارش این کالا اکنون باز نیست", code="preorder_closed")
    offer = orders._offer_row(conn, offer_id)
    if offer["supplier_status"] != "active" or offer["health_status"] == "suspended":
        raise ConflictError("فروشندهٔ این کالا فعال نیست", code="offer_unavailable")
    if w["max_quantity"] is not None:
        used = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM preorders WHERE offer_id=? AND status<>'cancelled'",
                            (offer_id,)).fetchone()[0]
        if used + qty > w["max_quantity"]:
            raise ConflictError("ظرفیت پیش‌سفارش این کالا تکمیل شده است", code="preorder_sold_out",
                                details={"remaining": max(0, w["max_quantity"] - used)})
    total = int(w["unit_price_minor"]) * qty
    deposit = total * int(w["deposit_bps"]) // 10000
    number = f"PRE-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
    cur = conn.execute(
        """INSERT INTO preorders (preorder_number, offer_id, product_id, supplier_id, user_id, quantity, unit_price_minor,
               total_minor, deposit_bps, deposit_minor, balance_minor, expected_ship_date, status, deposit_paid_at,
               recipient_name, recipient_phone, shipping_province, shipping_city, shipping_line1, shipping_postal_code,
               idempotency_key, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (number, offer_id, offer["product_id"], offer["supplier_id"], user_id, qty, w["unit_price_minor"], total,
         w["deposit_bps"], deposit, total - deposit, w["expected_ship_date"],
         "deposit_paid" if deposit == 0 else "deposit_due", now if deposit == 0 else None,
         address["recipient_name"], address["recipient_phone"], address["province"], address["city"],
         address["line1"], address["postal_code"], key, now, now))
    return 201, _preorder(conn.execute("SELECT * FROM preorders WHERE id=?", (cur.lastrowid,)).fetchone())


def _get(conn, preorder_id: int):
    row = conn.execute("SELECT * FROM preorders WHERE id=?", (preorder_id,)).fetchone()
    if row is None:
        raise NotFoundError("پیش‌سفارش یافت نشد")
    return row


def my_preorders(conn, *, user_id: int) -> list[dict]:
    return [_preorder(r) for r in conn.execute("SELECT * FROM preorders WHERE user_id=? ORDER BY id DESC",
                                               (user_id,)).fetchall()]


def confirm_deposit(conn, *, preorder_id: int, admin_user_id: int, reference) -> dict:
    row = _get(conn, preorder_id)
    if row["status"] != "deposit_due":
        raise ConflictError("بیعانهٔ این پیش‌سفارش در انتظار پرداخت نیست")
    ref = orders.pr_svc._text(reference, "شمارهٔ پیگیری", 100, required=True)
    conn.execute("UPDATE preorders SET status='deposit_paid', deposit_reference=?, deposit_paid_at=?, updated_at=? "
                 "WHERE id=?", (ref, _now(), _now(), preorder_id))
    return _preorder(_get(conn, preorder_id))


def cancel(conn, *, preorder_id: int, user_id: int) -> dict:
    row = _get(conn, preorder_id)
    if row["user_id"] != user_id:
        raise NotFoundError("پیش‌سفارش یافت نشد")
    if row["status"] != "deposit_due":
        raise ConflictError("فقط پیش‌سفارش بدون بیعانه قابل لغو توسط خریدار است")
    conn.execute("UPDATE preorders SET status='cancelled', updated_at=? WHERE id=?", (_now(), preorder_id))
    return _preorder(_get(conn, preorder_id))


def convert(conn, *, preorder_id: int, actor_user_id: int, supplier_id: int | None) -> dict:
    """Seller (owner) or platform admin (supplier_id=None) turns a paid pre-order into a real order."""
    row = _get(conn, preorder_id)
    if supplier_id is not None and row["supplier_id"] != supplier_id:
        raise NotFoundError("پیش‌سفارش یافت نشد")
    if row["status"] == "converted":
        return orders.order_view(conn, int(row["converted_order_id"]))
    if row["status"] != "deposit_paid":
        raise ConflictError("پیش‌سفارش تنها پس از پرداخت بیعانه قابل تبدیل است", code="deposit_not_paid")
    offer = orders._offer_row(conn, int(row["offer_id"]))
    unit, qty = int(row["unit_price_minor"]), int(row["quantity"])
    plan = {"customer_province": row["shipping_province"], "customer_city": row["shipping_city"],
            "items": [orders.plan_item(offer, quantity=qty, selling_price_minor=unit)]}
    fulfillment_service.reserve_supplier_stock_for_plan(conn, plan=plan)  # stock is reserved only now
    tax_minor, rate = orders._tax(conn, unit * qty, None)
    total = unit * qty + tax_minor
    address = {"recipient_name": row["recipient_name"], "recipient_phone": row["recipient_phone"],
               "province": row["shipping_province"], "city": row["shipping_city"], "line1": row["shipping_line1"],
               "postal_code": row["shipping_postal_code"]}
    created = orders.create_order_rows(
        conn, user_id=int(row["user_id"]), organization_id=None, actor_user_id=actor_user_id,
        lines=[{"product_id": offer["product_id"], "title_fa": offer["title_fa"], "sku": offer["sku"],
                "unit_price_minor": unit, "quantity": qty}],
        shipping_minor=0, tax_minor=tax_minor, tax_rate_bps=rate, address=address, credit_minor=0, cash_minor=total,
        allocation_id=None, idempotency_key=f"preorder:{preorder_id}", request_hash=row["preorder_number"], plan=plan)
    due = total - int(row["deposit_minor"])
    import json
    conn.execute("""INSERT INTO order_sources (order_id, source_kind, preorder_id, payment_method, cash_due_minor,
                    cash_status, payment_intent_id, fulfillment_plan_json, created_by_user_id, created_at)
                    VALUES (?, 'preorder', ?, 'cash', ?, ?, ?, ?, ?, ?)""",
                 (created["order_id"], preorder_id, due, "due" if due else "none", created["intent_id"],
                  json.dumps(plan, ensure_ascii=False), actor_user_id, _now()))
    conn.execute("UPDATE preorders SET status='converted', converted_order_id=?, updated_at=? WHERE id=?",
                 (created["order_id"], _now(), preorder_id))
    if due == 0:
        orders.finalize_paid(conn, order_id=created["order_id"], actor_user_id=actor_user_id, provider="preorder_deposit",
                             provider_ref=row["preorder_number"])
    audit_service.record(conn, action="preorder.converted", entity_type="preorder", entity_id=preorder_id,
                         actor_user_id=actor_user_id, metadata={"order_id": created["order_id"], "balance_due_minor": due})
    return orders.order_view(conn, created["order_id"])


def confirm_balance(conn, *, preorder_id: int, admin_user_id: int, reference) -> dict:
    row = _get(conn, preorder_id)
    if row["status"] != "converted":
        raise ConflictError("پیش‌سفارش هنوز به سفارش تبدیل نشده است")
    order_id = int(row["converted_order_id"])
    src = conn.execute("SELECT cash_status FROM order_sources WHERE order_id=?", (order_id,)).fetchone()
    if src["cash_status"] == "due":
        ref = orders.pr_svc._text(reference, "شمارهٔ پیگیری", 100, required=True)
        conn.execute("UPDATE order_sources SET cash_reference=? WHERE order_id=?", (ref, order_id))
        orders.finalize_paid(conn, order_id=order_id, actor_user_id=admin_user_id, provider="preorder_transfer",
                             provider_ref=ref)
    return orders.order_view(conn, order_id)
