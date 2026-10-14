"""Necessary supplier/image operator acceptance, isolated real application with synthetic fixtures."""
import json,uuid
from tests.test_product_management_e2e import ProductManagementTest
from tests.base import AppTestCase
class AdminCommerceCompletionTest(AppTestCase):
 create=ProductManagementTest.create
 read=ProductManagementTest.read
 fixture=ProductManagementTest.fixture
 edit_body=ProductManagementTest.edit_body
 patch=ProductManagementTest.patch
 def setUp(self):
  super().setUp();self.headers=self.admin_headers();self.app.config['TEST_SALES_OVERRIDE']=False;self.app.config['COMMERCE_TEST_MODE']=True
 def test_supplier_profile_cas_audit_and_commerce_preservation(self):
  mid,_=self.create();sku,supplier=self.fixture(mid);sid=supplier['supplier_id'];path=f'/api/v1/admin/suppliers/{sid}/profile'
  d=self.client.get(path,headers=self.headers).get_json();self.assertEqual(d['summary']['offers'],1)
  with self.db.read_transaction() as c:
   before={t:[tuple(x) for x in c.execute('select * from '+t)] for t in ('seller_offers','offer_price_history','inventory','products')}
  values={k:d['supplier'][k] for k in ('legal_name','display_name','phone','email','notes')};values['notes']='[TEST ONLY] revised supplier catalogue source'
  p={**values,'reason':'[TEST ONLY] source reviewed','expected_version':d['version']};r=self.client.patch(path,json=p,headers=self.headers);self.assertEqual(r.status_code,200,r.get_json())
  self.assertEqual(self.client.patch(path,json=p,headers=self.headers).status_code,409)
  after=self.client.get(path,headers=self.headers).get_json();self.assertEqual(after['supplier']['notes'],values['notes']);self.assertEqual(after['history'][0]['action'],'supplier.profile_updated');self.assertEqual(after['history'][0]['metadata']['before']['notes'],d['supplier']['notes'])
  with self.db.read_transaction() as c:self.assertEqual(before,{t:[tuple(x) for x in c.execute('select * from '+t)] for t in before})
 def test_supplier_review_obeys_existing_transitions_and_rbac(self):
  supplier=self.create_test_supplier();sid=supplier['supplier_id'];base=f'/api/v1/admin/suppliers/{sid}';d=self.client.get(base+'/profile',headers=self.headers).get_json()
  p={'expected_version':d['version'],'reason':'[TEST ONLY] operator reviewed','confirm':True,'to_stage':'approved'}
  self.assertEqual(self.client.post(base+'/review',json=p,headers=self.headers).status_code,422)
  for step in ('submitted','under_review','approved'):
   p={'expected_version':d['version'],'reason':'[TEST ONLY] '+step,'confirm':True,'to_stage':step};r=self.client.post(base+'/review',json=p,headers=self.headers);self.assertEqual(r.status_code,200,r.get_json());d=self.client.get(base+'/profile',headers=self.headers).get_json()
  self.assertEqual(d['supplier']['status'],'active');self.assertEqual(len(d['onboarding_events']),3)
  _,customer=self.new_customer();self.assertEqual(self.client.get(base+'/profile',headers=customer).status_code,403);self.assertEqual(self.client.post(base+'/review',json=p,headers=customer).status_code,403)
  with self.db.write_transaction() as c:
   admin=d['history'][0]['actor_user_id'];c.execute("update users set role='customer' where id=?",(admin,))
  self.assertEqual(self.client.get(base+'/profile',headers=self.headers).status_code,403)
 def test_supplier_creation_trace_duplicate_and_input_validation(self):
  p={'legal_name':'[TEST ONLY] manufacturer','display_name':'[TEST ONLY] manufacturer','national_id':'TEST-'+uuid.uuid4().hex,'supplier_type':'producer','notes':'[TEST ONLY] original supplied source','status':'pending'}
  r=self.client.post('/api/v1/admin/suppliers',json=p,headers=self.headers);self.assertEqual(r.status_code,201,r.get_json());sid=r.get_json()['supplier']['id']
  d=self.client.get(f'/api/v1/admin/suppliers/{sid}/profile',headers=self.headers).get_json();self.assertEqual(d['history'][0]['metadata']['after']['notes'],p['notes'])
  self.assertEqual(self.client.post('/api/v1/admin/suppliers',json=p,headers=self.headers).status_code,409)
  self.assertEqual(self.client.post('/api/v1/admin/suppliers',json=[],headers=self.headers).status_code,422)
  self.assertEqual(self.client.post('/api/v1/admin/suppliers',json={**p,'national_id':True},headers=self.headers).status_code,422)
 def test_supplier_offer_filter_and_exact_money(self):
  mid,_=self.create();one,supplier=self.fixture(mid);two,other=self.fixture(mid)
  with self.db.write_transaction() as c:c.execute('update seller_offers set selling_price_minor=? where id=?',(9007199254740993,one['offer_id']))
  r=self.client.get('/api/v1/admin/offer-review?supplier_id='+str(supplier['supplier_id']),headers=self.headers);self.assertEqual(r.status_code,200);self.assertEqual(r.get_json()['total'],1);self.assertEqual(r.get_json()['items'][0]['selling_price_minor'],'9007199254740993')
  self.assertEqual(self.client.get('/api/v1/admin/offer-review?supplier_id=-1',headers=self.headers).status_code,422)
 def test_image_queue_real_priority_and_malformed_json(self):
  a,_=self.create();b,_=self.create();c,_=self.create();d,_=self.create(status='draft');has,_=self.create()
  with self.db.write_transaction() as con:
   con.execute('insert into catalog_publications(master_product_id,slug,category_slug,publication_reason,created_at,updated_at) values(?,?,?,?,?,?)',(a,'[TEST ONLY]-'+str(a),'mobile','[TEST ONLY] reviewed','qa','qa'))
   pack=con.execute("insert into packs(slug,title_fa,kind,audience,purpose_fa,status) values(?,?,'custom','organization',?,'published')",('[TEST ONLY]'+str(b),'[TEST ONLY] pack','[TEST ONLY]')).lastrowid
   con.execute('insert into pack_items(pack_id,master_product_id,quantity) values(?,?,1)',(pack,b))
   con.execute('update master_products set image_urls_json=? where id=?',('{invalid',c));con.execute('update master_products set image_urls_json=? where id=?',('["https://example.test/verified-fixture.jpg"]',has))
  r=self.client.get('/api/v1/admin/media/image-review',headers=self.headers);self.assertEqual(r.status_code,200,r.get_json());byid={x['id']:x for x in r.get_json()['items']};self.assertEqual([byid[x]['priority'] for x in (a,b,c,d)],[1,2,3,4]);self.assertNotIn(has,byid)
 def test_image_review_cas_rbac_history_without_product_mutation(self):
  mid,p=self.create();path=f'/api/v1/admin/media/image-review/{mid}'
  with self.db.read_transaction() as c:original=tuple(c.execute('select * from master_products where id=?',(mid,)).fetchone())
  data={'outcome':'no_verified_source','checked_reference':'[TEST ONLY] matching PDF source checked; no matching licensed photo','reason':'[TEST ONLY] no exact package image','expected_version':0}
  r=self.client.patch(path,json=data,headers=self.headers);self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(self.client.patch(path,json=data,headers=self.headers).status_code,409)
  _,customer=self.new_customer();self.assertEqual(self.client.patch(path,json={**data,'expected_version':1},headers=customer).status_code,403)
  with self.db.read_transaction() as c:
   self.assertEqual(tuple(c.execute('select * from master_products where id=?',(mid,)).fetchone()),original)
   meta=json.loads(c.execute("select metadata_json from audit_logs where action='catalog.image_reviewed' and entity_id=?",(str(mid),)).fetchone()[0]);self.assertEqual(meta['after']['checked_reference'],data['checked_reference'])
