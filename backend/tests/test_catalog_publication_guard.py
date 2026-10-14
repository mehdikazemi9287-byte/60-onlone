from tests.base import AppTestCase
from app.services import master_catalog_service as master, catalog_structure_service as structure
from app.core.errors import ConflictError

class CatalogPublicationGuardTest(AppTestCase):
    def make_master(self, conn):
        row = master.create_master_product(conn,canonical_name_fa="[TEST ONLY] Guard",brand="Guard",category="mobile",image_urls=["/test-only.png"])
        conn.execute("UPDATE master_products SET provenance='real' WHERE id=?",(row["id"],))
        return row["id"]

    def test_malformed_images_cannot_publish_but_can_hide(self):
        with self.db.write_transaction() as conn:
            mid = self.make_master(conn)
            for raw in ('broken-json', '{}', '"image"', '[null,123,false]', '["", "  "]'):
                conn.execute("UPDATE master_products SET image_urls_json=? WHERE id=?",(raw,mid))
                with self.subTest(raw=raw), self.assertRaises(ConflictError):
                    structure.set_visibility(conn,master_product_id=mid,visible=True,reason="test review")
                self.assertIsNone(conn.execute("SELECT 1 FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone())
            hidden = structure.set_visibility(conn,master_product_id=mid,visible=False,reason="test hide")
            self.assertFalse(hidden["visible"])
            self.assertEqual(conn.execute("SELECT is_visible FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone()[0],0)
            conn.execute("UPDATE master_products SET image_urls_json='[\"/test-only.png\"]' WHERE id=?",(mid,))
            structure.set_visibility(conn,master_product_id=mid,visible=True,reason="test valid reference")
            self.assertEqual(conn.execute("SELECT is_visible FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone()[0],1)

    def test_merged_master_is_not_publishable(self):
        with self.db.write_transaction() as conn:
            mid = self.make_master(conn)
            conn.execute("UPDATE master_products SET status='merged' WHERE id=?",(mid,))
            review = next(row for row in structure.review_queue(conn) if row["master_product_id"]==mid)
            self.assertFalse(review["publishable"])
            with self.assertRaises(ConflictError):
                structure.set_visibility(conn,master_product_id=mid,visible=True,reason="test merged")
            self.assertIsNone(conn.execute("SELECT 1 FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone())
            structure.set_visibility(conn,master_product_id=mid,visible=False,reason="test hide merged")
            self.assertEqual(conn.execute("SELECT is_visible FROM catalog_publications WHERE master_product_id=?",(mid,)).fetchone()[0],0)
