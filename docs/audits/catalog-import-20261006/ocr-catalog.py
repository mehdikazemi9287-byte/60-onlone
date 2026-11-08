import os,json,subprocess,concurrent.futures
from pathlib import Path
root=Path('/home/ubuntu/60online-authoritative');out=root/'docs/audits/catalog-import-20261006';tools=Path('/tmp/60online-pdf-tools/root/usr/bin');work=Path('/tmp/60online-catalog-ocr');work.mkdir(exist_ok=True)
env={**os.environ,'LD_LIBRARY_PATH':'/tmp/60online-pdf-tools/root/usr/lib/x86_64-linux-gnu:/tmp/60online-visual-libs/root/usr/lib/x86_64-linux-gnu','FONTCONFIG_FILE':'/tmp/60online-visual-libs/fonts.conf','TESSDATA_PREFIX':'/tmp/60online-pdf-tools/root/usr/share/tesseract-ocr/5/tessdata','OMP_THREAD_LIMIT':'1'}
pdf=root/'data/data/imports/aria/Arya-Catalogue-2025.pdf'
def process(n):
 prefix=work/f'page-{n:03}'
 subprocess.run([str(tools/'pdftoppm'),'-f',str(n),'-l',str(n),'-r','220','-png','-singlefile',str(pdf),str(prefix)],env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 r=subprocess.run([str(tools/'tesseract'),str(prefix)+'.png','stdout','-l','fas','--psm','11'],env=env,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 (work/f'page-{n:03}.txt').write_text(r.stdout)
 return {'page':n,'ocr_text':r.stdout,'render':str(prefix)+'.png'}
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for r in pool.map(process,range(1,111)):
  results.append(r)
  if r['page']%10==0:print('OCR pages',r['page'],flush=True)
(out/'catalog-ocr.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print('OCR complete',len(results),flush=True)
