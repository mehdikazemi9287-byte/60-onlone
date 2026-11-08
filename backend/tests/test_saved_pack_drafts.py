import uuid,json
from tests.base import AppTestCase
from tests import test_product_management_e2e as helper_module
class SavedPackDraftTest(AppTestCase):
 create=helper_module.ProductManagementTest.create
 fixture=helper_module.ProductManagementTest.fixture
 def setUp(self):
  super().setUp();self.headers=self.admin_headers();self.app.config['TEST_SALES_OVERRIDE']=False;self.app.config['COMMERCE_TEST_MODE']=True
  mid,_=self.create();self.sku,_=self.fixture(mid);_,self.owner=self.new_customer();_,self.other=self.new_customer()
  self.payload={'title':'[TEST ONLY] saved real-catalogue draft','organization_id':None,'count':4,'items':[{'slug':self.sku['slug'],'quantity':2}],'request_key':uuid.uuid4().hex}
 def test_personal_create_edit_cas_replay_and_private_audit(self):
  r=self.client.post('/api/v1/me/pack-drafts',json=self.payload,headers=self.owner);self.assertEqual(r.status_code,201,r.get_json());p=r.get_json()['pack'];path='/api/v1/me/pack-drafts/'+str(p['id'])
  self.assertEqual(self.client.post('/api/v1/me/pack-drafts',json=self.payload,headers=self.owner).get_json()['pack']['id'],p['id'])
  self.assertEqual(self.client.get(path,headers=self.other).status_code,403)
  changed={**self.payload,'count':5,'expected_version':p['row_version']};changed.pop('request_key');r=self.client.patch(path,json=changed,headers=self.owner);self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(r.get_json()['pack']['draft']['count'],5)
  self.assertEqual(self.client.patch(path,json=changed,headers=self.owner).status_code,409)
  with self.db.read_transaction() as c:
   events=c.execute("select action,metadata_json from audit_logs where entity_type='pack_draft' and entity_id=? order by id",(str(p['id']),)).fetchall();self.assertEqual(len(events),2);self.assertNotIn('price',events[0]['metadata_json'])
 def test_archive_restore_and_retry_after_product_inactivated(self):
  p=self.client.post('/api/v1/me/pack-drafts',json=self.payload,headers=self.owner).get_json()['pack'];path='/api/v1/me/pack-drafts/'+str(p['id'])
  with self.db.write_transaction() as c:c.execute('update products set is_active=0 where id=?',(self.sku['product_id'],))
  r=self.client.post('/api/v1/me/pack-drafts',json=self.payload,headers=self.owner);self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['replayed'])
  for status in ('archived','draft'):
   r=self.client.patch(path,json={'status':status,'expected_version':p['row_version']},headers=self.owner);self.assertEqual(r.status_code,200,r.get_json());p=r.get_json()['pack']
  self.assertEqual(self.client.get('/api/v1/me/pack-drafts',headers=self.owner).get_json()['total'],1)
  self.assertEqual(self.client.get('/api/v1/me/pack-drafts?page='+('9'*80),headers=self.owner).status_code,422)
 def test_org_scope_foreign_member_and_fabricated_money_rejected(self):
  org=self.create_organization(name='[TEST ONLY] pack organization');org_headers,member=self.make_org_admin(org['id']);payload={**self.payload,'organization_id':org['id']}
  r=self.client.post('/api/v1/me/pack-drafts',json=payload,headers=org_headers);self.assertEqual(r.status_code,201,r.get_json());p=r.get_json()['pack'];path='/api/v1/me/pack-drafts/'+str(p['id'])
  self.assertEqual(self.client.get(path,headers=self.other).status_code,403)
  self.assertEqual(self.client.post('/api/v1/me/pack-drafts',json={**self.payload,'selling_price_minor':0},headers=self.owner).status_code,422)
  self.assertEqual(self.client.post('/api/v1/me/pack-drafts',json={**self.payload,'items':self.payload['items']*2},headers=self.owner).status_code,422)
  with self.db.write_transaction() as c:c.execute("update organization_memberships set status='inactive' where organization_id=? and user_id=?",(org['id'],member['user_id']))
  self.assertEqual(self.client.get(path,headers=org_headers).status_code,403)
