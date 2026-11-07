"""Organization money reports that competitors give HR and finance (Amazon Business analytics, Tara/Digipay payroll).

- payroll_csv: each member's NET organization-credit use in a period, for HR. Deducting it from salary is the
  employer's own decision under its agreement with the employee; welfare budget is a benefit and never appears here.
- spend_csv: every line the organization bought in a period, by buyer, department, category and seller.
Formula-looking text is neutralised in both.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io

from app.adapters.accounting.finance_formats import safe_cell
from app.core.errors import ValidationError

MAX_DAYS = 370


def period(start, end) -> tuple[str, str]:
    """Inclusive YYYY-MM-DD dates → [start 00:00, end+1 00:00) as 'YYYY-MM-DD HH:MM:SS'."""
    try:
        a = _dt.date.fromisoformat(str(start))
        b = _dt.date.fromisoformat(str(end))
    except ValueError as exc:
        raise ValidationError("بازه باید به شکل YYYY-MM-DD باشد", details={"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}) from exc
    if b < a or (b - a).days > MAX_DAYS:
        raise ValidationError(f"بازه نامعتبر است (حداکثر {MAX_DAYS} روز)")
    return f"{a} 00:00:00", f"{b + _dt.timedelta(days=1)} 00:00:00"


def _ts(col: str) -> str:
    return f"REPLACE(SUBSTR({col}, 1, 19), 'T', ' ')"


def payroll_rows(conn, *, organization_id: int, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        f"""SELECT m.employee_code, u.full_name, m.department, e.user_id,
                   SUM(CASE WHEN e.entry_type='capture' THEN e.amount_minor
                            WHEN e.entry_type='adjustment' AND e.order_id IS NOT NULL THEN -e.amount_minor ELSE 0 END) AS used
            FROM credit_ledger_entries e
            JOIN users u ON u.id = e.user_id
            LEFT JOIN organization_memberships m ON m.organization_id = e.organization_id AND m.user_id = e.user_id
            WHERE e.organization_id = ? AND e.entry_type IN ('capture','adjustment')
              AND {_ts('e.created_at')} >= ? AND {_ts('e.created_at')} < ?
            GROUP BY e.user_id, m.employee_code, u.full_name, m.department
            ORDER BY u.full_name""", (organization_id, start, end)).fetchall()
    return [dict(r) for r in rows if int(r["used"] or 0) != 0]


def payroll_csv(conn, *, organization_id: int, start: str, end: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["employee_code", "full_name", "department", "credit_used_rial"])
    for r in payroll_rows(conn, organization_id=organization_id, start=start, end=end):
        w.writerow([safe_cell(r["employee_code"] or ""), safe_cell(r["full_name"]), safe_cell(r["department"] or ""),
                    int(r["used"])])
    return buf.getvalue()


def spend_csv(conn, *, organization_id: int, start: str, end: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "order_number", "buyer", "department", "product", "category", "seller", "quantity",
                "line_total_rial", "paid_with"])
    rows = conn.execute(
        f"""SELECT o.placed_at, o.order_number, u.full_name, m.department, oi.title_fa, c.name_fa AS category,
                   s.display_name AS seller, oi.quantity, oi.line_total_minor, o.credit_minor, o.cash_minor,
                   COALESCE(o.welfare_minor, 0) AS welfare_minor
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id
            JOIN users u ON u.id = o.user_id
            LEFT JOIN organization_memberships m ON m.organization_id = ? AND m.user_id = o.user_id
            LEFT JOIN products p ON p.id = oi.product_id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN fulfillment_order_items fi ON fi.order_item_id = oi.id
            LEFT JOIN fulfillment_orders fo ON fo.id = fi.fulfillment_order_id
            LEFT JOIN suppliers s ON s.id = fo.supplier_id
            WHERE (o.organization_id = ? OR o.id IN (SELECT order_id FROM credit_ledger_entries
                                                     WHERE organization_id = ? AND order_id IS NOT NULL))
              AND {_ts('o.placed_at')} >= ? AND {_ts('o.placed_at')} < ?
            ORDER BY o.placed_at, o.id, oi.id""",
        (organization_id, organization_id, organization_id, start, end)).fetchall()
    for r in rows:
        parts = [n for n, v in (("credit", r["credit_minor"]), ("welfare", r["welfare_minor"]),
                                ("card", int(r["cash_minor"] or 0) - int(r["welfare_minor"] or 0))) if int(v or 0) > 0]
        w.writerow([str(r["placed_at"])[:10], safe_cell(r["order_number"]), safe_cell(r["full_name"]),
                    safe_cell(r["department"] or ""), safe_cell(r["title_fa"]), safe_cell(r["category"] or ""),
                    safe_cell(r["seller"] or ""), int(r["quantity"]), int(r["line_total_minor"]), "+".join(parts)])
    return buf.getvalue()
