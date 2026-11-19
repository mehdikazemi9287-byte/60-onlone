import test from 'node:test';
import assert from 'node:assert/strict';
import {readCatalogPages} from '../src/lib/paged-catalog.ts';
test('bounded parallel pages preserve ordering and the 50-page ceiling',async()=>{
  let inFlight=0,maximum=0,calls=0;
  const items=await readCatalogPages(async(page)=>{
    calls++;inFlight++;maximum=Math.max(maximum,inFlight);
    await new Promise(r=>setTimeout(r,5-(page%4)));
    inFlight--;return {items:[page],total_pages:100};
  });
  assert.equal(maximum,4);assert.equal(calls,50);assert.deepEqual(items,Array.from({length:50},(_,i)=>i+1));
});
test('failure cancels siblings',async()=>{
  let signal;
  await assert.rejects(readCatalogPages(async(page,s)=>{signal=s;if(page===1)return {items:[],total_pages:5};if(page===2)throw Error('failed');return new Promise((resolve,reject)=>s.addEventListener('abort',()=>reject(s.reason),{once:true}));}));
  assert.equal(signal.aborted,true);
});
test('deadline and caller cancellation propagate',async()=>{
  const read=async(page,s)=>new Promise((resolve,reject)=>{if(s.aborted)reject(s.reason);else s.addEventListener('abort',()=>reject(s.reason),{once:true});});
  await assert.rejects(readCatalogPages(read,undefined,5),{name:'TimeoutError'});
  const c=new AbortController();c.abort();await assert.rejects(readCatalogPages(read,c.signal),{name:'AbortError'});
});
test('malformed pagination fails instead of unbounded reads',async()=>{
  await assert.rejects(readCatalogPages(async()=>({items:[],total_pages:Infinity})),/Invalid catalog/);
});
