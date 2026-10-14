"""Versioned product management; identifiers/source history retained, financial snapshots untouched."""
import hashlib,json,re
from flask import jsonify,request
from app.core.deps import current_user,get_db,require_auth
from app.core.errors import ConflictError,NotFoundError,ValidationError
from app.api.v1.admin_content import body,text,assert_admin,now
from app.services import master_catalog_service as svc
from app.services import product_channel_policy as policy

def state(c,mid):
 if type(mid) is not int or not 1<=mid<=9223372036854775807:raise ValidationError('شناسه کالا نامعتبر است')
 m=c.execute('SELECT * FROM master_products WHERE id=?',(mid,)).fetchone()
 if not m:raise NotFoundError('کالا یافت نشد')
 profile=c.execute('SELECT * FROM direct_product_profiles WHERE master_product_id=?',(mid,)).fetchone()
 skus=[dict(x) for x in c.execute('SELECT * FROM products WHERE master_product_id=? ORDER BY id',(mid,))]
 aliases=[dict(x) for x in c.execute('SELECT * FROM product_identifiers_legacy WHERE master_product_id=? ORDER BY id',(mid,))]
 ids=[dict(x) for x in c.execute('SELECT i.* FROM product_identifiers i JOIN products p ON p.id=i.product_id WHERE p.master_product_id=? ORDER BY i.id',(mid,))]
 offers=[dict(x) for x in c.execute('SELECT o.* FROM seller_offers o JOIN products p ON p.id=o.product_id WHERE p.master_product_id=? ORDER BY o.id',(mid,))]
 pubs=[dict(x) for x in c.execute('SELECT * FROM catalog_publications WHERE master_product_id=? ORDER BY slug',(mid,))]
 return {'master':dict(m),'profile':dict(profile) if profile else None,'skus':skus,'aliases':aliases,'identifiers':ids,'offers':offers,'publications':pubs,'code_aliases':[dict(x) for x in c.execute('SELECT a.* FROM product_code_aliases a JOIN products p ON p.id=a.product_id WHERE p.master_product_id=? ORDER BY a.code',(mid,))]}
def version(s):return hashlib.sha256(json.dumps(s,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def current_fields(c,s):
 p=s['profile'] or {};m=s['master']
 code=p.get('sku') or next((x['identifier_value'] for x in s['aliases'] if x['identifier_type']=='INTERNAL' and x['is_active']),None) or next((x['sku'] for x in s['skus'] if x['sku']),None)
 reference=p.get('source_reference')
 if reference is None:
  row=c.execute("SELECT metadata_json FROM audit_logs WHERE entity_type='master_product' AND entity_id=? AND action='catalog.master_created' ORDER BY id DESC LIMIT 1",(str(m['id']),)).fetchone()
  reference=json.loads(row[0] or '{}').get('source_reference') if row else None
 return {'sku':code,'source_kind':p.get('source_kind'),'source_supplier_id':p.get('source_supplier_id'),'source_reference':reference,'supply_channel':p.get('supply_channel') or 'both','status':m['status'],'sku_updates':[{'id':x['id'],'sku':x['sku']} for x in s['skus']]}
def safe_numbers(value):
 if type(value) is int and abs(value)>9007199254740991:return str(value)
 if isinstance(value,dict):return {k:safe_numbers(v) for k,v in value.items()}
 if isinstance(value,list):return [safe_numbers(v) for v in value]
 return value
def history(c,mid,page=1):
 sql="""SELECT 'audit-'||a.id AS id,a.action,a.created_at,a.actor_user_id,a.metadata_json FROM audit_logs a WHERE a.entity_type='master_product' AND a.entity_id=?
 UNION ALL SELECT 'media-'||e.id,'media.'||e.action,e.created_at,e.actor_user_id,json_object('reason',e.reason,'asset_id',e.asset_id) FROM media_events e WHERE e.master_product_id=?
 UNION ALL SELECT 'offer-'||e.id,'offer.'||e.action,e.created_at,e.actor_user_id,json_object('offer_id',e.offer_id,'before',json(e.before_json),'after',json(e.after_json)) FROM offer_events e JOIN seller_offers o ON o.id=e.offer_id JOIN products p ON p.id=o.product_id WHERE p.master_product_id=?"""
 args=(str(mid),mid,mid);total=c.execute('SELECT COUNT(*) FROM ('+sql+')',args).fetchone()[0]
 items=[]
 for r in c.execute('SELECT e.*,u.full_name FROM ('+sql+') e LEFT JOIN users u ON u.id=e.actor_user_id ORDER BY e.created_at DESC,e.id DESC LIMIT 40 OFFSET ?',(*args,(page-1)*40)):
  item=dict(r);item['metadata']=safe_numbers(json.loads(item.pop('metadata_json') or '{}'));items.append(item)
 return {'items':items,'total':total,'page':page,'page_size':40}
def view(c,mid):
 s=state(c,mid);fields=current_fields(c,s);hist=history(c,mid)
 offer_views=[]
 for o in s['offers']:
  scope=policy.offer_fields(c,o['product_id'],o['channel']);offer_views.append({'id':o['id'],'product_id':o['product_id'],'supplier_id':o['supplier_id'],'status':o['status'],**scope})
 return {'product':svc.get_master_product(c,mid),'profile':s['profile'],'fields':fields,'version':version(s),'identifiers':svc.list_identifiers(c,mid),'linked_skus':[{'id':x['id'],'sku':x['sku'],'slug':x['slug'],'is_active':bool(x['is_active'])} for x in s['skus']],'offers':offer_views,'history':hist['items'],'history_total':hist['total'],'history_page_size':hist['page_size'],'price':None,'stock':None,'commerce_sku_created':bool(s['skus']),'public_content_count':sum(bool(x['is_visible']) for x in s['publications'])}
def register_management(bp):
 @bp.get('/admin/catalog/products/<int:mid>/management')
 @require_auth('admin')
 def get(mid):
  with get_db().read_transaction() as c:assert_admin(c);return jsonify(view(c,mid))
 @bp.get('/admin/catalog/products/<int:mid>/management/history')
 @require_auth('admin')
 def history_get(mid):
  raw=request.args.get('page','1')
  if not raw.isascii() or not raw.isdigit() or not 1<=int(raw)<=100000:raise ValidationError('صفحه نامعتبر است')
  with get_db().read_transaction() as c:assert_admin(c);state(c,mid);return jsonify(history(c,mid,int(raw)))
 @bp.patch('/admin/catalog/products/<int:mid>/management')
 @require_auth('admin')
 def edit(mid):
  from app.api.v1.direct_product_form import identifiers,duplicates
  d=body();allowed={'sku','source_kind','source_supplier_id','source_reference','status','supply_channel','sku_updates','expected_version','reason','confirm_real_source','confirm_commercial_effect','edit_request_key'}
  if set(d)-allowed:raise ValidationError('فیلد ویرایش غیرمجاز است')
  key=d.get('edit_request_key');reason=text(d.get('reason',''),500)
  if len(reason)<3 or not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):raise ValidationError('دلیل تغییر و کلید درخواست معتبر لازم است')
  hashed=hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  with get_db().write_transaction() as c:
   assert_admin(c);actor=current_user()['id']
   prior=c.execute("SELECT metadata_json FROM audit_logs WHERE actor_user_id=? AND action='catalog.management_updated' AND entity_type='master_product' AND entity_id=? AND json_valid(metadata_json) AND json_extract(metadata_json,'$.edit_request_key')=? ORDER BY id LIMIT 1",(actor,str(mid),key)).fetchone()
   if prior:
    if json.loads(prior[0]).get('payload_hash')!=hashed:raise ConflictError('کلید درخواست برای ویرایش دیگری استفاده شده است')
    return jsonify({**view(c,mid),'replayed':True,'changed':False})
   s=state(c,mid);before=current_fields(c,s)
   if s['master']['status']=='merged' or s['master']['provenance'] not in ('real','test'):raise ConflictError('کالای ادغام‌شده یا نمونه قابل ویرایش تجاری نیست')
   if d.get('expected_version')!=version(s):raise ConflictError('کالا، SKU یا Offer تغییر کرده؛ آخرین نسخه را بازبینی کنید',code='product_management_stale')
   code=identifiers({'sku':d.get('sku')})[0][1]
   if duplicates(c,{'sku':code},exclude_master_id=mid):raise ConflictError('کد کالا قبلاً ثبت شده است',code='product_duplicate')
   if d.get('source_kind') not in ('supplier','catalog','manual','other'):raise ValidationError('نوع منبع معتبر لازم است')
   ref=text(d.get('source_reference',''),500);supplier=d.get('source_supplier_id')
   if len(ref)<3:raise ValidationError('مرجع منبع لازم است')
   if d['source_kind']=='supplier':
    if type(supplier) is not int or not 1<=supplier<=9223372036854775807 or not c.execute("SELECT 1 FROM suppliers WHERE id=? AND provenance='real'",(supplier,)).fetchone():raise ValidationError('تأمین‌کننده واقعی موجود لازم است')
   elif supplier is not None:raise ValidationError('تأمین‌کننده برای این نوع منبع مجاز نیست')
   if d.get('status') not in ('active','draft') or d.get('supply_channel') not in policy.CHANNELS:raise ValidationError('وضعیت یا نوع عرضه نامعتبر است')
   raw=d.get('sku_updates')
   if not isinstance(raw,list) or len(raw)!=len(s['skus']):raise ValidationError('فهرست کامل SKUهای مرتبط لازم است')
   updates=[];seen=set();codes=set();existing={x['id']:x for x in s['skus']}
   for u in raw:
    if not isinstance(u,dict) or set(u)!={'id','sku'} or type(u.get('id')) is not int or u['id'] not in existing or u['id'] in seen:raise ValidationError('SKU متعلق به این کالا نیست یا تکراری است')
    val=text(u['sku'],100)
    if not val or val in codes:raise ValidationError('SKU خالی یا تکراری در فهرست است')
    if c.execute('SELECT 1 FROM product_code_aliases WHERE code=? AND product_id!=?',(val,u['id'])).fetchone() or c.execute('SELECT 1 FROM products WHERE sku=? AND id!=?',(val,u['id'])).fetchone() or duplicates(c,{'sku':val},exclude_master_id=mid):raise ConflictError('SKU فروشگاهی قبلاً استفاده شده است',code='product_duplicate')
    seen.add(u['id']);codes.add(val);updates.append({'id':u['id'],'sku':val})
   after={'sku':code,'source_kind':d['source_kind'],'source_supplier_id':supplier,'source_reference':ref,'status':d['status'],'supply_channel':d['supply_channel'],'sku_updates':sorted(updates,key=lambda x:x['id'])}
   source_changed=any(before[k]!=after[k] for k in ('source_kind','source_supplier_id','source_reference'))
   if source_changed and d.get('confirm_real_source') is not True:raise ValidationError('منبع جدید باید صریحاً تأیید شود')
   significant=any(before[k]!=after[k] for k in ('sku','sku_updates','status','supply_channel'))
   if significant and (s['skus'] or any(x['is_visible'] for x in s['publications'])) and d.get('confirm_commercial_effect') is not True:raise ValidationError('اثر تغییر بر SKU و عرضه را تأیید کنید')
   if before==after:return jsonify({**view(c,mid),'changed':False,'replayed':False})
   # Retain the old INTERNAL aliases. No source/snapshot/history row is deleted.
   for value in dict.fromkeys([v for v in [before['sku'],code,*[x['sku'] for x in s['skus']],*[u['sku'] for u in updates]] if v]):
    old=c.execute("SELECT 1 FROM product_identifiers_legacy WHERE master_product_id=? AND identifier_type='INTERNAL' AND identifier_value=? AND supplier_id IS NULL AND organization_id IS NULL",(mid,value)).fetchone()
    claimed=c.execute("SELECT 1 FROM product_identifiers_legacy WHERE identifier_type='INTERNAL' AND identifier_value=? AND supplier_id IS NULL AND organization_id IS NULL",(value,)).fetchone()
    if not old and not claimed:svc.add_identifier(c,master_product_id=mid,identifier_type='INTERNAL',identifier_value=value)
   offer_scope_before=[{'id':o['id'],**policy.offer_fields(c,o['product_id'],o['channel'])} for o in s['offers']]
   c.execute('INSERT INTO direct_product_profiles(master_product_id,sku,source_kind,source_supplier_id,supply_channel,source_reference) VALUES (?,?,?,?,?,?) ON CONFLICT(master_product_id) DO UPDATE SET sku=excluded.sku,source_kind=excluded.source_kind,source_supplier_id=excluded.source_supplier_id,supply_channel=excluded.supply_channel,source_reference=excluded.source_reference',(mid,code,after['source_kind'],supplier,after['supply_channel'],ref))
   for u in updates:
    if u['sku']!=existing[u['id']]['sku']:
     for value in (existing[u['id']]['sku'],u['sku']):
      c.execute('INSERT OR IGNORE INTO product_code_aliases(code,product_id,created_at) VALUES (?,?,?)',(value,u['id'],now()))
    c.execute('UPDATE products SET sku=? WHERE id=?',(u['sku'],u['id']))
    c.execute("UPDATE product_identifiers SET identifier_value=? WHERE product_id=? AND identifier_type='sku' AND namespace='' AND supplier_id IS NULL AND identifier_value=?",(u['sku'],u['id'],existing[u['id']]['sku']))
   c.execute('UPDATE master_products SET status=?,updated_at=? WHERE id=?',(after['status'],now(),mid))
   affected=[{'id':o['id'],**policy.offer_fields(c,o['product_id'],o['channel'])} for o in s['offers']]
   metadata={'before':before,'after':after,'reason':reason,'source_reference':ref,'source_confirmed':d.get('confirm_real_source') is True,'affected_offers':affected,'offer_scope_before':offer_scope_before,'edit_request_key':key,'payload_hash':hashed}
   c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'catalog.management_updated','master_product',?,?,?)",(actor,str(mid),json.dumps(metadata,ensure_ascii=False),now()))
   return jsonify({**view(c,mid),'changed':True,'replayed':False})
