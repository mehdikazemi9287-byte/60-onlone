"""Reviewed identity updates, with CAS across the affected catalog projection."""
import hashlib,json
from flask import Blueprint,jsonify
from app.core.deps import get_db,current_user,require_auth
from app.core.errors import ValidationError,NotFoundError,ConflictError
from app.api.v1.admin_content import body,text,now,assert_admin
from app.services import catalog_structure_service as structure
bp=Blueprint('admin_product_identity',__name__,url_prefix='/api/v1/admin/catalog/products')
FIELDS={'canonical_name_fa','brand','category'}

def target(c,mid):
 if not 1<=mid<=9223372036854775807:raise ValidationError('شناسه نامعتبر است')
 m=c.execute('SELECT * FROM master_products WHERE id=?',(mid,)).fetchone()
 if not m or m['provenance']!='real' or m['status']=='merged':raise NotFoundError('مرجع واقعی قابل ویرایش یافت نشد')
 return dict(m)

def proposal(c,m,d):
 if set(d)!=FIELDS:raise ValidationError('نام، برند و دسته باید صریح ارسال شوند')
 p={k:text(d[k],300 if k=='canonical_name_fa' else 150) for k in FIELDS}
 if not p['canonical_name_fa'] or not p['brand']:raise ValidationError('نام و برند نباید خالی باشند')
 if not c.execute("SELECT 1 FROM categories WHERE slug=? AND level='category'",(p['category'],)).fetchone():raise ValidationError('دسته موجود سطح category لازم است')
 return p

def preview(c,mid,d=None):
 m=target(c,mid);p=proposal(c,m,d) if d is not None else {k:m[k] or '' for k in FIELDS}
 keys={structure.family_group_key(m),structure.family_group_key({**m,**p})}
 all_m=[dict(r) for r in c.execute("SELECT * FROM master_products WHERE provenance='real' AND status<>'merged' ORDER BY id")]
 ids={mid};fids=set()
 while True:
  old=(len(ids),len(fids),len(keys))
  for row in all_m:
   key=structure.family_group_key(row)
   if row['id'] in ids or key in keys or row['family_id'] in fids:
    ids.add(row['id']);keys.add(key)
    if row['family_id']:fids.add(row['family_id'])
  if old==(len(ids),len(fids),len(keys)):break
 if len(ids)>5000:raise ValidationError('مجموعه اثر بزرگ است؛ بازبینی گروهی لازم است')
 members=[r for r in all_m if r['id'] in ids]
 marks=','.join('?' for _ in ids);args=sorted(ids)
 skus=[dict(r) for r in c.execute(f'SELECT * FROM products WHERE master_product_id IN ({marks}) ORDER BY id',args)]
 pubs=[dict(r) for r in c.execute(f'SELECT * FROM catalog_publications WHERE master_product_id IN ({marks}) ORDER BY master_product_id',args)]
 # Entire family/taxonomy metadata also guards allocation collisions and category ancestry.
 families=[dict(r) for r in c.execute('SELECT * FROM product_families ORDER BY id')]
 cats=[dict(r) for r in c.execute('SELECT * FROM categories ORDER BY id')]
 token=hashlib.sha256(json.dumps({'proposal':p,'members':members,'skus':skus,'publications':pubs,'families':families,'categories':cats},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 public=any(r['is_active'] for r in skus) or any(r['is_visible'] for r in pubs)
 result={'id':mid,'current':{k:m[k] for k in FIELDS},'proposed':p,'version':token,'affected_members':[{'id':r['id'],'name':r['canonical_name_fa'],'brand':r['brand'],'category':r['category'],'family_id':r['family_id']} for r in members], 'linked_sku_count':len(skus),'affects_public_content':public,'requires_family_confirmation':len(ids)>1}
 return result,m,keys,skus,pubs

@bp.get('/<int:mid>/identity')
@require_auth('admin')
def get(mid):
 with get_db().read_transaction() as c:return jsonify({'product':preview(c,mid)[0]})

@bp.post('/<int:mid>/identity/preview')
@require_auth('admin')
def review(mid):
 d=body()
 with get_db().read_transaction() as c:return jsonify({'product':preview(c,mid,d)[0]})

@bp.patch('/<int:mid>/identity')
@require_auth('admin')
def edit(mid):
 d=body()
 if set(d)-FIELDS-{'expected_version','reason','confirm_public_change','confirm_family_change'}:raise ValidationError('فیلد غیرمجاز')
 reason=text(d.get('reason'),500)
 if len(reason)<3:raise ValidationError('دلیل تغییر لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  info,m,keys,skus,pubs=preview(c,mid,{k:d.get(k) for k in FIELDS})
  if d.get('expected_version')!=info['version']:raise ConflictError('مجموعه اثر تغییر کرده؛ پیش‌نمایش تازه لازم است')
  if info['affects_public_content'] and d.get('confirm_public_change') is not True:raise ValidationError('تأیید اثر عمومی لازم است')
  if info['requires_family_confirmation'] and d.get('confirm_family_change') is not True:raise ValidationError('تأیید اثر روی اعضای خانواده لازم است')
  p=info['proposed'];cat=c.execute("SELECT id FROM categories WHERE slug=? AND level='category'",(p['category'],)).fetchone()['id']
  owned=[r for r in skus if r['master_product_id']==mid]
  needs_sync=any((r['title_fa'],r['brand_fa'],r['category_id'])!=(p['canonical_name_fa'],p['brand'],cat) for r in owned) or any(r['master_product_id']==mid and r['category_slug']!=p['category'] for r in pubs)
  if info['current']==p and not needs_sync:return jsonify({'product':info,'changed':False})
  structure.initialize_family_keys(c)
  c.execute('UPDATE master_products SET canonical_name_fa=?,brand=?,category=?,updated_at=? WHERE id=?',(p['canonical_name_fa'],p['brand'],p['category'],now(),mid))
  structure.reconcile_family_groups(c,keys)
  c.execute('UPDATE products SET title_fa=?,brand_fa=?,category_id=? WHERE master_product_id=?',(p['canonical_name_fa'],p['brand'],cat,mid))
  c.execute('UPDATE catalog_publications SET category_slug=?,updated_at=? WHERE master_product_id=?',(p['category'],now(),mid))
  metadata={'before':info['current'],'after':p,'reason':reason,'affected_master_ids':[r['id'] for r in info['affected_members']],'synced_sku_ids':[r['id'] for r in owned]}
  c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'catalog.identity_updated','master_product',?,?,?)",(current_user()['id'],str(mid),json.dumps(metadata,ensure_ascii=False),now()))
  return jsonify({'product':preview(c,mid)[0],'changed':True})
