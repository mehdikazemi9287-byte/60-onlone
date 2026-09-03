"""Unit tests for the Smart Fulfillment Engine (domain service, no HTTP).

Tests cover all 12 routing scenarios required by the spec + edge cases.
"""
from __future__ import annotations

import unittest

from tests.base import AppTestCase
from app.services import fulfillment_engine as engine


class _EngineBase(AppTestCase):
    """Bootstrap helpers for engine tests."""

    def _policy_id(self, conn, name: str) -> int:
        row = conn.execute(
            "SELECT id FROM fulfillment_policies WHERE name = ?", (name,)
        ).fetchone()
        self.assertIsNotNone(row, f"policy '{name}' not found")
        return int(row["id"])

    def _product_id(self, conn, slug: str) -> int:
        row = conn.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
        self.assertIsNotNone(row, f"product '{slug}' not found")
        return int(row["id"])

    def _set_policy(self, conn, slug: str, policy_name: str) -> None:
        pid  = self._product_id(conn, slug)
        fpid = self._policy_id(conn, policy_name)
        conn.execute(
            "UPDATE products SET fulfillment_policy_id = ? WHERE id = ?", (fpid, pid)
        )

    def _get_or_create_supplier(
        self, conn, *,
        nat_id: str, display_name: str,
        province: str, city: str,
        status: str = "active",
        rating_x10: int = 40,
        can_local: bool = True,
        can_intercity: bool = False,
        can_pickup: bool = False,
    ) -> tuple[int, int]:
        """Returns (supplier_id, location_id). Idempotent."""
        existing = conn.execute(
            "SELECT id FROM suppliers WHERE national_id = ?", (nat_id,)
        ).fetchone()
        if existing:
            sup_id = int(existing["id"])
        else:
            cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10) "
                "VALUES (?,?,?,?,?)",
                (display_name, display_name, nat_id, status, rating_x10),
            )
            sup_id = int(cur.lastrowid)

        loc = conn.execute(
            "SELECT id FROM supplier_locations WHERE supplier_id = ? AND city = ?",
            (sup_id, city),
        ).fetchone()
        if loc:
            loc_id = int(loc["id"])
        else:
            cur = conn.execute(
                "INSERT INTO supplier_locations "
                "(supplier_id, province, city, status, can_local_delivery, "
                "can_intercity_shipping, can_pickup, prep_time_minutes) "
                "VALUES (?,?,?, 'active', ?,?,?, 60)",
                (sup_id, province, city, int(can_local), int(can_intercity), int(can_pickup)),
            )
            loc_id = int(cur.lastrowid)

        return sup_id, loc_id

    def _add_offer(
        self, conn, *, supplier_id: int, location_id: int, product_slug: str,
        price: int = 100_000_000, stock: int = 10,
        fulfillment_type: str = "delivery",
    ) -> int:
        prod_id = self._product_id(conn, product_slug)
        existing = conn.execute(
            "SELECT id FROM seller_offers WHERE product_id=? AND supplier_id=? AND supplier_location_id=?",
            (prod_id, supplier_id, location_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE seller_offers SET stock_quantity=?, selling_price_minor=?, status='active' WHERE id=?",
                (stock, price, int(existing["id"])),
            )
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,?,?,'active',?)",
            (prod_id, supplier_id, location_id, price, stock, fulfillment_type),
        )
        return int(cur.lastrowid)


class TestRoutingScenarios(_EngineBase):
    """Scenarios A–L from the spec."""

    # ----- Scenario A: Tehran customer + LOCAL_PREFERRED mobile → Tehran supplier ------
    def test_scenario_a_local_preferred_selects_local_supplier(self):
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="T-A-001", display_name="تهران موبایل",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="mobile-samsung-a55", stock=5)
            self._set_policy(conn, "mobile-samsung-a55", "LOCAL_PREFERRED")

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "mobile-samsung-a55"),
                quantity_needed=1, customer_province="تهران", customer_city="تهران",
            )

        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.location_city, "تهران")
        self.assertEqual(result.selected.geo_tier, "same_city")

    # ----- Scenario B: Isfahan customer + LOCAL_PREFERRED mobile → Isfahan supplier ----
    def test_scenario_b_isfahan_customer_gets_isfahan_supplier(self):
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="I-B-001", display_name="اصفهان موبایل",
                province="اصفهان", city="اصفهان", can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="mobile-xiaomi-redmi-note-13", stock=5)
            self._set_policy(conn, "mobile-xiaomi-redmi-note-13", "LOCAL_PREFERRED")

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "mobile-xiaomi-redmi-note-13"),
                quantity_needed=1, customer_province="اصفهان", customer_city="اصفهان",
            )

        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.location_city, "اصفهان")

    # ----- Scenario C: LOCAL_ONLY + no local stock → unavailable (NOT national) -------
    def test_scenario_c_local_only_no_stock_is_unavailable(self):
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-water-dispenser", "LOCAL_ONLY")
            # Add a Tehran supplier WITH stock to prove LOCAL_ONLY never falls back to national
            teh_id, teh_loc = self._get_or_create_supplier(
                conn, nat_id="C-TEH-001", display_name="تهران آب (C)",
                province="تهران", city="تهران",
                can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=teh_id, location_id=teh_loc,
                           product_slug="appliance-water-dispenser", stock=10)
            # Ensure Isfahan has NO stock (zero out any existing Isfahan offer)
            conn.execute(
                """
                UPDATE seller_offers SET stock_quantity = 0
                WHERE product_id = (SELECT id FROM products WHERE slug = 'appliance-water-dispenser')
                  AND supplier_location_id IN (
                    SELECT id FROM supplier_locations WHERE city = 'اصفهان'
                  )
                """
            )

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn,
                product_id=self._product_id(conn, "appliance-water-dispenser"),
                quantity_needed=1,
                customer_province="اصفهان",
                customer_city="اصفهان",
            )

        # LOCAL_ONLY hard invariant: Tehran supplier must NEVER be selected for Isfahan customer
        self.assertIsNone(
            result.selected,
            "LOCAL_ONLY must not route to Tehran when Isfahan has no stock — "
            f"got: {result.selected.supplier_name if result.selected else None}",
        )
        # No out-of-city candidate must be eligible
        for c in result.candidates:
            if not engine.same_city(c.location_city, "اصفهان"):
                self.assertFalse(
                    c.eligible,
                    f"LOCAL_ONLY: out-of-city supplier ({c.location_city}) must never be eligible",
                )
        # unavailable_reason must be set
        self.assertTrue(
            bool(result.unavailable_reason),
            "unavailable_reason must explain why routing failed",
        )

    # ----- Scenario D: Kermanshah mobile (LOCAL_PREFERRED) → Kermanshah supplier ------
    def test_scenario_d_kermanshah_local_preferred(self):
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="K-D-001", display_name="کرمانشاه موبایل",
                province="کرمانشاه", city="کرمانشاه", can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="tablet-samsung-tab-a9", stock=3)
            self._set_policy(conn, "tablet-samsung-tab-a9", "LOCAL_PREFERRED")

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "tablet-samsung-tab-a9"),
                quantity_needed=1, customer_province="کرمانشاه", customer_city="کرمانشاه",
            )

        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.location_city, "کرمانشاه")

    # ----- Scenario E: Kermanshah local out of stock → national fallback ---------------
    def test_scenario_e_kermanshah_out_of_stock_falls_back_to_national(self):
        with self.db.write_transaction() as conn:
            # Set Kermanshah mobile stock to 0
            conn.execute(
                """
                UPDATE seller_offers SET stock_quantity = 0
                WHERE supplier_location_id IN (
                    SELECT id FROM supplier_locations WHERE city = 'کرمانشاه'
                )
                AND product_id = (SELECT id FROM products WHERE slug = 'mobile-samsung-a55')
                """
            )
            self._set_policy(conn, "mobile-samsung-a55", "LOCAL_PREFERRED")
            # Add a national (Tehran) supplier with intercity capability
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="T-E-001", display_name="تهران ملی موبایل",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="mobile-samsung-a55", stock=20, price=205_000_000)

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "mobile-samsung-a55"),
                quantity_needed=1, customer_province="کرمانشاه", customer_city="کرمانشاه",
            )

        self.assertIsNotNone(result.selected, "Should fall back to national supplier")

    # ----- Scenario F: National stationery → best candidate by score ------------------
    def test_scenario_f_national_stationery_best_candidate(self):
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "office-paper-a4-carton"),
                quantity_needed=1, customer_province="خراسان", customer_city="مشهد",
            )

        self.assertIsNotNone(result.selected, "NATIONAL_SHIPPING should find a candidate")
        # Supplier must allow intercity shipping
        self.assertTrue(
            result.selected.can_intercity_shipping or
            result.selected.geo_tier == "same_city",
            "Selected supplier must be able to ship to Mashhad"
        )

    # ----- Scenario G: Suspended supplier is never selected ---------------------------
    def test_scenario_g_suspended_supplier_never_selected(self):
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            # Make suspended supplier cheapest
            conn.execute(
                """
                UPDATE seller_offers SET selling_price_minor = 1
                WHERE supplier_id IN (
                    SELECT id FROM suppliers WHERE status = 'suspended'
                )
                """
            )

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "office-paper-a4-carton"),
                quantity_needed=1, customer_province="تهران", customer_city="تهران",
            )

        for c in result.candidates:
            if c.eligible:
                self.assertNotEqual(c.supplier_status, "suspended",
                                    "Suspended supplier must never be eligible")

    # ----- Scenario H: Best supplier rejects → next valid selected --------------------
    def test_scenario_h_rejection_fallback(self):
        """Deterministic fallback test.

        Supplier A wins routing (highest rating, lower price).
        After Supplier A rejects:
          - original FO status == 'rejected'
          - Supplier A reservation released (stock_reserved == 0)
          - a NEW fulfillment order created (exactly 2 FOs total)
          - new FO supplier_id == Supplier B
          - new FO status == 'assigned'
          - Supplier B stock reserved (stock_reserved >= 1)
          - routing_audit has a 'fallback' event for new FO
          - customer order_number unchanged
          - customer order total unchanged
          - exactly 1 captured payment intent (no second charge)
          - financial ledger unchanged (no second entry)
        """
        # Step 0: Set up two deterministic suppliers so routing is predictable.
        # Supplier A: rating_x10=50 (highest possible), lower price → will win routing.
        # Supplier B: rating_x10=20, higher price → will be fallback.
        # Both are in Tehran; customer is in Tehran (DEFAULT_ADDRESS).
        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            # Zero ALL existing offers so seeded data cannot interfere
            conn.execute(
                "UPDATE seller_offers SET stock_quantity=0, stock_reserved=0 "
                "WHERE product_id=(SELECT id FROM products WHERE slug='office-paper-a4-carton')"
            )

            # Supplier A — high rating, will WIN routing
            sup_a_id, loc_a_id = self._get_or_create_supplier(
                conn, nat_id="H-SUPA-DET", display_name="تأمین الف (اول)",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
                rating_x10=50,
            )
            offer_a_id = self._add_offer(
                conn, supplier_id=sup_a_id, location_id=loc_a_id,
                product_slug="office-paper-a4-carton", stock=5, price=14_000_000,
            )

            # Supplier B — low rating, higher price — fallback candidate
            sup_b_id, loc_b_id = self._get_or_create_supplier(
                conn, nat_id="H-SUPB-DET", display_name="تأمین ب (دوم)",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
                rating_x10=20,
            )
            offer_b_id = self._add_offer(
                conn, supplier_id=sup_b_id, location_id=loc_b_id,
                product_slug="office-paper-a4-carton", stock=5, price=16_000_000,
            )

        # Product inventory: enough for both to pass inventory gate
        paper = self.product("office-paper-a4-carton")
        self.set_stock(paper["id"], 10)

        # Step 1: Customer checks out → Supplier A must win routing
        token, headers = self.new_customer()
        self.add_to_cart(headers, paper["id"], 1)
        resp = self.checkout(headers)
        self.assertEqual(resp.status_code, 201, f"Scenario H checkout failed: {resp.get_json()}")

        order_json = resp.get_json()["order"]
        order_number  = order_json["order_number"]
        order_total   = int(order_json["total_minor"])

        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?", (order_number,)
            ).fetchone()
            order_id = int(order_row["id"])

            # Exactly one FO for this order; must belong to Supplier A
            fos_initial = conn.execute(
                "SELECT id, supplier_id, status FROM fulfillment_orders WHERE order_id=?",
                (order_id,),
            ).fetchall()

        self.assertEqual(len(fos_initial), 1, "Exactly one FO must exist after checkout")
        fo_a = fos_initial[0]
        fo_a_id       = int(fo_a["id"])
        fo_a_supplier = int(fo_a["supplier_id"])

        self.assertEqual(fo_a_supplier, sup_a_id,
                         f"Routing must select Supplier A (id={sup_a_id}), "
                         f"got supplier_id={fo_a_supplier}")
        self.assertEqual(fo_a["status"], "assigned",
                         "Initial FO must be in 'assigned' status")

        # Supplier A reservation: must be 1
        with self.db.read_transaction() as conn:
            res_a_before = conn.execute(
                "SELECT stock_reserved FROM seller_offers WHERE id=?", (offer_a_id,)
            ).fetchone()["stock_reserved"]
        self.assertEqual(int(res_a_before), 1,
                         "Supplier A must have 1 unit reserved after checkout")

        # Count captured payment intents and ledger entries before rejection
        with self.db.read_transaction() as conn:
            intents_before = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]
            ledger_entries_before = conn.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]

        # Step 2: Register a fresh portal user; wire them to Supplier A's record
        sup_a_email, sup_a_pw, reg_resp = self.register()
        self.assertEqual(reg_resp.status_code, 201, reg_resp.get_json())
        sup_a_user_id = int(
            reg_resp.get_json().get("user", {}).get("id") or
            self.db.query_one("SELECT id FROM users WHERE email_normalized=?", (sup_a_email.lower(),))["id"]
        )

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='supplier' WHERE id=?", (sup_a_user_id,))
            conn.execute("UPDATE suppliers SET user_id=NULL WHERE user_id=?", (sup_a_user_id,))
            conn.execute("UPDATE suppliers SET user_id=? WHERE id=?", (sup_a_user_id, sup_a_id))

        # Re-login to pick up role=supplier in the JWT
        sup_a_token = self.login(sup_a_email, sup_a_pw)
        sup_a_headers = {"Authorization": f"Bearer {sup_a_token}"}

        # Step 3: Supplier A rejects the FO
        reject_resp = self.client.post(
            f"/api/v1/supplier/orders/{fo_a_id}/reject",
            json={"reason": "موجودی واقعی نداریم"},
            headers=sup_a_headers,
        )
        self.assertIn(reject_resp.status_code, (200, 204),
                      f"Reject endpoint must succeed: {reject_resp.get_json()}")

        # Step 4: Assert every required postcondition
        with self.db.read_transaction() as conn:
            all_fos = conn.execute(
                "SELECT id, supplier_id, status FROM fulfillment_orders WHERE order_id=? ORDER BY id",
                (order_id,),
            ).fetchall()

        # (a) Exactly two FOs: the original (rejected) and the fallback (assigned)
        self.assertEqual(len(all_fos), 2,
                         f"Exactly 2 FOs must exist after rejection+fallback, got {len(all_fos)}")

        rejected_fos = [f for f in all_fos if f["status"] == "rejected"]
        assigned_fos = [f for f in all_fos if f["status"] == "assigned"]

        # (b) Original FO is rejected
        self.assertEqual(len(rejected_fos), 1, "Exactly 1 FO must be in 'rejected' status")
        self.assertEqual(int(rejected_fos[0]["id"]), fo_a_id,
                         "The rejected FO must be the original Supplier-A FO")

        # (c) Supplier A reservation released
        with self.db.read_transaction() as conn:
            res_a_after = int(conn.execute(
                "SELECT stock_reserved FROM seller_offers WHERE id=?", (offer_a_id,)
            ).fetchone()["stock_reserved"])
        self.assertEqual(res_a_after, 0,
                         "Supplier A stock_reserved must be 0 after rejection compensation")

        # (d) New FO exists and is assigned to Supplier B
        self.assertEqual(len(assigned_fos), 1, "Exactly 1 new FO must be in 'assigned' status")
        fo_b_id       = int(assigned_fos[0]["id"])
        fo_b_supplier = int(assigned_fos[0]["supplier_id"])
        self.assertEqual(fo_b_supplier, sup_b_id,
                         f"New FO must be assigned to Supplier B (id={sup_b_id}), "
                         f"got supplier_id={fo_b_supplier}")

        # (e) Supplier B stock reserved (exactly 1 unit)
        with self.db.read_transaction() as conn:
            res_b_after = int(conn.execute(
                "SELECT stock_reserved FROM seller_offers WHERE id=?", (offer_b_id,)
            ).fetchone()["stock_reserved"])
        self.assertEqual(res_b_after, 1,
                         "Supplier B must have exactly 1 unit reserved after fallback routing")

        # (f) Routing audit contains a 'fallback' event for the new FO
        with self.db.read_transaction() as conn:
            fallback_audit = conn.execute(
                "SELECT id FROM routing_audit WHERE fulfillment_order_id=? AND event_type='fallback'",
                (fo_b_id,),
            ).fetchone()
        self.assertIsNotNone(fallback_audit,
                             "routing_audit must have a 'fallback' event for the new Supplier-B FO")

        # (g) Customer order_number did not change
        with self.db.read_transaction() as conn:
            order_after = conn.execute(
                "SELECT order_number, total_minor FROM orders WHERE id=?", (order_id,)
            ).fetchone()
        self.assertEqual(order_after["order_number"], order_number,
                         "Customer order_number must not change after fallback")
        self.assertEqual(int(order_after["total_minor"]), order_total,
                         "Customer order total must not change after fallback")

        # (h) Exactly 1 captured payment intent (no second PSP charge)
        with self.db.read_transaction() as conn:
            intents_after = conn.execute(
                "SELECT COUNT(*) FROM payment_intents WHERE status='captured'"
            ).fetchone()[0]
        self.assertEqual(intents_after, intents_before,
                         "PSP captured payment count must not increase after supplier rejection")

        # (i) Financial ledger was not duplicated (no extra entries created)
        with self.db.read_transaction() as conn:
            ledger_entries_after = conn.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
        self.assertEqual(ledger_entries_after, ledger_entries_before,
                         "Financial ledger must not gain new entries after supplier rejection")

    # ----- Scenario I: Two customers compete for last unit → exactly one succeeds -----
    def test_scenario_i_concurrent_last_unit(self):
        import threading
        import uuid

        with self.db.write_transaction() as conn:
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="I-CONC-001", display_name="رقابت",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            # Zero out all existing offers so the race is purely on this 1-unit offer
            conn.execute(
                "UPDATE seller_offers SET stock_quantity=0, stock_reserved=0 "
                "WHERE product_id=(SELECT id FROM products WHERE slug='office-paper-a4-carton')"
            )
            # One unit for two competing customers
            offer_id = self._add_offer(
                conn, supplier_id=sup_id, location_id=loc_id,
                product_slug="office-paper-a4-carton", stock=1,
            )

        # Product inventory: enough for both customers to pass the inventory gate;
        # the race is settled exclusively at the supplier-stock-reservation level.
        paper_product = self.product("office-paper-a4-carton")
        self.set_stock(paper_product["id"], 10)

        # Two customers, both with paper in cart
        tokens_and_headers = []
        for _ in range(2):
            t, h = self.new_customer()
            resp = self.add_to_cart(h, paper_product["id"], 1)
            tokens_and_headers.append((t, h))

        results = []
        keys = [uuid.uuid4().hex, uuid.uuid4().hex]

        def do_checkout(headers, key):
            resp = self.checkout(headers, key=key)
            results.append(resp.status_code)

        threads = [
            threading.Thread(target=do_checkout, args=(h, k))
            for (_, h), k in zip(tokens_and_headers, keys)
        ]
        for thr in threads:
            thr.start()
        for thr in threads:
            thr.join()

        successes = results.count(201)
        # Exactly one customer must win the race for the single available unit
        self.assertEqual(
            successes, 1,
            f"Exactly one checkout must succeed for the last unit — got {successes}/2 (results: {results})",
        )
        # Supplier stock must not be over-reserved
        with self.db.read_transaction() as conn:
            offer_row = conn.execute(
                "SELECT stock_quantity, stock_reserved FROM seller_offers WHERE id = ?",
                (offer_id,),
            ).fetchone()
        self.assertLessEqual(
            int(offer_row["stock_reserved"]),
            int(offer_row["stock_quantity"]),
            f"Supplier stock over-reserved: reserved={offer_row['stock_reserved']}, "
            f"quantity={offer_row['stock_quantity']}",
        )

    # ----- Scenario J: Mixed cart → multiple fulfillment orders ----------------------
    def test_scenario_j_mixed_cart_multiple_fulfillment_orders(self):
        with self.db.write_transaction() as conn:
            # Ensure LOCAL_PREFERRED for mobiles, NATIONAL for office
            self._set_policy(conn, "mobile-samsung-a55",      "LOCAL_PREFERRED")
            self._set_policy(conn, "office-paper-a4-carton",  "NATIONAL_SHIPPING")

            # Tehran local mobile supplier
            mob_sup, mob_loc = self._get_or_create_supplier(
                conn, nat_id="J-MOB-001", display_name="موبایل تهران J",
                province="تهران", city="تهران", can_local=True, can_intercity=True, rating_x10=45,
            )
            self._add_offer(conn, supplier_id=mob_sup, location_id=mob_loc,
                           product_slug="mobile-samsung-a55", stock=5, price=202_000_000)

            # Different national paper supplier
            ppr_sup, ppr_loc = self._get_or_create_supplier(
                conn, nat_id="J-PPR-001", display_name="کاغذ تهران J",
                province="تهران", city="تهران", can_local=True, can_intercity=True, rating_x10=42,
            )
            self._add_offer(conn, supplier_id=ppr_sup, location_id=ppr_loc,
                           product_slug="office-paper-a4-carton", stock=20, price=15_000_000)

        token, headers = self.new_customer()
        mobile = self.product("mobile-samsung-a55")
        paper  = self.product("office-paper-a4-carton")
        self.add_to_cart(headers, mobile["id"], 1)
        self.add_to_cart(headers, paper["id"],  1)

        resp = self.checkout(headers)
        self.assertEqual(resp.status_code, 201, f"Scenario J checkout failed: {resp.get_json()}")

        order_number = resp.get_json()["order"]["order_number"]
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number = ?", (order_number,)
            ).fetchone()
            fos = conn.execute(
                "SELECT id, supplier_id FROM fulfillment_orders WHERE order_id = ?",
                (int(order_row["id"]),),
            ).fetchall()
            foi = conn.execute(
                "SELECT product_id FROM fulfillment_order_items WHERE fulfillment_order_id IN "
                f"({','.join('?' * len(fos))})",
                [f["id"] for f in fos],
            ).fetchall()

        covered_products = {int(r["product_id"]) for r in foi}
        self.assertIn(mobile["id"], covered_products, "Mobile must be in fulfillment")
        self.assertIn(paper["id"],  covered_products, "Paper must be in fulfillment")

    # ----- Scenario K: Phase 2 employee credit + local fulfillment -------------------
    def test_scenario_k_org_credit_with_local_fulfillment(self):
        """Employee Alice orders with org credit. Payment and fulfillment are independent."""
        org, admin_headers, admin, employee = self.org_fixture(credit_minor=200_000_000)
        emp_headers = employee["headers"]

        with self.db.write_transaction() as conn:
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="K-LOC-001", display_name="کتری محلی",
                province="تهران", city="تهران", can_local=True, can_intercity=True, rating_x10=40,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="appliance-kettle-2l", stock=5, price=12_000_000)

        kettle = self.product("appliance-kettle-2l")
        self.set_stock(kettle["id"], 20)
        self.add_to_cart(emp_headers, kettle["id"], 1)
        resp = self.checkout(emp_headers)
        self.assertEqual(resp.status_code, 201, resp.get_json())

        order_data = resp.get_json()["order"]
        order_number = order_data["order_number"]

        # Verify financial split is correct
        self.assertGreater(order_data.get("credit_minor", 0), 0, "Credit should be used")

        # Verify fulfillment order was created
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number = ?", (order_number,)
            ).fetchone()
            fo_count = conn.execute(
                "SELECT COUNT(*) AS n FROM fulfillment_orders WHERE order_id = ?",
                (int(order_row["id"]),),
            ).fetchone()["n"]

        # Financial and fulfillment are separate: both must be present
        self.assertGreaterEqual(fo_count, 1, "Fulfillment order must be created for credit purchase")

        # Financial ledger must still be balanced
        debits, credits = self.trial_balance()
        self.assertEqual(debits, credits, "Ledger must be balanced after credit purchase")

    # ----- Scenario L: Supplier A cannot read Supplier B's orders --------------------
    def test_scenario_l_supplier_isolation(self):
        """Supplier A must get 404 when trying to read Supplier B's fulfillment order."""
        # Register with known passwords so we can re-login after role assignment in DB
        emailA, pwA, regA = self.register()
        self.assertEqual(regA.status_code, 201, regA.get_json())
        emailB, pwB, regB = self.register()
        self.assertEqual(regB.status_code, 201, regB.get_json())

        with self.db.write_transaction() as conn:
            # Look up user IDs by email (deterministic, not fragile ORDER BY tricks)
            uA = conn.execute(
                "SELECT id FROM users WHERE email_normalized = ?", (emailA.lower(),)
            ).fetchone()
            uB = conn.execute(
                "SELECT id FROM users WHERE email_normalized = ?", (emailB.lower(),)
            ).fetchone()

            conn.execute("UPDATE users SET role='supplier' WHERE id=?", (uA["id"],))
            conn.execute("UPDATE users SET role='supplier' WHERE id=?", (uB["id"],))

            supA_cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10, user_id) "
                "VALUES (?,?,?,?,?,?)",
                ("تأمین A", "تأمین A", "L-ISOL-A01", "active", 40, int(uA["id"])),
            )
            supA_id = int(supA_cur.lastrowid)  # noqa: F841 — needed to prove A != B

            locA_cur = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping) VALUES (?,?,?,'active',1,1)",
                (supA_id, "تهران", "تهران"),
            )
            locA_id = int(locA_cur.lastrowid)  # noqa: F841

            supB_cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10, user_id) "
                "VALUES (?,?,?,?,?,?)",
                ("تأمین B", "تأمین B", "L-ISOL-B01", "active", 40, int(uB["id"])),
            )
            supB_id = int(supB_cur.lastrowid)
            locB_cur = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, "
                "can_local_delivery, can_intercity_shipping) VALUES (?,?,?,'active',1,1)",
                (supB_id, "تهران", "تهران"),
            )
            locB_id = int(locB_cur.lastrowid)

        # Create a real order + FO for supplier B via checkout
        _, cust_h = self.new_customer()
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 10)
        self.add_to_cart(cust_h, product["id"], 1)

        # Add offer for supplier B; zero out others so routing always picks B
        with self.db.write_transaction() as conn:
            prod_id = int(conn.execute(
                "SELECT id FROM products WHERE slug = 'office-paper-a4-carton'"
            ).fetchone()["id"])
            conn.execute(
                "UPDATE seller_offers SET stock_quantity=0, stock_reserved=0 WHERE product_id=?",
                (prod_id,),
            )
            conn.execute(
                "INSERT INTO seller_offers "
                "(product_id, supplier_id, supplier_location_id, selling_price_minor, "
                "stock_quantity, status, fulfillment_type) VALUES (?,?,?,?,?,'active','delivery')",
                (prod_id, supB_id, locB_id, 14_000_000, 10),
            )
            conn.execute(
                "UPDATE products SET fulfillment_policy_id = "
                "(SELECT id FROM fulfillment_policies WHERE name='NATIONAL_SHIPPING') "
                "WHERE slug = 'office-paper-a4-carton'"
            )

        resp = self.checkout(cust_h)
        self.assertEqual(resp.status_code, 201,
                         f"Scenario L checkout failed: {resp.get_json()}")

        order_num = resp.get_json()["order"]["order_number"]
        with self.db.read_transaction() as conn:
            order_id = int(conn.execute(
                "SELECT id FROM orders WHERE order_number=?", (order_num,)
            ).fetchone()["id"])
            fo_row = conn.execute(
                "SELECT id FROM fulfillment_orders WHERE order_id=?", (order_id,)
            ).fetchone()

        self.assertIsNotNone(fo_row, "Fulfillment order must be created for isolation test")
        fo_id = int(fo_row["id"])

        # Ensure the FO is explicitly owned by supplier B
        with self.db.write_transaction() as conn:
            conn.execute(
                "UPDATE fulfillment_orders SET supplier_id=?, supplier_location_id=? WHERE id=?",
                (supB_id, locB_id, fo_id),
            )

        # Supplier A re-logins to obtain a token with role=supplier
        tokenA = self.client.post(
            "/api/v1/auth/login",
            json={"email": emailA, "password": pwA},
        )
        self.assertEqual(tokenA.status_code, 200,
                         f"Supplier A login must succeed: {tokenA.get_json()}")
        headersA = {"Authorization": f"Bearer {tokenA.get_json()['access_token']}"}

        resp_deny = self.client.get(f"/api/v1/supplier/orders/{fo_id}", headers=headersA)
        # Must be 404 (not 200 and not 403 — 404 is the secure choice)
        self.assertEqual(resp_deny.status_code, 404,
                         "Supplier A must get 404 for Supplier B's order")


class TestScoringLogic(_EngineBase):
    """Unit tests for the scoring algorithm."""

    def test_geo_score_same_city_beats_intercity(self):
        """A same-city supplier should score higher than an intercity one."""
        with self.db.write_transaction() as conn:
            sup_local, loc_local = self._get_or_create_supplier(
                conn, nat_id="SC-LOC-01", display_name="محلی",
                province="اصفهان", city="اصفهان", can_local=True, can_intercity=False,
            )
            sup_nat, loc_nat = self._get_or_create_supplier(
                conn, nat_id="SC-NAT-01", display_name="ملی",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=sup_local, location_id=loc_local,
                           product_slug="appliance-kettle-2l", stock=5, price=12_500_000)
            self._add_offer(conn, supplier_id=sup_nat, location_id=loc_nat,
                           product_slug="appliance-kettle-2l", stock=5, price=12_500_000)
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "appliance-kettle-2l"),
                quantity_needed=1, customer_province="اصفهان", customer_city="اصفهان",
            )

        self.assertIsNotNone(result.selected)
        local_candidates  = [c for c in result.candidates if c.location_city == "اصفهان" and c.eligible]
        intercity_candidates = [c for c in result.candidates if c.location_city == "تهران" and c.eligible]
        if local_candidates and intercity_candidates:
            self.assertGreater(
                local_candidates[0].total_score,
                intercity_candidates[0].total_score,
                "Local supplier must score higher than intercity at same price",
            )

    def test_inactive_offer_is_not_eligible(self):
        """An inactive offer must never appear as eligible."""
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="INACT-01", display_name="غیرفعال",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                                       product_slug="appliance-kettle-2l", stock=100)
            conn.execute("UPDATE seller_offers SET status='inactive' WHERE id=?", (offer_id,))
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")

        with self.db.read_transaction() as conn:
            candidates = engine.load_candidates(
                conn, product_id=self._product_id(conn, "appliance-kettle-2l"),
                quantity_needed=1,
            )

        # None of the candidates from our inactive offer should appear
        for c in candidates:
            if c.supplier_id == sup_id:
                self.assertFalse(c.eligible, "Inactive offer must not be eligible")

    def test_zero_stock_is_not_eligible(self):
        """A candidate with stock=0 must never be eligible."""
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="ZERO-STK-01", display_name="بدون موجودی",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="appliance-kettle-2l", stock=0)
            self._set_policy(conn, "appliance-kettle-2l", "NATIONAL_SHIPPING")

        with self.db.read_transaction() as conn:
            result = engine.route(
                conn, product_id=self._product_id(conn, "appliance-kettle-2l"),
                quantity_needed=1, customer_province="تهران", customer_city="تهران",
            )

        for c in result.candidates:
            if c.supplier_id == sup_id:
                self.assertFalse(c.eligible, "Zero-stock candidate must not be eligible")


class TestStateMachine(_EngineBase):
    """Fulfillment order state machine tests."""

    def _create_test_fo(self) -> tuple[int, int]:
        """Create a test fulfillment order via checkout. Returns (fo_id, supplier_id).

        Asserts that checkout succeeds and a fulfillment order is created — no silent
        fallback.  Tests that call this must not guard with skipTest.
        """
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="SM-TEST-001", display_name="ماشین وضعیت",
                province="تهران", city="تهران", can_local=True, can_intercity=True, rating_x10=45,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="office-paper-a4-carton", stock=10, price=14_000_000)
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")

        _, h = self.new_customer()
        paper_id = self.product("office-paper-a4-carton")["id"]
        self.set_stock(paper_id, 10)
        self.add_to_cart(h, paper_id, 1)
        resp = self.checkout(h)
        self.assertEqual(resp.status_code, 201,
                         f"_create_test_fo: checkout failed: {resp.get_json()}")
        order_num = resp.get_json()["order"]["order_number"]
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?", (order_num,)
            ).fetchone()
            fo_row = conn.execute(
                "SELECT id, supplier_id FROM fulfillment_orders WHERE order_id=? AND status='assigned'",
                (int(order_row["id"]),),
            ).fetchone()
        self.assertIsNotNone(fo_row, "_create_test_fo: no fulfillment order created after checkout")
        return int(fo_row["id"]), int(fo_row["supplier_id"])

    def test_full_happy_path_transitions(self):
        """Test the complete happy path: assigned→accepted→preparing→ready→dispatched→delivered."""
        from app.services import fulfillment_service as fs

        fo_id, sup_id = self._create_test_fo()

        with self.db.write_transaction() as conn:
            fs.supplier_accept(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.read_transaction() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM fulfillment_orders WHERE id=?", (fo_id,)).fetchone()["status"],
                "accepted"
            )

        with self.db.write_transaction() as conn:
            fs.supplier_start_preparing(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_ready(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_dispatched(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

        with self.db.read_transaction() as conn:
            fo = conn.execute("SELECT status FROM fulfillment_orders WHERE id=?", (fo_id,)).fetchone()
        self.assertEqual(fo["status"], "delivered")

    def test_invalid_transition_rejected(self):
        """Jumping from assigned→delivered must raise ConflictError."""
        from app.core.errors import ConflictError
        from app.services import fulfillment_service as fs

        fo_id, sup_id = self._create_test_fo()

        with self.assertRaises(ConflictError):
            with self.db.write_transaction() as conn:
                # "delivered" is not a valid transition from "assigned"
                fs.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

    def test_state_log_records_every_transition(self):
        from app.services import fulfillment_service as fs

        fo_id, sup_id = self._create_test_fo()

        with self.db.write_transaction() as conn:
            fs.supplier_accept(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_start_preparing(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

        with self.db.read_transaction() as conn:
            logs = conn.execute(
                "SELECT from_status, to_status FROM fulfillment_state_log WHERE fulfillment_order_id=? ORDER BY id",
                (fo_id,),
            ).fetchall()

        statuses = [(r["from_status"], r["to_status"]) for r in logs]
        self.assertIn(("assigned", "accepted"),  statuses)
        self.assertIn(("accepted", "preparing"), statuses)

    def _offer_id_for_fo(self, fo_id: int) -> int:
        """Return the seller_offer_id for the first item of a fulfillment order."""
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT seller_offer_id FROM fulfillment_order_items WHERE fulfillment_order_id=? LIMIT 1",
                (fo_id,),
            ).fetchone()
        self.assertIsNotNone(row, f"No items found for FO {fo_id}")
        return int(row["seller_offer_id"])

    def _offer_state(self, offer_id: int) -> tuple[int, int]:
        """Return (stock_quantity, stock_reserved) for a seller_offer."""
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT stock_quantity, stock_reserved FROM seller_offers WHERE id=?",
                (offer_id,),
            ).fetchone()
        return int(row["stock_quantity"]), int(row["stock_reserved"])

    def test_delivery_path_stock_consumed_at_dispatch(self):
        """Delivery path: assigned→accepted→preparing→ready→dispatched→delivered.

        After dispatched: stock_reserved==0, stock_quantity reduced by 1.
        After delivered:  no further change (stock already consumed).
        """
        from app.services import fulfillment_service as fs

        fo_id, sup_id = self._create_test_fo()
        offer_id = self._offer_id_for_fo(fo_id)
        qty_before, res_before = self._offer_state(offer_id)

        # Reservation was set by checkout (stock_reserved should be 1)
        self.assertEqual(res_before, 1, "Checkout must have reserved 1 unit")

        # Run through delivery path
        with self.db.write_transaction() as conn:
            fs.supplier_accept(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_start_preparing(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_ready(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_dispatched(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

        # After dispatch: reservation gone, quantity reduced
        qty_after_dispatch, res_after_dispatch = self._offer_state(offer_id)
        self.assertEqual(res_after_dispatch, 0,
                         "stock_reserved must be 0 after dispatch")
        self.assertEqual(qty_after_dispatch, qty_before - 1,
                         "stock_quantity must be reduced by 1 after dispatch")

        # Mark delivered (dispatched→delivered): no further stock change
        with self.db.write_transaction() as conn:
            fs.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

        qty_after_deliver, res_after_deliver = self._offer_state(offer_id)
        self.assertEqual(res_after_deliver, 0,
                         "stock_reserved must remain 0 after delivered (delivery path)")
        self.assertEqual(qty_after_deliver, qty_before - 1,
                         "stock_quantity must not change again at delivered (delivery path)")

        with self.db.read_transaction() as conn:
            fo = conn.execute("SELECT status FROM fulfillment_orders WHERE id=?", (fo_id,)).fetchone()
        self.assertEqual(fo["status"], "delivered")

    def test_pickup_path_stock_consumed_at_delivered(self):
        """Pickup path: assigned→accepted→preparing→ready→delivered (direct pickup).

        Stock must be consumed at the ready→delivered transition (not at dispatch,
        since dispatch never happens in the pickup path).

        Final state: stock_reserved==0, stock_quantity reduced by exactly 1.
        """
        from app.services import fulfillment_service as fs

        fo_id, sup_id = self._create_test_fo()
        offer_id = self._offer_id_for_fo(fo_id)
        qty_before, res_before = self._offer_state(offer_id)

        self.assertEqual(res_before, 1, "Checkout must have reserved 1 unit")

        # Pickup path: skip dispatch
        with self.db.write_transaction() as conn:
            fs.supplier_accept(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_start_preparing(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_ready(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

        # At ready: reservation still held (not yet consumed)
        qty_at_ready, res_at_ready = self._offer_state(offer_id)
        self.assertEqual(res_at_ready, 1,
                         "stock_reserved must still be 1 before direct-pickup delivery")
        self.assertEqual(qty_at_ready, qty_before,
                         "stock_quantity must not have changed yet at ready")

        # Direct pickup delivery: ready → delivered (no dispatch)
        with self.db.write_transaction() as conn:
            fs.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=sup_id)

        qty_final, res_final = self._offer_state(offer_id)
        self.assertEqual(res_final, 0,
                         "stock_reserved must be 0 after pickup delivery (permanent reservation consumed)")
        self.assertEqual(qty_final, qty_before - 1,
                         "stock_quantity must be reduced by 1 after pickup delivery")

        with self.db.read_transaction() as conn:
            fo = conn.execute("SELECT status FROM fulfillment_orders WHERE id=?", (fo_id,)).fetchone()
        self.assertEqual(fo["status"], "delivered")

    def test_no_double_stock_consumption(self):
        """Delivering via the normal dispatch path must not consume stock twice.

        If _consume_stock were naively called at both dispatch AND deliver, the
        quantity would be decremented twice.  This test guards against that.
        """
        from app.services import fulfillment_service as fs

        fo_id, sup_id = self._create_test_fo()
        offer_id = self._offer_id_for_fo(fo_id)
        qty_before, _ = self._offer_state(offer_id)

        # Full delivery path
        for action in [
            lambda conn: fs.supplier_accept(conn, fulfillment_order_id=fo_id, supplier_id=sup_id),
            lambda conn: fs.supplier_start_preparing(conn, fulfillment_order_id=fo_id, supplier_id=sup_id),
            lambda conn: fs.supplier_mark_ready(conn, fulfillment_order_id=fo_id, supplier_id=sup_id),
            lambda conn: fs.supplier_mark_dispatched(conn, fulfillment_order_id=fo_id, supplier_id=sup_id),
            lambda conn: fs.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=sup_id),
        ]:
            with self.db.write_transaction() as conn:
                action(conn)

        qty_final, res_final = self._offer_state(offer_id)
        self.assertEqual(res_final, 0,
                         "stock_reserved must be 0 after full delivery path")
        self.assertEqual(qty_final, qty_before - 1,
                         "stock_quantity must be reduced exactly once (not twice)")
        self.assertGreaterEqual(qty_final, 0,
                                "stock_quantity must not go negative")


class TestSupplierIsolationAPI(_EngineBase):
    """Security: supplier portal isolation tests."""

    def test_supplier_cannot_update_another_suppliers_stock(self):
        """Supplier A calling PATCH /supplier/offers/{offer_B_id}/stock must get 404."""
        # Register two real users so we can log in with known passwords
        emailA, pwA, regA = self.register()
        self.assertEqual(regA.status_code, 201)
        emailB, pwB, regB = self.register()
        self.assertEqual(regB.status_code, 201)

        uA_id = int(self.db.query_one("SELECT id FROM users WHERE email_normalized=?", (emailA.lower(),))["id"])
        uB_id = int(self.db.query_one("SELECT id FROM users WHERE email_normalized=?", (emailB.lower(),))["id"])

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='supplier' WHERE id IN (?,?)", (uA_id, uB_id))

            supA_cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10, user_id) "
                "VALUES (?,?,?,?,?,?)",
                ("SupA", "SupA", "SA-ISOL-001", "active", 40, uA_id),
            )
            supA_id = int(supA_cur.lastrowid)  # noqa: F841 — suppA only needed for isolation

            supB_cur = conn.execute(
                "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10, user_id) "
                "VALUES (?,?,?,?,?,?)",
                ("SupB", "SupB", "SB-ISOL-001", "active", 40, uB_id),
            )
            supB_id = int(supB_cur.lastrowid)
            locB_cur = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, can_local_delivery) "
                "VALUES (?,?,?,'active',1)",
                (supB_id, "تهران", "تهران"),
            )
            locB_id = int(locB_cur.lastrowid)
            prod_id = int(conn.execute(
                "SELECT id FROM products WHERE slug='office-paper-a4-carton'"
            ).fetchone()["id"])
            offerB_cur = conn.execute(
                "INSERT INTO seller_offers (product_id, supplier_id, supplier_location_id, "
                "selling_price_minor, stock_quantity, status, fulfillment_type) "
                "VALUES (?,?,?,?,?,'active','delivery')",
                (prod_id, supB_id, locB_id, 15_000_000, 50),
            )
            offerB_id = int(offerB_cur.lastrowid)

        # Supplier A login (role was updated in DB; re-login to get supplier-role token)
        tokenA = self.client.post("/api/v1/auth/login", json={"email": emailA, "password": pwA})
        self.assertEqual(tokenA.status_code, 200,
                         f"Supplier A login must succeed: {tokenA.get_json()}")
        headersA = {"Authorization": f"Bearer {tokenA.get_json()['access_token']}"}

        resp = self.client.patch(
            f"/api/v1/supplier/offers/{offerB_id}/stock",
            json={"stock_quantity": 999},
            headers=headersA,
        )
        self.assertIn(resp.status_code, (404, 400),
                      "Supplier A must not be able to update Supplier B's stock")

    def test_supplier_cannot_see_anothers_fulfillment_order(self):
        """GET /supplier/orders/{fo_id} must 404 when FO belongs to another supplier."""
        # Register supplier X1 so we can log in with a real password
        emailX1, pwX1, regX1 = self.register()
        self.assertEqual(regX1.status_code, 201)
        uX1_id = int(self.db.query_one("SELECT id FROM users WHERE email_normalized=?", (emailX1.lower(),))["id"])

        with self.db.write_transaction() as conn:
            conn.execute("UPDATE users SET role='supplier' WHERE id=?", (uX1_id,))

            # Create two suppliers, FO owned by X2
            for suffix in ["X1", "X2"]:
                exists = conn.execute(
                    f"SELECT 1 FROM suppliers WHERE national_id='ISOL-{suffix}'"
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO suppliers (legal_name, display_name, national_id, status, rating_x10) "
                        "VALUES (?,?,?,?,?)",
                        (f"Sup{suffix}", f"Sup{suffix}", f"ISOL-{suffix}", "active", 40),
                    )

            supX1 = int(conn.execute("SELECT id FROM suppliers WHERE national_id='ISOL-X1'").fetchone()["id"])
            supX2 = int(conn.execute("SELECT id FROM suppliers WHERE national_id='ISOL-X2'").fetchone()["id"])

            # Attach user to X1 (clear any existing link first)
            conn.execute("UPDATE suppliers SET user_id=NULL WHERE user_id=?", (uX1_id,))
            conn.execute("UPDATE suppliers SET user_id=? WHERE id=?", (uX1_id, supX1))

            # Dummy order
            cust_cur = conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, role) "
                "VALUES (?,?,?,?,'customer')",
                ("cust_isol@test.com", "cust_isol@test.com", "scrypt$a$b$" + "x" * 40, "CustIsol"),
            )
            cust_id = int(cust_cur.lastrowid)
            order_cur = conn.execute(
                "INSERT INTO orders (order_number, user_id, status, subtotal_minor, total_minor, "
                "currency, recipient_name, recipient_phone, shipping_province, shipping_city, shipping_line1) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("TST-ISOL-001", cust_id, "paid", 10_000_000, 10_000_000, "IRR",
                 "تست", "09121111111", "تهران", "تهران", "خ"),
            )
            order_id = int(order_cur.lastrowid)

            locX2_cur = conn.execute(
                "INSERT INTO supplier_locations (supplier_id, province, city, status, can_local_delivery) "
                "VALUES (?,?,?,'active',1)",
                (supX2, "تهران", "تهران"),
            )
            locX2_id = int(locX2_cur.lastrowid)

            fo_cur = conn.execute(
                "INSERT INTO fulfillment_orders (order_id, supplier_id, supplier_location_id, status) "
                "VALUES (?,?,?, 'assigned')",
                (order_id, supX2, locX2_id),
            )
            fo_id = int(fo_cur.lastrowid)

        # X1 tries to read X2's FO (re-login to pick up role=supplier in the token)
        tokenX1 = self.client.post("/api/v1/auth/login", json={"email": emailX1, "password": pwX1})
        self.assertEqual(tokenX1.status_code, 200,
                         f"Supplier X1 login must succeed: {tokenX1.get_json()}")
        headersX1 = {"Authorization": f"Bearer {tokenX1.get_json()['access_token']}"}

        resp = self.client.get(f"/api/v1/supplier/orders/{fo_id}", headers=headersX1)
        self.assertEqual(resp.status_code, 404,
                         "Supplier X1 must not see Supplier X2's fulfillment order")


class TestRoutingAudit(_EngineBase):
    """Routing audit trail is recorded."""

    def test_routing_audit_created_on_checkout(self):
        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="AUDIT-001", display_name="آدیت",
                province="تهران", city="تهران", can_local=True, can_intercity=True, rating_x10=40,
            )
            self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                           product_slug="office-paper-a4-carton", stock=5, price=14_500_000)
            self._set_policy(conn, "office-paper-a4-carton", "NATIONAL_SHIPPING")

        _, h = self.new_customer()
        self.set_stock(self.product("office-paper-a4-carton")["id"], 5)
        self.add_to_cart(h, self.product("office-paper-a4-carton")["id"], 1)
        resp = self.checkout(h)
        self.assertEqual(resp.status_code, 201,
                         f"TestRoutingAudit checkout failed: {resp.get_json()}")

        order_num = resp.get_json()["order"]["order_number"]
        with self.db.read_transaction() as conn:
            order_row = conn.execute(
                "SELECT id FROM orders WHERE order_number=?", (order_num,)
            ).fetchone()
            fo_rows = conn.execute(
                "SELECT id FROM fulfillment_orders WHERE order_id=?",
                (int(order_row["id"]),),
            ).fetchall()

        self.assertTrue(len(fo_rows) >= 1,
                        "At least one fulfillment order must be created after checkout")

        fo_id = int(fo_rows[0]["id"])
        with self.db.read_transaction() as conn:
            audit_rows = conn.execute(
                "SELECT event_type, selected_supplier_id FROM routing_audit WHERE fulfillment_order_id=?",
                (fo_id,),
            ).fetchall()

        self.assertTrue(len(audit_rows) >= 1, "Routing audit must be recorded")
        event_types = {r["event_type"] for r in audit_rows}
        self.assertIn("initial_routing", event_types, "Initial routing event must be recorded")


class TestStockReservation(_EngineBase):
    """Supplier stock reservation semantics."""

    def test_no_negative_stock_reservation(self):
        """Reserving more than available must fail with ConflictError."""
        from app.core.errors import ConflictError
        from app.services.fulfillment_service import _reserve_stock

        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="RSRV-001", display_name="رزرو تست",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                                       product_slug="appliance-kettle-2l", stock=1)

        with self.assertRaises(ConflictError):
            with self.db.write_transaction() as conn:
                _reserve_stock(conn, offer_id=offer_id, quantity=2)

    def test_stock_released_on_failure(self):
        """Released stock returns to available."""
        from app.services.fulfillment_service import _release_stock, _reserve_stock

        with self.db.write_transaction() as conn:
            sup_id, loc_id = self._get_or_create_supplier(
                conn, nat_id="REL-001", display_name="آزاد",
                province="تهران", city="تهران", can_local=True, can_intercity=True,
            )
            offer_id = self._add_offer(conn, supplier_id=sup_id, location_id=loc_id,
                                       product_slug="appliance-kettle-2l", stock=5)

        with self.db.write_transaction() as conn:
            _reserve_stock(conn, offer_id=offer_id, quantity=3)
        with self.db.write_transaction() as conn:
            _release_stock(conn, offer_id=offer_id, quantity=3)

        row = self.db.query_one(
            "SELECT stock_reserved FROM seller_offers WHERE id=?", (offer_id,)
        )
        self.assertEqual(int(row["stock_reserved"]), 0, "Stock must be fully released")


class TestPolicyEnforcement(_EngineBase):
    """Policy gate unit tests."""

    def test_local_only_rejects_non_local_candidate(self):
        c = engine.OfferCandidate(
            offer_id=1, supplier_id=1, supplier_name="ملی", supplier_type="retailer",
            supplier_status="active", supplier_rating_x10=40,
            location_id=1, location_province="تهران", location_city="تهران",
            can_local_delivery=True, can_intercity_shipping=True, can_pickup=False,
            prep_time_minutes=60, selling_price_minor=100_000, cost_price_minor=None,
            stock_available=5, fulfillment_type="delivery",
        )
        c.geo_tier = "intercity"
        ok, reason = engine._policy_gate(c, "LOCAL_ONLY")
        self.assertFalse(ok)
        self.assertIn("LOCAL_ONLY", reason)

    def test_national_shipping_allows_intercity_with_capability(self):
        c = engine.OfferCandidate(
            offer_id=1, supplier_id=1, supplier_name="ملی", supplier_type="retailer",
            supplier_status="active", supplier_rating_x10=40,
            location_id=1, location_province="تهران", location_city="تهران",
            can_local_delivery=True, can_intercity_shipping=True, can_pickup=False,
            prep_time_minutes=60, selling_price_minor=100_000, cost_price_minor=None,
            stock_available=5, fulfillment_type="delivery",
        )
        c.geo_tier = "intercity"
        ok, reason = engine._policy_gate(c, "NATIONAL_SHIPPING")
        self.assertTrue(ok)

    def test_national_shipping_rejects_intercity_without_capability(self):
        c = engine.OfferCandidate(
            offer_id=1, supplier_id=1, supplier_name="محدود", supplier_type="local_shop",
            supplier_status="active", supplier_rating_x10=40,
            location_id=1, location_province="اصفهان", location_city="اصفهان",
            can_local_delivery=True, can_intercity_shipping=False, can_pickup=False,
            prep_time_minutes=60, selling_price_minor=100_000, cost_price_minor=None,
            stock_available=5, fulfillment_type="delivery",
        )
        c.geo_tier = "intercity"
        ok, reason = engine._policy_gate(c, "NATIONAL_SHIPPING")
        self.assertFalse(ok)

    def test_norm_city_matching(self):
        self.assertTrue(engine.same_city("تهران", "تهران "))
        self.assertTrue(engine.same_city("Isfahan", "isfahan"))
        self.assertFalse(engine.same_city("تهران", "اصفهان"))


if __name__ == "__main__":
    unittest.main()
