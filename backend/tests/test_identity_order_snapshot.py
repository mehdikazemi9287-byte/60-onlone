from tests.base import AppTestCase
from tests import test_product_identity as identity_tests
from app.services import supplier_service

class IdentityOrderSnapshotTest(AppTestCase):
    setup_catalog=identity_tests.ProductIdentityTest.setup_catalog
    proposed=identity_tests.ProductIdentityTest.proposed
    preview=identity_tests.ProductIdentityTest.preview
    save=identity_tests.ProductIdentityTest.save

    def test_existing_order_document_retains_item_snapshot_after_identity_edit(self):
        mid,_,_=self.setup_catalog();supplier=self.create_test_supplier();_,headers=self.new_customer()
        with self.db.write_transaction() as c:
            sku=c.execute('SELECT id FROM products WHERE master_product_id=?',(mid,)).fetchone()['id']
            supplier_service.create_offer(c,product_id=sku,supplier_id=supplier['supplier_id'],supplier_location_id=supplier['location_id'],selling_price_minor=15000000,stock_quantity=20)
            c.execute("UPDATE seller_offers SET last_price_confirmed_at=datetime('now'),last_inventory_confirmed_at=datetime('now') WHERE product_id=? AND supplier_id=?",(sku,supplier['supplier_id']))
        cart=self.add_to_cart(headers,sku,2)
        self.assertIn(cart.status_code,(200,201),cart.get_json())
        checkout=self.checkout(headers)
        self.assertIn(checkout.status_code,(200,201),checkout.get_json())
        with self.db.read_transaction() as c:
            items=[dict(r) for r in c.execute('SELECT * FROM order_items WHERE product_id=?',(sku,))]
            self.assertTrue(items,'checkout must create a nonempty historical item snapshot')
            order_ids={r['order_id'] for r in items}
            orders=[dict(c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()) for oid in sorted(order_ids)]
        review=self.preview(mid)
        result=self.save(mid,self.proposed(),review['version'],confirm_public_change=True,confirm_family_change=True)
        self.assertEqual(result.status_code,200,result.get_json())
        with self.db.read_transaction() as c:
            self.assertEqual(items,[dict(r) for r in c.execute('SELECT * FROM order_items WHERE product_id=?',(sku,))])
            self.assertEqual(orders,[dict(c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()) for oid in sorted(order_ids)])
            self.assertEqual(c.execute('SELECT title_fa FROM products WHERE id=?',(sku,)).fetchone()[0],self.proposed()['canonical_name_fa'])
