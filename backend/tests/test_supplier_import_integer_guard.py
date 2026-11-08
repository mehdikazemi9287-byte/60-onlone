from tests.test_supplier_marketplace_phase2_3 import _Base
from app.services import supplier_service, supplier_catalog_import_service
from app.core.errors import ValidationError

class SupplierImportIntegerGuardTest(_Base):
    def test_exact_parser_rejects_lossy_values(self):
        for value in (True, False, 1.0, 1.7, "1.7", "", None, -1, 2**63):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                supplier_service.exact_nonnegative_integer(value, "test")
        self.assertEqual(supplier_service.exact_nonnegative_integer("9007199254740995", "test"), 9007199254740995)
        self.assertEqual(supplier_service.exact_nonnegative_integer("۱۲۳", "test"), 123)

    def test_invalid_import_rows_do_not_queue_or_change_offer(self):
        with self.db.write_transaction() as conn:
            pid = self._product_id(conn, "mobile-samsung-a55")
            sup = self._make_supplier(conn, nat_id="GUARD-001", name="Guard")
            loc = self._make_location(conn, supplier_id=sup)
            conn.execute("INSERT INTO product_identifiers (product_id,identifier_type,identifier_value) VALUES (?,'EAN','guard-barcode')", (pid,))
            offer = supplier_service.create_offer(conn, product_id=pid, supplier_id=sup, supplier_location_id=loc, selling_price_minor=100, stock_quantity=10)
            rows = [{"barcode":"guard-barcode", "selling_price_minor": value, "stock_quantity": 5} for value in (True, 1.7, 2**63)]
            rows += [{"barcode":"guard-barcode", "selling_price_minor": 200, "stock_quantity": value} for value in (False, 1.0, -1)]
            result = supplier_catalog_import_service.import_catalog_batch(conn, supplier_id=sup, supplier_location_id=loc, submitted_by_user_id=None, rows=rows)
            self.assertEqual(result["rejected"], 6)
            self.assertEqual(result["matched"], 0)
            self.assertEqual(result["queued_for_review"], 0)
            current = supplier_service.get_offer(conn, offer_id=offer["id"])
            self.assertEqual((current["selling_price_minor"], current["stock_quantity"]), (100,10))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM offer_price_history WHERE offer_id=?", (offer["id"],)).fetchone()[0], 0)
            for value in (True, 1.5, 2**63):
                with self.assertRaises(ValidationError):
                    supplier_service.update_offer_price(conn, offer_id=offer["id"], supplier_id=sup, selling_price_minor=value)
                with self.assertRaises(ValidationError):
                    supplier_service.update_offer_stock(conn, offer_id=offer["id"], supplier_id=sup, stock_quantity=value)
