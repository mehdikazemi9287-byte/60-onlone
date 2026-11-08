"""Only Product Management acceptance paths; disposable DB/mock providers, no real business data."""
from tests.base import AppTestCase
from concurrent.futures import ThreadPoolExecutor
import uuid,json,datetime
from app.services import product_channel_policy as policy,sale_eligibility as se,storefront_service as store
from app.services import master_catalog_service as master,marketplace_offer_service as offers
from app.core.errors import ConflictError,ValidationError

class ProductManagementTest(AppTestCase):
 def setUp(self):
  super().setUp();self.headers=self.admin_headers();self.app.config['TEST_SALES_OVERRIDE']=False;self.app.config['COMMERCE_TEST_MODE']=True
 def create(self,channel='both',status='active'):
  p={'canonical_name_fa':'[TEST ONLY] reference '+uuid.uuid4().hex[:8],'brand':'[TEST ONLY] Brand','category':'mobile','unit':'عدد','package_quantity':None,'tax_category':'STANDARD','vat_applicable':False,'vat_rate_bps':0,'manual_review':True,'direct_form':True,'source_kind':'manual','source_supplier_id':None,'source_reference':'[TEST ONLY] original source','reason':'[TEST ONLY] create','confirm_real_source':True,'creation_request_key':str(uuid.uuid4()),'sku':'TEST-REFERENCE-'+uuid.uuid4().hex[:8],'identifiers':[],'media_ids':[],'status':status,'supply_channel':channel}
  r=self.client.post('/api/v1/admin/catalog/products',json=p,headers=self.headers);self.assertEqual(r.status_code,201,r.get_json());return r.get_json()['id'],p
 def read(self,mid):
  r=self.client.get(f'/api/v1/admin/catalog/products/{mid}/management',headers=self.headers);self.assertEqual(r.status_code,200,r.get_json());return r.get_json()
 def edit_body(self,d,**changes):return {**d['fields'],**changes,'expected_version':d['version'],'reason':'[TEST ONLY] reviewed edit','confirm_real_source':True,'confirm_commercial_effect':True,'edit_request_key':str(uuid.uuid4())}
 def patch(self,mid,p,headers=None):return self.client.patch(f'/api/v1/admin/catalog/products/{mid}/management',json=p,headers=headers or self.headers)
 def fixture(self,mid,supplier=None):
  supplier=supplier or self.create_test_supplier();sku=self.create_test_product_with_offer(supplier['supplier_id'],supplier['location_id'],price_minor=15000000,cost_minor=11000000,stock=100)
  with self.db.write_transaction() as c:
   c.execute("UPDATE products SET master_product_id=?,provenance='real' WHERE id=?",(mid,sku['product_id']))
   stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
   c.execute("UPDATE seller_offers SET provenance='real',last_price_confirmed_at=?,last_inventory_confirmed_at=?,channel='both' WHERE id=?",(stamp,stamp,sku['offer_id']))
  return sku,supplier
 def test_create_edit_read_duplicate_rejection_source_audit_and_replay(self):
  mid,created=self.create();d=self.read(mid);self.assertIsNone(d['price']);self.assertIsNone(d['stock'])
  other,other_p=self.create()
  p=self.edit_body(d,sku='TEST-EDITED-'+uuid.uuid4().hex[:8],source_kind='catalog',source_reference='[TEST ONLY] PDF revised',status='draft',supply_channel='organization')
  response=self.patch(mid,p);self.assertEqual(response.status_code,200,response.get_json());after=self.read(mid);self.assertEqual(after['fields']['sku'],p['sku']);self.assertEqual(after['fields']['source_reference'],p['source_reference']);self.assertEqual(after['product']['status'],'draft')
  replay=self.patch(mid,p);self.assertEqual(replay.status_code,200);self.assertTrue(replay.get_json()['replayed']);self.assertEqual(self.read(mid)['history_total'],after['history_total'])
  duplicate=self.patch(mid,self.edit_body(after,sku=other_p['sku']));self.assertEqual(duplicate.status_code,409,duplicate.get_json());self.assertEqual(self.read(mid)['version'],after['version'])
  historical_duplicate=self.client.post('/api/v1/admin/catalog/products',json={**other_p,'creation_request_key':str(uuid.uuid4()),'sku':created['sku']},headers=self.headers);self.assertEqual(historical_duplicate.status_code,409)
  event=next(x for x in after['history'] if x['action']=='catalog.management_updated');self.assertEqual(event['metadata']['before']['source_reference'],created['source_reference']);self.assertEqual(event['metadata']['after']['source_reference'],p['source_reference']);self.assertIsNotNone(event['actor_user_id']);self.assertTrue(event['created_at'])
  h=self.client.get(f'/api/v1/admin/catalog/products/{mid}/management/history?page=1',headers=self.headers);self.assertEqual(h.status_code,200);self.assertEqual(h.get_json()['total'],after['history_total'])
 def test_actual_sku_edit_preserves_orders_prices_and_aliases(self):
  mid,_=self.create();sku,_=self.fixture(mid);_,customer=self.new_customer();self.add_to_cart(customer,sku['product_id'],2)
  self.app.config['TEST_SALES_OVERRIDE']=True
  r=self.client.post('/api/v1/checkout',json={'shipping_address':self.DEFAULT_ADDRESS},headers={**customer,'Idempotency-Key':str(uuid.uuid4())});self.assertEqual(r.status_code,201,r.get_json());self.app.config['TEST_SALES_OVERRIDE']=False
  with self.db.read_transaction() as c:
   old_product=dict(c.execute('SELECT * FROM products WHERE id=?',(sku['product_id'],)).fetchone());snap={n:[dict(x) for x in c.execute('SELECT * FROM '+n)] for n in ('orders','order_items','seller_offers','offer_price_history','inventory')}
  d=self.read(mid);new_code='TEST-COMMERCE-EDIT-'+uuid.uuid4().hex[:8];p=self.edit_body(d,sku_updates=[{'id':sku['product_id'],'sku':new_code}],source_reference='[TEST ONLY] audited document')
  r=self.patch(mid,p);self.assertEqual(r.status_code,200,r.get_json())
  with self.db.read_transaction() as c:
   new=dict(c.execute('SELECT * FROM products WHERE id=?',(sku['product_id'],)).fetchone());self.assertEqual(new,{**old_product,'sku':new_code})
   for n,rows in snap.items():self.assertEqual(rows,[dict(x) for x in c.execute('SELECT * FROM '+n)],n)
   self.assertEqual(c.execute('SELECT product_id FROM product_code_aliases WHERE code=?',(old_product['sku'],)).fetchone()[0],sku['product_id'])
  d=self.read(mid);other,_=self.create();other_sku,_=self.fixture(other);collision=self.edit_body(d,sku_updates=[{'id':sku['product_id'],'sku':self.read(other)['linked_skus'][0]['sku']}]);self.assertEqual(self.patch(mid,collision).status_code,409)
  foreign=self.edit_body(d,sku_updates=[{'id':other_sku['product_id'],'sku':'[TEST] foreign'}]);self.assertEqual(self.patch(mid,foreign).status_code,422)
 def test_cas_concurrent_edits_and_role_revocation(self):
  mid,_=self.create();d=self.read(mid);payloads=[self.edit_body(d,source_reference='[TEST ONLY] revision '+str(i)) for i in range(2)]
  def invoke(p):
   with self.app.test_client() as client:return client.patch(f'/api/v1/admin/catalog/products/{mid}/management',json=p,headers=self.headers)
  with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(invoke,payloads))
  self.assertEqual(sorted(x.status_code for x in responses),[200,409],[x.get_json() for x in responses])
  _,customer=self.new_customer();self.assertEqual(self.patch(mid,self.edit_body(self.read(mid)),customer).status_code,403)
  supplier=self.create_test_supplier();self.assertEqual(self.patch(mid,{},supplier['headers']).status_code,403)
  actor=next(x['actor_user_id'] for x in self.read(mid)['history'] if x['action']=='catalog.master_created')
  for role,active in [('employee',1),('admin',0)]:
   with self.db.write_transaction() as c:c.execute('UPDATE users SET role=?,is_active=? WHERE id=?',(role,active,actor))
   for url in (f'/api/v1/admin/catalog/products/{mid}/management',f'/api/v1/admin/catalog/products/{mid}/management/history'):
    r=self.client.get(url,headers=self.headers);self.assertIn(r.status_code,(401,403))
   self.assertIn(self.patch(mid,{}).status_code,(401,403))
 def test_channel_intersection_matrix_public_api_cart_and_inactive(self):
  mid,_=self.create();sku,supplier=self.fixture(mid)
  for product_channel in ('retail','organization','both'):
   d=self.read(mid);r=self.patch(mid,self.edit_body(d,supply_channel=product_channel));self.assertEqual(r.status_code,200,r.get_json())
   for offer_channel in ('retail','organization','both'):
    with self.db.write_transaction() as c:c.execute('UPDATE seller_offers SET channel=? WHERE id=?',(offer_channel,sku['offer_id']))
    allowed=set(policy.channels(product_channel))&set(policy.channels(offer_channel))
    with self.app.app_context(),self.db.read_transaction() as c:
     self.assertEqual(set(policy.channels(policy.effective(c,sku['product_id'],offer_channel))),allowed)
     self.assertEqual(se.eligible_offer_conn(c,sku['product_id']) is not None,'retail' in allowed)
     views=store.offers_for(c,sku['product_id']);self.assertEqual(len(views),int(bool(allowed)));self.assertEqual(set(views[0]['allowed_channels']) if views else set(),allowed)
    api=self.client.get('/api/v1/storefront/products/'+sku['slug']);self.assertEqual(api.status_code,200,api.get_json());doc=api.get_json();self.assertEqual(set(doc['allowed_channels']),set(policy.channels(product_channel)));self.assertEqual(doc['price_minor'] is not None,'retail' in allowed)
    _,customer=self.new_customer();r=self.client.post('/api/v1/cart/items',json={'product_id':sku['product_id'],'quantity':1},headers=customer);self.assertEqual(r.status_code,201 if 'retail' in allowed else 409,r.get_json())
  d=self.read(mid);self.assertEqual(self.patch(mid,self.edit_body(d,status='draft')).status_code,200)
  self.assertEqual(self.client.get('/api/v1/storefront/products/'+sku['slug']).status_code,404);self.assertEqual(self.client.get('/api/v1/products/'+sku['slug']).status_code,404)
  with self.app.app_context(),self.db.read_transaction() as c:self.assertIsNone(se.eligible_offer_conn(c,sku['product_id']));self.assertEqual(store.offers_for(c,sku['product_id']),[])
 def test_org_intake_and_personal_inquiry_follow_live_channel(self):
  mid,_=self.create();sku,_=self.fixture(mid);org=self.create_organization(name='[TEST ONLY] PM organization');org_headers,_=self.make_org_admin(org['id']);_,customer=self.new_customer()
  for channel in ('retail','organization','both'):
   self.assertEqual(self.patch(mid,self.edit_body(self.read(mid),supply_channel=channel)).status_code,200)
   pr=self.client.post(f"/api/v1/orgs/{org['id']}/procurement/requests",json={'title':'[TEST ONLY] request','items':[{'master_product_id':mid,'quantity':2,'unit':'عدد'}]},headers=org_headers)
   self.assertEqual(pr.status_code,409 if channel=='retail' else 201,pr.get_json())
   for hdr,org_id,expected in [(customer,None,409 if channel=='organization' else 201),(org_headers,org['id'],409 if channel=='retail' else 201)]:
    r=self.client.post('/api/v1/requests',json={'kind':'price','subject':'[TEST ONLY] request','items':[{'slug':sku['slug'],'quantity':1}],**({'organization_id':org_id} if org_id else {})},headers={**hdr,'Idempotency-Key':str(uuid.uuid4())});self.assertEqual(r.status_code,expected,r.get_json())
 def test_supplier_offer_channel_and_tiers_cannot_override_product(self):
  mid,_=self.create('organization');sku,supplier=self.fixture(mid)
  base={'product_id':sku['product_id'],'selling_price_minor':15000000,'stock_quantity':100,'pricing_mode':'fixed','channel':'retail','tiers':[],'confirm':True}
  with self.app.app_context():
   with self.db.write_transaction() as c:
    with self.assertRaises(ValidationError):offers.update(c,supplier_id=supplier['supplier_id'],offer_id=sku['offer_id'],actor=supplier['user_id'],data=base)
   with self.db.write_transaction() as c:r=offers.update(c,supplier_id=supplier['supplier_id'],offer_id=sku['offer_id'],actor=supplier['user_id'],data={**base,'channel':'organization'});self.assertEqual(r['effective_channel'],'organization')
   with self.db.write_transaction() as c:
    with self.assertRaises(ValidationError):offers.update(c,supplier_id=supplier['supplier_id'],offer_id=sku['offer_id'],actor=supplier['user_id'],data={**base,'channel':'organization','tiers':[{'channel':'retail','min_qty':1,'unit_price_minor':15000000}]})
 def test_rfq_quote_po_revalidate_channel_without_altering_committed_snapshots(self):
  from app.services import procurement_service as pr,rfq_service as rfq,purchase_order_service as po
  mid,_=self.create();org=self.create_organization(name='[TEST ONLY] RFQ policy');_,member=self.make_org_admin(org['id']);supplier=self.create_test_supplier();uid=member['user_id']
  with self.db.write_transaction() as c:
   request=pr.create_purchase_request(c,organization_id=org['id'],requester_user_id=uid,title='[TEST ONLY] source request',items=[{'master_product_id':mid,'quantity':2,'unit':'عدد'}])
   pr.submit_purchase_request(c,request['id'],actor_user_id=uid,organization_id=org['id']);pr.approve_purchase_request(c,request['id'],actor_user_id=uid,organization_id=org['id'],action='approve')
   result=rfq.create_rfq(c,organization_id=org['id'],purchase_request_id=request['id'],actor_user_id=uid,title='[TEST ONLY] RFQ')
   rfq.invite_supplier_to_rfq(c,result['id'],actor_user_id=uid,organization_id=org['id'],supplier_id=supplier['supplier_id'])
   rfq.open_rfq(c,result['id'],actor_user_id=uid,organization_id=org['id']);item=result['items'][0]['id']
  self.assertEqual(self.patch(mid,self.edit_body(self.read(mid),supply_channel='retail')).status_code,200)
  with self.db.write_transaction() as c:
   with self.assertRaises(ConflictError):rfq.submit_supplier_quote(c,result['id'],supplier_id=supplier['supplier_id'],items=[{'rfq_item_id':item,'unit_price_minor':100000,'quantity':2}],vat_rate_bps=0)
  self.assertEqual(self.patch(mid,self.edit_body(self.read(mid),supply_channel='organization')).status_code,200)
  with self.db.write_transaction() as c:
   quote=rfq.submit_supplier_quote(c,result['id'],supplier_id=supplier['supplier_id'],items=[{'rfq_item_id':item,'unit_price_minor':100000,'quantity':2}],vat_rate_bps=0)
   rfq.close_rfq(c,result['id'],actor_user_id=uid,organization_id=org['id']);rfq.award_rfq(c,result['id'],actor_user_id=uid,organization_id=org['id'],winning_quote_id=quote['id'])
  self.assertEqual(self.patch(mid,self.edit_body(self.read(mid),status='draft')).status_code,200)
  with self.db.write_transaction() as c:
   with self.assertRaises(ConflictError):po.create_purchase_order(c,organization_id=org['id'],actor_user_id=uid,supplier_quote_id=quote['id'])
  self.assertEqual(self.patch(mid,self.edit_body(self.read(mid),status='active')).status_code,200)
  with self.db.write_transaction() as c:order=po.create_purchase_order(c,organization_id=org['id'],actor_user_id=uid,supplier_quote_id=quote['id']);snapshot=[dict(x) for x in c.execute('SELECT * FROM purchase_order_items WHERE purchase_order_id=?',(order['id'],))]
  self.assertEqual(self.patch(mid,self.edit_body(self.read(mid),supply_channel='retail')).status_code,200)
  with self.db.write_transaction() as c:
   with self.assertRaises(ConflictError):po.confirm_purchase_order(c,order['id'],actor_user_id=uid,organization_id=org['id'])
   self.assertEqual(snapshot,[dict(x) for x in c.execute('SELECT * FROM purchase_order_items WHERE purchase_order_id=?',(order['id'],))])
 def test_csv_reuses_edited_sku_and_preserves_manually_inactive_status(self):
  from app.services import catalog_bulk_import_service as bulk
  mid,_=self.create();sku,_=self.fixture(mid)
  with self.db.read_transaction() as c:old=dict(c.execute('SELECT * FROM products WHERE id=?',(sku['product_id'],)).fetchone())
  new_code='TEST-CODE-'+uuid.uuid4().hex[:8];r=self.patch(mid,self.edit_body(self.read(mid),status='draft',sku_updates=[{'id':sku['product_id'],'sku':new_code}]));self.assertEqual(r.status_code,200,r.get_json())
  with self.db.write_transaction() as c:
   m=c.execute('SELECT * FROM master_products WHERE id=?',(mid,)).fetchone()
   item={'sku':old['sku'],'canonical_name_fa':m['canonical_name_fa'],'brand':m['brand'],'category_slug':m['category'],'package_quantity':None,'vat_rate_bps':0,'publish_status':'active','price_minor':old['base_price_minor'],'stock_quantity':100}
   category=bulk._upsert_category(c,item);found=bulk._upsert_master(c,item);self.assertEqual(found,mid)
   product_id=bulk._upsert_storefront(c,item,mid,category);self.assertEqual(product_id,sku['product_id'])
   current=c.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone();self.assertEqual(current['sku'],new_code);self.assertEqual(current['slug'],old['slug']);self.assertEqual(c.execute('SELECT status FROM master_products WHERE id=?',(mid,)).fetchone()[0],'draft')
   self.assertEqual(c.execute('SELECT COUNT(*) FROM products WHERE master_product_id=?',(mid,)).fetchone()[0],1)
