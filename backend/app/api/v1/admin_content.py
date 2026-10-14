"""Versioned structured content. No HTML/JS execution, no implicit publication."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from flask import Blueprint, jsonify, request
from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ConflictError, NotFoundError, ValidationError, PermissionError_

bp=Blueprint('admin_content',__name__,url_prefix='/api/v1')
HOME_KEYS=('hero','collections','categories','today','why','groups','brands','packs','organization')
TYPES=('hero','text','banner','cta','home_section')
FIELDS={'id','type','title','body','link','button_label','image_url','key','enabled'}

def now():return datetime.now(timezone.utc).isoformat()

def assert_admin(c):
 if not c.execute("SELECT 1 FROM users WHERE id=? AND role='admin' AND is_active=1",(current_user()['id'],)).fetchone():
  raise PermissionError_('مجوز مدیریت دیگر فعال نیست')

def body():
 d=request.get_json(silent=True)
 if not isinstance(d,dict):raise ValidationError('بدنه درخواست باید شیء باشد')
 return d
def text(value,maximum=2000):
 if not isinstance(value,str) or len(value)>maximum:raise ValidationError('متن نامعتبر یا بیش از حد مجاز است')
 return value.strip()
def safe_link(value,image=False):
 value=text(value,1000)
 if not value:return ''
 p=urlsplit(value)
 if any(c in value for c in ('\\','\x00','\r','\n')) or p.username or p.password:raise ValidationError('نشانی نامعتبر است')
 if value.startswith('/') and not value.startswith('//') and '..' not in p.path.split('/'):
  return value
 if p.scheme=='https' and p.hostname:return value
 raise ValidationError('لینک باید مسیر سایت یا HTTPS باشد')
def validate_content(d,kind):
 if not isinstance(d,dict) or set(d)-{'title','blocks','seo'}:raise ValidationError('ساختار محتوا نامعتبر است')
 title=text(d.get('title'),200)
 if not title:raise ValidationError('عنوان لازم است')
 blocks=d.get('blocks')
 if not isinstance(blocks,list) or len(blocks)>40:raise ValidationError('حداکثر ۴۰ بلوک مجاز است')
 result=[];ids=set();keys=set()
 for b in blocks:
  if not isinstance(b,dict) or set(b)-FIELDS or b.get('type') not in TYPES:raise ValidationError('بلوک نامعتبر است')
  ident=text(b.get('id'),80)
  if not ident or ident in ids:raise ValidationError('شناسه بلوک باید یکتا باشد')
  ids.add(ident)
  item={'id':ident,'type':b['type'],'enabled':b.get('enabled',True)}
  if type(item['enabled']) is not bool:raise ValidationError('وضعیت بلوک نامعتبر است')
  for key in ('title','body','button_label'):item[key]=text(b.get(key,''),2000 if key=='body' else 200)
  for key in ('link','image_url'):item[key]=safe_link(b.get(key,''),key=='image_url')
  if b['type']=='home_section':
   key=b.get('key')
   if kind!='homepage' or key not in HOME_KEYS or key in keys:raise ValidationError('سکشن صفحه اصلی نامعتبر یا تکراری است')
   item['key']=key;keys.add(key)
  elif kind=='homepage':raise ValidationError('صفحه اصلی فقط از سکشن‌های هویت فعلی استفاده می‌کند')
  result.append(item)
 out={'title':title,'blocks':result}
 if 'seo' in d:
  seo=d['seo']
  if not isinstance(seo,dict) or set(seo)-{'title','description','canonical','noindex'}:raise ValidationError('تنظیم SEO نامعتبر است')
  noindex=seo.get('noindex',False)
  if type(noindex) is not bool:raise ValidationError('وضعیت ایندکس باید بولی باشد')
  canonical=text(seo.get('canonical',''),300)
  if canonical and (not canonical.startswith('/') or canonical.startswith('//') or safe_link(canonical)!=canonical):raise ValidationError('نشانی canonical باید مسیر همین سایت باشد')
  out['seo']={'title':text(seo.get('title',''),70),'description':text(seo.get('description',''),200),'canonical':canonical,'noindex':noindex}
 return out
def page(c,pid):
 r=c.execute('SELECT * FROM cms_pages WHERE id=?',(pid,)).fetchone()
 if not r:raise NotFoundError('صفحه یافت نشد')
 return dict(r)
def revision(c,pid,rid):
 r=c.execute('SELECT * FROM cms_revisions WHERE id=? AND page_id=?',(rid,pid)).fetchone()
 if not r:raise NotFoundError('نسخه متعلق به این صفحه یافت نشد')
 return dict(r)
def detail(c,pid):
 p=page(c,pid)
 p['content']=json.loads(revision(c,pid,p['draft_revision_id'])['content_json']) if p['draft_revision_id'] else {'title':p['title'],'blocks':[]}
 return p
def expected(d,p):
 if type(d.get('expected_revision')) is not int or d['expected_revision']!=p['draft_revision_id']:
  raise ConflictError('نسخه صفحه تغییر کرده است؛ ابتدا آخرین نسخه را دریافت کنید')
def save_revision(c,pid,content,actor,action,reason,source=None):
 encoded=json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 stamp=now()
 rid=c.execute('INSERT INTO cms_revisions(page_id,content_json,content_hash,created_by,created_at,source_revision_id) VALUES (?,?,?,?,?,?)',(pid,encoded,hashlib.sha256(encoded.encode()).hexdigest(),actor,stamp,source)).lastrowid
 c.execute('UPDATE cms_pages SET title=?,draft_revision_id=?,updated_at=? WHERE id=?',(content['title'],rid,stamp,pid))
 c.execute('INSERT INTO cms_events(page_id,revision_id,actor_user_id,action,reason,created_at) VALUES (?,?,?,?,?,?)',(pid,rid,actor,action,reason,stamp))
 return rid

@bp.get('/admin/content/pages')
@require_auth('admin')
def list_pages():
 with get_db().read_transaction() as c:
  return jsonify({'items':[dict(r) for r in c.execute('SELECT * FROM cms_pages ORDER BY updated_at DESC,id DESC LIMIT 200')]})

@bp.post('/admin/content/pages')
@require_auth('admin')
def create_page():
 d=body();slug=text(d.get('slug'),120);title=text(d.get('title'),200);kind=d.get('kind','page')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) or kind not in ('page','article','homepage') or not title:raise ValidationError('عنوان، آدرس یا نوع صفحه نامعتبر است')
 if (kind=='homepage')!=(slug=='homepage'):raise ValidationError('آدرس صفحه اصلی باید homepage باشد')
 with get_db().write_transaction() as c:
  assert_admin(c)
  if c.execute('SELECT 1 FROM cms_pages WHERE slug=?',(slug,)).fetchone():raise ConflictError('این آدرس قبلاً ثبت شده است')
  actor=current_user()['id'];stamp=now()
  pid=c.execute('INSERT INTO cms_pages(slug,title,kind,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?)',(slug,title,kind,actor,stamp,stamp)).lastrowid
  content={'title':title,'blocks':[{'id':'home-'+k,'type':'home_section','key':k,'enabled':True} for k in HOME_KEYS] if kind=='homepage' else []}
  save_revision(c,pid,validate_content(content,kind),actor,'created','ایجاد پیش‌نویس')
  return jsonify({'page':detail(c,pid)}),201

@bp.get('/admin/content/pages/<int:pid>')
@require_auth('admin')
def get_page(pid):
 with get_db().read_transaction() as c:return jsonify({'page':detail(c,pid)})

@bp.put('/admin/content/pages/<int:pid>')
@require_auth('admin')
def edit_page(pid):
 d=body()
 with get_db().write_transaction() as c:
  assert_admin(c)
  p=page(c,pid);expected(d,p)
  content=validate_content(d.get('content'),p['kind'])
  save_revision(c,pid,content,current_user()['id'],'edited',text(d.get('reason','ویرایش پیش‌نویس'),500))
  return jsonify({'page':detail(c,pid)})

@bp.post('/admin/content/pages/<int:pid>/publish')
@require_auth('admin')
def publish(pid):
 d=body()
 with get_db().write_transaction() as c:
  assert_admin(c)
  p=page(c,pid);expected(d,p)
  if p['published_revision_id']!=p['draft_revision_id']:
   r=revision(c,pid,p['draft_revision_id']);content=json.loads(r['content_json'])
   for b in content['blocks']:
    image=b.get('image_url','')
    if b['enabled'] and image.startswith('/api/v1/media/'):
     aid=image[len('/api/v1/media/'):]
     if not c.execute("SELECT 1 FROM media_assets WHERE id=? AND status='public'",(aid,)).fetchone():
      raise ValidationError('رسانه انتخابی هنوز برای نمایش عمومی تأیید نشده است')
   if not any(b['enabled'] for b in content['blocks']):raise ValidationError('صفحه خالی قابل انتشار نیست')
   reason=text(d.get('reason',''),500)
   if not reason:raise ValidationError('دلیل انتشار لازم است')
   stamp=now();c.execute('UPDATE cms_pages SET published_revision_id=?,updated_at=? WHERE id=?',(r['id'],stamp,pid))
   c.execute('INSERT INTO cms_events(page_id,revision_id,actor_user_id,action,reason,created_at) VALUES (?,?,?,?,?,?)',(pid,r['id'],current_user()['id'],'published',reason,stamp))
  return jsonify({'page':detail(c,pid)})

@bp.get('/admin/content/pages/<int:pid>/revisions')
@require_auth('admin')
def history(pid):
 with get_db().read_transaction() as c:
  page(c,pid)
  return jsonify({'items':[dict(r) for r in c.execute('SELECT id,page_id,content_hash,created_by,created_at,source_revision_id FROM cms_revisions WHERE page_id=? ORDER BY id DESC LIMIT 100',(pid,))],'events':[dict(r) for r in c.execute('SELECT * FROM cms_events WHERE page_id=? ORDER BY id DESC LIMIT 100',(pid,))]})

@bp.post('/admin/content/pages/<int:pid>/restore')
@require_auth('admin')
def restore(pid):
 d=body()
 if type(d.get('revision_id')) is not int:raise ValidationError('شناسه نسخه نامعتبر است')
 with get_db().write_transaction() as c:
  assert_admin(c)
  p=page(c,pid);expected(d,p);r=revision(c,pid,d['revision_id'])
  save_revision(c,pid,json.loads(r['content_json']),current_user()['id'],'restored',text(d.get('reason','بازگردانی نسخه به پیش‌نویس'),500),r['id'])
  return jsonify({'page':detail(c,pid)})

@bp.get('/content/pages/<slug>')
def public_page(slug):
 with get_db().read_transaction() as c:
  p=c.execute('SELECT * FROM cms_pages WHERE slug=? AND published_revision_id IS NOT NULL',(slug,)).fetchone()
  if not p:raise NotFoundError('صفحه منتشرشده یافت نشد')
  r=revision(c,p['id'],p['published_revision_id'])
  return jsonify({'slug':p['slug'],'kind':p['kind'],'revision':r['id'],'content':json.loads(r['content_json'])})

@bp.post('/admin/content/pages/<int:pid>/unpublish')
@require_auth('admin')
def unpublish(pid):
 d=body();reason=text(d.get('reason',''),500)
 if not reason:raise ValidationError('دلیل توقف انتشار لازم است')
 with get_db().write_transaction() as c:
  assert_admin(c);p=page(c,pid);expected(d,p)
  if p['published_revision_id']:
   c.execute('INSERT INTO cms_events(page_id,revision_id,actor_user_id,action,reason,created_at) VALUES (?,?,?,?,?,?)',(pid,p['published_revision_id'],current_user()['id'],'unpublished',reason,now()))
   c.execute('UPDATE cms_pages SET published_revision_id=NULL,updated_at=? WHERE id=?',(now(),pid))
  return jsonify({'page':detail(c,pid)})
