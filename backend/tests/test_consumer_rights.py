"""Legal checklist: statutory withdrawal, terms acceptance evidence, escrow floor, VAT-inclusive price."""
from __future__ import annotations

import datetime as dt
import sqlite3

from app.core.errors import ConflictError
from app.services import consumer_rights_service as rights
from app.services import settlement_service
from tests.base import AppTestCase
from tests.test_settlement import _make_delivered_payable

UTC = dt.timezone.utc


class WorkingDaysTest(AppTestCase):
    seed_data = False

    def test_fridays_and_holidays_skipped(self):
        # Wed 2026-11-04 10:00 Tehran → 7 working days skipping Fri 6th and Fri 13th → Thu 12th? count:
        # Thu5,Sat7,Sun8,Mon9,Tue10,Wed11,Thu12 = 7 → deadline end of Thu 12 Nov (Tehran).
        start = dt.datetime(2026, 11, 4, 6, 30, tzinfo=UTC)
        end = rights.add_working_days(start, 7)
        self.assertEqual(end.astimezone(dt.timezone(dt.timedelta(hours=3, minutes=30))).date(), dt.date(2026, 11, 12))
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"WITHDRAWAL_HOLIDAYS": "2026-11-08"}):
            end2 = rights.add_working_days(start, 7)
        self.assertEqual(end2.astimezone(dt.timezone(dt.timedelta(hours=3, minutes=30))).date(), dt.date(2026, 11, 14))


class WithdrawalFlowTest(AppTestCase):
    def _delivered_order(self):
        supplier_id, entry = _make_delivered_payable(self)
        with self.db.write_transaction() as conn:
            fo = conn.execute("SELECT fo.id, fo.order_id, o.order_number, o.user_id FROM fulfillment_orders fo "
                              "JOIN orders o ON o.id=fo.order_id WHERE fo.id=?", (entry["fulfillment_order_id"],)).fetchone()
            conn.execute("UPDATE fulfillment_orders SET delivered_at=? WHERE id=?",
                         (dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"), fo["id"]))
        return supplier_id, entry, dict(fo)

    def test_window_withdraw_no_reason_and_settlement_blocked(self):
        supplier_id, entry, fo = self._delivered_order()
        with self.db.write_transaction() as conn:
            w = rights.withdrawal_window(conn, user_id=fo["user_id"], order_number=fo["order_number"])
            self.assertTrue(w["open"])
            self.assertIn("بدون ذکر دلیل", w["notice_fa"])
            r = rights.request_withdrawal(conn, user_id=fo["user_id"], order_number=fo["order_number"], data={})
            self.assertEqual(r["status"], "approved")
            self.assertEqual(r["kind"], "withdrawal")
            self.assertIsNotNone(r["refund_due_at"])
            with self.assertRaises(ConflictError) as e:  # one open request at a time
                rights.request_withdrawal(conn, user_id=fo["user_id"], order_number=fo["order_number"], data={})
            self.assertEqual(e.exception.code, "return_open")
            with self.assertRaises(ConflictError) as e:  # seller is not paid while the withdrawal is open
                settlement_service.create_settlement_batch(conn, supplier_id=supplier_id,
                                                           payable_entry_ids=[entry["id"]], idempotency_key="w1")
            self.assertEqual(e.exception.code, "return_open")

    def test_window_closed_and_exempt_goods(self):
        _, _, fo = self._delivered_order()
        with self.db.write_transaction() as conn:
            late = dt.datetime.now(UTC) + dt.timedelta(days=20)
            with self.assertRaises(ConflictError) as e:
                rights.request_withdrawal(conn, user_id=fo["user_id"], order_number=fo["order_number"], data={}, now=late)
            self.assertEqual(e.exception.code, "withdrawal_window_closed")
            pid = conn.execute("SELECT product_id FROM order_items WHERE order_id=?", (fo["order_id"],)).fetchone()[0]
            conn.execute("UPDATE products SET withdrawal_exempt_reason='perishable' WHERE id=?", (pid,))
            with self.assertRaises(ConflictError) as e:
                rights.request_withdrawal(conn, user_id=fo["user_id"], order_number=fo["order_number"],
                                          data={"items": [{"product_id": pid, "quantity": 1}]})
            self.assertEqual(e.exception.code, "withdrawal_exempt")

    def test_api_requires_owner(self):
        _, _, fo = self._delivered_order()
        _, other = self.new_customer()
        r = self.client.get(f"/api/v1/me/orders/{fo['order_number']}/withdrawal", headers=other)
        self.assertEqual(r.status_code, 404)

    def test_shop_escrow_not_before_withdrawal_window(self):
        supplier_id, entry, fo = self._delivered_order()
        with self.db.write_transaction() as conn:
            floor = rights.escrow_floor(conn, fo["id"])
        self.assertGreaterEqual((floor - dt.datetime.now(UTC)).days, 7)  # 7 working days ≥ 8 calendar days


class TermsTest(AppTestCase):
    def test_acceptance_append_only_and_version_checked(self):
        _, h = self.new_customer()
        docs = self.client.get("/api/v1/legal/terms").get_json()["documents"]
        buyer = next(d for d in docs if d["doc_key"] == "buyer_terms")
        bad = self.client.post("/api/v1/me/terms-acceptances", json={"doc_key": "buyer_terms", "version": "old"}, headers=h)
        self.assertEqual(bad.status_code, 409)
        ok = self.client.post("/api/v1/me/terms-acceptances", json={"doc_key": "buyer_terms", "version": buyer["version"]},
                              headers={**h, "User-Agent": "test-agent"})
        self.assertEqual(ok.status_code, 201, ok.get_json())
        with self.db.write_transaction() as conn:
            row = conn.execute("SELECT * FROM terms_acceptances ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row["user_agent"], "test-agent")
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM terms_acceptances WHERE id=?", (row["id"],))
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE legal_documents SET version='x' WHERE doc_key='buyer_terms'")

    def test_checkout_requires_terms_when_enabled(self):
        import os
        from unittest import mock
        _, h = self.new_customer()
        with mock.patch.dict(os.environ, {"LEGAL_REQUIRE_BUYER_TERMS": "1"}):
            r = self.client.post("/api/v1/checkout", json={"shipping_address": {}}, headers={**h, "Idempotency-Key": "t1"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "terms_required")


class VatDisplayTest(AppTestCase):
    def test_gross(self):
        self.assertEqual(rights.gross(1_000_000, 1000), 1_100_000)
        self.assertIsNone(rights.gross(None, 1000))


class ReviewFixesTest(AppTestCase):
    def test_duplicate_withdrawal_lines_cannot_exceed_bought(self):
        supplier_id, entry, fo = WithdrawalFlowTest._delivered_order(self)
        with self.db.write_transaction() as conn:
            line = conn.execute("SELECT product_id, quantity FROM order_items WHERE order_id=?", (fo["order_id"],)).fetchone()
            from app.core.errors import ValidationError
            with self.assertRaises(ValidationError):
                rights.request_withdrawal(conn, user_id=fo["user_id"], order_number=fo["order_number"], data={
                    "items": [{"product_id": line[0], "quantity": line[1]}, {"product_id": line[0], "quantity": 1}]})

    def test_csv_formula_cells_neutralised(self):
        from app.adapters.accounting.finance_formats import csv_text, safe_cell
        self.assertEqual(safe_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(safe_cell("-1000"), "-1000")
        self.assertEqual(safe_cell(-1000), -1000)
        self.assertIn("'@SUM", csv_text(["a"], [["@SUM(A1)"]], bom=False))

    def test_withdrawal_after_batching_blocks_completion(self):
        supplier_id, entry, fo = WithdrawalFlowTest._delivered_order(self)
        with self.db.write_transaction() as conn:
            b = settlement_service.create_settlement_batch(conn, supplier_id=supplier_id,
                                                           payable_entry_ids=[entry["id"]], idempotency_key="rb1")
            rights.request_withdrawal(conn, user_id=fo["user_id"], order_number=fo["order_number"], data={})
            with self.assertRaises(ConflictError) as e:
                settlement_service.complete_settlement_batch(conn, batch_id=b["id"])
            self.assertEqual(e.exception.code, "return_open")
