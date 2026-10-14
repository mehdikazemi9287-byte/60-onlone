from tests.base import AppTestCase
from app.services import master_catalog_service as master, catalog_structure_service as structure

class StableFamilyGroupingTest(AppTestCase):
    def make(self,c,name):
        m=master.create_master_product(c,canonical_name_fa=name,brand="[TEST] Old",category="mobile")
        c.execute("UPDATE master_products SET provenance='real' WHERE id=?",(m["id"],))
        return m["id"]

    def test_moving_first_variant_preserves_old_family_and_repeat_is_stable(self):
        with self.db.write_transaction() as c:
            first=self.make(c,"[TEST] Model 100 گرم")
            second=self.make(c,"[TEST] Model 200 گرم")
            structure.apply(c,create_skus=False)
            original=c.execute("SELECT family_id FROM master_products WHERE id=?",(first,)).fetchone()[0]
            self.assertEqual(c.execute("SELECT family_id FROM master_products WHERE id=?",(second,)).fetchone()[0],original)
            slug=c.execute("SELECT slug FROM product_families WHERE id=?",(original,)).fetchone()[0]
            c.execute("UPDATE master_products SET brand='[TEST] New' WHERE id=?",(first,))
            structure.apply(c,create_skus=False)
            changed=c.execute("SELECT family_id FROM master_products WHERE id=?",(first,)).fetchone()[0]
            self.assertNotEqual(changed,original)
            self.assertEqual(c.execute("SELECT family_id FROM master_products WHERE id=?",(second,)).fetchone()[0],original)
            self.assertEqual(c.execute("SELECT slug FROM product_families WHERE id=?",(original,)).fetchone()[0],slug)
            before=[tuple(row) for row in c.execute("SELECT id,slug,grouping_key FROM product_families ORDER BY id")]
            structure.apply(c,create_skus=False)
            self.assertEqual(before,[tuple(row) for row in c.execute("SELECT id,slug,grouping_key FROM product_families ORDER BY id")])
            c.execute("UPDATE master_products SET brand='[TEST] Old' WHERE id=?",(first,))
            structure.apply(c,create_skus=False)
            self.assertEqual(c.execute("SELECT family_id FROM master_products WHERE id=?",(first,)).fetchone()[0],original)
