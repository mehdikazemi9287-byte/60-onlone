"""Reconcile commitments with approved request lines; never infer arbitrary destination splits."""
import json
from collections import defaultdict
from app.core.errors import ConflictError,ValidationError

def requested(c,prid):return [dict(x) for x in c.execute('SELECT * FROM purchase_request_items WHERE purchase_request_id=? ORDER BY id',(prid,))]

def link(line,items):
 if line.get('purchase_request_item_id') is not None:
  match=[p for p in items if p['id']==line['purchase_request_item_id']]
 else:
  match=[p for p in items if p['master_product_id']==line.get('master_product_id') and p['free_text_description']==line.get('free_text_description') and p['unit']==line.get('unit')]
 if len(match)!=1:raise ConflictError('تطبیق دقیق ردیف سفارش با درخواست تأییدشده لازم است',code='procurement_line_unresolved')
 p=match[0]
 if any(k in line and p[k]!=line[k] for k in ('master_product_id','free_text_description','unit')):raise ValidationError('ردیف استعلام با قلم تأییدشده تطبیق ندارد')
 return p

def committed(c,prid,orders=False):
 items=requested(c,prid);amounts=defaultdict(int)
 if orders:
  rows=c.execute("SELECT ri.*,poi.quantity AS committed_quantity FROM purchase_order_items poi JOIN purchase_orders po ON po.id=poi.purchase_order_id JOIN rfq_items ri ON ri.id=poi.rfq_item_id WHERE po.purchase_request_id=? AND po.status<>'cancelled'",(prid,)).fetchall()
 else:
  rows=c.execute("SELECT ri.*,qi.quantity_available AS committed_quantity FROM supplier_quote_items qi JOIN supplier_quotes q ON q.id=qi.supplier_quote_id JOIN rfq_items ri ON ri.id=qi.rfq_item_id JOIN rfqs r ON r.id=q.rfq_id WHERE r.purchase_request_id=? AND q.status='awarded'",(prid,)).fetchall()
 for r in rows:
  if type(r['committed_quantity']) is not int or r['committed_quantity']<1:raise ConflictError('مقدار تاریخی تعهد نیازمند بررسی است')
  amounts[link(dict(r),items)['id']]+=r['committed_quantity']
 return items,amounts

def quote_lines(c,qid):
 return [dict(x) for x in c.execute('SELECT ri.*,qi.quantity_available AS committed_quantity FROM supplier_quote_items qi JOIN rfq_items ri ON ri.id=qi.rfq_item_id WHERE qi.supplier_quote_id=? ORDER BY qi.id',(qid,))]

def proposal(c,prid,qid,orders=False):
 items,amounts=committed(c,prid,orders=orders)
 for line in quote_lines(c,qid):amounts[link(line,items)['id']]+=line['committed_quantity']
 if any(amounts[p['id']]>p['quantity'] for p in items):raise ConflictError('مقدار سفارش از درخواست تأییدشده بیشتر می‌شود',code='procurement_overcommitted')
 return all(amounts[p['id']]==p['quantity'] for p in items)

def assert_complete_orders(c,prid):
 items,amounts=committed(c,prid,orders=True)
 if not items or any(amounts[p['id']]!=p['quantity'] for p in items):raise ConflictError('همه اقلام و مقادیر درخواست هنوز سفارش نشده‌اند',code='procurement_incomplete')

def allocation_requirements(c,prid,qid):
 row=c.execute('SELECT destinations_json FROM purchase_requests WHERE id=?',(prid,)).fetchone()
 destinations=json.loads(row[0]) if row and row[0] else []
 items=requested(c,prid);indexes={x['id']:i for i,x in enumerate(items)};quantities=defaultdict(int)
 for line in quote_lines(c,qid):quantities[indexes[link(line,items)['id']]]+=line['committed_quantity']
 used=defaultdict(int)
 for order in c.execute("SELECT * FROM purchase_orders WHERE purchase_request_id=? AND status<>'cancelled'",(prid,)):
  if order['destinations_json_snapshot'] is None:
   # Derive only unambiguous full-line legacy allocations, never guess old partial city shares.
   lines=[dict(x) for x in c.execute('SELECT ri.*,poi.quantity AS committed_quantity FROM purchase_order_items poi JOIN rfq_items ri ON ri.id=poi.rfq_item_id WHERE poi.purchase_order_id=?',(order['id'],))]
   old=defaultdict(int)
   for line in lines:old[indexes[link(line,items)['id']]]+=line['committed_quantity']
   for idx,qty in old.items():
    if qty!=items[idx]['quantity'] and len([d for d in destinations if any(a['item_index']==idx and a['quantity']>0 for a in d.get('allocations',[]))])>1:
     raise ConflictError('تخصیص تاریخی مقدار جزئی به شهرها مشخص نیست؛ مدرک مقصد سفارش قبلی لازم است',code='legacy_destination_review_required')
   previous=[]
   for di,d in enumerate(destinations):
    for a in d.get('allocations',[]):
     idx=a['item_index']
     if idx in old:previous.append((di,idx,min(a['quantity'],old[idx])))
  else:
   previous=[(di,a['item_index'],a['quantity']) for di,d in enumerate(json.loads(order['destinations_json_snapshot'])) for a in d.get('allocations',[])]
  for di,idx,qty in previous:used[di,idx]+=qty
 requirements=[]
 for idx,qty in quantities.items():
  p=items[idx];targets=[]
  for di,d in enumerate(destinations):
   planned=sum(a['quantity'] for a in d.get('allocations',[]) if a['item_index']==idx);available=planned-used[di,idx]
   if available<0:raise ConflictError('تخصیص مقصدهای قبلی نیازمند بررسی است',code='destination_overcommitted')
   targets.append({'destination_index':di,'city':d.get('city'),'province':d.get('province'),'available':available})
  title=c.execute('SELECT canonical_name_fa FROM master_products WHERE id=?',(p['master_product_id'],)).fetchone() if p['master_product_id'] else None
  requirements.append({'purchase_request_item_id':p['id'],'item_index':idx,'title':title[0] if title else p['free_text_description'],'unit':p['unit'],'quantity':qty,'destinations':targets})
 return destinations,requirements

def quote_destinations(c,prid,qid,allocations=None):
 destinations,requirements=allocation_requirements(c,prid,qid)
 if not destinations:
  if allocations is not None and (not isinstance(allocations,list) or allocations):raise ValidationError('درخواست مقصد تخصیص‌یافته ندارد')
  return []
 rows=[]
 if allocations is None:
  for r in requirements:
   targets=[d for d in r['destinations'] if d['available']>0];total=sum(d['available'] for d in targets)
   if r['quantity']==total:
    rows.extend({'purchase_request_item_id':r['purchase_request_item_id'],'destination_index':d['destination_index'],'quantity':d['available']} for d in targets)
   elif len(targets)==1 and r['quantity']<=targets[0]['available']:
    rows.append({'purchase_request_item_id':r['purchase_request_item_id'],'destination_index':targets[0]['destination_index'],'quantity':r['quantity']})
   else:raise ConflictError('برای مقدار جزئی چندشهر، سهم مقصدها را صریح انتخاب کنید',code='partial_destination_allocation_required')
 else:
  if not isinstance(allocations,list) or len(allocations)>len(requirements)*len(destinations):raise ValidationError('تخصیص مقصد نامعتبر است')
  rows=allocations
 byid={r['purchase_request_item_id']:r for r in requirements};seen=set();totals=defaultdict(int);result=[{**d,'allocations':[]} for d in destinations]
 for a in rows:
  if not isinstance(a,dict) or any(type(a.get(k)) is not int for k in ('purchase_request_item_id','destination_index','quantity')):raise ValidationError('قلم، مقصد و مقدار باید عدد صحیح باشند')
  pid,di,qty=a['purchase_request_item_id'],a['destination_index'],a['quantity'];r=byid.get(pid)
  if not r or di<0 or di>=len(destinations) or qty<0 or (pid,di) in seen:raise ValidationError('قلم یا مقصد تکراری/نامعتبر است')
  seen.add((pid,di));available=r['destinations'][di]['available']
  if qty>available:raise ConflictError('مقدار این مقصد از سهم تأییدشده باقی‌مانده بیشتر است',code='destination_overcommitted')
  totals[pid]+=qty
  if qty:result[di]['allocations'].append({'item_index':r['item_index'],'quantity':qty})
 if any(totals[r['purchase_request_item_id']]!=r['quantity'] for r in requirements):raise ValidationError('جمع تخصیص شهرها باید برابر مقدار همان پیشنهاد باشد')
 return result

def order_destinations(c,po):
 if 'destinations_json_snapshot' in po.keys() and po['destinations_json_snapshot'] is not None:return json.loads(po['destinations_json_snapshot'])
 if not po['purchase_request_id']:return []
 # Read-only legacy projection; rows/snapshots are never backfilled or modified.
 row=c.execute('SELECT destinations_json FROM purchase_requests WHERE id=?',(po['purchase_request_id'],)).fetchone()
 return json.loads(row[0]) if row and row[0] else []

def summary(c,prid):
 items,awarded=committed(c,prid);_,ordered=committed(c,prid,orders=True)
 return [{'purchase_request_item_id':p['id'],'requested':p['quantity'],'awarded':awarded[p['id']],'ordered':ordered[p['id']],'unawarded':max(0,p['quantity']-awarded[p['id']]),'unordered':max(0,p['quantity']-ordered[p['id']])} for p in items]

def delivery_indexes(destinations):
 if not destinations:return {0}
 return {i for i,d in enumerate(destinations) if any(a['quantity']>0 for a in d.get('allocations',[]))}

def deliveries_complete(c,po):
 destinations=order_destinations(c,po)
 expected=delivery_indexes(destinations) if po['destinations_json_snapshot'] is not None else set(range(max(1,len(destinations))))
 done={r[0] for r in c.execute("SELECT destination_index FROM procurement_deliveries WHERE purchase_order_id=? AND status='delivered'",(po['id'],))}
 return bool(expected) and expected<=done
