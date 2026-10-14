"""Product status and channel ceiling intersect supplier Offer scope; no price/stock writes.

Legacy masters without an explicit profile retain both channels. Existing committed order
snapshots are never modified; new sales and procurement commitments revalidate live policy.
"""
from app.core.errors import ConflictError, NotFoundError, ValidationError
CHANNELS=('retail','organization','both')
def channels(value):
 return ('retail','organization') if value=='both' else (value,) if value in CHANNELS else ()
def master_policy(c,mid):
 if mid is None:return {'status':'active','supply_channel':'both'}
 r=c.execute('SELECT m.status,dp.supply_channel FROM master_products m LEFT JOIN direct_product_profiles dp ON dp.master_product_id=m.id WHERE m.id=?',(mid,)).fetchone()
 return {'status':r['status'],'supply_channel':r['supply_channel'] or 'both'} if r else None
def sku_policy(c,pid):
 p=c.execute('SELECT master_product_id,is_active FROM products WHERE id=?',(pid,)).fetchone()
 if not p:return None
 policy=master_policy(c,p['master_product_id'])
 if policy and not p['is_active']:policy['status']='draft'
 return policy
def effective(c,pid,declared):
 p=sku_policy(c,pid)
 if not p or p['status']!='active':return None
 result=set(channels(declared)) & set(channels(p['supply_channel']))
 return 'both' if len(result)==2 else next(iter(result)) if result else None
def require_master(c,mid,channel):
 if mid is None:return
 if type(mid) is not int or mid<1:raise ValidationError('شناسه کالا نامعتبر است')
 p=master_policy(c,mid)
 if not p:raise NotFoundError('کالای مرجع یافت نشد')
 if p['status']!='active' or channel not in channels(p['supply_channel']):
  raise ConflictError('وضعیت یا نوع عرضه کالا این عملیات را مجاز نمی‌کند',code='product_channel_unavailable',details={'master_product_id':mid,'channel':channel})
def require_sku(c,pid,channel):
 p=sku_policy(c,pid)
 if not p or p['status']!='active' or channel not in channels(p['supply_channel']):
  raise ConflictError('این کالا در کانال انتخاب‌شده فعال نیست',code='product_channel_unavailable',details={'product_id':pid,'channel':channel})
def require_references(c,table,fk,value,channel='organization'):
 # Table/key only trusted application literals, never request input.
 for r in c.execute(f'SELECT master_product_id FROM {table} WHERE {fk}=?',(value,)):
  require_master(c,r[0],channel)
def product_sql(expr,channel=None):
 condition=f"AND (policy_dp.supply_channel IS NULL OR policy_dp.supply_channel IN ('{channel}','both'))" if channel else ''
 return f"EXISTS (SELECT 1 FROM products policy_p LEFT JOIN master_products policy_m ON policy_m.id=policy_p.master_product_id LEFT JOIN direct_product_profiles policy_dp ON policy_dp.master_product_id=policy_m.id WHERE policy_p.id={expr} AND policy_p.is_active=1 AND (policy_m.id IS NULL OR policy_m.status='active') {condition})"
def offer_sql(product_expr,channel_expr,channel=None):
 if channel:return f"({channel_expr} IN ('{channel}','both') AND {product_sql(product_expr,channel)})"
 return f"({product_sql(product_expr)} AND EXISTS (SELECT 1 FROM products scoped_p LEFT JOIN direct_product_profiles scoped_dp ON scoped_dp.master_product_id=scoped_p.master_product_id WHERE scoped_p.id={product_expr} AND ({channel_expr}='both' OR scoped_dp.supply_channel IS NULL OR scoped_dp.supply_channel='both' OR scoped_dp.supply_channel={channel_expr})))"
def offer_fields(c,pid,declared):
 p=sku_policy(c,pid);scope=effective(c,pid,declared)
 return {'declared_channel':declared,'effective_channel':scope,'allowed_channels':list(channels(scope)),'product_supply_channel':p['supply_channel'] if p else None,'product_active':bool(p and p['status']=='active')}
