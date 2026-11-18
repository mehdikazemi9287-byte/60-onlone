// Offline renderer for Google Stitch HTML exports (no CDN access).
// usage: node render.mjs <in.html> <out.png> [cssWidth]
// Compiles the page's inline tailwind.config with local Tailwind v3, swaps CDN fonts for local
// Vazirmatn + Material Symbols, then screenshots with headless Chrome.
import fs from 'fs'; import path from 'path'; import { execFileSync } from 'child_process';
const [,, inFile, outPng, widthArg] = process.argv;
const R = '/opt/stitchrender', NM = R + '/node_modules';
const work = fs.mkdtempSync('/tmp/sr-');
let html = fs.readFileSync(inFile, 'utf8');
const m = html.match(/<script id="tailwind-config">([\s\S]*?)<\/script>/);
let cfgSrc = m ? m[1].trim().replace(/;\s*$/, '') : '';
// some Stitch exports have unbalanced braces in the config; close them so it still parses
{ const t = cfgSrc.replace(/"(?:[^"\\]|\\.)*"/g, ''); const miss = (t.match(/\{/g)||[]).length - (t.match(/\}/g)||[]).length; if (miss > 0) cfgSrc += '}'.repeat(miss); }
fs.writeFileSync(path.join(work, 'page.html'), html);
fs.writeFileSync(path.join(work, 'tailwind.config.cjs'),
  `const tailwind = {};\n${cfgSrc}\n;const c = tailwind.config || {};\nmodule.exports = { ...c, content: [${JSON.stringify(path.join(work, 'page.html'))}],\n plugins: [require('${NM}/@tailwindcss/forms'), require('${NM}/@tailwindcss/container-queries')] };\n`);
try { (await import('module')).createRequire(import.meta.url)(path.join(work, 'tailwind.config.cjs')); }
catch (e) { // broken config in this export: fall back to the shared design tokens from a sibling screen
  const ref = fs.readFileSync(process.env.STITCH_REF_CFG || '/tmp/stitch/docs/design/stitch/screens/30-28a7321c.html', 'utf8').match(/<script id="tailwind-config">([\s\S]*?)<\/script>/)[1];
  fs.writeFileSync(path.join(work, 'tailwind.config.cjs'), `const tailwind = {};\n${ref}\n;const c = tailwind.config || {};\nmodule.exports = { ...c, content: [${JSON.stringify(path.join(work, 'page.html'))}],\n plugins: [require('${NM}/@tailwindcss/forms'), require('${NM}/@tailwindcss/container-queries')] };\n`);
  console.error('note: config fallback used'); }
fs.writeFileSync(path.join(work, 'in.css'), '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n');
execFileSync(NM + '/.bin/tailwindcss', ['-c', path.join(work, 'tailwind.config.cjs'), '-i', path.join(work, 'in.css'), '-o', path.join(work, 'out.css')], { cwd: R, stdio: 'pipe' });
const css = fs.readFileSync(path.join(work, 'out.css'), 'utf8');
const fonts = `@font-face{font-family:'Material Symbols Outlined';font-style:normal;font-weight:100 700;src:url(file://${NM}/material-symbols/material-symbols-outlined.woff2) format('woff2')}
.material-symbols-outlined{font-family:'Material Symbols Outlined';font-weight:normal;font-style:normal;font-size:24px;line-height:1;letter-spacing:normal;text-transform:none;display:inline-block;white-space:nowrap;direction:ltr;-webkit-font-feature-settings:'liga';font-feature-settings:'liga';-webkit-font-smoothing:antialiased}
@font-face{font-family:'Vazirmatn';font-weight:400;src:url(file://${NM}/@fontsource/vazirmatn/files/vazirmatn-arabic-400-normal.woff2)}
@font-face{font-family:'Vazirmatn';font-weight:700;src:url(file://${NM}/@fontsource/vazirmatn/files/vazirmatn-arabic-700-normal.woff2)}
@font-face{font-family:'Vazirmatn, Sahel, Shabnam, system-ui';font-weight:400;src:url(file://${NM}/@fontsource/vazirmatn/files/vazirmatn-arabic-400-normal.woff2)}
@font-face{font-family:'Vazirmatn, Sahel, Shabnam, system-ui';font-weight:700;src:url(file://${NM}/@fontsource/vazirmatn/files/vazirmatn-arabic-700-normal.woff2)}
body{font-family:Vazirmatn,sans-serif}`;
html = html.replace(/<script src="https:\/\/cdn\.tailwindcss\.com[^"]*"><\/script>/g, '')
  .replace(/<script id="tailwind-config">[\s\S]*?<\/script>/, '')
  .replace(/<link[^>]+fonts\.googleapis\.com[^>]*>/g, '')
  .replace('</head>', `<style>${fonts}\n${css}</style></head>`);
const page = path.join(work, 'render.html'); fs.writeFileSync(page, html);
const W = Number(widthArg || 1440);
execFileSync('google-chrome', ['--headless=new', '--no-sandbox', '--hide-scrollbars', '--allow-file-access-from-files',
  `--window-size=${W},${W < 600 ? 2600 : 2400}`, '--virtual-time-budget=4000', `--screenshot=${outPng}`, 'file://' + page], { stdio: 'pipe', timeout: 90000 });
console.log('ok', outPng);
