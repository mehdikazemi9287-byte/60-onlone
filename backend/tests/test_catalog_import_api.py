from tests.base import AppTestCase


class CatalogImportApiTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.admin_headers()
        self.body = {
            "source": "isolated unit-test fixture",
            "csv_text": "canonical_name_fa,category_slug,sku,publish_status\nکالای آزمون بدون قیمت,office,INQUIRY-TEST,active\n",
        }

    def test_preview_confirm_and_replay_conflict(self):
        before = self.db.query_one("SELECT COUNT(*) n FROM products")["n"]
        preview = self.client.post(
            "/api/v1/admin/catalog/import", json=self.body, headers=self.headers
        )
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertFalse(preview.get_json()["confirmed"])
        token = preview.get_json()["preview_token"]
        response = self.client.post(
            "/api/v1/admin/catalog/import",
            json={**self.body, "confirm": True, "preview_token": token},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["published"], 1)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM products")["n"], before)
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/catalog/import",
                json={**self.body, "confirm": True, "preview_token": token},
                headers=self.headers,
            ).status_code,
            409,
        )
        row = self.db.query_one("SELECT * FROM catalog_publications")
        product = self.client.get("/api/v1/products/" + row["slug"]).get_json()["product"]
        self.assertIsNone(product["price_minor"])
        self.assertFalse(product["purchasable"])
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) n FROM audit_logs WHERE action='catalog_import'")[
                "n"
            ],
            1,
        )

    def test_wrong_payload_and_customer_denied(self):
        token = self.client.post(
            "/api/v1/admin/catalog/import", json=self.body, headers=self.headers
        ).get_json()["preview_token"]
        response = self.client.post(
            "/api/v1/admin/catalog/import",
            json={**self.body, "source": "changed", "confirm": True, "preview_token": token},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 409)
        _, headers = self.new_customer()
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/catalog/import", json=self.body, headers=headers
            ).status_code,
            403,
        )
