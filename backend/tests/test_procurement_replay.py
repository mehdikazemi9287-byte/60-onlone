from tests.base import AppTestCase
from tests.test_procurement import _make_org_with_admin


class ProcurementReplayTest(AppTestCase):
    def setUp(self):
        super().setUp()
        org, self.headers, _ = _make_org_with_admin(self)
        self.path = f"/api/v1/orgs/{org['id']}/procurement/requests"
        self.headers = {**self.headers, "Idempotency-Key": "isolated-procurement-replay"}
        self.body = {
            "title": "درخواست آزمون",
            "items": [{"free_text_description": "شرح آزمایشی", "quantity": 2}],
        }

    def test_retry_and_changed_payload(self):
        a = self.client.post(self.path, json=self.body, headers=self.headers)
        self.assertEqual(a.status_code, 201, a.get_json())
        b = self.client.post(self.path, json=self.body, headers=self.headers)
        self.assertEqual(b.status_code, 200, b.get_json())
        self.assertEqual(a.get_json(), b.get_json())
        self.assertEqual(
            self.client.post(
                self.path, json={**self.body, "title": "تغییر"}, headers=self.headers
            ).status_code,
            409,
        )
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM purchase_requests")["n"], 1)

    def test_other_user_cannot_replay(self):
        self.assertEqual(
            self.client.post(self.path, json=self.body, headers=self.headers).status_code, 201
        )
        _, other = self.new_customer()
        response = self.client.post(
            self.path,
            json=self.body,
            headers={**other, "Idempotency-Key": "isolated-procurement-replay"},
        )
        self.assertIn(response.status_code, (403, 404))

    def test_invalid_items_rollback(self):
        for item in [
            {"free_text_description": "x", "quantity": True},
            {"master_product_id": 999999, "quantity": 1},
        ]:
            response = self.client.post(
                self.path, json={**self.body, "items": [item]}, headers=self.headers
            )
            self.assertEqual(response.status_code, 422, response.get_json())
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM purchase_requests")["n"], 0)
