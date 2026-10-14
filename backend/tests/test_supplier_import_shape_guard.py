from tests.test_supplier_marketplace_phase2_3 import _Base
from app.services import supplier_service, supplier_catalog_import_service
from app.core.errors import ValidationError

class SupplierImportShapeGuardTest(_Base):
    def test_mixed_rows_reject_shapes_and_reserved_stock_without_partial_price(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "mobile-samsung-a55")
            sup = self._make_supplier(conn, nat_id="SHAPE-001", name="Shape")
            loc = self._make_location(conn, supplier_id=sup)
            conn.execute("INSERT INTO product_identifiers (product_id,identifier_type,identifier_value) VALUES (?,'EAN','shape-barcode')", (pid,))
            offer = supplier_service.create_offer(conn, product_id=pid, supplier_id=sup, supplier_location_id=loc, selling_price_minor=100, stock_quantity=10)
            conn.execute("UPDATE seller_offers SET stock_reserved=5 WHERE id=?", (offer["id"],))
            rows = [None, [], "bad", 123, {"barcode":123, "selling_price_minor":200}, {"barcode":"shape-barcode", "supplier_sku":{}, "sku":123, "selling_price_minor":200}, {"barcode":"shape-barcode", "selling_price_minor":200, "stock_quantity":4}, {"barcode":"unknown", "selling_price_minor":"9007199254740995", "stock_quantity":"۱۲"}]
            result = supplier_catalog_import_service.import_catalog_batch(conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None, rows=rows)
            self.assertEqual((result["rejected"],result["queued_for_review"],result["matched"]), (7,1,0))
            current = supplier_service.get_offer(conn, offer_id=offer["id"])
            self.assertEqual((current["selling_price_minor"],current["stock_quantity"],current["stock_reserved"]), (100,10,5))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM offer_price_history WHERE offer_id=?", (offer["id"],)).fetchone()[0], 0)
            result = supplier_catalog_import_service.import_catalog_batch(conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None, rows=[{"barcode":"shape-barcode", "selling_price_minor":"9007199254740995", "stock_quantity":"۱۲"}])
            self.assertEqual(result["matched"],1)
            current = supplier_service.get_offer(conn, offer_id=offer["id"])
            self.assertEqual((current["selling_price_minor"],current["stock_quantity"]),(9007199254740995,12))
            self.assertEqual(conn.execute("SELECT new_price_minor FROM offer_price_history WHERE offer_id=?", (offer["id"],)).fetchone()[0],9007199254740995)

    def test_batch_shape_and_signed_zero(self):
        with self.db.write_transaction() as conn:
            with self.assertRaises(ValidationError):
                supplier_catalog_import_service.import_catalog_batch(conn,supplier_id=1,supplier_location_id=1,submitted_by_user_id=None,rows={"bad":"shape"})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_catalog_import_batches").fetchone()[0],0)
        self.assertEqual(supplier_service.exact_nonnegative_integer("-0","test"),0)

    def test_import_http_requires_object_body(self):
        supplier = self.create_test_supplier()
        for body in ([1], "invalid", 123, None, True):
            with self.subTest(body=body):
                response = self.client.post("/api/v1/supplier/catalog/import", json=body, headers=supplier["headers"])
                self.assertEqual(response.status_code,422)
        with self.db.read_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM supplier_catalog_import_batches WHERE supplier_id=?",(supplier["supplier_id"],)).fetchone()[0],0)
