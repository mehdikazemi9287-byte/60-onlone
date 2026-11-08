"""Edit descriptive master data and its SKU projection without changing identity, sale eligibility or money."""
import hashlib,json
from flask import Blueprint,jsonify
from app.core.deps import get_db,current_user,require_auth
from app.core.errors import ValidationError,NotFoundError,ConflictError
from app.api.v1.admin_content import body,text,now,assert_admin
bp=Blueprint('admin_product_content',__name__,url_prefix='/api/v1/admin/catalog/products')
def snapshot(c,mid):
 if not 1<=mid<=9223372036854775807:raise ValidationError('شناسه کالا نامعتبر است')
 m=c.execute('SELECT * FROM master_products WHERE id=?',(mid,)).fetchone()
 if not m or m['provenance']!='real' or m['status']=='merged':raise NotFoundError('مرجع واقعی قابل ویرایش یافت نشد')
 m=dict(m);skus=[dict(r) for r in c.execute('SELECT * FROM products WHERE master_product_id=? ORDER BY id',(mid,))];pubs=[dict(r) for r in c.execute('SELECT * FROM catalog_publications WHERE master_product_id=?',(mid,))]
 token=hashlib.sha256(json.dumps({'master':m,'skus':skus,'publications':pubs},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 try:spec=json.loads(m['specifications_json'] or '{}')
 except (ValueError,TypeError):raise ValidationError('مشخصات ذخیره‌شده نیاز به بازبینی دارد')
 if not isinstance(spec,dict):raise ValidationError('ساختار مشخصات ذخیره‌شده نامعتبر است')
 visible=any(r['is_active'] for r in skus) or any(r['is_visible'] for r in pubs)
 return m,skus,{'id':m['id'],'canonical_name_fa':m['canonical_name_fa'],'brand':m['brand'],'category':m['category'],'unit':m['unit'],'status':m['status'],'canonical_name_en':m['canonical_name_en'] or '', 'country_of_origin':m['country_of_origin'] or '', 'description_fa':m['description_fa'] or '', 'specifications':spec,'version':token,'affects_public_content':visible,'linked_sku_count':len(skus)}
@bp.get('/<int:mid>/editor')
@require_auth('admin')
def get(mid):
 with get_db().read_transaction() as c:return jsonify({'product':snapshot(c,mid)[2]})
@bp.patch('/<int:mid>/editor')
@require_auth('admin')
def edit(mid):
 d=body()
 if set(d)-{'description_fa','canonical_name_en','country_of_origin','specifications','expected_version','reason','confirm_public_change'}:raise ValidationError('فقط محتوای توصیفی در این فرم تغییر می‌کند')
 desc=text(d.get('description_fa'),10000);name=text(d.get('canonical_name_en'),300);country=text(d.get('country_of_origin'),100);reason=text(d.get('reason'),500);spec=d.get('specifications')
 if len(reason)<3 or not isinstance(spec,dict):raise ValidationError('دلیل و مشخصات نامعتبر است')
 with get_db().write_transaction() as c:
  assert_admin(c);m,skus,p=snapshot(c,mid)
  if d.get('expected_version')!=p['version']:raise ConflictError('کالا یا SKU پس از دریافت تغییر کرده است؛ آخرین نسخه را بررسی کنید')
  if p['affects_public_content'] and d.get('confirm_public_change') is not True:raise ValidationError('تأیید تغییر محتوای کالای قابل نمایش لازم است')
  if spec==p['specifications']:
   cleaned=p['specifications']
  else:
   if len(spec)>40:raise ValidationError('حداکثر ۴۰ مشخصهٔ متنی مجاز است')
   cleaned={}
   for k,v in spec.items():
    key=text(k,80);val=text(v,500)
    if not key or key in cleaned:raise ValidationError('عنوان مشخصات باید غیرخالی و یکتا باشد')
    cleaned[key]=val
  before={k:p[k] for k in ('description_fa','canonical_name_en','country_of_origin','specifications')};after={'description_fa':desc,'canonical_name_en':name,'country_of_origin':country,'specifications':cleaned}
  needs_sku_sync=any(r['description_fa']!=desc for r in skus)
  if before!=after or needs_sku_sync:
   c.execute('UPDATE master_products SET description_fa=?,canonical_name_en=?,country_of_origin=?,specifications_json=?,updated_at=? WHERE id=?',(desc,name or None,country or None,json.dumps(cleaned,ensure_ascii=False),now(),mid))
   c.execute('UPDATE products SET description_fa=? WHERE master_product_id=?',(desc,mid))
   c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'catalog.content_updated','master_product',?,?,?)",(current_user()['id'],str(mid),json.dumps({'before':before,'after':after,'reason':reason,'linked_sku_count':len(skus)},ensure_ascii=False),now()))
  return jsonify({'product':snapshot(c,mid)[2]})
