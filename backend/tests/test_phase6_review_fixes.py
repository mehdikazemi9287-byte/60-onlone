"""Phase 6 security review fixes: shared catalog data protected from sellers, text/facet caps."""
from __future__ import annotations

from app.services import catalog_schema_service as cs
from app.services import faceted_search_service as fs
from app.services import marketplace_offer_service as offers
from app.core.errors import ValidationError
from tests.test_phase6_catalog_schema import Phase6Base


class SharedCatalogTest(Phase6Base):
    CAT = "supermarket--oil--liquid"

    def seller_on(self, m):
        sup = self.create_test_supplier()
        with self.db.write_transaction() as conn:
            offers.create(conn, supplier_id=sup["supplier_id"], actor=sup["user_id"],
                          data={"product_id": m["product_id"], "selling_price_minor": 1_000_000, "stock_quantity": 5,
                                "supplier_location_id": sup["location_id"]})
        return sup

    def put(self, sup, mid, attrs):
        return self.client.put(f"/api/v1/supplier/catalog/products/{mid}/attributes", headers=sup["headers"], json={"attributes": attrs})

    def test_second_seller_cannot_overwrite_or_delete(self):
        m = self.master(self.CAT)
        a, b = self.seller_on(m), self.seller_on(m)
        self.assertEqual(self.put(a, m["master_id"], {"oil_type": "sunflower"}).status_code, 200)
        r = self.put(b, m["master_id"], {"oil_type": "canola", "volume_ml": "810ml"})
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertEqual(d["written"], ["volume_ml"])   # empty attribute may be filled
        self.assertEqual(d["proposed"], ["oil_type"])   # differing value goes to review
        r = self.put(b, m["master_id"], {"oil_type": None})
        self.assertEqual(r.get_json()["skipped"], ["oil_type"])
        with self.db.read_transaction() as conn:
            self.assertEqual(cs.get_values(conn, m["master_id"])["oil_type"], "sunflower")
        # admin accepts the proposal
        h = self.admin_headers()
        items = self.client.get("/api/v1/admin/catalog/proposals", headers=h).get_json()["items"]
        self.assertEqual([i["code"] for i in items], ["oil_type"])
        ok = self.client.post(f"/api/v1/admin/catalog/proposals/{items[0]['id']}/decision", headers=h, json={"accept": True})
        self.assertEqual(ok.status_code, 200, ok.get_json())
        again = self.client.post(f"/api/v1/admin/catalog/proposals/{items[0]['id']}/decision", headers=h, json={"accept": True})
        self.assertEqual(again.status_code, 409)
        with self.db.read_transaction() as conn:
            self.assertEqual(cs.get_values(conn, m["master_id"])["oil_type"], "canola")

    def test_sole_seller_never_replaces_admin_rows(self):
        m = self.master(self.CAT)
        a = self.seller_on(m)
        with self.db.write_transaction() as conn:
            cs.set_values(conn, m["master_id"], {"oil_type": "sunflower"}, source="admin")
        d = self.put(a, m["master_id"], {"oil_type": "canola"}).get_json()
        self.assertEqual(d["proposed"], ["oil_type"])
        self.assertEqual(self.put(a, m["master_id"], {"oil_type": ""}).get_json()["skipped"], ["oil_type"])
        # sole seller can still replace its own values
        self.put(a, m["master_id"], {"volume_ml": "810ml"})
        self.assertEqual(self.put(a, m["master_id"], {"volume_ml": "1 L"}).get_json()["written"], ["volume_ml"])

    def test_inactive_offer_grants_no_access(self):
        m = self.master(self.CAT)
        a = self.seller_on(m)
        with self.db.write_transaction() as conn:
            conn.execute("UPDATE seller_offers SET status='inactive' WHERE supplier_id=?", (a["supplier_id"],))
        self.assertEqual(self.put(a, m["master_id"], {"oil_type": "canola"}).status_code, 404)

    def test_text_hard_cap(self):
        with self.db.read_transaction() as conn:
            attr = dict(conn.execute("SELECT * FROM attribute_definitions WHERE code='ingredients'").fetchone())
            self.assertEqual(len(cs.coerce(conn, attr, "ا" * 500)), 1)
            with self.assertRaises(ValidationError):
                cs.coerce(conn, attr, "ا" * 501)
            with self.assertRaises(ValidationError):
                cs.coerce(conn, attr, ["x"] * 1000)

    def test_facet_caps_and_dedupe(self):
        f = fs.parse_filters({"attr.oil_type": "canola,canola,sunflower"})
        self.assertEqual(f["attrs"]["oil_type"], ["canola", "sunflower"])
        with self.assertRaises(ValidationError):
            fs.parse_filters({"attr.oil_type": ",".join(str(i) for i in range(51))})
        with self.assertRaises(ValidationError):
            fs.parse_filters({f"attr.a{i}x": "1" for i in range(11)})
        r = self.client.get("/api/v1/storefront/products?" + "&".join(f"attr.a{i}x=1" for i in range(11)))
        self.assertEqual(r.status_code, 422)
