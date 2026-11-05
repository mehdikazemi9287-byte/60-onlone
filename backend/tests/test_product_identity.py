from tests.base import AppTestCase
from app.services import master_catalog_service as master, catalog_structure_service as structure, supplier_service

class ProductIdentityTest(AppTestCase):
    def setup_catalog(self):
        with self.db.write_transaction() as c:
            mids=[]
            for name in ('[TEST] Item 100 گرم','[TEST] Item 200 گرم','[TEST] Other'):
                m=master.create_master_product(c,canonical_name_fa=name,brand='[TEST] Brand',category='mobile',image_urls=['/test-only.png'])
                c.execute("UPDATE master_products SET provenance='real' WHERE id=?",(m['id'],));mids.append(m['id'])
            structure.apply(c)
            structure.set_visibility(c,master_product_id=mids[0],visible=True,reason='test publish')
        return mids
    def proposed(self):return {'canonical_name_fa':'[TEST] New name','brand':'[TEST] New brand','category':'laptop'}
    def preview(self,mid,p=None):
        response=self.client.post(f'/api/v1/admin/catalog/products/{mid}/identity/preview',json=p or self.proposed(),headers=self.admin_headers())
        self.assertEqual(response.status_code,200,response.get_json());return response.get_json()['product']
    def save(self,mid,p,version,**kw):
        return self.client.patch(f'/api/v1/admin/catalog/products/{mid}/identity',json={**p,'expected_version':version,'reason':'test identity review',**kw},headers=self.admin_headers())

    def test_identity_sync_preserves_sale_fields_offers_slugs_and_unrelated_master(self):
        a,b,other=self.setup_catalog();sup=self.create_test_supplier()
        with self.db.write_transaction() as c:
            sku=dict(c.execute('SELECT * FROM products WHERE master_product_id=?',(a,)).fetchone())
            offer=supplier_service.create_offer(c,product_id=sku['id'],supplier_id=sup['supplier_id'],supplier_location_id=sup['location_id'],selling_price_minor=9007199254740993,stock_quantity=9)
            publication=dict(c.execute('SELECT * FROM catalog_publications WHERE master_product_id=?',(a,)).fetchone())
            untouched=tuple(c.execute('SELECT * FROM master_products WHERE id=?',(other,)).fetchone())
            family=c.execute('SELECT family_id FROM master_products WHERE id=?',(b,)).fetchone()[0]
        review=self.preview(a);self.assertTrue(review['affects_public_content']);self.assertTrue(review['requires_family_confirmation'])
        response=self.save(a,self.proposed(),review['version'],confirm_public_change=True,confirm_family_change=True)
        self.assertEqual(response.status_code,200,response.get_json())
        with self.db.read_transaction() as c:
            changed=dict(c.execute('SELECT * FROM products WHERE id=?',(sku['id'],)).fetchone())
            for k,v in sku.items():
                if k not in ('title_fa','brand_fa','category_id'):self.assertEqual(changed[k],v,k)
            self.assertEqual(changed['title_fa'],self.proposed()['canonical_name_fa'])
            self.assertEqual(changed['brand_fa'],self.proposed()['brand'])
            pub=dict(c.execute('SELECT * FROM catalog_publications WHERE master_product_id=?',(a,)).fetchone())
            for k,v in publication.items():
                if k not in ('category_slug','updated_at'):self.assertEqual(pub[k],v,k)
            self.assertEqual(pub['category_slug'],'laptop')
            stored=dict(c.execute('SELECT * FROM seller_offers WHERE id=?',(offer['id'],)).fetchone())
            # create_offer also returns derived channel-policy fields; compare the stored columns only.
            self.assertEqual(stored,{k:offer[k] for k in stored})
            self.assertEqual(tuple(c.execute('SELECT * FROM master_products WHERE id=?',(other,)).fetchone()),untouched)
            self.assertEqual(c.execute('SELECT family_id FROM master_products WHERE id=?',(b,)).fetchone()[0],family)
        same={**self.proposed()};review=self.preview(a,same)
        response=self.save(a,same,review['version'],confirm_public_change=True,confirm_family_change=True)
        self.assertEqual(response.status_code,200);self.assertFalse(response.get_json()['changed'])
        with self.db.read_transaction() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='catalog.identity_updated'").fetchone()[0],1)

    def test_stale_affected_member_and_new_group_entry_rejected(self):
        a,b,_=self.setup_catalog();p=self.proposed();review=self.preview(a,p)
        with self.db.write_transaction() as c:c.execute("UPDATE master_products SET description_fa='concurrent edit' WHERE id=?",(b,))
        self.assertEqual(self.save(a,p,review['version'],confirm_public_change=True,confirm_family_change=True).status_code,409)
        review=self.preview(a,p)
        with self.db.write_transaction() as c:
            m=master.create_master_product(c,canonical_name_fa=p['canonical_name_fa'],brand=p['brand'],category=p['category'])
            c.execute("UPDATE master_products SET provenance='real' WHERE id=?",(m['id'],))
        self.assertEqual(self.save(a,p,review['version'],confirm_public_change=True,confirm_family_change=True).status_code,409)
        with self.db.read_transaction() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='catalog.identity_updated'").fetchone()[0],0)

    def test_confirmation_and_validation_no_mutation(self):
        a,_,_=self.setup_catalog();p=self.proposed();review=self.preview(a,p)
        self.assertEqual(self.save(a,p,review['version']).status_code,422)
        self.assertEqual(self.save(a,p,review['version'],confirm_public_change=True).status_code,422)
        for payload in ({}, {**p,'category':'not-a-category'}, {**p,'brand':''}, {**p,'selling_price_minor':1}):
            response=self.client.post(f'/api/v1/admin/catalog/products/{a}/identity/preview',json=payload,headers=self.admin_headers());self.assertEqual(response.status_code,422,response.get_json())
        with self.db.read_transaction() as c:self.assertEqual(c.execute('SELECT brand FROM master_products WHERE id=?',(a,)).fetchone()[0],'[TEST] Brand')

    def test_customer_denied_and_merged_reference_denied(self):
        a,_,_=self.setup_catalog();customer=self.new_customer()
        self.assertEqual(self.client.get(f'/api/v1/admin/catalog/products/{a}/identity',headers=customer[1]).status_code,403)
        with self.db.write_transaction() as c:c.execute("UPDATE master_products SET status='merged' WHERE id=?",(a,))
        self.assertEqual(self.client.get(f'/api/v1/admin/catalog/products/{a}/identity',headers=self.admin_headers()).status_code,404)

    def test_incomplete_brand_can_be_reviewed_and_preview_is_readonly(self):
        a,_,_=self.setup_catalog()
        with self.db.write_transaction() as c:c.execute('UPDATE master_products SET brand=NULL WHERE id=?',(a,))
        with self.db.read_transaction() as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM product_families ORDER BY id')]
        response=self.client.get(f'/api/v1/admin/catalog/products/{a}/identity',headers=self.admin_headers())
        self.assertEqual(response.status_code,200,response.get_json())
        self.preview(a)
        with self.db.read_transaction() as c:self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM product_families ORDER BY id')])

    def test_stale_sku_and_publication_rejected(self):
        a,_,_=self.setup_catalog();p=self.proposed();review=self.preview(a,p)
        with self.db.write_transaction() as c:c.execute('UPDATE products SET base_price_minor=99 WHERE master_product_id=?',(a,))
        self.assertEqual(self.save(a,p,review['version'],confirm_public_change=True,confirm_family_change=True).status_code,409)
        review=self.preview(a,p)
        with self.db.write_transaction() as c:c.execute("UPDATE catalog_publications SET publication_reason='concurrent review' WHERE master_product_id=?",(a,))
        self.assertEqual(self.save(a,p,review['version'],confirm_public_change=True,confirm_family_change=True).status_code,409)
