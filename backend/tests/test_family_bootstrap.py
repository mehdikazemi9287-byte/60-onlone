from tests.base import AppTestCase
from app.services import master_catalog_service as master, catalog_structure_service as structure

class FamilyBootstrapTest(AppTestCase):
    def test_bootstrap_only_changes_legacy_group_key_and_is_repeatable(self):
        with self.db.write_transaction() as c:
            m=master.create_master_product(c,canonical_name_fa="[TEST] Bootstrap 100 گرم",brand="[TEST] Brand",category="mobile")
            fid=c.execute("INSERT INTO product_families(slug,title_fa,brand) VALUES ('test-bootstrap','[TEST] Original title','[TEST] Brand')").lastrowid
            c.execute("UPDATE master_products SET provenance='real',family_id=? WHERE id=?",(fid,m['id']))
            tables=('categories','products','master_products','catalog_publications','seller_offers','offer_price_history')
            before={t:[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY id' if t!='catalog_publications' else f'SELECT * FROM {t} ORDER BY master_product_id')] for t in tables}
            family_before=dict(c.execute('SELECT * FROM product_families WHERE id=?',(fid,)).fetchone())
            structure.initialize_family_keys(c)
            family_after=dict(c.execute('SELECT * FROM product_families WHERE id=?',(fid,)).fetchone())
            self.assertTrue(family_after['grouping_key'])
            self.assertEqual({k:v for k,v in family_before.items() if k!='grouping_key'},{k:v for k,v in family_after.items() if k!='grouping_key'})
            structure.initialize_family_keys(c)
            self.assertEqual(family_after,dict(c.execute('SELECT * FROM product_families WHERE id=?',(fid,)).fetchone()))
            for t in tables:
                self.assertEqual(before[t],[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY id' if t!='catalog_publications' else f'SELECT * FROM {t} ORDER BY master_product_id')],t)
