"""PIN, not a decision: VAT on shipping as the code computes it TODAY, in both paths.

Open owner/accountant decision («تصمیم ۱۱» in the group MASTER-PLAN; docs/decisions/2026-11-18-federated-credit-vandapay.md §VAT):
  * retail cart (quote_service) and organisation orders (org_order_service._tax): shipping is VAT-EXEMPT;
  * RFQ / supplier quote → PO (rfq_service.submit_supplier_quote): shipping is VAT-CHARGEABLE at the item rate.
These tests make any change to either rule a deliberate, reviewed edit. When the decision is taken, update
the code AND these tests together (and the VandaPay ``build_items`` shipping line).
"""
from __future__ import annotations

from app.adapters.payment.vandapay import build_items
from app.services import cart_service
from tests.base import AppTestCase
from tests.test_vat_procurement_regression import _make_org_with_admin, _setup_full_rfq


class RetailShippingVatPin(AppTestCase):
    def test_retail_quote_shipping_is_vat_exempt(self):
        _, headers = self.new_customer()
        kettle = self.product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 5)
        self.add_to_cart(headers, kettle["id"], 1)
        q = self.quote(headers)
        sub, ship = q["cart"]["subtotal_minor"], q["cart"]["shipping_fee_minor"]
        self.assertEqual(ship, cart_service.SHIPPING_FLAT_MINOR)
        self.assertGreater(ship, 0)
        self.assertEqual(q["taxable_base_minor"], sub)  # shipping NOT in the VAT base
        self.assertEqual(q["tax_minor"], sub * q["tax_rate_bps"] // 10_000)
        self.assertEqual(q["cart"]["total_minor"], sub + ship + q["tax_minor"])

    def test_vandapay_items_send_shipping_without_vat(self):
        items = build_items(lines=[{"product_id": 1, "sku": "K", "title_fa": "کتری", "quantity": 1,
                                    "line_total_minor": 11_900_000}],
                            subtotal_minor=11_900_000, shipping_minor=500_000, tax_minor=1_190_000,
                            tax_rate_bps=1000, currency="IRR")
        self.assertEqual([i["amount"] for i in items], [13_090_000, 500_000])


class OrgOrderShippingVatPin(AppTestCase):
    def test_org_order_tax_helper_is_merchandise_only(self):
        from app.services.org_order_service import _tax
        with self.db.read_transaction() as conn:
            tax, bps = _tax(conn, 1_000_000, None)
        self.assertEqual(tax, 1_000_000 * bps // 10_000)  # the helper never sees shipping


class RfqShippingVatPin(AppTestCase):
    def test_rfq_supplier_quote_charges_vat_on_shipping(self):
        org, _admin_h, admin_uid = _make_org_with_admin(self)
        rfq_id, item_ids, supplier_id = _setup_full_rfq(self, org["id"], admin_uid, [{"quantity": 1}],
                                                        shipping_cost_minor=200_000)
        from app.services.rfq_service import submit_supplier_quote
        with self.db.write_transaction() as conn:
            quote = submit_supplier_quote(conn, rfq_id, supplier_id=supplier_id,
                                          items=[{"rfq_item_id": item_ids[0], "unit_price_minor": 100_000,
                                                  "quantity": 1}],
                                          shipping_cost_minor=200_000)
        bps = quote["shipping_vat_rate_bps"]
        self.assertGreater(bps, 0)
        self.assertEqual(quote["shipping_vat_minor"], 200_000 * bps // 10_000)
