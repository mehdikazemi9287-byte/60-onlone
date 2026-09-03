from tests.base import AppTestCase
from app.services.catalog_bulk_import_service import import_catalog_csv


HEADER = "canonical_name_fa,category_slug,category_name_fa,brand,sku,price_minor,stock_quantity,publish_status\n"


class CatalogBulkImportTest(AppTestCase):
    def test_preview_does_not_write(self):
        csv_text = HEADER + "روغن مایع,supermarket,سوپرمارکت,نمونه,,,,draft\n"
        with self.db.read_transaction() as conn:
            result = import_catalog_csv(conn, csv_text)
            count = conn.execute("SELECT COUNT(*) FROM master_products WHERE canonical_name_fa='روغن مایع'").fetchone()[0]
        self.assertEqual(result["valid"], 1)
        self.assertEqual(count, 0)

    def test_draft_created_once_and_active_published(self):
        draft = HEADER + "روغن مایع,supermarket,سوپرمارکت,نمونه,OIL-001,,,draft\n"
        with self.db.write_transaction() as conn:
            first = import_catalog_csv(conn, draft, confirm=True)
            second = import_catalog_csv(conn, draft, confirm=True)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["updated"], 1)
        active = HEADER + "روغن مایع,supermarket,سوپرمارکت,نمونه,OIL-001,600000,50,active\n"
        with self.db.write_transaction() as conn:
            result = import_catalog_csv(conn, active, confirm=True)
            product = conn.execute("SELECT * FROM products WHERE sku='OIL-001'").fetchone()
            stock = conn.execute("SELECT quantity_available FROM inventory WHERE product_id=?", (product["id"],)).fetchone()[0]
        self.assertEqual(result["published"], 1)
        self.assertEqual(stock, 50)
