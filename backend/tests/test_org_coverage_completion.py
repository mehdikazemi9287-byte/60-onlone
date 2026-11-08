import json
from tests.base import AppTestCase
from tests import test_product_management_e2e as h
from app.services import procurement_service as pr,rfq_service as rfq,purchase_order_service as po,enterprise_procurement_service as ops
from app.services import procurement_coverage as coverage
from app.core.errors import ConflictError,ValidationError
class OrgCoverageCompletionTest(AppTestCase):
 create=h.ProductManagementTest.create
 def setUp(self):
  super().setUp();self.headers=self.admin_headers();self.app.config['TEST_SALES_OVERRIDE']=False;self.app.config['COMMERCE_TEST_MODE']=True
  self.mids=[self.create()[0],self.create()[0]];org=self.create_organization(name='[TEST ONLY] multi-source cities');self.oid=org['id'];self.member_headers,m=self.make_org_admin(self.oid);self.uid=m['user_id'];self.suppliers=[self.create_test_supplier(),self.create_test_supplier()]
  with self.db.write_transaction() as c:
   p=pr.create_purchase_request(c,organization_id=self.oid,requester_user_id=self.uid,title='[TEST ONLY] two supplier lines',items=[{'master_product_id':x,'quantity':2,'unit':'عدد'} for x in self.mids],destinations=[{'city':'[TEST ONLY] A','province':'[TEST ONLY] A','address':'[TEST ONLY] A','allocations':[{'item_index':0,'quantity':1},{'item_index':1,'quantity':1}]},{'city':'[TEST ONLY] B','province':'[TEST ONLY] B','address':'[TEST ONLY] B','allocations':[{'item_index':0,'quantity':1},{'item_index':1,'quantity':1}]}])
   self.prid=p['id'];pr.submit_purchase_request(c,self.prid,actor_user_id=self.uid,organization_id=self.oid);pr.approve_purchase_request(c,self.prid,actor_user_id=self.uid,organization_id=self.oid,action='approve')
   self.items=coverage.requested(c,self.prid)
 def award(self,index,quantity=2):
  sup=self.suppliers[index]
  with self.db.write_transaction() as c:
   r=rfq.create_rfq(c,organization_id=self.oid,purchase_request_id=self.prid,actor_user_id=self.uid,title='[TEST ONLY] group',items=[{'purchase_request_item_id':self.items[index]['id'],'quantity':quantity}])
   rfq.invite_supplier_to_rfq(c,r['id'],actor_user_id=self.uid,organization_id=self.oid,supplier_id=sup['supplier_id']);rfq.open_rfq(c,r['id'],actor_user_id=self.uid,organization_id=self.oid)
   q=rfq.submit_supplier_quote(c,r['id'],supplier_id=sup['supplier_id'],items=[{'rfq_item_id':r['items'][0]['id'],'unit_price_minor':100000,'quantity':quantity}],vat_rate_bps=0)
   rfq.close_rfq(c,r['id'],actor_user_id=self.uid,organization_id=self.oid);rfq.award_rfq(c,r['id'],actor_user_id=self.uid,organization_id=self.oid,winning_quote_id=q['id'])
   return r,q
 def test_next_action_after_partial_order_targets_remaining_lines(self):
  _,quote=self.award(0)
  with self.db.write_transaction() as c:
   po.create_purchase_order(c,organization_id=self.oid,actor_user_id=self.uid,supplier_quote_id=quote['id'])
   w=ops.workspace(c,organization_id=self.oid,pr_id=self.prid,actor_user_id=self.uid)
   self.assertEqual(w['next_action']['key'],'create_rfq')
 def test_explicit_two_supplier_city_split_api_preview_guards_audit_and_snapshots(self):
  _,quote=self.award(0,1);base=f'/api/v1/orgs/{self.oid}/procurement/purchase-orders';h=self.member_headers
  r=self.client.get(base+'/allocation-preview',query_string={'supplier_quote_id':quote['id']},headers=h);self.assertEqual(r.status_code,200,r.get_json());self.assertIsNone(r.get_json()['suggested']);self.assertEqual([d['available'] for d in r.get_json()['requirements'][0]['destinations']],[1,1])
  _,outsider=self.new_customer();self.assertEqual(self.client.get(base+'/allocation-preview',query_string={'supplier_quote_id':quote['id']},headers=outsider).status_code,403)
  pid=self.items[0]['id'];a={'purchase_request_item_id':pid,'destination_index':0,'quantity':1}
  self.assertEqual(self.client.post(base,json={'supplier_quote_id':quote['id']},headers=h).status_code,409)
  for rows,status in (([a,a],422),([{**a,'quantity':2}],409),([{**a,'quantity':True}],422),([{**a,'purchase_request_item_id':self.items[1]['id']}],422),([],422)):
   self.assertEqual(self.client.post(base,json={'supplier_quote_id':quote['id'],'destination_allocations':rows},headers=h).status_code,status)
  self.assertEqual(self.client.post(base,json={'supplier_quote_id':1.5},headers=h).status_code,422)
  with self.db.read_transaction() as c:original=c.execute('select destinations_json from purchase_requests where id=?',(self.prid,)).fetchone()[0]
  r=self.client.post(base,json={'supplier_quote_id':quote['id'],'destination_allocations':[a]},headers=h);self.assertEqual(r.status_code,201,r.get_json());first=r.get_json()['purchase_order'];self.assertEqual(first['grand_total_minor'],quote['grand_total_minor'])
  self.suppliers[0]=self.suppliers[1];_,q2=self.award(0,1)
  preview=self.client.get(base+'/allocation-preview',query_string={'supplier_quote_id':q2['id']},headers=h).get_json();self.assertEqual(preview['suggested'],[{**a,'destination_index':1}])
  self.assertEqual(self.client.post(base,json={'supplier_quote_id':q2['id'],'destination_allocations':[a]},headers=h).status_code,409)
  r=self.client.post(base,json={'supplier_quote_id':q2['id']},headers=h);self.assertEqual(r.status_code,201,r.get_json());second=r.get_json()['purchase_order']
  with self.db.read_transaction() as c:
   self.assertEqual(c.execute('select destinations_json from purchase_requests where id=?',(self.prid,)).fetchone()[0],original)
   for order,city in ((first,0),(second,1)):
    snapshot=json.loads(c.execute('select destinations_json_snapshot from purchase_orders where id=?',(order['id'],)).fetchone()[0]);self.assertEqual(snapshot[city]['allocations'],[{'item_index':0,'quantity':1}]);self.assertEqual(snapshot[1-city]['allocations'],[])
   event=c.execute("select details_json from procurement_audit_log where entity_type='purchase_order' and entity_id=? order by id desc limit 1",(first['id'],)).fetchone();self.assertTrue(event)
 def test_two_supplier_groups_two_cities_no_premature_closure_or_financial_rewrite(self):
  r,q=self.award(0)
  with self.db.write_transaction() as c:
   self.assertEqual(c.execute('select status from purchase_requests where id=?',(self.prid,)).fetchone()[0],'sourcing')
   first=po.create_purchase_order(c,organization_id=self.oid,actor_user_id=self.uid,supplier_quote_id=q['id']);self.assertEqual(first['grand_total_minor'],q['grand_total_minor'])
   with self.assertRaises(ConflictError):ops.close_request(c,organization_id=self.oid,pr_id=self.prid,actor_user_id=self.uid)
  r2,q2=self.award(1)
  with self.db.write_transaction() as c:
   second=po.create_purchase_order(c,organization_id=self.oid,actor_user_id=self.uid,supplier_quote_id=q2['id']);self.assertEqual(c.execute('select status from purchase_requests where id=?',(self.prid,)).fetchone()[0],'awarded')
   for order,index in [(first,0),(second,1)]:
    snapshot=c.execute('select * from purchase_orders where id=?',(order['id'],)).fetchone();d=coverage.order_destinations(c,snapshot);self.assertEqual([x['allocations'] for x in d],[[{'item_index':index,'quantity':1}],[{'item_index':index,'quantity':1}]])
    po.confirm_purchase_order(c,order['id'],actor_user_id=self.uid,organization_id=self.oid);po.send_purchase_order(c,order['id'],actor_user_id=self.uid,organization_id=self.oid)
    for idx in (0,1):
     for state in ('preparing','ready','shipped'):ops.update_delivery(c,organization_id=self.oid,po_id=order['id'],destination_index=idx,actor_user_id=self.uid,status=state,tracking_reference='[TEST ONLY] carrier')
     ops.record_receipt(c,organization_id=self.oid,po_id=order['id'],actor_user_id=self.uid,data={'destination_index':idx,'kind':'full','receiver_name':'[TEST ONLY] receiver','quantities':[{'item_index':index,'quantity':1}]})
     self.assertEqual(coverage.deliveries_complete(c,c.execute('select * from purchase_orders where id=?',(order['id'],)).fetchone()),idx==1)
     if idx==0:
      from unittest.mock import patch
      from app.services import procurement_finance_service as fin
      with patch.object(fin,'po_finance',return_value={'settlement':None,'fully_paid':True}):
       with self.assertRaises(ConflictError):fin.record_settlement(c,org=self.oid,po_id=order['id'],actor=self.uid,reference='[TEST ONLY] no premature settlement')
   ops.close_request(c,organization_id=self.oid,pr_id=self.prid,actor_user_id=self.uid);self.assertEqual(c.execute('select status from purchase_requests where id=?',(self.prid,)).fetchone()[0],'completed')
 def test_next_action_checks_all_orders_when_latest_is_delivered(self):
  _,a=self.award(0);_,b=self.award(1)
  with self.db.write_transaction() as c:
   orders=[po.create_purchase_order(c,organization_id=self.oid,actor_user_id=self.uid,supplier_quote_id=q['id']) for q in (a,b)]
   for order in orders:
    po.confirm_purchase_order(c,order['id'],actor_user_id=self.uid,organization_id=self.oid);po.send_purchase_order(c,order['id'],actor_user_id=self.uid,organization_id=self.oid)
   for idx in (0,1):
    for state in ('preparing','ready','shipped'):ops.update_delivery(c,organization_id=self.oid,po_id=orders[1]['id'],destination_index=idx,actor_user_id=self.uid,status=state)
    ops.record_receipt(c,organization_id=self.oid,po_id=orders[1]['id'],actor_user_id=self.uid,data={'destination_index':idx,'kind':'full','receiver_name':'[TEST ONLY] latest order delivered','quantities':[{'item_index':1,'quantity':1}]})
   w=ops.workspace(c,organization_id=self.oid,pr_id=self.prid,actor_user_id=self.uid);self.assertEqual(w['next_action']['key'],'fulfillment')
 def test_forged_subset_overcommit_partial_destination_and_contradictory_receipt_rejected(self):
  with self.db.write_transaction() as c:
   with self.assertRaises(ValidationError):rfq.create_rfq(c,organization_id=self.oid,purchase_request_id=self.prid,actor_user_id=self.uid,title='[TEST ONLY] invalid',items=[{'purchase_request_item_id':self.items[0]['id'],'master_product_id':self.mids[1],'quantity':2}])
  r,q=self.award(0,1)
  with self.db.write_transaction() as c:
   with self.assertRaises(ConflictError):po.create_purchase_order(c,organization_id=self.oid,actor_user_id=self.uid,supplier_quote_id=q['id'])
   with self.assertRaises(ValidationError):rfq.create_rfq(c,organization_id=self.oid,purchase_request_id=self.prid,actor_user_id=self.uid,title='[TEST ONLY] overcommit',items=[{'purchase_request_item_id':self.items[0]['id'],'quantity':2}])
  r2,q2=self.award(1)
  with self.db.write_transaction() as c:
   order=po.create_purchase_order(c,organization_id=self.oid,actor_user_id=self.uid,supplier_quote_id=q2['id']);po.confirm_purchase_order(c,order['id'],actor_user_id=self.uid,organization_id=self.oid);po.send_purchase_order(c,order['id'],actor_user_id=self.uid,organization_id=self.oid)
   for state in ('preparing','ready','shipped'):ops.update_delivery(c,organization_id=self.oid,po_id=order['id'],destination_index=0,actor_user_id=self.uid,status=state)
   for quantities in ([{'item_index':0,'quantity':1}],[{'item_index':1,'quantity':2}],[{'item_index':1,'quantity':1}]*2,[{'item_index':1,'quantity':0}]):
    with self.assertRaises(ValidationError):ops.record_receipt(c,organization_id=self.oid,po_id=order['id'],actor_user_id=self.uid,data={'destination_index':0,'kind':'full','receiver_name':'[TEST ONLY] invalid','quantities':quantities})
   self.assertEqual(c.execute('select count(*) from procurement_receipts where purchase_order_id=?',(order['id'],)).fetchone()[0],0)
