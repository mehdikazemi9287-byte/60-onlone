"""Phase 5B — canonical finance export, jobs, Moadian payloads and API scoping (fixed DB fixtures)."""
from __future__ import annotations

import hashlib
import json

from tests.base import AppTestCase

from app.api.v1 import finance_exports as fx_api
from app.core.errors import NotFoundError, ValidationError
from app.services import finance_export_service as fx
from app.services import moadian_invoice_service as moadian

TS = "2026-10-25 10:00:00"


class FinanceFixture(AppTestCase):
    def setUp(self):
        super().setUp()
        if "finance_exports" not in self.app.blueprints:  # app/main.py registration is owned elsewhere
            self.app.register_blueprint(fx_api.bp)
        self.admin = self.admin_headers()
        self.seller_hdr, self.s1 = self._seller("s1@example.com", "فروشگاه یک", "10320000001")
        self.other_hdr, self.s2 = self._seller("s2@example.com", "فروشگاه دو", "10320000002")
        with self.db.write_transaction() as c:
            c.execute("""INSERT INTO organizations (legal_name, display_name, national_id, status, economic_code,
                         created_at, updated_at) VALUES ('شرکت الف','الف','10101010101','active','411111111111',?,?)""",
                      (TS, TS))
            self.org = c.execute("SELECT id FROM organizations WHERE national_id='10101010101'").fetchone()[0]
            uid = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
            # order 1: org buyer, seller 1, two lines; order 2: individual, seller 2
            self.fo1 = self._order(c, uid, self.org, self.s1, [(3, 1_250_001), (2, 333_333)], credit=True)
            self.fo2 = self._order(c, uid, None, self.s2, [(1, 999_999)])

    def _seller(self, email, name, nid):
        self.register(email=email)
        hdr = {"Authorization": f"Bearer {self.login(email, 'Passw0rd!23')}"}
        with self.db.write_transaction() as c:
            uid = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
            c.execute("""INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, status, user_id,
                         commission_rate_bps, created_at, updated_at) VALUES (?,?,?,'retailer','active',?,800,?,?)""",
                      (name, name, nid, uid, TS, TS))
            sid = c.execute("SELECT id FROM suppliers WHERE national_id=?", (nid,)).fetchone()[0]
        return hdr, sid

    def _order(self, c, uid, org, sid, lines, credit=False):
        n = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] + 1
        total = sum(q * p for q, p in lines)
        c.execute("""INSERT INTO orders (order_number, user_id, status, subtotal_minor, shipping_fee_minor, tax_minor,
                     total_minor, currency, recipient_name, recipient_phone, shipping_province, shipping_city,
                     shipping_line1, shipping_postal_code, placed_at, organization_id, credit_minor, cash_minor)
                     VALUES (?,?,'paid',?,0,0,?,'IRR','خریدار','09120000000','تهران','تهران','خیابان','1234567890',?,?,?,?)""",
                  (f"P5B-{n}", uid, total, total, TS, org, total if credit else 0, 0 if credit else total))
        oid = c.execute("SELECT id FROM orders WHERE order_number=?", (f"P5B-{n}",)).fetchone()[0]
        pid = c.execute("SELECT id FROM products ORDER BY id LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO supplier_locations (supplier_id, province, city, created_at, updated_at) "
                  "VALUES (?,'تهران','تهران',?,?)", (sid, TS, TS))
        loc = c.execute("SELECT MAX(id) FROM supplier_locations").fetchone()[0]
        c.execute("""INSERT INTO fulfillment_orders (order_id, supplier_id, supplier_location_id, status,
                     gross_payable_minor, created_at, updated_at) VALUES (?,?,?,'delivered',?,?,?)""",
                  (oid, sid, loc, total, TS, TS))
        fo = c.execute("SELECT MAX(id) FROM fulfillment_orders").fetchone()[0]
        c.execute("INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, selling_price_minor, "
                  "created_at, updated_at) VALUES (?,?,?,1,?,?)", (pid, sid, loc, TS, TS))
        offer = c.execute("SELECT MAX(id) FROM seller_offers").fetchone()[0]
        for q, p in lines:
            c.execute("""INSERT INTO order_items (order_id, product_id, title_fa, sku, unit_price_minor, quantity,
                         line_total_minor) VALUES (?,?,'کالا','SKU',?,?,?)""", (oid, pid, p, q, q * p))
            oi = c.execute("SELECT MAX(id) FROM order_items").fetchone()[0]
            c.execute("""INSERT INTO fulfillment_order_items (fulfillment_order_id, order_item_id, seller_offer_id, product_id,
                         title_fa, quantity, selling_price_minor, cost_price_minor, line_selling_minor, line_cost_minor, created_at)
                         VALUES (?,?,?,?,'کالا',?,?,0,?,0,?)""", (fo, oi, offer, pid, q, p, q * p, TS))
        c.execute("""INSERT INTO supplier_payable_entries (supplier_id, fulfillment_order_id, gross_minor,
                     idempotency_key, status, created_at, commission_rate_bps, commission_minor)
                     VALUES (?,?,?,?, 'unbatched', ?, 800, ?)""",
                  (sid, fo, total, f"fulfillment:{fo}:sale-payable", TS, total * 800 // 10000))
        c.execute("""INSERT INTO payments (order_id, provider, provider_ref, method, amount_minor, currency, status,
                     created_at) VALUES (?,'mock',?,'card',?,'IRR','captured',?)""", (oid, f"ref-{oid}", total, TS))
        return fo

    def export(self, entity_type, entity_id=None, connector="JSON"):
        with self.db.read_transaction() as c:
            return fx.build_export(c, entity_type=entity_type, entity_id=entity_id,
                                   period_start="2026-10-23", period_end="2026-10-29", connector=connector)


class CanonicalExport(FinanceFixture):
    def _assert_reconciles(self, ex):
        for d in ex["documents"]:
            if d["lines"]:
                for k in ("gross_minor", "discount_minor", "net_minor", "vat_minor", "total_minor"):
                    self.assertEqual(d["totals"][k], sum(ln[k] for ln in d["lines"]), (d["doc_number"], k))
                for ln in d["lines"]:
                    self.assertEqual(ln["vat_minor"], ln["net_minor"] * ln["vat_rate_bps"] // 10000)
            self.assertEqual(sum(v["debit_minor"] for v in d["voucher"]),
                             sum(v["credit_minor"] for v in d["voucher"]), d["doc_number"])
            for v in d["voucher"]:
                self.assertIsInstance(v["debit_minor"], int)
        self.assertEqual(ex["totals"]["debit_minor"], ex["totals"]["credit_minor"])

    def test_platform_export_documents_and_balance(self):
        ex = self.export("platform")
        types = sorted({d["doc_type"] for d in ex["documents"]})
        self.assertEqual(types, ["commission_invoice", "receipt", "sales_invoice"])
        self._assert_reconciles(ex)
        si = next(d for d in ex["documents"] if d["doc_number"] == f"SI-{self.fo1:08d}")
        # 3×1,250,001 + 2×333,333 = 4,416,669; VAT 10% floored per line: 375,000 + 66,666
        self.assertEqual(si["totals"], {"gross_minor": 4_416_669, "discount_minor": 0, "net_minor": 4_416_669,
                                        "vat_minor": 441_666, "total_minor": 4_858_335})
        self.assertEqual(si["settlement_method"], 2)
        self.assertEqual(si["issuer"]["code"], f"S{self.s1}")

    def test_seller_sees_only_own_documents(self):
        with self.db.write_transaction() as c:
            for sid, net in ((self.s1, 900_000), (self.s2, 700_000)):
                c.execute("INSERT INTO settlement_batches (supplier_id, idempotency_key, status, net_minor, created_at,"
                          " updated_at) VALUES (?,?,'completed',?,?,?)", (sid, f"b-{sid}", net, TS, TS))
                b = c.execute("SELECT MAX(id) FROM settlement_batches").fetchone()[0]
                c.execute("INSERT INTO settlement_payments (settlement_batch_id, supplier_id, net_minor, created_at)"
                          " VALUES (?,?,?,?)", (b, sid, net, TS))
        ex = self.export("seller", self.s1)
        payouts = [d for d in ex["documents"] if d["doc_type"] == "settlement_payout"]
        self.assertEqual([d["totals"]["total_minor"] for d in payouts], [900_000])
        self.assertEqual([v["account_key"] for v in payouts[0]["voucher"]], ["bank", "receivable"])
        self._assert_reconciles(ex)
        nums = [d["doc_number"] for d in ex["documents"]]
        self.assertIn(f"SI-{self.fo1:08d}", nums)
        self.assertNotIn(f"SI-{self.fo2:08d}", nums)
        cm = next(d for d in ex["documents"] if d["doc_type"] == "commission_invoice")
        self.assertEqual(cm["lines"][0]["net_minor"], 4_416_669 * 800 // 10000)
        self.assertEqual(cm["counterparty"]["code"], f"S{self.s1}")

    def test_organization_purchase_invoices(self):
        ex = self.export("organization", self.org)
        self._assert_reconciles(ex)
        self.assertEqual([d["doc_type"] for d in ex["documents"]], ["purchase_invoice", "payment"])
        keys = [v["account_key"] for v in ex["documents"][0]["voucher"]]
        self.assertEqual(keys, ["purchases", "vat_receivable", "payable"])

    def test_mapping_override_and_validation(self):
        with self.db.write_transaction() as c:
            fx.upsert_mapping(c, {"connector": "sepidar", "account_key": "revenue", "account_code": "6101"})
            with self.assertRaises(ValidationError):
                fx.upsert_mapping(c, {"connector": "SEPIDAR", "account_key": "nope", "account_code": "1"})
        codes = {v["account_code"] for d in self.export("seller", self.s1, "SEPIDAR")["documents"]
                 for v in d["voucher"] if v["account_key"] == "revenue"}
        self.assertEqual(codes, {"6101"})
        self.assertEqual({v["account_code"] for d in self.export("seller", self.s1, "MAHAK")["documents"]
                          for v in d["voucher"] if v["account_key"] == "revenue"}, {"4101"})

    def test_job_idempotent_same_hash(self):
        with self.db.write_transaction() as c:
            a = fx.create_export_job(c, entity_type="seller", entity_id=self.s1, period_start="2026-10-23",
                                     period_end="2026-10-29", connector="SEPIDAR")
            b = fx.create_export_job(c, entity_type="seller", entity_id=self.s1, period_start="2026-10-23",
                                     period_end="2026-10-29", connector="SEPIDAR")
            content = fx.get_job(c, a["id"], with_content=True)["content"]
        self.assertEqual((a["id"], a["content_sha256"], b["reused"]), (b["id"], b["content_sha256"], True))
        self.assertEqual(hashlib.sha256(content.encode()).hexdigest(), a["content_sha256"])

    def test_bad_period(self):
        with self.assertRaises(ValidationError):
            with self.db.read_transaction() as c:
                fx.build_export(c, entity_type="platform", entity_id=None, period_start="2026-10-30",
                                period_end="2026-10-01")


class MoadianPayloads(FinanceFixture):
    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as c:
            moadian.set_fiscal_id(c, issuer_key=f"supplier:{self.s1}", fiscal_memory_id="A11216",
                                  economic_code="10320000001")
            moadian.set_fiscal_id(c, issuer_key="platform", fiscal_memory_id="B22327", economic_code="14000000001")

    def test_taxid_shape_and_check_digit(self):
        t = moadian.generate_taxid("A11216", moadian.indatim_for("2026-10-25"), 1)
        self.assertEqual(len(t), 22)
        self.assertEqual(t[:6], "A11216")
        days = moadian.indatim_for("2026-10-25") // 86_400_000
        self.assertEqual(int(t[6:11], 16), days)
        self.assertEqual(int(t[11:21], 16), 1)
        control = "A11216".replace("A", str(ord("A"))) + f"{days:06d}" + f"{1:012d}"
        self.assertTrue(moadian.verhoeff_valid(control + t[-1]))
        self.assertEqual(moadian.verhoeff_digit("236"), 3)  # classic Verhoeff test vector

    def test_seller_invoice_payload_totals(self):
        with self.db.write_transaction() as c:
            doc = moadian.build_document(c, f"fo:{self.fo1}", sstid_resolver=lambda ln, s: "2710000138624")
        h, body = doc["payload"]["header"], doc["payload"]["body"]
        self.assertEqual((doc["issuer_type"], doc["issuer_supplier_id"], doc["status"]), ("seller", self.s1, "built"))
        self.assertEqual((h["inty"], h["tob"], h["bid"], h["tinb"], h["tins"], h["setm"]),
                         (1, 2, "10101010101", "411111111111", "10320000001", 2))
        self.assertEqual((h["tprdis"], h["tdis"], h["tadis"], h["tvam"], h["todam"], h["tbill"]),
                         (4_416_669, 0, 4_416_669, 441_666, 0, 4_858_335))
        self.assertEqual(h["tbill"], sum(b["tsstam"] for b in body))
        self.assertEqual((h["cap"], h["insp"]), (0, 4_858_335))
        self.assertEqual(body[0], {"sstid": "2710000138624", "sstt": "کالا", "am": 3, "mu": moadian.DEFAULT_UNIT,
                                   "fee": 1_250_001, "prdis": 3_750_003, "dis": 0, "adis": 3_750_003, "vra": 10,
                                   "vam": 375_000, "odam": 0, "olam": 0, "tsstam": 4_125_003})
        with self.db.write_transaction() as c:
            again = moadian.build_document(c, f"fo:{self.fo1}")
        self.assertTrue(again["reused"])
        self.assertEqual(again["taxid"], h["taxid"])

    def test_platform_issues_only_commission(self):
        with self.db.write_transaction() as c:
            doc = moadian.build_document(c, f"commission:{self.s1}:2026-10-23:2026-10-29")
            with self.assertRaises(ValidationError):  # seller 2 has no fiscal id → cannot issue
                moadian.build_document(c, f"fo:{self.fo2}")
        h = doc["payload"]["header"]
        self.assertEqual((doc["issuer_type"], doc["issuer_supplier_id"], h["tins"]), ("platform", None, "14000000001"))
        self.assertEqual(h["bid"], "10320000001")
        self.assertEqual(h["tadis"], 4_416_669 * 800 // 10000)
        self.assertEqual(h["tbill"], h["tadis"] + h["tadis"] // 10)
        self.assertTrue(doc["warnings"])  # sstid missing → flagged

    def test_mark_submitted_and_submit_interface(self):
        with self.db.write_transaction() as c:
            d = moadian.build_document(c, f"fo:{self.fo1}", sstid_resolver=lambda ln, s: "2710000138624")
            signed = []
            out = moadian.submit_document(c, d["id"], signer=lambda p: signed.append(p) or "JWS",
                                          transport=lambda pkt, taxid: {"reference": f"R-{taxid}"})
            self.assertEqual((out["status"], out["submission_reference"]), ("submitted", f"R-{d['taxid']}"))
            out = moadian.mark_submitted(c, d["id"], reference="R-1", status="accepted")
            self.assertEqual(out["status"], "accepted")
            with self.assertRaises(ValidationError):
                moadian.mark_submitted(c, d["id"], reference="R-2", status="rejected")
            c2 = moadian.build_document(c, f"commission:{self.s1}:2026-10-23:2026-10-29")
            with self.assertRaises(ValidationError):  # missing sstid blocks submission
                moadian.submit_document(c, c2["id"], signer=lambda p: "x", transport=lambda *a: {"reference": "r"})
            with self.assertRaises(NotFoundError):
                moadian.get_document(c, d["id"], supplier_id=self.s2)


class FinanceApi(FinanceFixture):
    def test_admin_flow(self):
        r = self.client.post("/api/v1/admin/finance-exports", headers=self.admin,
                             json={"entity_type": "platform", "period_start": "2026-10-23",
                                   "period_end": "2026-10-29", "connector": "MAHAK"})
        self.assertEqual(r.status_code, 201, r.get_json())
        job = r.get_json()["job"]
        r2 = self.client.post("/api/v1/admin/finance-exports", headers=self.admin,
                              json={"entity_type": "platform", "period_start": "2026-10-23",
                                    "period_end": "2026-10-29", "connector": "MAHAK"})
        self.assertEqual((r2.status_code, r2.get_json()["job"]["id"]), (200, job["id"]))
        dl = self.client.get(f"/api/v1/admin/finance-exports/{job['id']}/download", headers=self.admin)
        self.assertEqual(hashlib.sha256(dl.data).hexdigest(), job["content_sha256"])
        self.assertIn("attachment", dl.headers["Content-Disposition"])
        m = self.client.post("/api/v1/admin/finance-mappings", headers=self.admin,
                             json={"connector": "MAHAK", "account_key": "bank", "account_code": "111"})
        self.assertEqual(m.status_code, 200)
        mid = m.get_json()["mapping"]["id"]
        self.assertEqual(self.client.delete(f"/api/v1/admin/finance-mappings/{mid}", headers=self.admin).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/finance-exports", headers=self.seller_hdr).status_code, 403)
        self.client.put("/api/v1/admin/moadian/fiscal-ids", headers=self.admin,
                        json={"issuer_key": f"supplier:{self.s1}", "fiscal_memory_id": "A11216"})
        p = self.client.post("/api/v1/admin/moadian/preview", headers=self.admin, json={"source_ref": f"fo:{self.fo1}"})
        self.assertEqual(p.status_code, 200, p.get_json())
        b = self.client.post("/api/v1/admin/moadian/documents", headers=self.admin, json={"source_ref": f"fo:{self.fo1}"})
        self.assertEqual(b.status_code, 201)
        self.assertEqual(b.get_json()["document"]["taxid"], p.get_json()["payload"]["header"]["taxid"])
        ms = self.client.post(f"/api/v1/admin/moadian/documents/{b.get_json()['document']['id']}/mark-submitted",
                              headers=self.admin, json={"reference": "TRK-1"})
        self.assertEqual(ms.get_json()["document"]["status"], "submitted")

    def test_supplier_scoping(self):
        r = self.client.post("/api/v1/supplier/finance-exports", headers=self.seller_hdr,
                             json={"period_start": "2026-10-23", "period_end": "2026-10-29", "connector": "JSON",
                                   "entity_type": "platform", "entity_id": self.s2})  # ignored: forced to own
        self.assertEqual(r.status_code, 201, r.get_json())
        job = r.get_json()["job"]
        self.assertEqual((job["entity_type"], job["entity_id"]), ("seller", self.s1))
        dl = self.client.get(f"/api/v1/supplier/finance-exports/{job['id']}/download", headers=self.seller_hdr)
        data = json.loads(dl.data)
        self.assertTrue(all(d["issuer"]["code"] == f"S{self.s1}" or d["counterparty"]["code"] == f"S{self.s1}"
                            or d["doc_type"] == "settlement_payout" for d in data["documents"]))
        self.assertEqual(self.client.get(f"/api/v1/supplier/finance-exports/{job['id']}/download",
                                         headers=self.other_hdr).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/supplier/finance-exports", headers=self.other_hdr)
                         .get_json()["jobs"], [])
        admin_job = self.client.post("/api/v1/admin/finance-exports", headers=self.admin,
                                     json={"entity_type": "platform", "period_start": "2026-10-23",
                                           "period_end": "2026-10-29"}).get_json()["job"]
        self.assertEqual(self.client.get(f"/api/v1/supplier/finance-exports/{admin_job['id']}/download",
                                         headers=self.seller_hdr).status_code, 404)
