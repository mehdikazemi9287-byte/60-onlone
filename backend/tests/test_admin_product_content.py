from tests.base import AppTestCase
class ProductContentTests(AppTestCase):
 def setUp(self):
  super().setUp();self.h=self.admin_headers()
  r=self.client.post('/api/v1/admin/catalog/products',headers=self.h,json={'canonical_name_fa':'[TEST ONLY] content master','unit':'عدد'});self.assertEqual(r.status_code,201,r.get_json());self.assertIn('provenance',r.get_json());self.mid=r.get_json()['id']
  with self.db.write_transaction() as c:
   c.execute("UPDATE master_products SET provenance='real' WHERE id=?",(self.mid,))
   self.pid=c.execute('SELECT id FROM products ORDER BY id LIMIT 1').fetchone()[0]
   c.execute('UPDATE products SET master_product_id=? WHERE id=?',(self.mid,self.pid))
  self.path='/api/v1/admin/catalog/products/'+str(self.mid)+'/editor'
 def current(self):
  r=self.client.get(self.path,headers=self.h);self.assertEqual(r.status_code,200,r.get_json());return r.get_json()['product']
 def payload(self,p,**extra):
  d={'expected_version':p['version'],'description_fa':'[TEST ONLY] edited','canonical_name_en':'TEST ONLY','country_of_origin':'TEST ONLY','specifications':{'TEST ONLY':'value'},'reason':'TEST ONLY edit','confirm_public_change':True};d.update(extra);return d
 def test_customer_denied_and_non_descriptive_fields_rejected(self):
  _,h=self.new_customer();self.assertEqual(self.client.get(self.path,headers=h).status_code,403)
  p=self.current();self.assertEqual(self.client.patch(self.path,headers=self.h,json=self.payload(p,brand='invented')).status_code,422)
 def test_public_confirmation_and_atomic_sku_sync_preserve_sale_fields(self):
  p=self.current()
  with self.db.read_transaction() as c:before=dict(c.execute('SELECT * FROM products WHERE id=?',(self.pid,)).fetchone())
  self.assertTrue(p['affects_public_content']);self.assertEqual(self.client.patch(self.path,headers=self.h,json=self.payload(p,confirm_public_change=False)).status_code,422)
  r=self.client.patch(self.path,headers=self.h,json=self.payload(p));self.assertEqual(r.status_code,200,r.get_json())
  with self.db.read_transaction() as c:
   after=dict(c.execute('SELECT * FROM products WHERE id=?',(self.pid,)).fetchone());master=c.execute('SELECT description_fa FROM master_products WHERE id=?',(self.mid,)).fetchone()[0]
  self.assertEqual(master,after['description_fa']);self.assertEqual(master,'[TEST ONLY] edited')
  public=self.client.get('/api/v1/products/'+after['slug']);self.assertEqual(public.status_code,200,public.get_json());self.assertEqual(public.get_json()['product']['description_fa'],master)
  for k in before:
   if k!='description_fa':self.assertEqual(before[k],after[k],k)
 def test_external_sku_change_invalidates_old_editor_version(self):
  p=self.current()
  with self.db.write_transaction() as c:c.execute('UPDATE products SET base_price_minor=base_price_minor+1 WHERE id=?',(self.pid,))
  self.assertEqual(self.client.patch(self.path,headers=self.h,json=self.payload(p)).status_code,409)
 def test_hidden_product_stays_hidden_and_repeated_save_is_noop(self):
  with self.db.write_transaction() as c:c.execute('UPDATE products SET is_active=0 WHERE id=?',(self.pid,))
  p=self.current();self.assertFalse(p['affects_public_content'])
  r=self.client.patch(self.path,headers=self.h,json=self.payload(p,confirm_public_change=False));self.assertEqual(r.status_code,200,r.get_json());p=r.get_json()['product']
  self.assertEqual(self.client.patch(self.path,headers=self.h,json=self.payload(p,confirm_public_change=False)).status_code,200)
  with self.db.read_transaction() as c:
   self.assertEqual(c.execute('SELECT is_active FROM products WHERE id=?',(self.pid,)).fetchone()[0],0)
   self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='catalog.content_updated'").fetchone()[0],1)

 def test_existing_structured_specifications_survive_description_edit(self):
  import json
  spec={'numeric':5,'nested':{'size':[1,2]}}
  with self.db.write_transaction() as c:c.execute('UPDATE master_products SET specifications_json=? WHERE id=?',(json.dumps(spec),self.mid))
  p=self.current();r=self.client.patch(self.path,headers=self.h,json=self.payload(p,specifications=p['specifications']))
  self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(r.get_json()['product']['specifications'],spec)
