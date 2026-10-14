"""Persist real-catalogue selections; draft storage never asserts a price or commits a purchase."""
import json,hashlib
from flask import Blueprint,jsonify,request
from app.core.deps import get_db,current_user,require_auth
from app.core.errors import ValidationError,ConflictError,PermissionError_,NotFoundError
from app.api.v1.admin_content import body,text,now
from app.services import procurement_service as pr
bp=Blueprint('saved_pack_drafts',__name__,url_prefix='/api/v1/me/pack-drafts')

def integer(x,name):
 if type(x) is not int or not 1<=x<=100000:raise ValidationError(name+' باید عدد صحیح معتبر باشد')
 return x

def organization(c,oid,write=False):
 if oid is None:return None
 if type(oid) is not int or not 1<=oid<=9223372036854775807:raise ValidationError('شناسه سازمان نامعتبر است')
 m=pr._assert_org_member(c,current_user()['id'],oid)
 if write:pr._assert_org_accepts_intake(c,oid)
 return m

def row(c,did):
 r=c.execute('SELECT * FROM saved_pack_drafts WHERE id=?',(did,)).fetchone()
 if not r:raise NotFoundError('پک ذخیره‌شده یافت نشد')
 m=organization(c,r['organization_id'])
 if r['created_by']!=current_user()['id'] and (not m or not pr._can_procure(m)):raise PermissionError_('مجوز مدیریت این پک را ندارید')
 return dict(r)

def data(c,d):
 if set(d)-{'title','items','count','organization_id','expected_version','request_key','status'}:raise ValidationError('پک فقط اقلام و تعداد نگه می‌دارد؛ قیمت کلاینت معتبر نیست')
 title=text(d.get('title'),200)
 if not title:raise ValidationError('نام پک لازم است')
 organization(c,d.get('organization_id'),write=True)
 count=integer(d.get('count'),'تعداد پک');items=d.get('items')
 if not isinstance(items,list) or not 1<=len(items)<=50:raise ValidationError('۱ تا ۵۰ قلم واقعی انتخاب کنید')
 out=[];seen=set()
 for x in items:
  if not isinstance(x,dict) or set(x)!={'slug','quantity'}:raise ValidationError('قلم پک نامعتبر است')
  slug=text(x['slug'],200);qty=integer(x['quantity'],'تعداد قلم')
  if slug in seen:raise ValidationError('کالای تکراری در پک مجاز نیست')
  p=c.execute("SELECT p.id,p.slug,p.title_fa,p.master_product_id FROM products p LEFT JOIN master_products m ON m.id=p.master_product_id WHERE p.slug=? AND p.provenance='real' AND p.is_active=1 AND (m.id IS NULL OR m.status='active')",(slug,)).fetchone()
  if not p:raise ValidationError('کالا واقعی و فعال در کاتالوگ یافت نشد')
  from app.services import storefront_service
  storefront_service.product(c,slug)
  seen.add(slug);out.append({'slug':slug,'quantity':qty,'title':p['title_fa']})
 return {'title':title,'organization_id':d.get('organization_id'),'draft':{'items':out,'count':count}}

def view(r):
 return {'id':r['id'],'title':r['title'],'organization_id':r['organization_id'],'created_by':r['created_by'],'status':r['status'],'row_version':r['row_version'],'created_at':r['created_at'],'updated_at':r['updated_at'],'draft':json.loads(r['draft_json'])}

def event(c,did,action,before,after):
 c.execute('INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,?,?,?,?,?)',(current_user()['id'],action,'pack_draft',str(did),json.dumps({'before':before,'after':after},ensure_ascii=False),now()))

@bp.get('')
@require_auth()
def listing():
 with get_db().read_transaction() as c:
  from app.api.v1.admin_console import pagination
  page,size,off=pagination();status=request.args.get('status','draft')
  if status not in ('draft','archived'):raise ValidationError('وضعیت فهرست نامعتبر است')
  raw=request.args.get('organization_id');oid=None
  if raw:
   if not raw.isascii() or not raw.isdigit():raise ValidationError('شناسه سازمان نامعتبر است')
   oid=int(raw);m=organization(c,oid)
   where='WHERE organization_id=? AND status=? AND (created_by=? OR ?=1)';args=(oid,status,current_user()['id'],int(pr._can_procure(m)))
  else:where='WHERE created_by=? AND organization_id IS NULL AND status=?';args=(current_user()['id'],status)
  total=c.execute('SELECT COUNT(*) FROM saved_pack_drafts '+where,args).fetchone()[0]
  rows=c.execute('SELECT * FROM saved_pack_drafts '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',(*args,size,off)).fetchall()
  return jsonify({'items':[view(dict(x)) for x in rows],'total':total,'page':page,'page_size':size})

@bp.get('/<int:did>')
@require_auth()
def get(did):
 with get_db().read_transaction() as c:return jsonify({'pack':view(row(c,did))})

@bp.post('')
@require_auth()
def create():
 d=body();key=text(d.get('request_key'),100)
 if len(key)<8:raise ValidationError('کلید درخواست لازم است')
 with get_db().write_transaction() as c:
  hashed=hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!='request_key'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  old=c.execute('SELECT * FROM saved_pack_drafts WHERE created_by=? AND request_key=?',(current_user()['id'],key)).fetchone()
  if old:
   if old['request_hash']!=hashed:raise ConflictError('کلید تکراری با محتوای متفاوت')
   return jsonify({'pack':view(row(c,old['id'])),'replayed':True})
  cleaned=data(c,d)
  stamp=now();did=c.execute('INSERT INTO saved_pack_drafts(created_by,organization_id,title,draft_json,request_key,request_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(current_user()['id'],cleaned['organization_id'],cleaned['title'],json.dumps(cleaned['draft'],ensure_ascii=False),key,hashed,stamp,stamp)).lastrowid
  r=row(c,did);event(c,did,'pack_draft.created',None,view(r));return jsonify({'pack':view(r),'replayed':False}),201

@bp.patch('/<int:did>')
@require_auth()
def update(did):
 d=body()
 with get_db().write_transaction() as c:
  old=row(c,did)
  if type(d.get('expected_version')) is not int or old['row_version']!=d['expected_version']:raise ConflictError('پک تغییر کرده؛ آخرین نسخه را دریافت کنید')
  if set(d)=={'status','expected_version'} and d['status'] in ('draft','archived'):
   c.execute('UPDATE saved_pack_drafts SET status=?,row_version=row_version+1,updated_at=? WHERE id=?',(d['status'],now(),did))
   after=row(c,did);event(c,did,'pack_draft.status_changed',view(old),view(after));return jsonify({'pack':view(after)})
  cleaned=data(c,d)
  if cleaned['organization_id']!=old['organization_id']:raise ValidationError('پک شخصی و سازمانی باید در همان دامنه اولیه بماند')
  status=d.get('status','draft')
  if status not in ('draft','archived'):raise ValidationError('وضعیت پک نامعتبر است')
  c.execute('UPDATE saved_pack_drafts SET title=?,draft_json=?,status=?,row_version=row_version+1,updated_at=? WHERE id=?',(cleaned['title'],json.dumps(cleaned['draft'],ensure_ascii=False),status,now(),did))
  after=row(c,did);event(c,did,'pack_draft.updated',view(old),view(after));return jsonify({'pack':view(after)})
