from tests.base import AppTestCase
from app.services import master_catalog_service as master, catalog_structure_service as structure

class LegacyFamilyAllocationTest(AppTestCase):
    def make(self,c,name='[TEST] Legacy 100 گرم',brand='[TEST] Brand'):
        m=master.create_master_product(c,canonical_name_fa=name,brand=brand,category='mobile')
        c.execute("UPDATE master_products SET provenance='real' WHERE id=?",(m['id'],))
        return m

    def family(self,c,slug,provenance='real'):
        return c.execute("INSERT INTO product_families(slug,title_fa,brand,provenance) VALUES (?,?,?,?)",(slug,'[TEST] Legacy','[TEST] Brand',provenance)).lastrowid

    def test_legacy_duplicate_group_retains_rows_and_chooses_stable_family(self):
        with self.db.write_transaction() as c:
            a=self.make(c);b=self.make(c,'[TEST] Legacy 200 گرم')
            fa=self.family(c,'legacy-a');fb=self.family(c,'legacy-b')
            c.execute('UPDATE master_products SET family_id=? WHERE id=?',(fa,a['id']))
            c.execute('UPDATE master_products SET family_id=? WHERE id=?',(fb,b['id']))
            structure.apply(c,create_skus=False)
            self.assertEqual([r[0] for r in c.execute('SELECT family_id FROM master_products WHERE id IN (?,?) ORDER BY id',(a['id'],b['id']))],[fa,fa])
            self.assertEqual(c.execute('SELECT slug FROM product_families WHERE id=?',(fb,)).fetchone()[0],'legacy-b')
            self.assertIsNone(c.execute('SELECT grouping_key FROM product_families WHERE id=?',(fb,)).fetchone()[0])
            before=[tuple(r) for r in c.execute('SELECT id,slug,grouping_key FROM product_families ORDER BY id')]
            structure.apply(c,create_skus=False)
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT id,slug,grouping_key FROM product_families ORDER BY id')])

    def test_nonreal_slug_collision_not_adopted_or_overwritten(self):
        with self.db.write_transaction() as c:
            a=self.make(c)
            slug='f-'+a['public_product_id'];old=self.family(c,slug,'demo')
            c.execute('UPDATE master_products SET family_id=? WHERE id=?',(old,a['id']))
            before=tuple(c.execute('SELECT slug,title_fa,brand,provenance,status,grouping_key FROM product_families WHERE id=?',(old,)).fetchone())
            structure.apply(c,create_skus=False)
            new=c.execute('SELECT family_id FROM master_products WHERE id=?',(a['id'],)).fetchone()[0]
            self.assertNotEqual(new,old)
            self.assertEqual(before,tuple(c.execute('SELECT slug,title_fa,brand,provenance,status,grouping_key FROM product_families WHERE id=?',(old,)).fetchone()))
            newslug=c.execute('SELECT slug FROM product_families WHERE id=?',(new,)).fetchone()[0]
            self.assertTrue(newslug.startswith(slug+'-'))
            structure.apply(c,create_skus=False)
            self.assertEqual(c.execute('SELECT family_id FROM master_products WHERE id=?',(a['id'],)).fetchone()[0],new)

    def test_split_legacy_majority_retains_family_and_archive_state(self):
        with self.db.write_transaction() as c:
            a=self.make(c,brand='[TEST] Moved');b=self.make(c);d=self.make(c,'[TEST] Legacy 200 گرم')
            old=self.family(c,'legacy-majority')
            c.execute("UPDATE product_families SET status='archived' WHERE id=?",(old,))
            c.execute('UPDATE master_products SET family_id=? WHERE id IN (?,?,?)',(old,a['id'],b['id'],d['id']))
            structure.apply(c,create_skus=False)
            self.assertNotEqual(c.execute('SELECT family_id FROM master_products WHERE id=?',(a['id'],)).fetchone()[0],old)
            for mid in (b['id'],d['id']):self.assertEqual(c.execute('SELECT family_id FROM master_products WHERE id=?',(mid,)).fetchone()[0],old)
            self.assertEqual(c.execute('SELECT status,slug FROM product_families WHERE id=?',(old,)).fetchone()[0],'archived')
