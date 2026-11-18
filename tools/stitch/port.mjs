// Port a Google Stitch HTML export (or one region of it) to JSX that uses this repo's st- Tailwind tokens.
//
//   node tools/stitch/port.mjs <screen.html> [css-selector] > out.jsx
//
// - class -> className; Stitch token utilities (bg-surface-container, px-margin-lg, text-headline-xl, ...)
//   are rewritten to the prefixed tokens in frontend/tailwind.config.ts (bg-st-surface-container, ...).
//   Stitch's font-<token> family classes are dropped (the site has one font: Vazirmatn).
// - Attributes are converted to their JSX names; inline style strings become objects; void tags self-close.
// - The output is a STARTING POINT: replace demo text, numbers and images with real data from the API
//   (AGENTS.md rule 9 — never ship Stitch's sample products, prices or photos), and split into components.
// Needs node-html-parser (installed in /opt/stitchrender, or `npm i node-html-parser` anywhere on NODE_PATH).
import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire('/opt/stitchrender/package.json');
const { parse } = require('node-html-parser');

const [, , file, selector] = process.argv;
const html = fs.readFileSync(file, 'utf8');
const cfgSrc = (html.match(/<script id="tailwind-config">([\s\S]*?)<\/script>/) || [, ''])[1];
let ext = {};
try { const tailwind = {}; eval(cfgSrc); ext = tailwind.config.theme.extend; } catch { /* broken config: fall back */ }
const ref = JSON.parse(fs.readFileSync(new URL('./stitch-tokens.json', import.meta.url), 'utf8'));
const colorKeys = new Set([...Object.keys(ext.colors || {}), ...Object.keys(ref.colors).map(k => k.slice(3))]);
const spaceKeys = new Set([...Object.keys(ext.spacing || {}), ...Object.keys(ref.spacing).map(k => k.slice(3))]);
const fsKeys = new Set([...Object.keys(ext.fontSize || {}), ...Object.keys(ref.fontSize).map(k => k.slice(3))]);
const famKeys = new Set([...Object.keys(ext.fontFamily || {}), ...fsKeys]);

const colorUtil = /^(-?)(bg|text|border(?:-[trblxyse])?|ring|ring-offset|from|via|to|fill|stroke|divide|outline|placeholder|shadow|accent|caret|decoration)-(.+?)(\/\d+)?$/;
const spaceUtil = /^(-?)(p[trblxyse]?|m[trblxyse]?|gap(?:-[xy])?|space-[xy]|w|h|min-w|min-h|max-w|max-h|top|bottom|left|right|inset(?:-[xy])?|start|end|translate-[xy]|scroll-m[trblxy]?|scroll-p[trblxy]?|basis)-(.+)$/;

function mapToken(tok) {
  const parts = tok.split(':'); const u = parts.pop();
  let out = u, m;
  if ((m = u.match(/^text-(.+)$/)) && fsKeys.has(m[1])) out = `text-st-${m[1]}`;
  else if ((m = u.match(/^font-(.+)$/)) && famKeys.has(m[1])) return null;
  else if ((m = u.match(colorUtil)) && colorKeys.has(m[3])) out = `${m[1]}${m[2]}-st-${m[3]}${m[4] || ''}`;
  else if ((m = u.match(spaceUtil)) && spaceKeys.has(m[3])) out = `${m[1]}${m[2]}-st-${m[3]}`;
  return [...parts, out].join(':');
}
const attrMap = { class: 'className', for: 'htmlFor', tabindex: 'tabIndex', readonly: 'readOnly', maxlength: 'maxLength',
  colspan: 'colSpan', rowspan: 'rowSpan', 'stroke-width': 'strokeWidth', 'stroke-linecap': 'strokeLinecap',
  'stroke-linejoin': 'strokeLinejoin', 'fill-rule': 'fillRule', 'clip-rule': 'clipRule', 'viewbox': 'viewBox',
  autocomplete: 'autoComplete', srcset: 'srcSet', crossorigin: 'crossOrigin', 'xlink:href': 'xlinkHref', 'xmlns:xlink': 'xmlnsXlink' };
const voids = new Set(['area','base','br','col','embed','hr','img','input','link','meta','source','track','wbr']);
const styleObj = s => '{{' + s.split(';').map(x => x.trim()).filter(Boolean).map(d => {
  const i = d.indexOf(':'); const k = d.slice(0, i).trim(); const v = d.slice(i + 1).trim();
  const key = k.startsWith('--') ? JSON.stringify(k) : k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  return `${key}: ${JSON.stringify(v)}`; }).join(', ') + '}}';

function jsx(node, ind = '') {
  if (node.nodeType === 3) { const t = node.rawText; return t.trim() ? ind + t.trim().replace(/[{}]/g, c => `{'${c}'}`) + '\n' : ''; }
  if (node.nodeType === 8) return ind + `{/* ${node.rawText.trim()} */}\n`;
  const tag = node.rawTagName; if (!tag || ['script','style'].includes(tag)) return '';
  const attrs = Object.entries(node.attributes).filter(([k]) => !/^on[a-z]+$/.test(k) && !k.startsWith('data-')).map(([k, v]) => {
    const name = attrMap[k.toLowerCase()] || k;
    if (k === 'class') { const c = v.split(/\s+/).filter(Boolean).map(mapToken).filter(Boolean).join(' '); return `className="${c}"`; }
    if (k === 'style') return `style=${styleObj(v)}`;
    if (v === '') return name;
    return `${name}=${JSON.stringify(v)}`;
  });
  const open = `<${tag}${attrs.length ? ' ' + attrs.join(' ') : ''}`;
  if (voids.has(tag)) return `${ind}${open} />\n`;
  const kids = node.childNodes.map(c => jsx(c, ind + '  ')).join('');
  return kids ? `${ind}${open}>\n${kids}${ind}</${tag}>\n` : `${ind}${open}></${tag}>\n`;
}
const root = parse(html, { comment: true });
const target = selector ? root.querySelector(selector) : (root.querySelector('body') || root);
if (!target) { console.error('selector not found'); process.exit(1); }
process.stdout.write(selector ? jsx(target) : target.childNodes.map(c => jsx(c)).join(''));
