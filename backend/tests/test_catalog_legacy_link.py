from tests.base import AppTestCase
from app.services.master_catalog_service import create_master_product


class LegacyLinkTest(AppTestCase):
    def test_link_replay_and_duplicate_prevention(self):
        headers = self.admin_headers()
        with self.db.write_transaction() as conn:
            master = create_master_product(conn, canonical_name_fa="مرجع آزمون")
            products = conn.execute(
                "SELECT id FROM products WHERE master_product_id IS NULL LIMIT 2"
            ).fetchall()
        body = {"master_product_id": master["id"], "evidence": "مدرک تطبیق صرفاً در آزمون مجزا"}
        first = "/api/v1/admin/catalog/legacy-products/" + str(products[0]["id"]) + "/link"
        response = self.client.post(first, json=body, headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(self.client.post(first, json=body, headers=headers).get_json()["changed"])
        second = "/api/v1/admin/catalog/legacy-products/" + str(products[1]["id"]) + "/link"
        self.assertEqual(self.client.post(second, json=body, headers=headers).status_code, 409)
        self.assertEqual(
            self.db.query_one(
                "SELECT COUNT(*) n FROM audit_logs WHERE action='catalog_legacy_link'"
            )["n"],
            1,
        )
        _, customer = self.new_customer()
        self.assertEqual(self.client.post(first, json=body, headers=customer).status_code, 403)
