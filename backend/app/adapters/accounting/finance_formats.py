"""Financial export formatters — Phase 5B (درگاه‌های مخصوص نرم‌افزارهای مالی).

A formatter turns the CANONICAL finance export (built by
app.services.finance_export_service.build_export) into a file or payload for one
accounting package. Formatters are pure functions of the canonical model: no DB,
no clock, no network — the same export always renders to the same bytes, which
is what makes export jobs idempotent (same params → same sha256).

Canonical model (schema "60online.finance-export/1"):
  {schema, connector, currency, entity{type,id,name}, period{start,end},
   documents:[{doc_type, doc_number, doc_date, description, issuer{...},
               counterparty{role,id,code,name,national_id,economic_code},
               lines:[{line_no, code, description, quantity, unit_price_minor,
                       gross_minor, discount_minor, net_minor, vat_rate_bps,
                       vat_minor, total_minor}],
               totals{gross_minor, discount_minor, net_minor, vat_minor, total_minor},
               voucher:[{account_key, account_code, detail_code, debit_minor,
                         credit_minor, description}],
               source{table, id}}],
   totals{documents, debit_minor, credit_minor}}

Vendor layouts (Sepidar / Mahak / Holoo / Hamkaran) follow the import templates
these packages commonly ship; column names are configurable per deployment
because each customer's template may differ. They are NOT certified by the
vendors — verify against the customer's own import template before go-live.
"""
from __future__ import annotations

import csv
import io
import json

from app.core.errors import ValidationError

BOM = "﻿"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Integer Gregorian → Jalali (Solar Hijri) conversion (standard algorithm)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
            + (gy2 + 399) // 400 + gd + g_d_m[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def jalali(date_iso: str, sep: str = "/") -> str:
    """'2026-03-21' → '1405/01/01'."""
    y, m, d = (int(x) for x in date_iso[:10].split("-"))
    jy, jm, jd = gregorian_to_jalali(y, m, d)
    return f"{jy:04d}{sep}{jm:02d}{sep}{jd:02d}"


def csv_text(header: list[str], rows: list[list], *, bom: bool = True, delimiter: str = ",") -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return (BOM if bom else "") + buf.getvalue()


def voucher_rows(export: dict):
    """(doc, voucher_line_no, voucher_line) for every voucher line, in model order."""
    for doc in export["documents"]:
        for i, v in enumerate(doc["voucher"], start=1):
            yield doc, i, v


def _base_name(export: dict, connector: str | None = None) -> str:
    e, p = export["entity"], export["period"]
    ent = e["type"] if e.get("id") is None else f"{e['type']}-{e['id']}"
    return f"60online-{(connector or export['connector']).lower()}-{ent}-{p['start']}_{p['end']}"


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────

class FinanceExportFormatter:
    """render(export) -> {"file_name", "content_type", "content": str}."""

    connector = "BASE"
    label = ""
    layouts: tuple[str, ...] = ("vouchers",)

    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})
        layout = self.config.get("layout") or self.layouts[0]
        if layout not in self.layouts:
            raise ValidationError(f"قالب '{layout}' برای {self.connector} پشتیبانی نمی‌شود")
        self.layout = layout

    def render(self, export: dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def _csv(self, export: dict, header, rows, suffix="") -> dict:
        name = _base_name(export, self.connector) + (f"-{suffix}" if suffix else "")
        return {"file_name": f"{name}.csv", "content_type": "text/csv; charset=utf-8",
                "content": csv_text(header, rows)}


class JsonFormatter(FinanceExportFormatter):
    connector = "JSON"
    label = "JSON استاندارد ۶۰آنلاین"

    def render(self, export: dict) -> dict:
        return {"file_name": _base_name(export, self.connector) + ".json",
                "content_type": "application/json; charset=utf-8",
                "content": json.dumps(export, ensure_ascii=False, sort_keys=True, indent=2) + "\n"}


class GenericCsvFormatter(FinanceExportFormatter):
    """One flat CSV. layout 'vouchers' (journal lines) or 'invoices' (item lines)."""

    connector = "CSV"
    label = "CSV / Excel عمومی"
    layouts = ("vouchers", "invoices")

    def render(self, export: dict) -> dict:
        if self.layout == "invoices":
            header = ["doc_type", "doc_number", "doc_date", "counterparty_code", "counterparty_name",
                      "line_no", "item_code", "description", "quantity", "unit_price", "gross",
                      "discount", "net", "vat_rate_bps", "vat", "total"]
            rows = [[d["doc_type"], d["doc_number"], d["doc_date"], d["counterparty"]["code"],
                     d["counterparty"]["name"], ln["line_no"], ln["code"], ln["description"],
                     ln["quantity"], ln["unit_price_minor"], ln["gross_minor"], ln["discount_minor"],
                     ln["net_minor"], ln["vat_rate_bps"], ln["vat_minor"], ln["total_minor"]]
                    for d in export["documents"] for ln in d["lines"]]
            return self._csv(export, header, rows, "invoices")
        header = ["doc_type", "doc_number", "doc_date", "line_no", "account_key", "account_code",
                  "detail_code", "debit", "credit", "description"]
        rows = [[d["doc_type"], d["doc_number"], d["doc_date"], i, v["account_key"], v["account_code"],
                 v["detail_code"], v["debit_minor"], v["credit_minor"], v["description"]]
                for d, i, v in voucher_rows(export)]
        return self._csv(export, header, rows, "vouchers")


class ExcelCsvFormatter(GenericCsvFormatter):
    """Same as CSV; UTF-8 BOM makes Excel open Persian text correctly."""
    connector = "EXCEL"
    label = "Excel (CSV با BOM)"


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

def _registry() -> dict[str, type[FinanceExportFormatter]]:
    from app.adapters.accounting.hamkaran import HamkaranVoucherFormatter
    from app.adapters.accounting.holo import HolooFinanceFormatter
    from app.adapters.accounting.mahak import MahakFinanceFormatter
    from app.adapters.accounting.sepidar import SepidarFinanceFormatter
    return {
        "JSON": JsonFormatter,
        "CSV": GenericCsvFormatter,
        "EXCEL": ExcelCsvFormatter,
        "SEPIDAR": SepidarFinanceFormatter,
        "HAMKARAN": HamkaranVoucherFormatter,
        "RAHKARAN": HamkaranVoucherFormatter,
        "MAHAK": MahakFinanceFormatter,
        "HOLOO": HolooFinanceFormatter,
        "HOLO": HolooFinanceFormatter,
    }


def finance_connectors() -> list[str]:
    return sorted(_registry())


def get_finance_formatter(connector: str, *, config: dict | None = None) -> FinanceExportFormatter:
    key = (connector or "").upper().strip()
    cls = _registry().get(key)
    if cls is None:
        raise ValidationError(
            f"قالب خروجی مالی '{connector}' ناشناخته است. گزینه‌ها: {', '.join(finance_connectors())}")
    return cls(config=config)


def list_finance_formats() -> list[dict]:
    return [{"connector": k, "label": c.label, "layouts": list(c.layouts)}
            for k, c in sorted(_registry().items())]
