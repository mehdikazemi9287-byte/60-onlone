"""Mahak (محک) accounting — Phase 5B CSV voucher import.

Mahak has no public web API; data is moved with its "ورود سند از فایل" CSV import.
Layout: one row per voucher line, Jalali dates, integer Rial amounts. Column titles
follow the common Mahak template and can be renamed with config["header"].

MahakAccountingAdapter keeps the Phase 7 contract (fail-closed, not implemented).
"""
from __future__ import annotations

from app.adapters.accounting.base import AccountingAdapter
from app.adapters.accounting.finance_formats import FinanceExportFormatter, jalali, voucher_rows


class MahakAccountingAdapter(AccountingAdapter):
    adapter_name = "mahak"
    implementation_status = "not_implemented"

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def capabilities(self) -> dict:
        return {"adapter_name": self.adapter_name, "implementation_status": self.implementation_status,
                "supported": ["finance_export_csv"], "notes": "محک — فقط خروجی فایل CSV؛ API ندارد"}


class MahakFinanceFormatter(FinanceExportFormatter):
    connector = "MAHAK"
    label = "محک — CSV ورود سند"

    HEADER = ["شماره سند", "تاریخ", "ردیف", "کد حساب", "کد تفصیلی", "شرح", "بدهکار", "بستانکار"]

    def render(self, export: dict) -> dict:
        header = list(self.config.get("header") or self.HEADER)
        numbers = {d["doc_number"]: n for n, d in enumerate(export["documents"], start=1)}
        rows = [[numbers[d["doc_number"]], jalali(d["doc_date"]), i, v["account_code"], v["detail_code"],
                 f"{v['description']} - {d['doc_number']}", v["debit_minor"], v["credit_minor"]]
                for d, i, v in voucher_rows(export)]
        return self._csv(export, header, rows, "vouchers")
