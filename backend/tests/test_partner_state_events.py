"""order.status_changed and offer.stock_low partner webhooks (state-diff bridge)."""
from __future__ import annotations

import json

from app.services import partner_webhook_service as hooks
from tests.base import TEST_SECRET
from tests.test_phase5a_partner_api import _Base, _public_resolver


class StateEventsTest(_Base):
    def sub(self, owner_type, events):
        client, _ = self.make_client(["orders:read"], owner_type=owner_type) if owner_type == "platform" else self.make_client(["orders:read"])
        with self.db.write_transaction() as c:
            hooks.create_subscription(c, client_id=client["id"], url="https://hooks.example.com/60", event_types=events,
                                      master_key=TEST_SECRET, actor_user_id=None, resolver=_public_resolver)
        return client

    def events(self, kind):
        with self.db.read_transaction() as c:
            return [dict(r) for r in c.execute("SELECT * FROM partner_webhook_events WHERE event_type=? ORDER BY id", (kind,))]

    def test_stock_low_fires_once_per_drop(self):
        self.sub("supplier", ["offer.stock_low"])
        hooks.bridge_state_changes(self.db)  # baseline (stock 50)
        oid = self.offer["offer_id"] if "offer_id" in self.offer else self.offer["id"]
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET stock_quantity=2 WHERE id=?", (oid,))
        hooks.bridge_state_changes(self.db)
        hooks.bridge_state_changes(self.db)
        ev = [e for e in self.events("offer.stock_low") if json.loads(e["payload_json"]).get("offer_id") == oid]
        self.assertEqual(len(ev), 1)
        self.assertEqual(json.loads(ev[0]["payload_json"])["stock_quantity"], 2)
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET stock_quantity=20 WHERE id=?", (oid,))
        hooks.bridge_state_changes(self.db)
        with self.db.write_transaction() as c:
            c.execute("UPDATE seller_offers SET stock_quantity=0 WHERE id=?", (oid,))
        hooks.bridge_state_changes(self.db)
        ev = [e for e in self.events("offer.stock_low") if json.loads(e["payload_json"]).get("offer_id") == oid]
        self.assertEqual(len(ev), 2)
        with self.db.read_transaction() as c:
            self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 2)

    def test_order_and_seller_part_status(self):
        self.sub("platform", ["order.status_changed"])
        product = self.product("office-paper-a4-carton")
        self.set_stock(product["id"], 10)
        _, h = self.new_customer()
        self.add_to_cart(h, product["id"], 1)
        self.assertEqual(self.checkout(h).status_code, 201)
        hooks.bridge_state_changes(self.db)
        before = len(self.events("order.status_changed"))
        with self.db.write_transaction() as c:
            o = c.execute("SELECT id, status FROM orders ORDER BY id DESC LIMIT 1").fetchone()
            fo = c.execute("SELECT id, status, supplier_id FROM fulfillment_orders WHERE order_id=?", (o["id"],)).fetchone()
            c.execute("UPDATE orders SET status='delivered' WHERE id=?", (o["id"],))
            c.execute("UPDATE fulfillment_orders SET status='delivered' WHERE id=?", (fo["id"],))
        self.assertEqual(hooks.bridge_state_changes(self.db), 2)
        self.assertEqual(hooks.bridge_state_changes(self.db), 0)
        ev = self.events("order.status_changed")[before:]
        buyer = json.loads(ev[0]["payload_json"])
        self.assertEqual((buyer["from"], buyer["to"]), (o["status"], "delivered"))
        seller = json.loads(ev[1]["payload_json"])
        self.assertEqual((seller["supplier_id"], seller["to"]), (fo["supplier_id"], "delivered"))
        self.assertNotIn("total_minor", seller)
        self.assertEqual(json.loads(ev[1]["audience_json"])["supplier_ids"], [fo["supplier_id"]])
