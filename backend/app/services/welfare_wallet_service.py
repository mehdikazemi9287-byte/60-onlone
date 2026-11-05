"""Phase 4 — employee welfare wallet (کیف پول رفاهی).

An organization creates welfare plans: free (any product), category-limited or
product-limited, each with a per-employee cap and an expiry date. Usage is an
append-only ledger (welfare_ledger_entries): remaining = cap - spend + reversal.
`can_spend` answers, per cart line, how much welfare budget may pay for it.
"""
from __future__ import annotations

import secrets
from datetime import datetime

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services.credit_contract_service import _int, _utc, fmt, parse_ts

PLAN_TYPES = ("free", "category", "product")


def _plan_row(conn, plan_id: int, organization_id: int | None = None):
    row = conn.execute("SELECT * FROM welfare_plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None or (organization_id is not None and int(row["organization_id"]) != organization_id):
        raise NotFoundError("طرح رفاهی یافت نشد", code="welfare_plan_not_found")
    return row


def plan_dict(conn, row) -> dict:
    data = {k: row[k] for k in row.keys()}
    data.pop("idempotency_key", None)
    targets = conn.execute("SELECT category_slug, product_id FROM welfare_plan_targets WHERE plan_id = ?",
                           (int(row["id"]),)).fetchall()
    data["category_slugs"] = [t["category_slug"] for t in targets if t["category_slug"]]
    data["product_ids"] = [int(t["product_id"]) for t in targets if t["product_id"] is not None]
    return data


def create_plan(conn, *, organization_id: int, payload: dict, actor_user_id: int | None,
                idempotency_key: str, now: datetime | None = None) -> tuple[bool, dict]:
    if not idempotency_key:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    existing = conn.execute("SELECT * FROM welfare_plans WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if existing is not None:
        if int(existing["organization_id"]) != organization_id:
            raise ConflictError("کلید یکتایی برای سازمان دیگری استفاده شده است", code="idempotency_conflict")
        return False, plan_dict(conn, existing)
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValidationError("عنوان طرح لازم است", details={"title": "لازم"})
    plan_type = payload.get("plan_type", "free")
    if plan_type not in PLAN_TYPES:
        raise ValidationError("نوع طرح نامعتبر است", details={"plan_type": list(PLAN_TYPES)})
    cap = _int(payload.get("per_employee_cap_minor"), "per_employee_cap_minor")
    if not payload.get("expires_at"):
        raise ValidationError("تاریخ انقضای طرح لازم است", details={"expires_at": "لازم"})
    starts_at = fmt(parse_ts(payload["starts_at"])) if payload.get("starts_at") else fmt(_utc(now))
    expires_at = fmt(parse_ts(payload["expires_at"]))
    if expires_at <= starts_at:
        raise ValidationError("تاریخ انقضا باید بعد از شروع باشد", details={"expires_at": "نامعتبر"})
    slugs = [s for s in payload.get("category_slugs") or [] if isinstance(s, str) and s.strip()]
    products = payload.get("product_ids") or []
    if plan_type == "category" and not slugs:
        raise ValidationError("برای طرح دسته‌ای حداقل یک دسته لازم است", details={"category_slugs": "لازم"})
    if plan_type == "product" and not products:
        raise ValidationError("برای طرح کالایی حداقل یک کالا لازم است", details={"product_ids": "لازم"})
    members = payload.get("membership_ids") or []
    stamp = fmt(_utc(now))
    cursor = conn.execute(
        """
        INSERT INTO welfare_plans (reference, organization_id, title, plan_type, per_employee_cap_minor,
            starts_at, expires_at, all_members, status, idempotency_key, created_by_user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?, 'active', ?,?,?,?)
        """,
        (f"WP-{secrets.token_hex(6).upper()}", organization_id, title, plan_type, cap, starts_at, expires_at,
         0 if members else 1, idempotency_key, actor_user_id, stamp, stamp),
    )
    plan_id = int(cursor.lastrowid)
    if plan_type == "category":
        for slug in slugs:
            conn.execute("INSERT INTO welfare_plan_targets (plan_id, category_slug) VALUES (?,?)", (plan_id, slug))
    if plan_type == "product":
        for pid in products:
            conn.execute("INSERT INTO welfare_plan_targets (plan_id, product_id) VALUES (?,?)",
                         (plan_id, _int(pid, "product_ids")))
    for mid in members:
        add_member(conn, plan_id=plan_id, organization_id=organization_id, membership_id=_int(mid, "membership_ids"))
    return True, plan_dict(conn, _plan_row(conn, plan_id))


def add_member(conn, *, plan_id: int, organization_id: int, membership_id: int, cap_minor: int | None = None) -> None:
    _plan_row(conn, plan_id, organization_id)
    m = conn.execute("SELECT id FROM organization_memberships WHERE id = ? AND organization_id = ?",
                     (membership_id, organization_id)).fetchone()
    if m is None:
        raise NotFoundError("عضو سازمان یافت نشد", code="membership_not_found")
    if cap_minor is not None:
        _int(cap_minor, "cap_minor")
    conn.execute("INSERT OR IGNORE INTO welfare_plan_members (plan_id, membership_id, cap_minor) VALUES (?,?,?)",
                 (plan_id, membership_id, cap_minor))
    conn.execute("UPDATE welfare_plans SET all_members = 0 WHERE id = ?", (plan_id,))


def close_plan(conn, *, plan_id: int, organization_id: int, now: datetime | None = None) -> dict:
    _plan_row(conn, plan_id, organization_id)
    conn.execute("UPDATE welfare_plans SET status = 'closed', updated_at = ? WHERE id = ?",
                 (fmt(_utc(now)), plan_id))
    return plan_dict(conn, _plan_row(conn, plan_id))


def list_plans(conn, organization_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM welfare_plans WHERE organization_id = ? ORDER BY id DESC",
                        (organization_id,)).fetchall()
    return [plan_dict(conn, r) for r in rows]


def _remaining(conn, plan, membership_id: int, cap: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN entry_type='spend' THEN amount_minor ELSE -amount_minor END),0) AS n "
        "FROM welfare_ledger_entries WHERE plan_id = ? AND membership_id = ?",
        (int(plan["id"]), membership_id),
    ).fetchone()
    return max(0, cap - int(row["n"]))


def eligible_plans(conn, membership_id: int, now: datetime | None = None) -> list[dict]:
    """Active, started, unexpired plans that cover this member, soonest-expiring first."""
    m = conn.execute("SELECT id, organization_id, status FROM organization_memberships WHERE id = ?",
                     (membership_id,)).fetchone()
    if m is None:
        raise NotFoundError("عضو سازمان یافت نشد", code="membership_not_found")
    if m["status"] != "active":
        return []
    stamp = fmt(_utc(now))
    rows = conn.execute(
        """
        SELECT p.*, pm.cap_minor AS member_cap, pm.id AS member_row
        FROM welfare_plans p
        LEFT JOIN welfare_plan_members pm ON pm.plan_id = p.id AND pm.membership_id = ?
        WHERE p.organization_id = ? AND p.status = 'active' AND p.starts_at <= ? AND p.expires_at > ?
        ORDER BY p.expires_at, p.id
        """,
        (membership_id, int(m["organization_id"]), stamp, stamp),
    ).fetchall()
    out = []
    for r in rows:
        if not r["all_members"] and r["member_row"] is None:
            continue
        cap = int(r["member_cap"]) if r["member_cap"] is not None else int(r["per_employee_cap_minor"])
        plan = plan_dict(conn, r)
        plan["cap_minor"] = cap
        plan["remaining_minor"] = _remaining(conn, r, membership_id, cap)
        out.append(plan)
    return out


def _line(conn, line) -> dict:
    get = line.get if isinstance(line, dict) else (lambda k, d=None: getattr(line, k, d))
    product_id = int(get("product_id"))
    total = get("line_total_minor")
    if total is None:
        total = int(get("unit_price_minor")) * int(get("quantity"))
    slug = get("category_slug")
    if slug is None:
        row = conn.execute("SELECT c.slug AS s FROM products p JOIN categories c ON c.id = p.category_id "
                           "WHERE p.id = ?", (product_id,)).fetchone()
        slug = row["s"] if row else ""
    return {"product_id": product_id, "category_slug": slug, "line_total_minor": int(total)}


def can_spend(conn, membership_id: int, cart_lines, now: datetime | None = None) -> dict:
    """Allowed welfare amount per cart line. Plans are drawn soonest-expiring first."""
    plans = eligible_plans(conn, membership_id, now)
    budget = {p["id"]: p["remaining_minor"] for p in plans}
    lines = []
    for raw in cart_lines:
        line = _line(conn, raw)
        need, uses = line["line_total_minor"], []
        for p in plans:
            if need <= 0:
                break
            covered = (p["plan_type"] == "free"
                       or (p["plan_type"] == "category" and line["category_slug"] in p["category_slugs"])
                       or (p["plan_type"] == "product" and line["product_id"] in p["product_ids"]))
            take = min(need, budget[p["id"]]) if covered else 0
            if take > 0:
                budget[p["id"]] -= take
                need -= take
                uses.append({"plan_id": p["id"], "amount_minor": take})
        line["allowed_minor"] = line["line_total_minor"] - need
        line["plans"] = uses
        lines.append(line)
    return {
        "membership_id": membership_id,
        "lines": lines,
        "total_allowed_minor": sum(l["allowed_minor"] for l in lines),
        "plans": [{"id": p["id"], "title": p["title"], "plan_type": p["plan_type"],
                   "expires_at": p["expires_at"], "remaining_minor": p["remaining_minor"]} for p in plans],
    }


def record_spend(conn, *, membership_id: int, cart_lines, idempotency_key: str, order_id: int | None = None,
                 now: datetime | None = None) -> dict:
    """Consume welfare budget for a cart. Idempotent on idempotency_key."""
    if not idempotency_key:
        raise ValidationError("کلید یکتایی لازم است", code="idempotency_key_required")
    prior = conn.execute("SELECT plan_id, amount_minor FROM welfare_ledger_entries WHERE idempotency_key = ? "
                         "AND entry_type = 'spend'", (idempotency_key,)).fetchall()
    if prior:
        return {"created": False, "total_minor": sum(int(r["amount_minor"]) for r in prior),
                "plans": [dict(r) for r in prior]}
    result = can_spend(conn, membership_id, cart_lines, now)
    per_plan: dict[int, int] = {}
    for line in result["lines"]:
        for use in line["plans"]:
            per_plan[use["plan_id"]] = per_plan.get(use["plan_id"], 0) + use["amount_minor"]
    stamp = fmt(_utc(now))
    for plan_id, amount in per_plan.items():
        conn.execute(
            "INSERT INTO welfare_ledger_entries (plan_id, membership_id, entry_type, amount_minor, order_id, "
            "idempotency_key, created_at) VALUES (?,?, 'spend', ?,?,?,?)",
            (plan_id, membership_id, amount, order_id, idempotency_key, stamp),
        )
    return {"created": True, "total_minor": sum(per_plan.values()),
            "plans": [{"plan_id": k, "amount_minor": v} for k, v in per_plan.items()]}


def member_summary(conn, user_id: int, now: datetime | None = None) -> dict:
    total = 0
    for m in conn.execute("SELECT id FROM organization_memberships WHERE user_id = ? AND status = 'active'",
                          (user_id,)).fetchall():
        total += sum(p["remaining_minor"] for p in eligible_plans(conn, int(m["id"]), now))
    return {"remaining_minor": total}
