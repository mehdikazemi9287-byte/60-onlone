"""Finance Export Service — Phase 5B (درگاه‌های مخصوص نرم‌افزارهای مالی).

Builds the CANONICAL finance export for a period and an entity, then renders it
with a connector formatter (app.adapters.accounting.finance_formats).

Entities and the documents they get:
  platform      sales invoices (issued by sellers, platform acts as agent),
                commission invoices (platform → seller), receipts, settlement
                payouts, credit statements
  seller        its own sales invoices, the platform's commission invoices to
                it, its settlement payouts — nothing of any other seller
  organization  purchase invoices (its orders' seller invoices), its payments
                (receipts) and its credit statements

Invariants (enforced here, asserted in tests):
  * integer Rial only; VAT per line via tax_service (floor), header = Σ lines
  * every voucher balances: Σ debit == Σ credit
  * deterministic: no clocks/random in the model → same params, same bytes

Assumption (documented): seller line prices (fulfillment_order_items.
line_selling_minor) and supplier commission amounts are VAT-exclusive bases;
VAT is added at the tax_service rate in force on the document date.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

from app.adapters.accounting.finance_formats import get_finance_formatter
from app.core.errors import NotFoundError, ValidationError
from app.services.tax_service import calculate_line_tax_with_conn

SCHEMA = "60online.finance-export/1"
ENTITY_TYPES = ("platform", "seller", "organization")
ACCOUNT_KEYS = ("bank", "receivable", "credit_receivable", "vat_receivable", "seller_payable",
                "payable", "credit_payable", "vat_payable", "revenue", "commission_income",
                "purchases", "commission_expense")
INVOICEABLE_FO_STATUSES = ("accepted", "preparing", "ready", "dispatched", "delivered")
PLATFORM_PARTY = {"role": "platform", "id": None, "code": "P", "name": "۶۰آنلاین",
                  "national_id": "", "economic_code": ""}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _one(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def _date(v, field) -> str:
    try:
        return date.fromisoformat(str(v)[:10]).isoformat() if v and len(str(v)) == 10 else _bad(field)
    except ValueError:
        return _bad(field)


def _bad(field):
    raise ValidationError(f"تاریخ {field} نامعتبر است (YYYY-MM-DD)")


# ─────────────────────────────────────────────────────────────────────────────
# Account mappings
# ─────────────────────────────────────────────────────────────────────────────

def list_mappings(conn, connector: str | None = None) -> list[dict]:
    if connector:
        return _rows(conn, "SELECT * FROM finance_account_mappings WHERE connector=? ORDER BY account_key",
                     (connector.upper(),))
    return _rows(conn, "SELECT * FROM finance_account_mappings ORDER BY connector, account_key")


def upsert_mapping(conn, data: dict) -> dict:
    connector = str(data.get("connector") or "").upper().strip()
    key = str(data.get("account_key") or "").strip()
    code = str(data.get("account_code") or "").strip()
    name = str(data.get("account_name") or "").strip()[:200]
    if not connector or len(connector) > 40:
        raise ValidationError("نام درگاه (connector) الزامی است")
    if key not in ACCOUNT_KEYS:
        raise ValidationError(f"کلید حساب نامعتبر است. گزینه‌ها: {', '.join(ACCOUNT_KEYS)}")
    if not code or len(code) > 40:
        raise ValidationError("کد حساب الزامی است")
    now = _now()
    row = _one(conn, "SELECT id FROM finance_account_mappings WHERE connector=? AND account_key=?",
               (connector, key))
    if row:
        conn.execute("UPDATE finance_account_mappings SET account_code=?, account_name=?, updated_at=? "
                     "WHERE id=?", (code, name, now, row["id"]))
    else:
        conn.execute("INSERT INTO finance_account_mappings (connector, account_key, account_code, "
                     "account_name, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (connector, key, code, name, now, now))
    return _one(conn, "SELECT * FROM finance_account_mappings WHERE connector=? AND account_key=?",
                (connector, key))


def delete_mapping(conn, mapping_id: int) -> None:
    row = _one(conn, "SELECT connector FROM finance_account_mappings WHERE id=?", (mapping_id,))
    if row is None:
        raise NotFoundError("نگاشت حساب یافت نشد")
    if row["connector"] == "DEFAULT":
        raise ValidationError("نگاشت‌های پیش‌فرض حذف‌شدنی نیستند؛ آن‌ها را ویرایش کنید")
    conn.execute("DELETE FROM finance_account_mappings WHERE id=?", (mapping_id,))


def account_map(conn, connector: str) -> dict[str, str]:
    out = {r["account_key"]: r["account_code"] for r in list_mappings(conn, "DEFAULT")}
    out.update({r["account_key"]: r["account_code"] for r in list_mappings(conn, connector)})
    missing = [k for k in ACCOUNT_KEYS if k not in out]
    if missing:
        raise ValidationError(f"نگاشت حساب برای {', '.join(missing)} تعریف نشده است")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Parties
# ─────────────────────────────────────────────────────────────────────────────

def _supplier_party(s: dict) -> dict:
    return {"role": "seller", "id": s["id"], "code": f"S{s['id']}",
            "name": s.get("legal_name") or s.get("display_name") or "",
            "national_id": s.get("national_id") or "", "economic_code": s.get("national_id") or "",
            # شناسه ملی اشخاص حقوقی ۱۱ رقمی، کد ملی اشخاص حقیقی ۱۰ رقمی
            "legal": len(str(s.get("national_id") or "")) != 10}


def _buyer_party(conn, order: dict) -> dict:
    if order.get("organization_id"):
        o = _one(conn, "SELECT * FROM organizations WHERE id=?", (order["organization_id"],)) or {}
        return {"role": "organization", "id": order["organization_id"], "code": f"O{order['organization_id']}",
                "name": o.get("legal_name") or o.get("display_name") or "",
                "national_id": o.get("national_id") or "", "economic_code": o.get("economic_code") or "",
                "legal": True}
    return {"role": "customer", "id": order.get("user_id"), "code": f"U{order.get('user_id')}",
            "name": order.get("recipient_name") or "", "national_id": "", "economic_code": "",
            "legal": False}


# ─────────────────────────────────────────────────────────────────────────────
# Document building
# ─────────────────────────────────────────────────────────────────────────────

def _tax_category(conn, product_id, on: str) -> str:
    if not product_id:
        return "STANDARD"
    r = _one(conn, """SELECT c.code FROM tax_product_assignments a JOIN tax_categories c ON c.id=a.tax_category_id
                      WHERE a.product_id=? AND a.effective_from<=? AND (a.effective_until IS NULL OR a.effective_until>=?)
                      ORDER BY a.effective_from DESC LIMIT 1""", (product_id, on, on))
    return r["code"] if r else "STANDARD"


def _line(conn, *, line_no, code, description, quantity, unit_price, gross, discount=0, on,
          category="STANDARD", organization_id=None) -> dict:
    gross, discount, quantity, unit_price = int(gross), int(discount), int(quantity), int(unit_price)
    net = gross - discount
    tax = calculate_line_tax_with_conn(conn, subtotal_minor=net, tax_category_code=category,
                                       effective_date=on, organization_id=organization_id)
    return {"line_no": line_no, "code": str(code), "description": description, "quantity": quantity,
            "unit_price_minor": unit_price, "gross_minor": gross, "discount_minor": discount,
            "net_minor": net, "vat_rate_bps": int(tax["rate_bps"]), "vat_minor": int(tax["tax_minor"]),
            "total_minor": net + int(tax["tax_minor"])}


def _totals(lines) -> dict:
    keys = ("gross_minor", "discount_minor", "net_minor", "vat_minor", "total_minor")
    return {k: sum(ln[k] for ln in lines) for k in keys}


def _v(acc, key, detail, debit, credit, description):
    return {"account_key": key, "account_code": acc[key], "detail_code": detail,
            "debit_minor": int(debit), "credit_minor": int(credit), "description": description}


def _doc(*, doc_type, doc_number, doc_date, description, issuer, counterparty, lines, voucher,
         source, totals=None, settlement_method=1) -> dict:
    voucher = [v for v in voucher if v["debit_minor"] or v["credit_minor"]]
    if sum(v["debit_minor"] for v in voucher) != sum(v["credit_minor"] for v in voucher):
        raise ValidationError(f"سند {doc_number} تراز نیست")  # pragma: no cover - by construction
    return {"doc_type": doc_type, "doc_number": doc_number, "doc_date": doc_date,
            "description": description, "issuer": issuer, "counterparty": counterparty,
            "lines": lines, "totals": totals or _totals(lines), "voucher": voucher,
            "source": source, "settlement_method": settlement_method}


def settlement_method(order: dict) -> int:
    """Moadian setm: 1 نقدی، 2 نسیه، 3 نقدی/نسیه."""
    credit, cash = int(order.get("credit_minor") or 0), int(order.get("cash_minor") or 0)
    if credit and cash:
        return 3
    return 2 if credit else 1


def seller_invoice_lines(conn, fo: dict, order: dict, on: str) -> list[dict]:
    items = _rows(conn, "SELECT * FROM fulfillment_order_items WHERE fulfillment_order_id=? ORDER BY id", (fo["id"],))
    return [_line(conn, line_no=i, code=it.get("product_id") or "", description=it.get("title_fa") or "",
                  quantity=it["quantity"], unit_price=it["selling_price_minor"], gross=it["line_selling_minor"],
                  on=on, category=_tax_category(conn, it.get("product_id"), on),
                  organization_id=order.get("organization_id"))
            for i, it in enumerate(items, start=1)]


def _sales_docs(conn, acc, *, perspective, start, end, supplier_id=None, organization_id=None):
    sql = ("SELECT fo.*, substr(fo.created_at,1,10) AS d FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id "
           f"WHERE fo.status IN ({','.join('?' * len(INVOICEABLE_FO_STATUSES))}) "
           "AND substr(fo.created_at,1,10)>=? AND substr(fo.created_at,1,10)<=?")
    params = [*INVOICEABLE_FO_STATUSES, start, end]
    if supplier_id is not None:
        sql += " AND fo.supplier_id=?"
        params.append(supplier_id)
    if organization_id is not None:
        sql += " AND o.organization_id=?"
        params.append(organization_id)
    out = []
    for fo in _rows(conn, sql + " ORDER BY fo.id", params):
        order = _one(conn, "SELECT * FROM orders WHERE id=?", (fo["order_id"],))
        seller = _supplier_party(_one(conn, "SELECT * FROM suppliers WHERE id=?", (fo["supplier_id"],)))
        buyer = _buyer_party(conn, order)
        lines = seller_invoice_lines(conn, fo, order, fo["d"])
        t = _totals(lines)
        no = f"SI-{fo['id']:08d}"
        if perspective == "seller":
            voucher = [_v(acc, "receivable", "P", t["total_minor"], 0, f"فروش {no}"),
                       _v(acc, "revenue", buyer["code"], 0, t["net_minor"], f"درآمد فروش {no}"),
                       _v(acc, "vat_payable", "", 0, t["vat_minor"], f"ارزش افزوده {no}")]
            doc_type, counterparty = "sales_invoice", buyer
        elif perspective == "organization":
            no = f"PI-{fo['id']:08d}"
            voucher = [_v(acc, "purchases", seller["code"], t["net_minor"], 0, f"خرید {no}"),
                       _v(acc, "vat_receivable", "", t["vat_minor"], 0, f"ارزش افزوده خرید {no}"),
                       _v(acc, "payable", "P", 0, t["total_minor"], f"بدهی خرید {no}")]
            doc_type, counterparty = "purchase_invoice", seller
        else:  # platform: agent — collects from buyer on the seller's behalf
            voucher = [_v(acc, "receivable", buyer["code"], t["total_minor"], 0, f"فروش فروشنده {no}"),
                       _v(acc, "seller_payable", seller["code"], 0, t["total_minor"], f"بدهی به فروشنده {no}")]
            doc_type, counterparty = "sales_invoice", buyer
        out.append(_doc(doc_type=doc_type, doc_number=no, doc_date=fo["d"],
                        description=f"فاکتور فروش سفارش {order.get('order_number') or order['id']}",
                        issuer=seller, counterparty=counterparty, lines=lines, voucher=voucher,
                        source={"table": "fulfillment_orders", "id": fo["id"]},
                        settlement_method=settlement_method(order)))
    return out


def commission_lines(conn, supplier: dict, start: str, end: str) -> list[dict]:
    entries = _rows(conn, "SELECT * FROM supplier_payable_entries WHERE supplier_id=? AND "
                    "substr(created_at,1,10)>=? AND substr(created_at,1,10)<=? ORDER BY id",
                    (supplier["id"], start, end))
    lines = []
    for e in entries:
        commission = e.get("commission_minor")
        if commission is None:
            rate = e.get("commission_rate_bps")
            rate = supplier.get("commission_rate_bps") if rate is None else rate
            commission = int(e["gross_minor"]) * int(rate or 0) // 10000
        if int(commission) <= 0:
            continue
        lines.append(_line(conn, line_no=len(lines) + 1, code="COMMISSION",
                           description=f"کارمزد خدمات بازارگاه — سفارش تأمین {e['fulfillment_order_id']}",
                           quantity=1, unit_price=commission, gross=commission, on=end))
    return lines


def commission_doc_number(supplier_id: int, start: str, end: str) -> str:
    return f"CM-{supplier_id}-{start.replace('-', '')}-{end.replace('-', '')}"


def _commission_docs(conn, acc, *, perspective, start, end, supplier_id=None):
    sql, params = "SELECT * FROM suppliers", ()
    if supplier_id is not None:
        sql, params = sql + " WHERE id=?", (supplier_id,)
    out = []
    for s in _rows(conn, sql + " ORDER BY id", params):
        lines = commission_lines(conn, s, start, end)
        if not lines:
            continue
        seller = _supplier_party(s)
        t = _totals(lines)
        no = commission_doc_number(s["id"], start, end)
        if perspective == "seller":
            voucher = [_v(acc, "commission_expense", "P", t["net_minor"], 0, f"کارمزد {no}"),
                       _v(acc, "vat_receivable", "", t["vat_minor"], 0, f"ارزش افزوده کارمزد {no}"),
                       _v(acc, "receivable", "P", 0, t["total_minor"], f"کسر از طلب {no}")]
        else:
            voucher = [_v(acc, "seller_payable", seller["code"], t["total_minor"], 0, f"کسر کارمزد {no}"),
                       _v(acc, "commission_income", seller["code"], 0, t["net_minor"], f"درآمد کارمزد {no}"),
                       _v(acc, "vat_payable", "", 0, t["vat_minor"], f"ارزش افزوده کارمزد {no}")]
        out.append(_doc(doc_type="commission_invoice", doc_number=no, doc_date=end,
                        description=f"فاکتور کارمزد ۶۰آنلاین {start} تا {end}", issuer=PLATFORM_PARTY,
                        counterparty=seller, lines=lines, voucher=voucher,
                        source={"table": "supplier_payable_entries", "id": f"{s['id']}:{start}:{end}"},
                        settlement_method=2))
    return out


def _receipt_docs(conn, acc, *, perspective, start, end, organization_id=None):
    sql = ("SELECT p.*, substr(p.created_at,1,10) AS d FROM payments p JOIN orders o ON o.id=p.order_id "
           "WHERE p.status='captured' AND substr(p.created_at,1,10)>=? AND substr(p.created_at,1,10)<=?")
    params = [start, end]
    if organization_id is not None:
        sql += " AND o.organization_id=?"
        params.append(organization_id)
    out = []
    for p in _rows(conn, sql + " ORDER BY p.id", params):
        order = _one(conn, "SELECT * FROM orders WHERE id=?", (p["order_id"],))
        buyer, amt, no = _buyer_party(conn, order), int(p["amount_minor"]), f"RC-{p['id']:08d}"
        if perspective == "organization":
            voucher = [_v(acc, "payable", "P", amt, 0, f"پرداخت {no}"), _v(acc, "bank", "", 0, amt, f"پرداخت {no}")]
            doc_type, party = "payment", PLATFORM_PARTY
        else:
            voucher = [_v(acc, "bank", "", amt, 0, f"دریافت {no}"),
                       _v(acc, "receivable", buyer["code"], 0, amt, f"دریافت {no}")]
            doc_type, party = "receipt", buyer
        out.append(_doc(doc_type=doc_type, doc_number=no, doc_date=p["d"],
                        description=f"دریافت وجه سفارش {order.get('order_number') or order['id']} ({p['provider']})",
                        issuer=PLATFORM_PARTY, counterparty=party, lines=[], voucher=voucher,
                        totals={"gross_minor": amt, "discount_minor": 0, "net_minor": amt, "vat_minor": 0,
                                "total_minor": amt},
                        source={"table": "payments", "id": p["id"]}))
    return out


def _payout_docs(conn, acc, *, perspective, start, end, supplier_id=None):
    sql = ("SELECT *, substr(created_at,1,10) AS d FROM settlement_payments "
           "WHERE substr(created_at,1,10)>=? AND substr(created_at,1,10)<=?")
    params = [start, end]
    if supplier_id is not None:
        sql += " AND supplier_id=?"
        params.append(supplier_id)
    out = []
    for sp in _rows(conn, sql + " ORDER BY id", params):
        seller = _supplier_party(_one(conn, "SELECT * FROM suppliers WHERE id=?", (sp["supplier_id"],)))
        amt, no = int(sp["net_minor"]), f"ST-{sp['id']:08d}"
        if perspective == "seller":
            voucher = [_v(acc, "bank", "", amt, 0, f"تسویه {no}"), _v(acc, "receivable", "P", 0, amt, f"تسویه {no}")]
            party = PLATFORM_PARTY
        else:
            voucher = [_v(acc, "seller_payable", seller["code"], amt, 0, f"تسویه {no}"),
                       _v(acc, "bank", "", 0, amt, f"تسویه {no}")]
            party = seller
        out.append(_doc(doc_type="settlement_payout", doc_number=no, doc_date=sp["d"],
                        description=f"تسویه با فروشنده — دسته {sp['settlement_batch_id']}",
                        issuer=PLATFORM_PARTY, counterparty=party, lines=[], voucher=voucher,
                        totals={"gross_minor": amt, "discount_minor": 0, "net_minor": amt, "vat_minor": 0,
                                "total_minor": amt},
                        source={"table": "settlement_payments", "id": sp["id"]}))
    return out


def _credit_docs(conn, acc, *, perspective, start, end, organization_id=None):
    sql = ("SELECT *, substr(issued_at,1,10) AS d FROM credit_statements "
           "WHERE substr(issued_at,1,10)>=? AND substr(issued_at,1,10)<=?")
    params = [start, end]
    if organization_id is not None:
        sql += " AND organization_id=?"
        params.append(organization_id)
    out = []
    for cs in _rows(conn, sql + " ORDER BY id", params):
        org = _buyer_party(conn, {"organization_id": cs["organization_id"]})
        usage, no = int(cs["usage_minor"]), f"CS-{cs['reference']}"
        if perspective == "organization":
            voucher = [_v(acc, "payable", "P", usage, 0, f"صورت‌حساب اعتباری {no}"),
                       _v(acc, "credit_payable", "P", 0, usage, f"صورت‌حساب اعتباری {no}")]
            party = PLATFORM_PARTY
        else:
            voucher = [_v(acc, "credit_receivable", org["code"], usage, 0, f"صورت‌حساب اعتباری {no}"),
                       _v(acc, "receivable", org["code"], 0, usage, f"صورت‌حساب اعتباری {no}")]
            party = org
        out.append(_doc(doc_type="credit_statement", doc_number=no, doc_date=cs["d"],
                        description=f"صورت‌حساب اعتباری {cs['period_start'][:10]} تا {cs['period_end'][:10]}",
                        issuer=PLATFORM_PARTY, counterparty=party, lines=[], voucher=voucher,
                        totals={"gross_minor": usage, "discount_minor": 0, "net_minor": usage, "vat_minor": 0,
                                "total_minor": usage, "opening_minor": int(cs["opening_minor"]),
                                "payments_minor": int(cs["payments_minor"]),
                                "closing_minor": int(cs["closing_minor"])},
                        source={"table": "credit_statements", "id": cs["id"]}, settlement_method=2))
    return out


def build_export(conn, *, entity_type: str, entity_id: int | None, period_start: str, period_end: str,
                 connector: str = "JSON") -> dict:
    """The canonical model. Pure function of DB state + params (no clock)."""
    start, end = _date(period_start, "شروع"), _date(period_end, "پایان")
    if start > end:
        raise ValidationError("تاریخ شروع باید پیش از تاریخ پایان باشد")
    if entity_type not in ENTITY_TYPES:
        raise ValidationError("نوع موجودیت نامعتبر است (platform | seller | organization)")
    connector = (connector or "JSON").upper()
    acc = account_map(conn, connector)
    if entity_type == "platform":
        entity_id, name = None, PLATFORM_PARTY["name"]
        docs = (_sales_docs(conn, acc, perspective="platform", start=start, end=end)
                + _commission_docs(conn, acc, perspective="platform", start=start, end=end)
                + _receipt_docs(conn, acc, perspective="platform", start=start, end=end)
                + _payout_docs(conn, acc, perspective="platform", start=start, end=end)
                + _credit_docs(conn, acc, perspective="platform", start=start, end=end))
    elif entity_type == "seller":
        s = _one(conn, "SELECT * FROM suppliers WHERE id=?", (entity_id,)) if entity_id else None
        if s is None:
            raise NotFoundError("فروشنده یافت نشد")
        name = _supplier_party(s)["name"]
        kw = {"perspective": "seller", "start": start, "end": end, "supplier_id": s["id"]}
        docs = _sales_docs(conn, acc, **kw) + _commission_docs(conn, acc, **kw) + _payout_docs(conn, acc, **kw)
    else:
        o = _one(conn, "SELECT * FROM organizations WHERE id=?", (entity_id,)) if entity_id else None
        if o is None:
            raise NotFoundError("سازمان یافت نشد")
        name = o.get("legal_name") or o.get("display_name") or ""
        kw = {"perspective": "organization", "start": start, "end": end, "organization_id": o["id"]}
        docs = _sales_docs(conn, acc, **kw) + _receipt_docs(conn, acc, **kw) + _credit_docs(conn, acc, **kw)
    debit = sum(v["debit_minor"] for d in docs for v in d["voucher"])
    credit = sum(v["credit_minor"] for d in docs for v in d["voucher"])
    return {"schema": SCHEMA, "connector": connector, "currency": "IRR",
            "entity": {"type": entity_type, "id": entity_id, "name": name},
            "period": {"start": start, "end": end}, "documents": docs,
            "totals": {"documents": len(docs), "debit_minor": debit, "credit_minor": credit}}


# ─────────────────────────────────────────────────────────────────────────────
# Export jobs
# ─────────────────────────────────────────────────────────────────────────────

_JOB_COLS = ("id, reference, entity_type, entity_id, connector, period_start, period_end, status, "
             "document_count, file_name, content_type, content_sha256, created_by_user_id, created_at")


def create_export_job(conn, *, entity_type, entity_id, period_start, period_end, connector,
                      layout=None, user_id=None) -> dict:
    connector = str(connector or "").upper().strip()
    formatter = get_finance_formatter(connector, config={"layout": layout} if layout else None)
    export = build_export(conn, entity_type=entity_type, entity_id=entity_id, period_start=period_start,
                          period_end=period_end, connector=connector)
    rendered = formatter.render(export)
    content = rendered["content"]
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    params = {"entity_type": entity_type, "entity_id": export["entity"]["id"], "connector": connector,
              "layout": formatter.layout, "start": export["period"]["start"], "end": export["period"]["end"]}
    params_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    existing = _one(conn, f"SELECT {_JOB_COLS} FROM finance_export_jobs WHERE params_hash=? AND content_sha256=?",
                    (params_hash, sha))
    if existing:
        return {**existing, "reused": True}
    ref = f"FX-{params_hash[:10]}-{sha[:10]}"
    conn.execute("""INSERT INTO finance_export_jobs (reference, entity_type, entity_id, connector, period_start,
                    period_end, params_hash, status, document_count, file_name, content_type, content,
                    content_sha256, created_by_user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (ref, entity_type, export["entity"]["id"], connector, params["start"], params["end"], params_hash,
                  "ready", len(export["documents"]), rendered["file_name"], rendered["content_type"], content,
                  sha, user_id, _now()))
    return {**_one(conn, f"SELECT {_JOB_COLS} FROM finance_export_jobs WHERE reference=?", (ref,)), "reused": False}


def list_jobs(conn, *, entity_type=None, entity_id=None, limit=100) -> list[dict]:
    sql, params = f"SELECT {_JOB_COLS} FROM finance_export_jobs WHERE 1=1", []
    if entity_type:
        sql += " AND entity_type=?"
        params.append(entity_type)
    if entity_id is not None:
        sql += " AND entity_id=?"
        params.append(entity_id)
    return _rows(conn, sql + " ORDER BY id DESC LIMIT ?", (*params, int(limit)))


def get_job(conn, job_id: int, *, supplier_id: int | None = None, with_content=False) -> dict:
    cols = _JOB_COLS + (", content" if with_content else "")
    job = _one(conn, f"SELECT {cols} FROM finance_export_jobs WHERE id=?", (job_id,))
    # A seller only ever sees its own seller-scoped jobs; anything else is "not found".
    if job is None or (supplier_id is not None and (job["entity_type"] != "seller"
                                                     or job["entity_id"] != supplier_id)):
        raise NotFoundError("خروجی مالی یافت نشد")
    return job
