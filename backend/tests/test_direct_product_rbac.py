from tests.base import AppTestCase
class DirectProductRBACTest(AppTestCase):
 def test_supplier_employee_and_revoked_admin_cannot_create_or_read(self):
  headers=self.admin_headers()
  with self.db.read_transaction() as c:uid=c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id DESC LIMIT 1").fetchone()[0]
  for role,active in [('supplier',1),('employee',1),('admin',0)]:
   with self.db.write_transaction() as c:c.execute('UPDATE users SET role=?,is_active=? WHERE id=?',(role,active,uid))
   for route,method in [('/api/v1/admin/catalog/create-options','get'),('/api/v1/admin/catalog/products/duplicate-check','post'),('/api/v1/admin/catalog/products','post'),('/api/v1/admin/catalog/products/1/management','get')]:
    r=getattr(self.client,method)(route,json={'canonical_name_fa':'[TEST ONLY] refused','sku':'[TEST ONLY]'},headers=headers);self.assertIn(r.status_code,(401,403),(role,route,r.get_json()))
