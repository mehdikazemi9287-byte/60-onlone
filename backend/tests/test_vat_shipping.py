"""Owner decision 11 (2026-11-18): VAT on shipping is ALWAYS applied — retail, organisation orders, RFQ/PO.

Replaces the earlier pin (tests/test_vat_shipping_pin.py) that froze the old, inconsistent behaviour
(retail + org orders exempt, RFQ/PO chargeable). Rules proven here:
  * 10% rate in basis points, integer minor units, integer floor (no floats);
  * retail cart and org orders: one floor on the taxable base ``subtotal + shipping``;
  * RFQ / supplier quote: per-item floors + ``shipping * bps // 10000`` (unchanged), and an org order or PO
    built from an awarded quote copies the quote's VAT, so Quote == PO == Order;
  * VandaPay ``items``: the shipping line carries its own VAT and ``sum(items.amount) == amount``.
Synthetic, clearly labelled test data only; disposable SQLite DB.
"""
from __future__ import annotations

import datetime
import uuid

from app.adapters.payment.vandapay import build_items, line_vat
from app.services import cart_service
from tests.base import AppTestCase
from tests.test_vat_procurement_regression import _make_org_with_admin, _setup_full_rfq

RATE_BPS = 1000  # Iran VAT 10%


class RetailShippingVatTest(AppTestCase):
    def _cart(self):
        _, headers = self.new_customer()
        kettle = self.product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 5)
        self.add_to_cart(headers, kettle["id"], 1)
        return headers

    def test_quote_puts_shipping_in_the_vat_base(self):
        q = self.quote(self._cart())
        sub, ship = q["cart"]["subtotal_minor"], q["cart"]["shipping_fee_minor"]
        self.assertEqual(ship, cart_service.SHIPPING_FLAT_MINOR)
        self.assertGreater(ship, 0)
        self.assertEqual(q["tax_rate_bps"], RATE_BPS)
        self.assertEqual(q["taxable_base_minor"], sub + ship)
        self.assertEqual(q["tax_minor"], (sub + ship) * RATE_BPS // 10_000)
        self.assertGreater(q["tax_minor"], sub * RATE_BPS // 10_000)  # strictly more than merchandise-only VAT
        self.assertEqual(q["cart"]["total_minor"], sub + ship + q["tax_minor"])
        self.assertEqual(q["cash_due_minor"], q["cart"]["total_minor"])

    def test_checkout_persists_the_same_snapshot_and_ledger_balances(self):
        headers = self._cart()
        q = self.quote(headers)
        r = self.checkout(headers)
        self.assertEqual(r.status_code, 201, r.get_json())
        order = r.get_json()["order"]
        self.assertEqual(order["tax_minor"], q["tax_minor"])
        self.assertEqual(order["total_minor"], q["cart"]["total_minor"])
        with self.db.read_transaction() as c:
            row = c.execute("SELECT subtotal_minor, shipping_fee_minor, tax_minor, taxable_base_minor, total_minor "
                            "FROM orders WHERE id=?", (order["id"],)).fetchone()
            vat_posted = c.execute(
                "SELECT COALESCE(SUM(CASE e.direction WHEN 'credit' THEN e.amount_minor ELSE -e.amount_minor END), 0) "
                "FROM ledger_entries e "
                "JOIN ledger_accounts a ON a.id = e.account_id WHERE a.code = '2010'").fetchone()[0]
        self.assertEqual(row["taxable_base_minor"], row["subtotal_minor"] + row["shipping_fee_minor"])
        self.assertEqual(row["tax_minor"], row["taxable_base_minor"] * RATE_BPS // 10_000)
        self.assertEqual(row["total_minor"], row["subtotal_minor"] + row["shipping_fee_minor"] + row["tax_minor"])
        self.assertEqual(vat_posted, row["tax_minor"])  # shipping VAT reaches VAT payable
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)


class VandaPayShippingLineVatTest(AppTestCase):
    LINE = {"product_id": 1, "sku": "K", "title_fa": "[TEST] کتری", "quantity": 1, "line_total_minor": 11_900_000}

    def test_shipping_line_carries_its_vat_and_items_add_up(self):
        sub, ship = 11_900_000, 500_000
        tax = (sub + ship) * RATE_BPS // 10_000
        items = build_items(lines=[self.LINE], subtotal_minor=sub, shipping_minor=ship, tax_minor=tax,
                            tax_rate_bps=RATE_BPS, currency="IRR")
        self.assertEqual([i["amount"] for i in items], [sub + 1_190_000, ship + 50_000])
        self.assertEqual(items[-1]["sku"], "SHIPPING")
        self.assertEqual(sum(i["amount"] for i in items), sub + ship + tax)

    def test_rounding_remainder_is_exact_and_bounded(self):
        lines = [dict(self.LINE, product_id=i, sku=f"K{i}", line_total_minor=v)
                 for i, v in enumerate((333_337, 12_345, 99_999), start=1)]
        sub, ship = sum(l["line_total_minor"] for l in lines), 45_557
        tax = (sub + ship) * RATE_BPS // 10_000
        items = build_items(lines=lines, subtotal_minor=sub, shipping_minor=ship, tax_minor=tax,
                            tax_rate_bps=RATE_BPS, currency="IRR")
        self.assertEqual(sum(i["amount"] for i in items), sub + ship + tax)
        self.assertTrue(all(type(i["amount"]) is int for i in items))
        ship_vat = items[-1]["amount"] - ship
        self.assertIn(ship_vat, (ship * RATE_BPS // 10_000, ship * RATE_BPS // 10_000 + 1))

    def test_per_line_rule_from_a_quote_is_kept_as_is(self):
        # RFQ/PO VAT = Σ floor(item) + floor(shipping); line_vat must not re-spread it.
        bases = [100_005, 200_007, 45_009]
        tax = sum(b * RATE_BPS // 10_000 for b in bases)
        self.assertEqual(line_vat(bases, tax_minor=tax, rate_bps=RATE_BPS),
                         [b * RATE_BPS // 10_000 for b in bases])

    def test_toman_shipping_line_converted_with_its_vat(self):
        items = build_items(lines=[dict(self.LINE, line_total_minor=1_000_000)], subtotal_minor=1_000_000,
                            shipping_minor=50_000, tax_minor=105_000, tax_rate_bps=RATE_BPS, currency="IRT")
        self.assertEqual(items[-1]["amount"], (50_000 + 5_000) * 10)


class OrgOrderShippingVatTest(AppTestCase):
    def test_tax_helper_is_one_floor_on_the_given_base(self):
        from app.services.org_order_service import _tax
        with self.db.read_transaction() as conn:
            tax, bps = _tax(conn, 1_000_000 + 200_005, None)
        self.assertEqual(bps, RATE_BPS)
        self.assertEqual(tax, 1_200_005 * RATE_BPS // 10_000)

    def _master_with_offer(self):
        headers = self.admin_headers()
        p = {"canonical_name_fa": "[TEST ONLY] کالای مرجع " + uuid.uuid4().hex[:8], "brand": "[TEST ONLY] Brand",
             "category": "mobile", "unit": "عدد", "package_quantity": None, "tax_category": "STANDARD",
             "vat_applicable": True, "vat_rate_bps": RATE_BPS, "manual_review": True, "direct_form": True,
             "source_kind": "manual", "source_supplier_id": None, "source_reference": "[TEST ONLY] source",
             "reason": "[TEST ONLY] create", "confirm_real_source": True,
             "creation_request_key": str(uuid.uuid4()), "sku": "TEST-VATSHIP-" + uuid.uuid4().hex[:8],
             "identifiers": [], "media_ids": [], "status": "active", "supply_channel": "both"}
        r = self.client.post("/api/v1/admin/catalog/products", json=p, headers=headers)
        self.assertEqual(r.status_code, 201, r.get_json())
        mid = r.get_json()["id"]
        supplier = self.create_test_supplier()
        sku = self.create_test_product_with_offer(supplier["supplier_id"], supplier["location_id"],
                                                  price_minor=1_500_000, cost_minor=1_100_000, stock=100)
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.db.write_transaction() as c:
            c.execute("UPDATE products SET master_product_id=?, provenance='real' WHERE id=?", (mid, sku["product_id"]))
            c.execute("UPDATE seller_offers SET provenance='real', last_price_confirmed_at=?, "
                      "last_inventory_confirmed_at=?, channel='both' WHERE id=?", (stamp, stamp, sku["offer_id"]))
        return mid, supplier

    def test_order_from_awarded_quote_charges_shipping_vat_and_matches_quote_and_po(self):
        from app.services import org_order_service as svc
        from app.services import procurement_service as pr
        from app.services import purchase_order_service as po
        from app.services import rfq_service as rfq
        mid, supplier = self._master_with_offer()
        org = self.create_organization(name="[TEST ONLY] VAT shipping org")
        _, member = self.make_org_admin(org["id"])
        uid, ship = member["user_id"], 200_005
        with self.db.write_transaction() as c:
            req = pr.create_purchase_request(
                c, organization_id=org["id"], requester_user_id=uid, title="[TEST ONLY] درخواست",
                items=[{"master_product_id": mid, "quantity": 2, "unit": "عدد"}],
                delivery_province="تهران", delivery_city="تهران", delivery_address="[TEST] خیابان آزمایش ۱")
            pr.submit_purchase_request(c, req["id"], actor_user_id=uid, organization_id=org["id"])
            pr.approve_purchase_request(c, req["id"], actor_user_id=uid, organization_id=org["id"], action="approve")
            res = rfq.create_rfq(c, organization_id=org["id"], purchase_request_id=req["id"], actor_user_id=uid,
                                 title="[TEST ONLY] RFQ")
            rfq.invite_supplier_to_rfq(c, res["id"], actor_user_id=uid, organization_id=org["id"],
                                       supplier_id=supplier["supplier_id"])
            rfq.open_rfq(c, res["id"], actor_user_id=uid, organization_id=org["id"])
            quote = rfq.submit_supplier_quote(
                c, res["id"], supplier_id=supplier["supplier_id"], shipping_cost_minor=ship,
                items=[{"rfq_item_id": res["items"][0]["id"], "unit_price_minor": 1_000_003, "quantity": 2}])
            rfq.close_rfq(c, res["id"], actor_user_id=uid, organization_id=org["id"])
            rfq.award_rfq(c, res["id"], actor_user_id=uid, organization_id=org["id"], winning_quote_id=quote["id"])
            svc.update_buying_policy(c, organization_id=org["id"], actor_user_id=uid, data={"payment_method": "cash"})
        self.assertEqual(quote["shipping_vat_minor"], ship * RATE_BPS // 10_000)
        items_vat = 2_000_006 * RATE_BPS // 10_000
        expected_tax = items_vat + ship * RATE_BPS // 10_000
        with self.db.write_transaction() as c:
            status, body = svc.convert_purchase_request(
                c, organization_id=org["id"], actor_user_id=uid, idempotency_key="vat-ship-1",
                data={"purchase_request_id": req["id"], "supplier_quote_id": quote["id"],
                      "recipient": {"name": "[TEST] تدارکات", "phone": "02112345678"}})
        self.assertEqual(status, 201, body)
        order = body["order"] if "order" in body else body
        self.assertEqual(order["shipping_fee_minor"], ship)
        self.assertEqual(order["tax_minor"], expected_tax)
        self.assertEqual(order["total_minor"], 2_000_006 + ship + expected_tax)
        self.assertEqual(order["total_minor"], quote["grand_total_minor"])  # Quote == Order
        with self.db.read_transaction() as c:
            base = c.execute("SELECT taxable_base_minor FROM orders WHERE id=?", (order["id"],)).fetchone()[0]
        self.assertEqual(base, 2_000_006 + ship)
        with self.db.write_transaction() as c:
            p = po.create_purchase_order(c, organization_id=org["id"], actor_user_id=uid,
                                         supplier_quote_id=quote["id"])
        self.assertEqual(p["grand_total_minor"], order["total_minor"])  # PO == Order


class RfqShippingVatTest(AppTestCase):
    def test_supplier_quote_charges_vat_on_shipping(self):
        org, _admin_h, admin_uid = _make_org_with_admin(self)
        rfq_id, item_ids, supplier_id = _setup_full_rfq(self, org["id"], admin_uid, [{"quantity": 1}],
                                                        shipping_cost_minor=200_000)
        from app.services.rfq_service import submit_supplier_quote
        with self.db.write_transaction() as conn:
            quote = submit_supplier_quote(conn, rfq_id, supplier_id=supplier_id,
                                          items=[{"rfq_item_id": item_ids[0], "unit_price_minor": 100_000,
                                                  "quantity": 1}],
                                          shipping_cost_minor=200_000)
        self.assertEqual(quote["shipping_vat_rate_bps"], RATE_BPS)
        self.assertEqual(quote["shipping_vat_minor"], 200_000 * RATE_BPS // 10_000)
        self.assertEqual(quote["grand_total_minor"], 100_000 + 200_000 + 10_000 + 20_000)
