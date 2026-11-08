"""Phase 3 mandatory tests: Fulfillment-First Checkout.

Most important acceptance principle:
    NO CUSTOMER SHOULD BE SUCCESSFULLY CHARGED FOR AN ORDER THAT 60ONLINE HAS NOT
    SUCCESSFULLY PLANNED AND RESERVED FOR FULFILLMENT.

Coverage:
  A. No supplier → 422 fulfillment_unavailable, zero PSP charge, zero orders
  B. Credit user, no supplier → 422, zero credit consumed
  C. Atomic reservation: mixed cart, one item unroutable → all fail, other item not reserved
  D. PSP decline after supplier stock reserved → stock released by compensation
  E. Successful split checkout → correct reservation, FO created, ledger balanced

  Idempotency:
    - Same key after 201 → replayed 201, no second FO
    - Same key after 422 fulfillment_unavailable → replayed 422

  Scenario 18 (Alice/Isfahan, LOCAL_ONLY, success):
    Isfahan customer, LOCAL_ONLY policy, supplier X in Isfahan (stock=5), supplier Y in
    Tehran (cheaper, national).  X must be selected (not Y), stock reserved BEFORE PSP,
    FO created for X, Y's stock untouched.  Retry same key → idempotent.

  Scenario 19 (Alice/Isfahan, LOCAL_ONLY, no stock → must fail before PSP):
    Same setup but X has zero stock.  Y (Tehran) has stock but LOCAL_ONLY blocks it.
    Checkout must return 422 fulfillment_unavailable with no PSP call, no credit
    consumption, no order, and no FO.
"""
from __future__ import annotations

import uuid

from tests.base import AppTestCase


ISFAHAN_ADDRESS = {
    "recipient_name": "آلیس کریمی",
    "recipient_phone": "09131234567",
    "province": "اصفهان",
    "city": "اصفهان",
    "line1": "خیابان چهارباغ، پلاک ۵",
    "postal_code": "8134567890",
}


class _CheckoutBase(AppTestCase):
    """Common helpers for fulfillment-first checkout tests."""

    def _set_catalogue_price(self, conn, slug: str, price_minor: int) -> None:
        """Override the catalogue base_price for a product (controls what PSP is charged).

        Note: price is snapshotted into cart_items.unit_price_minor at add-to-cart time,
        so this must be called BEFORE the customer adds the item to their cart.
        """
        conn.execute(
            "UPDATE products SET base_price_minor=? WHERE slug=?", (price_minor, slug)
        )

    def _get_or_create_supplier(
        self, conn, *, nat_id, display_name, province, city,
        can_local=True, can_intercity=False, rating_x10=40,
    ) -> tuple[int, int]:
        existing = conn.execute(
            "SELECT id FROM suppliers WHERE national_id = ?", (nat_id,)
        ).fetchone()
        if existing:
            sup_id = int(existing["id"])
            loc_row = conn.execute(
                "SELECT id FROM supplier_locations WHERE supplier_id = ? LIMIT 1", (sup_id,)
            ).fetchone()
            return sup_id, int(loc_row["id"])

        cur = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10) "
            "VALUES (?,?,?,?,?)",
            (display_name, display_name, nat_id, "active", rating_x10),
        )
        sup_id = int(cur.lastrowid)
        cur2 = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping) "
            "VALUES (?,?,?,'active',?,?)",
            (sup_id, province, city, int(can_local), int(can_intercity)),
        )
        return sup_id, int(cur2.lastrowid)

    def _add_offer(
        self, conn, *, supplier_id, location_id, product_slug, stock, price=14_000_000,
    ) -> int:
        prod_id = int(conn.execute(
            "SELECT id FROM products WHERE slug=?", (product_slug,)
        ).fetchone()["id"])
        cur = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,?,?,'active','delivery')",
            (prod_id, supplier_id, location_id, price, stock),
        )
        return int(cur.lastrowid)

    def _set_policy(self, conn, slug, policy_name):
        conn.execute(
            "UPDATE products SET fulfillment_policy_id = "
            "(SELECT id FROM fulfillment_policies WHERE name=?) "
            "WHERE slug=?",
            (policy_name, slug),
        )

    def _zero_offers(self, conn, slug):
        """Remove all available stock from every offer for this product."""
        conn.execute(
            "UPDATE seller_offers SET stock_quantity=0, stock_reserved=0 "
            "WHERE product_id=(SELECT id FROM products WHERE slug=?)",
            (slug,),
        )

    def _count_orders(self, conn, user_id=None):
        if user_id is not None:
            return conn.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=? AND status='paid'", (user_id,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()[0]

    def _offer_reserved(self, offer_id: int) -> int:
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT stock_reserved FROM seller_offers WHERE id=?", (offer_id,)
            ).fetchone()
        return int(row["stock_reserved"])


# ─────────────────────────────────────────────────────────────────────────────
# A. No supplier → no charge, no order
# ─────────────────────────────────────────────────────────────────────────────

class TestFulfillmentUnavailableBlocksCheckout(_CheckoutBase):
    """Fulfillment must be planned BEFORE PSP.  If no supplier → 422, nothing moves."""

    def setUp(self):
        super().setUp()
        # Use paper as the test product; set to NATIONAL_SHIPPING
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "office-paper-a4-carton")
        self.product = super().product("office-paper-a4-carton")
        self.set_stock(self.product["id"], 10)

    def test_A_no_supplier_no_charge_cash(self):
        """Pure cash checkout with no available supplier must return 422 without any PSP call."""
        token, headers = self.new_customer()
        self.add_to_cart(headers, self.product["id"], 1)

        resp = self.checkout(headers)

        self.assertEqual(resp.status_code, 422, resp.get_json())
        body = resp.get_json()
        self.assertEqual(body["error"]["code"], "fulfillment_unavailable",
                         "Error code must be fulfillment_unavailable")

        # No paid order must exist in the DB
        with self.db.read_transaction() as conn:
            orders_paid = conn.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()[0]
        self.assertEqual(orders_paid, 0, "No paid order must exist after fulfillment_unavailable")

        # No payment intent in 'captured' state
        with self.db.read_transaction() as conn:
            captured = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]
        self.assertEqual(captured, 0, "No payment intent must be captured")

    def test_B_credit_user_no_supplier_no_credit_consumed(self):
        """Employee with credit: if no supplier, credit balance must remain untouched."""
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "appliance-kettle-2l")
        kettle = super().product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)

        credit_minor = 50_000_000
        org, admin_headers, _, employee = self.org_fixture(credit_minor=credit_minor)
        emp_h = employee["headers"]
        self.add_to_cart(emp_h, kettle["id"], 1)

        # Record credit balance before
        with self.db.read_transaction() as conn:
            balance_before = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount_minor "
                "WHEN entry_type='debit' THEN -amount_minor END), 0) "
                "FROM credit_ledger_entries WHERE allocation_id = ?",
                (employee["allocation"]["id"],),
            ).fetchone()[0]

        resp = self.checkout(emp_h)

        self.assertEqual(resp.status_code, 422, resp.get_json())
        self.assertEqual(resp.get_json()["error"]["code"], "fulfillment_unavailable")

        # Credit balance must be exactly the same
        with self.db.read_transaction() as conn:
            balance_after = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount_minor "
                "WHEN entry_type='debit' THEN -amount_minor END), 0) "
                "FROM credit_ledger_entries WHERE allocation_id = ?",
                (employee["allocation"]["id"],),
            ).fetchone()[0]

        self.assertEqual(balance_before, balance_after,
                         "Credit balance must not change when fulfillment is unavailable")

    def test_C_atomic_mixed_cart_one_item_fails_all_fail(self):
        """Mixed cart: item A has a supplier, item B has no supplier → full 422, A not reserved."""
        # Item A: paper — has a supplier (we'll add one back)
        # Item B: kettle — no supplier (already zeroed out in setUp logic below)
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "appliance-kettle-2l")
            # Add a supplier for paper so the router CAN route paper
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="ATOMIC-PPR-001", display_name="کاغذ اتمیک",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_paper = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="office-paper-a4-carton", stock=5, price=14_000_000,
            )

        kettle = super().product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)

        _, headers = self.new_customer()
        self.add_to_cart(headers, self.product["id"], 1)   # paper — routeable
        self.add_to_cart(headers, kettle["id"], 1)          # kettle — no supplier

        resp = self.checkout(headers)

        self.assertEqual(resp.status_code, 422, resp.get_json())
        self.assertEqual(resp.get_json()["error"]["code"], "fulfillment_unavailable")

        # Paper supplier's stock must NOT be reserved (transaction must have rolled back)
        self.assertEqual(self._offer_reserved(offer_paper), 0,
                         "Paper supplier stock must not be reserved when checkout fails atomically")


# ─────────────────────────────────────────────────────────────────────────────
# D. PSP decline after supplier stock reserved → compensation releases stock
# ─────────────────────────────────────────────────────────────────────────────

class TestCompensationOnPspDecline(_CheckoutBase):
    """When the PSP declines, _fail_attempt must release supplier stock (and credit)."""

    def test_D_psp_decline_releases_supplier_stock(self):
        """Mock PSP declines (total ends in 13) → supplier stock_reserved returns to 0.

        The mock PSP declines when `cash_minor % 100 == 13`.  The customer pays the
        catalogue price (not the offer price), so we set the catalogue price such that
        total_minor (price + VAT(10%) + 350,000 shipping) ends in 13.
        price=14,500,012 → tax=1,450,001 → total=16,300,013 → 16300013 % 100 == 13 ✓
        """
        # Price chosen so that total (price + VAT + 350,000 shipping) ends in 13
        DECLINE_CATALOGUE_PRICE = 14_500_012

        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "office-paper-a4-carton")
            self._set_catalogue_price(conn, "office-paper-a4-carton", DECLINE_CATALOGUE_PRICE)
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="COMP-PSP-001", display_name="جبران پرداخت",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="office-paper-a4-carton", stock=5, price=14_000_000,
            )

        paper = super().product("office-paper-a4-carton")
        self.set_stock(paper["id"], 10)
        _, headers = self.new_customer()
        self.add_to_cart(headers, paper["id"], 1)

        resp = self.checkout(headers)

        # PSP decline → 402 payment_failed
        self.assertEqual(resp.status_code, 402,
                         f"Expected 402 payment_failed from mock PSP decline, got: {resp.get_json()}")

        # Supplier stock reservation must be released
        self.assertEqual(self._offer_reserved(offer_id), 0,
                         "Supplier stock_reserved must be 0 after PSP decline compensation")

        # No paid order
        with self.db.read_transaction() as conn:
            orders_paid = conn.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()[0]
        self.assertEqual(orders_paid, 0, "No paid order after PSP decline")

    def test_D2_psp_decline_releases_credit(self):
        """Split checkout: PSP declines → credit reservation is also released.

        To produce a PSP decline in a split payment, the CASH portion must end in 13.
        price=12,000,012 → tax=1,200,001 → total=13,550,013. credit=5,000,000 → cash=8,550,013 → %100==13 ✓
        """
        DECLINE_CATALOGUE_PRICE = 12_000_012   # total=13,550,013, cash=8,550,013 → ends in 13
        PARTIAL_CREDIT = 5_000_000              # partial credit, not enough to cover all

        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "appliance-kettle-2l")
            self._set_catalogue_price(conn, "appliance-kettle-2l", DECLINE_CATALOGUE_PRICE)
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="COMP-CRED-001", display_name="جبران اعتبار",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="appliance-kettle-2l", stock=5, price=11_000_000,
            )

        kettle = super().product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)

        org, admin_headers, _, employee = self.org_fixture(credit_minor=PARTIAL_CREDIT)
        emp_h = employee["headers"]
        self.add_to_cart(emp_h, kettle["id"], 1)

        with self.db.read_transaction() as conn:
            balance_before = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount_minor "
                "WHEN entry_type='debit' THEN -amount_minor END), 0) "
                "FROM credit_ledger_entries WHERE allocation_id = ?",
                (employee["allocation"]["id"],),
            ).fetchone()[0]

        resp = self.checkout(emp_h)

        self.assertEqual(resp.status_code, 402, resp.get_json())

        # Supplier stock released
        self.assertEqual(self._offer_reserved(offer_id), 0,
                         "Supplier stock must be released after PSP decline")

        # Credit balance must be restored
        with self.db.read_transaction() as conn:
            balance_after = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN entry_type='credit' THEN amount_minor "
                "WHEN entry_type='debit' THEN -amount_minor END), 0) "
                "FROM credit_ledger_entries WHERE allocation_id = ?",
                (employee["allocation"]["id"],),
            ).fetchone()[0]

        self.assertEqual(balance_before, balance_after,
                         "Credit balance must be restored after PSP decline compensation")

    def test_E_successful_split_correct_reservation(self):
        """Successful split checkout: supplier stock reserved, FO created, ledger balanced."""
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "appliance-kettle-2l")
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="SPLIT-OK-001", display_name="اسپلیت موفق",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="appliance-kettle-2l", stock=5, price=12_000_000,
            )

        kettle = super().product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)

        org, admin_headers, _, employee = self.org_fixture(credit_minor=200_000_000)
        emp_h = employee["headers"]
        self.add_to_cart(emp_h, kettle["id"], 1)

        resp = self.checkout(emp_h)

        self.assertEqual(resp.status_code, 201, resp.get_json())
        order_data = resp.get_json()["order"]

        # Credit must have been used
        self.assertGreater(order_data.get("credit_minor", 0), 0, "Credit must be used in split")

        # Supplier stock must be reserved (1 unit)
        self.assertGreaterEqual(self._offer_reserved(offer_id), 1,
                                "Supplier stock must be reserved after successful checkout")

        # Fulfillment order must be created
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?",
                (order_data["order_number"],),
            ).fetchone()
            fo_count = conn.execute(
                "SELECT COUNT(*) FROM fulfillment_orders WHERE order_id=?",
                (int(order_row["id"]),),
            ).fetchone()[0]

        self.assertGreaterEqual(fo_count, 1, "Fulfillment order must be created")

        # Ledger must be balanced
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits, "Ledger must be balanced after split checkout")


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckoutIdempotency(_CheckoutBase):
    """Replaying the same Idempotency-Key must never create a second FO or double-charge."""

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "office-paper-a4-carton")
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="IDEM-001", display_name="ایدمپوتنت",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._offer_id = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="office-paper-a4-carton", stock=10, price=14_000_000,
            )
        self.paper = super().product("office-paper-a4-carton")
        self.set_stock(self.paper["id"], 10)

    def test_idempotency_same_key_returns_same_201(self):
        """Replaying a successful checkout key must return the same 201, no second FO."""
        _, headers = self.new_customer()
        self.add_to_cart(headers, self.paper["id"], 1)
        key = uuid.uuid4().hex

        resp1 = self.checkout(headers, key=key)
        self.assertEqual(resp1.status_code, 201, resp1.get_json())

        resp2 = self.checkout(headers, key=key)
        self.assertEqual(resp2.status_code, 201, resp2.get_json())

        # Must be the exact same order number
        self.assertEqual(
            resp1.get_json()["order"]["order_number"],
            resp2.get_json()["order"]["order_number"],
            "Idempotent replay must return the same order number",
        )

        # Exactly one FO, not two
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?",
                (resp1.get_json()["order"]["order_number"],),
            ).fetchone()
            fo_count = conn.execute(
                "SELECT COUNT(*) FROM fulfillment_orders WHERE order_id=?",
                (int(order_row["id"]),),
            ).fetchone()[0]

        self.assertEqual(fo_count, 1, "Idempotent replay must not create a second fulfillment order")

    def test_idempotency_failed_checkout_returns_same_error(self):
        """Replaying a key that failed (422 fulfillment_unavailable) returns same 422."""
        with self.db.write_transaction() as conn:
            self._zero_offers(conn, "office-paper-a4-carton")

        _, headers = self.new_customer()
        # Set stock back to something non-zero so inventory isn't the problem
        self.set_stock(self.paper["id"], 10)
        self.add_to_cart(headers, self.paper["id"], 1)
        key = uuid.uuid4().hex

        resp1 = self.checkout(headers, key=key)
        self.assertEqual(resp1.status_code, 422, resp1.get_json())

        # Re-add to cart (first checkout clears cart on failure... actually no, it rolls back)
        # Just retry with the same key. The cart may or may not still have items.
        resp2 = self.checkout(headers, key=key)
        self.assertEqual(resp2.status_code, 422,
                         "Replaying a failed-checkout key must return the same 422")
        self.assertEqual(resp2.get_json()["error"]["code"], "fulfillment_unavailable")

    def test_idempotency_no_double_supplier_stock_reservation(self):
        """Replaying a successful key must not increment stock_reserved twice."""
        # Re-add offer with stock
        with self.db.write_transaction() as conn:
            self._zero_offers(conn, "office-paper-a4-carton")
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="IDEM-STOCK-001", display_name="ایدمپوتنت موجودی",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="office-paper-a4-carton", stock=10, price=14_000_000,
            )

        _, headers = self.new_customer()
        self.set_stock(self.paper["id"], 10)
        self.add_to_cart(headers, self.paper["id"], 1)
        key = uuid.uuid4().hex

        resp1 = self.checkout(headers, key=key)
        self.assertEqual(resp1.status_code, 201, resp1.get_json())
        reserved_after_first = self._offer_reserved(offer_id)

        resp2 = self.checkout(headers, key=key)
        self.assertEqual(resp2.status_code, 201)
        reserved_after_second = self._offer_reserved(offer_id)

        self.assertEqual(reserved_after_first, reserved_after_second,
                         "Replaying checkout key must not double-reserve supplier stock")


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 18: Alice + Isfahan + LOCAL_ONLY + X has stock, Y cheaper national
# ─────────────────────────────────────────────────────────────────────────────

class TestAliceIsfahanScenarios(_CheckoutBase):
    """Scenario 18 + 19: Isfahan customer with LOCAL_ONLY fulfillment policy."""

    PRODUCT_SLUG = "appliance-kettle-2l"

    def _setup_isfahan_suppliers(self, *, x_stock: int = 5, y_stock: int = 10):
        """Configure: X in Isfahan (more expensive), Y in Tehran (cheaper, national)."""
        with self.db.write_transaction() as conn:
            self._set_policy(conn, self.PRODUCT_SLUG, "LOCAL_ONLY")
            self._zero_offers(conn, self.PRODUCT_SLUG)

            # Supplier X: local to Isfahan (the right choice for LOCAL_ONLY)
            x_sup, x_loc = self._get_or_create_supplier(
                conn, nat_id="ISF-X-001", display_name="تأمین اصفهان X",
                province="اصفهان", city="اصفهان", can_local=True, can_intercity=False,
                rating_x10=40,
            )
            x_offer = self._add_offer(
                conn, supplier_id=x_sup, location_id=x_loc,
                product_slug=self.PRODUCT_SLUG, stock=x_stock, price=13_500_000,
            )

            # Supplier Y: Tehran, cheaper, can ship nationally — but LOCAL_ONLY must block it
            y_sup, y_loc = self._get_or_create_supplier(
                conn, nat_id="ISF-Y-001", display_name="تأمین تهران Y",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
                rating_x10=45,
            )
            y_offer = self._add_offer(
                conn, supplier_id=y_sup, location_id=y_loc,
                product_slug=self.PRODUCT_SLUG, stock=y_stock, price=12_000_000,  # cheaper
            )

        kettle = super().product(self.PRODUCT_SLUG)
        self.set_stock(kettle["id"], 20)
        return kettle, x_sup, x_loc, x_offer, y_sup, y_loc, y_offer

    def test_scenario_18_isfahan_local_only_selects_x_not_y(self):
        """LOCAL_ONLY: Isfahan customer must get X (local), not Y (cheaper but national)."""
        kettle, x_sup, x_loc, x_offer, y_sup, y_loc, y_offer = \
            self._setup_isfahan_suppliers(x_stock=5, y_stock=10)

        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)

        key = uuid.uuid4().hex
        resp = self.checkout(headers, key=key, address=ISFAHAN_ADDRESS)

        self.assertEqual(resp.status_code, 201,
                         f"Scenario 18 checkout must succeed: {resp.get_json()}")
        order_num = resp.get_json()["order"]["order_number"]

        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?", (order_num,)
            ).fetchone()
            order_id = int(order_row["id"])
            fo_rows = conn.execute(
                "SELECT supplier_id FROM fulfillment_orders WHERE order_id=?",
                (order_id,),
            ).fetchall()

        # Exactly one FO, and it must be for X (Isfahan supplier), not Y (Tehran)
        self.assertEqual(len(fo_rows), 1, "Exactly one FO must be created")
        self.assertEqual(int(fo_rows[0]["supplier_id"]), x_sup,
                         "FO must be assigned to Isfahan supplier X, not cheaper Tehran Y")

        # X's supplier stock must be reserved; Y's must be untouched
        self.assertGreaterEqual(self._offer_reserved(x_offer), 1,
                                "Isfahan supplier X must have stock reserved")
        self.assertEqual(self._offer_reserved(y_offer), 0,
                         "Tehran supplier Y must have zero stock reserved (LOCAL_ONLY)")

    def test_scenario_18_stock_reserved_before_psp(self):
        """The supplier stock must be reserved in the payment_intent BEFORE PSP capture."""
        kettle, x_sup, x_loc, x_offer, y_sup, y_loc, y_offer = \
            self._setup_isfahan_suppliers(x_stock=5, y_stock=10)

        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)
        resp = self.checkout(headers, address=ISFAHAN_ADDRESS)
        self.assertEqual(resp.status_code, 201, resp.get_json())

        # The payment_intent must have a fulfillment_plan_json stored
        with self.db.read_transaction() as conn:
            intent_row = conn.execute(
                "SELECT fulfillment_plan_json FROM payment_intents ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(intent_row["fulfillment_plan_json"],
                             "fulfillment_plan_json must be stored in payment_intent")

        import json
        plan = json.loads(intent_row["fulfillment_plan_json"])
        self.assertIn("items", plan)
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual(int(plan["items"][0]["supplier_id"]), x_sup,
                         "Plan must reference Isfahan supplier X")

    def test_scenario_18_idempotent_retry(self):
        """Scenario 18 retry with same key: returns same 201, no second FO."""
        kettle, x_sup, x_loc, x_offer, y_sup, y_loc, y_offer = \
            self._setup_isfahan_suppliers(x_stock=5, y_stock=10)

        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)
        key = uuid.uuid4().hex

        resp1 = self.checkout(headers, key=key, address=ISFAHAN_ADDRESS)
        self.assertEqual(resp1.status_code, 201, resp1.get_json())

        resp2 = self.checkout(headers, key=key, address=ISFAHAN_ADDRESS)
        self.assertEqual(resp2.status_code, 201, resp2.get_json())

        self.assertEqual(
            resp1.get_json()["order"]["order_number"],
            resp2.get_json()["order"]["order_number"],
            "Idempotent replay must return the same order",
        )

        # Only one FO
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?",
                (resp1.get_json()["order"]["order_number"],),
            ).fetchone()
            fo_count = conn.execute(
                "SELECT COUNT(*) FROM fulfillment_orders WHERE order_id=?",
                (int(order_row["id"]),),
            ).fetchone()[0]

        self.assertEqual(fo_count, 1, "Idempotent retry must not create a second FO")

    def test_scenario_19_x_out_of_stock_y_national_must_fail_before_psp(self):
        """Scenario 19: LOCAL_ONLY, X has no stock, Y (Tehran) blocked → 422 before PSP."""
        # X out of stock (stock=0); Y has plenty but is national (Tehran)
        kettle, x_sup, x_loc, x_offer, y_sup, y_loc, y_offer = \
            self._setup_isfahan_suppliers(x_stock=0, y_stock=10)

        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)

        resp = self.checkout(headers, address=ISFAHAN_ADDRESS)

        # Must fail with 422 fulfillment_unavailable — BEFORE PSP
        self.assertEqual(resp.status_code, 422,
                         f"Scenario 19 must return 422, got {resp.status_code}: {resp.get_json()}")
        self.assertEqual(resp.get_json()["error"]["code"], "fulfillment_unavailable",
                         "Error code must be fulfillment_unavailable (not payment_failed)")

        # Zero paid orders
        with self.db.read_transaction() as conn:
            paid_orders = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status='paid'"
            ).fetchone()[0]
        self.assertEqual(paid_orders, 0, "No paid order must exist after scenario 19 failure")

        # Zero FOs
        with self.db.read_transaction() as conn:
            fo_count = conn.execute("SELECT COUNT(*) FROM fulfillment_orders").fetchone()[0]
        self.assertEqual(fo_count, 0, "No FO must be created after scenario 19 failure")

        # No captured payment intent
        with self.db.read_transaction() as conn:
            captured = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]
        self.assertEqual(captured, 0, "PSP must not have been called (no captured intent)")

        # Neither supplier's stock was reserved
        self.assertEqual(self._offer_reserved(x_offer), 0,
                         "X stock_reserved must be 0 (no stock)")
        self.assertEqual(self._offer_reserved(y_offer), 0,
                         "Y stock_reserved must be 0 (LOCAL_ONLY blocks Tehran)")

    def test_scenario_19_ledger_balanced_after_failure(self):
        """Scenario 19: Ledger must remain balanced even after failed checkout."""
        self._setup_isfahan_suppliers(x_stock=0, y_stock=10)

        kettle = super().product(self.PRODUCT_SLUG)
        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)
        resp = self.checkout(headers, address=ISFAHAN_ADDRESS)
        self.assertEqual(resp.status_code, 422, resp.get_json())

        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits, "Ledger must remain balanced after scenario 19 failure")


# ─────────────────────────────────────────────────────────────────────────────
# Customer price integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestCustomerPriceIntegrity(_CheckoutBase):
    """The price charged to the customer must equal the order total; no float leakage."""

    def test_integer_minor_units_throughout(self):
        """All monetary values in the order must be integers with no floating-point leakage."""
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "office-paper-a4-carton")
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="PRICE-INT-001", display_name="صحت قیمت",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="office-paper-a4-carton", stock=10, price=14_567_890,
            )

        paper = super().product("office-paper-a4-carton")
        self.set_stock(paper["id"], 10)
        _, headers = self.new_customer()
        self.add_to_cart(headers, paper["id"], 2)

        resp = self.checkout(headers)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        order = resp.get_json()["order"]

        # These fields must exist and must be integers (no floats)
        for key in ("subtotal_minor", "total_minor", "shipping_fee_minor"):
            val = order.get(key)
            self.assertIsNotNone(val, f"Order field '{key}' must be present")
            self.assertIsInstance(
                val, int,
                f"Order field '{key}' must be an integer (no floats), got {type(val).__name__}={val!r}",
            )

        # Ledger balanced
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits, "Ledger balanced after multi-unit checkout")

    def test_supplier_price_does_not_influence_customer_price(self):
        """The customer pays the catalogue price, not the supplier cost."""
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")
            self._zero_offers(conn, "appliance-kettle-2l")
            # Supplier cost is irrelevant to customer price
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="PRICE-SEP-001", display_name="قیمت مجزا",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="appliance-kettle-2l", stock=10, price=9_000_000,
            )

        kettle = super().product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)
        catalogue_price = int(kettle["price_minor"])

        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)
        resp = self.checkout(headers)
        self.assertEqual(resp.status_code, 201, resp.get_json())

        order = resp.get_json()["order"]
        # Customer subtotal must reflect the catalogue price (what they saw in the product listing)
        self.assertEqual(int(order["subtotal_minor"]), catalogue_price,
                         "Customer subtotal must equal catalogue price, not supplier cost")


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL_PREFERRED and LOCAL_ONLY hard invariants
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutingPolicyInvariants(_CheckoutBase):
    """LOCAL_ONLY and LOCAL_PREFERRED tier rules must be hard invariants at checkout."""

    def test_local_only_never_routes_to_another_city(self):
        """LOCAL_ONLY product: a supplier in another city must never be used."""
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "LOCAL_ONLY")
            self._zero_offers(conn, "appliance-kettle-2l")
            # Only a Tehran supplier available; customer is in Mashhad
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="INV-LO-001", display_name="تهران‌تنها",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="appliance-kettle-2l", stock=10, price=12_000_000,
            )

        kettle = super().product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 10)
        _, headers = self.new_customer()
        self.add_to_cart(headers, kettle["id"], 1)

        mashhad_address = {**self.DEFAULT_ADDRESS, "province": "خراسان رضوی", "city": "مشهد"}
        resp = self.checkout(headers, address=mashhad_address)

        # Mashhad customer cannot be served by a Tehran LOCAL_ONLY supplier
        self.assertEqual(resp.status_code, 422, resp.get_json())
        self.assertEqual(resp.get_json()["error"]["code"], "fulfillment_unavailable",
                         "LOCAL_ONLY must not route to out-of-city supplier")

    def test_local_preferred_same_city_beats_national(self):
        """LOCAL_PREFERRED: if a same-city supplier exists, it must win over a national one."""
        from app.services import fulfillment_engine as engine

        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "LOCAL_PREFERRED")
            self._zero_offers(conn, "office-paper-a4-carton")
            # Tehran same-city supplier (higher price)
            teh_sup, teh_loc = self._get_or_create_supplier(
                conn, nat_id="LP-CITY-001", display_name="تهران همشهری",
                province="تهران", city="تهران", can_local=True, can_intercity=False,
                rating_x10=40,
            )
            teh_offer = self._add_offer(
                conn, supplier_id=teh_sup, location_id=teh_loc,
                product_slug="office-paper-a4-carton", stock=5, price=15_000_000,
            )
            # Shiraz national supplier (cheaper)
            shi_sup, shi_loc = self._get_or_create_supplier(
                conn, nat_id="LP-NAT-001", display_name="شیراز ملی",
                province="فارس", city="شیراز", can_local=True, can_intercity=True,
                rating_x10=45,
            )
            shi_offer = self._add_offer(
                conn, supplier_id=shi_sup, location_id=shi_loc,
                product_slug="office-paper-a4-carton", stock=5, price=12_000_000,
            )

        paper = super().product("office-paper-a4-carton")
        self.set_stock(paper["id"], 10)
        _, headers = self.new_customer()  # DEFAULT_ADDRESS is Tehran
        self.add_to_cart(headers, paper["id"], 1)
        resp = self.checkout(headers)  # customer is in Tehran

        self.assertEqual(resp.status_code, 201, resp.get_json())
        order_num = resp.get_json()["order"]["order_number"]

        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?", (order_num,)
            ).fetchone()
            fo = conn.execute(
                "SELECT supplier_id FROM fulfillment_orders WHERE order_id=?",
                (int(order_row["id"]),),
            ).fetchone()

        self.assertEqual(int(fo["supplier_id"]), teh_sup,
                         "LOCAL_PREFERRED must select same-city Tehran supplier over cheaper Shiraz")
        self.assertGreaterEqual(self._offer_reserved(teh_offer), 1,
                                "Tehran supplier stock must be reserved")
        self.assertEqual(self._offer_reserved(shi_offer), 0,
                         "Shiraz supplier stock must NOT be reserved")


# ─────────────────────────────────────────────────────────────────────────────
# Gap 1: Alice — Org + Split + LOCAL_ONLY + exact amounts (30M/20M/10M)
# ─────────────────────────────────────────────────────────────────────────────

class TestAliceOrgSplitLocalFulfillment(_CheckoutBase):
    """Gap 1 acceptance test.

    Alice is an employee of Org A (Isfahan delivery).
    Product policy: LOCAL_ONLY.
    Order total: exactly 30,000,000 minor  (≥ 20M threshold → shipping FREE).
    Org credit allocation: 20,000,000 minor.
    PSP charge: 10,000,000 minor  (10_000_000 % 100 == 0 → MockPSP will NOT decline).

    Supplier X is in Isfahan (same city as delivery) — eligible under LOCAL_ONLY.
    Supplier Y is in Tehran (cheaper than X, nationally-capable) — must be BLOCKED.

    Assertions (first checkout): 16
    Assertions (idempotency replay): 11
    Total: 27 assertions in one end-to-end test method.
    """

    PRODUCT_SLUG    = "appliance-kettle-2l"
    CATALOGUE_PRICE = 30_000_000   # subtotal=30M, shipping=0 (≥ free-shipping threshold)
    TAX_MINOR       = CATALOGUE_PRICE * 1000 // 10000  # 3,000,000 at STANDARD 10%
    TOTAL_MINOR     = CATALOGUE_PRICE + TAX_MINOR      # 33,000,000 (v6 VAT-inclusive)
    CREDIT_AMOUNT   = 20_000_000   # org credit allocated to Alice
    PSP_AMOUNT      = TOTAL_MINOR - CREDIT_AMOUNT      # 13M; 13_000_000 % 100 == 0 → MockPSP won't decline

    # Unique nat_ids avoid any cross-test collision (each test has its own DB, but be explicit)
    X_NAT_ID = "G1-ISF-X-2024"
    Y_NAT_ID = "G1-TEH-Y-2024"

    def setUp(self):
        super().setUp()
        with self.db.write_transaction() as conn:
            # Pin catalogue price BEFORE add-to-cart (snapshot happens at that moment)
            self._set_catalogue_price(conn, self.PRODUCT_SLUG, self.CATALOGUE_PRICE)
            # LOCAL_ONLY policy on the product
            self._set_policy(conn, self.PRODUCT_SLUG, "LOCAL_ONLY")
            # Zero all existing offers so no seed-data supplier can interfere
            self._zero_offers(conn, self.PRODUCT_SLUG)

            # Supplier X: Isfahan warehouse — eligible for LOCAL_ONLY to Isfahan customer
            x_sup, x_loc = self._get_or_create_supplier(
                conn, nat_id=self.X_NAT_ID, display_name="تأمین اصفهان X (Gap1)",
                province="اصفهان", city="اصفهان",
                can_local=True, can_intercity=False, rating_x10=40,
            )
            x_offer = self._add_offer(
                conn, supplier_id=x_sup, location_id=x_loc,
                product_slug=self.PRODUCT_SLUG, stock=5, price=28_000_000,
            )

            # Supplier Y: Tehran warehouse — cheaper than X but must be blocked by LOCAL_ONLY
            y_sup, y_loc = self._get_or_create_supplier(
                conn, nat_id=self.Y_NAT_ID, display_name="تأمین تهران Y (Gap1)",
                province="تهران", city="تهران",
                can_local=True, can_intercity=True, rating_x10=45,
            )
            y_offer = self._add_offer(
                conn, supplier_id=y_sup, location_id=y_loc,
                product_slug=self.PRODUCT_SLUG, stock=5, price=25_000_000,  # cheaper than X
            )

        self._x_sup   = x_sup
        self._x_offer = x_offer
        self._y_sup   = y_sup
        self._y_offer = y_offer

        # Make sure catalogue inventory permits purchasing
        kettle = self.product(self.PRODUCT_SLUG)
        self._kettle_id = kettle["id"]
        self.set_stock(self._kettle_id, 20)

    def test_alice_org_split_local_fulfillment_complete(self):
        """16 assertions (first checkout) + 11 assertions (idempotency replay).

        NO CUSTOMER SHOULD BE SUCCESSFULLY CHARGED FOR AN ORDER THAT 60ONLINE HAS
        NOT SUCCESSFULLY PLANNED AND RESERVED FOR FULFILLMENT.
        """
        import json as _json

        # ── Org + Alice setup ────────────────────────────────────────────────
        org, admin_headers, _, alice = self.org_fixture(credit_minor=self.CREDIT_AMOUNT)
        alice_h = alice["headers"]
        alice_alloc_id = alice["allocation"]["id"]

        # Price is already snapshotted into the catalogue (setUp); add to cart NOW
        self.add_to_cart(alice_h, self._kettle_id, 1)

        key = uuid.uuid4().hex

        # ── First checkout ───────────────────────────────────────────────────
        resp = self.checkout(alice_h, key=key, address=ISFAHAN_ADDRESS)

        # (1) HTTP 201
        self.assertEqual(resp.status_code, 201,
                         f"Alice org+split checkout must succeed: {resp.get_json()}")
        order = resp.get_json()["order"]

        # (2) Total is VAT-inclusive (subtotal 30M + VAT 3M = 33M)
        self.assertEqual(int(order["total_minor"]), self.TOTAL_MINOR,
                         f"Order total must be exactly {self.TOTAL_MINOR} minor (incl. VAT)")

        # (3) Credit consumed is exactly 20,000,000
        self.assertEqual(int(order.get("credit_minor", 0)), 20_000_000,
                         "Credit used must be exactly 20,000,000 minor")

        # (4) PSP cash portion = total - credit
        cash_minor = int(order["total_minor"]) - int(order.get("credit_minor", 0))
        self.assertEqual(cash_minor, self.PSP_AMOUNT,
                         f"PSP cash charge must be exactly {self.PSP_AMOUNT} minor")

        # (5) Order number is a non-empty string
        order_number = order.get("order_number", "")
        self.assertTrue(order_number, "order_number must be a non-empty string")

        # Read order_id for subsequent DB assertions
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id, status FROM orders WHERE order_number=?", (order_number,)
            ).fetchone()
        order_id = int(order_row["id"])

        # (6) Order status is 'paid' in the database
        self.assertEqual(order_row["status"], "paid",
                         "Order status must be 'paid' in the database")

        # (7) Exactly one FO was created for this order
        with self.db.read_transaction() as conn:
            all_fos = conn.execute(
                "SELECT id, supplier_id, status FROM fulfillment_orders WHERE order_id=?",
                (order_id,),
            ).fetchall()
        self.assertEqual(len(all_fos), 1,
                         f"Exactly 1 FO must be created, got {len(all_fos)}")

        fo = all_fos[0]
        fo_id = int(fo["id"])

        # (8) FO is assigned to Isfahan Supplier X — not cheaper Tehran Supplier Y
        self.assertEqual(int(fo["supplier_id"]), self._x_sup,
                         f"FO must be assigned to Isfahan Supplier X (id={self._x_sup}), "
                         f"got supplier_id={fo['supplier_id']}")

        # (9) FO status is 'assigned'
        self.assertEqual(fo["status"], "assigned",
                         "Newly created FO must be in 'assigned' status")

        # (10) Supplier X stock is reserved (1 unit)
        self.assertEqual(self._offer_reserved(self._x_offer), 1,
                         "Isfahan Supplier X must have exactly 1 unit reserved")

        # (11) Supplier Y stock is untouched — LOCAL_ONLY blocked the cheaper Tehran supplier
        self.assertEqual(self._offer_reserved(self._y_offer), 0,
                         "Tehran Supplier Y stock_reserved must be 0 (LOCAL_ONLY blocks intercity)")

        # (12) fulfillment_plan_json stored in the payment_intent (stock reserved BEFORE PSP)
        with self.db.read_transaction() as conn:
            intent_row = conn.execute(
                "SELECT fulfillment_plan_json, status FROM payment_intents "
                "WHERE order_id=? ORDER BY id DESC LIMIT 1",
                (order_id,),
            ).fetchone()
        self.assertIsNotNone(intent_row["fulfillment_plan_json"],
                             "fulfillment_plan_json must be stored in payment_intent")

        # (13) Plan references Isfahan Supplier X specifically
        plan = _json.loads(intent_row["fulfillment_plan_json"])
        self.assertEqual(len(plan.get("items", [])), 1, "Plan must have exactly 1 item")
        self.assertEqual(int(plan["items"][0]["supplier_id"]), self._x_sup,
                         "fulfillment_plan_json must reference Isfahan Supplier X")

        # (14) Ledger is balanced after the checkout
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits,
                         f"Ledger must be balanced after checkout (debits={debits}, credits={credits})")

        # (15) No FO was created for Supplier Y
        with self.db.read_transaction() as conn:
            y_fo_count = conn.execute(
                "SELECT COUNT(*) FROM fulfillment_orders WHERE order_id=? AND supplier_id=?",
                (order_id, self._y_sup),
            ).fetchone()[0]
        self.assertEqual(y_fo_count, 0,
                         "No FO must exist for Tehran Supplier Y (blocked by LOCAL_ONLY)")

        # (16) Exactly 1 captured payment intent (PSP charged once)
        with self.db.read_transaction() as conn:
            captured_count = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE order_id=? AND status='captured'",
                (order_id,),
            ).fetchone()[0]
        self.assertEqual(captured_count, 1,
                         "Exactly 1 captured payment intent must exist after checkout")

        # ── Idempotency replay (same key, same address) ──────────────────────
        resp2 = self.checkout(alice_h, key=key, address=ISFAHAN_ADDRESS)

        # (I-1) Status 201 on replay
        self.assertEqual(resp2.status_code, 201,
                         f"Idempotent replay must return 201: {resp2.get_json()}")
        order2 = resp2.get_json()["order"]

        # (I-2) Same order number — no duplicate order
        self.assertEqual(order2["order_number"], order_number,
                         "Idempotent replay must return the same order_number")

        # (I-3) Total unchanged on replay
        self.assertEqual(int(order2["total_minor"]), self.TOTAL_MINOR,
                         f"Replayed order total must still be {self.TOTAL_MINOR}")

        # (I-4) Credit field unchanged on replay
        self.assertEqual(int(order2.get("credit_minor", 0)), 20_000_000,
                         "Replayed order credit_minor must still be 20,000,000")

        # (I-5) Cash portion unchanged on replay
        cash2 = int(order2["total_minor"]) - int(order2.get("credit_minor", 0))
        self.assertEqual(cash2, self.PSP_AMOUNT,
                         f"Replayed PSP cash portion must still be {self.PSP_AMOUNT}")

        # (I-6) Still exactly 1 FO — replay must not create a second FO
        with self.db.read_transaction() as conn:
            fo_count_after = conn.execute(
                "SELECT COUNT(*) FROM fulfillment_orders WHERE order_id=?", (order_id,)
            ).fetchone()[0]
        self.assertEqual(fo_count_after, 1,
                         "Idempotent replay must not create a second FO")

        # (I-7) FO supplier still Supplier X
        with self.db.read_transaction() as conn:
            fo2 = conn.execute(
                "SELECT supplier_id, status FROM fulfillment_orders WHERE order_id=?",
                (order_id,),
            ).fetchone()
        self.assertEqual(int(fo2["supplier_id"]), self._x_sup,
                         "Replayed FO must still be assigned to Isfahan Supplier X")

        # (I-8) FO status still 'assigned' after replay
        self.assertEqual(fo2["status"], "assigned",
                         "FO status must still be 'assigned' after idempotent replay")

        # (I-9) Supplier X stock_reserved is still 1 — replay must not double-reserve
        self.assertEqual(self._offer_reserved(self._x_offer), 1,
                         "Supplier X stock_reserved must remain exactly 1 after idempotent replay")

        # (I-10) PSP captured count unchanged — no second charge
        with self.db.read_transaction() as conn:
            captured_after = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE order_id=? AND status='captured'",
                (order_id,),
            ).fetchone()[0]
        self.assertEqual(captured_after, 1,
                         "PSP captured count must not increase after idempotent replay")

        # (I-11) Ledger remains balanced after replay
        debits2, credits2 = self.trial_balance()
        self.assertEqual(debits2, credits2,
                         f"Ledger must remain balanced after idempotent replay "
                         f"(debits={debits2}, credits={credits2})")
