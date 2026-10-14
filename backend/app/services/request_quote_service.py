"""Personal inquiry → versioned quote with deadline → customer acceptance → revalidation → pending order.

No organization membership is involved. Unpriced lines are not allowed in a quote (a quote is a priced
offer); the request itself keeps unknown prices as null. Acceptance re-checks ownership, status, expiry and
that every quoted SKU is still an active REAL product, then creates exactly one 'pending' order (payment
pending — no charge, credit or reservation). Replaying acceptance returns the same order.
"""
from __future__ import annotations

import datetime
import json
import secrets

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import sale_eligibility as se
from app.services import product_channel_policy as policy


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _view(row) -> dict:
    d = dict(row)
    d["lines"] = json.loads(d.pop("lines_json"))
    d["expired"] = d["status"] == "sent" and d["expires_at"] < _iso(_now())
    d["state"] = "expired" if d["expired"] else d["status"]
    return d


def list_for_request(conn, request_id: int) -> list[dict]:
    return [_view(r) for r in conn.execute("SELECT * FROM customer_request_quotes WHERE request_id=? ORDER BY version DESC", (request_id,))]


def _int(v, name, lo=0):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise ValidationError(f"{name} نامعتبر است")
    return v


def create(conn, *, request_id: int, actor: int, data: dict) -> dict:
    req = conn.execute("SELECT * FROM customer_requests WHERE id=?", (request_id,)).fetchone()
    if not req:
        raise NotFoundError("درخواست یافت نشد")
    if req["status"] == "closed":
        raise ConflictError("درخواست بسته شده است")
    if req["organization_id"]:
        raise ConflictError("درخواست سازمانی از مسیر خرید سازمانی قیمت‌گذاری می‌شود", code="organization_request")
    if conn.execute("SELECT 1 FROM customer_request_quotes WHERE request_id=? AND status='accepted'", (request_id,)).fetchone():
        raise ConflictError("برای این درخواست قبلاً سفارش ثبت شده است", code="already_ordered")
    lines = []
    for ln in data.get("lines") or []:
        if not isinstance(ln, dict):
            raise ValidationError("ردیف پیشنهاد نامعتبر است")
        p = conn.execute("SELECT id, slug, sku, title_fa, provenance, is_active FROM products WHERE slug=?", (ln.get("slug"),)).fetchone()
        if not p or not p["is_active"] or p["provenance"] not in se.allowed_provenance():
            raise ValidationError("کالای پیشنهاد باید کالای فعال فروشگاه باشد")
        policy.require_sku(conn,p["id"],"retail")
        qty, unit = _int(ln.get("quantity"), "تعداد", 1), _int(ln.get("unit_price_minor"), "قیمت واحد", 1)
        lines.append({"product_id": p["id"], "slug": p["slug"], "sku": p["sku"], "title_fa": p["title_fa"], "quantity": qty,
                      "unit_price_minor": unit, "line_total_minor": unit * qty})
    if not lines:
        raise ValidationError("پیشنهاد حداقل یک ردیف قیمت‌دار لازم دارد")
    days = _int(data.get("valid_days", 3), "مهلت", 1)
    if days > 30:
        raise ValidationError("مهلت پیشنهاد حداکثر ۳۰ روز است")
    shipping, tax = _int(data.get("shipping_minor", 0), "هزینه ارسال"), _int(data.get("tax_minor", 0), "مالیات")
    subtotal = sum(line["line_total_minor"] for line in lines)
    version = (conn.execute("SELECT COALESCE(MAX(version),0) FROM customer_request_quotes WHERE request_id=?", (request_id,)).fetchone()[0]) + 1
    conn.execute("UPDATE customer_request_quotes SET status='superseded' WHERE request_id=? AND status='sent'", (request_id,))
    qid = conn.execute("""INSERT INTO customer_request_quotes (request_id, version, lines_json, subtotal_minor, shipping_minor, tax_minor, total_minor,
                          note, expires_at, created_by_user_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       (request_id, version, json.dumps(lines, ensure_ascii=False), subtotal, shipping, tax, subtotal + shipping + tax,
                        (data.get("note") or "")[:1000] or None, _iso(_now() + datetime.timedelta(days=days)), actor)).lastrowid
    now = _iso(_now())
    conn.execute("UPDATE customer_requests SET status='answered', response=?, updated_at=? WHERE id=?",
                 (f"پیشنهاد قیمت نسخه {version} ارسال شد", now, request_id))
    conn.execute("INSERT INTO customer_request_events (request_id, actor_user_id, status, message, created_at) VALUES (?,?,?,?,?)",
                 (request_id, actor, "answered", f"پیشنهاد قیمت نسخه {version} (مهلت {days} روز)", now))
    from app.services.commerce_ops_service import notify
    notify(conn, req["user_id"], "request_quote", f"پیشنهاد قیمت برای «{req['subject']}»", f"مهلت پذیرش: {days} روز", f"/requests/{request_id}")
    return _view(conn.execute("SELECT * FROM customer_request_quotes WHERE id=?", (qid,)).fetchone())


def accept(conn, *, user_id: int, request_id: int, quote_id: int, address: dict) -> dict:
    from app.services.checkout_service import validate_address
    req = conn.execute("SELECT * FROM customer_requests WHERE id=? AND user_id=?", (request_id, user_id)).fetchone()
    if not req:
        raise NotFoundError("درخواست یافت نشد")
    q = conn.execute("SELECT * FROM customer_request_quotes WHERE id=? AND request_id=?", (quote_id, request_id)).fetchone()
    if not q:
        raise NotFoundError("پیشنهاد یافت نشد")
    if q["status"] == "accepted" and q["order_id"]:
        o = conn.execute("SELECT order_number, status, total_minor FROM orders WHERE id=?", (q["order_id"],)).fetchone()
        return {"order": dict(o), "replayed": True}
    if q["status"] != "sent":
        raise ConflictError("این نسخه پیشنهاد دیگر معتبر نیست؛ آخرین نسخه را ببینید", code="quote_not_current")
    if req["status"] == "closed":
        raise ConflictError("این درخواست بسته شده است", code="request_closed")
    if q["expires_at"] < _iso(_now()):
        raise ConflictError("مهلت این پیشنهاد تمام شده است؛ پیشنهاد تازه درخواست کنید", code="quote_expired")
    lines = json.loads(q["lines_json"])
    for ln in lines:  # revalidate: every quoted product must still be an active sellable catalog product
        policy.require_sku(conn,ln["product_id"],"retail")
        p = conn.execute("SELECT is_active, provenance FROM products WHERE id=?", (ln["product_id"],)).fetchone()
        if not p or not p["is_active"] or p["provenance"] not in se.allowed_provenance():
            raise ConflictError(f"«{ln['title_fa']}» دیگر در فروشگاه فعال نیست؛ پیشنهاد باید به‌روز شود", code="quote_line_unavailable")
    a = validate_address(address or {})
    number = "Q" + _now().strftime("%y%m%d") + secrets.token_hex(3).upper()
    oid = conn.execute("""INSERT INTO orders (order_number, user_id, status, subtotal_minor, shipping_fee_minor, tax_minor, total_minor, currency,
                          recipient_name, recipient_phone, shipping_province, shipping_city, shipping_line1, shipping_postal_code)
                          VALUES (?,?,'pending',?,?,?,?,'IRR',?,?,?,?,?,?)""",
                       (number, user_id, q["subtotal_minor"], q["shipping_minor"], q["tax_minor"], q["total_minor"], a["recipient_name"],
                        a["recipient_phone"], a["province"], a["city"], a["line1"], a.get("postal_code"))).lastrowid
    for ln in lines:
        conn.execute("""INSERT INTO order_items (order_id, product_id, title_fa, sku, unit_price_minor, quantity, line_total_minor)
                        VALUES (?,?,?,?,?,?,?)""", (oid, ln["product_id"], ln["title_fa"], ln["sku"], ln["unit_price_minor"], ln["quantity"], ln["line_total_minor"]))
    changed = conn.execute("""UPDATE customer_request_quotes SET status='accepted', order_id=?, accepted_at=? WHERE id=? AND status='sent'""",
                           (oid, _iso(_now()), quote_id))
    if changed.rowcount != 1:
        raise ConflictError("پیشنهاد همزمان تغییر کرد؛ دوباره تلاش کنید", code="stale_quote")
    now = _iso(_now())
    conn.execute("UPDATE customer_requests SET status='closed', updated_at=? WHERE id=?", (now, request_id))
    conn.execute("INSERT INTO customer_request_events (request_id, actor_user_id, status, message, created_at) VALUES (?,?,?,?,?)",
                 (request_id, user_id, "closed", f"پیشنهاد نسخه {q['version']} پذیرفته شد؛ سفارش {number} در انتظار پرداخت", now))
    return {"order": {"order_number": number, "status": "pending", "total_minor": q["total_minor"]}, "replayed": False}
