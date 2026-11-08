"""Controlled taxonomy metadata over existing categories; brand names remain actual master data."""
import json,re
from flask import Blueprint,jsonify,request
from app.core.deps import get_db,current_user,require_auth
from app.core.errors import ValidationError,NotFoundError,ConflictError
from app.api.v1.admin_content import body,text,now,assert_admin
bp=Blueprint('admin_taxonomy',__name__,url_prefix='/api/v1/admin/catalog')
LEVELS=('department','category','subcategory','product_type')
def row(c,cid):
 r=c.execute('SELECT id,slug,name_fa,parent_id,sort_order,level,admin_managed,admin_row_version FROM categories WHERE id=?',(cid,)).fetchone()
 if not r:raise NotFoundError('دسته یافت نشد')
 return dict(r)
def values(d,level):
 name=text(d.get('name_fa'),200);parent=d.get('parent_id');sort=d.get('sort_order',0)
 if not name or type(sort) is not int or not 0<=sort<=1000000:raise ValidationError('نام و ترتیب نمایش نامعتبر است')
 if parent is not None and (type(parent) is not int or parent<1):raise ValidationError('والد نامعتبر است')
 if level not in LEVELS:raise ValidationError('سطح دسته نامعتبر است')
 if level=='department' and parent is not None:raise ValidationError('گروه اصلی والد ندارد')
 if level in ('subcategory','product_type') and parent is None:raise ValidationError('والد این سطح لازم است')
 return name,parent,sort

def parent_check(c,parent,level,cid=None):
 if parent is None:return
 p=row(c,parent);expected={'category':'department','subcategory':'category','product_type':'subcategory'}.get(level)
 if p['level']!=expected:raise ValidationError('سطح والد با ساختار دسته سازگار نیست')
 if cid is not None:
  cycle=c.execute('WITH RECURSIVE ancestors(id,parent_id) AS (SELECT id,parent_id FROM categories WHERE id=? UNION SELECT c.id,c.parent_id FROM categories c JOIN ancestors a ON c.id=a.parent_id) SELECT 1 FROM ancestors WHERE id=?',(parent,cid)).fetchone()
  if cycle:raise ValidationError('ساختار دسته نباید چرخه داشته باشد')
def audit(c,cid,before,after,reason):
 c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,metadata_json,created_at) VALUES (?,'taxonomy.updated','category',?,?,?)",(current_user()['id'],str(cid),json.dumps({'before':before,'after':after,'reason':reason},ensure_ascii=False),now()))

@bp.get('/categories')
@require_auth('admin')
def listing():
 with get_db().read_transaction() as c:
  rows=c.execute("SELECT c.id,c.slug,c.name_fa,c.parent_id,c.sort_order,c.level,c.admin_managed,c.admin_row_version,(SELECT COUNT(*) FROM master_products m WHERE m.category=c.slug AND m.provenance='real') AS master_count FROM categories c ORDER BY c.sort_order,c.id").fetchall()
  return jsonify({'items':[dict(r) for r in rows]})

@bp.post('/categories')
@require_auth('admin')
def create():
 d=body()
 if set(d)-{'slug','name_fa','parent_id','sort_order','level','reason'}:raise ValidationError('فیلد ناشناخته در دسته')
 slug=text(d.get('slug'),120);level=d.get('level');v=values(d,level);reason=text(d.get('reason'),500)
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) or len(reason)<3:raise ValidationError('آدرس و دلیل ایجاد لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c);parent_check(c,v[1],level)
  if c.execute('SELECT 1 FROM categories WHERE slug=?',(slug,)).fetchone():raise ConflictError('این آدرس قبلاً ثبت شده است')
  cid=c.execute('INSERT INTO categories(slug,name_fa,parent_id,sort_order,level,admin_managed) VALUES (?,?,?,?,?,1)',(slug,*v,level)).lastrowid
  result=row(c,cid);audit(c,cid,None,result,reason);return jsonify({'category':result}),201

@bp.patch('/categories/<int:cid>')
@require_auth('admin')
def edit(cid):
 d=body()
 if set(d)-{'name_fa','parent_id','sort_order','expected_version','reason'}:raise ValidationError('آدرس و سطح دسته از این فرم تغییر نمی‌کند')
 reason=text(d.get('reason'),500)
 if len(reason)<3:raise ValidationError('دلیل تغییر لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c);old=row(c,cid)
  if type(d.get('expected_version')) is not int or d['expected_version']!=old['admin_row_version']:raise ConflictError('دسته تغییر کرده است؛ آخرین نسخه را دریافت کنید')
  v=values(d,old['level']);parent_check(c,v[1],old['level'],cid)
  c.execute('UPDATE categories SET name_fa=?,parent_id=?,sort_order=?,admin_managed=1 WHERE id=?',(*v,cid));result=row(c,cid)
  if old!=result:audit(c,cid,old,result,reason)
  return jsonify({'category':result})

@bp.get('/brands')
@require_auth('admin')
def brands():
 with get_db().read_transaction() as c:
  rows=c.execute("SELECT brand,COUNT(*) AS master_count FROM master_products WHERE provenance='real' AND status<>'merged' AND brand IS NOT NULL AND trim(brand)<>'' GROUP BY brand ORDER BY brand").fetchall()
  return jsonify({'items':[dict(r) for r in rows],'source':'master_products.brand'})
