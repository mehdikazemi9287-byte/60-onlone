"""Customer commercial orders, separate from supplier purchase orders.

Financial event execution is deliberately test-only pending actual policies and
provider integration. No seeding, grant provisioning, or production test toggle.
"""
import hashlib,json
from datetime import datetime,timezone
from app.core.errors import ValidationError,PermissionError_,ConflictError,NotFoundError
from app.services import organization_operations_service as ops

def j(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def text(v,label='شرح',maximum=2000):
 if not isinstance(v,str) or not 1<=len(v.strip())<=maximum:raise ValidationError(label+' الزامی است')
 return v.strip()
def integer(v,label='مقدار',zero=False):
 if type(v) is not int or v<(0 if zero else 1) or v>10**13:raise ValidationError(label+' نامعتبر است')
 return v
def timestamp(v):
 try:
  d=datetime.fromisoformat(v.replace('Z','+00:00'))
  if not d.tzinfo:raise ValueError()
  return d.astimezone(timezone.utc)
 except (ValueError,AttributeError,TypeError):raise ValidationError('زمان باید ISO با منطقه زمانی باشد')
def now():return datetime.now(timezone.utc)
def access(c,org,case,user):
 row=c.execute('SELECT ca.* FROM organization_operations_cases ca JOIN purchase_requests pr ON pr.id=ca.purchase_request_id AND pr.organization_id=ca.organization_id WHERE ca.id=? AND ca.organization_id=?',(case,org)).fetchone()
 if not row:raise NotFoundError('پرونده یافت نشد')
 member=c.execute("SELECT m.role FROM organization_memberships m JOIN organizations o ON o.id=m.organization_id AND o.status='active' JOIN users u ON u.id=m.user_id AND u.is_active=1 WHERE m.organization_id=? AND m.user_id=? AND m.status='active'",(org,user)).fetchone()
 role=member['role'] if member else None;caps=ops.capabilities(c,org,user)
 staff=bool(caps and ('case_manager'in caps or row['assignee_user_id']==user))
 if not staff and role not in ('organization_admin','organization_finance'):raise PermissionError_('مجوز گردش سفارش این پرونده ندارید')
 return dict(row),role,staff

def read(c,org,case,user):
 base,role,staff=access(c,org,case,user)
 meta=c.execute('SELECT * FROM customer_workflows WHERE case_id=?',(case,)).fetchone()
 quotes=[dict(q) for q in c.execute('SELECT q.*,d.decision,d.actor_user_id AS decided_by,d.reason AS decision_reason FROM customer_quotes q LEFT JOIN customer_quote_decisions d ON q.id=d.quote_id WHERE q.case_id=? ORDER BY q.revision',(case,))]
 for q in quotes:
  q['snapshot']=json.loads(q.pop('snapshot_json'))
  if not staff:q['snapshot'].pop('sources',None)
 order=c.execute('SELECT * FROM customer_orders WHERE case_id=?',(case,)).fetchone();order=dict(order) if order else None
 events=[dict(e) for e in c.execute('SELECT * FROM customer_workflow_events WHERE case_id=? ORDER BY id',(case,)) if staff or e['visibility']=='customer']
 for e in events:e['payload']=json.loads(e.pop('payload_json'))
 pr=dict(c.execute('SELECT id,title,request_number,status,destinations_json FROM purchase_requests WHERE id=? AND organization_id=?',(base['purchase_request_id'],org)).fetchone())
 pr['destinations']=json.loads(pr.pop('destinations_json'));pr['items']=[dict(r) for r in c.execute('SELECT id,free_text_description,quantity,unit FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id',(pr['id'],))]
 visible_meta=dict(meta) if meta else None
 if visible_meta and not staff:visible_meta={k:v for k,v in visible_meta.items() if k in ('case_id','version','created_at')}
 timeline=[dict(e, id='workflow:'+str(e['id']), source='workflow') for e in events]
 for e in c.execute("SELECT * FROM procurement_audit_log WHERE organization_id=? AND entity_type='purchase_request' AND entity_id=? ORDER BY id",(org,pr['id'])):
  details=json.loads(e['details_json'])
  timeline.append({'id':'request:'+str(e['id']),'action':e['event_type'],'actor_user_id':e['actor_user_id'],'created_at':e['occurred_at'],'source':'request','payload':{k:v for k,v in details.items() if k in ('reason','request_number','title')}})
 for e in c.execute('SELECT * FROM organization_operations_events WHERE case_id=? ORDER BY id',(case,)):
  after=json.loads(e['after_json']);payload={k:v for k,v in after.items() if k in ('assignee_user_id','status')}
  if staff:payload['reason']=e['reason']
  timeline.append({'id':'case:'+str(e['id']),'action':'case_'+e['action'],'actor_user_id':e['actor_user_id'],'created_at':e['created_at'],'source':'case','payload':payload})
 timeline.sort(key=lambda e:(e['created_at'],e['id']))
 actor_ids={e['actor_user_id'] for e in timeline if e['actor_user_id'] is not None}
 actor_names={r['id']:r['full_name'] for r in c.execute('SELECT id,full_name FROM users WHERE id IN ('+','.join('?' for _ in actor_ids)+')',tuple(actor_ids))} if actor_ids else {}
 for e in timeline:e['actor_name']=actor_names.get(e['actor_user_id'])
 trace={'request_id':pr['id'],'case_id':case,'accepted_quote_id':order['quote_id'] if order else None,'approval_quote_id':order['quote_id'] if order else None,'order_id':order['id'] if order else None}

 return {'trace':trace,'timeline':timeline,'request':pr,'case':base,'workflow':visible_meta,'quotes':quotes,'order':order,'events':events,'staff':staff,'role':role,
 'quantity_events':[dict(x) for x in c.execute('SELECT * FROM customer_quantity_events WHERE order_id=? ORDER BY id',(order['id'],))] if order else [],
 'payment_events':[dict(x) for x in c.execute('SELECT * FROM customer_payment_events WHERE order_id=? ORDER BY id',(order['id'],))] if order else [],
 'payment_proposals':[dict(x) for x in c.execute('SELECT p.*,e.id AS confirmed_event_id FROM customer_payment_proposals p LEFT JOIN customer_payment_events e ON e.proposal_id=p.id WHERE p.order_id=? ORDER BY p.id',(order['id'],))] if order else []}

def policy(c,quote,org,environment,financial=False):
 row=c.execute('SELECT * FROM customer_payment_policies WHERE id=? AND organization_id=?',(quote['policy_id'],org)).fetchone()
 if not row:raise ConflictError('سیاست مصوب متصل نشده است',code='policy_required')
 if row['environment']!=environment:raise ConflictError('سیاست متعلق به این محیط نیست',code='policy_required')
 if financial and environment!='test':raise ConflictError('اجرای مالی واقعی فعال نیست؛ سیاست و اتصال معتبر نیاز است',code='financial_execution_disabled')
 try:rules=json.loads(row['rules_json'])
 except (TypeError,ValueError):raise ConflictError('ساختار سیاست نامعتبر است')
 if not isinstance(rules,dict) or not isinstance(rules.get('methods'),list) or not all(m in ('cash','cheque','credit','bill') for m in rules['methods']):raise ConflictError('ساختار روش‌های سیاست نامعتبر است')
 rules['_version']=row['version'];rules['_contract_reference']=row['contract_reference']
 return rules
def balance(c,order):
 return {kind:c.execute('SELECT COALESCE(SUM(amount_minor),0) FROM customer_payment_events WHERE order_id=? AND kind=?',(order,kind)).fetchone()[0] for kind in ['collected','refunded','reserved','consumed','released']}
def settlement_signature(c,order):
 financial=[tuple(r) for r in c.execute("SELECT id,kind,amount_minor FROM customer_payment_events WHERE order_id=? AND kind!='settled' ORDER BY id",(order,))]
 quantities=[tuple(r) for r in c.execute('SELECT id,kind,quantity FROM customer_quantity_events WHERE order_id=? ORDER BY id',(order,))]
 return hashlib.sha256(j([financial,quantities]).encode()).hexdigest()

def money_event(c,order,kind,amount,user,ref,proposal=None):
 c.execute('INSERT INTO customer_payment_events(order_id,proposal_id,kind,amount_minor,actor_user_id,reference) VALUES (?,?,?,?,?,?)',(order,proposal,kind,amount,user,ref))
def mutate(c,org,case,user,action,data,key,environment,currency):
 base,role,staff=access(c,org,case,user)
 if not isinstance(data,dict):raise ValidationError('بدنه نامعتبر')
 text(key,'Idempotency-Key',128);reason=text(data.get('reason'),'دلیل')
 staff_actions={'plan','note','source','quote','prepare','dispatch','return_resolved','close','cancel'}
 customer_actions={'accept','reject','receipt','return'}
 finance_actions={'payment_method','instrument','propose_collection','propose_refund','confirm_payment','settle'}
 if action in staff_actions and not staff:raise PermissionError_('مجوز عملیات لازم است')
 if action in customer_actions and role!='organization_admin':raise PermissionError_('تأیید مدیر سازمان لازم است')
 if action in finance_actions and role!='organization_finance':raise PermissionError_('نقش مستقل مالی سازمان لازم است')
 if action not in staff_actions|customer_actions|finance_actions:raise ValidationError('اقدام ناشناخته')
 c.execute('INSERT OR IGNORE INTO customer_workflows(case_id) VALUES (?)',(case,))
 digest=hashlib.sha256(j([action,data]).encode()).hexdigest()
 replay=c.execute('SELECT * FROM customer_workflow_idempotency WHERE case_id=? AND actor_user_id=? AND key=?',(case,user,key)).fetchone()
 if replay:
  if replay['payload_hash']!=digest:raise ConflictError('کلید اقدام با داده دیگری استفاده شده است')
  return read(c,org,case,user)
 state=read(c,org,case,user);version=state['workflow']['version']
 if type(data.get('expected_version')) is not int or data['expected_version']!=version:raise ConflictError('نسخه تغییر کرده است؛ اطلاعات را تازه کنید',code='stale_version')
 if base['status']=='closed':raise ConflictError('پرونده بسته است')
 order=state['order'];quote=state['quotes'][-1] if state['quotes'] else None
 payload={'reason':reason};visibility='customer';order_id=order['id'] if order else None
 if action in ('plan','note','source'):
  visibility='internal'
  if action=='plan':
   due=data.get('due_at');timestamp(due) if due else None
   blocked=data.get('blocked_reason','')
   if not isinstance(blocked,str) or len(blocked)>2000:raise ValidationError('علت توقف نامعتبر')
   c.execute('UPDATE customer_workflows SET next_action=?,due_at=?,blocked_reason=? WHERE case_id=?',(text(data.get('next_action'),'اقدام بعدی'),due,data.get('blocked_reason','')[:2000],case));payload.update(next_action=data['next_action'],due_at=due,blocked_reason=data.get('blocked_reason',''))
  elif action=='source':
   supplier=integer(data.get('supplier_id'),'تأمین‌کننده')
   if not c.execute("SELECT id FROM suppliers WHERE id=? AND status='active'",(supplier,)).fetchone():raise ValidationError('تأمین‌کننده فعال یافت نشد')
   if data.get('outcome') not in ['requested','available','failed']:raise ValidationError('وضعیت تأمین نامعتبر')
   allocations=data.get('allocations')
   lines=c.execute('SELECT quantity FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id',(base['purchase_request_id'],)).fetchall()
   if not isinstance(allocations,list) or not allocations:raise ValidationError('تخصیص اقلام تأمین لازم است')
   seen=set()
   for a in allocations:
    if not isinstance(a,dict):raise ValidationError('تخصیص نامعتبر')
    i=integer(a.get('item_index'),'قلم',True);q=integer(a.get('quantity'),'تعداد')
    if i>=len(lines) or i in seen or q>lines[i]['quantity']:raise ValidationError('تخصیص نامعتبر')
    seen.add(i)
   payload.update(supplier_id=supplier,outcome=data['outcome'],allocations=allocations,reference=text(data.get('reference'),'مرجع استعلام'))
 elif action=='quote':
  if order:raise ConflictError('سفارش ایجاد شده؛ اصلاح نیازمند گردش مستقل است')
  if not base['assignee_user_id'] or not ops.capabilities(c,org,base['assignee_user_id']):raise ConflictError('مسئول فعال لازم است')
  pr=c.execute('SELECT * FROM purchase_requests WHERE id=? AND organization_id=?',(base['purchase_request_id'],org)).fetchone()
  if pr['status']!='approved':raise ConflictError('درخواست باید توسط سازمان تأیید شود')
  latest_sources={}
  for event in state['events']:
   if event['action']=='source':latest_sources[event['payload']['supplier_id']]=event['payload']
  available=[v for v in latest_sources.values() if v['outcome']=='available']
  if not available:raise ConflictError('پاسخ جاری تأمین لازم است')
  expiry=timestamp(data.get('expires_at'))
  if expiry<=now():raise ValidationError('اعتبار پیشنهاد باید در آینده باشد')
  lines=[dict(r) for r in c.execute('SELECT id,master_product_id,free_text_description,quantity,unit FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id',(pr['id'],))]
  covered=[0]*len(lines)
  for source in available:
   if not c.execute("SELECT id FROM suppliers WHERE id=? AND status='active'",(source['supplier_id'],)).fetchone():raise ConflictError('تأمین‌کننده دیگر فعال نیست')
   for a in source['allocations']:covered[a['item_index']]+=a['quantity']
  if covered!=[line['quantity'] for line in lines]:raise ConflictError('پوشش دقیق تأمین همه اقلام لازم است')
  prices=data.get('unit_prices_minor')
  if not isinstance(prices,list) or len(prices)!=len(lines):raise ValidationError('قیمت تک‌تک اقلام لازم است')
  for line,price in zip(lines,prices):line['unit_price_minor']=integer(price,'قیمت واحد',True)
  destinations=json.loads(pr['destinations_json'])
  if not destinations:raise ValidationError('مقصد و تخصیص اقلام لازم است')
  from app.services.procurement_service import unallocated
  if unallocated(destinations,[{'quantity':x['quantity']} for x in lines]):raise ConflictError('تخصیص مقصد برخی اقلام ناقص است',code='destinations_incomplete')
  shipping=integer(data.get('shipping_minor'),'هزینه ارسال',True);tax=integer(data.get('tax_minor'),'مالیات اعلام‌شده',True)
  total=sum(x['quantity']*x['unit_price_minor'] for x in lines)+shipping+tax
  if total<=0 or total>10**13:raise ValidationError('جمع مبلغ نامعتبر')
  pid=data.get('policy_id');terms=None
  if pid is not None:
   integer(pid,'سیاست');terms=policy(c,{'policy_id':pid},org,environment)
  snapshot={'lines':lines,'destinations':destinations,'currency':currency,'shipping_minor':shipping,'tax_minor':tax,'total_minor':total,'payment_terms':text(data.get('payment_terms'),'شرایط پرداخت'),'policy_id':pid,'official_invoice':False,'policy_terms':terms,'sources':available}
  qid=c.execute('INSERT INTO customer_quotes(case_id,revision,snapshot_json,expires_at,policy_id,created_by) VALUES (?,?,?,?,?,?)',(case,len(state['quotes'])+1,j(snapshot),expiry.isoformat(),pid,user)).lastrowid;payload.update(quote_id=qid,revision=len(state['quotes'])+1,total_minor=total,currency=currency)
 elif action in ('accept','reject'):
  if not quote or quote['id']!=data.get('quote_id') or quote['decision']:raise ConflictError('فقط آخرین نسخه تصمیم‌گیری‌نشده قابل بررسی است')
  if timestamp(quote['expires_at'])<=now():raise ConflictError('پیشنهاد منقضی شده است')
  if action=='accept':
   pr_status=c.execute('SELECT status FROM purchase_requests WHERE id=? AND organization_id=?',(base['purchase_request_id'],org)).fetchone()
   if not pr_status or pr_status['status']!='approved':raise ConflictError('درخواست دیگر در وضعیت تأییدشده نیست')
   policy(c,quote,org,environment)
  c.execute('INSERT INTO customer_quote_decisions(quote_id,actor_user_id,decision,reason) VALUES (?,?,?,?)',(quote['id'],user,'accepted' if action=='accept' else 'rejected',reason))
  if action=='accept':order_id=c.execute("INSERT INTO customer_orders(case_id,quote_id,status) VALUES (?,?,'awaiting_payment')",(case,quote['id'])).lastrowid
  payload.update(quote_id=quote['id'],order_id=order_id)
 else:
  if not order:raise ConflictError('سفارش پذیرفته‌شده لازم است')
  quote=next(q for q in state['quotes'] if q['id']==order['quote_id']);snap=quote['snapshot'];total=snap['total_minor'];b=balance(c,order_id)
  if order['status'] in ('closed','cancelled') and not (action=='close' and order['status']=='cancelled'):raise ConflictError('سفارش خاتمه یافته است')
  if action in finance_actions:
   if action!='payment_method' and order['payment_method'] not in (None,'cash'):raise ConflictError('چرخه روش غیرنقدی تکمیل نشده',code='technical_gap')
   rules=policy(c,quote,org,environment,True)
   if action=='payment_method':
    method=data.get('method')
    if method!='cash':raise ConflictError('چرخه این روش هنوز قابل اجرا نیست',code='technical_gap')
    if order['payment_method'] or method not in rules.get('methods',[]):raise ConflictError('روش پرداخت مجاز نیست یا قبلاً انتخاب شده')
    c.execute('UPDATE customer_orders SET payment_method=? WHERE id=?',(method,order_id));money_event(c,order_id,'method_selected',0,user,reason)
    if method=='credit':
     limit=integer(rules.get('credit_limit_minor'),'سقف مصوب',True)
     used=c.execute("SELECT COALESCE(SUM(CASE WHEN e.kind='reserved' THEN e.amount_minor WHEN e.kind IN ('released','collected') THEN -e.amount_minor ELSE 0 END),0) FROM customer_payment_events e JOIN customer_orders o ON o.id=e.order_id JOIN organization_operations_cases ca ON ca.id=o.case_id WHERE ca.organization_id=? AND o.payment_method='credit'",(org,)).fetchone()[0]
     if used+total>limit:raise ConflictError('اعتبار کافی نیست')
     money_event(c,order_id,'reserved',total,user,reason)
    payload['method']=method
   elif action=='instrument':
    if order['payment_method'] not in ('cheque','bill'):raise ConflictError('روش چکی یا تعهد لازم است')
    due=timestamp(data.get('due_at'));ref=text(data.get('reference'),'شناسه سند')
    if any(e['kind']=='received_instrument' for e in state['payment_events']):raise ConflictError('سند قبلاً دریافت شده')
    money_event(c,order_id,'received_instrument',total,user,ref);payload.update(due_at=due.isoformat(),reference=ref,not_collected=True)
   elif action.startswith('propose_'):
    if not order['payment_method']:raise ConflictError('روش پرداخت انتخاب نشده')
    amount=integer(data.get('amount_minor'),'مبلغ');ref=text(data.get('reference'),'مرجع تطبیق آزمایشی');kind='refund' if action=='propose_refund' else 'collection'
    proposal=c.execute('INSERT INTO customer_payment_proposals(order_id,kind,amount_minor,reference,proposer) VALUES (?,?,?,?,?)',(order_id,kind,amount,ref,user)).lastrowid;payload['proposal_id']=proposal
   elif action=='confirm_payment':
    p=c.execute('SELECT * FROM customer_payment_proposals WHERE id=? AND order_id=?',(data.get('proposal_id'),order_id)).fetchone()
    if not p or p['proposer']==user:raise PermissionError_('تأییدکننده مستقل لازم است')
    if c.execute('SELECT id FROM customer_payment_events WHERE proposal_id=?',(p['id'],)).fetchone():raise ConflictError('قبلاً تأیید شده')
    if p['kind']=='collection' and b['collected']+p['amount_minor']>total:raise ConflictError('بیش از بدهی سفارش است')
    if p['kind']=='refund':
     cap=sum(e['quantity']*snap['lines'][e['item_index']]['unit_price_minor'] for e in state['quantity_events'] if e['kind']=='return_resolved')
     if rules.get('refund_basis')!='accepted_return_units_excluding_tax_shipping':raise ConflictError('قاعده مصوب مرجوعی لازم است')
     if b['refunded']+p['amount_minor']>min(b['collected'],cap):raise ConflictError('بیش از وجه وصول‌شده یا مرجوعی پذیرفته‌شده است')
    money_event(c,order_id,'collected' if p['kind']=='collection' else 'refunded',p['amount_minor'],user,p['reference'],p['id']);payload.update(proposal_id=p['id'],test_only=True)
   elif action=='settle':
    if order['status']!='received':raise ConflictError('رسید تحویل قبل از تسویه لازم است')
    returned_value=sum(e['quantity']*snap['lines'][e['item_index']]['unit_price_minor'] for e in state['quantity_events'] if e['kind']=='return_resolved')
    if returned_value and rules.get('refund_basis')!='accepted_return_units_excluding_tax_shipping':raise ConflictError('قاعده مرجوعی مصوب لازم است')
    if b['collected']-b['refunded']!=total-returned_value:raise ConflictError('مانده با تعهد مرجوعی و مبلغ اصلاح‌شده تطبیق ندارد')
    signature=settlement_signature(c,order_id)
    if any(e['kind']=='settled' and e['reference']==signature for e in state['payment_events']):raise ConflictError('قبلاً تطبیق شده')
    money_event(c,order_id,'settled',0,user,signature)
  elif action=='prepare':
   if order['payment_method']!='cash':raise ConflictError('چرخه روش غیرنقدی تکمیل نشده',code='technical_gap')
   if order['status']!='awaiting_payment':raise ConflictError('وضعیت آماده‌سازی نامعتبر')
   rules=policy(c,quote,org,environment,True)
   latest={}
   for event in state['events']:
    if event['action']=='source':latest[event['payload']['supplier_id']]=event['payload']
   if any(latest.get(src['supplier_id'])!=src for src in snap['sources']):raise ConflictError('وضعیت تأمین از زمان پیشنهاد تغییر کرده است')
   if not order['payment_method']:raise ConflictError('روش پرداخت لازم است')
   method=order['payment_method'];permitted=(b['collected']-b['refunded']>=total or (method=='credit' and b['reserved']-b['released']>=total) or (method in rules.get('dispatch_on_received_instrument',[]) and any(e['kind']=='received_instrument' for e in state['payment_events'])))
   if not permitted:raise ConflictError('شرط پرداخت مصوب برای آماده‌سازی برقرار نیست')
   c.execute("UPDATE customer_orders SET status='preparing' WHERE id=?",(order_id,))
  elif action in ('dispatch','receipt','return','return_resolved'):
   if order['status'] not in ('preparing','dispatched','received'):raise ConflictError('وضعیت تحویل نامعتبر')
   dest=integer(data.get('destination_index'),'مقصد',True);item=integer(data.get('item_index'),'قلم',True);qty=integer(data.get('quantity'),'تعداد');ref=text(data.get('reference'),'شماره رسید / مرجع')
   if dest>=len(snap['destinations']) or item>=len(snap['lines']):raise ValidationError('قلم یا مقصد نامعتبر')
   allocated=next((a['quantity'] for a in snap['destinations'][dest]['allocations'] if a['item_index']==item),0)
   sums={k:c.execute('SELECT COALESCE(SUM(quantity),0) FROM customer_quantity_events WHERE order_id=? AND destination_index=? AND item_index=? AND kind=?',(order_id,dest,item,k)).fetchone()[0] for k in ['dispatch','receipt','return','return_resolved']}
   limit={'dispatch':allocated-sums['dispatch'],'receipt':sums['dispatch']-sums['receipt'],'return':sums['receipt']-sums['return'],'return_resolved':sums['return']-sums['return_resolved']}[action]
   if c.execute('SELECT id FROM customer_quantity_events WHERE order_id=? AND kind=? AND destination_index=? AND item_index=? AND reference=?',(order_id,action,dest,item,ref)).fetchone():raise ConflictError('این مرجع برای همین قلم و مقصد قبلاً ثبت شده است')
   if qty>limit:raise ConflictError('تعداد از مانده مجاز این قلم/مقصد بیشتر است')
   c.execute('INSERT INTO customer_quantity_events(order_id,destination_index,item_index,kind,quantity,actor_user_id,reference) VALUES (?,?,?,?,?,?,?)',(order_id,dest,item,action,qty,user,ref))
   if action=='dispatch':
    latest={}
    for event in state['events']:
     if event['action']=='source':latest[event['payload']['supplier_id']]=event['payload']
    if any(latest.get(src['supplier_id'])!=src or not c.execute("SELECT id FROM suppliers WHERE id=? AND status='active'",(src['supplier_id'],)).fetchone() for src in snap['sources']):raise ConflictError('وضعیت تأمین برای ارسال معتبر نیست')
    if order['payment_method']=='credit' and not b['consumed']:
     policy(c,quote,org,environment,True);money_event(c,order_id,'consumed',total,user,reason)
    c.execute("UPDATE customer_orders SET status='dispatched' WHERE id=?",(order_id,))
   received=c.execute("SELECT COALESCE(SUM(quantity),0) FROM customer_quantity_events WHERE order_id=? AND kind='receipt'",(order_id,)).fetchone()[0]
   if received==sum(x['quantity'] for x in snap['lines']):c.execute("UPDATE customer_orders SET status='received' WHERE id=?",(order_id,))
   payload.update(destination_index=dest,item_index=item,quantity=qty,reference=ref,financial_refund=False)
  elif action=='cancel':
   if state['quantity_events'] or b['collected'] or b['consumed']:raise ConflictError('لغو نیازمند اصلاح تحویل/مالی مستقل است')
   if b['reserved']>b['released']:policy(c,quote,org,environment,True);money_event(c,order_id,'released',b['reserved']-b['released'],user,reason)
   c.execute("UPDATE customer_orders SET status='cancelled' WHERE id=?",(order_id,))
  elif action=='close':
   if order['status']=='cancelled':
    if state['quantity_events'] or b['collected'] or b['refunded'] or b['consumed'] or b['reserved']!=b['released'] or any(e['kind']=='received_instrument' for e in state['payment_events']):raise ConflictError('تعهد باز در پرونده لغوشده وجود دارد')
    ops.mutate(c,org,user,'transition',{'status':'closed','expected_version':base['version'],'reason':reason},'workflow-close-'+hashlib.sha256(key.encode()).hexdigest(),case)
   else:
    if order['status']!='received':raise ConflictError('رسید همه اقلام لازم است')
    unresolved=c.execute("SELECT COALESCE(SUM(CASE WHEN kind='return' THEN quantity WHEN kind='return_resolved' THEN -quantity ELSE 0 END),0) FROM customer_quantity_events WHERE order_id=?",(order_id,)).fetchone()[0]
    if unresolved:raise ConflictError('مرجوعی باز وجود دارد')
    signature=settlement_signature(c,order_id)
    if not any(e['kind']=='settled' and e['reference']==signature for e in state['payment_events']):raise ConflictError('تطبیق جاری پس از آخرین تغییر لازم است')
    c.execute("UPDATE customer_orders SET status='closed' WHERE id=?",(order_id,))
    ops.mutate(c,org,user,'transition',{'status':'closed','expected_version':base['version'],'reason':reason},'workflow-close-'+hashlib.sha256(key.encode()).hexdigest(),case)
 c.execute('INSERT INTO customer_workflow_events(case_id,actor_user_id,action,visibility,payload_json) VALUES (?,?,?,?,?)',(case,user,action,visibility,j(payload)))
 c.execute('UPDATE customer_workflows SET version=version+1 WHERE case_id=? AND version=?',(case,version))
 result=read(c,org,case,user)
 c.execute('INSERT INTO customer_workflow_idempotency VALUES (?,?,?,?,?)',(case,user,key,digest,j(result)))
 return result
