from tests.base import AppTestCase
from app.services import master_catalog_service as master
from app.core.errors import ValidationError

class MasterCreationInputTest(AppTestCase):
    def test_http_invalid_types_do_not_create_master_or_family(self):
        with self.db.read_transaction() as c:
            count=c.execute('SELECT COUNT(*) FROM master_products').fetchone()[0]
            families=c.execute('SELECT COUNT(*) FROM product_families').fetchone()[0]
        cases=[None,[1],{'canonical_name_fa':123},{'canonical_name_fa':'[TEST] New','vat_rate_bps':True},{'canonical_name_fa':'[TEST] New','vat_rate_bps':900.5},{'canonical_name_fa':'[TEST] New','vat_rate_bps':'900'},{'canonical_name_fa':'[TEST] New','vat_rate_bps':2**63},{'canonical_name_fa':'[TEST] New','vat_applicable':1},{'canonical_name_fa':'[TEST] New','vat_applicable':'false'},{'canonical_name_fa':'[TEST] New','package_quantity':2**63}]
        for payload in cases:
            with self.subTest(payload=payload):
                response=self.client.post('/api/v1/admin/catalog/products',json=payload,headers=self.admin_headers())
                self.assertEqual(response.status_code,422,response.get_json())
        with self.db.read_transaction() as c:
            self.assertEqual(count,c.execute('SELECT COUNT(*) FROM master_products').fetchone()[0])
            self.assertEqual(families,c.execute('SELECT COUNT(*) FROM product_families').fetchone()[0])

    def test_service_rejects_lossy_values_and_preserves_explicit_and_default_tax_values(self):
        with self.db.write_transaction() as c:
            for fields in ({'vat_rate_bps':False},{'vat_rate_bps':1.0},{'vat_rate_bps':-1},{'vat_rate_bps':2**63},{'vat_applicable':0},{'vat_applicable':'true'},{'package_quantity':2**63}):
                with self.subTest(fields=fields),self.assertRaises(ValidationError):master.create_master_product(c,canonical_name_fa='[TEST] Invalid',**fields)
            row=master.create_master_product(c,canonical_name_fa='[TEST] Explicit',vat_applicable=False,vat_rate_bps=0,package_quantity=2)
            stored=c.execute('SELECT vat_applicable,vat_rate_bps,package_quantity FROM master_products WHERE id=?',(row['id'],)).fetchone()
            self.assertEqual(tuple(stored),(0,0,2))
            row=master.create_master_product(c,canonical_name_fa='[TEST] Existing default')
            self.assertEqual(tuple(c.execute('SELECT vat_applicable,vat_rate_bps FROM master_products WHERE id=?',(row['id'],)).fetchone()),(1,900))
