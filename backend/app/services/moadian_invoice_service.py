"""Moadian (سامانهٔ مودیان) e-invoice builder — Phase 5B.

Issuer split (marketplace model):
  * every SELLER issues its own invoice for its goods  → source_ref "fo:{fulfillment_order_id}"
  * 60Online issues invoices ONLY for its commission/services to sellers
                                                       → source_ref "commission:{supplier_id}:{start}:{end}"

Payload = {"header": {...}, "body": [...], "payments": []} with INTA field names
(taxid, indatim, inty, inp, ins, tins, tob, bid, tinb, tprdis, tdis, tadis, tvam,
todam, tbill, setm / sstid, sstt, am, mu, fee, prdis, dis, adis, vra, vam, tsstam).
Totals reconcile exactly: Σ line tsstam == tbill, Σ vam == tvam, ...

TAXID — implemented as documented in INTA's reference SDK (TaxIdGenerator):
  fiscal_memory_id(6) + hex(days since epoch of indatim, 5) + hex(serial, 10)
  + Verhoeff check digit over: decimal(fiscal id: digits kept, letters → ASCII
  code) + days zero-padded to 6 + serial zero-padded to 12; result upper-cased.
  VERIFY against the current official SDK before production; the generator is
  pluggable (taxid_generator=...).

Signing (JWS with the taxpayer's private key) and transport (token + send) are
INJECTED interfaces — no keys, no network here. ASSUMPTIONS to verify: the
measurement-unit code (DEFAULT_UNIT) and the 13-digit sstid of each product /
service (sstid_resolver) must come from the INTA lists; a missing sstid is
reported in `warnings` and blocks submission.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.core.errors import NotFoundError, ValidationError
from app.services import finance_export_service as fx

DEFAULT_UNIT = "1627"          # «عدد» — verify against INTA unit list
INDATIM_UTC_TIME = "08:30:00"  # 12:00 Tehran on the document date (deterministic)
STATUSES = ("built", "submitted", "accepted", "rejected")

# ─────────────────────────────────────────────────────────────────── Verhoeff
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_digit(num: str) -> int:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return _INV[c]


def verhoeff_valid(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def generate_taxid(fiscal_memory_id: str, indatim_ms: int, serial: int) -> str:
    fid = (fiscal_memory_id or "").strip().upper()
    if len(fid) != 6 or not fid.isalnum() or not fid.isascii():
        raise ValidationError("شناسه حافظه مالیاتی باید ۶ نویسه لاتین/عدد باشد")
    if not 0 < serial < 16 ** 10:
        raise ValidationError("شماره سریال صورتحساب نامعتبر است")
    days = indatim_ms // 86_400_000
    control = "".join(c if c.isdigit() else str(ord(c)) for c in fid) + f"{days:06d}" + f"{serial:012d}"
    return f"{fid}{days:05x}{serial:010x}{verhoeff_digit(control)}".upper()


def indatim_for(doc_date: str) -> int:
    dt = datetime.fromisoformat(f"{doc_date[:10]}T{INDATIM_UTC_TIME}").replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) * 1000


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _vra(rate_bps: int):
    return rate_bps // 100 if rate_bps % 100 == 0 else f"{rate_bps // 100}.{rate_bps % 100:02d}"


# ─────────────────────────────────────────────────────────── fiscal ids
def set_fiscal_id(conn, *, issuer_key: str, fiscal_memory_id: str, economic_code: str = "") -> dict:
    if issuer_key != "platform" and not (issuer_key.startswith("supplier:") and issuer_key[9:].isdigit()):
        raise ValidationError("issuer_key باید 'platform' یا 'supplier:{id}' باشد")
    generate_taxid(fiscal_memory_id, 0, 1)  # validates the id shape
    now, fid = _now(), fiscal_memory_id.strip().upper()
    if conn.execute("SELECT 1 FROM moadian_fiscal_ids WHERE issuer_key=?", (issuer_key,)).fetchone():
        conn.execute("UPDATE moadian_fiscal_ids SET fiscal_memory_id=?, economic_code=?, updated_at=? "
                     "WHERE issuer_key=?", (fid, economic_code or "", now, issuer_key))
    else:
        conn.execute("INSERT INTO moadian_fiscal_ids (issuer_key, fiscal_memory_id, economic_code, created_at, "
                     "updated_at) VALUES (?,?,?,?,?)", (issuer_key, fid, economic_code or "", now, now))
    return dict(conn.execute("SELECT * FROM moadian_fiscal_ids WHERE issuer_key=?", (issuer_key,)).fetchone())


def _fiscal(conn, issuer_key):
    r = conn.execute("SELECT * FROM moadian_fiscal_ids WHERE issuer_key=?", (issuer_key,)).fetchone()
    if r is None:
        raise ValidationError(f"شناسه حافظه مالیاتی برای «{issuer_key}» ثبت نشده است")
    return dict(r)


# ─────────────────────────────────────────────────────────── source → invoice
def _source(conn, source_ref: str) -> dict:
    """Resolve a source_ref to {doc_type, issuer_type, supplier_id, issuer, buyer, lines, date, setm}."""
    parts = str(source_ref or "").split(":")
    if parts[0] == "fo" and len(parts) == 2 and parts[1].isdigit():
        fo = fx._one(conn, "SELECT *, substr(created_at,1,10) AS d FROM fulfillment_orders WHERE id=?",
                     (int(parts[1]),))
        if fo is None or fo["status"] not in fx.INVOICEABLE_FO_STATUSES:
            raise NotFoundError("سفارش تأمین قابل صدور صورتحساب یافت نشد")
        order = fx._one(conn, "SELECT * FROM orders WHERE id=?", (fo["order_id"],))
        s = fx._one(conn, "SELECT * FROM suppliers WHERE id=?", (fo["supplier_id"],))
        return {"doc_type": "seller_sale", "issuer_type": "seller", "supplier_id": s["id"],
                "issuer": fx._supplier_party(s), "buyer": fx._buyer_party(conn, order), "date": fo["d"],
                "lines": fx.seller_invoice_lines(conn, fo, order, fo["d"]), "setm": fx.settlement_method(order),
                "cash_minor": int(order.get("cash_minor") or 0), "credit_minor": int(order.get("credit_minor") or 0)}
    if parts[0] == "commission" and len(parts) == 4 and parts[1].isdigit():
        start, end = fx._date(parts[2], "شروع"), fx._date(parts[3], "پایان")
        s = fx._one(conn, "SELECT * FROM suppliers WHERE id=?", (int(parts[1]),))
        if s is None:
            raise NotFoundError("فروشنده یافت نشد")
        lines = fx.commission_lines(conn, s, start, end)
        if not lines:
            raise NotFoundError("کارمزدی در این دوره وجود ندارد")
        return {"doc_type": "platform_commission", "issuer_type": "platform", "supplier_id": None,
                "issuer": fx.PLATFORM_PARTY, "buyer": fx._supplier_party(s), "date": end, "lines": lines,
                "setm": 2, "cash_minor": 0, "credit_minor": None}
    raise ValidationError("source_ref نامعتبر است (fo:{id} یا commission:{supplier}:{start}:{end})")


def build_payload(conn, source_ref: str, *, serial: int, sstid_resolver=None, taxid_generator=None) -> dict:
    src = _source(conn, source_ref)
    issuer_key = "platform" if src["issuer_type"] == "platform" else f"supplier:{src['supplier_id']}"
    fiscal = _fiscal(conn, issuer_key)
    indatim = indatim_for(src["date"])
    taxid = (taxid_generator or generate_taxid)(fiscal["fiscal_memory_id"], indatim, serial)
    resolve = sstid_resolver or (lambda line, src: None)
    warnings, body = [], []
    for ln in src["lines"]:
        sstid = resolve(ln, src)
        if not sstid:
            warnings.append(f"ردیف {ln['line_no']}: شناسه کالا/خدمت (sstid) تعریف نشده است")
        prdis = ln["unit_price_minor"] * ln["quantity"]
        if prdis != ln["gross_minor"]:
            raise ValidationError(f"ردیف {ln['line_no']}: مبلغ قبل از تخفیف با فی × تعداد برابر نیست")
        body.append({"sstid": sstid or "", "sstt": ln["description"], "am": ln["quantity"], "mu": DEFAULT_UNIT,
                     "fee": ln["unit_price_minor"], "prdis": prdis, "dis": ln["discount_minor"],
                     "adis": ln["net_minor"], "vra": _vra(ln["vat_rate_bps"]), "vam": ln["vat_minor"],
                     "odam": 0, "olam": 0, "tsstam": ln["net_minor"] + ln["vat_minor"]})
    buyer = src["buyer"]
    has_buyer = bool(buyer.get("national_id") or buyer.get("economic_code"))
    tins = fiscal["economic_code"] or src["issuer"].get("economic_code") or ""
    if not tins:
        warnings.append("شماره اقتصادی فروشنده (tins) ثبت نشده است")
    header = {"taxid": taxid, "indatim": indatim, "indati2m": indatim, "inty": 1 if has_buyer else 2,
              "inno": f"{serial:010x}".upper(), "irtaxid": None, "inp": 1, "ins": 1, "tins": tins,
              "tob": (2 if buyer.get("legal") else 1) if has_buyer else None,
              "bid": buyer.get("national_id") or None if has_buyer else None,
              "tinb": buyer.get("economic_code") or None if has_buyer else None,
              "tprdis": sum(b["prdis"] for b in body), "tdis": sum(b["dis"] for b in body),
              "tadis": sum(b["adis"] for b in body), "tvam": sum(b["vam"] for b in body), "todam": 0}
    header["tbill"] = header["tadis"] + header["tvam"] + header["todam"]
    header["setm"] = src["setm"]
    header["cap"] = header["tbill"] if src["setm"] == 1 else min(src["cash_minor"], header["tbill"])
    header["insp"] = header["tbill"] - header["cap"]
    assert header["tbill"] == sum(b["tsstam"] for b in body)
    return {"payload": {"header": header, "body": body, "payments": []}, "issuer_key": issuer_key,
            "issuer_type": src["issuer_type"], "supplier_id": src["supplier_id"], "doc_type": src["doc_type"],
            "warnings": warnings}


def _next_serial(conn, issuer_key) -> int:
    r = conn.execute("SELECT MAX(serial) AS m FROM moadian_documents WHERE issuer_key=?", (issuer_key,)).fetchone()
    return int((dict(r)["m"] if r else None) or 0) + 1


def _issuer_key_for(conn, source_ref):
    src = _source(conn, source_ref)
    return "platform" if src["issuer_type"] == "platform" else f"supplier:{src['supplier_id']}"


def preview(conn, source_ref: str, **kw) -> dict:
    existing = conn.execute("SELECT * FROM moadian_documents WHERE source_ref=?", (source_ref,)).fetchone()
    serial = dict(existing)["serial"] if existing else _next_serial(conn, _issuer_key_for(conn, source_ref))
    return build_payload(conn, source_ref, serial=serial, **kw)


def _doc_out(row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json"))
    return d


def build_document(conn, source_ref: str, **kw) -> dict:
    """Idempotent: one stored invoice per source_ref; a re-build returns the stored one."""
    row = conn.execute("SELECT * FROM moadian_documents WHERE source_ref=?", (source_ref,)).fetchone()
    if row:
        return {**_doc_out(row), "reused": True}
    serial = _next_serial(conn, _issuer_key_for(conn, source_ref))
    built = build_payload(conn, source_ref, serial=serial, **kw)
    payload_json = json.dumps(built["payload"], ensure_ascii=False, sort_keys=True)
    now, h = _now(), built["payload"]["header"]
    conn.execute("""INSERT INTO moadian_documents (source_ref, doc_type, issuer_type, issuer_supplier_id, issuer_key,
                    serial, taxid, inty, tbill_minor, payload_json, payload_sha256, status, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'built',?,?)""",
                 (source_ref, built["doc_type"], built["issuer_type"], built["supplier_id"], built["issuer_key"],
                  serial, h["taxid"], h["inty"], h["tbill"], payload_json,
                  hashlib.sha256(payload_json.encode()).hexdigest(), now, now))
    row = conn.execute("SELECT * FROM moadian_documents WHERE source_ref=?", (source_ref,)).fetchone()
    return {**_doc_out(row), "reused": False, "warnings": built["warnings"]}


def get_document(conn, doc_id: int, *, supplier_id: int | None = None) -> dict:
    row = conn.execute("SELECT * FROM moadian_documents WHERE id=?", (doc_id,)).fetchone()
    if row is None or (supplier_id is not None and dict(row)["issuer_supplier_id"] != supplier_id):
        raise NotFoundError("صورتحساب مودیان یافت نشد")
    return _doc_out(row)


def list_documents(conn, *, issuer_type=None, supplier_id=None, status=None, limit=100) -> list[dict]:
    sql, p = "SELECT * FROM moadian_documents WHERE 1=1", []
    for col, val in (("issuer_type", issuer_type), ("issuer_supplier_id", supplier_id), ("status", status)):
        if val is not None:
            sql += f" AND {col}=?"
            p.append(val)
    return [_doc_out(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*p, int(limit))).fetchall()]


def mark_submitted(conn, doc_id: int, *, reference: str, status: str = "submitted", error: str | None = None) -> dict:
    if status not in STATUSES[1:]:
        raise ValidationError("وضعیت نامعتبر است (submitted | accepted | rejected)")
    reference = str(reference or "").strip()
    if not reference or len(reference) > 120:
        raise ValidationError("شماره پیگیری (reference) الزامی است")
    doc = get_document(conn, doc_id)
    if doc["status"] == "accepted":
        raise ValidationError("صورتحساب پذیرفته‌شده قابل تغییر نیست")
    now = _now()
    conn.execute("UPDATE moadian_documents SET status=?, submission_reference=?, submission_error=?, "
                 "submitted_at=COALESCE(submitted_at, ?), updated_at=? WHERE id=?",
                 (status, reference, (error or None) and str(error)[:500], now, now, doc_id))
    return get_document(conn, doc_id)


def submit_document(conn, doc_id: int, *, signer, transport) -> dict:
    """signer(payload: dict) -> str (signed packet); transport(packet: str, taxid) -> {"reference": str}.
    Both injected; nothing here holds keys or opens sockets."""
    doc = get_document(conn, doc_id)
    if any(not b["sstid"] for b in doc["payload"]["body"]) or not doc["payload"]["header"]["tins"]:
        raise ValidationError("صورتحساب ناقص است (sstid یا tins)؛ ارسال ممکن نیست")
    result = transport(signer(doc["payload"]), doc["taxid"])
    return mark_submitted(conn, doc_id, reference=result["reference"])
