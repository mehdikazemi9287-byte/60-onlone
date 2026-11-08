"""Delta integration checks against a private disposable candidate copy.
No seed, Production writes, test-sales override or fabricated catalog fixtures.
Synthetic users/organizations/requests are confined to the disposable copy.
"""
import json,os,secrets,sqlite3,tempfile,unittest
from pathlib import Path
from app.main import create_app
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ValidationError
from app.services import master_catalog_service as masters
from app.services.catalog_bulk_import_service import parse_catalog_csv

ROOT=Path(__file__).resolve().parents[2]

class NullableCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidate=ROOT/'data/catalog-import-20261006/candidate.db'
        if not candidate.exists():raise unittest.SkipTest('Private import candidate required')
        cls.tmp=tempfile.TemporaryDirectory(prefix='60online-nullable-test-')
        cls.path=Path(cls.tmp.name)/'qa.db'
        source=sqlite3.connect('file:'+str(candidate)+'?mode=ro',uri=True)
        target=sqlite3.connect(cls.path);source.backup(target);source.close();target.close();os.chmod(cls.path,0o600)
        cls.db=Database(str(cls.path));cls.app=create_app(Settings(secret_key=secrets.token_hex(32),database_url='sqlite:///'+str(cls.path),app_env='development',seed_on_start=False),cls.db)
        cls.client=cls.app.test_client()
        r=cls.client.post('/api/v1/auth/register',json={'email':'synthetic-nullable-qa@example.invalid','password':secrets.token_hex(24),'full_name':'SYNTHETIC NULLABLE QA'})
        assert r.status_code==201,r.json
        cls.uid=r.json['user']['id'];cls.headers={'Authorization':'Bearer '+r.json['access_token']}
        with cls.db.write_transaction() as c:
            cls.oid=c.execute("INSERT INTO organizations(legal_name,display_name,national_id,status,provenance) VALUES('SYNTHETIC QA','SYNTHETIC QA','SYNTHETIC-NULLABLE-QA','active','test')").lastrowid
            c.execute("INSERT INTO organization_memberships(organization_id,user_id,role,status) VALUES(?,?,'organization_admin','active')",(cls.oid,cls.uid))
    @classmethod
    def tearDownClass(cls):cls.db.close();cls.tmp.cleanup()

    def test_nullable_validation_and_preserved_values(self):
        with self.db.read_transaction() as c:
            info={r['name']:r for r in c.execute('PRAGMA table_info(master_products)')}
            for key in ('unit','package_quantity'):
                self.assertEqual(info[key]['notnull'],0);self.assertIsNone(info[key]['dflt_value'])
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0],'ok')
            old=sqlite3.connect('file:'+str(ROOT/'data/catalog-import-20261006/before-nullable.db')+'?mode=ro',uri=True)
            for row in old.execute('SELECT * FROM master_products'):
                self.assertEqual(tuple(c.execute('SELECT * FROM master_products WHERE id=?',(row[0],)).fetchone()),tuple(row))
            old.close()
        with self.db.write_transaction() as c:
            c.execute('SAVEPOINT synthetic_master_validation')
            product=masters.create_master_product(c,canonical_name_fa='SYNTHETIC QA NULL')
            self.assertIsNone(product['unit']);self.assertIsNone(product['package_quantity'])
            for pack in (0,-1,True,'1',1.5):
                with self.assertRaises(ValidationError):masters.create_master_product(c,canonical_name_fa='SYNTHETIC QA',package_quantity=pack)
            for unit in ('',False,123):
                with self.assertRaises(ValidationError):masters.create_master_product(c,canonical_name_fa='SYNTHETIC QA',unit=unit)
            c.execute('ROLLBACK TO synthetic_master_validation');c.execute('RELEASE synthetic_master_validation')
        parsed=parse_catalog_csv('canonical_name_fa,category_slug\nSYNTHETIC QA,books-stationery\n')
        self.assertIsNone(parsed['rows'][0]['data']['package_quantity'])

    def test_staged_completion_selection_and_prices(self):
        with self.db.read_transaction() as c:
            mappings=c.execute("SELECT * FROM external_product_mappings WHERE external_identifier_type='PDF_CATALOG'").fetchall()
            self.assertEqual(len(mappings),401)
            pending=[r['external_identifier_value'] for r in mappings if r['master_product_id'] is None]
            self.assertEqual(pending,['آریا:sku:9030'])
            self.assertEqual(len({r['master_product_id'] for r in mappings if r['master_product_id'] is not None}),400)
            self.assertEqual(sum(s['price'] is not None for r in mappings for s in json.loads(r['external_metadata_json'])['sources']),176)
            for r in mappings:
                if r['master_product_id'] is None:continue
                product=c.execute('SELECT * FROM master_products WHERE id=?',(r['master_product_id'],)).fetchone()
                pub=c.execute('SELECT * FROM catalog_publications WHERE master_product_id=?',(r['master_product_id'],)).fetchone()
                self.assertIsNone(pub['verified_price_minor']);self.assertEqual(pub['is_purchasable'],0)
                if r['external_identifier_value'].startswith('پویا پروتئین:'):
                    self.assertIsNone(product['unit']);self.assertIsNone(product['package_quantity'])
                response=self.client.get('/api/v1/products/'+pub['slug']);self.assertEqual(response.status_code,200)
                self.assertIsNone(response.json['product']['price']);self.assertIsNone(response.json['product']['quantity_available']);self.assertFalse(response.json['product']['purchasable'])
        for supplier,expected in [('آریا',233),('پویا پروتئین',167)]:
            response=self.client.get('/api/v1/catalog/selection',query_string={'supplier':supplier,'page_size':48});self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['total'],expected);ids=[]
            for page in range(1,response.json['total_pages']+1):
                items=self.client.get('/api/v1/catalog/selection',query_string={'supplier':supplier,'page_size':48,'page':page}).json['items'];ids.extend(p['id'] for p in items)
                self.assertTrue(all(p['purchasable'] is False and p['price'] is None and p['stock'] is None for p in items))
            self.assertEqual(len(ids),len(set(ids)))
        response=self.client.get('/api/v1/catalog/selection?supplier=آریا&q=8033');self.assertEqual(response.json['total'],1)
        self.assertEqual(self.client.get('/api/v1/catalog/selection?category=protein-fresh--poultry&supplier=پویا پروتئین').json['total'],62)
        self.assertEqual(self.client.get('/api/v1/catalog/selection?page=bad').status_code,422)
        self.assertEqual(self.client.get('/api/v1/catalog/selection?page_size=49').status_code,422)

    def test_request_to_rfq_null_unit_end_to_end(self):
        chosen=self.client.get('/api/v1/catalog/selection?supplier=پویا پروتئین').json['items'][0]
        base=f'/api/v1/orgs/{self.oid}/procurement/'
        body={'title':'SYNTHETIC RFQ QA','items':[{'master_product_id':chosen['id'],'quantity':3,'unit':None,'estimated_unit_price_minor':None}]}
        headers={**self.headers,'Idempotency-Key':'synthetic-nullable-request'}
        r=self.client.post(base+'requests',json=body,headers=headers);self.assertEqual(r.status_code,201,r.json)
        request=r.json['purchase_request'];self.assertIsNone(request['items'][0]['unit']);self.assertIsNone(request['items'][0]['estimated_unit_price_minor'])
        replay=self.client.post(base+'requests',json=body,headers=headers);self.assertEqual(replay.status_code,200,replay.json)
        pid=request['id']
        for op,data in [('submit',{}),('approve',{'action':'approve'})]:
            r=self.client.post(base+f'requests/{pid}/{op}',json=data,headers=self.headers);self.assertEqual(r.status_code,200,r.json)
        r=self.client.post(base+'rfqs',json={'purchase_request_id':pid,'title':'SYNTHETIC QUOTE REQUEST'},headers=self.headers);self.assertEqual(r.status_code,201,r.json)
        rfq=r.json['rfq'];self.assertEqual(rfq['items'][0]['master_product_id'],chosen['id']);self.assertIsNone(rfq['items'][0]['unit']);self.assertEqual(rfq['items'][0]['quantity'],3)
        self.assertEqual(self.client.get(base+f"rfqs/{rfq['id']}",headers=self.headers).status_code,200)
        bad=self.client.post('/api/v1/cart/items',json={'product_id':-chosen['id'],'quantity':1},headers=self.headers)
        self.assertIn(bad.status_code,(404,422))
        unauthorized=self.client.get(base+'requests');self.assertEqual(unauthorized.status_code,401)
