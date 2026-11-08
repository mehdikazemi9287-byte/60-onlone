"""Supplier workbench over existing supplier/offer/source records; no commerce values rewritten."""
import hashlib,json,re
from flask import Blueprint,jsonify,request
from app.core.deps import get_db,current_user,require_auth
from app.core.errors import ValidationError,ConflictError
from app.api.v1.admin_content import assert_admin,body,text,now
from app.services import supplier_service as service
bp=Blueprint('admin_supplier_profile',__name__,url_prefix='/api/v1/admin')
EDIT=('legal_name','display_name','phone','email','notes')
def snapshot(c,sid):
 s=service.get_supplier(c,supplier_id=sid)
 version=hashlib.sha256(json.dumps(s,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
 return s,version

def audit(c,sid,action,before,after,reason):
 c.execute('INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,?,?,?,?,?)',(current_user()['id'],action,'supplier',str(sid),json.dumps({'before':before,'after':after,'reason':reason},ensure_ascii=False),now()))

@bp.get('/suppliers/<int:sid>/profile')
@require_auth('admin')
def profile(sid):
 with get_db().read_transaction() as c:
  assert_admin(c);s,v=snapshot(c,sid)
  locations=service.list_locations(c,supplier_id=sid)
  counters=c.execute('SELECT COUNT(*) AS offers,COUNT(DISTINCT product_id) AS products,MAX(last_price_confirmed_at) AS last_price_confirmation,MAX(last_inventory_confirmed_at) AS last_stock_confirmation FROM seller_offers WHERE supplier_id=?',(sid,)).fetchone()
  events=c.execute("SELECT a.id,a.action,a.actor_user_id,u.full_name AS actor_name,a.created_at,a.metadata_json FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_user_id WHERE a.entity_type='supplier' AND a.entity_id=? ORDER BY a.id DESC LIMIT 40",(str(sid),)).fetchall()
  return jsonify({'supplier':s,'version':v,'locations':locations,'summary':dict(counters),'onboarding_events':service.list_onboarding_events(c,supplier_id=sid),'history':[{**dict(x),'metadata':json.loads(x['metadata_json'])} for x in events]})

@bp.patch('/suppliers/<int:sid>/profile')
@require_auth('admin')
def edit(sid):
 d=body()
 if set(d)-set(EDIT)-{'expected_version','reason'}:raise ValidationError('فقط اطلاعات پروفایل قابل ویرایش است؛ شناسه ملی و اطلاعات مالی ثابت‌اند')
 reason=text(d.get('reason'),500)
 if len(reason)<3:raise ValidationError('دلیل تغییر لازم است')
 values={k:(None if d.get(k) is None else text(d[k],2000 if k=='notes' else 200)) for k in EDIT}
 if not values['legal_name'] or not values['display_name']:raise ValidationError('نام حقوقی و نمایشی لازم است')
 if values['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']):raise ValidationError('ایمیل نامعتبر است')
 with get_db().write_transaction() as c:
  assert_admin(c);s,v=snapshot(c,sid)
  if d.get('expected_version')!=v:raise ConflictError('پروفایل تغییر کرده است؛ آخرین نسخه را دریافت کنید')
  before={k:s[k] for k in EDIT}
  if before!=values:
   c.execute('UPDATE suppliers SET legal_name=?,display_name=?,phone=?,email=?,notes=?,updated_at=? WHERE id=?',(*(values[k] for k in EDIT),now(),sid))
   audit(c,sid,'supplier.profile_updated',before,values,reason)
  s,v=snapshot(c,sid);return jsonify({'supplier':s,'version':v})

@bp.post('/suppliers/<int:sid>/review')
@require_auth('admin')
def review(sid):
 d=body();reason=text(d.get('reason'),500)
 if set(d)-{'expected_version','reason','to_stage','status','confirm'} or len(reason)<3 or d.get('confirm') is not True:raise ValidationError('اقدام و دلیل تأییدشده لازم است')
 if ('to_stage' in d)==('status' in d):raise ValidationError('یک اقدام پذیرش یا وضعیت انتخاب کنید')
 with get_db().write_transaction() as c:
  assert_admin(c);s,v=snapshot(c,sid)
  if d.get('expected_version')!=v:raise ConflictError('پروفایل تغییر کرده است؛ آخرین نسخه را دریافت کنید')
  if 'to_stage' in d:after=service.advance_onboarding_stage(c,supplier_id=sid,to_stage=d['to_stage'],actor_user_id=current_user()['id'],note=reason)
  else:
   after=service.update_supplier_status(c,supplier_id=sid,status=d['status'])
  if s!=after:audit(c,sid,'supplier.reviewed',s,after,reason)
  return jsonify({'supplier':after,'version':snapshot(c,sid)[1]})
