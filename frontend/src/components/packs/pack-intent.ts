// 60AI hero input → Budget Builder parameters. This only turns the buyer's Persian sentence into the
// three inputs of the real `/storefront/pack-builder` endpoint (count, budget per pack, occasion).
// No products, prices or stock are produced here; the suggestion itself comes from the backend.

export type PackIntent = { people: number | null; budgetToman: number | null; occasion: string | null };

const FA = "۰۱۲۳۴۵۶۷۸۹", AR = "٠١٢٣٤٥٦٧٨٩";
function norm(s: string): string {
  return s.replace(/[۰-۹]/g, (d) => String(FA.indexOf(d))).replace(/[٠-٩]/g, (d) => String(AR.indexOf(d)))
    .replace(/٫/g, ".").replace(/[٬,،](?=\d{3}\b)/g, "").replace(/ي/g, "ی").replace(/ك/g, "ک")
    .replace(/‌/g, " ").replace(/\s+/g, " ").trim();
}
function amount(num: string, unit?: string): number | null {
  const n = parseFloat(num);
  if (!Number.isFinite(n) || n <= 0) return null;
  const v = unit === "میلیون" ? n * 1_000_000 : unit === "هزار" ? n * 1_000 : n;
  const r = Math.round(v);
  return Number.isSafeInteger(r) ? r : null;
}

// Order matters: the first matching occasion wins (keys = BudgetBuilder / backend OCCASION_CATEGORIES).
const OCCASION_WORDS: [string, string[]][] = [
  ["ramadan", ["رمضان", "افطار", "افطاری"]],
  ["yalda", ["یلدا", "شب چله"]],
  ["nowruz", ["نوروز", "عید نوروز", "عیدانه"]],
  ["religious", ["نذر", "نذری", "محرم", "مذهبی", "هیئت", "مسجد"]],
  ["charity", ["خیریه", "نیازمند", "مستمند", "مهربانی"]],
  ["stationery", ["لوازم التحریر", "نوشت افزار", "مدرسه", "مدارس", "تحصیلی", "مهر"]],
  ["cultural", ["فرهنگی", "کتاب"]],
  ["welfare", ["رفاهی"]],
  ["livelihood", ["معیشتی", "ارزاق", "سبد کالا", "خواروبار", "خوار و بار"]],
];

export function parsePackIntent(raw: string): PackIntent {
  const t = norm(raw);
  let people: number | null = null, budgetToman: number | null = null, occasion: string | null = null;
  const p = t.match(/(\d+)\s*(?:نفر|پک|بسته|عدد|پرسنل|کارمند|خانوار)/);
  if (p) { const n = Number(p[1]); if (Number.isSafeInteger(n) && n > 0 && n <= 100000) people = n; }
  const amountRe = "(\\d+(?:\\.\\d+)?)\\s*(میلیون|هزار)?";
  const total = t.match(new RegExp("(?:بودجه\\s*(?:کل|کلی)|کل\\s*بودجه|مجموعا|جمعا)\\s*" + amountRe));
  const per = t.match(new RegExp("(?:سقف|حداکثر|تا|بودجه(?:\\s*هر\\s*(?:پک|بسته|نفر))?|هر\\s*(?:پک|بسته|نفر)|نفری|سرانه)\\s*" + amountRe));
  if (total) {
    const v = amount(total[1], total[2]);
    if (v && people) budgetToman = Math.floor(v / people);
  } else if (per) budgetToman = amount(per[1], per[2]);
  else {
    const any = t.match(/(\d+(?:\.\d+)?)\s*(میلیون|هزار)\s*(?:تومان|تومن)?/);
    if (any) budgetToman = amount(any[1], any[2]);
  }
  for (const [key, words] of OCCASION_WORDS) if (words.some((w) => t.includes(w))) { occasion = key; break; }
  return { people, budgetToman, occasion };
}
