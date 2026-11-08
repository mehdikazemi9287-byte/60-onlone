/* Isolated synthetic fixtures only. No API, database, real user or network calls. */
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
let tsPath;
try { tsPath = require.resolve('typescript'); }
catch { tsPath = require.resolve(path.join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'typescript')); }
const ts = require(tsPath);
const frontend = path.resolve(__dirname, '..');
const admin = path.join(frontend, 'src/components/admin');
const build = fs.mkdtempSync(path.join(os.tmpdir(), '60online-admin-test-'));
after(() => fs.rmSync(build, { recursive: true, force: true }));
// Semantic typecheck of pure helpers, not a full Next.js application build.
execFileSync(process.execPath, [path.resolve(path.dirname(tsPath), '../bin/tsc'),
  path.join(admin, 'dashboard-state.ts'), path.join(admin, 'catalog-file.ts'),
  '--strict', '--target', 'ES2020', '--lib', 'ES2020,DOM', '--module', 'commonjs',
  '--outDir', build, '--pretty', 'false'], { stdio: 'pipe' });
const d = require(path.join(build, 'dashboard-state.js'));
const csv = require(path.join(build, 'catalog-file.js'));
const item = (kind, id = 1) => ({ id, kind, title: 'TEST FIXTURE — NOT CATALOG DATA', status: 'open',
  href: { customer_request: '/admin/inquiries', catalog_image: '/admin/catalog-review', supplier: '/admin/suppliers' }[kind] });
const snapshot = () => ({ environment: 'test', as_of: '2026-10-14T10:00:00+00:00', timezone: 'Asia/Tehran',
  metrics: { personal_today: 0, org_waiting: 2 }, attention: [item('customer_request')], attention_is_sample: true,
  operations: { scope_count: 1, items: [], has_more: false }, integrations: { sepidar: 'not_connected' } });
const encodedFile = (text, name = 'test.csv') => {
  const bytes = new TextEncoder().encode(text);
  return { name, size: bytes.byteLength, arrayBuffer: async () => bytes.buffer };
};

test('metrics preserve verified zero and positive integers', () => {
  for (const n of [0, 1, 1039, Number.MAX_SAFE_INTEGER]) assert.equal(d.metricValue(n), n);
});
test('unknown metrics never silently become zero', () => {
  for (const x of [null, undefined, '', '0', false, -1, 1.2, NaN, Infinity, [], {}, Number.MAX_SAFE_INTEGER + 1])
    assert.equal(d.metricValue(x), null);
});
test('all filter returns a copy without mutation', () => {
  const source = Object.freeze([item('supplier')]); const result = d.filterAttention(source, 'all');
  assert.deepEqual(result, source); assert.notEqual(result, source);
});
test('each filter contains only the requested kind', () => {
  const source = ['customer_request', 'catalog_image', 'supplier'].map((kind, i) => item(kind, i + 1));
  for (const kind of ['customer_request', 'catalog_image', 'supplier']) {
    assert.deepEqual(d.filterAttention(source, kind), source.filter(x => x.kind === kind));
  }
});
test('pending operations never show a permission or empty message', () => {
  assert.equal(d.operationsState(null, true), 'pending');
  assert.equal(d.operationsState({ scope_count: 0, items: [], has_more: false }, true), 'pending');
});
test('unavailable, forbidden, empty and populated operations are distinct', () => {
  assert.equal(d.operationsState(null, false), 'unavailable');
  assert.equal(d.operationsState({ scope_count: 0, items: [], has_more: false }, false), 'forbidden');
  assert.equal(d.operationsState({ scope_count: 1, items: [], has_more: false }, false), 'empty');
  assert.equal(d.operationsState({ scope_count: 1, items: [{ id: 1 }], has_more: true }, false), 'ready');
});
test('snapshot time uses the requested timezone', () => {
  const stamp = '2026-10-14T10:00:00Z';
  assert.equal(d.formatSnapshotTime(stamp, 'Asia/Tehran'), new Intl.DateTimeFormat('fa-IR', {
    hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tehran' }).format(new Date(stamp)));
});
test('invalid dates or timezone produce unknown, not invented time', () => {
  assert.equal(d.formatSnapshotTime('', 'UTC'), null);
  assert.equal(d.formatSnapshotTime('invalid', 'UTC'), null);
  assert.equal(d.formatSnapshotTime('2026-10-14T00:00:00Z', 'invalid/timezone'), null);
});
test('verified API-shaped snapshot remains unchanged', () => {
  const value = snapshot(); assert.equal(d.parseDashboard(value), value);
});
test('missing or malformed response sections fail explicitly', () => {
  for (const key of ['environment', 'as_of', 'timezone', 'metrics', 'attention', 'attention_is_sample', 'operations', 'integrations']) {
    const value = snapshot(); delete value[key]; assert.throws(() => d.parseDashboard(value));
  }
  for (const value of [null, [], '', 1]) assert.throws(() => d.parseDashboard(value));
});
test('attention href cannot navigate outside the verified admin route', () => {
  for (const href of ['https://example.invalid', '//example.invalid', 'javascript:alert(1)', '/admin/access']) {
    const value = snapshot(); value.attention[0].href = href; assert.throws(() => d.parseDashboard(value));
  }
});
test('unknown and prototype-named attention kinds are rejected', () => {
  for (const kind of ['other', '__proto__', 'constructor', 'toString']) {
    const value = snapshot(); value.attention[0].kind = kind; assert.throws(() => d.parseDashboard(value));
  }
});
test('all three canonical attention destinations are accepted', () => {
  const value = snapshot(); value.attention = ['customer_request', 'catalog_image', 'supplier'].map(k => item(k));
  assert.equal(d.parseDashboard(value), value);
});
test('zero organization scope cannot contain operations or claim more items', () => {
  const value = snapshot(); value.operations.scope_count = 0; value.operations.has_more = true;
  assert.throws(() => d.parseDashboard(value));
  value.operations.has_more = false; value.operations.items = [{ id: 1, organization_id: 1, title: 'TEST' }];
  assert.throws(() => d.parseDashboard(value));
});
test('operations identifiers must be positive integers', () => {
  for (const id of [0, -1, '1', 1.5]) {
    const value = snapshot(); value.operations.items = [{ id, organization_id: 1, title: 'TEST' }];
    assert.throws(() => d.parseDashboard(value));
  }
});
test('header-only template has no invented rows, price or publish status', () => {
  assert.equal(csv.CATALOG_CSV_TEMPLATE.replace(/^\uFEFF/, ''), 'canonical_name_fa,category_slug\r\n');
});
test('valid UTF-8 Persian file is preserved byte-for-text', async () => {
  const text = 'canonical_name_fa,category_slug\nآزمون مستقل,TEST_ONLY\n';
  assert.equal(await csv.readCatalogCsv(encodedFile(text)), text);
});
test('UTF-8 BOM exported by spreadsheet tools is accepted', async () => {
  assert.equal(await csv.readCatalogCsv(encodedFile(csv.CATALOG_CSV_TEMPLATE)), 'canonical_name_fa,category_slug\r\n');
});
test('uppercase CSV extension is accepted', async () => {
  assert.equal(await csv.readCatalogCsv(encodedFile('a,b\n', 'TEST.CSV')), 'a,b\n');
});
test('wrong file type is rejected before reading', async () => {
  let read = false;
  await assert.rejects(csv.readCatalogCsv({ name: 'test.xlsx', size: 20, arrayBuffer: async () => { read = true; return new ArrayBuffer(20); } }));
  assert.equal(read, false);
});
test('empty, invalid and oversized files are rejected before allocation', async () => {
  for (const size of [0, -1, NaN, 0.5, csv.MAX_CSV_BYTES + 1]) {
    let read = false;
    await assert.rejects(csv.readCatalogCsv({ name: 'test.csv', size, arrayBuffer: async () => { read = true; return new ArrayBuffer(1); } }));
    assert.equal(read, false);
  }
});
test('file I/O failure produces an actionable error', async () => {
  await assert.rejects(csv.readCatalogCsv({ name: 'test.csv', size: 1, arrayBuffer: async () => { throw new Error('disk'); } }), /خواندن/);
});
test('invalid UTF-8 and binary null bytes are rejected', async () => {
  const bytes = Uint8Array.from([0xc3, 0x28]);
  await assert.rejects(csv.readCatalogCsv({ name: 'test.csv', size: 2, arrayBuffer: async () => bytes.buffer }), /UTF-8/);
  await assert.rejects(csv.readCatalogCsv(encodedFile('a\u0000,b')));
});
test('incomplete reads and whitespace-only files cannot reach preview', async () => {
  await assert.rejects(csv.readCatalogCsv({ name: 'test.csv', size: 5, arrayBuffer: async () => new ArrayBuffer(2) }));
  await assert.rejects(csv.readCatalogCsv(encodedFile('  \r\n')));
});
test('three changed React components transpile without syntax diagnostics (not full build)', () => {
  for (const relative of ['admin/AdminDashboard.tsx', 'admin/AdminShell.tsx', 'AdminCatalog.tsx']) {
    const file = path.join(frontend, 'src/components', relative);
    const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, reportDiagnostics: true,
      compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.Preserve, isolatedModules: true } });
    assert.deepEqual((result.diagnostics || []).filter(x => x.category === ts.DiagnosticCategory.Error), [], relative);
  }
});
test('dashboard import shortcut targets the actual catalog anchor', () => {
  const dashboard = fs.readFileSync(path.join(admin, 'AdminDashboard.tsx'), 'utf8');
  const catalog = fs.readFileSync(path.join(frontend, 'src/components/AdminCatalog.tsx'), 'utf8');
  assert.ok(dashboard.includes('/admin/catalog#catalog-import'));
  assert.ok(catalog.includes('id="catalog-import"'));
});
test('all CSS-module references in the changed dashboard and shell exist', () => {
  const cssText = fs.readFileSync(path.join(admin, 'admin.module.css'), 'utf8');
  for (const name of ['AdminDashboard.tsx', 'AdminShell.tsx']) {
    const source = fs.readFileSync(path.join(admin, name), 'utf8');
    for (const [, key] of source.matchAll(/\bs\.([a-zA-Z][a-zA-Z0-9_]*)/g))
      assert.match(cssText, new RegExp('\\.' + key + '(?![\\w-])'), name + ':' + key);
  }
});
