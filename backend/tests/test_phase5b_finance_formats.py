"""Phase 5B — connector formats rendered from a FIXED canonical export (no DB)."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.accounting.finance_formats import (  # noqa: E402
    BOM, get_finance_formatter, gregorian_to_jalali, list_finance_formats)
from app.adapters.accounting.hamkaran import HamkaranVoucherClient, HamkaranVoucherFormatter  # noqa: E402
from app.adapters.accounting.base import AccountingAdapterError  # noqa: E402
from app.adapters.accounting.registry import get_accounting_adapter, list_accounting_systems  # noqa: E402
from app.core.errors import ValidationError  # noqa: E402


def _v(key, code, detail, dr, cr, desc):
    return {"account_key": key, "account_code": code, "detail_code": detail, "debit_minor": dr,
            "credit_minor": cr, "description": desc}


FIXTURE = {
    "schema": "60online.finance-export/1", "connector": "X", "currency": "IRR",
    "entity": {"type": "seller", "id": 7, "name": "فروشگاه نمونه"},
    "period": {"start": "2026-10-23", "end": "2026-10-29"},
    "documents": [
        {"doc_type": "sales_invoice", "doc_number": "SI-00000011", "doc_date": "2026-10-25",
         "description": "فاکتور فروش سفارش ORD-1", "issuer": {"code": "S7"},
         "counterparty": {"role": "organization", "id": 3, "code": "O3", "name": "شرکت الف",
                          "national_id": "10101010101", "economic_code": "411111111111"},
         "lines": [{"line_no": 1, "code": "501", "description": "کاغذ A4", "quantity": 3,
                    "unit_price_minor": 1_250_000, "gross_minor": 3_750_000, "discount_minor": 0,
                    "net_minor": 3_750_000, "vat_rate_bps": 1000, "vat_minor": 375_000,
                    "total_minor": 4_125_000}],
         "totals": {"gross_minor": 3_750_000, "discount_minor": 0, "net_minor": 3_750_000,
                    "vat_minor": 375_000, "total_minor": 4_125_000},
         "voucher": [_v("receivable", "1301", "P", 4_125_000, 0, "فروش SI-00000011"),
                     _v("revenue", "4101", "O3", 0, 3_750_000, "درآمد فروش SI-00000011"),
                     _v("vat_payable", "2201", "", 0, 375_000, "ارزش افزوده SI-00000011")],
         "source": {"table": "fulfillment_orders", "id": 11}, "settlement_method": 1},
        {"doc_type": "settlement_payout", "doc_number": "ST-00000002", "doc_date": "2026-10-29",
         "description": "تسویه با فروشنده — دسته 2", "issuer": {"code": "P"},
         "counterparty": {"role": "platform", "id": None, "code": "P", "name": "۶۰آنلاین",
                          "national_id": "", "economic_code": ""},
         "lines": [], "totals": {"gross_minor": 900_000, "discount_minor": 0, "net_minor": 900_000,
                                 "vat_minor": 0, "total_minor": 900_000},
         "voucher": [_v("bank", "1101", "", 900_000, 0, "تسویه ST-00000002"),
                     _v("receivable", "1301", "P", 0, 900_000, "تسویه ST-00000002")],
         "source": {"table": "settlement_payments", "id": 2}, "settlement_method": 1},
    ],
    "totals": {"documents": 2, "debit_minor": 5_025_000, "credit_minor": 5_025_000},
}


def render(connector, layout=None):
    return get_finance_formatter(connector, config={"layout": layout} if layout else None).render(FIXTURE)


class FormatSamples(unittest.TestCase):
    def test_jalali(self):
        self.assertEqual(gregorian_to_jalali(2026, 3, 21), (1405, 1, 1))
        self.assertEqual(gregorian_to_jalali(2026, 10, 25), (1405, 8, 3))

    def test_sepidar_vouchers(self):
        out = render("SEPIDAR")
        self.assertEqual(out["file_name"], "60online-sepidar-seller-7-2026-10-23_2026-10-29-vouchers.csv")
        self.assertEqual(out["content"], BOM + (
            "ردیف,شماره سند,تاریخ سند,شرح سند,کد حساب,کد تفصیلی,شرح ردیف,بدهکار,بستانکار,شماره مرجع\r\n"
            "1,1,1405/08/03,فاکتور فروش سفارش ORD-1,1301,P,فروش SI-00000011,4125000,0,SI-00000011\r\n"
            "2,1,1405/08/03,فاکتور فروش سفارش ORD-1,4101,O3,درآمد فروش SI-00000011,0,3750000,SI-00000011\r\n"
            "3,1,1405/08/03,فاکتور فروش سفارش ORD-1,2201,,ارزش افزوده SI-00000011,0,375000,SI-00000011\r\n"
            "1,2,1405/08/07,تسویه با فروشنده — دسته 2,1101,,تسویه ST-00000002,900000,0,ST-00000002\r\n"
            "2,2,1405/08/07,تسویه با فروشنده — دسته 2,1301,P,تسویه ST-00000002,0,900000,ST-00000002\r\n"))

    def test_sepidar_invoices(self):
        lines = render("SEPIDAR", "invoices")["content"].splitlines()
        self.assertEqual(len(lines), 2)  # payout has no item lines
        self.assertEqual(lines[1], "SI-00000011,1405/08/03,O3,شرکت الف,10101010101,501,کاغذ A4,3,1250000,"
                                   "3750000,0,375000,4125000")

    def test_mahak(self):
        lines = render("MAHAK")["content"].lstrip(BOM).splitlines()
        self.assertEqual(lines[0], "شماره سند,تاریخ,ردیف,کد حساب,کد تفصیلی,شرح,بدهکار,بستانکار")
        self.assertEqual(lines[1], "1,1405/08/03,1,1301,P,فروش SI-00000011 - SI-00000011,4125000,0")
        self.assertEqual(len(lines), 6)

    def test_holoo(self):
        lines = render("HOLOO")["content"].lstrip(BOM).splitlines()
        self.assertEqual(lines[0], "تاریخ,شماره سند,کد معین,کد تفصیلی,شرح,بدهکار,بستانکار")
        self.assertEqual(lines[5], "1405/08/07,2,1301,P,تسویه ST-00000002 (ST-00000002),0,900000")

    def test_generic_csv_and_excel(self):
        csv_out, xl = render("CSV"), render("EXCEL")
        self.assertEqual(csv_out["content"], xl["content"])
        self.assertTrue(csv_out["content"].startswith(BOM + "doc_type,doc_number,doc_date,line_no,account_key"))
        inv = render("CSV", "invoices")["content"].splitlines()
        self.assertEqual(inv[1], "sales_invoice,SI-00000011,2026-10-25,O3,شرکت الف,1,501,کاغذ A4,3,1250000,"
                                 "3750000,0,3750000,1000,375000,4125000")

    def test_json_roundtrip(self):
        out = render("JSON")
        self.assertEqual(json.loads(out["content"]), FIXTURE)

    def test_hamkaran_json_and_xml(self):
        p = json.loads(render("HAMKARAN")["content"])
        v = p["Vouchers"][0]
        self.assertEqual((v["Number"], v["Date"], len(v["Items"])), ("SI-00000011", "1405/08/03", 3))
        self.assertEqual(sum(i["Debit"] for i in v["Items"]), sum(i["Credit"] for i in v["Items"]))
        self.assertEqual(v["Items"][1], {"RowNumber": 2, "SLCode": "4101", "DLCode": "O3", "Debit": 0,
                                         "Credit": 3_750_000, "Description": "درآمد فروش SI-00000011"})
        xml = render("RAHKARAN", "xml")["content"]
        self.assertIn('<Voucher Number="SI-00000011" Date="1405/08/03">', xml)
        self.assertIn('<Item RowNumber="1" SLCode="1101" DLCode="" Debit="900000" Credit="0">تسویه ST-00000002</Item>',
                      xml)

    def test_deterministic_hashes(self):
        for c in ("SEPIDAR", "MAHAK", "HOLOO", "CSV", "JSON", "HAMKARAN"):
            a = hashlib.sha256(render(c)["content"].encode()).hexdigest()
            self.assertEqual(a, hashlib.sha256(render(c)["content"].encode()).hexdigest())

    def test_unknown_connector_and_layout(self):
        with self.assertRaises(ValidationError):
            get_finance_formatter("NOPE")
        with self.assertRaises(ValidationError):
            get_finance_formatter("MAHAK", config={"layout": "xml"})
        self.assertIn("MAHAK", [f["connector"] for f in list_finance_formats()])
        self.assertIn("MAHAK", [s["system"] for s in list_accounting_systems()])
        self.assertEqual(get_accounting_adapter("MAHAK").adapter_name, "mahak")

    def test_hamkaran_transport_injected(self):
        calls = []

        def transport(method, url, body, headers):
            calls.append((method, url, json.loads(body), headers))
            return 200, b'{"VoucherIds":[91]}'

        client = HamkaranVoucherClient(base_url="https://erp.local/api", transport=transport,
                                       token_provider=lambda: "t0k")
        res = client.submit(HamkaranVoucherFormatter().payload(FIXTURE))
        self.assertEqual(res["response"], {"VoucherIds": [91]})
        self.assertEqual(calls[0][1], "https://erp.local/api/Vouchers/Import")
        self.assertEqual(calls[0][3]["Authorization"], "Bearer t0k")
        with self.assertRaises(AccountingAdapterError):
            HamkaranVoucherClient().submit({})
        with self.assertRaises(AccountingAdapterError):
            HamkaranVoucherClient(transport=lambda *a: (503, b"")).submit({})


if __name__ == "__main__":
    unittest.main()
