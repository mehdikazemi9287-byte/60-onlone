"""Synthetic-only tests for controlled media and business console mutations."""
import base64,io,os,sqlite3
from PIL import Image
from tests.base import AppTestCase
class AdminConsoleMediaTests(AppTestCase):
 def setUp(self):
  super().setUp();self.h=self.admin_headers();self.app.config['MEDIA_ROOT']=os.path.join(self.tmpdir,'media')
 def upload(self):
  f=io.BytesIO();Image.new('RGB',(32,24),(255,0,0)).save(f,'PNG')
  return self.client.post('/api/v1/admin/media',headers=self.h,json={'name':'[TEST ONLY].png','alt_text':'[TEST ONLY] red square','source_reference':'synthetic fixture','data_base64':base64.b64encode(f.getvalue()).decode()})
 def test_media_is_private_and_original_is_preserved(self):
  r=self.upload();self.assertEqual(r.status_code,201,r.get_json());a=r.get_json()['asset']
  self.assertEqual(self.client.get(a['url']).status_code,404)
  original=self.client.get('/api/v1/admin/media/'+a['id']+'/original',headers=self.h)
  self.assertEqual(original.status_code,200);self.assertTrue(original.data.startswith(b'\x89PNG'))
  self.assertEqual(original.headers['Cache-Control'],'no-store')
  self.assertEqual(self.client.get('/api/v1/admin/media/'+a['id']+'/original').status_code,401)
 def test_deduplication_and_version_guard(self):
  a=self.upload().get_json()['asset'];r=self.upload();self.assertEqual(r.status_code,200);self.assertTrue(r.get_json()['duplicate'])
  r=self.client.patch('/api/v1/admin/media/'+a['id'],headers=self.h,json={'expected_version':-1,'alt_text':'test','source_reference':'test'})
  self.assertEqual(r.status_code,409)
 def test_media_publication_archive_restore_and_immutable_audit(self):
  a=self.upload().get_json()['asset']
  for action,status in [('publish','public'),('archive','archived'),('restore','private')]:
   r=self.client.post('/api/v1/admin/media/'+a['id']+'/'+action,headers=self.h,json={'expected_version':a['row_version'],'reason':'TEST ONLY review'})
   self.assertEqual(r.status_code,200,r.get_json());a=r.get_json()['asset'];self.assertEqual(a['status'],status)
   self.assertEqual(self.client.get(a['url']).status_code,200 if status=='public' else 404)
  with self.assertRaises(sqlite3.IntegrityError):
   with self.db.write_transaction() as c:c.execute('DELETE FROM media_events')
 def test_invalid_file_and_missing_storage_rejected(self):
  r=self.client.post('/api/v1/admin/media',headers=self.h,json={'alt_text':'test','source_reference':'test','data_base64':base64.b64encode(b'<script>bad</script>').decode()});self.assertEqual(r.status_code,422)
  self.app.config.pop('MEDIA_ROOT');self.assertEqual(self.upload().status_code,409)
 def test_customer_cannot_access_console_modules(self):
  _,h=self.new_customer()
  for path in ['customers','orders','notifications','audit','reports/overview','settings','media']:
   self.assertEqual(self.client.get('/api/v1/admin/'+path,headers=h).status_code,403,path)
 def test_actual_console_projections_and_cache_policy(self):
  for path in ['customers','orders','notifications','audit','reports/overview','settings','media']:
   r=self.client.get('/api/v1/admin/'+path,headers=self.h);self.assertEqual(r.status_code,200,(path,r.get_json()));self.assertEqual(r.headers['Cache-Control'],'no-store')
 def test_settings_are_versioned_and_cannot_change_financial_policy(self):
  r=self.client.get('/api/v1/admin/settings',headers=self.h);d=r.get_json();self.assertEqual(r.status_code,200,d)
  payload={'values':d['values'],'expected_version':d['row_version']}
  self.assertEqual(self.client.put('/api/v1/admin/settings',headers=self.h,json=payload).status_code,200)
  self.assertEqual(self.client.put('/api/v1/admin/settings',headers=self.h,json=payload).status_code,409)
  payload['values']['credit_limit']='999999';self.assertEqual(self.client.put('/api/v1/admin/settings',headers=self.h,json=payload).status_code,422)
 def test_role_change_requires_exact_account_and_cannot_disable_self(self):
  _,customer_headers=self.new_customer();me=self.client.get('/api/v1/auth/me',headers=customer_headers).get_json();u=me.get('user',me)
  payload={'role':'employee','is_active':True,'expected_role':'customer','expected_active':True,'expected_email':u['email'],'reason':'TEST ONLY role change','confirm_scope':True}
  r=self.client.patch('/api/v1/admin/users/'+str(u['id'])+'/role',headers=self.h,json=payload);self.assertEqual(r.status_code,200,r.get_json())
  self.assertEqual(self.client.patch('/api/v1/admin/users/'+str(u['id'])+'/role',headers=self.h,json=payload).status_code,409)
  me=self.client.get('/api/v1/auth/me',headers=self.h).get_json();u=me.get('user',me);payload.update(role='customer',is_active=False,expected_role='admin',expected_email=u['email'])
  self.assertEqual(self.client.patch('/api/v1/admin/users/'+str(u['id'])+'/role',headers=self.h,json=payload).status_code,409)
 def test_unpublish_preserves_draft_and_history(self):
  p=self.client.post('/api/v1/admin/content/pages',headers=self.h,json={'slug':'test-unpublish','kind':'page','title':'TEST ONLY'}).get_json()['page']
  p=self.client.put('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h,json={'expected_revision':p['draft_revision_id'],'content':{'title':'TEST ONLY','blocks':[{'id':'b','type':'text','body':'TEST ONLY'}]}}).get_json()['page']
  d={'expected_revision':p['draft_revision_id'],'reason':'TEST ONLY'}
  self.assertEqual(self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/publish',headers=self.h,json=d).status_code,200)
  self.assertEqual(self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/unpublish',headers=self.h,json=d).status_code,200)
  self.assertEqual(self.client.get('/api/v1/content/pages/test-unpublish').status_code,404)
  saved=self.client.get('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h).get_json()['page'];self.assertEqual(saved['draft_revision_id'],p['draft_revision_id'])
