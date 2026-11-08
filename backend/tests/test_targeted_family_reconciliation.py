from tests.base import AppTestCase
from app.services import master_catalog_service as master, catalog_structure_service as structure
from app.core.errors import ValidationError

class TargetedFamilyReconciliationTest(AppTestCase):
    def make(self,c,name,brand):
        m=master.create_master_product(c,canonical_name_fa=name,brand=brand,category="mobile")
        c.execute("UPDATE master_products SET provenance='real' WHERE id=?",(m['id'],))
        return m['id']

    def test_targeted_move_preserves_unrelated_records_and_existing_skus(self):
        with self.db.write_transaction() as c:
            a=self.make(c,'[TEST] Item 100 گرم','[TEST] Old')
            b=self.make(c,'[TEST] Item 200 گرم','[TEST] Old')
            other=self.make(c,'[TEST] Other','[TEST] Other')
            structure.apply(c)
            def row(mid):return c.execute('SELECT * FROM master_products WHERE id=?',(mid,)).fetchone()
            oldkey=structure.family_group_key(row(a));oldfamily=row(a)['family_id']
            untouched=tuple(row(other));fid=row(other)['family_id']
            family=tuple(c.execute('SELECT * FROM product_families WHERE id=?',(fid,)).fetchone())
            skus=[tuple(r) for r in c.execute('SELECT * FROM products ORDER BY id')]
            categories=[tuple(r) for r in c.execute('SELECT * FROM categories ORDER BY id')]
            structure.initialize_family_keys(c)
            c.execute("UPDATE master_products SET brand='[TEST] New' WHERE id=?",(a,))
            newkey=structure.family_group_key(row(a))
            result=structure.reconcile_family_groups(c,{oldkey,newkey})
            self.assertEqual(result['families'],2)
            self.assertNotEqual(row(a)['family_id'],oldfamily)
            self.assertEqual(row(b)['family_id'],oldfamily)
            self.assertEqual(tuple(row(other)),untouched)
            self.assertEqual(tuple(c.execute('SELECT * FROM product_families WHERE id=?',(fid,)).fetchone()),family)
            self.assertEqual(skus,[tuple(r) for r in c.execute('SELECT * FROM products ORDER BY id')])
            self.assertEqual(categories,[tuple(r) for r in c.execute('SELECT * FROM categories ORDER BY id')])

    def test_empty_target_does_not_trigger_global_rebuild(self):
        with self.db.write_transaction() as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM categories ORDER BY id')]
            self.assertEqual(structure.reconcile_family_groups(c,set())['families'],0)
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM categories ORDER BY id')])
            with self.assertRaises(ValidationError):structure.reconcile_family_groups(c,None)
