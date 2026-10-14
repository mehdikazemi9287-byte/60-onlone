const { chromium } = require('/tmp/pw/node_modules/playwright');
const fs=require('fs');
(async()=>{
const browser=await chromium.launch({executablePath:'/tmp/60online-test-browsers/chromium-1187/chrome-linux/chrome',args:['--no-sandbox']});
const stage=process.argv[2]||'before';const results=[];
for(const width of (stage==='before'?[390,1440]:[390,430,768,1024,1280,1440])){
const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce'});
if(stage==='before') await page.route('**/images/catalog/**',async route=>{const url=new URL(route.request().url());const r=await fetch('http://127.0.0.1'+url.pathname,{headers:{Host:'60online.ir'}});await route.fulfill({status:r.status,body:Buffer.from(await r.arrayBuffer()),contentType:r.headers.get('content-type')||'image/png'});});
for(const [label,path] of [['home','/'],['catalog','/search?q=پنیر'],['pdp','/products/kaleh-30003517'],['category','/category/supermarket'],['org','/org']]){
console.log(stage,label,width); await page.goto('http://127.0.0.1:3295'+path,{waitUntil:'networkidle',timeout:90000});await page.evaluate(()=>document.fonts.ready);await page.addStyleTag({content:'nextjs-portal{display:none!important}'}); if(label==='home') await page.locator('h3').filter({hasText:'ماست'}).first().waitFor({timeout:60000}).catch(async()=>{await page.locator('#pack-builder').waitFor();}); if(label==='catalog'||label==='category') await page.waitForFunction(()=>!document.body.innerText.includes('در حال دریافت…'),{},{timeout:60000});await page.evaluate(async()=>{for(let y=0;y<document.documentElement.scrollHeight;y+=700){scrollTo(0,y);await new Promise(r=>setTimeout(r,100));}scrollTo(0,0);}); await page.waitForTimeout(700);await page.screenshot({path:`/home/ubuntu/60online-authoritative/docs/audits/premium-20261005/screenshots/${stage}-${label}-${width}.png`,fullPage:true});
results.push({label,width,...await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,rtl:document.documentElement.dir,brokenImages:[...document.images].filter(x=>!x.complete||x.naturalWidth===0).length,componentOverflow:[...document.querySelectorAll('main h1,main h2,.product-card,.product-media,.catalog-toolbar input,.catalog-toolbar select,.pack-panel')].filter(e=>{const r=e.getBoundingClientRect();return r.left< -1||r.right>innerWidth+1}).length}))});
}
await page.close();}
fs.writeFileSync(`/home/ubuntu/60online-authoritative/docs/audits/premium-20261005/${stage}-qa.json`,JSON.stringify(results,null,2));console.log(JSON.stringify(results));await browser.close();
})();
