"""Version isolation, concurrency and authorization against the migrated disposable database."""
from tests.base import AppTestCase
class ContentTests(AppTestCase):
 def setUp(self):
  super().setUp();self.h=self.admin_headers()
 def create(self,slug='test-page',kind='page'):
  r=self.client.post('/api/v1/admin/content/pages',headers=self.h,json={'slug':slug,'title':'[TEST ONLY] صفحه','kind':kind})
  self.assertEqual(r.status_code,201,r.get_json());return r.get_json()['page']
 def edit(self,p,title='[TEST ONLY] عنوان',link='/business/catalog'):
  return self.client.put('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h,json={'expected_revision':p['draft_revision_id'],'content':{'title':title,'blocks':[{'id':'b1','type':'hero','title':title,'body':'[TEST ONLY] متن','link':link,'enabled':True}]}})
 def publish(self,p):return self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/publish',headers=self.h,json={'expected_revision':p['draft_revision_id'],'reason':'TEST ONLY review'})
 def test_draft_is_not_public(self):
  p=self.create();self.assertEqual(self.client.get('/api/v1/content/pages/'+p['slug']).status_code,404)
 def test_nonadmin_cannot_read_or_write_content(self):
  _,h=self.new_customer()
  self.assertEqual(self.client.get('/api/v1/admin/content/pages',headers=h).status_code,403)
  self.assertEqual(self.client.post('/api/v1/admin/content/pages',headers=h,json={}).status_code,403)
 def test_published_snapshot_is_unchanged_by_draft_edit(self):
  p=self.edit(self.create(),'[TEST ONLY] v1').get_json()['page'];self.assertEqual(self.publish(p).status_code,200)
  r=self.edit(p,'[TEST ONLY] v2');self.assertEqual(r.status_code,200,r.get_json())
  public=self.client.get('/api/v1/content/pages/test-page').get_json()
  self.assertEqual(public['content']['title'],'[TEST ONLY] v1')
  self.assertNotEqual(public['revision'],r.get_json()['page']['draft_revision_id'])
 def test_stale_revision_cannot_overwrite_new_draft(self):
  p=self.create();self.assertEqual(self.edit(p).status_code,200);self.assertEqual(self.edit(p,'stale').status_code,409)
 def test_script_scheme_and_unknown_executable_fields_are_rejected(self):
  p=self.create();self.assertEqual(self.edit(p,link='javascript:alert(1)').status_code,422)
  r=self.client.put('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h,json={'expected_revision':p['draft_revision_id'],'content':{'title':'TEST','blocks':[{'id':'b','type':'text','html':'<script>alert(1)</script>'}]}})
  self.assertEqual(r.status_code,422)
 def test_homepage_uses_existing_section_inventory(self):
  p=self.create('homepage','homepage');self.assertEqual(len(p['content']['blocks']),9)
  self.assertEqual([b['key'] for b in p['content']['blocks']][:2],['hero','collections'])
  self.assertEqual(self.publish(p).status_code,200)
 def test_restore_foreign_revision_is_denied_and_history_is_immutable(self):
  p=self.create();other=self.create('another-page')
  r=self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/restore',headers=self.h,json={'expected_revision':p['draft_revision_id'],'revision_id':other['draft_revision_id']})
  self.assertEqual(r.status_code,404)
  updated=self.edit(p).get_json()['page']
  r=self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/restore',headers=self.h,json={'expected_revision':updated['draft_revision_id'],'revision_id':p['draft_revision_id']})
  self.assertEqual(r.status_code,200,r.get_json());self.assertGreater(r.get_json()['page']['draft_revision_id'],updated['draft_revision_id'])
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM cms_revisions WHERE page_id=?',(p['id'],)).fetchone()[0],3)
 def test_repeated_publication_does_not_duplicate_events(self):
  p=self.edit(self.create()).get_json()['page'];self.assertEqual(self.publish(p).status_code,200);self.assertEqual(self.publish(p).status_code,200)
  with self.db.read_transaction() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cms_events WHERE page_id=? AND action='published'",(p['id'],)).fetchone()[0],1)
