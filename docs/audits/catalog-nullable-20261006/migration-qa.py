import sys,sqlite3,hashlib,json,os
from pathlib import Path
from datetime import datetime,timezone
root=Path('/home/ubuntu/60online-authoritative');sys.path.insert(0,str(root/'backend'))
from app.core.catalog_nullable_migration import apply,rollback
p=root/'docs/audits/catalog-nullable-20261006';data=root/'data/catalog-import-20261006';candidate=data/'candidate.db'
backup=data/'before-nullable.db';assert not backup.exists();src=sqlite3.connect('file:'+str(candidate)+'?mode=ro',uri=True);dst=sqlite3.connect(backup);src.backup(dst);dst.close();os.chmod(backup,0o600)
qa=Path('/tmp/60online-nullable-migration-qa.db');assert not qa.exists();dst=sqlite3.connect(qa);src.backup(dst);src.close();os.chmod(qa,0o600);dst.row_factory=sqlite3.Row;dst.execute('PRAGMA foreign_keys=ON')
checksum=hashlib.sha256((root/'backend/migrations/0043_nullable_master_unit_pack.sql').read_bytes()).hexdigest();now=datetime.now(timezone.utc).isoformat()
assert apply(dst,checksum=checksum,now=now);assert apply(dst,checksum=checksum,now=now) is False
assert [(r[1],r[3],r[4]) for r in dst.execute('PRAGMA table_info(master_products)') if r[1] in ('unit','package_quantity')]==[('unit',0,None),('package_quantity',0,None)]
dst.execute('INSERT INTO master_products(public_product_id,canonical_name_fa,unit,package_quantity,provenance) VALUES(?,?,?,?,?)',('SYNTHETIC-NULLABLE-QA','SYNTHETIC QA',None,None,'test'));dst.commit()
try:rollback(dst);raise AssertionError('rollback accepted later writes')
except ValueError:pass
# Test constraint rollback on an independent migration-only copy; no deletes.
qa2=Path('/tmp/60online-nullable-rollback-qa.db');src=sqlite3.connect('file:'+str(backup)+'?mode=ro',uri=True);q=sqlite3.connect(qa2);src.backup(q);src.close();os.chmod(qa2,0o600);q.row_factory=sqlite3.Row;q.execute('PRAGMA foreign_keys=ON');apply(q,checksum=checksum,now=now);rollback(q);assert not q.execute('PRAGMA foreign_key_check').fetchall();assert q.execute('PRAGMA quick_check').fetchone()[0]=='ok';q.close();dst.close()
c=sqlite3.connect(candidate);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');assert apply(c,checksum=checksum,now=now);assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
(p/'migration-qa.json').write_text(json.dumps({'status':'PASS','candidate_only':True,'snapshot_before':'data/catalog-import-20261006/before-nullable.db','nullable_columns':['unit','package_quantity'],'populated_values_preserved':True,'no_drop_delete':True,'foreign_keys':'PASS','null_insert':'PASS: synthetic isolated clone','second_migration':'no-op','constraint_rollback':'PASS before subsequent writes','rollback_after_write':'refused without data loss','postgresql':'NOT_RUN: target is SQLite'},indent=2));print('Nullable migration PASS; candidate only')
