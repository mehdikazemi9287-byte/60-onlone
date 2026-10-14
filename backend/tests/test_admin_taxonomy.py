"""Taxonomy lifecycle and preservation against the existing derivation/import pipeline."""
from tests.base import AppTestCase
from app.services.catalog_structure_service import _node,apply
from app.services.catalog_bulk_import_service import _upsert_category
class TaxonomyTests(AppTestCase):
 def setUp(self):super().setUp();self.h=self.admin_headers()
 def create(self,slug='test-root',level='department',parent=None):
  r=self.client.post('/api/v1/admin/catalog/categories',headers=self.h,json={'slug':slug,'name_fa':'[TEST ONLY] taxonomy','level':level,'parent_id':parent,'sort_order':2,'reason':'TEST ONLY create'})
  self.assertEqual(r.status_code,201,r.get_json());return r.get_json()['category']
 def patch(self,p,**changes):
  d={'name_fa':'[TEST ONLY] renamed','parent_id':p['parent_id'],'sort_order':3,'expected_version':p['admin_row_version'],'reason':'TEST ONLY edit'};d.update(changes)
  return self.client.patch('/api/v1/admin/catalog/categories/'+str(p['id']),headers=self.h,json=d)
 def test_role_validation_and_slug_immutability(self):
  _,h=self.new_customer();self.assertEqual(self.client.get('/api/v1/admin/catalog/categories',headers=h).status_code,403)
  p=self.create();self.assertEqual(self.patch(p,slug='changed-identity').status_code,422)
  self.assertEqual(self.patch(p,sort_order=True).status_code,422)
  self.assertEqual(self.client.post('/api/v1/admin/catalog/categories',headers=self.h,json={'slug':'test-root','name_fa':'TEST','level':'department','reason':'TEST'}).status_code,409)
 def test_concurrency_external_change_and_parent_level(self):
  p=self.create();r=self.patch(p);self.assertEqual(r.status_code,200,r.get_json());new=r.get_json()['category'];self.assertGreater(new['admin_row_version'],p['admin_row_version']);self.assertEqual(self.patch(p).status_code,409)
  child=self.create('test-child','category',p['id']);self.assertEqual(self.patch(new,parent_id=child['id']).status_code,422)
  with self.db.write_transaction() as c:c.execute('UPDATE categories SET name_fa=? WHERE id=?',('TEST ONLY external',p['id']))
  self.assertEqual(self.patch(new).status_code,409)
 def test_manual_names_survive_automatic_node_and_bulk_import(self):
  p=self.create();p=self.patch(p).get_json()['category']
  with self.db.write_transaction() as c:
   self.assertEqual(_node(c,p['slug'],'TEST automatic',None,'department'),p['id'])
   self.assertEqual(_upsert_category(c,{'category_slug':p['slug'],'category_name_fa':'TEST importer'}),p['id'])
   after=dict(c.execute('SELECT * FROM categories WHERE id=?',(p['id'],)).fetchone())
  self.assertEqual(after['name_fa'],p['name_fa']);self.assertEqual(after['admin_row_version'],p['admin_row_version'])
 def test_managed_category_parent_survives_structure_apply(self):
  root=self.create();
  with self.db.write_transaction() as c:
   existing=c.execute("SELECT id FROM categories WHERE slug='office-org'").fetchone()
   if existing:c.execute('UPDATE categories SET parent_id=?,admin_managed=1 WHERE id=?',(root['id'],existing['id']));cid=existing['id']
   else:cid=c.execute("INSERT INTO categories(slug,name_fa,level,parent_id,admin_managed) VALUES ('office-org','TEST ONLY','category',?,1)",(root['id'],)).lastrowid
   apply(c,create_skus=False);self.assertEqual(c.execute('SELECT parent_id FROM categories WHERE id=?',(cid,)).fetchone()[0],root['id'])
 def test_automatic_unmanaged_nodes_keep_existing_behavior(self):
  with self.db.write_transaction() as c:
   cid=_node(c,'test-auto','TEST first',None,'department');_node(c,'test-auto','TEST second',None,'department')
   r=c.execute('SELECT name_fa,admin_managed,admin_row_version FROM categories WHERE id=?',(cid,)).fetchone()
   self.assertEqual(r['name_fa'],'TEST second');self.assertEqual(r['admin_managed'],0);self.assertGreater(r['admin_row_version'],1)
 def test_brands_are_existing_real_master_values_not_invented_registry(self):
  r=self.client.get('/api/v1/admin/catalog/brands',headers=self.h);self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(r.get_json()['source'],'master_products.brand');self.assertEqual(r.headers['Cache-Control'],'no-store')

 def test_existing_corrupt_ancestor_cycle_is_rejected(self):
  root=self.create();child=self.create('test-cycle-child','category',root['id'])
  with self.db.write_transaction() as c:c.execute('UPDATE categories SET parent_id=? WHERE id=?',(child['id'],root['id']))
  self.assertEqual(self.patch(child).status_code,422)
