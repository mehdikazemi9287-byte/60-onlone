const {chromium}=require('playwright');const http=require('http');const fs=require('fs');const path=require('path');
const srv=http.createServer((q,r)=>{const p=path.join(__dirname,decodeURIComponent(q.url.split('?')[0])==='/'?'index.html':decodeURIComponent(q.url.split('?')[0]));fs.readFile(p,(e,d)=>{if(e){r.writeHead(404);return r.end()}r.writeHead(200,{'Content-Type':p.endsWith('.css')?'text/css':p.endsWith('.js')?'text/javascript':p.endsWith('.html')?'text/html':p.endsWith('.png')?'image/png':'image/jpeg'});r.end(d)})}).listen(8123,async()=>{
 const b=await chromium.launch();const errs=[];
 for(const [w,n] of [[1440,'desk'],[390,'mob']]){const pg=await b.newPage({viewport:{width:w,height:900}});pg.on('pageerror',e=>errs.push(String(e)));pg.on('console',m=>m.type()==='error'&&errs.push(m.text()));await pg.goto('http://localhost:8123/');await pg.waitForTimeout(1200);await pg.screenshot({path:n+'.png',fullPage:true});
  const ov=await pg.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);console.log(n,'hscroll',ov);}
 console.log('errors',errs);await b.close();srv.close();});
