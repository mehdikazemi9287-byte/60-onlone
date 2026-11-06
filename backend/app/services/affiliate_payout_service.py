"""تسویه با همکاران فروش (affiliate payouts).

Rules:
- Money goes only to a Sheba an admin has verified. Changing the Sheba clears verification and is refused while a
  payout is in flight.
- An earning is payable when: still 'pending', not in a payout, past available_at (return window), not held by an
  open return, and its amount after proportional reversals is > 0 (affiliate_service.settle_returns).
- A batch gathers, per verified active affiliate with no unsettled payout, every payable earning whose sum reaches
  AFFILIATE_MIN_PAYOUT_MINOR (default 1,000,000 rial = 100,000 toman). One payout per affiliate per batch.
- Paid → its earnings become 'paid'. Failed → earnings return to the balance and the Sheba must be verified again.
Everything is integer rial.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import secrets
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import audit_service
from app.services.affiliate_service import settle_returns
from app.services.seller_shop_service import valid_sheba


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def min_payout_minor() -> int:
    try:
        return max(1, int(os.environ.get("AFFILIATE_MIN_PAYOUT_MINOR", "1000000")))
    except ValueError:
        return 1_000_000


def mask(sheba: str | None) -> str | None:
    return f"IR{'*' * 18}{sheba[-6:]}" if sheba else None


def _affiliate_by_user(conn, user_id: int):
    a = conn.execute("SELECT * FROM affiliates WHERE user_id=?", (user_id,)).fetchone()
    if a is None:
        raise NotFoundError("هنوز عضو همکاری در فروش نیستی", code="affiliate_not_found")
    return a


def set_sheba(conn: sqlite3.Connection, *, user_id: int, sheba, holder) -> dict:
    a = _affiliate_by_user(conn, user_id)
    v = (sheba or "").replace(" ", "").upper() if isinstance(sheba, str) else ""
    if not valid_sheba(v):
        raise ValidationError("شمارهٔ شبا معتبر نیست (IR و ۲۴ رقم)", code="invalid_sheba")
    h = holder.strip() if isinstance(holder, str) else ""
    if not 2 <= len(h) <= 120:
        raise ValidationError("نام صاحب حساب لازم است", code="holder_required")
    if conn.execute("SELECT 1 FROM affiliate_payouts WHERE affiliate_id=? AND status='pending'", (a["id"],)).fetchone():
        raise ConflictError("تا تسویهٔ در جریان تمام نشده، شبا را نمی‌توان عوض کرد", code="payout_in_progress")
    conn.execute("UPDATE affiliates SET sheba=?, sheba_holder=?, sheba_verified_at=NULL, sheba_updated_at=? WHERE id=?",
                 (v, h, _now(), a["id"]))
    audit_service.record(conn, action="affiliate.sheba_changed", entity_type="affiliate", entity_id=int(a["id"]),
                         actor_user_id=user_id, metadata={"sheba_tail": v[-6:]})
    return {"sheba": mask(v), "holder": h, "verified": False}


def verify_sheba(conn: sqlite3.Connection, *, affiliate_id: int, actor_user_id: int) -> dict:
    a = conn.execute("SELECT id, sheba FROM affiliates WHERE id=?", (affiliate_id,)).fetchone()
    if a is None:
        raise NotFoundError("همکار یافت نشد", code="affiliate_not_found")
    if not a["sheba"]:
        raise ConflictError("همکار هنوز شبا ثبت نکرده است", code="sheba_missing")
    conn.execute("UPDATE affiliates SET sheba_verified_at=? WHERE id=?", (_now(), affiliate_id))
    audit_service.record(conn, action="affiliate.sheba_verified", entity_type="affiliate", entity_id=affiliate_id,
                         actor_user_id=actor_user_id, metadata={"sheba_tail": a["sheba"][-6:]})
    return {"id": affiliate_id, "verified": True}


def payable(conn, affiliate_id: int, now: str | None = None) -> list[tuple[int, int]]:
    """[(earning_id, amount)] ready to pay for this affiliate."""
    stamp = now or _now()
    out = []
    for r in conn.execute("SELECT * FROM affiliate_earnings WHERE affiliate_id=? AND status='pending' AND payout_id IS NULL "
                          "AND available_at<=? ORDER BY id", (affiliate_id, stamp)).fetchall():
        amount, state = settle_returns(conn, r)
        if state == "pending" and amount > 0:
            out.append((int(r["id"]), amount))
    return out


def balances(conn, affiliate_id: int, now: str | None = None) -> dict:
    stamp = now or _now()
    pending = available = in_payout = paid = 0
    for r in conn.execute("SELECT * FROM affiliate_earnings WHERE affiliate_id=?", (affiliate_id,)).fetchall():
        amount, state = settle_returns(conn, r)
        if state == "paid":
            paid += amount
        elif state == "reversed":
            continue
        elif r["payout_id"] is not None:
            in_payout += amount
        elif state == "pending" and r["available_at"] <= stamp:
            available += amount
        else:
            pending += amount
    return {"pending_minor": pending, "available_minor": available, "in_payout_minor": in_payout, "paid_minor": paid}


def preview(conn, now: str | None = None) -> dict:
    stamp, floor = now or _now(), min_payout_minor()
    ready, waiting = [], []
    for a in conn.execute("SELECT id, code, sheba, sheba_holder, sheba_verified_at FROM affiliates WHERE status='active' "
                          "ORDER BY id").fetchall():
        if conn.execute("SELECT 1 FROM affiliate_payouts WHERE affiliate_id=? AND status='pending'", (a["id"],)).fetchone():
            continue
        total = sum(x for _, x in payable(conn, int(a["id"]), stamp))
        if total <= 0:
            continue
        row = {"affiliate_id": int(a["id"]), "code": a["code"], "amount_minor": total, "sheba": mask(a["sheba"]),
               "holder": a["sheba_holder"]}
        if not a["sheba"]:
            waiting.append({**row, "reason": "no_sheba"})
        elif not a["sheba_verified_at"]:
            waiting.append({**row, "reason": "sheba_unverified"})
        elif total < floor:
            waiting.append({**row, "reason": "below_minimum"})
        else:
            ready.append(row)
    return {"min_payout_minor": floor, "ready": ready, "waiting": waiting,
            "ready_total_minor": sum(r["amount_minor"] for r in ready)}


def create_batch(conn: sqlite3.Connection, *, actor_user_id: int, now: str | None = None) -> dict:
    stamp = now or _now()
    plan = preview(conn, stamp)
    if not plan["ready"]:
        raise ConflictError("فعلاً پورسانتی آمادهٔ پرداخت نیست", code="nothing_to_pay")
    ref = "AFP-" + stamp[:10].replace("-", "") + "-" + secrets.token_hex(3).upper()
    batch_id = int(conn.execute("INSERT INTO affiliate_payout_batches (reference, created_by_user_id, created_at) VALUES (?,?,?)",
                                (ref, actor_user_id, stamp)).lastrowid)
    total = 0
    for row in plan["ready"]:
        a = conn.execute("SELECT sheba, sheba_holder FROM affiliates WHERE id=?", (row["affiliate_id"],)).fetchone()
        items = payable(conn, row["affiliate_id"], stamp)  # recomputed inside the same transaction
        amount = sum(x for _, x in items)
        if amount < plan["min_payout_minor"]:
            continue
        pid = int(conn.execute(
            "INSERT INTO affiliate_payouts (batch_id, affiliate_id, reference, amount_minor, sheba, holder, created_at) "
            "VALUES (?,?,?,?,?,?,?)", (batch_id, row["affiliate_id"], f"{ref}-{row['affiliate_id']}", amount, a["sheba"],
                                       a["sheba_holder"], stamp)).lastrowid)
        conn.executemany("UPDATE affiliate_earnings SET payout_id=? WHERE id=? AND payout_id IS NULL",
                         [(pid, eid) for eid, _ in items])
        total += amount
    count = conn.execute("SELECT COUNT(*) FROM affiliate_payouts WHERE batch_id=?", (batch_id,)).fetchone()[0]
    conn.execute("UPDATE affiliate_payout_batches SET total_minor=?, payout_count=? WHERE id=?", (total, count, batch_id))
    audit_service.record(conn, action="affiliate.payout_batch_created", entity_type="affiliate_payout_batch",
                         entity_id=batch_id, actor_user_id=actor_user_id, metadata={"total_minor": total, "count": count})
    return batch(conn, batch_id)


def batch(conn, batch_id: int) -> dict:
    b = conn.execute("SELECT * FROM affiliate_payout_batches WHERE id=?", (batch_id,)).fetchone()
    if b is None:
        raise NotFoundError("دستهٔ تسویه یافت نشد", code="batch_not_found")
    payouts = [{**dict(p), "sheba": mask(p["sheba"])} for p in conn.execute(
        "SELECT p.id, p.reference, p.affiliate_id, a.code, p.amount_minor, p.sheba, p.holder, p.status, p.bank_reference, "
        "p.failure_reason, p.settled_at FROM affiliate_payouts p JOIN affiliates a ON a.id=p.affiliate_id "
        "WHERE p.batch_id=? ORDER BY p.id", (batch_id,))]
    return {**dict(b), "payouts": payouts}


def list_batches(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM affiliate_payout_batches ORDER BY id DESC LIMIT 100")]


def export_csv(conn, *, batch_id: int, actor_user_id: int) -> str:
    """Bank transfer sheet (full Sheba, admin only). Formula-looking cells are neutralised."""
    from app.adapters.accounting.finance_formats import safe_cell
    batch(conn, batch_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reference", "sheba", "holder", "amount_rial", "description"])
    for p in conn.execute("SELECT reference, sheba, holder, amount_minor FROM affiliate_payouts WHERE batch_id=? AND status='pending' "
                          "ORDER BY id", (batch_id,)):
        w.writerow([safe_cell(p["reference"]), safe_cell(p["sheba"]), safe_cell(p["holder"]), p["amount_minor"],
                    safe_cell("پورسانت همکاری در فروش شصت آنلاین")])
    conn.execute("UPDATE affiliate_payout_batches SET status=CASE WHEN status='open' THEN 'exported' ELSE status END, "
                 "exported_at=COALESCE(exported_at, ?) WHERE id=?", (_now(), batch_id))
    audit_service.record(conn, action="affiliate.payout_batch_exported", entity_type="affiliate_payout_batch",
                         entity_id=batch_id, actor_user_id=actor_user_id, metadata={})
    return "﻿" + buf.getvalue()


def _payout(conn, payout_id: int):
    p = conn.execute("SELECT * FROM affiliate_payouts WHERE id=?", (payout_id,)).fetchone()
    if p is None:
        raise NotFoundError("پرداخت یافت نشد", code="payout_not_found")
    if p["status"] != "pending":
        raise ConflictError("وضعیت این پرداخت قبلاً ثبت شده است", code="payout_settled")
    return p


def _close_batch_if_done(conn, batch_id: int) -> None:
    if not conn.execute("SELECT 1 FROM affiliate_payouts WHERE batch_id=? AND status='pending'", (batch_id,)).fetchone():
        conn.execute("UPDATE affiliate_payout_batches SET status='closed' WHERE id=?", (batch_id,))


def mark_paid(conn: sqlite3.Connection, *, payout_id: int, bank_reference, actor_user_id: int) -> dict:
    p = _payout(conn, payout_id)
    ref = bank_reference.strip() if isinstance(bank_reference, str) else ""
    if not 4 <= len(ref) <= 64:
        raise ValidationError("شمارهٔ پیگیری بانک لازم است", code="bank_reference_required")
    stamp = _now()
    conn.execute("UPDATE affiliate_payouts SET status='paid', bank_reference=?, settled_at=? WHERE id=?", (ref, stamp, payout_id))
    conn.execute("UPDATE affiliate_earnings SET status='paid' WHERE payout_id=? AND status='pending'", (payout_id,))
    _close_batch_if_done(conn, int(p["batch_id"]))
    audit_service.record(conn, action="affiliate.payout_paid", entity_type="affiliate_payout", entity_id=payout_id,
                         actor_user_id=actor_user_id, metadata={"amount_minor": int(p["amount_minor"]), "bank_reference": ref})
    return {"id": payout_id, "status": "paid"}


def mark_failed(conn: sqlite3.Connection, *, payout_id: int, reason, actor_user_id: int) -> dict:
    p = _payout(conn, payout_id)
    why = reason.strip()[:300] if isinstance(reason, str) and reason.strip() else "نامشخص"
    stamp = _now()
    conn.execute("UPDATE affiliate_payouts SET status='failed', failure_reason=?, settled_at=? WHERE id=?", (why, stamp, payout_id))
    conn.execute("UPDATE affiliate_earnings SET payout_id=NULL WHERE payout_id=? AND status='pending'", (payout_id,))
    conn.execute("UPDATE affiliates SET sheba_verified_at=NULL WHERE id=?", (p["affiliate_id"],))  # likely a wrong account
    _close_batch_if_done(conn, int(p["batch_id"]))
    audit_service.record(conn, action="affiliate.payout_failed", entity_type="affiliate_payout", entity_id=payout_id,
                         actor_user_id=actor_user_id, metadata={"reason": why})
    return {"id": payout_id, "status": "failed"}


def unverified(conn) -> list[dict]:
    return [{"affiliate_id": int(r["id"]), "code": r["code"], "sheba": r["sheba"], "holder": r["sheba_holder"],
             "user_name": r["full_name"], "updated_at": r["sheba_updated_at"]}
            for r in conn.execute("SELECT a.id, a.code, a.sheba, a.sheba_holder, a.sheba_updated_at, u.full_name FROM affiliates a "
                                  "JOIN users u ON u.id=a.user_id WHERE a.sheba IS NOT NULL AND a.sheba_verified_at IS NULL "
                                  "AND a.status='active' ORDER BY a.sheba_updated_at")]


def my_payouts(conn, *, user_id: int) -> dict:
    a = _affiliate_by_user(conn, user_id)
    return {"sheba": mask(a["sheba"]), "holder": a["sheba_holder"], "verified": bool(a["sheba_verified_at"]),
            "min_payout_minor": min_payout_minor(), **balances(conn, int(a["id"])),
            "payouts": [dict(r) for r in conn.execute(
                "SELECT reference, amount_minor, status, bank_reference, created_at, settled_at FROM affiliate_payouts "
                "WHERE affiliate_id=? ORDER BY id DESC LIMIT 50", (a["id"],))]}
