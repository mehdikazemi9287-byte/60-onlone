"""Private-by-default media; decode/re-encode images, retain originals, audit publication/association."""
import base64
import binascii
import hashlib
import io
import json
import os
import uuid
import warnings
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request, send_file
from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.api.v1.admin_content import body, now, text, assert_admin

bp=Blueprint('admin_media',__name__,url_prefix='/api/v1')
MAX_BYTES=2*1024*1024
MAX_PIXELS=16_000_000
def root():
 path=current_app.config.get('MEDIA_ROOT') or os.environ.get('MEDIA_ROOT')
 if not path:raise ConflictError('فضای پایدار ذخیره‌سازی رسانه تنظیم نشده است')
 return Path(path).resolve()
def asset(c,aid):
 r=c.execute('SELECT * FROM media_assets WHERE id=?',(aid,)).fetchone()
 if not r:raise NotFoundError('رسانه یافت نشد')
 return dict(r)
def view(r):
 d=dict(r);d.pop('filename',None);d['url']='/api/v1/media/'+d['id'];return d
def event(c,aid,action,reason,master=None):
 c.execute('INSERT INTO media_events(asset_id,actor_user_id,master_product_id,action,reason,created_at) VALUES (?,?,?,?,?,?)',(aid,current_user()['id'],master,action,reason,now()))
def exact_version(d,r):
 if type(d.get('expected_version')) is not int or d['expected_version']!=r['row_version']:raise ConflictError('رسانه تغییر کرده است؛ آخرین نسخه را دریافت کنید')
def decode_image(encoded):
 from PIL import Image,ImageOps,UnidentifiedImageError
 if not isinstance(encoded,str) or len(encoded)>((MAX_BYTES+2)//3)*4:raise ValidationError('حداکثر حجم تصویر دو مگابایت است')
 try:raw=base64.b64decode(encoded,validate=True)
 except (ValueError,binascii.Error):raise ValidationError('فایل تصویر نامعتبر است')
 if not raw or len(raw)>MAX_BYTES:raise ValidationError('حداکثر حجم تصویر دو مگابایت است')
 try:
  with warnings.catch_warnings():
   warnings.simplefilter('error',Image.DecompressionBombWarning)
   with Image.open(io.BytesIO(raw)) as check:
    if check.format not in ('PNG','JPEG','WEBP') or getattr(check,'n_frames',1)!=1 or check.width*check.height>MAX_PIXELS:raise ValidationError('فقط تصویر ثابت PNG، JPEG یا WebP تا ۱۶ مگاپیکسل مجاز است')
    check.verify()
   with Image.open(io.BytesIO(raw)) as source:
    im=ImageOps.exif_transpose(source).convert('RGBA' if source.mode in ('RGBA','LA') or 'transparency' in source.info else 'RGB')
    im.thumbnail((2400,2400))
    width,height=im.size
    full=io.BytesIO();im.save(full,format='WEBP',quality=92,method=4)
    im.thumbnail((220,220));thumb=io.BytesIO();im.save(thumb,format='WEBP',quality=80)
 except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise ValidationError('تصویر قابل پردازش نیست')
 return raw,full.getvalue(),'data:image/webp;base64,'+base64.b64encode(thumb.getvalue()).decode(),width,height

@bp.get('/admin/media')
@require_auth('admin')
def listing():
 try:p=int(request.args.get('page','1'))
 except ValueError:raise ValidationError('صفحه نامعتبر است')
 if p<1:raise ValidationError('صفحه نامعتبر است')
 q=request.args.get('q','').strip()[:200];like='%'+q+'%'
 with get_db().read_transaction() as c:
  args=(like,like)
  status=request.args.get("status","")
  if status not in ("","private","public","archived"):raise ValidationError("وضعیت نامعتبر است")
  where="WHERE status!='archived' AND (original_name LIKE ? OR alt_text LIKE ?)"
  if status:where="WHERE status=? AND (original_name LIKE ? OR alt_text LIKE ?)";args=(status,*args)
  total=c.execute('SELECT COUNT(*) FROM media_assets '+where,args).fetchone()[0]
  rows=c.execute('SELECT * FROM media_assets '+where+' ORDER BY created_at DESC,id LIMIT 24 OFFSET ?',(*args,(p-1)*24)).fetchall()
  return jsonify({'items':[view(r) for r in rows],'total':total,'page':p,'page_size':24,'storage_configured':bool(current_app.config.get('MEDIA_ROOT') or os.environ.get('MEDIA_ROOT'))})

@bp.post('/admin/media')
@require_auth('admin')
def upload():
 d=body();folder=root();alt=text(d.get('alt_text',''),300);source=text(d.get('source_reference',''),1000);name=text(d.get('name','تصویر'),250)
 if not alt or not source:raise ValidationError('متن جایگزین و مرجع منبع لازم است')
 raw,data,thumb,width,height=decode_image(d.get('data_base64'));digest=hashlib.sha256(data).hexdigest()
 with get_db().write_transaction() as c:
  assert_admin(c)
  old=c.execute('SELECT * FROM media_assets WHERE checksum=?',(digest,)).fetchone()
  if old:return jsonify({'asset':view(old),'duplicate':True})
  aid=str(uuid.uuid4());filename=aid+'.webp';folder.mkdir(parents=True,exist_ok=True,mode=0o700);original=folder/(aid+'.original');target=folder/filename
  try:
   original.write_bytes(raw);os.chmod(original,0o600);target.write_bytes(data);stamp=now()
   c.execute('INSERT INTO media_assets(id,checksum,original_checksum,filename,original_name,mime_type,width,height,size_bytes,alt_text,source_reference,thumbnail_data_uri,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,digest,hashlib.sha256(raw).hexdigest(),filename,name,'image/webp',width,height,len(data),alt,source,thumb,current_user()['id'],stamp,stamp))
   event(c,aid,'uploaded','ثبت فایل با منبع و متن جایگزین')
  except Exception:
   original.unlink(missing_ok=True);target.unlink(missing_ok=True);raise
  return jsonify({'asset':view(asset(c,aid)),'duplicate':False}),201

@bp.patch('/admin/media/<aid>')
@require_auth('admin')
def edit(aid):
 d=body();alt=text(d.get('alt_text',''),300);source=text(d.get('source_reference',''),1000)
 if not alt or not source:raise ValidationError('متن جایگزین و منبع لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  r=asset(c,aid);exact_version(d,r)
  c.execute('UPDATE media_assets SET alt_text=?,source_reference=?,row_version=row_version+1,updated_at=? WHERE id=?',(alt,source,now(),aid));event(c,aid,'metadata_updated','ویرایش متن جایگزین و مرجع منبع')
  return jsonify({'asset':view(asset(c,aid))})

@bp.post('/admin/media/<aid>/<action>')
@require_auth('admin')
def transition(aid,action):
 d=body();reason=text(d.get('reason',''),500)
 if not reason:raise ValidationError('دلیل اقدام لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  r=asset(c,aid);exact_version(d,r)
  if action=='publish':
   if r['status']=='archived':raise ConflictError('رسانه آرشیوشده قابل انتشار نیست')
   if not (root()/r['filename']).is_file():raise ConflictError('فایل رسانه در فضای ذخیره‌سازی موجود نیست')
   c.execute("UPDATE media_assets SET status='public',row_version=row_version+1,updated_at=? WHERE id=?",(now(),aid));event(c,aid,'published',reason)
  elif action=='restore':
   if r['status']!='archived':raise ConflictError('رسانه آرشیو نشده است')
   c.execute("UPDATE media_assets SET status='private',row_version=row_version+1,updated_at=? WHERE id=?",(now(),aid));event(c,aid,'restored',reason)
  elif action=='archive':
   url='/api/v1/media/'+aid
   used=c.execute('SELECT 1 FROM cms_pages p JOIN cms_revisions r ON r.id=p.published_revision_id WHERE instr(r.content_json,?)>0',(url,)).fetchone()
   masters=c.execute('SELECT 1 FROM master_products WHERE instr(image_urls_json,?)>0',(url,)).fetchone()
   if used or masters:raise ConflictError('رسانه در محتوای منتشرشده یا کاتالوگ استفاده می‌شود؛ ابتدا کاربرد آن را تغییر دهید')
   c.execute("UPDATE media_assets SET status='archived',row_version=row_version+1,updated_at=? WHERE id=?",(now(),aid));event(c,aid,'archived',reason)
  else:raise ValidationError('اقدام رسانه نامعتبر است')
  return jsonify({'asset':view(asset(c,aid))})

@bp.post('/admin/media/<aid>/attach-to-product')
@require_auth('admin')
def attach(aid):
 d=body();mid=d.get('master_product_id');reason=text(d.get('reason',''),500)
 if type(mid) is not int or mid<1 or d.get('confirm_identity') is not True or not reason:raise ValidationError('شناسه کالا، تأیید تطابق تصویر و دلیل لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  r=asset(c,aid)
  if r['status']!='public':raise ConflictError('تصویر ابتدا باید برای نمایش عمومی تأیید شود')
  master=c.execute('SELECT image_urls_json,status,provenance,updated_at FROM master_products WHERE id=?',(mid,)).fetchone()
  if not master:raise NotFoundError('کالای مرجع یافت نشد')
  if d.get('expected_product_revision')!=master['updated_at']:raise ConflictError('اطلاعات کالا تغییر کرده است؛ دوباره انتخاب کنید')
  if master['provenance']!='real':raise ConflictError('تصویر تجاری فقط به کالای مرجع واقعی متصل می‌شود')
  if master['status']!='active':raise ConflictError('کالای مرجع فعال نیست')
  try:urls=json.loads(master['image_urls_json'] or '[]')
  except (ValueError,TypeError):raise ValidationError('تصاویر قبلی کالا نیاز به بازبینی دارند')
  if not isinstance(urls,list):raise ValidationError('ساختار تصاویر قبلی کالا نامعتبر است')
  url='/api/v1/media/'+aid
  mode=d.get('mode','append')
  if mode not in ('append','primary'):raise ValidationError('روش اتصال تصویر نامعتبر است')
  if url not in urls or mode=='primary':
   urls=[url]+[u for u in urls if u!=url] if mode=='primary' else [*urls,url]
   c.execute('UPDATE master_products SET image_urls_json=?,updated_at=? WHERE id=?',(json.dumps(urls),now(),mid));event(c,aid,'attached_to_product',reason,mid)
  return jsonify({'master_product_id':mid,'image_urls':urls})

@bp.get('/media/<aid>')
def public_image(aid):
 with get_db().read_transaction() as c:
  r=c.execute("SELECT filename FROM media_assets WHERE id=? AND status='public'",(aid,)).fetchone()
  if not r:raise NotFoundError('تصویر عمومی یافت نشد')
  path=root()/r['filename']
  if not path.is_file():raise NotFoundError('فایل تصویر یافت نشد')
 return send_file(path,mimetype='image/webp',max_age=3600)


@bp.get('/admin/media/master-products')
@require_auth('admin')
def master_search():
 q=request.args.get('q','').strip()[:200]
 if len(q)<2:return jsonify({'items':[]})
 with get_db().read_transaction() as c:
  rows=c.execute("SELECT id,canonical_name_fa,brand,variant,size_label,unit,updated_at FROM master_products WHERE provenance='real' AND status='active' AND canonical_name_fa LIKE ? ORDER BY id LIMIT 20",('%'+q+'%',)).fetchall()
  return jsonify({'items':[dict(r) for r in rows]})

@bp.get('/admin/media/<aid>/original')
@require_auth('admin')
def download_original(aid):
 with get_db().read_transaction() as c:asset(c,aid)
 path=root()/(aid+'.original')
 if not path.is_file():raise NotFoundError('فایل اصلی یافت نشد')
 return send_file(path,mimetype='application/octet-stream',as_attachment=True,download_name=aid+'.original',max_age=0)
