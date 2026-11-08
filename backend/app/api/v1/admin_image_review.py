"""Prioritize actual missing-image records; never substitute another product image."""
import json
from flask import Blueprint,jsonify,request
from app.core.deps import get_db,current_user,require_auth
from app.core.errors import ValidationError,ConflictError,NotFoundError
from app.api.v1.admin_content import assert_admin,body,text,now
from app.api.v1.admin_console import pagination
from app.api.v1.admin_catalog_sources import sources
bp=Blueprint('admin_image_review',__name__,url_prefix='/api/v1/admin')
MISSING="""NOT EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(m.image_urls_json) THEN CASE WHEN json_type(m.image_urls_json)='array' THEN m.image_urls_json ELSE '[]' END ELSE '[]' END) j WHERE j.type='text' AND (j.value LIKE 'https://%' OR (j.value LIKE '/%' AND j.value NOT LIKE '//%')))"""
PRIORITY="""CASE WHEN EXISTS(SELECT 1 FROM catalog_publications p WHERE p.master_product_id=m.id AND p.is_visible=1) THEN 1 WHEN EXISTS(SELECT 1 FROM pack_items i JOIN packs p ON p.id=i.pack_id WHERE i.master_product_id=m.id AND p.provenance='real' AND p.status='published') THEN 2 WHEN m.status='active' AND (dp.supply_channel IS NULL OR dp.supply_channel IN ('organization','both')) THEN 3 ELSE 4 END"""
@bp.get('/media/image-review')
@require_auth('admin')
def listing():
 p,size,off=pagination();q='%'+request.args.get('q','').strip()[:200]+'%';priority=request.args.get('priority','')
 if priority and priority not in ('1','2','3','4'):raise ValidationError('اولویت نامعتبر است')
 with get_db().read_transaction() as c:
  assert_admin(c)
  sql="SELECT m.id,m.canonical_name_fa,m.brand,m.unit,m.package_quantity,m.category,m.status,m.specifications_json,dp.source_reference AS source_note,dp.supply_channel,r.outcome,r.checked_reference,r.reason,r.row_version,r.reviewed_at,"+PRIORITY+" AS priority FROM master_products m LEFT JOIN direct_product_profiles dp ON dp.master_product_id=m.id LEFT JOIN catalog_image_reviews r ON r.master_product_id=m.id WHERE m.provenance='real' AND m.status<>'merged' AND "+MISSING
  outer='SELECT * FROM ('+sql+') WHERE (canonical_name_fa LIKE ? OR COALESCE(brand,\'\') LIKE ?)';args=(q,q)
  if priority:outer+=' AND priority=?';args=(*args,int(priority))
  total=c.execute('SELECT COUNT(*) FROM ('+outer+')',args).fetchone()[0]
  rows=c.execute(outer+' ORDER BY priority,id LIMIT ? OFFSET ?',(*args,size,off)).fetchall()
  return jsonify({'items':[{**{k:x[k] for k in x.keys() if k!='specifications_json'},'source_records':sources(x['specifications_json'])} for x in rows],'total':total,'page':p,'page_size':size,'priority_basis':'actual publication eligibility, published pack membership, active organization channel, remainder'})

@bp.patch('/media/image-review/<int:mid>')
@require_auth('admin')
def mark(mid):
 d=body()
 if set(d)-{'outcome','checked_reference','reason','expected_version'}:raise ValidationError('فیلد بررسی تصویر نامعتبر است')
 if d.get('outcome') not in ('needs_review','no_verified_source'):raise ValidationError('وضعیت بررسی نامعتبر است')
 ref=text(d.get('checked_reference'),2000);reason=text(d.get('reason'),500)
 if len(ref)<3 or len(reason)<3:raise ValidationError('مرجع بررسی‌شده و دلیل لازم است')
 if type(d.get('expected_version')) is not int or d['expected_version']<0:raise ValidationError('نسخه بررسی لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  if not c.execute("SELECT 1 FROM master_products WHERE id=? AND provenance='real' AND status<>'merged'",(mid,)).fetchone():raise NotFoundError('مرجع واقعی یافت نشد')
  old=c.execute('SELECT * FROM catalog_image_reviews WHERE master_product_id=?',(mid,)).fetchone();v=old['row_version'] if old else 0
  if v!=d['expected_version']:raise ConflictError('بررسی دیگری ثبت شده؛ آخرین نسخه را دریافت کنید')
  c.execute('INSERT INTO catalog_image_reviews VALUES(?,?,?,?,?,?,?) ON CONFLICT(master_product_id) DO UPDATE SET outcome=excluded.outcome,checked_reference=excluded.checked_reference,reason=excluded.reason,row_version=excluded.row_version,reviewed_by=excluded.reviewed_by,reviewed_at=excluded.reviewed_at',(mid,d['outcome'],ref,reason,v+1,current_user()['id'],now()))
  after=dict(c.execute('SELECT * FROM catalog_image_reviews WHERE master_product_id=?',(mid,)).fetchone())
  c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'catalog.image_reviewed','master_product',?,?,?)",(current_user()['id'],str(mid),json.dumps({'before':dict(old) if old else None,'after':after},ensure_ascii=False),now()))
  return jsonify({'review':after})
