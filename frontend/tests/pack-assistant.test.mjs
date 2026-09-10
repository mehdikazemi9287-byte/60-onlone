// Regression + behavioural tests for the pack-assistant parser, run against the
// live staging /api/assistant (deterministic, no LLM).
import test from "node:test";
import assert from "node:assert/strict";
import { get } from "node:http";

const B = process.env.ASSIST_BASE || "http://127.0.0.1:3064";
function ask(q) {
  return new Promise((res, rej) => {
    get(B + "/api/assistant?q=" + encodeURIComponent(q), (r) => {
      let d = ""; r.on("data", (c) => (d += c));
      r.on("end", () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
    }).on("error", rej);
  });
}
const groups = (d) => d.packDraft.constraints;

test("REGRESSION: شوینده must not add/remove/match laptop", async () => {
  const d = await ask("برای ۳۰ نفر یک پک معیشتی با بودجه کل ۴۵ میلیون می‌خواهم. برنج را حذف کن و شوینده اضافه کن.");
  const c = groups(d);
  assert.ok(!c.addGroups.includes("laptop"), "laptop wrongly added: " + JSON.stringify(c.addGroups));
  assert.ok(!c.removeGroups.includes("laptop"), "laptop wrongly removed: " + JSON.stringify(c.removeGroups));
  // real intent still honoured:
  assert.equal(c.recipientCount, 30);
  assert.equal(d.packDraft.effPerPersonToman, 1_500_000);
  assert.equal(d.packDraft.effTotalToman, 45_000_000);
  assert.ok(c.removeGroups.includes("supermarket"), "برنج should remove supermarket group");
  assert.equal(c.purposeLabel, "معیشتی");
  assert.equal(d.packDraft.totalMinor, null); // no fabricated total (0 priced products)
});

test("connectors alone never match a category", async () => {
  const d = await ask("پک هدیه برای ۱۰ نفر و با بودجه نفری ۱ میلیون");
  const c = groups(d);
  assert.deepEqual(c.addGroups.filter((g) => g === "laptop"), []);
});

test("valid group edits still work", async () => {
  const d1 = await ask("پک معیشتی ۴۰ نفر نفری ۳ میلیون، لبنیات را حذف کن");
  assert.ok(groups(d1).removeGroups.includes("fresh-dairy-frozen"));
  const d2 = await ask("پک معیشتی ۴۰ نفر نفری ۳ میلیون، آجیل هم اضافه کن");
  assert.ok(groups(d2).addGroups.includes("nuts-local"));
});

test("budget math: total→per-person and per-person→total", async () => {
  const a = await ask("پک متعادل برای ۵۰ نفر، نفری ۲ میلیون تومان");
  assert.equal(a.packDraft.effTotalToman, 100_000_000);
  assert.equal(a.packDraft.constraints.tier, "balanced");
  const b = await ask("پک معیشتی برای ۳۰ نفر، بودجه کل ۴۵ میلیون تومان");
  assert.equal(b.packDraft.effPerPersonToman, 1_500_000);
});
