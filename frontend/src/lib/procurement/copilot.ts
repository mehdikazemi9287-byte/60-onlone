// 60AI procurement copilot — deterministic Persian request interpreter.
// Turns free text into DraftOps (never prices or stock) and asks only the
// questions the draft genuinely needs. Runs fully in the browser.

import {
  type Draft, type DraftOp, type LineItem, type Priority, type RequestKind,
  applyOp, newDestination, newItem, allocated,
} from "./draft";
import { JALALI_MONTHS, addDaysIso, jalaliMonthLength, jalaliToIso, toJalali } from "./jalali";

export type CopilotIntent =
  | { kind: "find"; query: string }
  | { kind: "alternatives"; query: string }
  | { kind: "compare"; a: string; b: string }
  | { kind: "status"; ref: string | null }
  | { kind: "guide" };

export interface CopilotResult {
  intent?: CopilotIntent;
  ops: DraftOp[];
  changes: string[];
  questions: string[];
  undo?: boolean;
  searches: { itemId: string; query: string }[];
}

const CITIES: [string, string][] = [
  ["تهران", "تهران"], ["کرج", "البرز"], ["اصفهان", "اصفهان"], ["مشهد", "خراسان رضوی"], ["شیراز", "فارس"],
  ["تبریز", "آذربایجان شرقی"], ["قم", "قم"], ["اهواز", "خوزستان"], ["کرمانشاه", "کرمانشاه"], ["رشت", "گیلان"],
  ["ارومیه", "آذربایجان غربی"], ["یزد", "یزد"], ["کرمان", "کرمان"], ["همدان", "همدان"], ["اراک", "مرکزی"],
  ["قزوین", "قزوین"], ["زنجان", "زنجان"], ["ساری", "مازندران"], ["گرگان", "گلستان"], ["بندرعباس", "هرمزگان"],
  ["بوشهر", "بوشهر"], ["سنندج", "کردستان"], ["خرم‌آباد", "لرستان"], ["زاهدان", "سیستان و بلوچستان"],
  ["اردبیل", "اردبیل"], ["بیرجند", "خراسان جنوبی"], ["بجنورد", "خراسان شمالی"], ["ایلام", "ایلام"],
  ["یاسوج", "کهگیلویه و بویراحمد"], ["شهرکرد", "چهارمحال و بختیاری"], ["سمنان", "سمنان"], ["کیش", "هرمزگان"],
  ["اسلامشهر", "تهران"], ["شهریار", "تهران"], ["پردیس", "تهران"], ["کاشان", "اصفهان"], ["نیشابور", "خراسان رضوی"],
];
const WORD_NUM: Record<string, number> = {
  یک: 1, دو: 2, سه: 3, چهار: 4, پنج: 5, شش: 6, هفت: 7, هشت: 8, نه: 9, ده: 10, یازده: 11, دوازده: 12,
  پانزده: 15, بیست: 20, سی: 30, چهل: 40, پنجاه: 50, صد: 100,
};
const UNIT_WORDS = "عدد|دستگاه|تا|بسته|کارتن|پک|جفت|سری|قلم|سبد|کارت";
const FILLER = /\s*(\s*هم\s*(?:اضافه\s*کن|اضافه|بیفزا).*|\s*(?:اضافه\s*کن|بیفزا).*|لازم\s*داریم|لازم\s*است|نیاز\s*داریم|نیاز\s*است|می[‌ ]?خواهیم|می[‌ ]?خواهم|میخوایم|میخوام|احتیاج\s*داریم|می[‌ ]?خوام|تهیه\s*کنید|بخریم|برای\s+.*|تحویل.*|با\s+بودجه.*|حدود.*|تا\s+.*)$/;
const NOT_ITEM = /^(نفر|پرسنل|کارمند|همکار|گیرنده|میلیون|میلیارد|هزار|تومان|ریال|روز|هفته|ماه|سال|شعبه|درصد|ساعت|مقصد|واحد|سهم)/;

export function normalize(input: string): string {
  return input
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/(\d)[٬,](?=\d{3}\b)/g, "$1")
    .replace(/ي/g, "ی").replace(/ك/g, "ک")
    .replace(/\s+/g, " ")
    .trim();
}

const key = (s: string) => s.replace(/[‌\s]+/g, "").replace(/ها$/, "");
function findItem(d: Draft, name: string): LineItem | undefined {
  const k = key(name);
  if (!k) return undefined;
  return d.items.find((i) => key(i.name) === k) ?? d.items.find((i) => key(i.name).includes(k) || k.includes(key(i.name)));
}
const cityOf = (s: string) => CITIES.find(([c]) => key(s).includes(key(c)));

function amountToman(num: string, scale?: string, currency?: string): number {
  let v = parseFloat(num);
  if (scale === "هزار") v *= 1_000;
  else if (scale === "میلیون") v *= 1_000_000;
  else if (scale === "میلیارد") v *= 1_000_000_000;
  if (currency === "ریال") v /= 10;
  return Math.round(v);
}
const AMOUNT = String.raw`(\d+(?:\.\d+)?)\s*(هزار|میلیون|میلیارد)?\s*(تومان|ریال)?`;

function parseDate(t: string): string | null {
  const iso = t.match(/\b(20\d{2}-\d{2}-\d{2})\b/);
  if (iso) return iso[1];
  const today = toJalali(new Date());
  const month = t.match(new RegExp(`(\\d{1,2})\\s*(${JALALI_MONTHS.join("|")})(?:\\s*(?:ماه)?\\s*(1[34]\\d{2}))?`));
  if (month) {
    const jm = JALALI_MONTHS.indexOf(month[2]) + 1;
    let jy = month[3] ? Number(month[3]) : today.jy;
    if (!month[3] && (jm < today.jm || (jm === today.jm && Number(month[1]) < today.jd))) jy += 1;
    const jd = Math.min(Number(month[1]), jalaliMonthLength(jy, jm));
    return jalaliToIso(jy, jm, jd);
  }
  if (/آخر\s*(همین\s*)?ماه|پایان\s*(همین\s*)?ماه/.test(t)) return jalaliToIso(today.jy, today.jm, jalaliMonthLength(today.jy, today.jm));
  if (/آخر\s*ماه\s*(بعد|آینده)|پایان\s*ماه\s*(بعد|آینده)/.test(t)) {
    const jm = today.jm === 12 ? 1 : today.jm + 1, jy = today.jm === 12 ? today.jy + 1 : today.jy;
    return jalaliToIso(jy, jm, jalaliMonthLength(jy, jm));
  }
  const days = t.match(/(\d+)\s*روز\s*(دیگر|آینده|بعد)/);
  if (days) return addDaysIso(Number(days[1]));
  const weeks = t.match(/(\d+)\s*هفته\s*(دیگر|آینده|بعد)/);
  if (weeks) return addDaysIso(Number(weeks[1]) * 7);
  if (/هفته\s*(آینده|بعد)/.test(t)) return addDaysIso(7);
  if (/آخر\s*(همین\s*)?هفته/.test(t)) {
    const now = new Date();
    return addDaysIso((5 - now.getDay() + 7) % 7 || 7);
  }
  if (/فردا/.test(t)) return addDaysIso(1);
  return null;
}

function parseKind(t: string): RequestKind | null {
  if (/یلدا|نوروز|هدیه|پک|سبد|مناسبت|عید|جشن\s*تولد|کارت\s*هدیه/.test(t)) return "gift_pack";
  if (/مانیتور|لپ\s*‌?تاپ|کیبورد|ماوس|کامپیوتر|رایانه|پرینتر|چاپگر|سرور|سوییچ|روتر|هارد|تبلت|موبایل|گوشی/.test(t)) return "it_equipment";
  if (/کاغذ|خودکار|میز|صندلی|لوازم\s*اداری|تحریر|کلاسور|زونکن/.test(t)) return "office";
  if (/همایش|رویداد|سمینار|کنفرانس|نمایشگاه/.test(t)) return "event";
  return null;
}

function parsePriority(t: string): Priority | null {
  if (/فوری|اضطراری|هر\s*چه\s*زودتر|خیلی\s*عجله/.test(t)) return "urgent";
  if (/اولویت\s*(بالا|زیاد)|مهم\s*است/.test(t)) return "high";
  if (/عجله\s*(ای|‌ای)?\s*نیست|اولویت\s*(پایین|کم)/.test(t)) return "low";
  return null;
}

function parseItems(t: string): { name: string; quantity: number; unit?: string }[] {
  const out: { name: string; quantity: number; unit?: string }[] = [];
  const re = new RegExp(String.raw`(\d+)\s*(${UNIT_WORDS})?\s*([^\d،,؛.\n:]+?)(?=\s*(?:،|,|؛|\.|\n|\sو\s|$|\d))`, "g");
  for (const m of t.matchAll(re)) {
    let name = m[3].replace(/^(عدد|تا)\s+/, "").replace(FILLER, "").replace(/^(از|برای|به)\s+/, "").trim();
    if (!name || NOT_ITEM.test(name) || cityOf(name) && key(name).length <= key(cityOf(name)![0]).length + 1) continue;
    if (/^(میلیون|میلیارد|هزار)/.test(m[2] ?? "")) continue;
    if (/(درصد|روز|هفته|ماه|آذر|دی|بهمن|اسفند|فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان)$/.test(name)) continue;
    name = name.replace(/\s+(ها|های)$/, "").slice(0, 120);
    const unit = m[2] && !["تا", "قلم"].includes(m[2]) ? m[2] : undefined;
    out.push({ name, quantity: Number(m[1]), unit });
  }
  return out;
}

function parsePack(t: string): string | null {
  const m = t.match(/((?:پک|سبد|بسته|کارت)\s*(?:هدیه\s*)?[^\d،,؛.\n]{0,40})/);
  if (!m) return null;
  const name = m[1].replace(FILLER, "").trim();
  return name.length >= 3 ? name : null;
}

function parseAllocations(t: string): { city: string; province: string; count: number }[] {
  const out: { city: string; province: string; count: number }[] = [];
  for (const [city, province] of CITIES) {
    const a = t.match(new RegExp(`${city}\\s*[:：—\\-–]?\\s*(\\d+)`)) ?? t.match(new RegExp(`(\\d+)\\s*(?:${UNIT_WORDS}|نفر)?\\s*(?:برای|به|در|ویژه)?\\s*${city}`));
    if (a) out.push({ city, province, count: Number(a[1]) });
  }
  return out;
}

function mentionedCities(t: string) {
  return CITIES.filter(([c]) => new RegExp(`(^|[\\s،,؛و])${c}($|[\\s،,؛.و:])`).test(t));
}

export function interpret(raw: string, d: Draft): CopilotResult {
  const t = normalize(raw);
  const res: CopilotResult = { ops: [], changes: [], questions: [], searches: [] };
  const add = (op: DraftOp, change?: string) => { res.ops.push(op); if (change) res.changes.push(change); };
  // Work on a scratch copy so later rules see earlier edits in the same message.
  let scratch: Draft = d;
  const push = (op: DraftOp, change?: string, next?: (x: Draft) => Draft) => { add(op, change); if (next) scratch = next(scratch); };

  // ── Lookups that answer from live data instead of editing the draft ────
  const compare = t.match(/^(?:مقایسه(?:\s*کن)?)\s+(.+?)\s+(?:و|با)\s+(.+?)(?:\s*(?:را|رو))?(?:\s*مقایسه\s*کن)?$/);
  if (compare) return { ...res, intent: { kind: "compare", a: compare[1].trim(), b: compare[2].trim() } };
  const alt = t.match(/(?:جایگزین|مشابه)\s+(?:برای\s+)?(.+?)(?:\s+(?:چی\s*داری|پیشنهاد\s*بده|بده|چیه|هست))?[؟?]?$/);
  if (alt && !/جایگزین\s*کن/.test(t)) return { ...res, intent: { kind: "alternatives", query: alt[1].replace(/\s*(را|رو)$/, "").trim() } };
  const status = t.match(/(?:وضعیت|پیگیری|کجاست)/) && t.match(/(درخواست|سفارش|پرونده|PR-)/);
  if (status) { const ref = t.match(/PR-\d{8}-\d{4}/i); return { ...res, intent: { kind: "status", ref: ref ? ref[0].toUpperCase() : null } }; }
  if (/(قدم|مرحله)\s*(بعد|بعدی)|حالا\s*چ(ی|ه)\s*کار|چه\s*کار\s*کنم|راهنمایی/.test(t)) return { ...res, intent: { kind: "guide" } };
  const find = t.match(/^(.+?)\s*(?:پیدا\s*کن|را\s*پیدا\s*کن|داری[؟?]?|دارید[؟?]?|موجوده[؟?]?|را\s*جستجو\s*کن|بگرد)$/) ?? t.match(/^(?:پیدا\s*کن|جستجو\s*کن|بگرد|دنبال)\s+(.+?)(?:\s*(?:می‌گردم|میگردم|هستم))?$/);
  if (find && !/\d/.test(find[1])) return { ...res, intent: { kind: "find", query: find[1].replace(/^(یک|یه)\s+/, "").replace(/\s*(مناسب.*)$/, "").trim() } };

  if (/^(برگرد|بازگردان|undo|آخرین\s*تغییر\s*(را\s*)?(برگردان|لغو\s*کن)|لغو\s*آخرین\s*تغییر)/i.test(t)) return { ...res, undo: true };

  // ── Edit commands on an existing draft ───────────────────────────────────
  const note = t.match(/^(توضیح|یادداشت)\s*[:：]\s*(.+)$/);
  if (note) {
    push({ type: "set", patch: { notes: [d.notes, note[2]].filter(Boolean).join("\n") } }, "توضیح به پیش‌نویس اضافه شد");
    return res;
  }
  const remove = t.match(/^(.+?)\s*(?:را|رو)?\s*(?:حذف\s*کن|بردار|پاک\s*کن|حذف)$/);
  if (remove) {
    const target = remove[1].replace(/^(مقصد|قلم|کالای?)\s+/, "");
    const item = findItem(d, target);
    const dest = d.destinations.find((x) => x.city && (key(target).includes(key(x.city)) || (x.label && key(target).includes(key(x.label)))));
    if (dest && (/مقصد|شعبه/.test(remove[1]) || !item)) { push({ type: "removeDestination", id: dest.id }, `مقصد «${dest.label || dest.city}» حذف شد`); return res; }
    if (item) { push({ type: "removeItem", id: item.id }, `«${item.name}» حذف شد`); return res; }
  }
  const replace = t.match(/^(.+?)\s*(?:را|رو)\s*(?:با|به)\s+(.+?)\s*(?:جایگزین\s*کن|عوض\s*کن|تعویض\s*کن)$/);
  if (replace) {
    const item = findItem(d, replace[1]);
    if (item) {
      push({ type: "updateItem", id: item.id, patch: { name: replace[2], masterProductId: null, sku: null, imageUrl: null, verifiedPriceMinor: null, catalog: "searching" } },
        `«${item.name}» با «${replace[2]}» جایگزین شد`);
      res.searches.push({ itemId: item.id, query: replace[2] });
      return res;
    }
  }
  const setQty = t.match(/^تعداد\s+(.+?)\s+(?:را|رو)?\s*(?:به\s*)?(\d+)\s*(?:عدد|تا)?\s*(?:کن|برسان|تغییر\s*بده)?$/)
    ?? t.match(/^(.+?)\s+(?:را|رو)\s+(?:به\s*)?(\d+)\s*(?:عدد|تا)?\s*(?:کن|برسان)$/);
  if (setQty) {
    const item = findItem(d, setQty[1]);
    if (item) { push({ type: "updateItem", id: item.id, patch: { quantity: Number(setQty[2]) } }, `تعداد «${item.name}» ← ${setQty[2]}`); return res; }
  }
  const delta = t.match(/^(\d+)\s*(?:عدد|تا)?\s*(?:به|از)?\s*(.+?)\s*(اضافه\s*کن|بیشتر\s*کن|اضافه|کم\s*کن|کمتر\s*کن)$/);
  if (delta) {
    const item = findItem(d, delta[2]);
    const n = Number(delta[1]) * (/کم/.test(delta[3]) ? -1 : 1);
    if (item) {
      const q = Math.max(1, item.quantity + n);
      push({ type: "updateItem", id: item.id, patch: { quantity: q } }, `تعداد «${item.name}» ← ${q}`);
      return res;
    }
  }
  const pct = t.match(/بودجه(?:\s*کل)?\s*(?:را|رو)?\s*(\d+)\s*درصد\s*(بیشتر|افزایش|زیاد|کمتر|کاهش|کم)/);
  if (pct && (d.budgetTotalToman || d.budgetPerCapitaToman)) {
    const f = 1 + (Number(pct[1]) / 100) * (/کم|کاهش/.test(pct[2]) ? -1 : 1);
    const patch = d.budgetTotalToman
      ? { budgetTotalToman: Math.round(d.budgetTotalToman * f) }
      : { budgetPerCapitaToman: Math.round((d.budgetPerCapitaToman ?? 0) * f) };
    push({ type: "set", patch }, `بودجه ${pct[1]}٪ ${/کم|کاهش/.test(pct[2]) ? "کاهش" : "افزایش"} یافت`);
    return res;
  }
  if (/(مساوی|برابر|یکسان)/.test(t) && /تقسیم|پخش|سهم/.test(t)) {
    push({ type: "splitEqual" }, "تعداد اقلام به‌طور مساوی بین مقصدها تقسیم شد");
    return res;
  }

  // ── Structured extraction (new request or additions) ─────────────────────
  const kind = parseKind(t);
  if (kind && (d.kind === "general" || !d.items.length)) push({ type: "set", patch: { kind } }, undefined, (x) => ({ ...x, kind }));

  let recipients: number | null = null;
  const rec = t.match(/(\d+)\s*(?:نفر|پرسنل|کارمند|همکار|گیرنده|نیرو)/)
    ?? t.match(new RegExp(`(${Object.keys(WORD_NUM).join("|")})\\s*(?:نفر|کارمند)`));
  if (rec) {
    recipients = /\d/.test(rec[1]) ? Number(rec[1]) : WORD_NUM[rec[1]];
    push({ type: "set", patch: { recipients } }, `تعداد گیرندگان: ${recipients.toLocaleString("fa-IR")} نفر`, (x) => ({ ...x, recipients }));
  }

  const perCap = t.match(new RegExp(`${AMOUNT}\\s*(?:برای|به\\s*ازای)?\\s*(?:هر\\s*نفر|سرانه|هر\\s*پک|هر\\s*گیرنده|نفری)`))
    ?? t.match(new RegExp(`(?:هر\\s*نفر|سرانه|نفری|هر\\s*پک)\\s*(?:حدود|تقریباً|تقریبا)?\\s*${AMOUNT}`));
  if (perCap) {
    const v = amountToman(perCap[1], perCap[2], perCap[3]);
    push({ type: "set", patch: { budgetPerCapitaToman: v } }, `بودجه سرانه: ${v.toLocaleString("fa-IR")} تومان`);
  } else {
    const total = t.match(new RegExp(`بودجه(?:\\s*کل)?\\s*(?:حدود|تقریباً|تقریبا|را|رو|به)?\\s*${AMOUNT}`))
      ?? t.match(new RegExp(`${AMOUNT}\\s*(?:بودجه|در\\s*مجموع|کل)`));
    if (total) {
      const v = amountToman(total[1], total[2], total[3]);
      if (v >= 10_000) push({ type: "set", patch: { budgetTotalToman: v } }, `بودجه کل: ${v.toLocaleString("fa-IR")} تومان`);
    }
  }

  const date = parseDate(t);
  if (date) push({ type: "set", patch: { neededBy: date } }, "تاریخ موردنیاز ثبت شد");
  const priority = parsePriority(t);
  if (priority) push({ type: "set", patch: { priority } }, `اولویت: ${{ low: "کم", normal: "عادی", high: "بالا", urgent: "فوری" }[priority]}`);

  const constraints = t.split(/[.؛\n]/).map((s) => s.trim())
    .filter((s) => /(بدون|فقط|حتماً|حتما|برند|اصل|گارانتی|ضمانت|ایرانی|خارجی|حلال|انقضا|بسته‌بندی|بسته بندی|لوگو)/.test(s) && s.length <= 160);
  if (constraints.length) {
    const merged = Array.from(new Set([...d.constraints, ...constraints]));
    push({ type: "set", patch: { constraints: merged } }, `محدودیت ثبت شد: ${constraints.join("؛ ")}`);
  }

  // Items
  const found = parseItems(t).filter((x) => !(recipients && x.quantity === recipients && /^(نفر|پرسنل)/.test(x.name)));
  const pack = parsePack(t);
  if (pack && !found.some((f) => key(f.name).includes(key(pack)) || key(pack).includes(key(f.name)))) {
    found.push({ name: pack, quantity: recipients ?? 0, unit: "پک" });
  }
  for (const f of found) {
    const existing = findItem(scratch, f.name);
    if (existing) {
      if (f.quantity) push({ type: "updateItem", id: existing.id, patch: { quantity: f.quantity } }, `تعداد «${existing.name}» ← ${f.quantity}`);
      continue;
    }
    const item = newItem(f.name, f.quantity || 1, { unit: f.unit ?? "", catalog: "searching" });
    push({ type: "addItem", item }, `قلم «${f.name}» × ${(f.quantity || 1).toLocaleString("fa-IR")} اضافه شد`,
      (x) => ({ ...x, items: [...x.items, item] }));
    res.searches.push({ itemId: item.id, query: f.name });
    if (!f.quantity) res.questions.push(`برای «${f.name}» چند عدد لازم است؟`);
  }

  if (!d.title.trim() && scratch.items.length) {
    const names = scratch.items.slice(0, 3).map((i) => i.name);
    const title = scratch.kind === "gift_pack" && recipients
      ? `${names[0]} — ${recipients.toLocaleString("fa-IR")} نفر`
      : names.length > 1 ? `${names.slice(0, -1).join("، ")} و ${names[names.length - 1]}` : names[0];
    push({ type: "set", patch: { title: title.slice(0, 200) } }, `عنوان: ${title}`);
  }

  // Destinations & allocations
  const allocs = parseAllocations(t);
  const cities = mentionedCities(t);
  const wanted = allocs.length ? allocs.map((a) => ({ city: a.city, province: a.province })) : cities.map(([city, province]) => ({ city, province }));
  const counts: Record<string, number> = {};
  let dests = scratch.destinations;
  for (const w of wanted) {
    let dest = dests.find((x) => key(x.city) === key(w.city));
    if (!dest) {
      const blank = dests.find((x) => !x.city && !x.address && !x.province);
      if (blank) {
        push({ type: "updateDestination", id: blank.id, patch: { city: w.city, province: w.province, label: w.city } }, `مقصد «${w.city}» ثبت شد`);
        dest = { ...blank, city: w.city, province: w.province, label: w.city };
        dests = dests.map((x) => (x.id === blank.id ? dest! : x));
      } else {
        dest = newDestination({ city: w.city, province: w.province, label: w.city });
        push({ type: "addDestination", destination: dest }, `مقصد «${w.city}» اضافه شد`);
        dests = [...dests, dest];
      }
    }
    const a = allocs.find((x) => x.city === w.city);
    if (a) counts[dest.id] = a.count;
  }
  scratch = { ...scratch, destinations: dests };
  if (Object.keys(counts).length && dests.length > 1) {
    push({ type: "splitByCounts", counts }, "سهم هر مقصد بر اساس تعداد اعلام‌شده تقسیم شد");
    const sum = Object.values(counts).reduce((a, b) => a + b, 0);
    const single = scratch.items.length === 1 ? scratch.items[0] : null;
    if (single && sum !== single.quantity && !recipients) {
      push({ type: "updateItem", id: single.id, patch: { quantity: sum } }, `تعداد «${single.name}» ← ${sum} (جمع سهم مقصدها)`);
      push({ type: "splitByCounts", counts });
    }
  } else if (dests.length > 1 && wanted.length > 1) {
    push({ type: "splitEqual" }, "تعداد فعلاً مساوی بین مقصدها تقسیم شد؛ برای سهم دقیق بنویسید مثلاً «تهران ۱۵۰، کرج ۸۰»");
  }
  const branches = t.match(new RegExp(`(\\d+|${Object.keys(WORD_NUM).join("|")})\\s*(?:شعبه|واحد|دفتر|انبار)`));
  const branchCount = branches ? (/\d/.test(branches[1]) ? Number(branches[1]) : WORD_NUM[branches[1]]) : 0;

  // ── Only the questions the draft really needs ────────────────────────────
  const after = res.ops.reduce(applyOp, d);
  const q: string[] = [...res.questions];
  if (!res.ops.length && !res.changes.length) {
    return {
      ...res,
      questions: ["متوجه نشدم چه تغییری لازم است. می‌توانید بنویسید مثلاً «۱۲۰ مانیتور و ۸۰ کیبورد برای تهران و کرج تا آخر ماه» یا «کیبورد را حذف کن»."],
    };
  }
  if (!after.items.length && !found.length) q.push("چه کالاهایی و هر کدام چه تعدادی لازم است؟");
  if (branchCount > Math.max(wanted.length, after.destinations.filter((x) => x.city).length))
    q.push(`نام شهر ${branchCount.toLocaleString("fa-IR")} شعبه را بنویسید (مثلاً «تهران ۵۰، کرج ۴۰، اصفهان ۳۰»).`);
  else if (!after.destinations.some((x) => x.city)) q.push("مقصد تحویل کجاست؟ (شهر یا شعبه‌ها)");
  else if (after.destinations.length > 1 && !Object.keys(counts).length && after.items.some((i) => allocated(after, i.id) !== i.quantity))
    q.push("سهم هر مقصد چقدر باشد؟ مثلاً «تهران ۱۵۰، کرج ۸۰» یا بنویسید «مساوی تقسیم کن».");
  if (!after.neededBy && !date) q.push("تاریخ موردنیاز تحویل چه روزی است؟");
  res.questions = q.slice(0, 2);
  return res;
}

export const COPILOT_EXAMPLES = [
  "برای ۳۰۰ نفر پک شب یلدا می‌خواهم، حدود ۲ میلیون برای هر نفر، تحویل تهران و کرج",
  "برای سه شعبه ۱۲۰ مانیتور، ۸۰ کیبورد و ۴۰ لپ‌تاپ لازم داریم. تحویل تا آخر ماه",
  "تهران ۱۵۰، کرج ۸۰، اصفهان ۷۰",
];
