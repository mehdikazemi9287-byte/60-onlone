/* Isolated synthetic fixtures only. No API, database or network calls. Audit SO-04. */
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
let tsPath;
try { tsPath = require.resolve('typescript'); }
catch { tsPath = require.resolve(path.join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'typescript')); }
const frontend = path.resolve(__dirname, '..');
const build = fs.mkdtempSync(path.join(os.tmpdir(), '60online-trust-test-'));
after(() => fs.rmSync(build, { recursive: true, force: true }));
execFileSync(process.execPath, [path.resolve(path.dirname(tsPath), '../bin/tsc'),
  path.join(frontend, 'src/app/products/[id]/price-trust.ts'),
  '--strict', '--target', 'ES2020', '--module', 'commonjs', '--outDir', build, '--pretty', 'false'], { stdio: 'pipe' });
const { priceTrustText } = require(path.join(build, 'price-trust.js'));
const VERIFIED = 'تأییدشده';

test('a sale-eligible seller price may be called verified', () => {
  assert.ok(priceTrustText({ price_minor: 1_000_000, list_price_minor: null }).includes(VERIFIED));
});
test('a supplier list price never claims a verified price', () => {
  const t = priceTrustText({ price_minor: null, list_price_minor: 880_000 });
  assert.ok(!t.includes(VERIFIED));
  assert.ok(t.includes('فهرست'));
});
test('an inquiry-only item claims neither verified price nor verified stock', () => {
  for (const d of [{}, { price_minor: null, list_price_minor: null }, { price_minor: undefined, list_price_minor: 0 }])
    assert.ok(!priceTrustText(d).includes(VERIFIED));
});
test('the product page uses the helper, not a fixed claim', () => {
  const src = fs.readFileSync(path.join(frontend, 'src/app/products/[id]/ProductDetail.tsx'), 'utf8');
  assert.ok(src.includes('priceTrustText(d)'));
  assert.ok(!src.includes('همیشه قیمت تأییدشده'));
});
