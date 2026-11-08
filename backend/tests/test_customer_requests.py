from tests.base import AppTestCase


class CustomerRequestTest(AppTestCase):
    def setUp(self):
        super().setUp()
        _, self.headers = self.new_customer()
        self.body = {
            "kind": "price",
            "subject": "استعلام",
            "message": "شرایط تحویل",
            "items": [{"slug": "office-paper-a4-carton", "quantity": 2}],
        }

    def post(self, body=None, key="inquiry-1", headers=None):
        return self.client.post(
            "/api/v1/requests",
            json=body or self.body,
            headers={**(headers or self.headers), "Idempotency-Key": key},
        )

    def test_create_replay_and_ownership(self):
        first = self.post()
        self.assertEqual(first.status_code, 201, first.get_json())
        rid = first.get_json()["request"]["id"]
        self.assertEqual(self.post().status_code, 200)
        _, other = self.new_customer()
        self.assertEqual(self.client.get(f"/api/v1/requests/{rid}", headers=other).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/admin/requests", headers=other).status_code, 403)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM customer_requests")["n"], 1)
        self.assertNotIn("price_minor", first.get_json()["request"]["items"][0])

    def test_changed_replay_rejected(self):
        self.assertEqual(self.post().status_code, 201)
        changed = {**self.body, "message": "تغییر"}
        self.assertEqual(self.post(changed).status_code, 409)

    def test_invalid_item_and_org_rejected(self):
        for items in [
            [{"slug": "missing", "quantity": 1}],
            [{"slug": "office-paper-a4-carton", "quantity": True}],
        ]:
            self.assertIn(self.post({**self.body, "items": items}).status_code, (404, 422))
        self.assertEqual(self.post({**self.body, "organization_id": 999999}).status_code, 404)

    def test_admin_response_audited(self):
        rid = self.post().get_json()["request"]["id"]
        admin = self.admin_headers()
        response = self.client.patch(
            f"/api/v1/admin/requests/{rid}",
            json={"status": "answered", "response": "نیازمند بررسی تأمین"},
            headers=admin,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(len(response.get_json()["events"]), 2)
