import {compile} from '/opt/npm-tools/node_modules/tailwindcss/dist/lib.mjs';
import fs from 'fs'; import path from 'path';
const base='/opt/npm-tools/node_modules/tailwindcss';
const src=fs.readFileSync(process.argv[2]||'../../frontend/src/components/home/HomeSections.tsx','utf8');
const cands=new Set(src.match(/[A-Za-z0-9_\-:\[\]\.#%\/]+/g));
const css='@import "tailwindcss";\n@theme { --color-white: #F9F9F9; }';
const c=await compile(css,{base,loadStylesheet:async(id,b)=>{const p=id==='tailwindcss'?path.join(base,'index.css'):path.resolve(b,id);return {path:p,base:path.dirname(p),content:fs.readFileSync(p,'utf8')}}});
fs.writeFileSync('app.css',c.build([...cands]));console.log('css bytes',fs.statSync('app.css').size);
