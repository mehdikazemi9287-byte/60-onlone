import test from 'node:test';
import assert from 'node:assert/strict';
import {coalesceRead, invalidatePendingReads, deadline} from '../src/lib/request-performance.ts';

test('coalesces identical pending reads and expires success immediately', async () => {
  let resolve, calls=0;
  const run=()=>{calls++; return new Promise(r=>resolve=r)};
  const a=coalesceRead('same',run), b=coalesceRead('same',run);
  assert.equal(calls,1); resolve(7); assert.deepEqual(await Promise.all([a,b]),[7,7]);
  await coalesceRead('same',async()=>{calls++;return 8}); assert.equal(calls,2);
});
test('failure is not cached and identities are independent', async()=>{
  await assert.rejects(coalesceRead('fail',async()=>{throw Error('failure')}));
  assert.equal(await coalesceRead('fail',async()=>8),8);
  assert.deepEqual(await Promise.all([coalesceRead('user-a',async()=>1),coalesceRead('user-b',async()=>2)]),[1,2]);
});
test('mutation invalidation isolates new reads from old pending cleanup', async()=>{
  let finish;
  const old=coalesceRead('x',()=>new Promise(r=>finish=r));
  invalidatePendingReads();
  let complete;
  const fresh=coalesceRead('x',()=>new Promise(r=>complete=r));
  finish('old'); await old;
  assert.equal(coalesceRead('x',async()=> 'wrong'),fresh);
  complete('new'); assert.equal(await fresh,'new');
});
test('deadline aborts slow responses and preserves parent abort', async()=>{
  const d=deadline(undefined,10);
  await new Promise(r=>setTimeout(r,20));
  assert.equal(d.signal.aborted,true); assert.equal(d.signal.reason.name,'TimeoutError'); d.dispose();
  const parent=new AbortController(); const c=deadline(parent.signal,1000);
  parent.abort(new Error('caller')); assert.equal(c.signal.reason.message,'caller'); c.dispose();
  const already=deadline(parent.signal); assert.equal(already.signal.aborted,true); already.dispose();
});
test('dispose prevents timeout after successful response',async()=>{
  const d=deadline(undefined,5);d.dispose();await new Promise(r=>setTimeout(r,15));assert.equal(d.signal.aborted,false);
});
