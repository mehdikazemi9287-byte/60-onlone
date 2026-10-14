"""Business console read models and controlled metadata. Does not settle funds or activate credit."""
import json
import re
from datetime import date
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from flask import Blueprint,jsonify,request
from app.core.deps import require_auth,current_user,get_db,get_settings
from app.core.errors import ValidationError,ConflictError,NotFoundError
from app.api.v1.admin_content import body,text,now,safe_link,assert_admin

bp=Blueprint('admin_console',__name__,url_prefix='/api/v1/admin')
def pagination():
 try:p=int(request.args.get('page','1'))
 except ValueError:raise ValidationError('صفحه نامعتبر است')
 if not 1<=p<=1000000:raise ValidationError('صفحه نامعتبر است')
 return p,25,(p-1)*25
def minor_fields(row):
 d=dict(row)
 for k,v in d.items():
  if k.endswith('_minor') and v is not None:
   if type(v) is not int:raise ValidationError('مبلغ ذخیره‌شده نیازمند بررسی مالی است')
   d[k]=str(v)
 return d

@bp.get('/customers')
@require_auth('admin')
def customers():
 p,size,off=pagination();q='%'+request.args.get('q','').strip()[:200]+'%'
 with get_db().read_transaction() as c:
  where="WHERE (role='customer' OR EXISTS (SELECT 1 FROM orders o WHERE o.user_id=users.id AND o.organization_id IS NULL) OR EXISTS (SELECT 1 FROM customer_requests r WHERE r.user_id=users.id AND r.organization_id IS NULL)) AND (full_name LIKE ? OR email LIKE ?)";args=(q,q)
  count=c.execute('SELECT COUNT(*) FROM users '+where,args).fetchone()[0]
  rows=c.execute('SELECT id,full_name,email,is_active,created_at FROM users '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',(*args,size,off)).fetchall()
  return jsonify({'items':[dict(r) for r in rows],'total':count,'page':p,'page_size':size})

@bp.get('/orders')
@require_auth('admin')
def orders():
 p,size,off=pagination();q='%'+request.args.get('q','').strip()[:200]+'%'
 with get_db().read_transaction() as c:
  where='WHERE o.organization_id IS NULL AND o.order_number LIKE ?'
  total=c.execute('SELECT COUNT(*) FROM orders o '+where,(q,)).fetchone()[0]
  rows=c.execute('SELECT o.id,o.order_number,o.user_id,o.status,o.total_minor,o.currency,o.placed_at,u.full_name FROM orders o JOIN users u ON u.id=o.user_id '+where+' ORDER BY o.id DESC LIMIT ? OFFSET ?',(q,size,off)).fetchall()
  return jsonify({'items':[minor_fields(r) for r in rows],'total':total,'page':p,'page_size':size})

@bp.get('/orders/<int:oid>')
@require_auth('admin')
def order_detail(oid):
 with get_db().read_transaction() as c:
  order=c.execute('SELECT * FROM orders WHERE id=? AND organization_id IS NULL',(oid,)).fetchone()
  if not order:raise NotFoundError('سفارش شخصی یافت نشد')
  return jsonify({'order':minor_fields(order),'items':[minor_fields(r) for r in c.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id',(oid,))]})

@bp.get('/notifications')
@require_auth('admin')
def notifications():
 p,size,off=pagination()
 with get_db().read_transaction() as c:
  total=c.execute('SELECT COUNT(*) FROM user_notifications').fetchone()[0]
  rows=c.execute('SELECT n.id,n.user_id,n.kind,n.title,n.body,n.link,n.created_at,n.read_at,u.full_name FROM user_notifications n JOIN users u ON u.id=n.user_id ORDER BY n.id DESC LIMIT ? OFFSET ?',(size,off)).fetchall()
  return jsonify({'items':[dict(r) for r in rows],'total':total,'page':p,'page_size':size,'delivery_channel':'in_app'})

@bp.post('/notifications')
@require_auth('admin')
def notify():
 d=body();uid=d.get('user_id');title=text(d.get('title'),200);message=text(d.get('message'),2000);link=safe_link(d.get('link',''))
 if type(uid) is not int or uid<1 or not title or not message or d.get('confirm_recipient') is not True:raise ValidationError('مخاطب، متن و تأیید گیرنده لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  if not c.execute('SELECT 1 FROM users WHERE id=? AND is_active=1',(uid,)).fetchone():raise NotFoundError('کاربر فعال یافت نشد')
  nid=c.execute("INSERT INTO user_notifications(user_id,kind,title,body,link,created_at) VALUES (?,'admin_message',?,?,?,?)",(uid,title,message,link,now())).lastrowid
  c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'notification.created','notification',?,'{}',?)",(current_user()['id'],str(nid),now()))
  return jsonify({'notification_id':nid,'delivery_channel':'in_app'}),201

@bp.get('/audit')
@require_auth('admin')
def audit():
 p,size,off=pagination()
 union="""SELECT 'system' AS source,id,action,actor_user_id,entity_type,CAST(entity_id AS TEXT) AS entity_id,created_at FROM audit_logs
 UNION ALL SELECT 'procurement',id,event_type,actor_user_id,entity_type,CAST(entity_id AS TEXT),occurred_at FROM procurement_audit_log
 UNION ALL SELECT 'connector',id,action,actor_user_id,'connector',CAST(connector_account_id AS TEXT),created_at FROM connector_audit_log
 UNION ALL SELECT 'access',id,action,actor_user_id,scope,CAST(subject_user_id AS TEXT),created_at FROM role_assignment_events
 UNION ALL SELECT 'content',id,action,actor_user_id,'page',CAST(page_id AS TEXT),created_at FROM cms_events
 UNION ALL SELECT 'media',id,action,actor_user_id,'media',asset_id,created_at FROM media_events
 UNION ALL SELECT 'settings',id,'settings.updated',actor_user_id,'store','1',created_at FROM admin_setting_events
 UNION ALL SELECT 'contract',id,action,actor_user_id,'contract',CAST(contract_id AS TEXT),created_at FROM organization_contract_events"""
 with get_db().read_transaction() as c:
  total=c.execute('SELECT COUNT(*) FROM ('+union+')').fetchone()[0]
  rows=c.execute('SELECT * FROM ('+union+') ORDER BY datetime(created_at) DESC,source,id DESC LIMIT ? OFFSET ?',(size,off)).fetchall()
  return jsonify({'items':[dict(r) for r in rows],'total':total,'page':p,'page_size':size})

@bp.get('/reports/overview')
@require_auth('admin')
def reports():
 with get_db().read_transaction() as c:
  result={'personal_orders_by_status':[dict(r) for r in c.execute('SELECT status,COUNT(*) AS count FROM orders WHERE organization_id IS NULL GROUP BY status ORDER BY status')],
          'organization_requests_by_status':[dict(r) for r in c.execute("SELECT p.status,COUNT(*) AS count FROM purchase_requests p JOIN organizations o ON o.id=p.organization_id WHERE o.provenance='real' GROUP BY p.status ORDER BY p.status")],
          'document_totals_by_currency':[minor_fields(r) for r in c.execute('SELECT currency,COUNT(*) AS count,SUM(total_minor) AS total_minor FROM orders WHERE organization_id IS NULL GROUP BY currency')],
          'as_of':now(),'money_definition':'stored_order_document_totals_not_collected_revenue'}
  return jsonify(result)

DEFAULT_SETTINGS={'support_email':'','support_phone':'','business_timezone':'UTC','order_contact_note':''}
def settings_value(c):
 r=c.execute('SELECT * FROM admin_store_settings WHERE id=1').fetchone()
 return {'values':json.loads(r['value_json']),'row_version':r['row_version'],'updated_at':r['updated_at']} if r else {'values':DEFAULT_SETTINGS,'row_version':0,'updated_at':None}

@bp.get('/settings')
@require_auth('admin')
def settings():
 with get_db().read_transaction() as c:d=settings_value(c)
 s=get_settings();d['runtime']={'environment':s.app_env,'currency':s.currency,'payment_provider_name':s.payment_provider,'sepidar':'not_connected'}
 return jsonify(d)

@bp.put('/settings')
@require_auth('admin')
def settings_save():
 d=body();values=d.get('values')
 if not isinstance(values,dict) or set(values)!=set(DEFAULT_SETTINGS):raise ValidationError('فیلدهای تنظیمات نامعتبر است')
 v={k:text(val,1000 if k=='order_contact_note' else 254) for k,val in values.items()}
 if v['support_email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v['support_email']):raise ValidationError('ایمیل پشتیبانی نامعتبر است')
 try:ZoneInfo(v['business_timezone'])
 except (ZoneInfoNotFoundError,ValueError):raise ValidationError('منطقه زمانی نامعتبر است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  old=settings_value(c)
  if type(d.get('expected_version')) is not int or d['expected_version']!=old['row_version']:raise ConflictError('تنظیمات تغییر کرده است؛ آخرین نسخه را دریافت کنید')
  encoded=json.dumps(v,ensure_ascii=False);stamp=now();actor=current_user()['id']
  if old['row_version']:c.execute('UPDATE admin_store_settings SET value_json=?,row_version=row_version+1,updated_by=?,updated_at=? WHERE id=1',(encoded,actor,stamp))
  else:c.execute('INSERT INTO admin_store_settings(id,value_json,updated_by,updated_at) VALUES (1,?,?,?)',(encoded,actor,stamp))
  c.execute('INSERT INTO admin_setting_events(actor_user_id,before_json,after_json,created_at) VALUES (?,?,?,?)',(actor,json.dumps(old['values'],ensure_ascii=False),encoded,stamp))
  return jsonify(settings_value(c))

@bp.get('/organizations/<int:oid>/contracts')
@require_auth('admin')
def contracts(oid):
 with get_db().read_transaction() as c:
  if not c.execute('SELECT 1 FROM organizations WHERE id=?',(oid,)).fetchone():raise NotFoundError('سازمان یافت نشد')
  return jsonify({'items':[dict(r) for r in c.execute('SELECT * FROM organization_contracts WHERE organization_id=? ORDER BY id DESC',(oid,))]})

def contract_values(d):
 title=text(d.get('title'),200);ref=text(d.get('contract_reference'),200);notes=text(d.get('notes',''),2000);status=d.get('status','draft');start=d.get('start_date') or None;end=d.get('end_date') or None
 if not title or not ref or status not in ('draft','recorded','expired','archived'):raise ValidationError('عنوان، مرجع یا وضعیت قرارداد نامعتبر است')
 try:
  if start:start=date.fromisoformat(start).isoformat()
  if end:end=date.fromisoformat(end).isoformat()
 except (ValueError,TypeError):raise ValidationError('تاریخ قرارداد نامعتبر است')
 if start and end and end<start:raise ValidationError('پایان قرارداد قبل از شروع است')
 return title,ref,start,end,notes,status

@bp.post('/organizations/<int:oid>/contracts')
@require_auth('admin')
def contract_create(oid):
 d=body();v=contract_values(d)
 with get_db().write_transaction() as c:
  assert_admin(c)
  if not c.execute("SELECT 1 FROM organizations WHERE id=? AND provenance='real'",(oid,)).fetchone():raise NotFoundError('سازمان واقعی یافت نشد')
  actor=current_user()['id'];stamp=now()
  cid=c.execute('INSERT INTO organization_contracts(organization_id,title,contract_reference,start_date,end_date,notes,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(oid,*v,actor,stamp,stamp)).lastrowid
  c.execute("INSERT INTO organization_contract_events(contract_id,actor_user_id,action,reason,created_at) VALUES (?,?,'created','ثبت مرجع قرارداد؛ بدون امضا یا فعال‌سازی اعتبار',?)",(cid,actor,stamp))
  return jsonify({'contract':dict(c.execute('SELECT * FROM organization_contracts WHERE id=?',(cid,)).fetchone())}),201

@bp.put('/organizations/<int:oid>/contracts/<int:cid>')
@require_auth('admin')
def contract_edit(oid,cid):
 d=body();v=contract_values(d);reason=text(d.get('reason',''),500)
 if not reason:raise ValidationError('دلیل تغییر قرارداد لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  old=c.execute('SELECT * FROM organization_contracts WHERE id=? AND organization_id=?',(cid,oid)).fetchone()
  if not old:raise NotFoundError('قرارداد این سازمان یافت نشد')
  if type(d.get('expected_version')) is not int or d['expected_version']!=old['row_version']:raise ConflictError('نسخه قرارداد تغییر کرده است')
  stamp=now();c.execute('UPDATE organization_contracts SET title=?,contract_reference=?,start_date=?,end_date=?,notes=?,status=?,row_version=row_version+1,updated_at=? WHERE id=?',(*v,stamp,cid))
  c.execute("INSERT INTO organization_contract_events(contract_id,actor_user_id,action,reason,created_at) VALUES (?,?,'edited',?,?)",(cid,current_user()['id'],reason,stamp))
  return jsonify({'contract':dict(c.execute('SELECT * FROM organization_contracts WHERE id=?',(cid,)).fetchone())})

@bp.patch('/users/<int:uid>/role')
@require_auth('admin')
def user_role(uid):
    from app.core.deps import ROLE_HIERARCHY
    from app.core.errors import PermissionError_
    d=body();role=d.get('role');active=d.get('is_active');reason=text(d.get('reason',''),500)
    if role not in ROLE_HIERARCHY or type(active) is not bool or len(reason)<3 or d.get('confirm_scope') is not True:
        raise ValidationError('نقش، وضعیت، دلیل و تأیید محدوده دسترسی لازم است')
    with get_db().write_transaction() as c:
        assert_admin(c)
        actor=current_user()['id']
        permitted=c.execute("SELECT 1 FROM users WHERE id=? AND role='admin' AND is_active=1",(actor,)).fetchone()
        if not permitted:raise PermissionError_('مجوز مدیریت دیگر فعال نیست')
        old=c.execute('SELECT id,role,is_active,email FROM users WHERE id=?',(uid,)).fetchone()
        if not old:raise NotFoundError('کاربر یافت نشد')
        if d.get('expected_role')!=old['role'] or type(d.get('expected_active')) is not bool or d['expected_active']!=bool(old['is_active']) or d.get('expected_email')!=old['email']:
            raise ConflictError('اطلاعات کاربر تغییر کرده است؛ دوباره انتخاب کنید')
        if uid==actor and (role!='admin' or not active):raise ConflictError('کاهش یا غیرفعال‌سازی دسترسی حساب جاری از این صفحه مجاز نیست')
        if old['role']=='admin' and old['is_active'] and (role!='admin' or not active):
            if c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]<=1:raise ConflictError('آخرین مدیر فعال نمی‌تواند حذف یا غیرفعال شود')
        if role=='supplier' and not c.execute("SELECT 1 FROM suppliers WHERE user_id=? UNION SELECT 1 FROM supplier_users WHERE user_id=? AND status='active'",(uid,uid)).fetchone():
            raise ValidationError('ابتدا حساب تأمین‌کننده را برای این کاربر متصل کنید')
        if role=='org_admin' and not c.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND role='organization_admin' AND status='active'",(uid,)).fetchone():
            raise ValidationError('عضویت فعال مدیر سازمان لازم است')
        before={'role':old['role'],'is_active':bool(old['is_active'])};after={'role':role,'is_active':active}
        if before!=after:
            c.execute('UPDATE users SET role=?,is_active=? WHERE id=?',(role,int(active),uid))
            meta=json.dumps({'before':before,'after':after,'reason':reason},ensure_ascii=False)
            c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'user.role_changed','user',?,?,?)",(actor,str(uid),meta,now()))
        return jsonify({'user':dict(c.execute('SELECT id,full_name,email,role,is_active FROM users WHERE id=?',(uid,)).fetchone())})

@bp.get('/offer-review')
@require_auth('admin')
def offer_review():
 p,size,off=pagination();q='%'+request.args.get('q','').strip()[:200]+'%'
 with get_db().read_transaction() as c:
  where='WHERE (p.title_fa LIKE ? OR s.display_name LIKE ? OR COALESCE(o.supplier_sku,\'\') LIKE ?)';args=(q,q,q)
  supplier=request.args.get('supplier_id')
  if supplier is not None:
   if not supplier.isascii() or not supplier.isdigit() or not 1<=int(supplier)<=9223372036854775807:raise ValidationError('شناسه تأمین‌کننده نامعتبر است')
   where+=' AND o.supplier_id=?';args=(*args,int(supplier))
  total=c.execute('SELECT COUNT(*) FROM seller_offers o JOIN products p ON p.id=o.product_id JOIN suppliers s ON s.id=o.supplier_id JOIN supplier_locations l ON l.id=o.supplier_location_id '+where,args).fetchone()[0]
  rows=c.execute('SELECT o.*,p.title_fa,p.currency,s.display_name AS supplier_name,l.city,l.province FROM seller_offers o JOIN products p ON p.id=o.product_id JOIN suppliers s ON s.id=o.supplier_id JOIN supplier_locations l ON l.id=o.supplier_location_id '+where+' ORDER BY o.id DESC LIMIT ? OFFSET ?',(*args,size,off)).fetchall()
  from app.services.product_channel_policy import offer_fields
  return jsonify({'items':[{**minor_fields(r),**offer_fields(c,r['product_id'],r['channel'])} for r in rows],'total':total,'page':p,'page_size':size})

@bp.get('/offers/<int:oid>/history')
@require_auth('admin')
def offer_history(oid):
 if oid<1 or oid>9223372036854775807:raise ValidationError('شناسه Offer نامعتبر است')
 p,size,off=pagination()
 with get_db().read_transaction() as c:
  offer=c.execute('SELECT o.*,p.title_fa,p.currency,s.display_name AS supplier_name,l.city,l.province FROM seller_offers o JOIN products p ON p.id=o.product_id JOIN suppliers s ON s.id=o.supplier_id JOIN supplier_locations l ON l.id=o.supplier_location_id WHERE o.id=?',(oid,)).fetchone()
  if not offer:raise NotFoundError('Offer یافت نشد')
  total=c.execute('SELECT COUNT(*) FROM offer_price_history WHERE offer_id=?',(oid,)).fetchone()[0]
  rows=c.execute('SELECT id,old_price_minor,new_price_minor,changed_by_supplier_id,changed_at FROM offer_price_history WHERE offer_id=? ORDER BY id DESC LIMIT ? OFFSET ?',(oid,size,off)).fetchall()
  from app.services.product_channel_policy import offer_fields
  return jsonify({'offer':{**minor_fields(offer),**offer_fields(c,offer['product_id'],offer['channel'])},'items':[minor_fields(r) for r in rows],'total':total,'page':p,'page_size':size,'price_write_owner':'supplier'})
