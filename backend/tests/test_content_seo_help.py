from tests.base import AppTestCase
class ContentSeoHelpTest(AppTestCase):
 def setUp(self):super().setUp();self.h=self.admin_headers()
 def test_published_seo_help_is_versioned_and_draft_private(self):
  p=self.client.post('/api/v1/admin/content/pages',headers=self.h,json={'slug':'help-faq','title':'[TEST ONLY] FAQ','kind':'page'}).get_json()['page']
  content={'title':'[TEST ONLY] رسمی','blocks':[{'id':'faq1','type':'text','title':'[TEST ONLY] پرسش','body':'[TEST ONLY] پاسخ رسمی مصنوعی','link':'','button_label':'','image_url':'','enabled':True}],'seo':{'title':'[TEST ONLY] SEO','description':'[TEST ONLY] description','canonical':'/help/faq','noindex':True}}
  r=self.client.put('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h,json={'expected_revision':p['draft_revision_id'],'content':content,'reason':'[TEST ONLY] review'});self.assertEqual(r.status_code,200,r.get_json());p=r.get_json()['page']
  self.assertEqual(self.client.get('/api/v1/content/pages/help-faq').status_code,404)
  r=self.client.post('/api/v1/admin/content/pages/'+str(p['id'])+'/publish',headers=self.h,json={'expected_revision':p['draft_revision_id'],'reason':'[TEST ONLY] approved'});self.assertEqual(r.status_code,200,r.get_json())
  public=self.client.get('/api/v1/content/pages/help-faq').get_json();self.assertEqual(public['content'],content)
  later={**content,'seo':{**content['seo'],'title':'[TEST ONLY] later draft'}}
  self.assertEqual(self.client.put('/api/v1/admin/content/pages/'+str(p['id']),headers=self.h,json={'expected_revision':p['draft_revision_id'],'content':later,'reason':'[TEST ONLY] draft'}).status_code,200)
  self.assertEqual(self.client.get('/api/v1/content/pages/help-faq').get_json()['content']['seo']['title'],content['seo']['title'])
 def test_legacy_content_parity_and_unsafe_seo_rejected(self):
  from app.api.v1.admin_content import validate_content
  from app.core.errors import ValidationError
  content={'title':'[TEST ONLY] legacy','blocks':[]};self.assertEqual(validate_content(content,'page'),content)
  for seo in ({'noindex':'false'},{'canonical':'https://other.example/test'},{'canonical':'//example.test'},{'description':'x'*201},{'script':'alert(1)'}):
   with self.assertRaises(ValidationError):validate_content({**content,'seo':seo},'page')
