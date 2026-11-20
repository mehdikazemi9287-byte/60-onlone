/* Isolated synthetic tests for src/lib/chunk-reload.ts. No network, no browser, no business data. */
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const tsPath = require.resolve('typescript');
const frontend = path.resolve(__dirname, '..');
const build = fs.mkdtempSync(path.join(os.tmpdir(), '60online-chunk-test-'));
after(() => fs.rmSync(build, { recursive: true, force: true }));
execFileSync(process.execPath, [path.resolve(path.dirname(tsPath), '../bin/tsc'),
  path.join(frontend, 'src/lib/chunk-reload.ts'),
  '--strict', '--target', 'ES2020', '--lib', 'ES2020,DOM', '--module', 'commonjs',
  '--outDir', build, '--pretty', 'false'], { stdio: 'pipe' });
const c = require(path.join(build, 'chunk-reload.js'));

const memStore = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };

test('detects chunk / dynamic import failures and ignores other errors', () => {
  const e = new Error('Loading chunk 123 failed.\n(error: https://x/_next/static/chunks/123.js)'); e.name = 'ChunkLoadError';
  assert.equal(c.isChunkLoadError(e), true);
  assert.equal(c.isChunkLoadError({ name: 'Error', message: 'Loading CSS chunk 7 failed.' }), true);
  assert.equal(c.isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: https://x/a.js')), true);
  assert.equal(c.isChunkLoadError('Importing a module script failed.'), true);
  assert.equal(c.isChunkLoadError(new Error('Cannot read properties of undefined')), false);
  assert.equal(c.isChunkLoadError(new TypeError('Failed to fetch')), false);
  assert.equal(c.isChunkLoadError(null), false);
});

test('only our own /_next/static scripts count', () => {
  const o = 'https://60online.example';
  assert.equal(c.isOwnChunkScriptUrl('/_next/static/chunks/app/page-abc.js', o), true);
  assert.equal(c.isOwnChunkScriptUrl(o + '/_next/static/chunks/1.js', o), true);
  assert.equal(c.isOwnChunkScriptUrl('https://other.example/_next/static/chunks/1.js', o), false);
  assert.equal(c.isOwnChunkScriptUrl('/analytics.js', o), false);
});

test('reloads at most once per path inside the window (no loop)', () => {
  const s = memStore(); const t = 1_000_000;
  assert.equal(c.claimReload(s, '/cart', t), true);
  assert.equal(c.claimReload(s, '/cart', t + 1000), false);
  assert.equal(c.claimReload(s, '/cart', t + c.RELOAD_WINDOW_MS - 1), false);
  assert.equal(c.claimReload(s, '/cart', t + c.RELOAD_WINDOW_MS + 1), true);
  assert.equal(c.claimReload(s, '/checkout', t + c.RELOAD_WINDOW_MS + 2), true);
});

test('no storage, broken storage or silently failing writes never reload', () => {
  assert.equal(c.claimReload(null, '/', 1), false);
  assert.equal(c.claimReload({ getItem() { throw new Error('denied'); }, setItem() {} }, '/', 1), false);
  assert.equal(c.claimReload({ getItem: () => null, setItem() {} }, '/', 1), false);
  const s = memStore(); s.setItem(c.RELOAD_KEY, '{not json');
  assert.equal(c.claimReload(s, '/', 5), true); // corrupt record is replaced, then the guard holds
  assert.equal(c.claimReload(s, '/', 6), false);
});
