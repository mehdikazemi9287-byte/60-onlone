"""Expose actual imported PDF provenance separately from legal supplier registry and sale Offers."""
import json
from flask import Blueprint,jsonify,request
from app.core.deps import get_db,require_auth
from app.api.v1.admin_content import assert_admin
from app.api.v1.admin_console import pagination
bp=Blueprint('admin_catalog_sources',__name__,url_prefix='/api/v1/admin/catalog')

def sources(spec):
 try:d=json.loads(spec or '{}')
 except (ValueError,TypeError):return []
 catalog=d.get('pdf_catalog') if isinstance(d,dict) else None
 rows=catalog.get('sources') if isinstance(catalog,dict) else None
 if not isinstance(rows,list):return []
 keys=('supplier','source_file','source_page','source_sha256','source_identifier','source_date','supplier_product_code','original_name','price_status','price_type','price_basis','currency','unit','stock','images')
 result=[]
 for x in rows:
  if not isinstance(x,dict):continue
  item={k:x.get(k) for k in keys};issues=[]
  for k in keys:
   value=item[k]
   if k=='images':
    if not isinstance(value,list):item[k]=[]
   elif k in ('source_page','stock'):
    if value is not None and (type(value) is not int or value<0):item[k]=None;issues.append(k)
   elif value is not None and not isinstance(value,str):item[k]=None;issues.append(k)
  price=x.get('price')
  if price is not None and (isinstance(price,bool) or not isinstance(price,(str,int,float))):price=None;issues.append('price')
  item['price']=str(price) if price is not None else None;item['format_issues']=issues
  result.append(item)
 return result

ROWS="""FROM master_products m JOIN json_each(CASE WHEN json_valid(m.specifications_json) THEN CASE WHEN json_type(m.specifications_json,'$.pdf_catalog.sources')='array' THEN json_extract(m.specifications_json,'$.pdf_catalog.sources') ELSE '[]' END ELSE '[]' END) src WHERE m.provenance='real' AND m.status<>'merged' AND src.type='object' AND CASE WHEN src.type='object' THEN json_type(src.value,'$.supplier') ELSE NULL END='text'"""
@bp.get('/sources')
@require_auth('admin')
def directory():
 with get_db().read_transaction() as c:
  assert_admin(c)
  rows=c.execute("SELECT json_extract(src.value,'$.supplier') AS source_name,COUNT(DISTINCT m.id) AS products,COUNT(DISTINCT json_extract(src.value,'$.source_file')) AS files "+ROWS+" GROUP BY source_name ORDER BY source_name").fetchall()
  result=[]
  for row in rows:
   item=dict(row);s=c.execute("SELECT id FROM suppliers WHERE display_name=? AND provenance='real'",(item['source_name'],)).fetchall();item['supplier_id']=s[0]['id'] if len(s)==1 else None;result.append(item)
  return jsonify({'items':result,'source':'master_products.specifications_json.pdf_catalog.sources'})

@bp.get('/source-products')
@require_auth('admin')
def products():
 page,size,off=pagination();source=request.args.get('source','')[:200];q='%'+request.args.get('q','').strip()[:200]+'%'
 with get_db().read_transaction() as c:
  assert_admin(c);where=ROWS+" AND json_extract(src.value,'$.supplier')=? AND m.canonical_name_fa LIKE ?";args=(source,q)
  total=c.execute('SELECT COUNT(DISTINCT m.id) '+where,args).fetchone()[0]
  rows=c.execute('SELECT DISTINCT m.id,m.canonical_name_fa,m.brand,m.specifications_json,m.unit,m.package_quantity '+where+' ORDER BY m.id LIMIT ? OFFSET ?',(*args,size,off)).fetchall()
  return jsonify({'items':[{**{k:r[k] for k in ('id','canonical_name_fa','brand','unit','package_quantity')},'sources':[x for x in sources(r['specifications_json']) if x['supplier']==source]} for r in rows],'total':total,'page':page,'page_size':size,'prices_are_sale_offers':False})
