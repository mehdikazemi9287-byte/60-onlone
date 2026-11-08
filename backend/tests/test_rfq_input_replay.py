from tests.base import AppTestCase
from tests.test_vat_procurement_regression import _make_org_with_admin, _setup_full_rfq

class RFQInputReplayTest(AppTestCase):
    def setUp(self):
        super().setUp()
        org, _, uid = _make_org_with_admin(self)
        rfq, items, supplier = _setup_full_rfq(self, org["id"], uid, [{"quantity": 2}])
        token, self.headers = self.new_customer()
        with self.db.write_transaction() as conn:
            row = conn.execute("SELECT id FROM users ORDER BY id DESC LIMIT 1").fetchone()
            conn.execute("UPDATE suppliers SET user_id=? WHERE id=?", (row["id"], supplier))
        self.path = f"/api/v1/supplier/rfqs/{rfq}/quotes"
        self.headers = {**self.headers, "Idempotency-Key": "isolated-rfq-replay"}
        self.body = {"items": [{"rfq_item_id": items[0], "quantity": 2, "unit_price_minor": 100}], "shipping_cost_minor": 0}

    def test_replay_and_payload_conflict(self):
        first = self.client.post(self.path, json=self.body, headers=self.headers)
        self.assertEqual(first.status_code, 201, first.get_json())
        replay = self.client.post(self.path, json=self.body, headers=self.headers)
        self.assertEqual(replay.status_code, 200, replay.get_json())
        self.assertEqual(first.get_json(), replay.get_json())
        conflict = self.client.post(self.path, json={**self.body, "shipping_cost_minor": 1}, headers=self.headers)
        self.assertEqual(conflict.status_code, 409, conflict.get_json())
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM supplier_quotes")["n"], 1)

    def test_invalid_money_quantity_and_duplicates_are_atomic(self):
        item = self.body["items"][0]
        bad = [
            {**self.body, "items": [{**item, "unit_price_minor": True}]},
            {**self.body, "items": [{**item, "unit_price_minor": 1.5}]},
            {**self.body, "items": [{k:v for k,v in item.items() if k != "unit_price_minor"}]},
            {**self.body, "items": [{**item, "quantity": True}]},
            {**self.body, "items": [item, item]},
            {**self.body, "shipping_cost_minor": "0"},
            {**self.body, "items": [{**item, "unit_price_minor": 9007199254740991}]},
        ]
        for body in bad:
            response = self.client.post(self.path, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 422, response.get_json())
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM supplier_quotes")["n"], 0)

    def test_other_user_cannot_replay_quote(self):
        self.assertEqual(self.client.post(self.path, json=self.body, headers=self.headers).status_code, 201)
        _, headers = self.new_customer()
        response = self.client.post(self.path, json=self.body, headers={**headers, "Idempotency-Key": "isolated-rfq-replay"})
        self.assertIn(response.status_code, (403, 404, 422))
