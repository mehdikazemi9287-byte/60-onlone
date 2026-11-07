"""Bring your own customer (Faire Direct pattern) — 0% commission on buyers a seller brings to the platform itself.

Why: in a closed ecosystem the fastest supply of buyers is the sellers' own offline customers. A seller will only move
them online if doing so costs nothing; the platform still gains the buyer, the data and every OTHER seller's sale to
that buyer (which stay commissionable).
"""
from __future__ import annotations

import datetime as _dt
import secrets

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import audit_service

INVITE_TTL_DAYS = 30
DAILY_INVITES = 50


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_invite(conn, *, supplier_id: int, actor_user_id: int, note=None, now: _dt.datetime | None = None) -> dict:
    now = now or _now()
    day_ago = _iso(now - _dt.timedelta(days=1))
    if conn.execute("SELECT COUNT(*) FROM seller_direct_invites WHERE supplier_id=? AND created_at>?",
                    (supplier_id, day_ago)).fetchone()[0] >= DAILY_INVITES:
        raise ConflictError(f"حداکثر {DAILY_INVITES} دعوت در روز", code="invite_rate_limited")
    if note is not None and (not isinstance(note, str) or len(note) > 200):
        raise ValidationError("یادداشت حداکثر ۲۰۰ نویسه", details={"note": "<=200"})
    code = secrets.token_urlsafe(9)
    conn.execute("INSERT INTO seller_direct_invites (supplier_id, code, note, created_by, created_at, expires_at) "
                 "VALUES (?,?,?,?,?,?)", (supplier_id, code, (note or "").strip() or None, actor_user_id, _iso(now),
                                          _iso(now + _dt.timedelta(days=INVITE_TTL_DAYS))))
    return {"code": code, "path": f"/join/{code}", "expires_days": INVITE_TTL_DAYS}


def invite_info(conn, *, code: str) -> dict:
    row = conn.execute("SELECT i.expires_at, i.claimed_at, s.display_name, s.shop_slug FROM seller_direct_invites i "
                       "JOIN suppliers s ON s.id=i.supplier_id WHERE i.code=?", (code,)).fetchone()
    if row is None or row["claimed_at"] or row["expires_at"] <= _iso(_now()):
        raise NotFoundError("این دعوت معتبر نیست یا استفاده شده است", code="invite_invalid")
    return {"seller": row["display_name"], "shop_slug": row["shop_slug"]}


def claim(conn, *, code: str, user_id: int, now: _dt.datetime | None = None) -> dict:
    now = now or _now()
    inv = conn.execute("SELECT * FROM seller_direct_invites WHERE code=?", (code,)).fetchone()
    if inv is None or inv["claimed_at"] or inv["expires_at"] <= _iso(now):
        raise NotFoundError("این دعوت معتبر نیست یا استفاده شده است", code="invite_invalid")
    sid = int(inv["supplier_id"])
    from app.services.access_admin_service import supplier_accounts
    if sid in [a["id"] for a in supplier_accounts(conn, user_id)]:
        raise ConflictError("فروشنده نمی‌تواند خودش را دعوت کند", code="self_invite")
    if conn.execute("SELECT 1 FROM seller_direct_customers WHERE supplier_id=? AND user_id=?", (sid, user_id)).fetchone():
        raise ConflictError("شما از قبل مشتری مستقیم این فروشنده هستید", code="already_linked")
    # A buyer the platform already brought to this seller is not the seller's to claim.
    if conn.execute("SELECT 1 FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
                    "WHERE fo.supplier_id=? AND o.user_id=? LIMIT 1", (sid, user_id)).fetchone():
        raise ConflictError("شما قبلاً از طریق شصت آنلاین از این فروشنده خرید کرده‌اید؛ این دعوت برای مشتریان تازه است",
                            code="existing_platform_customer")
    cur = conn.execute("UPDATE seller_direct_invites SET claimed_by=?, claimed_at=? WHERE id=? AND claimed_at IS NULL",
                       (user_id, _iso(now), int(inv["id"])))
    if cur.rowcount != 1:
        raise NotFoundError("این دعوت معتبر نیست یا استفاده شده است", code="invite_invalid")
    conn.execute("INSERT INTO seller_direct_customers (supplier_id, user_id, invite_id, linked_at) VALUES (?,?,?,?)",
                 (sid, user_id, int(inv["id"]), _iso(now)))
    audit_service.record(conn, action="seller_direct.claimed", entity_type="supplier", entity_id=sid,
                         actor_user_id=user_id, metadata={"invite_id": int(inv["id"])})
    return {"supplier_id": sid, "linked": True}


def is_direct(conn, *, supplier_id: int, user_id: int | None) -> bool:
    if not user_id:
        return False
    return conn.execute("SELECT 1 FROM seller_direct_customers WHERE supplier_id=? AND user_id=?",
                        (supplier_id, user_id)).fetchone() is not None


def my_customers(conn, *, supplier_id: int) -> dict:
    rows = conn.execute(
        "SELECT c.user_id, c.linked_at, u.full_name, "
        "(SELECT COUNT(*) FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
        " WHERE fo.supplier_id=c.supplier_id AND o.user_id=c.user_id) AS orders "
        "FROM seller_direct_customers c JOIN users u ON u.id=c.user_id WHERE c.supplier_id=? ORDER BY c.id DESC",
        (supplier_id,)).fetchall()
    open_invites = conn.execute("SELECT COUNT(*) FROM seller_direct_invites WHERE supplier_id=? AND claimed_at IS NULL "
                                "AND expires_at>?", (supplier_id, _iso(_now()))).fetchone()[0]
    return {"items": [dict(r) for r in rows], "open_invites": int(open_invites)}
