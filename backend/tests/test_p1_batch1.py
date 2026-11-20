"""P1 batch 1 (2026-11-21): per-mode carts, customer cancellation before shipment, address book.

Synthetic test fixtures only (seeded test catalog, throwaway users); nothing here is runtime business data.
"""
from __future__ import annotations

import sqlite3
import uuid

from app.services import fulfillment_service, ledger_service, loyalty_service
from tests.base import AppTestCase

STAFF = {"X-Shopping-Mode": "staff"}
ORG = {"X-Shopping-Mode": "org"}


class _Helpers(AppTestCase):
    PAPER = "office-paper-a4-carton"

    def user_id(self, headers: dict) -> int:
        return self.client.get("/api/v1/auth/me", headers=headers).get_json()["user"]["id"]

    def cart(self, headers: dict) -> dict:
        r = self.client.get("/api/v1/cart", headers=headers)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def second_product(self, exclude: int) -> dict:
        with self.db.read_transaction() as conn:
            row = conn.execute(
                "SELECT p.slug FROM products p JOIN inventory i ON i.product_id = p.id "
                "WHERE p.is_active = 1 AND p.base_price_minor > 0 AND p.id <> ? ORDER BY p.id LIMIT 1",
                (exclude,)).fetchone()
        return self.product(row["slug"])

    def pay(self, headers: dict, *, key: str | None = None, **body):
        return self.client.post("/api/v1/checkout", json={"shipping_address": self.DEFAULT_ADDRESS, **body},
                                headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex})

    def ledger_balance(self, code: str) -> int:
        with self.db.read_transaction() as conn:
            return ledger_service.account_balance_minor(conn, code)

    def coins(self, user_id: int) -> int:
        with self.db.read_transaction() as conn:
            return loyalty_service.balance(conn, user_id)


# ──────────────────────────────────────────────────────────── 1. per-mode carts
class ShoppingModeCartTest(_Helpers):
    def test_each_mode_has_its_own_cart_and_no_header_is_personal(self):
        org, admin_headers, admin, emp = self.org_fixture()
        auth = {"Authorization": emp["headers"]["Authorization"]}  # no mode header = personal (old client)
        a = self.product(self.PAPER)
        b = self.second_product(a["id"])
        self.set_stock(a["id"], 50); self.set_stock(b["id"], 50)
        self.assertEqual(self.add_to_cart(auth, a["id"], 2).status_code, 201)
        self.assertEqual(self.add_to_cart({**auth, **STAFF}, b["id"], 1).status_code, 201)
        personal, staff = self.cart(auth), self.cart({**auth, **STAFF})
        self.assertEqual([i["product_id"] for i in personal["items"]], [a["id"]])
        self.assertEqual([i["product_id"] for i in staff["items"]], [b["id"]])
        self.assertEqual((personal["shopping_mode"], staff["shopping_mode"]), ("personal", "staff"))
        self.assertNotEqual(personal["cart_id"], staff["cart_id"])
        explicit = self.cart({**auth, "X-Shopping-Mode": "personal"})
        self.assertEqual(explicit["cart_id"], personal["cart_id"])
        # ?mode= works too, the header wins over it
        self.assertEqual(self.client.get("/api/v1/cart?mode=staff", headers=auth).get_json()["cart_id"], staff["cart_id"])
        summary = self.client.get("/api/v1/cart/summary", headers=auth).get_json()["modes"]
        self.assertEqual({m["shopping_mode"]: m["item_count"] for m in summary}, {"personal": 2, "staff": 1, "org": 0})
        # clearing one mode leaves the other untouched
        self.client.delete("/api/v1/cart", headers={**auth, **STAFF})
        self.assertEqual(self.cart({**auth, **STAFF})["items"], [])
        self.assertEqual(len(self.cart(auth)["items"]), 1)

    def test_mode_eligibility_is_checked_on_the_server(self):
        _, customer = self.new_customer()
        p = self.product(self.PAPER)
        r = self.add_to_cart({**customer, **STAFF}, p["id"], 1)
        self.assertEqual(r.status_code, 403, r.get_json())
        self.assertEqual(r.get_json()["error"]["code"], "shopping_mode_not_allowed")
        view = self.cart({**customer, **STAFF})  # reading never breaks, never creates a cart
        self.assertEqual((view["items"], view["mode_access"]["allowed"]), ([], False))
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM carts WHERE shopping_mode='staff'").fetchone()[0], 0)
        self.assertEqual(self.client.get("/api/v1/checkout/quote", headers={**customer, **STAFF}).status_code, 403)
        self.assertEqual(self.pay({**customer, **STAFF}).status_code, 403)
        # «سازمانی و عمده» is open to any buyer (hotel, mosque, charity…): its own cart, never employer money
        self.assertEqual(self.add_to_cart({**customer, **ORG}, p["id"], 1).status_code, 201)
        q = self.quote({**customer, **ORG})
        self.assertEqual((q["shopping_mode"], q["credit_to_use_minor"]), ("org", 0))
        self.assertEqual(self.cart(customer)["items"], [])  # personal cart untouched
        # an employee is staff; an organization admin with credit still gets no credit in org mode
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=0)
        self.assertEqual(self.add_to_cart(emp["headers"], p["id"], 1).status_code, 201)
        self.assertEqual(self.add_to_cart({**admin_headers, **ORG}, p["id"], 1).status_code, 201)

    def test_invalid_mode_is_rejected(self):
        _, customer = self.new_customer()
        r = self.client.get("/api/v1/cart", headers={**customer, "X-Shopping-Mode": "vip"})
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "invalid_shopping_mode"))

    def test_checkout_takes_only_the_active_mode_cart_and_credit_only_in_staff(self):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=500_000_000)
        auth = {"Authorization": emp["headers"]["Authorization"]}
        a = self.product(self.PAPER)
        b = self.second_product(a["id"])
        self.set_stock(a["id"], 50); self.set_stock(b["id"], 50)
        self.add_to_cart(auth, a["id"], 1)
        self.add_to_cart({**auth, **STAFF}, b["id"], 1)
        q_personal = self.quote(auth)
        q_staff = self.quote({**auth, **STAFF})
        self.assertEqual((q_personal["credit_to_use_minor"], q_personal["has_organization_credit"]), (0, False))
        self.assertEqual(q_staff["credit_to_use_minor"], q_staff["cart"]["total_minor"])

        r = self.pay({**auth, **STAFF})
        self.assertEqual(r.status_code, 201, r.get_json())
        staff_order = r.get_json()["order"]
        self.assertEqual([i["product_id"] for i in staff_order["items"]], [b["id"]])
        self.assertEqual((staff_order["shopping_mode"], staff_order["credit_minor"]), ("staff", q_staff["cart"]["total_minor"]))
        # the personal cart was neither emptied nor charged
        self.assertEqual([i["product_id"] for i in self.cart(auth)["items"]], [a["id"]])
        self.assertEqual(self.cart({**auth, **STAFF})["items"], [])

        r = self.pay(auth)
        self.assertEqual(r.status_code, 201, r.get_json())
        personal_order = r.get_json()["order"]
        self.assertEqual([i["product_id"] for i in personal_order["items"]], [a["id"]])
        self.assertEqual((personal_order["shopping_mode"], personal_order["credit_minor"]), ("personal", 0))
        self.assertEqual(personal_order["cash_minor"], personal_order["total_minor"])
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)

    def test_welfare_is_refused_outside_staff_mode(self):
        _, customer = self.new_customer()
        p = self.product(self.PAPER)
        self.add_to_cart(customer, p["id"], 1)
        r = self.pay(customer, use_welfare=True)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (422, "welfare_not_in_mode"))
        w = self.client.get("/api/v1/checkout/welfare", headers=customer).get_json()
        self.assertEqual((w["available"], w["allowed_minor"]), (False, 0))

    def test_same_idempotency_key_cannot_be_replayed_in_another_mode(self):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=0)
        auth = {"Authorization": emp["headers"]["Authorization"]}
        p = self.product(self.PAPER)
        self.set_stock(p["id"], 50)
        self.add_to_cart(auth, p["id"], 1)
        self.add_to_cart({**auth, **STAFF}, p["id"], 1)
        key = uuid.uuid4().hex
        self.assertEqual(self.pay(auth, key=key).status_code, 201)
        r = self.pay({**auth, **STAFF}, key=key)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "idempotency_key_reuse"))

    def test_lost_membership_freezes_the_staff_cart_but_it_can_be_emptied(self):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=0)
        p = self.product(self.PAPER)
        self.add_to_cart(emp["headers"], p["id"], 1)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE organization_memberships SET status='inactive' WHERE id=?", (emp["id"],))
        view = self.cart(emp["headers"])
        self.assertEqual((len(view["items"]), view["mode_access"]["allowed"]), (1, False))
        self.assertEqual(self.pay(emp["headers"]).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/v1/cart/items/{p['id']}", json={"quantity": 2},
                                           headers=emp["headers"]).status_code, 403)
        r = self.client.delete(f"/api/v1/cart/items/{p['id']}", headers=emp["headers"])
        self.assertEqual((r.status_code, r.get_json()["items"]), (200, []))

    def test_schema_default_is_personal_and_one_active_cart_per_mode(self):
        _, customer = self.new_customer()
        uid = self.user_id(customer)
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO carts (user_id, status) VALUES (?, 'active')", (uid,))  # pre-0084 style insert
            self.assertEqual(conn.execute("SELECT shopping_mode FROM carts WHERE user_id=?", (uid,)).fetchone()[0],
                             "personal")
            conn.execute("INSERT INTO carts (user_id, status, shopping_mode) VALUES (?, 'active', 'staff')", (uid,))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.write_transaction() as conn:
                conn.execute("INSERT INTO carts (user_id, status, shopping_mode) VALUES (?, 'active', 'staff')", (uid,))

    def test_pack_add_and_proforma_follow_the_mode(self):
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=0)
        auth = {"Authorization": emp["headers"]["Authorization"]}
        p = self.product(self.PAPER)
        self.add_to_cart({**auth, **STAFF}, p["id"], 1)
        pf = self.client.post("/api/v1/me/proformas", json={}, headers={**auth, **STAFF})
        self.assertEqual(pf.status_code, 201, pf.get_json())
        self.assertEqual(pf.get_json()["shopping_mode"], "staff")
        self.assertEqual(self.client.post("/api/v1/me/proformas", json={}, headers=auth).get_json()["error"]["code"],
                         "cart_empty")
        # a staff pro-forma cannot guard a personal checkout
        self.add_to_cart(auth, p["id"], 1)
        r = self.pay(auth, proforma_number=pf.get_json()["number"])
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "proforma_mode_mismatch"))


# ─────────────────────────────────────────────────── 2. cancellation before shipment
class OrderCancellationTest(_Helpers):
    def place(self, headers: dict, qty: int = 1, **body) -> dict:
        p = self.product(self.PAPER)
        self.set_stock(p["id"], 50)
        self.assertEqual(self.add_to_cart(headers, p["id"], qty).status_code, 201)
        r = self.pay(headers, **body)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["order"]

    def cancel(self, headers: dict, number: str, **body):
        return self.client.post(f"/api/v1/orders/{number}/cancel", json=body, headers=headers)

    def stock(self, order_id: int) -> tuple[int, list[tuple[int, int, int]]]:
        with self.db.read_transaction() as conn:
            pid = conn.execute("SELECT product_id FROM order_items WHERE order_id=?", (order_id,)).fetchone()[0]
            inv = conn.execute("SELECT quantity_available FROM inventory WHERE product_id=?", (pid,)).fetchone()[0]
            offers = [tuple(r) for r in conn.execute(
                "SELECT so.id, so.stock_quantity, so.stock_reserved FROM seller_offers so "
                "JOIN fulfillment_order_items foi ON foi.seller_offer_id = so.id "
                "JOIN fulfillment_orders fo ON fo.id = foi.fulfillment_order_id WHERE fo.order_id=? ORDER BY so.id",
                (order_id,))]
        return inv, offers

    def test_card_order_cancel_restores_stock_coins_and_books_exact_refund(self):
        _, customer = self.new_customer()
        uid = self.user_id(customer)
        loyalty_service.earn(self.db, user_id=uid, amount_coins=50, source="campaign")
        p = self.product(self.PAPER)
        self.set_stock(p["id"], 50)
        with self.db.read_transaction() as conn:
            inv_before = conn.execute("SELECT quantity_available FROM inventory WHERE product_id=?", (p["id"],)).fetchone()[0]
        self.add_to_cart(customer, p["id"], 2)
        r = self.pay(customer, redeem_coins=3)
        self.assertEqual(r.status_code, 201, r.get_json())
        order = r.get_json()["order"]
        earned = order["subtotal_minor"] // 10_000
        self.assertEqual(self.coins(uid), 50 - 3 + earned)
        _, offers_after_checkout = self.stock(order["id"])
        self.assertTrue(offers_after_checkout, "checkout must have created fulfillment orders")
        refunds_before = self.ledger_balance("2060")

        res = self.cancel(customer, order["order_number"], reason="  دیگر لازم   ندارم ")
        self.assertEqual(res.status_code, 201, res.get_json())
        body = res.get_json()
        c = body["cancellation"]
        self.assertEqual(body["order"]["status"], "cancelled")
        self.assertEqual(c["reason"], "دیگر لازم ندارم")
        self.assertEqual(c["total_minor"], order["total_minor"])
        self.assertEqual(c["card_refund_minor"], order["total_minor"])  # card paid everything
        self.assertEqual((c["coins_restored"], c["coins_clawed_back"], c["coins_clawback_shortfall"]), (3, earned, 0))
        self.assertEqual(self.coins(uid), 50)  # exactly where the customer started
        self.assertEqual([r["status"] for r in c["refunds"]], ["pending_finance"])
        self.assertEqual(c["refunds"][0]["amount_minor"], order["total_minor"])

        inv_after, offers_after_cancel = self.stock(order["id"])
        self.assertEqual(inv_after, inv_before)
        for (oid, qty0, res0), (oid1, qty1, res1) in zip(offers_after_checkout, offers_after_cancel):
            self.assertEqual((oid, qty1), (oid1, qty0))
            self.assertEqual(res1, res0 - 2)  # the reservation made at checkout is released
        with self.db.read_transaction() as conn:
            self.assertEqual({r[0] for r in conn.execute("SELECT status FROM fulfillment_orders WHERE order_id=?",
                                                         (order["id"],))}, {"cancelled"})
            entries = ledger_service.entries_for_reference(conn, f"order-cancel:{order['order_number']}")
            audit = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action='order.cancelled_by_customer' "
                                 "AND entity_id=?", (str(order["id"]),)).fetchone()[0]
        debits = {e["account_code"]: e["amount_minor"] for e in entries if e["direction"] == "debit"}
        credits = {e["account_code"]: e["amount_minor"] for e in entries if e["direction"] == "credit"}
        self.assertEqual(debits.get("4010"), order["subtotal_minor"])
        self.assertEqual(debits.get("2010", 0), order["tax_minor"])
        self.assertEqual(debits.get("4020", 0), order["shipping_fee_minor"])
        self.assertEqual(credits, {"2060": order["total_minor"]})
        self.assertEqual(self.ledger_balance("2060") - refunds_before, order["total_minor"])
        self.assertEqual(audit, 1)
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)

    def test_double_cancel_is_idempotent(self):
        _, customer = self.new_customer()
        order = self.place(customer)
        first = self.cancel(customer, order["order_number"])
        self.assertEqual(first.status_code, 201)
        inv1, offers1 = self.stock(order["id"])
        second = self.cancel(customer, order["order_number"], reason="دوباره")
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertTrue(second.get_json()["already_cancelled"])
        self.assertEqual(second.get_json()["cancellation"]["id"], first.get_json()["cancellation"]["id"])
        self.assertEqual(self.stock(order["id"]), (inv1, offers1))  # nothing restored twice
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_refunds WHERE order_id=?", (order["id"],)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ledger_transactions WHERE reference LIKE 'order-cancel:%'").fetchone()[0], 1)
        status = self.client.get(f"/api/v1/orders/{order['order_number']}", headers=customer).get_json()["cancellation"]
        self.assertEqual((status["cancellable"], status["code"]), (False, "already_cancelled"))

    def test_staff_order_gives_back_credit_and_welfare_exactly(self):
        from app.services import credit_service, welfare_wallet_service as wf
        org, admin_headers, admin, emp = self.org_fixture(credit_minor=300_000_000)
        with self.db.write_transaction() as conn:
            wf.create_plan(conn, organization_id=org["id"], idempotency_key="w-p1", actor_user_id=None,
                           payload={"title": "بن خرید", "plan_type": "free", "per_employee_cap_minor": 100_000,
                                    "expires_at": "2099-01-01"})
        alloc_id = emp["allocation"]["id"]
        with self.db.read_transaction() as conn:
            avail0 = credit_service.allocation_state(conn, alloc_id)["available_minor"]
            welfare0 = wf.member_summary(conn, emp["user_id"])["remaining_minor"]
        receivable0 = self.ledger_balance("1020")
        order = self.place(emp["headers"], use_welfare=True)
        self.assertEqual(order["welfare_minor"], 100_000)
        self.assertEqual(order["credit_minor"], order["total_minor"] - 100_000)
        res = self.cancel(emp["headers"], order["order_number"])
        self.assertEqual(res.status_code, 201, res.get_json())
        c = res.get_json()["cancellation"]
        self.assertEqual((c["credit_restored_minor"], c["welfare_restored_minor"], c["card_refund_minor"]),
                         (order["credit_minor"], 100_000, 0))
        self.assertEqual(c["refunds"], [])  # nothing to wire back: employer money returned to its ledgers
        with self.db.read_transaction() as conn:
            self.assertEqual(credit_service.allocation_state(conn, alloc_id)["available_minor"], avail0)
            self.assertEqual(wf.member_summary(conn, emp["user_id"])["remaining_minor"], welfare0)
        self.assertEqual(self.ledger_balance("1020"), receivable0)
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)

    def _advance(self, order_id: int, *steps: str) -> int:
        with self.db.write_transaction() as conn:
            fo = conn.execute("SELECT id, supplier_id FROM fulfillment_orders WHERE order_id=? ORDER BY id LIMIT 1",
                              (order_id,)).fetchone()
            fo_id, sid = int(fo["id"]), int(fo["supplier_id"])
            for step in steps:
                if step == "delivered":
                    fulfillment_service.supplier_mark_delivered(conn, fulfillment_order_id=fo_id, supplier_id=None,
                                                                actor_type="admin")
                else:
                    getattr(fulfillment_service, step)(conn, fulfillment_order_id=fo_id, supplier_id=sid)
        return fo_id

    def test_cancel_allowed_while_preparing_but_refused_once_ready_or_shipped(self):
        _, customer = self.new_customer()
        prep = self.place(customer)
        self._advance(prep["id"], "supplier_accept", "supplier_start_preparing")
        self.assertEqual(self.cancel(customer, prep["order_number"]).status_code, 201)

        ready = self.place(customer)
        self._advance(ready["id"], "supplier_accept", "supplier_start_preparing", "supplier_mark_ready")
        r = self.cancel(customer, ready["order_number"])
        self.assertEqual(r.status_code, 409, r.get_json())
        self.assertEqual((r.get_json()["error"]["code"], r.get_json()["error"]["details"]["reason"]),
                         ("order_not_cancellable", "shipping_started"))

        shipped = self.place(customer)
        self._advance(shipped["id"], "supplier_accept", "supplier_start_preparing", "supplier_mark_ready",
                      "supplier_mark_dispatched")
        r = self.cancel(customer, shipped["order_number"])
        self.assertEqual((r.status_code, r.get_json()["error"]["details"]["reason"]), (409, "shipping_started"))
        with self.db.read_transaction() as conn:
            for o in (ready, shipped):
                self.assertEqual(conn.execute("SELECT status FROM orders WHERE id=?", (o["id"],)).fetchone()[0], "paid")
                self.assertIsNone(conn.execute("SELECT 1 FROM order_cancellations WHERE order_id=?", (o["id"],)).fetchone())

    def test_cancelled_order_never_reaches_supplier_settlement(self):
        from app.core.errors import ConflictError
        _, customer = self.new_customer()
        cancelled = self.place(customer)
        delivered = self.place(customer)
        self.assertEqual(self.cancel(customer, cancelled["order_number"]).status_code, 201)
        self._advance(delivered["id"], "supplier_accept", "supplier_start_preparing", "supplier_mark_ready", "delivered")
        with self.db.read_transaction() as conn:
            fo = conn.execute("SELECT id, supplier_id FROM fulfillment_orders WHERE order_id=?", (cancelled["id"],)).fetchone()
            payables = {r["fulfillment_order_id"] for r in conn.execute(
                "SELECT pe.fulfillment_order_id FROM supplier_payable_entries pe "
                "JOIN fulfillment_orders f ON f.id = pe.fulfillment_order_id WHERE f.order_id IN (?,?)",
                (cancelled["id"], delivered["id"]))}
        self.assertNotIn(fo["id"], payables)
        self.assertEqual(len(payables), 1)  # only the delivered order's FO earns a payable
        # the supplier can no longer move the cancelled FO towards delivery (state machine is terminal)
        for step in ("supplier_accept", "supplier_start_preparing"):
            with self.assertRaises(ConflictError):
                with self.db.write_transaction() as conn:
                    getattr(fulfillment_service, step)(conn, fulfillment_order_id=fo["id"], supplier_id=fo["supplier_id"])
        from app.services import logistics_service
        with self.assertRaises(ConflictError) as ctx:
            logistics_service.book_shipment(self.db, fo["id"], user_id=0, user_role="admin")
        self.assertEqual(ctx.exception.code, "fo_cancelled")

    def test_only_the_owner_can_cancel_and_open_returns_block_it(self):
        _, owner = self.new_customer()
        _, other = self.new_customer()
        order = self.place(owner)
        self.assertEqual(self.cancel(other, order["order_number"]).status_code, 404)
        with self.db.write_transaction() as conn:
            conn.execute("INSERT INTO order_return_requests (order_id, user_id, reason, items_json, status) "
                         "VALUES (?,?, 'defective', '[]', 'requested')", (order["id"], self.user_id(owner)))
        r = self.cancel(owner, order["order_number"])
        self.assertEqual((r.status_code, r.get_json()["error"]["details"]["reason"]), (409, "return_open"))

    def test_finance_marks_the_refund_paid_once(self):
        _, customer = self.new_customer()
        order = self.place(customer)
        self.cancel(customer, order["order_number"])
        admin = self.admin_headers()
        items = self.client.get("/api/v1/admin/order-refunds?status=pending_finance", headers=admin).get_json()["items"]
        refund = next(i for i in items if i["order_id"] == order["id"])
        self.assertEqual(self.client.get("/api/v1/admin/order-refunds", headers=customer).status_code, 403)
        before = self.ledger_balance("2060")
        url = f"/api/v1/admin/order-refunds/{refund['id']}/mark-paid"
        self.assertEqual(self.client.post(url, json={"bank_reference": "x"}, headers=admin).status_code, 422)
        r = self.client.post(url, json={"bank_reference": "SATNA-1403-0001"}, headers=admin)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["refund"]["status"], "paid")
        self.assertEqual(before - self.ledger_balance("2060"), refund["amount_minor"])
        self.assertEqual(self.client.post(url, json={"bank_reference": "SATNA-1403-0001"}, headers=admin).status_code, 200)
        r = self.client.post(url, json={"bank_reference": "OTHER-REF"}, headers=admin)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "refund_already_paid"))
        self.assertEqual(before - self.ledger_balance("2060"), refund["amount_minor"])  # paid exactly once
        debit, credit = self.trial_balance()
        self.assertEqual(debit, credit)

    def test_order_page_reports_cancellable(self):
        _, customer = self.new_customer()
        order = self.place(customer)
        st = self.client.get(f"/api/v1/orders/{order['order_number']}", headers=customer).get_json()["cancellation"]
        self.assertEqual((st["cancellable"], st["cancellation"]), (True, None))


# ──────────────────────────────────────────────────────────────── 3. address book
class AddressBookTest(_Helpers):
    GOOD = {"title": "خانه", "recipient": "مهدی کاظمی", "phone": "۰۹۱۲۱۲۳۴۵۶۷", "province": "تهران",
            "city": "تهران", "postal_code": "۱۲۳۴۵-۶۷۸۹۰", "line1": "خیابان ولیعصر، پلاک ۱۰"}

    def add(self, headers: dict, **over):
        return self.client.post("/api/v1/me/addresses", json={**self.GOOD, **over}, headers=headers)

    def test_digits_are_normalized_and_first_address_is_default(self):
        _, h = self.new_customer()
        r = self.add(h)
        self.assertEqual(r.status_code, 201, r.get_json())
        a = r.get_json()["address"]
        self.assertEqual((a["phone"], a["postal_code"], a["is_default"]), ("09121234567", "1234567890", True))
        a2 = self.add(h, title="کار", phone="+989121112233", postal_code="٨١٣٤٥٦٧٨٩٠").get_json()["address"]
        self.assertEqual((a2["phone"], a2["postal_code"], a2["is_default"]), ("09121112233", "8134567890", False))

    def test_validation_rejects_bad_postal_code_and_mobile(self):
        _, h = self.new_customer()
        for over, field in (({"postal_code": "123456789"}, "postal_code"), ({"postal_code": "12345678901"}, "postal_code"),
                            ({"phone": "02188776655"}, "phone"), ({"phone": "0912123"}, "phone"),
                            ({"line1": "کو"}, "line1"), ({"recipient": ""}, "recipient")):
            r = self.add(h, **over)
            self.assertEqual(r.status_code, 422, (over, r.get_json()))
            self.assertIn(field, r.get_json()["error"]["details"], over)
        self.assertEqual(self.client.get("/api/v1/me/addresses", headers=h).get_json()["items"], [])

    def test_one_default_switching_and_delete_promotes(self):
        _, h = self.new_customer()
        first = self.add(h).get_json()["address"]
        second = self.add(h, title="کار", is_default=True).get_json()["address"]
        items = self.client.get("/api/v1/me/addresses", headers=h).get_json()["items"]
        self.assertEqual([(i["id"], i["is_default"]) for i in items], [(second["id"], True), (first["id"], False)])
        self.client.post(f"/api/v1/me/addresses/{first['id']}/default", headers=h)
        items = self.client.delete(f"/api/v1/me/addresses/{first['id']}", headers=h).get_json()["items"]
        self.assertEqual([(i["id"], i["is_default"]) for i in items], [(second["id"], True)])
        r = self.client.patch(f"/api/v1/me/addresses/{second['id']}", json={"postal_code": "۹۸۷۶۵۴۳۲۱۰"}, headers=h)
        self.assertEqual(r.get_json()["address"]["postal_code"], "9876543210")
        self.assertEqual(self.client.patch(f"/api/v1/me/addresses/{second['id']}", json={"phone": "123"},
                                           headers=h).status_code, 422)

    def test_owner_scope_and_checkout_by_address_id(self):
        _, owner = self.new_customer()
        _, other = self.new_customer()
        a = self.add(owner, postal_code="8134567890").get_json()["address"]
        self.assertEqual(self.client.patch(f"/api/v1/me/addresses/{a['id']}", json={"title": "x"}, headers=other).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/me/addresses/{a['id']}", headers=other).status_code, 404)
        p = self.product(self.PAPER)
        self.add_to_cart(other, p["id"], 1)
        r = self.client.post("/api/v1/checkout", json={"address_id": a["id"]},
                             headers={**other, "Idempotency-Key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 404, r.get_json())  # another user's saved address is never usable
        self.add_to_cart(owner, p["id"], 1)
        r = self.client.post("/api/v1/checkout", json={"address_id": a["id"]},
                             headers={**owner, "Idempotency-Key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 201, r.get_json())
        ship = r.get_json()["order"]["shipping_address"]
        self.assertEqual((ship["recipient_name"], ship["recipient_phone"], ship["postal_code"]),
                         ("مهدی کاظمی", "09121234567", "8134567890"))
        # editing the saved address later never rewrites the order's copy
        self.client.patch(f"/api/v1/me/addresses/{a['id']}", json={"line1": "نشانی تازه برای آزمون"}, headers=owner)
        order = self.client.get(f"/api/v1/orders/{r.get_json()['order']['order_number']}", headers=owner).get_json()["order"]
        self.assertEqual(order["shipping_address"]["line1"], "خیابان ولیعصر، پلاک ۱۰")

    def test_typed_checkout_address_digits_and_postal_code(self):
        _, h = self.new_customer()
        p = self.product(self.PAPER)
        self.add_to_cart(h, p["id"], 1)
        bad = {**self.DEFAULT_ADDRESS, "postal_code": "۱۲۳"}
        r = self.client.post("/api/v1/checkout", json={"shipping_address": bad}, headers={**h, "Idempotency-Key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 422)
        self.assertIn("postal_code", r.get_json()["error"]["details"])
        good = {**self.DEFAULT_ADDRESS, "recipient_phone": "۰۹۱۲۱۲۳۴۵۶۷", "postal_code": "۱۲۳۴۵۶۷۸۹۰"}
        r = self.client.post("/api/v1/checkout", json={"shipping_address": good}, headers={**h, "Idempotency-Key": uuid.uuid4().hex})
        self.assertEqual(r.status_code, 201, r.get_json())
        ship = r.get_json()["order"]["shipping_address"]
        self.assertEqual((ship["recipient_phone"], ship["postal_code"]), ("09121234567", "1234567890"))

    def test_address_limit(self):
        from app.services import address_book_service
        _, h = self.new_customer()
        for i in range(address_book_service.MAX_ADDRESSES):
            self.assertEqual(self.add(h, title=f"نشانی {i}").status_code, 201)
        r = self.add(h, title="یکی بیشتر")
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "address_limit"))
