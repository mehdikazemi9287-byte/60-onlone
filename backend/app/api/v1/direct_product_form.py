"""Direct form contract; master reference only, never fabricated commerce rows."""
import json
from flask import jsonify
from app.core.deps import get_db, require_auth
from app.core.errors import ConflictError, ValidationError
from app.api.v1.admin_content import body, text, assert_admin
from app.services import master_catalog_service as svc

GLOBAL_TYPES={'INTERNAL','GTIN','EAN','UPC','ISBN','BARCODE','MFR_SKU','ERP_CODE'}
def identifiers(d):
 sku=text(d.get('sku',''),100)
 if not sku:raise ValidationError('SKU / کد داخلی کالا لازم است')
 raw=d.get('identifiers',[])
 if not isinstance(raw,list) or len(raw)>12:raise ValidationError('حداکثر ۱۲ شناسه معتبر مجاز است')
 out=[('INTERNAL',sku)];seen=set(out)
 for item in raw:
  if not isinstance(item,dict) or set(item)!={'type','value'} or not isinstance(item['type'],str) or item['type'] not in GLOBAL_TYPES-{'INTERNAL'}:raise ValidationError('نوع شناسه سراسری نامعتبر است')
  value=text(item['value'],100)
  if not value or (item['type'],value) in seen:raise ValidationError('شناسه خالی یا تکراری است')
  kind=item['type']
  if kind in ('GTIN','EAN','UPC','ISBN'):
   if not value.isascii() or not value.isdigit():raise ValidationError('شناسه استاندارد باید فقط ارقام لاتین باشد')
   lengths={'GTIN':(8,12,13,14),'EAN':(8,13),'UPC':(12,),'ISBN':(13,)}
   if len(value) not in lengths[kind] or (kind=='ISBN' and not value.startswith(('978','979'))):raise ValidationError('طول یا پیشوند شناسه استاندارد نامعتبر است')
   checksum=(10-sum(int(ch)*(3 if i%2==0 else 1) for i,ch in enumerate(reversed(value[:-1])))%10)%10
   if checksum!=int(value[-1]):raise ValidationError('رقم کنترل شناسه استاندارد نامعتبر است')
  seen.add((kind,value));out.append((kind,value))
 return out

def duplicates(c,d,exclude_master_id=None,exclude_product_id=None):
 ids=identifiers(d);matches=[]
 mapping={'INTERNAL':'sku','GTIN':'gtin','EAN':'barcode','UPC':'barcode','BARCODE':'barcode','ISBN':'isbn','ERP_CODE':'erp_code','MFR_SKU':'custom'}
 for kind,value in ids:
  kinds=('GTIN','EAN','UPC','BARCODE','ISBN') if kind in ('GTIN','EAN','UPC','BARCODE','ISBN') else (kind,)
  placeholders=','.join('?' for _ in kinds)
  rows=c.execute('SELECT master_product_id FROM product_identifiers_legacy WHERE identifier_type IN ('+placeholders+') AND identifier_value=? AND supplier_id IS NULL AND organization_id IS NULL',(*kinds,value)).fetchall()
  for row in rows:matches.append({'master_product_id':row[0],'type':kind,'value':value})
  lower=('gtin','barcode','isbn') if len(kinds)>1 else (mapping[kind],)
  marks=','.join('?' for _ in lower)
  rows=c.execute('SELECT p.master_product_id,p.id FROM product_identifiers i JOIN products p ON p.id=i.product_id WHERE i.identifier_type IN ('+marks+') AND i.identifier_value=? AND i.supplier_id IS NULL AND i.namespace=?',(*lower,value,'')).fetchall()
  if kind=='INTERNAL':
   for row in c.execute('SELECT master_product_id FROM direct_product_profiles WHERE sku=?',(value,)):
    matches.append({'master_product_id':row[0],'type':kind,'value':value})
   rows=[*rows,*c.execute('SELECT master_product_id,id FROM products WHERE sku=?',(value,)).fetchall(),*c.execute('SELECT p.master_product_id,p.id FROM product_code_aliases a JOIN products p ON p.id=a.product_id WHERE a.code=?',(value,)).fetchall()]
  for row in rows:matches.append({'master_product_id':row[0],'product_id':row[1],'type':kind,'value':value})
 return [m for m in matches if not (exclude_master_id is not None and m.get("master_product_id")==exclude_master_id) and not (exclude_product_id is not None and m.get("product_id")==exclude_product_id)]

def validate(c,d):
 if d.get('direct_form') is not True:raise ValidationError('قرارداد فرم مستقیم نامعتبر است')
 identifiers(d)
 if d.get('source_kind') not in ('supplier','catalog','manual','other'):raise ValidationError('نوع منبع لازم است')
 supplier=d.get('source_supplier_id')
 if d['source_kind']=='supplier':
  if type(supplier) is not int or not 1<=supplier<=9223372036854775807 or not c.execute("SELECT 1 FROM suppliers WHERE id=? AND provenance='real'",(supplier,)).fetchone():raise ValidationError('تأمین‌کننده واقعی موجود لازم است')
 elif supplier is not None:raise ValidationError('تأمین‌کننده فقط برای منبع تأمین‌کننده مجاز است')
 if d.get('status') not in ('active','draft'):raise ValidationError('وضعیت کالا باید فعال یا غیرفعال باشد')
 if d.get('supply_channel') not in ('retail','organization','both'):raise ValidationError('نوع عرضه لازم است')
 assets=d.get('media_ids',[])
 if not isinstance(assets,list) or len(assets)>10 or any(not isinstance(x,str) for x in assets) or len(set(assets))!=len(assets):raise ValidationError('حداکثر ۱۰ تصویر یکتا مجاز است')
 if assets and d.get('confirm_image_identity') is not True:raise ValidationError('تطابق تصاویر با برند و بسته‌بندی باید تأیید شود')
 from app.api.v1.admin_media import root
 for aid in assets:
  r=c.execute("SELECT filename FROM media_assets WHERE id=? AND status='public'",(aid,)).fetchone()
  if not r or not (root()/r['filename']).is_file():raise ValidationError('تصویر عمومی تأییدشده و فایل موجود لازم است')
 if duplicates(c,d):raise ConflictError('SKU یا یکی از شناسه‌ها قبلاً ثبت شده؛ کالای موجود را بررسی کنید',code='product_duplicate')

def save(c,d,mid):
 ids=identifiers(d)
 for kind,value in ids:svc.add_identifier(c,master_product_id=mid,identifier_type=kind,identifier_value=value)
 c.execute('UPDATE master_products SET status=?,image_urls_json=? WHERE id=?',(d['status'],json.dumps(['/api/v1/media/'+x for x in d.get('media_ids',[])]),mid))
 c.execute('INSERT INTO direct_product_profiles(master_product_id,sku,source_kind,source_supplier_id,supply_channel,source_reference) VALUES (?,?,?,?,?,?)',(mid,d['sku'].strip(),d['source_kind'],d.get('source_supplier_id'),d['supply_channel'],d['source_reference'].strip()))
 return svc.get_master_product(c,mid)

def register(bp):
 @bp.post('/admin/catalog/products/duplicate-check')
 @require_auth('admin')
 def check():
  d=body()
  with get_db().read_transaction() as c:
   assert_admin(c);return jsonify({'matches':duplicates(c,d)})
 @bp.get('/admin/catalog/create-options')
 @require_auth('admin')
 def options():
  with get_db().read_transaction() as c:
   assert_admin(c)
   return jsonify({'suppliers':[dict(x) for x in c.execute("SELECT id,legal_name FROM suppliers WHERE provenance='real' ORDER BY legal_name")], 'tax_categories':[dict(x) for x in c.execute('SELECT code,name_fa FROM tax_categories WHERE is_active=1 ORDER BY code')]})
 from app.api.v1.product_management import register_management
 register_management(bp)
