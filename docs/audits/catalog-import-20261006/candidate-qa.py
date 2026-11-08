import sys,json,sqlite3,secrets,hashlib,collections,os
from pathlib import Path
root=Path('/home/ubuntu/60online-authoritative'); sys.path[:0]=[str(root/'backend'),str(root/'backend/scripts')]
from app.main import create_app
from app.core.config import Settings
from app.core.db import Database
from import_pdf_catalog import hide_imported_publications
out=root/'docs/audits/catalog-import-20261006'; data=root/'data/catalog-import-20261006'
def db(p):
 c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
before=db(data/'before-import.db');after=db(data/'candidate.db')
j=json.loads((data/'import-journal.json').read_text());second=json.loads((data/'second-import-journal.json').read_text());assert second['insertions']==[]
changed=collections.Counter(x['table'] for x in j['insertions']);preserved={}
for (t,) in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
 quote='"'+t.replace('"','""')+'"'
 old=collections.Counter(tuple(r) for r in before.execute('SELECT * FROM '+quote));new=collections.Counter(tuple(r) for r in after.execute('SELECT * FROM '+quote))
 assert not old-new,t+' existing rows changed'
 assert sum((new-old).values())==changed.get(t,0),t+' unrelated new rows'
 preserved[t]={'existing_rows_preserved':sum(old.values()),'new_rows':sum((new-old).values())}
assert not after.execute('PRAGMA foreign_key_check').fetchall();assert after.execute('PRAGMA quick_check').fetchone()[0]=='ok'
publications=[x['after'] for x in j['insertions'] if x['table']=='catalog_publications']
masters={x['key']:x['after'] for x in j['insertions'] if x['table']=='master_products'}
qa=Path('/tmp/60online-import-qa-v5.db'); assert not qa.exists();conn=sqlite3.connect(qa);after.backup(conn);os.chmod(qa,0o600);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
assert hide_imported_publications(conn,j)==223
assert all(conn.execute('SELECT is_visible FROM catalog_publications WHERE master_product_id=?',(p['master_product_id'],)).fetchone()[0]==0 for p in publications)
conn.rollback()
conn.execute('UPDATE catalog_publications SET publication_reason=? WHERE master_product_id=?',('SYNTHETIC QA EDIT',publications[0]['master_product_id']))
try: hide_imported_publications(conn,j);raise AssertionError('independent edit accepted')
except ValueError: pass
conn.rollback();conn.close()
settings=Settings(secret_key=secrets.token_hex(32),database_url='sqlite:///'+str(qa),app_env='development',seed_on_start=False)
app=create_app(settings,Database(str(qa)));client=app.test_client();assert not app.config['TEST_SALES_OVERRIDE']
products=[]
for pub in publications:
 response=client.get('/api/v1/products/'+pub['slug']);assert response.status_code==200,(pub['slug'],response.status_code)
 product=response.json['product'];products.append(product)
 if len(products)==1: print('PUBLIC_KEYS',list(product))
 assert product['purchasable'] is False
 assert product['price'] is None
 assert product['quantity_available'] is None
 assert product['title_fa'].strip()
 offers=client.get('/api/v1/products/'+pub['slug']+'/offers'); assert offers.status_code==200
 assert offers.json['offers']==[] and offers.json['best_offer'] is None
listing=client.get('/api/v1/products?category=books-stationery&page_size=48');assert listing.status_code==200
print('LIST_KEYS',list(listing.json),'PDP_COUNT',len(products))
assert len(listing.json['items'])>0
assert client.get('/api/v1/products?page=abc').status_code==422
# Explicitly synthetic auth/procurement fixtures exist only in disposable QA copy.
reg=client.post('/api/v1/auth/register',json={'email':'synthetic-import-qa@example.invalid','password':secrets.token_hex(16),'full_name':'SYNTHETIC IMPORT QA'});assert reg.status_code==201,reg.json
uid=reg.json['user']['id'];headers={'Authorization':'Bearer '+reg.json['access_token']}
search=client.get('/api/v1/catalog/search?brand=آریا&page_size=48',headers=headers);assert search.status_code==200
for master in masters.values():
 r=client.get('/api/v1/catalog/products/'+master['public_product_id'],headers=headers);assert r.status_code==200
from app.services.procurement_service import _add_pr_item
conn=sqlite3.connect(qa);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
oid=conn.execute("INSERT INTO organizations(legal_name,display_name,national_id,status,provenance) VALUES('SYNTHETIC QA','SYNTHETIC QA','SYNTHETIC-IMPORT-QA','active','test')").lastrowid
pr=conn.execute("INSERT INTO purchase_requests(organization_id,requester_user_id,request_number,title) VALUES(?,?,'SYNTHETIC-IMPORT-QA','SYNTHETIC QA')",(oid,uid)).lastrowid
for mid,master in masters.items(): _add_pr_item(conn,pr,{'master_product_id':mid,'quantity':1,'unit':master['unit']})
assert conn.execute('SELECT count(*) FROM purchase_request_items WHERE purchase_request_id=? AND estimated_unit_price_minor IS NULL',(pr,)).fetchone()[0]==223
conn.rollback();conn.close()
report={'status':'PASS','scope':'isolated candidate and disposable QA clone; no Production writes','all_existing_tables':preserved,'new_rows':dict(changed),'second_confirmed_run_insertions':0,'foreign_key_check':'PASS','quick_check':'ok','publication_PDP_API_checks':223,'all_inquiry_only':True,'new_seller_offers':0,'authenticated_master_lookup_checks':223,'organization_item_validation_checks':223,'organization_UI_selection':'BLOCKED: Source form only accepts free-text; Pouya has no masters','pack_builder_selection':'BLOCKED: Source builder inactive','visibility_rollback_checks':223,'rollback_independent_edit_guard':'PASS','sample_slugs':[publications[0]['slug'],next(p['slug'] for p in publications if masters[p['master_product_id']]['image_urls_json']!='[]')]}
(out/'candidate-qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('QA PASS')
