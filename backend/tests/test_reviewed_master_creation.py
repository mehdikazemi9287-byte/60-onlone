from tests.base import AppTestCase
import json

class ReviewedMasterCreationTest(AppTestCase):
    def payload(self):return {'canonical_name_fa':'[TEST] Manual reference','brand':'[TEST] Brand','category':'mobile','unit':'عدد','tax_category':'standard','vat_applicable':False,'vat_rate_bps':0,'manual_review':True,'source_reference':'[TEST ONLY] original document','reason':'test reviewed identity','confirm_real_source':True,'creation_request_key':'test-creation-key-001'}
    def post(self,p):
        if not hasattr(self,'creation_headers'):self.creation_headers=self.admin_headers()
        return self.client.post('/api/v1/admin/catalog/products',json=p,headers=self.creation_headers)
    def test_reviewed_create_audit_no_sale_and_retry_is_same_reference(self):
        p=self.payload();response=self.post(p);self.assertEqual(response.status_code,201,response.get_json());mid=response.get_json()['id']
        replay=self.post(p);self.assertEqual(replay.status_code,201);self.assertEqual(replay.get_json()['id'],mid)
        with self.db.read_transaction() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM products WHERE master_product_id=?',(mid,)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_publications WHERE master_product_id=?',(mid,)).fetchone()[0],0)
            self.assertIsNotNone(c.execute('SELECT family_id FROM master_products WHERE id=?',(mid,)).fetchone()[0])
            events=c.execute("SELECT metadata_json FROM audit_logs WHERE action='catalog.master_created' AND entity_id=?",(str(mid),)).fetchall();self.assertEqual(len(events),1)
            self.assertEqual(json.loads(events[0][0])['source_reference'],p['source_reference'])
        changed={**p,'canonical_name_fa':'[TEST] Different'};self.assertEqual(self.post(changed).status_code,409)

    def test_invalid_review_contract_does_not_create(self):
        with self.db.read_transaction() as c:before=c.execute('SELECT COUNT(*) FROM master_products').fetchone()[0]
        for fields in ({'category':'missing'},{'source_reference':''},{'confirm_real_source':False},{'creation_request_key':None},{'brand':''},{'unit':''},{'selling_price_minor':100},{'model':{}},{'specifications':[]}):
            p={**self.payload(),**fields};response=self.post(p);self.assertEqual(response.status_code,422,response.get_json())
        p=self.payload();del p['vat_rate_bps'];self.assertEqual(self.post(p).status_code,422)
        with self.db.read_transaction() as c:self.assertEqual(before,c.execute('SELECT COUNT(*) FROM master_products').fetchone()[0])

    def test_existing_minimal_admin_create_still_works(self):
        response=self.post({'canonical_name_fa':'[TEST] Existing API caller'})
        self.assertEqual(response.status_code,201,response.get_json());mid=response.get_json()['id']
        self.assertEqual(response.get_json()['vat_rate_bps'],900)
        with self.db.read_transaction() as c:
            event=c.execute("SELECT metadata_json FROM audit_logs WHERE action='catalog.master_created' AND entity_id=?",(str(mid),)).fetchone()
            metadata=json.loads(event[0]);self.assertEqual(metadata['channel'],'existing_admin_api')
            self.assertIsNone(metadata['source_reference'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM catalog_publications WHERE master_product_id=?',(mid,)).fetchone()[0],0)
