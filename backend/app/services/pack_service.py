"""Saved shopping packs (Smart Pack Builder backend).

Honesty rules enforced here:
  * A pack line is "verified-priced" only when sale_eligibility returns a real
    eligible offer for that product — exactly the same test the storefront uses.
  * Pack totals sum ONLY verified-priced lines. Unpriced lines are reported
    explicitly and never folded into a fake total.
  * Every product reference is validated against the live catalog; no
    fabricated SKU, price, stock or availability.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from app.core.errors import NotFoundError, ValidationError
from app.services import sale_eligibility

MAX_ITEMS = 60
MAX_QTY = 999
VALID_KINDS = ("custom", "essentials", "gift", "seasonal", "organization")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _first_image(raw):
    if not raw:
        return None
    try:
        urls = json.loads(raw)
        return urls[0] if isinstance(urls, list) and urls else None
    except (TypeError, ValueError):
        return None


def _owned(db, user_id: int, pack_id: int):
    row = db.query_one("SELECT * FROM saved_packs WHERE id=? AND user_id=?", (pack_id, user_id))
    if row is None:
        raise NotFoundError("پک یافت نشد")
    return row


def _load_product(db, product_id: int):
    return db.query_one(
        """SELECT p.id, p.slug, p.title_fa, p.brand_fa, p.base_price_minor, p.is_active,
                  p.category_id, c.slug AS category_slug, c.name_fa AS category_name_fa,
                  COALESCE(i.quantity_available, 0) AS qty,
                  m.image_urls_json AS img
           FROM products p
           LEFT JOIN inventory i ON i.product_id = p.id
           LEFT JOIN categories c ON c.id = p.category_id
           LEFT JOIN master_products m ON m.id = p.master_product_id
           WHERE p.id = ?""",
        (product_id,),
    )


def _line_view(db, row, quantity: int, exponent: int):
    offer = sale_eligibility.eligible_offer_db(db, int(row["id"]))
    if offer is not None:
        unit_minor = int(offer["selling_price_minor"])
        price_status = "verified"
        purchase_status = "purchasable"
    else:
        unit_minor = None
        price_status = "unpriced"
        purchase_status = "inquiry-only"
    in_stock = int(row["qty"]) > 0
    line = {
        "product_id": int(row["id"]),
        "slug": row["slug"],
        "title": row["title_fa"],
        "brand": row["brand_fa"],
        "category_slug": row["category_slug"],
        "category_name": row["category_name_fa"],
        "quantity": quantity,
        "image_url": _first_image(row["img"]),
        "price_status": price_status,
        "purchase_status": purchase_status,
        "in_stock": in_stock,
        "unit_price_minor": unit_minor,
        "unit_price": (unit_minor / (10 ** exponent)) if unit_minor is not None else None,
        "line_total_minor": (unit_minor * quantity) if unit_minor is not None else None,
        "line_total": (unit_minor * quantity / (10 ** exponent)) if unit_minor is not None else None,
    }
    return line


def _pack_view(db, pack_row, exponent: int):
    items = db.query(
        "SELECT product_id, quantity FROM saved_pack_items WHERE pack_id=? ORDER BY id",
        (pack_row["id"],),
    )
    lines = []
    verified_subtotal_minor = 0
    unpriced = 0
    for it in items:
        prod = _load_product(db, int(it["product_id"]))
        if prod is None or not int(prod["is_active"]):
            lines.append({
                "product_id": int(it["product_id"]), "slug": None, "title": "کالای حذف‌شده",
                "quantity": int(it["quantity"]), "price_status": "unavailable",
                "purchase_status": "unavailable", "in_stock": False,
                "unit_price_minor": None, "unit_price": None,
                "line_total_minor": None, "line_total": None, "image_url": None,
                "brand": None, "category_slug": None, "category_name": None,
            })
            unpriced += 1
            continue
        line = _line_view(db, prod, int(it["quantity"]), exponent)
        if line["line_total_minor"] is not None:
            verified_subtotal_minor += line["line_total_minor"]
        else:
            unpriced += 1
        lines.append(line)
    return {
        "id": int(pack_row["id"]),
        "name": pack_row["name"],
        "kind": pack_row["kind"],
        "created_at": pack_row["created_at"],
        "updated_at": pack_row["updated_at"],
        "items": lines,
        "item_count": len(lines),
        "summary": {
            "verified_subtotal_minor": verified_subtotal_minor if verified_subtotal_minor else None,
            "verified_subtotal": (verified_subtotal_minor / (10 ** exponent)) if verified_subtotal_minor else None,
            "unpriced_item_count": unpriced,
            "has_unpriced": unpriced > 0,
            "all_purchasable": unpriced == 0 and len(lines) > 0,
            "currency": "IRR",
            "note": (
                "همه اقلام دارای قیمت تأییدشده هستند." if unpriced == 0 and lines
                else "این پک شامل کالاهای بدون قیمت تأییدشده است؛ جمع کل فقط از اقلام قیمت‌دار محاسبه شده و باقی اقلام «استعلامی» هستند."
            ),
        },
    }


def list_packs(db, user_id: int):
    rows = db.query(
        """SELECT sp.id, sp.name, sp.kind, sp.updated_at,
                  (SELECT COUNT(*) FROM saved_pack_items spi WHERE spi.pack_id = sp.id) AS item_count
           FROM saved_packs sp WHERE sp.user_id = ? ORDER BY sp.updated_at DESC, sp.id DESC""",
        (user_id,),
    )
    return [dict(r) for r in rows]


def get_pack(db, user_id: int, pack_id: int, exponent: int):
    return _pack_view(db, _owned(db, user_id, pack_id), exponent)


def create_pack(db, user_id: int, name: str, kind: str, exponent: int):
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationError("نام پک باید بین ۱ تا ۱۲۰ نویسه باشد")
    if kind not in VALID_KINDS:
        kind = "custom"
    if int(db.query_one("SELECT COUNT(*) AS c FROM saved_packs WHERE user_id=?", (user_id,))["c"]) >= 100:
        raise ValidationError("حداکثر تعداد پک ذخیره‌شده به سقف رسیده است")
    now = _now()
    cur = db.execute(
        "INSERT INTO saved_packs (user_id, name, kind, created_at, updated_at) VALUES (?,?,?,?,?)",
        (user_id, name, kind, now, now),
    )
    return _pack_view(db, _owned(db, user_id, int(cur.lastrowid)), exponent)


def rename_pack(db, user_id: int, pack_id: int, name: str, exponent: int):
    _owned(db, user_id, pack_id)
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationError("نام پک باید بین ۱ تا ۱۲۰ نویسه باشد")
    db.execute("UPDATE saved_packs SET name=?, updated_at=? WHERE id=?", (name, _now(), pack_id))
    return _pack_view(db, _owned(db, user_id, pack_id), exponent)


def delete_pack(db, user_id: int, pack_id: int):
    _owned(db, user_id, pack_id)
    db.execute("DELETE FROM saved_pack_items WHERE pack_id=?", (pack_id,))
    db.execute("DELETE FROM saved_packs WHERE id=?", (pack_id,))
    return {"deleted": pack_id}


def set_item(db, user_id: int, pack_id: int, product_id: int, quantity: int, exponent: int):
    _owned(db, user_id, pack_id)
    if not isinstance(product_id, int) or isinstance(product_id, bool):
        raise ValidationError("شناسه کالا نامعتبر است")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0 or quantity > MAX_QTY:
        raise ValidationError("تعداد نامعتبر است")
    if quantity == 0:
        db.execute("DELETE FROM saved_pack_items WHERE pack_id=? AND product_id=?", (pack_id, product_id))
        db.execute("UPDATE saved_packs SET updated_at=? WHERE id=?", (_now(), pack_id))
        return _pack_view(db, _owned(db, user_id, pack_id), exponent)
    prod = _load_product(db, product_id)
    if prod is None or not int(prod["is_active"]):
        raise NotFoundError("کالای فعال با این شناسه یافت نشد")
    count = int(db.query_one("SELECT COUNT(*) AS c FROM saved_pack_items WHERE pack_id=?", (pack_id,))["c"])
    exists = db.query_one("SELECT 1 FROM saved_pack_items WHERE pack_id=? AND product_id=?", (pack_id, product_id))
    if exists is None and count >= MAX_ITEMS:
        raise ValidationError(f"هر پک حداکثر {MAX_ITEMS} قلم می‌تواند داشته باشد")
    db.execute(
        """INSERT INTO saved_pack_items (pack_id, product_id, quantity, added_at) VALUES (?,?,?,?)
           ON CONFLICT(pack_id, product_id) DO UPDATE SET quantity=excluded.quantity""",
        (pack_id, product_id, quantity, _now()),
    )
    db.execute("UPDATE saved_packs SET updated_at=? WHERE id=?", (_now(), pack_id))
    return _pack_view(db, _owned(db, user_id, pack_id), exponent)


def remove_item(db, user_id: int, pack_id: int, product_id: int, exponent: int):
    _owned(db, user_id, pack_id)
    db.execute("DELETE FROM saved_pack_items WHERE pack_id=? AND product_id=?", (pack_id, product_id))
    db.execute("UPDATE saved_packs SET updated_at=? WHERE id=?", (_now(), pack_id))
    return _pack_view(db, _owned(db, user_id, pack_id), exponent)


def add_to_cart(db, user_id: int, pack_id: int, exponent: int):
    """Add only purchasable pack lines to the cart. Never forces an ineligible
    product through; each skip is reported with a reason."""
    from app.services import cart_service

    _owned(db, user_id, pack_id)
    view = _pack_view(db, _owned(db, user_id, pack_id), exponent)
    added, skipped = [], []
    for line in view["items"]:
        if line["purchase_status"] != "purchasable":
            skipped.append({"product_id": line["product_id"], "title": line["title"],
                            "reason": "این کالا فعلاً قابل خرید نیست (استعلامی یا بدون قیمت تأییدشده)"})
            continue
        try:
            cart_service.add_item(db, user_id=user_id, product_id=line["product_id"],
                                  quantity=min(line["quantity"], 20))
            added.append({"product_id": line["product_id"], "title": line["title"],
                          "quantity": min(line["quantity"], 20)})
        except Exception as exc:  # noqa: BLE001 - report, never fabricate success
            skipped.append({"product_id": line["product_id"], "title": line["title"],
                            "reason": str(getattr(exc, "message", exc))})
    return {"pack_id": pack_id, "added": added, "skipped": skipped,
            "cart_updated": bool(added)}


def create_proforma(db, user_id: int, pack_id: int, message: str, organization_id):
    """Turn a saved pack into an owned procurement request (پیش‌فاکتور).
    No price/quote is fabricated — staff respond later."""
    pack = _owned(db, user_id, pack_id)
    rows = db.query(
        """SELECT p.slug, p.title_fa, spi.quantity
           FROM saved_pack_items spi JOIN products p ON p.id = spi.product_id
           WHERE spi.pack_id = ? AND p.is_active = 1 ORDER BY spi.id""",
        (pack_id,),
    )
    if not rows:
        raise ValidationError("این پک قلم فعالی برای درخواست پیش‌فاکتور ندارد")
    if organization_id is not None:
        ok = db.query_one(
            "SELECT 1 FROM organization_memberships WHERE organization_id=? AND user_id=? AND status='active'",
            (organization_id, user_id),
        )
        if not ok:
            raise NotFoundError("عضویت فعال سازمانی یافت نشد")
    items = [{"slug": r["slug"], "title": r["title_fa"], "quantity": int(r["quantity"])} for r in rows]
    key = uuid.uuid4().hex
    payload = json.dumps({"pack_id": pack_id, "items": items}, ensure_ascii=False, sort_keys=True)
    now = _now()
    cur = db.execute(
        """INSERT INTO customer_requests
           (user_id, organization_id, kind, subject, message, items_json, status,
            idempotency_key, payload_hash, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, organization_id, "procurement",
         f"درخواست پیش‌فاکتور برای پک: {pack['name']}",
         (message or "").strip()[:4000] or "درخواست پیش‌فاکتور از پک ذخیره‌شده",
         json.dumps(items, ensure_ascii=False), "open",
         key, hashlib.sha256(payload.encode()).hexdigest(), now, now),
    )
    return {"request_id": int(cur.lastrowid), "kind": "procurement", "status": "open",
            "items": items, "subject": f"درخواست پیش‌فاکتور برای پک: {pack['name']}"}
