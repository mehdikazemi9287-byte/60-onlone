"""Phase 6 — seller write path for typed product attributes (PUT /supplier/catalog/products/<mid>/attributes)."""
from __future__ import annotations

import json

from app.services import catalog_schema_service as cs
from app.services import marketplace_offer_service as offers
from tests.test_phase6_catalog_schema import Phase6Base


class SellerAttributesTest(Phase6Base):
    CAT = "supermarket--oil--liquid"

    def owned(self):
        sup = self.create_test_supplier()
        m = self.master(self.CAT)
        with self.db.write_transaction() as conn:
            offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"],
                          data={"product_id": m["product_id"], "selling_price_minor": 1_000_000, "stock_quantity": 5,
                                "supplier_location_id": sup["location_id"]})
        return sup, m

    def url(self, mid):
        return f"/api/v1/supplier/catalog/products/{mid}/attributes"

    def test_owner_saves_and_gets_quality(self):
        sup, m = self.owned()
        r = self.client.put(self.url(m["master_id"]), headers=sup["headers"],
                            json={"attributes": {"volume_ml": "۸۱۰ میلی‌لیتر", "oil_type": "sunflower", "shelf_life_months": "۱۲"}})
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertEqual(sorted(d["written"]), ["oil_type", "shelf_life_months", "volume_ml"])
        self.assertIn("score", d["quality"])
        self.assertEqual(d["quality"]["missing_required"], [])
        with self.db.read_transaction() as conn:
            vals = cs.get_values(conn, m["master_id"])
            self.assertEqual(vals["oil_type"], "sunflower")
            src = conn.execute("SELECT DISTINCT source FROM product_attribute_values WHERE master_product_id=?", (m["master_id"],)).fetchall()
            self.assertEqual([x["source"] for x in src], ["seller"])
            log = conn.execute("SELECT * FROM audit_logs WHERE action='supplier.catalog.attributes_set' AND entity_id=?",
                               (str(m["master_id"]),)).fetchone()
            self.assertIsNotNone(log)
            self.assertEqual(json.loads(log["metadata_json"])["supplier_id"], sup["supplier_id"])
        g = self.client.get(self.url(m["master_id"]), headers=sup["headers"])
        self.assertEqual(g.status_code, 200, g.get_json())
        self.assertEqual(g.get_json()["category_slug"], self.CAT)
        self.assertEqual(g.get_json()["values"]["oil_type"], "sunflower")
        lst = self.client.get("/api/v1/supplier/offers", headers=sup["headers"]).get_json()["offers"]
        self.assertEqual(lst[0]["master_product_id"], m["master_id"])

    def test_required_missing_reported(self):
        sup, m = self.owned()
        r = self.client.put(self.url(m["master_id"]), headers=sup["headers"], json={"attributes": {"oil_type": "sunflower"}})
        self.assertEqual(r.status_code, 200, r.get_json())
        q = r.get_json()["quality"]
        self.assertTrue(q["missing_required"])
        bad = [c["key"] for c in q["checklist"] if not c["ok"]]
        self.assertIn("attr:volume_ml", bad)

    def test_invalid_enum_422(self):
        sup, m = self.owned()
        r = self.client.put(self.url(m["master_id"]), headers=sup["headers"], json={"attributes": {"oil_type": "no-such-oil"}})
        self.assertEqual(r.status_code, 422, r.get_json())
        with self.db.read_transaction() as conn:
            self.assertNotIn("oil_type", cs.get_values(conn, m["master_id"]))

    def test_other_seller_404_and_non_supplier_403(self):
        _, m = self.owned()
        other = self.create_test_supplier()
        r = self.client.put(self.url(m["master_id"]), headers=other["headers"], json={"attributes": {"oil_type": "sunflower"}})
        self.assertEqual(r.status_code, 404, r.get_json())
        self.assertEqual(self.client.get(self.url(m["master_id"]), headers=other["headers"]).status_code, 404)
        self.assertEqual(self.client.put(self.url(999999), headers=other["headers"], json={"attributes": {}}).status_code, 404)
        _, cust = self.new_customer()
        self.assertEqual(self.client.put(self.url(m["master_id"]), headers=cust, json={"attributes": {}}).status_code, 403)
        self.assertEqual(self.client.put(self.url(m["master_id"]), json={"attributes": {}}).status_code, 401)

    def test_body_must_have_attributes_object(self):
        sup, m = self.owned()
        self.assertEqual(self.client.put(self.url(m["master_id"]), headers=sup["headers"], json={"attributes": []}).status_code, 422)
