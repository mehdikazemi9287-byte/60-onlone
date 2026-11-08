import json
from tests import test_product_management_e2e as helper
from tests.base import AppTestCase
from app.services.marketplace_offer_service import _clean
from app.core.errors import ValidationError,ConflictError

class CatalogSourceDirectoryTest(AppTestCase):
 create=helper.ProductManagementTest.create
 fixture=helper.ProductManagementTest.fixture
 def setUp(self):
  super().setUp();self.headers=self.admin_headers()
 def test_real_provenance_null_price_duplicates_malformed_and_rbac(self):
  a,_=self.create();b,_=self.create();c,_=self.create()
  source={'supplier':'[TEST ONLY] PDF source','source_file':'[TEST ONLY] original.pdf','source_page':4,'price':None,'stock':None,'supplier_product_code':'[TEST ONLY] 1030'}
  with self.db.write_transaction() as con:
   con.execute('update master_products set specifications_json=? where id=?',(json.dumps({'pdf_catalog':{'sources':[source,source,'invalid',{'supplier':source['supplier'],'price':{'bad':1},'stock':True}]}}),a))
   con.execute('update master_products set specifications_json=? where id=?',('{invalid',b))
   con.execute('update master_products set specifications_json=? where id=?',(json.dumps({'pdf_catalog':{'sources':[{**source,'price':9007199254740993}]}}),c))
  r=self.client.get('/api/v1/admin/catalog/sources',headers=self.headers);self.assertEqual(r.status_code,200,r.get_json());row=next(x for x in r.get_json()['items'] if x['source_name']==source['supplier']);self.assertEqual(row['products'],2);self.assertIsNone(row['supplier_id'])
  r=self.client.get('/api/v1/admin/catalog/source-products',query_string={'source':source['supplier']},headers=self.headers);self.assertEqual(r.status_code,200,r.get_json());d=r.get_json();self.assertFalse(d['prices_are_sale_offers']);self.assertEqual(d['total'],2);items={x['id']:x for x in d['items']};self.assertIsNone(items[a]['sources'][0]['price']);self.assertIsNone(items[a]['sources'][2]['stock']);self.assertEqual(items[c]['sources'][0]['price'],'9007199254740993')
  _,customer=self.new_customer();self.assertEqual(self.client.get('/api/v1/admin/catalog/sources',headers=customer).status_code,403)
 def test_unknown_inventory_is_not_silently_zero(self):
  data={'selling_price_minor':1001,'pricing_mode':'fixed','stock_quantity':0}
  self.assertEqual(_clean(data)['selling_price_minor'],1001);self.assertEqual(_clean(data)['stock_quantity'],0)
  for missing in (None,True,1.5):
   with self.assertRaises(ValidationError):_clean({**data,'stock_quantity':missing})
  del data['stock_quantity']
  with self.assertRaises(ValidationError):_clean(data)
 def test_new_offer_requires_real_price_without_changing_unpriced_catalog(self):
  from app.services import marketplace_offer_service as offers
  mid,_=self.create();sku,supplier=self.fixture(mid)
  with self.db.write_transaction() as con:
   product=con.execute('select * from products where id=?',(sku['product_id'],)).fetchone()
   con.execute('delete from seller_offers where id=?',(sku['offer_id'],))
   data={'product_id':sku['product_id'],'selling_price_minor':0,'stock_quantity':0,'pricing_mode':'rfq_only'}
   with self.assertRaises(ValidationError):offers.create(con,supplier_id=supplier['supplier_id'],actor=supplier['user_id'],data=data)
   self.assertIsNone(con.execute('select id from seller_offers where product_id=?',(sku['product_id'],)).fetchone())
   self.assertEqual(tuple(product),tuple(con.execute('select * from products where id=?',(sku['product_id'],)).fetchone()))
   result=offers.create(con,supplier_id=supplier['supplier_id'],actor=supplier['user_id'],data={**data,'selling_price_minor':1001,'stock_quantity':2})
   self.assertEqual(result['selling_price_minor'],1001)
 def test_offer_edit_preserves_source_and_rejected_inventory_has_no_mutation(self):
  from app.services import marketplace_offer_service as offers
  mid,_=self.create();sku,supplier=self.fixture(mid)
  with self.db.write_transaction() as c:
   c.execute('update seller_offers set source_reference=?,stock_reserved=1 where id=?',('[TEST ONLY] original price document',sku['offer_id']))
   data={'selling_price_minor':1001,'stock_quantity':2,'pricing_mode':'fixed','channel':'both'}
   result=offers.update(c,supplier_id=supplier['supplier_id'],offer_id=sku['offer_id'],actor=supplier['user_id'],data=data)
   self.assertEqual(result['source_reference'],'[TEST ONLY] original price document')
   before=tuple(c.execute('select * from seller_offers where id=?',(sku['offer_id'],)).fetchone())
   with self.assertRaises(ConflictError):offers.update(c,supplier_id=supplier['supplier_id'],offer_id=sku['offer_id'],actor=supplier['user_id'],data={**data,'stock_quantity':0,'selling_price_minor':7777})
   self.assertEqual(before,tuple(c.execute('select * from seller_offers where id=?',(sku['offer_id'],)).fetchone()))
   event=json.loads(c.execute("select after_json from offer_events where offer_id=? and action='updated' order by id desc limit 1",(sku['offer_id'],)).fetchone()[0]);self.assertEqual(event['source_reference'],result['source_reference'])
