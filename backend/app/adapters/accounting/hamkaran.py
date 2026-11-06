"""Hamkaran System — Rahkaran (همکاران سیستم / راهکاران) voucher import, Phase 5B.

Rahkaran accepts vouchers through its integration web service (customer-hosted).
The exact endpoint/contract is deployment-specific and NOT publicly documented, so:
  * HamkaranVoucherFormatter renders the canonical export as a voucher-import
    payload in JSON (default) or XML (config["layout"]="xml") — one <Voucher> per
    document, items with SLCode (معین) / DLCode (تفصیلی) / Debit / Credit.
  * HamkaranVoucherClient sends that payload through an INJECTED transport
    callable(method, url, body: bytes, headers) -> (status:int, body:bytes).
    The default transport refuses to run — no live network in this codebase.
"""
from __future__ import annotations

import json
from xml.sax.saxutils import escape

from app.adapters.accounting.base import AccountingAdapterError
from app.adapters.accounting.finance_formats import FinanceExportFormatter, _base_name, jalali


def build_vouchers(export: dict) -> list[dict]:
    out = []
    for d in export["documents"]:
        out.append({
            "Number": d["doc_number"],
            "Date": jalali(d["doc_date"]),
            "Description": d["description"],
            "Items": [{"RowNumber": i, "SLCode": v["account_code"], "DLCode": v["detail_code"],
                       "Debit": v["debit_minor"], "Credit": v["credit_minor"],
                       "Description": v["description"]}
                      for i, v in enumerate(d["voucher"], start=1)],
        })
    return out


class HamkaranVoucherFormatter(FinanceExportFormatter):
    connector = "HAMKARAN"
    label = "همکاران سیستم (راهکاران) — JSON/XML ورود سند"
    layouts = ("json", "xml")

    def payload(self, export: dict) -> dict:
        return {"Vouchers": build_vouchers(export), "Currency": export["currency"],
                "Source": "60online", "Period": export["period"]}

    def render(self, export: dict) -> dict:
        p = self.payload(export)
        if self.layout == "xml":
            parts = ['<?xml version="1.0" encoding="utf-8"?>', "<VoucherImport>"]
            for v in p["Vouchers"]:
                parts.append(f'  <Voucher Number="{escape(v["Number"])}" Date="{v["Date"]}">')
                parts.append(f"    <Description>{escape(v['Description'])}</Description>")
                for it in v["Items"]:
                    parts.append(
                        f'    <Item RowNumber="{it["RowNumber"]}" SLCode="{escape(it["SLCode"])}"'
                        f' DLCode="{escape(it["DLCode"])}" Debit="{it["Debit"]}" Credit="{it["Credit"]}">'
                        f"{escape(it['Description'])}</Item>")
                parts.append("  </Voucher>")
            parts.append("</VoucherImport>")
            return {"file_name": _base_name(export, self.connector) + ".xml",
                    "content_type": "application/xml; charset=utf-8", "content": "\n".join(parts) + "\n"}
        return {"file_name": _base_name(export, self.connector) + ".json", "content_type": "application/json; charset=utf-8",
                "content": json.dumps(p, ensure_ascii=False, sort_keys=True, indent=2) + "\n"}


def _no_transport(method, url, body, headers):
    raise AccountingAdapterError("انتقال به راهکاران پیکربندی نشده است", code="transport_not_configured")


class HamkaranVoucherClient:
    """Posts a voucher-import payload via an injectable transport. No credentials stored."""

    def __init__(self, *, base_url: str = "", transport=None, token_provider=None):
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _no_transport
        self.token_provider = token_provider

    def submit(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.token_provider:
            headers["Authorization"] = f"Bearer {self.token_provider()}"
        status, resp = self.transport("POST", f"{self.base_url}/Vouchers/Import", body, headers)
        try:
            data = json.loads(resp.decode("utf-8") if isinstance(resp, bytes) else resp or "{}")
        except ValueError:
            data = {}
        if status >= 400:
            raise AccountingAdapterError(f"راهکاران خطا برگرداند ({status})", code="remote_error",
                                         retryable=status >= 500)
        return {"acknowledged": True, "status": status, "response": data}
