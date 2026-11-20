"""Numbered pro-forma from the caller's cart, valid PROFORMA_VALID_HOURS, with a no-surprise checkout guard."""
from __future__ import annotations

import datetime as _dt
import json
import secrets

from app.core.errors import ConflictError, NotFoundError
from app.services import cart_service, quote_service, shopping_mode

PROFORMA_VALID_HOURS = 72
DAILY_LIMIT = 30


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _org_of(conn, user_id: int):
    row = conn.execute("SELECT organization_id FROM organization_memberships WHERE user_id=? AND status='active' "
                       "ORDER BY id LIMIT 1", (user_id,)).fetchone()
    return int(row["organization_id"]) if row else None


def create(conn, *, user_id: int, now: _dt.datetime | None = None, mode: str = shopping_mode.PERSONAL) -> dict:
    now = now or _now()
    if conn.execute("SELECT COUNT(*) FROM proformas WHERE user_id=? AND created_at>?",
                    (user_id, _iso(now - _dt.timedelta(days=1)))).fetchone()[0] >= DAILY_LIMIT:
        raise ConflictError(f"حداکثر {DAILY_LIMIT} پیش‌فاکتور در روز", code="proforma_rate_limited")
    mode = shopping_mode.parse(mode)
    shopping_mode.require(conn, user_id, mode)
    cart = cart_service.read_cart(conn, user_id, mode=mode)
    if not cart["items"]:
        raise ConflictError("سبد خرید خالی است", code="cart_empty")
    quote = quote_service.build_quote(conn, user_id=user_id, mode=mode)
    snapshot = {
        "items": [{k: i[k] for k in ("product_id", "title_fa", "sku", "quantity", "unit_price_minor", "line_total_minor")}
                  for i in cart["items"]],
        "subtotal_minor": quote["cart"]["subtotal_minor"], "shipping_fee_minor": quote["cart"]["shipping_fee_minor"],
        "tax_minor": quote["tax_minor"], "total_minor": quote["cart"]["total_minor"],
        "shopping_mode": mode,
    }
    number = f"PF-{now:%y%m%d}-{secrets.token_hex(3).upper()}"
    conn.execute("INSERT INTO proformas (number, user_id, organization_id, snapshot_json, total_minor, created_at, valid_until) "
                 "VALUES (?,?,?,?,?,?,?)", (number, user_id, _org_of(conn, user_id), json.dumps(snapshot, ensure_ascii=False),
                                          snapshot["total_minor"], _iso(now),
                                          _iso(now + _dt.timedelta(hours=PROFORMA_VALID_HOURS))))
    return get(conn, user_id=user_id, number=number)


def get(conn, *, user_id: int, number: str) -> dict:
    row = conn.execute("SELECT p.*, o.legal_name FROM proformas p LEFT JOIN organizations o ON o.id=p.organization_id "
                       "WHERE p.number=? AND p.user_id=?", (number, user_id)).fetchone()
    if row is None:
        raise NotFoundError("پیش‌فاکتور یافت نشد", code="proforma_not_found")
    return {"number": row["number"], "organization": row["legal_name"], "created_at": row["created_at"],
            "valid_until": row["valid_until"], "expired": row["valid_until"] <= _iso(_now()),
            "used": row["used_order_id"] is not None, **json.loads(row["snapshot_json"])}


def list_for_user(conn, *, user_id: int, date_from: str | None = None, date_to: str | None = None,
                  limit: int = 200) -> list[dict]:
    """The caller's own pro-formas, newest first (owner-scoped; dates are YYYY-MM-DD, inclusive)."""
    sql = ("SELECT p.number, p.created_at, p.valid_until, p.used_order_id, p.total_minor, p.snapshot_json, o.legal_name "
           "FROM proformas p LEFT JOIN organizations o ON o.id=p.organization_id WHERE p.user_id=?")
    args: list = [user_id]
    if date_from:
        sql += " AND p.created_at>=?"; args.append(f"{date_from}T00:00:00Z")
    if date_to:
        sql += " AND p.created_at<=?"; args.append(f"{date_to}T23:59:59Z")
    sql += " ORDER BY p.created_at DESC, p.id DESC LIMIT ?"; args.append(max(1, min(int(limit), 200)))
    now = _iso(_now())
    return [{"number": r["number"], "organization": r["legal_name"], "created_at": r["created_at"],
             "valid_until": r["valid_until"], "expired": r["valid_until"] <= now, "used": r["used_order_id"] is not None,
             "total_minor": r["total_minor"], "item_count": len(json.loads(r["snapshot_json"]).get("items", []))}
            for r in conn.execute(sql, args).fetchall()]


def guard_checkout(conn, *, user_id: int, number: str, mode: str = shopping_mode.PERSONAL) -> None:
    """Refuse a checkout that would cost more than the approved pro-forma (cheaper is fine)."""
    pf = get(conn, user_id=user_id, number=number)
    if pf["expired"]:
        raise ConflictError("مهلت این پیش‌فاکتور تمام شده است؛ پیش‌فاکتور تازه بگیرید", code="proforma_expired")
    if (pf.get("shopping_mode") or shopping_mode.PERSONAL) != mode:  # snapshots before 0084 were personal carts
        raise ConflictError("این پیش‌فاکتور برای سبد حالت خرید دیگری صادر شده است", code="proforma_mode_mismatch")
    total = quote_service.build_quote(conn, user_id=user_id, mode=mode)["cart"]["total_minor"]
    if total > pf["total_minor"]:
        raise ConflictError(f"مبلغ سبد ({total:,} ریال) از پیش‌فاکتور تأییدشده ({pf['total_minor']:,} ریال) بیشتر شده است؛ "
                            "سبد یا قیمت‌ها تغییر کرده‌اند", code="proforma_price_changed",
                            details={"proforma_total_minor": pf["total_minor"], "current_total_minor": total})
