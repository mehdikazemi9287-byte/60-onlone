import test from "node:test";
import assert from "node:assert/strict";
import {
  addItem, budgetState, buildRecommendations, filterPriced, packTotalMinor,
  removeItem, replaceItem, setQuantity,
} from "./pack-builder.reference.mjs";
const product = (id, price_minor, in_stock = true) => ({ id, price_minor, in_stock });
test("filterPriced drops products with no real price", () => {
  assert.deepEqual(filterPriced([product(1,100000),{id:2,price_minor:null},{id:3}]).map(p=>p.id),[1]);
});
test("packTotalMinor sums price * quantity exactly", () => {
  assert.equal(packTotalMinor([{product:product(1,1000000),quantity:2},{product:product(2,500000),quantity:3}]),3500000);
});
test("addItem merges quantity on repeat add", () => {
  let items = addItem([], product(1,100000), 1);
  items = addItem(items, product(1,100000), 2);
  assert.equal(items.length,1); assert.equal(items[0].quantity,3);
});
test("removeItem drops matching line only", () => {
  assert.deepEqual(removeItem([{product:product(1,1),quantity:1},{product:product(2,2),quantity:1}],1).map(it=>it.product.id),[2]);
});
test("setQuantity clamps to removal at zero", () => {
  const items=[{product:product(1,100000),quantity:2}];
  assert.equal(setQuantity(items,1,5)[0].quantity,5);
  assert.deepEqual(setQuantity(items,1,0),[]);
});
test("replaceItem swaps product keeps quantity", () => {
  const next=replaceItem([{product:product(1,1),quantity:4}],1,product(9,250000));
  assert.equal(next[0].product.id,9); assert.equal(next[0].quantity,4);
});
test("budgetState remaining + over-budget", () => {
  const under=budgetState([{product:product(1,1000000),quantity:3}],5000000);
  assert.equal(under.remaining_minor,2000000); assert.equal(under.over_budget,false);
  const over=budgetState([{product:product(1,1000000),quantity:3}],2000000);
  assert.equal(over.over_budget,true);
});
test("buildRecommendations never invents price, stays within tier target", () => {
  const products=[product(1,500000),product(2,1000000),product(3,2000000),product(4,5000000),{id:5,price_minor:null},product(6,3000000,false)];
  const recs=buildRecommendations(products,10_000_000);
  for(const t of [recs.economy,recs.balanced,recs.premium]) for(const it of t.items){assert.notEqual(it.product.id,5);assert.notEqual(it.product.id,6);}
  assert.ok(recs.economy.total_minor<=Math.floor(10_000_000*0.6));
  assert.ok(recs.premium.total_minor>=recs.economy.total_minor);
});
test("buildRecommendations empty tiers when nothing fits", () => {
  const recs=buildRecommendations([product(1,50_000_000)],1_000_000);
  assert.deepEqual(recs.economy.items,[]); assert.deepEqual(recs.premium.items,[]);
});
