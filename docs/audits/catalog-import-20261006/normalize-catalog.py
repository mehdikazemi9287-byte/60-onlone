import json,re,hashlib,sys
from pathlib import Path
root=Path('/home/ubuntu/60online-authoritative');out=root/'docs/audits/catalog-import-20261006';sys.path.insert(0,str(root/'backend/scripts'))
from extract_aria_pouya import base,clean,normalized
alltext=json.loads((out/'pdf-text.json').read_text()); native=json.loads((out/'catalog-native-codes.json').read_text());ocr=json.loads((out/'catalog-ocr.json').read_text());rows=json.loads((out/'table-rows.json').read_text())
price={r['supplier_product_code']:r for r in rows if r['supplier']=='آریا'}
# Additional product codes transcribed from readable source labels, with
# visual review where OCR omitted/transposed digits. Native values take precedence.
extra={25:['3018'],26:['3021','3022','3023'],29:['3051','3052','3053'],31:['3005'],32:['3001'],34:['3044','3045'],35:['3046','3047'],36:['3048','3049'],45:['2050'],46:['2024','2027'],48:['2012','2030','2031'],53:['5008','5009'],54:['5005'],56:['4071'],57:['4009','4016'],58:['4015'],62:['7020','7016'],63:['7015','7014'],64:['7005','7003','7004'],65:['7031'],66:['7030'],67:['7032'],68:['7021'],78:['8033'],79:['8030','8031','8041'],80:['8038'],82:['1010'],83:['1011'],84:['1015','1016'],86:['6025','6020'],87:['6021','6022','6050'],88:['6023','6024'],91:['9013'],92:['6001','6002','6005'],93:['6003','6004','6015'],94:['6041','6042'],96:['9030'],97:['9030'],98:['9039','9040'],101:['6030'],102:['6035','6036'],106:['9097','9098','9091'],107:['9090','9099'],108:['9093','9094'],109:['9096']}
# Source-backed names, declared carton units/quantity, and optional explicitly
# printed product weight. Weight is gross product weight, never net contents.
manual={
'1056':('خمیربازی 15 رنگ پلمپ دار آریا','عدد',24,'خمیر'),
'1096':('خمیرشنی آموزش حروف و اعداد انگلیسی','عدد',6,'خمیر'),
'1095':('خمیرشنی آموزش حروف و اعداد فارسی','عدد',6,'خمیر'),
'3007':('مدادرنگی 12+3 رنگ فلزی BlueLine','بسته',120,'مداد'),
'3008':('مدادرنگی 24+3 رنگ فلزی BlueLine','بسته',72,'مداد'),
'3009':('مدادرنگی 36+3 رنگ فلزی BlueLine','بسته',40,'مداد'),
'3050':('مداد مشکی تحریر متالیک','بسته',240,'مداد'),
'1305':('مداد مشکی طرح دار لیوانی','بسته',20,'مداد'),
'3042':('مداد مشکی مدل ویترای','عدد',240,'مداد'),
'3043':('مداد مشکی مدل سیرک','عدد',240,'مداد'),
'3044':('مداد مشکی مدل جوان','عدد',240,'مداد'),
'3045':('مداد مشکی باغ وحش','عدد',240,'مداد'),
'3046':('مداد مشکی مدل بافتنی','عدد',240,'مداد'),
'3047':('مداد مشکی مدل کودکانه','عدد',240,'مداد'),
'3048':('مداد مشکی مدل میوه ای','عدد',240,'مداد'),
'3049':('مداد مشکی مدل سیاه و سفیدها','عدد',240,'مداد'),
'2035':('پاستل روغنی 12 رنگ کیفی جدید','عدد',72,'پاستل'),
'2036':('پاستل روغنی 24 رنگ کیفی جدید','عدد',48,'پاستل'),
'2019':('پاستل روغنی 19 رنگ کیف دار','عدد',72,'پاستل'),
'5014':('آبرنگ 12 رنگ آکوا BlueLine','عدد',48,'آبرنگ'),
'5015':('آبرنگ 24 رنگ آکوا BlueLine','عدد',48,'آبرنگ'),
'5012':('آبرنگ 6 رنگ آکوا','عدد',144,'آبرنگ'),
'5013':('آبرنگ 12 رنگ آکوا','عدد',72,'آبرنگ'),
'5010':('آبرنگ 8 رنگ آکوا','عدد',72,'آبرنگ'),
'5011':('آبرنگ 16 رنگ آکوا','عدد',36,'آبرنگ'),
'4022':('گواش 12 رنگ BlueLine','عدد',24,'گواش'),
'4071':('گواش فسفری 8 رنگ','عدد',12,'گواش'),
'7005':('رنگ انگشتی 4 رنگ','عدد',24,'رنگ انگشتی'),
'9050':('جعبه خودکار 6 عددی','عدد',432,'خودکار'),
'9026':('کاغذ تحریر A5','بسته',5,'متفرقه'),
'7071':('رنگ صورت پیچی 6 رنگ','عدد',48,'رنگ صورت'),
'7072':('رنگ صورت پیچی 12 رنگ','عدد',24,'رنگ صورت'),
'7073':('رنگ صورت پیچی 6 رنگ وکیومی','عدد',60,'رنگ صورت'),
'1010':('خمیر ژل اسلایم 150 گرم','عدد',96,'اسلایم'),
'1011':('خمیر ژل اسلایم 300 گرم','عدد',72,'اسلایم'),
'1015':('خمیر ژل اسلایم مات 150 گرم','عدد',96,'اسلایم'),
'1016':('خمیر ژل اسلایم مات 300 گرم','عدد',48,'اسلایم'),
'6022':('ظرف غذا بیضی','عدد',24,'جانبی'),
'6041':('رول نقاشی پشت چسبدار 20 سانتی متری','عدد',48,'جانبی'),
'6042':('رول نقاشی پشت چسبدار 30 سانتی متری','عدد',48,'جانبی'),
'9039':('قیچی درپوش دار','عدد',96,'متفرقه'),
'9040':('قیچی کاردستی مهد کودک','عدد',120,'متفرقه'),
'6036':('جایزه ویژه ماشین جادویی',None,None,'جانبی'),
'9030':('اینرباکس قیچی حیوانات','عدد',112,'متفرقه'),
'9097':('استند فلزی قرمز رنگ کوچک',None,None,'استندها'),
'9098':('استند فلزی قرمز رنگ بزرگ',None,None,'استندها'),
'9091':('استند استوانه ای فلزی',None,None,'استندها'),
'9090':('استند اتوبوس فلزی زرد رنگ',None,None,'استندها'),
'9099':('استند اتوبوس کوچک سوپرمارکتی',None,None,'استندها'),
'9093':('استند اتوبوس بزرگ چوبی',None,None,'استندها'),
'9094':('استند اتوبوس کوچک چوبی',None,None,'استندها'),
'9096':('استند مداد مدل قلعه',None,None,'استندها'),
}
keys={(c['page'],c['sku']) for c in native}
keys.update((page,sku) for page,skus in extra.items() for sku in skus)
catalog=[]
for page,sku in sorted(keys):
 p=alltext[0]['pages'][page-1]
 if sku in manual:
  name,unit,qty,group=manual[sku]
  r=base(alltext[0]['file'],page,'آریا',name,sku,[],f'sku:{sku}')
  r.update(unit=unit,carton_quantity=qty,subcategory=group)
 else:
  if sku not in price:raise ValueError('Unreviewed catalog-only SKU: '+sku)
  # The canonical label is resolved from the newer source by exact code;
  # it is not claimed to be a verbatim title in the 2025 catalogue.
  r=base(alltext[0]['file'],page,'آریا',price[sku]['normalized_name'],sku,[],f'sku:{sku}')
  r['original_name']=None
  r['name_resolved_from_file']=price[sku]['source_file']
  r['unit']=None;r['carton_quantity']=None
 r['category']='books-stationery';r['source_date']='2025';r['source_page_text']=p['logical_text'];r['source_page_ocr']=ocr[page-1]['ocr_text'];r['extraction_method']='native_text_and_reviewed_ocr_census'
 r['source_sha256']=alltext[0]['sha256']
 if sku=='9030':r['issues'].append('conflicting_catalog_weights_same_sku')
 catalog.append(r)
# Explicit source headings; continuation pages inherit the preceding group.
last=None
for p in alltext[1]['pages']:
 h=[x for x in p['pieces'] if 'گروه' in x['text']]
 if p['page']==8:h.append({'y':648,'text':'خودکار'})
 h=sorted(h,key=lambda x:-x['y'])
 for r in [r for r in rows if r['source_file']==alltext[1]['file'] and r['source_page']==p['page']]:
  y=max(x['y'] for x in r['raw_cells']);above=[x for x in h if x['y']>y]
  r['subcategory']=clean(min(above,key=lambda x:x['y'])['text']).replace('گروه','').strip() if above else last
  r['source_sha256']=alltext[1]['sha256']
  w=re.search(r'(\d+(?:[./]\d+)?)\s*(کیلویی|گرمی)',r['normalized_name'])
  if w:r['weight'],r['weight_unit']=w.group(1),'kg' if w.group(2)=='کیلویی' else 'g'
  elif 'کیلویی' in r['normalized_name']:r['weight'],r['weight_unit']='1','kg'
  r['price_type']='consumer'
 if h:last=clean(h[-1]['text']).replace('گروه','').strip()
for r in rows:
 if r['supplier']!='آریا':
  r['source_sha256']=next(f['sha256'] for f in alltext if f['file']==r['source_file'])
 rows_sha=next(f['sha256'] for f in alltext if f['file']==r['source_file'])
 r['source_sha256']=rows_sha
# Source caption declares gross weights, not net contents; store separately.
for r in catalog:
 if r['supplier_product_code'] in {'1010','1015'}:r['attributes']['declared_product_weight']={'raw':'150 گرم','value':'150','unit':'g','basis':'product_weight'}
 if r['supplier_product_code'] in {'1011','1016'}:r['attributes']['declared_product_weight']={'raw':'300 گرم','value':'300','unit':'g','basis':'product_weight'}
 if r['supplier_product_code']=='9030':r['attributes']['declared_product_weight']={'raw':('50 گرم' if r['source_page']==96 else '1500 گرم'),'value':('50' if r['source_page']==96 else '1500'),'unit':'g','basis':'product_weight'}
 if r['supplier_product_code']=='9093':r['size']='3348×1200×2010 mm'
 if r['supplier_product_code']=='9094':r['size']='2650×1000×1850 mm'
# Page 78 prints the same supplier code for two different angle variants.
for r in catalog:
 if r['supplier_product_code']=='8033':
  r['issues'].append('same_catalog_sku_two_angle_variants')
  r['original_name']='گونیا کوچک، 45 درجه';r['normalized_name']=r['original_name'];r['variant']='45 درجه';r['source_identifier']='sku:8033:45-degree-panel'
  second=dict(r);second['original_name']='گونیا کوچک، 60 درجه';second['normalized_name']=second['original_name'];second['variant']='60 درجه';second['source_identifier']='sku:8033:60-degree-panel'
  catalog.append(second)
  break
(out/'catalog-rows.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2));(out/'normalized-rows.json').write_text(json.dumps(rows+catalog,ensure_ascii=False,indent=2));(out/'catalog-reviewed-census.json').write_text(json.dumps({'product_occurrences':len(catalog),'unique_codes':len(set(r['supplier_product_code'] for r in catalog)),'page_codes':{str(n):[r['supplier_product_code'] for r in catalog if r['source_page']==n] for n in range(1,111)},'manual_catalog_only_fields':manual,'all_110_pages_ocr_completed':True},ensure_ascii=False,indent=2))
print('catalog occurrences',len(catalog),'unique codes',len(set(r['supplier_product_code'] for r in catalog)),'all source rows',len(rows+catalog),'catalog-only codes',len({r['supplier_product_code'] for r in catalog}-set(price)))
