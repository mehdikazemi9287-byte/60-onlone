const {chromium}=require('/tmp/pw/node_modules/playwright');const fs=require('fs');
(async()=>{
const root='/home/ubuntu/60online-authoritative/docs/audits/catalog-import-20261006';const qa=JSON.parse(fs.readFileSync(root+'/candidate-qa.json'));const browser=await chromium.launch({executablePath:'/tmp/60online-test-browsers/chromium-1187/chrome-linux/chrome',headless:true,args:['--no-sandbox']});const results=[];
for(const width of [390,1440]){
const context=await browser.newContext({viewport:{width,height:900},deviceScaleFactor:1});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
for(const [name,path] of [['homepage','/'],['listing','/category/books-stationery'],['search','/search?q='+encodeURIComponent('آریا')],['pdp-no-image','/products/'+qa.sample_slugs[0]],['pdp-image','/products/'+qa.sample_slugs[1]],['organization','/org']]){
let response=await page.goto('http://127.0.0.1:3295'+path,{waitUntil:'networkidle'});await page.waitForTimeout(500);
let state=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,rtl:document.documentElement.dir==='rtl',cards:document.querySelectorAll('.product-card').length,brokenImages:[...document.images].filter(i=>i.complete&&i.naturalWidth===0).map(i=>i.getAttribute('src')),title:document.querySelector('h1')?.textContent,body:document.body.innerText}));
if(response.status()!=200||state.overflow||!state.rtl||state.brokenImages.length||errors.length)throw new Error(JSON.stringify({name,width,status:response.status(),state,errors}));
if(name==='homepage'&&state.cards===0)throw new Error('empty homepage');
if(['listing','search'].includes(name)&&state.cards===0)throw new Error('empty catalog '+name);
if(name.startsWith('pdp')&&!state.body.includes('استعلام'))throw new Error('missing inquiry behavior');
await page.screenshot({path:root+'/'+name+'-'+width+'.png',fullPage:true});delete state.body;results.push({name,width,status:response.status(),...state,pageErrors:errors.length});
}await context.close();}
await browser.close();fs.writeFileSync(root+'/ui-qa.json',JSON.stringify({status:'PASS',scope:'current Source frontend; isolated candidate API; 390px/1440px; basic anonymous UI',results},null,2));console.log('12 UI checks PASS');
})().catch(e=>{console.error(e);process.exit(1)});
