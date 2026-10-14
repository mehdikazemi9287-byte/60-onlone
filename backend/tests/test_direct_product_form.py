from tests.test_reviewed_master_creation import ReviewedMasterCreationTest
from concurrent.futures import ThreadPoolExecutor
from tests.base import AppTestCase
import uuid

class DirectProductFormTest(AppTestCase):
 def payload(self):
  return {**ReviewedMasterCreationTest.payload(self),'direct_form':True,'sku':'[TEST]-DIRECT-SKU','source_kind':'manual','source_supplier_id':None,'status':'draft','supply_channel':'organization','media_ids':[],'identifiers':[{'type':'GTIN','value':'4006381333931'}]}
 def setUp(self):super().setUp();self.headers=self.admin_headers()
 def post(self,p):return self.client.post('/api/v1/admin/catalog/products',json=p,headers=self.headers)
 def test_create_duplicate_retry_and_management(self):
  p=self.payload();check=self.client.post('/api/v1/admin/catalog/products/duplicate-check',json=p,headers=self.headers);self.assertEqual(check.status_code,200,check.get_json());self.assertEqual(check.get_json()['matches'],[])
  response=self.post(p);self.assertEqual(response.status_code,201,response.get_json());mid=response.get_json()['id'];self.assertEqual(response.get_json()['status'],'draft');self.assertIsNone(response.get_json()['package_quantity'])
  self.assertEqual(self.post(p).get_json()['id'],mid)
  for change in ({'identifiers':[{'type':'EAN','value':'4006381333931'}],'sku':'[TEST]different-2','creation_request_key':str(uuid.uuid4())},{'creation_request_key':str(uuid.uuid4())},{'sku':'[TEST]different','creation_request_key':str(uuid.uuid4())}):self.assertEqual(self.post({**p,**change}).status_code,409)
  management=self.client.get(f'/api/v1/admin/catalog/products/{mid}/management',headers=self.headers);self.assertEqual(management.status_code,200,management.get_json());d=management.get_json();self.assertEqual(d['profile']['supply_channel'],'organization');self.assertEqual(d['profile']['source_kind'],'manual');self.assertIsNone(d['price']);self.assertIsNone(d['stock']);self.assertEqual(len(d['history']),1);self.assertEqual(d['history'][0]['metadata']['created_fields']['sku'],p['sku']);self.assertEqual(len(d['identifiers']),2)
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM products WHERE master_product_id=?',(mid,)).fetchone()[0],0)
  with self.db.read_transaction() as c:legacy=c.execute('SELECT sku FROM products WHERE sku IS NOT NULL LIMIT 1').fetchone()
  self.assertIsNotNone(legacy)
  self.assertEqual(self.post({**p,'sku':legacy[0],'identifiers':[],'creation_request_key':str(uuid.uuid4())}).status_code,409)
  opt=self.client.get('/api/v1/admin/catalog/create-options',headers=self.headers);self.assertEqual(opt.status_code,200,opt.get_json())
 def test_invalid_and_role_boundaries(self):
  p=self.payload()
  for field in ({'source_kind':''},{'source_kind':'supplier','source_supplier_id':999999},{'media_ids':['missing'],'confirm_image_identity':True},{'status':'merged'},{'supply_channel':'unknown'},{'identifiers':[{'type':'SUPPLIER_SKU','value':'x'}]},{'sku':''},{'price':0},{'identifiers':[{'type':{},'value':'x'}]},{'identifiers':[{'type':'GTIN','value':'4006381333932'}]}):
   response=self.post({**p,**field});self.assertEqual(response.status_code,422,response.get_json())
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM direct_product_profiles').fetchone()[0],0)
  _,customer=self.new_customer()
  for url,method in [('/api/v1/admin/catalog/create-options','get'),('/api/v1/admin/catalog/products/duplicate-check','post'),('/api/v1/admin/catalog/products','post'),('/api/v1/admin/catalog/products/1/management','get')]:
   self.assertEqual(getattr(self.client,method)(url,json=p,headers=customer).status_code,403)
 def test_concurrent_same_key_is_one_creation(self):
  p=self.payload()
  def invoke(_):
   with self.app.test_client() as client:return client.post('/api/v1/admin/catalog/products',json=p,headers=self.headers)
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(invoke,range(2)))
  self.assertEqual([r.status_code for r in results],[201,201],[r.get_json() for r in results]);self.assertEqual(results[0].get_json()['id'],results[1].get_json()['id'])
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM direct_product_profiles').fetchone()[0],1)
 def test_real_media_selection_and_private_rejection(self):
  import base64,io
  from PIL import Image
  self.app.config['MEDIA_ROOT']=str(__import__('pathlib').Path(self.tmpdir)/'direct-media')
  b=io.BytesIO();Image.new('RGB',(12,12),'red').save(b,format='PNG')
  response=self.client.post('/api/v1/admin/media',json={'name':'[TEST ONLY].png','alt_text':'[TEST ONLY] image','source_reference':'[TEST ONLY] source','data_base64':base64.b64encode(b.getvalue()).decode()},headers=self.headers)
  self.assertEqual(response.status_code,201,response.get_json());asset=response.get_json()['asset']
  p={**self.payload(),'media_ids':[asset['id']],'confirm_image_identity':True}
  self.assertEqual(self.post(p).status_code,422)
  pub=self.client.post('/api/v1/admin/media/'+asset['id']+'/publish',json={'expected_version':asset['row_version'],'reason':'[TEST ONLY] reviewed'},headers=self.headers);self.assertEqual(pub.status_code,200,pub.get_json())
  response=self.post(p);self.assertEqual(response.status_code,201,response.get_json());self.assertEqual(response.get_json()['image_urls'],['/api/v1/media/'+asset['id']])
