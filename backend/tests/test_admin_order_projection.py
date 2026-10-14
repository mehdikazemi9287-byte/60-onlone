"""Order snapshot names, exact int64 strings and personal/organization separation."""
from tests.base import AppTestCase
class OrderProjectionTests(AppTestCase):
 def setUp(self):super().setUp();self.h=self.admin_headers()
 def order(self,org=None):
  _,h=self.new_customer();me=self.client.get('/api/v1/auth/me',headers=h).get_json();u=me.get('user',me);amount=9007199254740993
  with self.db.write_transaction() as c:
   oid=c.execute("INSERT INTO orders(order_number,user_id,subtotal_minor,total_minor,currency,recipient_name,recipient_phone,shipping_province,shipping_city,shipping_line1,organization_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",('TEST ONLY '+str(u['id']),u['id'],amount,amount,'IRR','TEST ONLY','TEST ONLY','TEST ONLY','TEST ONLY','TEST ONLY',org)).lastrowid
   pid=c.execute('SELECT id FROM products ORDER BY id LIMIT 1').fetchone()[0]
   c.execute('INSERT INTO order_items(order_id,product_id,title_fa,sku,unit_price_minor,quantity,line_total_minor) VALUES (?,?,?,?,?,?,?)',(oid,pid,'[TEST ONLY] immutable snapshot','TEST ONLY SKU',amount,1,amount))
  return oid,amount
 def test_personal_snapshot_and_large_amounts_are_exact_strings(self):
  oid,amount=self.order();r=self.client.get('/api/v1/admin/orders/'+str(oid),headers=self.h);self.assertEqual(r.status_code,200,r.get_json());d=r.get_json()
  self.assertEqual(d['order']['total_minor'],str(amount));self.assertEqual(d['items'][0]['title_fa'],'[TEST ONLY] immutable snapshot');self.assertEqual(d['items'][0]['line_total_minor'],str(amount));self.assertEqual(r.headers['Cache-Control'],'no-store')
 def test_organization_order_is_not_personal_order(self):
  org=self.create_organization(name='TEST ONLY organization');oid,_=self.order(org['id'])
  self.assertEqual(self.client.get('/api/v1/admin/orders/'+str(oid),headers=self.h).status_code,404)
  rows=self.client.get('/api/v1/admin/orders',headers=self.h).get_json()['items'];self.assertFalse(any(x['id']==oid for x in rows))
