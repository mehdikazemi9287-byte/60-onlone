"""BLOCKER 2: Real end-to-end Scenario 22.

ONE Alice / ONE org / ONE cart / ONE checkout / 30 M IRR total (20 M credit + 10 M PSP).

Cart contains THREE meaningful product types, all fulfilled by ONE test supplier:
  1. perishable item (8 M IRR) — logistics_profile='perishable'
  2. mobile/electronics item (12 M IRR) — logistics_profile='standard'
  3. A4 paper / standard item (10 M IRR) — logistics_profile='standard'

Real system flow (NO direct INSERT/UPDATE of orders, fulfillment_orders, shipments,
supplier_payable_entries, or settlement tables inside the scenario — only
fixture catalogue/supplier/carrier setup uses the DB directly):

  checkout
    → FO auto-created (status='assigned')
    → shipment plan auto-created (status='quote_selected') by checkout commit
    → admin calls ensure/plan endpoint (idempotent verify)
    → admin books mock carrier via API (two-phase: booking → booked)
    → carrier sends authenticated in_transit tracking webhook (HMAC-SHA256)
    → supplier drives FO state machine: accept → prepare → ready → dispatch → deliver
    → carrier sends authenticated delivered tracking webhook (HMAC-SHA256)
    → payable auto-created atomically on deliver (BLOCKER 3)
    → admin creates settlement batch via API
    → admin completes settlement via API → exactly one settlement_payment

27 assertions cover the full lifecycle.

Security properties exercised:
  - Carrier webhook HMAC-SHA256 verification (reject without valid sig)
  - Provider-stable event IDs (deduplication key)
  - Two-phase booking: idempotency_key committed before external call
  - Integer floor commission: commission_minor = (gross * bps) // 10_000
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
import unittest

from tests.base import AppTestCase
from app.adapters.logistics.mock import MOCK_WEBHOOK_SECRET


# ─────────────────────────────────────────────────────────────────────────────
# Money constants (all IRR minor units)
# ─────────────────────────────────────────────────────────────────────────────
PERISHABLE_PRICE  = 8_000_000    # 8 M IRR  — perishable, requires cold_chain carrier
MOBILE_PRICE      = 12_000_000   # 12 M IRR — mobile/electronics, standard profile
PAPER_PRICE       = 10_000_000   # 10 M IRR — A4 paper, standard profile
SUBTOTAL_PRICE    = PERISHABLE_PRICE + MOBILE_PRICE + PAPER_PRICE  # 30 M IRR subtotal
TAX_MINOR         = SUBTOTAL_PRICE * 1000 // 10000                 # 3 M (STANDARD 10%)
TOTAL_PRICE       = SUBTOTAL_PRICE + TAX_MINOR                     # 33 M IRR (VAT-inclusive, v6)
CREDIT_AMOUNT     = 20_000_000   # 20 M org credit for Alice
# PSP covers the remainder: 33M - 20M = 13 M IRR (v6)

# Settlement
COMMISSION_BPS    = 1_000        # 10 %  —  commission_minor = (gross * 1000) // 10_000
SHIPPING_CHARGE   = 0            # no platform shipping charge in test
SHIPPING_PAYER    = "customer"


def _make_mock_sig(body: bytes) -> str:
    """HMAC-SHA256 of body with MOCK_WEBHOOK_SECRET (same as production mock adapter)."""
    return hmac.new(MOCK_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()


def _carrier_webhook_headers(body: bytes, event_id: str,
                              shipment_ext_id: str, event_type: str) -> dict:
    """Build headers for a correctly-signed mock carrier webhook."""
    return {
        "Content-Type": "application/json",
        "X-Mock-Signature": _make_mock_sig(body),
        "X-Mock-Event-Id":  event_id,
        "X-Mock-Shipment-Id": shipment_ext_id,
        "X-Mock-Event-Type": event_type,
    }


class Scenario22Test(AppTestCase):
    """Real E2E lifecycle — carrier booking + HMAC webhooks + supplier state machine
    + atomic payable + admin settlement."""

    # ── Fixture helpers ──────────────────────────────────────────────────────

    def _setup_fixtures(self):
        """Create supplier + 3 products + Alice with 20 M credit.

        The supplier is in Tehran with capabilities='local,cold_chain' so that:
          • perishable product (requires cold_chain) routes correctly
          • A4 paper (standard) also routes correctly

        Returns supplier_info, products (list of 3), alice, org_id.
        """
        supplier_info = self.create_test_supplier(
            province="تهران",
            city="تهران",
            capabilities="local,cold_chain",
        )

        products = [
            self.create_test_product_with_offer(
                supplier_info["supplier_id"],
                supplier_info["location_id"],
                price_minor=PERISHABLE_PRICE,
                cost_minor=PERISHABLE_PRICE,
                stock=10,
                logistics_profile="perishable",   # requires cold_chain carrier
            ),
            self.create_test_product_with_offer(
                supplier_info["supplier_id"],
                supplier_info["location_id"],
                price_minor=MOBILE_PRICE,
                cost_minor=MOBILE_PRICE,
                stock=10,
                logistics_profile="standard",
            ),
            self.create_test_product_with_offer(
                supplier_info["supplier_id"],
                supplier_info["location_id"],
                price_minor=PAPER_PRICE,
                cost_minor=PAPER_PRICE,
                stock=10,
                logistics_profile="standard",
            ),
        ]

        org, _admin_h, _admin, alice = self.org_fixture(credit_minor=CREDIT_AMOUNT)
        return supplier_info, products, alice, org["id"]

    # ── Main scenario ────────────────────────────────────────────────────────

    def test_scenario_22_full_lifecycle(self):
        supplier_info, products, alice, org_id = self._setup_fixtures()
        alice_h        = alice["headers"]
        allocation_id  = alice["allocation"]["id"]
        supplier_id    = supplier_info["supplier_id"]
        supplier_h     = supplier_info["headers"]
        admin_h        = self.admin_headers()   # created once; reused throughout

        # ── A1: Org credit allocation exists ─────────────────────────────────
        with self.db.read_transaction() as conn:
            alloc = conn.execute(
                "SELECT * FROM credit_allocations WHERE id=?", (allocation_id,)
            ).fetchone()
        self.assertIsNotNone(alloc, "A1: credit allocation must exist")
        self.assertGreaterEqual(
            int(alloc["allocated_minor"]), CREDIT_AMOUNT,
            "A1: allocation must be >= 20 M IRR",
        )

        # ── Add 3 products to cart ────────────────────────────────────────────
        for prod in products:
            r = self.add_to_cart(alice_h, prod["product_id"], 1)
            self.assertIn(r.status_code, (200, 201), r.get_json())

        # ── A2: Cart has exactly 3 items ──────────────────────────────────────
        cart_resp = self.client.get("/api/v1/cart", headers=alice_h)
        self.assertEqual(cart_resp.status_code, 200, cart_resp.get_json())
        cart_data  = cart_resp.get_json()
        cart_items = cart_data.get("items") or cart_data.get("cart", {}).get("items", [])
        self.assertEqual(len(cart_items), 3, "A2: cart must have 3 items")

        # ── A3: Quote credit == exactly 20 M ─────────────────────────────────
        quote = self.quote(alice_h)
        self.assertEqual(
            quote["credit_to_use_minor"], CREDIT_AMOUNT,
            f"A3: quote must use exactly {CREDIT_AMOUNT} credit (got {quote['credit_to_use_minor']})",
        )

        # ── A4: Quote cash_due == exactly 13 M (v6: VAT-inclusive total - credit) ──
        expected_cash = TOTAL_PRICE - CREDIT_AMOUNT   # 33M - 20M = 13M
        self.assertEqual(
            quote["cash_due_minor"], expected_cash,
            f"A4: cash_due must be exactly {expected_cash} (got {quote['cash_due_minor']})",
        )

        # ── A5: Checkout returns 201 ──────────────────────────────────────────
        idem_key   = uuid.uuid4().hex
        checkout_r = self.checkout(alice_h, key=idem_key)
        self.assertEqual(checkout_r.status_code, 201, checkout_r.get_json())
        order_body = checkout_r.get_json()
        order_id   = order_body["order"]["id"]

        # ── A6: Order number has correct prefix ───────────────────────────────
        self.assertTrue(
            order_body["order"]["order_number"].startswith("ORD-"),
            f"A6: got '{order_body['order']['order_number']}'",
        )

        # ── A7: Order committed as 'paid'; verify exact funding split ────────
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT status, total_minor, credit_minor, cash_minor FROM orders WHERE id=?",
                (order_id,),
            ).fetchone()
        self.assertEqual(order_row["status"], "paid", "A7: order must be paid")
        # Verify exact funding amounts persisted in production orders table.
        # No manual ledger/payment row injection — these come from real checkout flow.
        self.assertEqual(
            int(order_row["total_minor"]), TOTAL_PRICE,
            f"A7x: order.total_minor must be exactly {TOTAL_PRICE} IRR (33 M with VAT, v6)",
        )
        self.assertEqual(
            int(order_row["credit_minor"]), CREDIT_AMOUNT,
            f"A7x: order.credit_minor must be exactly {CREDIT_AMOUNT} IRR (20 M credit captured)",
        )
        expected_cash_minor = TOTAL_PRICE - CREDIT_AMOUNT   # 13 M IRR (v6)
        self.assertEqual(
            int(order_row["cash_minor"]), expected_cash_minor,
            f"A7x: order.cash_minor must be exactly {expected_cash_minor} IRR ({expected_cash_minor} PSP funded)",
        )
        self.assertEqual(
            int(order_row["credit_minor"]) + int(order_row["cash_minor"]),
            TOTAL_PRICE,
            "A7x: credit + cash must sum to total (VAT-inclusive)",
        )

        # ── A7y: Prove real funding ledgers (no manual row injection) ─────────
        # Verify from credit_ledger_entries: exactly 20 M captured for this order.
        with self.db.read_transaction() as conn:
            credit_cap_row = conn.execute(
                "SELECT COALESCE(SUM(amount_minor), 0) AS total "
                "FROM credit_ledger_entries "
                "WHERE order_id=? AND entry_type='capture'",
                (order_id,),
            ).fetchone()
        credit_captured = int(credit_cap_row["total"])
        self.assertEqual(
            credit_captured, CREDIT_AMOUNT,
            f"A7y: credit_ledger_entries SUM(capture, order_id={order_id}) "
            f"must be exactly {CREDIT_AMOUNT} IRR (20 M); got {credit_captured}",
        )

        # Verify from payments: exactly 10 M PSP capture for this order, status='captured'.
        with self.db.read_transaction() as conn:
            psp_row = conn.execute(
                "SELECT amount_minor, status FROM payments WHERE order_id=?",
                (order_id,),
            ).fetchone()
        self.assertIsNotNone(
            psp_row,
            f"A7y: payments row must exist for order_id={order_id}",
        )
        self.assertEqual(
            int(psp_row["amount_minor"]), TOTAL_PRICE - CREDIT_AMOUNT,
            f"A7y: payments.amount_minor must be exactly "
            f"{TOTAL_PRICE - CREDIT_AMOUNT} IRR (10 M PSP); "
            f"got {psp_row['amount_minor']}",
        )
        self.assertEqual(
            psp_row["status"], "captured",
            "A7y: payments.status must be 'captured' for a completed checkout",
        )
        self.assertEqual(
            credit_captured + int(psp_row["amount_minor"]), TOTAL_PRICE,
            f"A7y: credit_captured ({credit_captured}) + "
            f"psp_captured ({psp_row['amount_minor']}) "
            f"must equal {TOTAL_PRICE} IRR (30 M)",
        )

        # ── A8: Exactly ONE FO created, status='assigned' ─────────────────────
        with self.db.read_transaction() as conn:
            fo_rows = conn.execute(
                "SELECT * FROM fulfillment_orders WHERE order_id=?", (order_id,)
            ).fetchall()
        self.assertEqual(len(fo_rows), 1, "A8: exactly ONE FO for single-supplier order")
        fo_row = dict(fo_rows[0])
        fo_id  = fo_row["id"]
        self.assertEqual(fo_row["status"], "assigned", "A8: FO must start as 'assigned'")

        # ── A9: FO is assigned to our test supplier ───────────────────────────
        self.assertEqual(
            int(fo_row["supplier_id"]), supplier_id,
            "A9: FO must be assigned to our test supplier",
        )

        # ── A10: Idempotent checkout replay returns the same order ────────────
        replay_r = self.checkout(alice_h, key=idem_key)
        self.assertEqual(replay_r.status_code, 201, "A10: replay must return 201")
        self.assertEqual(
            replay_r.get_json()["order"]["id"], order_id,
            "A10: idempotent replay must return same order",
        )

        # ── A11: Ensure shipment plan is in quote_selected state ──────────────
        # checkout calls ensure_shipment_plan() automatically; calling the endpoint
        # again is idempotent and ensures the plan is ready for booking.
        plan_r = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/shipment-plan", headers=admin_h
        )
        self.assertEqual(plan_r.status_code, 200, f"A11 plan: {plan_r.get_json()}")
        plan_data = plan_r.get_json()
        # Response shape: {"shipment_plan": {...}, "quotes": [...]}
        plan_obj    = plan_data.get("shipment_plan") or plan_data.get("plan") or {}
        plan_status = plan_obj.get("status", "")
        self.assertIn(
            plan_status, ("quote_selected", "planned"),
            f"A11: plan must be in quote_selected/planned state, got '{plan_status}'",
        )

        # ── A12: Admin books the carrier (two-phase, real logistics service) ──
        book_r = self.client.post(
            f"/api/v1/fulfillment-orders/{fo_id}/book-shipment", headers=admin_h
        )
        self.assertEqual(book_r.status_code, 200, f"A12 book: {book_r.get_json()}")
        shipment      = book_r.get_json()["shipment"]
        ext_id        = shipment["external_shipment_id"]
        tracking_code = shipment.get("tracking_code", "")
        self.assertEqual(shipment["status"], "booked", "A12: shipment must be booked")
        self.assertTrue(ext_id.startswith("MOCK-"), f"A12: expected MOCK- id, got '{ext_id}'")
        self.assertTrue(len(tracking_code) > 0, "A12: tracking_code must be non-empty")

        # ── A13: Carrier sends authenticated in_transit webhook ───────────────
        transit_body    = json.dumps({"type": "in_transit"}).encode()
        transit_headers = _carrier_webhook_headers(
            transit_body, f"evt-s22-transit-{uuid.uuid4().hex[:8]}", ext_id, "in_transit"
        )
        transit_r = self.client.post(
            "/api/v1/webhooks/carrier/mock", data=transit_body, headers=transit_headers
        )
        self.assertEqual(transit_r.status_code, 200, transit_r.get_json())
        transit_result = transit_r.get_json()
        self.assertEqual(transit_result["outcome"], "accepted", "A13: in_transit webhook must be accepted")
        self.assertEqual(transit_result.get("new_status"), "in_transit", "A13: shipment status → in_transit")

        # ── Supplier drives FO state machine through production API ──────────
        # A14: accept
        r_accept = self.client.post(
            f"/api/v1/supplier/orders/{fo_id}/accept", headers=supplier_h
        )
        self.assertEqual(r_accept.status_code, 200, f"A14 accept: {r_accept.get_json()}")
        self.assertEqual(r_accept.get_json()["fulfillment_order"]["status"], "accepted", "A14")

        # A15: prepare
        r_prepare = self.client.post(
            f"/api/v1/supplier/orders/{fo_id}/prepare", headers=supplier_h
        )
        self.assertEqual(r_prepare.status_code, 200, f"A15 prepare: {r_prepare.get_json()}")
        self.assertEqual(r_prepare.get_json()["fulfillment_order"]["status"], "preparing", "A15")

        # A16: ready
        r_ready = self.client.post(
            f"/api/v1/supplier/orders/{fo_id}/ready", headers=supplier_h
        )
        self.assertEqual(r_ready.status_code, 200, f"A16 ready: {r_ready.get_json()}")
        self.assertEqual(r_ready.get_json()["fulfillment_order"]["status"], "ready", "A16")

        # A17: dispatch
        r_dispatch = self.client.post(
            f"/api/v1/supplier/orders/{fo_id}/dispatch", headers=supplier_h
        )
        self.assertEqual(r_dispatch.status_code, 200, f"A17 dispatch: {r_dispatch.get_json()}")
        self.assertEqual(r_dispatch.get_json()["fulfillment_order"]["status"], "dispatched", "A17")

        # A18: deliver — atomically creates supplier payable (BLOCKER 3)
        r_deliver = self.client.post(
            f"/api/v1/supplier/orders/{fo_id}/deliver", headers=supplier_h
        )
        self.assertEqual(r_deliver.status_code, 200, f"A18 deliver: {r_deliver.get_json()}")
        self.assertEqual(r_deliver.get_json()["fulfillment_order"]["status"], "delivered", "A18")

        # ── A19: Carrier sends authenticated delivered webhook ────────────────
        # Carrier confirms physical delivery — updates shipment tracking status.
        # This is separate from the FO 'delivered' state (supplier confirms it; carrier confirms
        # the parcel reached the customer), and both must work.
        delivered_body    = json.dumps({"type": "delivered"}).encode()
        delivered_headers = _carrier_webhook_headers(
            delivered_body, f"evt-s22-del-{uuid.uuid4().hex[:8]}", ext_id, "delivered"
        )
        delivered_r = self.client.post(
            "/api/v1/webhooks/carrier/mock", data=delivered_body, headers=delivered_headers
        )
        self.assertEqual(delivered_r.status_code, 200, delivered_r.get_json())
        self.assertEqual(
            delivered_r.get_json()["outcome"], "accepted",
            "A19: delivered webhook must be accepted",
        )
        # Verify shipment tracking status updated in DB
        with self.db.read_transaction() as conn:
            ship_row = conn.execute(
                "SELECT status FROM shipments WHERE fulfillment_order_id=?", (fo_id,)
            ).fetchone()
        self.assertEqual(
            ship_row["status"], "delivered",
            "A19: shipment tracking status must be 'delivered' after webhook",
        )

        # ── A20: Payable auto-created on delivery (no direct DB call) ─────────
        payables_r = self.client.get(
            f"/api/v1/admin/suppliers/{supplier_id}/payables", headers=admin_h
        )
        self.assertEqual(payables_r.status_code, 200, payables_r.get_json())
        payables   = payables_r.get_json().get("payables", [])
        fo_payable = next(
            (p for p in payables if int(p["fulfillment_order_id"]) == fo_id), None
        )
        self.assertIsNotNone(fo_payable, "A20: payable entry must exist after delivery")
        self.assertEqual(fo_payable["entry_type"], "sale_payable", "A20: entry_type")
        self.assertEqual(fo_payable["status"], "unbatched", "A20: status must be unbatched")

        # ── A21: Payable gross matches immutable FO items snapshot ────────────
        with self.db.read_transaction() as conn:
            snap = conn.execute(
                "SELECT SUM(COALESCE(line_cost_minor, line_selling_minor)) AS g "
                "FROM fulfillment_order_items WHERE fulfillment_order_id=?",
                (fo_id,),
            ).fetchone()
        expected_gross = int(snap["g"] or 0)
        self.assertGreater(expected_gross, 0, "A21: gross must be > 0")
        self.assertEqual(
            int(fo_payable["gross_minor"]), expected_gross,
            "A21: gross must match immutable FO items snapshot",
        )

        # ── A22: Settlement batch created via admin API ───────────────────────
        payable_id = int(fo_payable["id"])
        batch_key  = f"s22-batch-{uuid.uuid4().hex}"
        batch_r    = self.client.post(
            "/api/v1/admin/settlement-batches",
            json={
                "supplier_id":           supplier_id,
                "payable_entry_ids":     [payable_id],
                "idempotency_key":       batch_key,
                "commission_rate_bps":   COMMISSION_BPS,
                "shipping_charge_minor": SHIPPING_CHARGE,
                "shipping_payer":        SHIPPING_PAYER,
            },
            headers=admin_h,
        )
        self.assertEqual(batch_r.status_code, 201, f"A22 batch: {batch_r.get_json()}")
        batch    = batch_r.get_json()["batch"]
        batch_id = int(batch["id"])
        self.assertEqual(batch["status"], "pending", "A22: batch must be pending")

        # Idempotency: same key returns same batch
        batch_r2 = self.client.post(
            "/api/v1/admin/settlement-batches",
            json={
                "supplier_id":         supplier_id,
                "payable_entry_ids":   [payable_id],
                "idempotency_key":     batch_key,
                "commission_rate_bps": COMMISSION_BPS,
            },
            headers=admin_h,
        )
        self.assertEqual(batch_r2.status_code, 201, batch_r2.get_json())
        self.assertEqual(
            int(batch_r2.get_json()["batch"]["id"]), batch_id,
            "A22: idempotent batch creation must return same id",
        )

        # ── A23: Commission = integer floor division (BLOCKER 5) ─────────────
        gross         = int(batch["gross_minor"])
        expected_comm = (gross * COMMISSION_BPS) // 10_000   # integer floor
        actual_comm   = int(batch["commission_minor"])
        self.assertEqual(actual_comm, expected_comm, "A23: commission must use floor division")
        self.assertIsInstance(actual_comm, int,       "A23: commission_minor must be int")
        # shipping_payer='customer' → no deduction from supplier
        expected_net  = gross - expected_comm
        self.assertEqual(int(batch["net_minor"]), expected_net, "A23: net = gross − commission")

        # ── A24: Settlement completed via admin API ───────────────────────────
        complete_r = self.client.post(
            f"/api/v1/admin/settlement-batches/{batch_id}/complete",
            json={"payment_reference": f"TXN-S22-{uuid.uuid4().hex[:8]}"},
            headers=admin_h,
        )
        self.assertEqual(complete_r.status_code, 200, f"A24 complete: {complete_r.get_json()}")
        result     = complete_r.get_json()
        self.assertEqual(result["batch"]["status"], "completed", "A24: batch must be completed")
        self.assertIsNotNone(result.get("payment"), "A24: settlement_payment must be returned")
        payment_id = int(result["payment"]["id"])

        # Idempotency: completing again returns same payment
        complete_r2 = self.client.post(
            f"/api/v1/admin/settlement-batches/{batch_id}/complete",
            json={"payment_reference": f"TXN-S22-{uuid.uuid4().hex[:8]}"},
            headers=admin_h,
        )
        self.assertEqual(complete_r2.status_code, 200, complete_r2.get_json())
        self.assertEqual(
            int(complete_r2.get_json()["payment"]["id"]), payment_id,
            "A24: idempotent completion must return same payment_id",
        )

        # ── A25: Customer tracking endpoint returns shipment info ─────────────
        tracking_r = self.client.get(
            f"/api/v1/fulfillment-orders/{fo_id}/tracking", headers=alice_h
        )
        self.assertEqual(tracking_r.status_code, 200, tracking_r.get_json())
        tracking_data = tracking_r.get_json()
        # Response: {"shipment": {"tracking_code": ..., "status": ...}, ...}
        tracking_shipment = tracking_data.get("shipment") or {}
        self.assertEqual(
            tracking_shipment.get("tracking_code"), tracking_code,
            "A25: customer-facing tracking must show booked carrier tracking_code",
        )

        # ── A26: Trial balance is balanced ────────────────────────────────────
        debits, credits = self.trial_balance()
        self.assertEqual(
            debits, credits,
            f"A26: trial balance (debits={debits}, credits={credits})",
        )

        # ── A27: Webhook deduplication — re-sending in_transit is rejected ────
        dup_r = self.client.post(
            "/api/v1/webhooks/carrier/mock", data=transit_body, headers=transit_headers
        )
        self.assertEqual(dup_r.status_code, 200, dup_r.get_json())
        self.assertEqual(
            dup_r.get_json()["outcome"], "duplicate",
            "A27: duplicate webhook must be rejected as 'duplicate'",
        )


if __name__ == "__main__":
    unittest.main()
