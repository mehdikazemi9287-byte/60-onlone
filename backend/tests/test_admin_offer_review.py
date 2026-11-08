from tests.base import AppTestCase
class OfferReviewTests(AppTestCase):
 def setUp(self):
  super().setUp();self.h=self.admin_headers();self.sup=self.create_test_supplier();self.other=self.create_test_supplier()
  self.o=self.create_test_product_with_offer(self.sup['supplier_id'],self.sup['location_id'],price_minor=9007199254740993)
 def test_customer_denied_and_amounts_exact(self):
  _,h=self.new_customer();path='/api/v1/admin/offers/'+str(self.o['offer_id'])+'/history'
  self.assertEqual(self.client.get(path,headers=h).status_code,403)
  r=self.client.get(path,headers=self.h);self.assertEqual(r.status_code,200,r.get_json());d=r.get_json();self.assertEqual(d['offer']['selling_price_minor'],'9007199254740993');self.assertEqual(d['price_write_owner'],'supplier');self.assertEqual(r.headers['Cache-Control'],'no-store')
 def test_history_is_actual_and_reads_do_not_change_offer(self):
  from app.services.supplier_service import update_offer_price
  with self.db.write_transaction() as c:update_offer_price(c,offer_id=self.o['offer_id'],supplier_id=self.sup['supplier_id'],selling_price_minor=9007199254740995)
  path='/api/v1/admin/offers/'+str(self.o['offer_id'])+'/history';d=self.client.get(path,headers=self.h).get_json()
  self.assertEqual(d['items'][0]['old_price_minor'],'9007199254740993');self.assertEqual(d['items'][0]['new_price_minor'],'9007199254740995');self.assertEqual(d['items'][0]['changed_by_supplier_id'],self.sup['supplier_id'])
  self.assertEqual(self.client.get('/api/v1/admin/offer-review',headers=self.h).status_code,200)
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT selling_price_minor FROM seller_offers WHERE id=?',(self.o['offer_id'],)).fetchone()[0],9007199254740995)
 def test_existing_supplier_ownership_is_not_bypassed(self):
  path='/api/v1/supplier/offers/'+str(self.o['offer_id'])+'/price'
  r=self.client.patch(path,headers=self.other['headers'],json={'selling_price_minor':123});self.assertEqual(r.status_code,404,r.get_json())
  self.assertEqual(self.client.get('/api/v1/admin/offer-review?page=-1',headers=self.h).status_code,422)
  self.assertEqual(self.client.get('/api/v1/admin/offers/99999999/history',headers=self.h).status_code,404)

 def test_invalid_price_and_stock_values_never_mutate_offer(self):
  for field,route in [('selling_price_minor','price'),('stock_quantity','stock')]:
   for value in [True,False,1.7,1.0,9223372036854775808]:
    r=self.client.patch('/api/v1/supplier/offers/'+str(self.o['offer_id'])+'/'+route,headers=self.sup['headers'],json={field:value})
    self.assertEqual(r.status_code,422,(field,value,r.get_json()))
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT selling_price_minor FROM seller_offers WHERE id=?',(self.o['offer_id'],)).fetchone()[0],9007199254740993)
 def test_exact_decimal_string_price_remains_supported(self):
  r=self.client.patch('/api/v1/supplier/offers/'+str(self.o['offer_id'])+'/price',headers=self.sup['headers'],json={'selling_price_minor':'9007199254740995'})
  self.assertEqual(r.status_code,200,r.get_json())
  with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT selling_price_minor FROM seller_offers WHERE id=?',(self.o['offer_id'],)).fetchone()[0],9007199254740995)
