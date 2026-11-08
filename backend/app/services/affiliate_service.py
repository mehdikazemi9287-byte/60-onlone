"""همکاری در فروش (affiliate program), after Digikala (about 3% of monthly sales) and Basalam.

- Anyone (an organization employee, a content creator, a shop itself) creates a personal code;
  links look like /?ref=CODE. A logged-in buyer's landing is recorded; the last referral within
  7 days wins. Self-referral earns nothing.
- When a seller part of an order is delivered and its payable is recorded, an earning is
  accrued: platform base rate (by category) paid out of the platform's commission — never more
  than the commission itself — plus the seller's optional extra rate, which is added to that
  payable's commission so it comes out of the seller's share.
- Earnings become withdrawable only after the payable's escrow/withdrawal window and while no
  return or withdrawal is open; a return reverses them.
"""
from __future__ import annotations

import datetime as _dt
import re
import json
import secrets
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError

REFERRAL_DAYS = 7
_CODE = re.compile(r"^[A-Za-z0-9]{4,24}$")
_OPEN_RETURN = ("requested", "approved", "received", "refund_pending")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


AFFILIATE_TERMS_VERSION = "draft-1405-1"  # bump when /terms/affiliate changes; members re-accept on next join call


def join(conn: sqlite3.Connection, *, user_id: int, code: str | None = None, accept_terms: bool = False) -> dict:
    row = conn.execute("SELECT * FROM affiliates WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return dict(row)
    if accept_terms is not True:
        raise ValidationError("برای پیوستن، پذیرش قوانین همکاری در فروش لازم است", code="terms_required")
    if code is not None:
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValidationError("کد معرف فقط حروف و عدد لاتین، ۴ تا ۲۴ نویسه", details={"field": "code"})
        if conn.execute("SELECT 1 FROM affiliates WHERE lower(code)=lower(?)", (code,)).fetchone():
            raise ConflictError("این کد قبلاً گرفته شده است", code="affiliate_code_taken")
    else:
        code = "R" + secrets.token_hex(4).upper()
    conn.execute("INSERT INTO affiliates (user_id, code, terms_version, terms_accepted_at) VALUES (?,?,?,?)",
                 (user_id, code, AFFILIATE_TERMS_VERSION, _iso(_now())))
    return dict(conn.execute("SELECT * FROM affiliates WHERE user_id=?", (user_id,)).fetchone())


def record_landing(conn: sqlite3.Connection, *, buyer_user_id: int, code: str, now: _dt.datetime | None = None) -> dict:
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValidationError("کد معرف نامعتبر است")
    a = conn.execute("SELECT id, user_id FROM affiliates WHERE lower(code)=lower(?) AND status='active'", (code,)).fetchone()
    if a is None:
        raise NotFoundError("کد معرف یافت نشد")
    if a["user_id"] == buyer_user_id:
        return {"recorded": False, "reason": "self_referral"}
    t = now or _now()
    conn.execute("INSERT INTO affiliate_referrals (buyer_user_id, affiliate_id, landed_at, expires_at) VALUES (?,?,?,?)",
                 (buyer_user_id, a["id"], _iso(t), _iso(t + _dt.timedelta(days=REFERRAL_DAYS))))
    return {"recorded": True, "expires_in_days": REFERRAL_DAYS}


def _rate_bps(conn: sqlite3.Connection, category_id: int | None) -> int:
    row = conn.execute("SELECT rate_bps FROM affiliate_rates WHERE category_id=? ORDER BY id DESC LIMIT 1",
                       (category_id,)).fetchone() if category_id is not None else None
    row = row or conn.execute("SELECT rate_bps FROM affiliate_rates WHERE category_id IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return int(row["rate_bps"]) if row else 0


def accrue(conn: sqlite3.Connection, *, fulfillment_order_id: int, payable_entry_id: int,
           commission_minor: int, available_at: str | None) -> dict | None:
    """Called when a delivered seller part's payable is recorded (same transaction).

    Returns the earning or None. Increases the payable's commission by the seller-paid part.
    """
    fo = conn.execute("SELECT fo.order_id, fo.supplier_id, fo.affiliate_bonus_bps, o.user_id, o.placed_at AS created_at FROM fulfillment_orders fo "
                      "JOIN orders o ON o.id=fo.order_id WHERE fo.id=?", (fulfillment_order_id,)).fetchone()
    if fo is None or conn.execute("SELECT 1 FROM affiliate_earnings WHERE fulfillment_order_id=?",
                                  (fulfillment_order_id,)).fetchone():
        return None
    order_at = fo["created_at"].replace(" ", "T")[:19]
    ref = conn.execute(
        "SELECT r.affiliate_id, a.user_id FROM affiliate_referrals r JOIN affiliates a ON a.id=r.affiliate_id "
        "WHERE r.buyer_user_id=? AND a.status='active' AND substr(r.landed_at,1,19)<=? AND substr(r.expires_at,1,19)>=? "
        "ORDER BY r.id DESC LIMIT 1", (fo["user_id"], order_at, order_at)).fetchone()
    if ref is None or ref["user_id"] == fo["user_id"]:
        return None
    lines = conn.execute("SELECT p.category_id, COALESCE(i.line_selling_minor, 0) AS gross FROM fulfillment_order_items i "
                         "JOIN products p ON p.id=i.product_id WHERE i.fulfillment_order_id=?", (fulfillment_order_id,)).fetchall()
    gross = sum(int(l["gross"]) for l in lines)
    platform = sum(int(l["gross"]) * _rate_bps(conn, l["category_id"]) // 10_000 for l in lines)
    platform = min(platform, max(0, int(commission_minor)))  # never more than what the platform earns
    bonus_bps = fo["affiliate_bonus_bps"]  # snapshot taken when the order was placed (seller can't change it afterwards)
    if bonus_bps is None:  # parts created before the snapshot column existed
        bonus_bps = conn.execute("SELECT affiliate_bonus_bps FROM suppliers WHERE id=?", (fo["supplier_id"],)).fetchone()[0]
    seller = gross * int(bonus_bps or 0) // 10_000
    if platform + seller <= 0:
        return None
    if seller:
        conn.execute("UPDATE supplier_payable_entries SET commission_minor=COALESCE(commission_minor,0)+? WHERE id=?",
                     (seller, payable_entry_id))
    stamp = available_at or _iso(_now() + _dt.timedelta(days=REFERRAL_DAYS))
    conn.execute(
        "INSERT INTO affiliate_earnings (affiliate_id, fulfillment_order_id, order_id, gross_minor, platform_paid_minor, "
        "seller_paid_minor, available_at, reference) VALUES (?,?,?,?,?,?,?,?)",
        (ref["affiliate_id"], fulfillment_order_id, fo["order_id"], gross, platform, seller, stamp,
         "AF-" + secrets.token_hex(5).upper()))
    return dict(conn.execute("SELECT * FROM affiliate_earnings WHERE fulfillment_order_id=?", (fulfillment_order_id,)).fetchone())


def _returns_for_part(conn: sqlite3.Connection, fulfillment_order_id: int, order_id: int):
    """(open_hold, refunded_gross) for one seller part: only returns that touch this part's products count."""
    lines = {int(r["product_id"]): (int(r["quantity"]), int(r["gross"])) for r in conn.execute(
        "SELECT product_id, quantity, COALESCE(line_selling_minor,0) AS gross FROM fulfillment_order_items "
        "WHERE fulfillment_order_id=?", (fulfillment_order_id,))}
    held, refunded_qty = False, {}
    for rr in conn.execute("SELECT status, items_json FROM order_return_requests WHERE order_id=? AND status NOT IN "
                           "('rejected','cancelled')", (order_id,)):
        try:
            its = json.loads(rr["items_json"] or "[]")
        except ValueError:
            its = []
        for it in its:
            try:
                pid, q = int(it.get("product_id")), int(it.get("quantity") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            if pid not in lines or q <= 0:
                continue
            if rr["status"] in _OPEN_RETURN:
                held = True
            elif rr["status"] == "refunded":
                refunded_qty[pid] = refunded_qty.get(pid, 0) + q
    refunded = sum(g * min(refunded_qty.get(pid, 0), q) // q for pid, (q, g) in lines.items() if q)
    return held, refunded


def settle_returns(conn: sqlite3.Connection, r) -> tuple[int, str]:
    """Apply refunded returns of this part to the earning, in proportion, and persist it. Returns (amount, state)."""
    total = int(r["platform_paid_minor"]) + int(r["seller_paid_minor"])
    if r["status"] != "pending" or ("payout_id" in r.keys() and r["payout_id"] is not None):
        # settled, or frozen inside a payout batch (amount was fixed when the batch was made)
        return max(0, total - int(r["reversed_minor"] or 0)), ("in_payout" if r["status"] == "pending" else r["status"])
    held, refunded_gross = _returns_for_part(conn, r["fulfillment_order_id"], r["order_id"])
    gross = int(r["gross_minor"])
    reversed_amt = total if gross <= 0 else min(total, total * min(refunded_gross, gross) // gross)
    status = "reversed" if reversed_amt >= total and total > 0 else "pending"
    if reversed_amt != int(r["reversed_minor"] or 0) or status != r["status"]:
        conn.execute("UPDATE affiliate_earnings SET reversed_minor=?, status=? WHERE id=? AND status='pending'",
                     (reversed_amt, status, r["id"]))
    if status == "reversed":
        return 0, "reversed"
    return total - reversed_amt, ("on_hold" if held else "pending")


def dashboard(conn: sqlite3.Connection, *, user_id: int, now: _dt.datetime | None = None) -> dict:
    a = conn.execute("SELECT * FROM affiliates WHERE user_id=?", (user_id,)).fetchone()
    if a is None:
        raise NotFoundError("هنوز عضو همکاری در فروش نیستی")
    stamp = _iso(now or _now())
    rows = conn.execute("SELECT * FROM affiliate_earnings WHERE affiliate_id=? ORDER BY id DESC LIMIT 200", (a["id"],)).fetchall()
    pending = available = paid = 0
    items = []
    for r in rows:
        amount, state = settle_returns(conn, r)
        if state == "pending" and r["available_at"] <= stamp:
            state = "available"
        if state == "available":
            available += amount
        elif state in ("pending", "on_hold"):
            pending += amount
        elif state == "paid":
            paid += amount
        items.append({"id": r["id"], "reference": r["reference"] or f"AF-{r['id']}", "amount_minor": amount, "state": state,
                      "available_at": r["available_at"]})  # neither buyer identity nor order id is shown to the referrer
    from app.services.affiliate_payout_service import balances  # totals over every earning, not only the listed 200
    return {"code": a["code"], "status": a["status"], "link_path": f"/?ref={a['code']}", **balances(conn, int(a["id"]), stamp),
            "items": items}


def set_seller_bonus(conn: sqlite3.Connection, *, supplier_id: int, bonus_bps: int) -> int:
    if type(bonus_bps) is not int or not 0 <= bonus_bps <= 2000:
        raise ValidationError("کمیسیون اضافهٔ معرف باید بین ۰ تا ۲۰۰۰ واحد پایه (۰ تا ۲۰٪) باشد")
    conn.execute("UPDATE suppliers SET affiliate_bonus_bps=? WHERE id=?", (bonus_bps, supplier_id))
    return bonus_bps
