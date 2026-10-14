"""Exact master identity and published content safety in a disposable test database."""
from tests.test_admin_console_media import AdminConsoleMediaTests
class MediaIdentityTests(AdminConsoleMediaTests):
 def test_attach_requires_confirmation_and_preserves_existing_images(self):
  a=self.upload().get_json()['asset'];r=self.client.post('/api/v1/admin/media/'+a['id']+'/publish',headers=self.h,json={'expected_version':a['row_version'],'reason':'TEST ONLY'});self.assertEqual(r.status_code,200,r.get_json());a=r.get_json()['asset']
  r=self.client.post('/api/v1/admin/catalog/products',headers=self.h,json={'canonical_name_fa':'[TEST ONLY] exact identity product','unit':'عدد'})
  self.assertEqual(r.status_code,201,r.get_json());mid=r.get_json()['id']
  with self.db.write_transaction() as c:
   c.execute("UPDATE master_products SET provenance='real',status='active',image_urls_json='[\"https://example.test/original.png\"]' WHERE id=?",(mid,))
   stamp=c.execute('SELECT updated_at FROM master_products WHERE id=?',(mid,)).fetchone()[0]
  path='/api/v1/admin/media/'+a['id']+'/attach-to-product';payload={'master_product_id':mid,'expected_product_revision':stamp,'confirm_identity':False,'reason':'TEST ONLY','mode':'append'}
  self.assertEqual(self.client.post(path,headers=self.h,json=payload).status_code,422)
  payload['confirm_identity']=True;payload['expected_product_revision']='stale';self.assertEqual(self.client.post(path,headers=self.h,json=payload).status_code,409)
  payload['expected_product_revision']=stamp;r=self.client.post(path,headers=self.h,json=payload);self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(r.get_json()['image_urls'],['https://example.test/original.png',a['url']])
  r=self.client.post('/api/v1/admin/media/'+a['id']+'/archive',headers=self.h,json={'expected_version':a['row_version'],'reason':'TEST ONLY'});self.assertEqual(r.status_code,409)
 def test_cms_cannot_publish_private_library_asset(self):
  a=self.upload().get_json()['asset'];p=self.client.post('/api/v1/admin/content/pages',headers=self.h,json={'slug':'test-private-image','title':'TEST ONLY','kind':'page'}).get_json()['page']
  p=self.client.put('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h,json={'expected_revision':p['draft_revision_id'],'content':{'title':'TEST ONLY','blocks':[{'id':'b','type':'banner','image_url':a['url']}]}}).get_json()['page']
  d={'expected_revision':p['draft_revision_id'],'reason':'TEST ONLY'};self.assertEqual(self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/publish',headers=self.h,json=d).status_code,422)
