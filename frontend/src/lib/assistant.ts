// Deterministic, rule-based shopping assistant. No LLM. No fabrication.
// Single source of truth: the real staging/production catalog API
// (/api/v1/products, /api/v1/categories). It never invents SKUs, prices,
// stock, or unrelated fallback products.

export type PriceStatus = "verified" | "unpriced";
export type PurchaseStatus = "purchasable" | "inquiry-only" | "unavailable";

export interface RawProduct {
  id: number; slug: string; sku?: string; title_fa: string;
  brand_fa: string | null; category_slug: string; category_name_fa: string;
  price: number | null; price_minor: number | null; currency?: string;
  in_stock: boolean; purchasable: boolean; quantity_available: number | null;
  image_url: string | null;
}

export interface AssistantProduct {
  id: number; slug: string; title: string; brand: string | null;
  categorySlug: string; categoryName: string;
  price: number | null; currency: string; inStock: boolean;
  priceStatus: PriceStatus; purchaseStatus: PurchaseStatus;
  imageUrl: string | null;
}

export interface ParsedQuery {
  raw: string;
  categorySlug: string | null;
  categoryName: string | null;
  budgetMin: number | null;
  budgetMax: number | null;
  brand: string | null;
  inStockOnly: boolean;
  keywords: string[];
}

export interface AssistantMatch { product: AssistantProduct; score: number; reasons: string[]; }
export interface AssistantResult {
  parsed: ParsedQuery;
  matches: AssistantMatch[];
  total: number;
  note: string | null;
  disclaimers: string[];
}

// slug -> Persian trigger words (all real category slugs of the store)
const CATEGORY_KEYWORDS: Record<string, string[]> = {
  laptop: ["لپ‌تاپ", "لپ تاپ", "لپتاپ", "نوت بوک", "نوت‌بوک", "رایانه", "کامپیوتر"],
  mobile: ["موبایل", "گوشی", "تلفن همراه", "اسمارت فون", "تبلت"],
  office: ["صندلی اداری", "میز اداری", "لوازم اداری", "میز کار"],
  network: ["شبکه", "روتر", "مودم", "سوییچ", "سوئیچ", "اکسس پوینت", "میکروتیک"],
  appliance: ["لوازم برقی", "کتری برقی", "آبسردکن", "مایکروویو", "اتو بخار", "چای ساز"],
  supermarket: ["سوپرمارکت", "برنج", "روغن", "خواربار", "مایحتاج", "ماکارونی", "قند", "شکر"],
  "protein-fresh": ["گوشت", "ماهی", "مرغ", "پروتئین", "قزل آلا", "قزل‌آلا", "گوساله", "گوسفند", "بوقلمون", "شترمرغ"],
  "fresh-dairy-frozen": ["لبنیات", "شیر", "ماست", "پنیر", "کره", "بستنی", "منجمد", "میوه", "سبزیجات", "کفیر", "خامه"],
  "nuts-local": ["آجیل", "خشکبار", "پسته", "بادام", "نخودچی", "تخمه", "خرما", "مغز", "کشمش", "محلی"],
  "home-kitchen": ["خانه و آشپزخانه", "قابلمه", "سرویس آشپزخانه", "ظرف", "لوازم آشپزی", "سرویس قاشق"],
  appliances: ["لوازم خانگی", "یخچال", "فریزر", "لباسشویی", "تلویزیون", "ظرفشویی", "کولر", "بخاری", "جاروبرقی"],
  digital: ["کالای دیجیتال", "دیجیتال", "هدفون", "هدست", "مانیتور", "پاوربانک", "اسپیکر", "کنسول"],
  fashion: ["پوشاک", "لباس", "کفش", "کیف", "مانتو", "شلوار", "پیراهن", "کاپشن"],
  "beauty-health": ["زیبایی", "بهداشت", "آرایشی", "مراقبت پوست", "عطر", "شامپو", "کرم", "لوازم آرایش"],
  "mother-child-toys": ["مادر و کودک", "نوزاد", "اسباب بازی", "اسباب‌بازی", "پوشک", "سیسمونی", "کالسکه"],
  "books-stationery": ["کتاب", "نوشت افزار", "نوشت‌افزار", "دفتر", "خودکار", "لوازم التحریر", "فرهنگ"],
  "sports-camping": ["ورزش", "ورزشی", "کمپینگ", "کوهنوردی", "چادر مسافرتی", "دمبل", "تردمیل", "کوله پشتی"],
  "auto-tools": ["خودرو", "ابزار", "آچار", "دریل", "لوازم خودرو", "ابزارآلات", "جک"],
  "office-org": ["اداری و سازمانی", "تجهیزات سازمانی"],
  "gift-seasonal": ["هدیه", "کادو", "کادویی", "مناسبتی", "یلدا", "نوروز", "عید", "سبد هدیه"],
};

const STOPWORDS = new Set([
  "می", "خواهم", "میخوام", "می‌خوام", "یک", "یه", "با", "برای", "از", "به", "در", "و", "که", "تا",
  "زیر", "بالای", "کمتر", "بیشتر", "حداکثر", "حداقل", "بین", "قیمت", "تومان", "تومن", "میلیون", "هزار",
  "موجود", "دارید", "دارین", "میخواهم", "لطفا", "لطفاً", "پیشنهاد", "بده", "کن", "چی", "چه", "خوب",
  "ارزان", "گران", "بهترین", "نیاز", "دارم", "می‌خواهم",
]);

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
function normalizeDigits(s: string): string {
  return s.replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d)))
          .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
}
function normalize(s: string): string {
  return normalizeDigits(s).replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/‌/g, " ").replace(/\s+/g, " ").trim();
}

// Parse a Toman amount that may use میلیون / هزار multipliers.
function parseAmount(numStr: string, unit: string | undefined): number {
  let n = parseFloat(numStr.replace(/[,،]/g, ""));
  if (!isFinite(n)) return NaN;
  if (unit && unit.includes("میلیون")) n *= 1_000_000;
  else if (unit && unit.includes("هزار")) n *= 1_000;
  return Math.round(n);
}

export function parseQuery(raw: string, knownBrands: string[]): ParsedQuery {
  const text = normalize(raw);
  const low = text;

  // category
  let categorySlug: string | null = null;
  for (const [slug, words] of Object.entries(CATEGORY_KEYWORDS)) {
    if (words.some((w) => low.includes(normalize(w)))) { categorySlug = slug; break; }
  }

  // budget
  let budgetMin: number | null = null;
  let budgetMax: number | null = null;
  const amt = "([\\d.,،]+)\\s*(میلیون|هزار)?";
  let m: RegExpMatchArray | null;
  if ((m = low.match(new RegExp("بین\\s*" + amt + "\\s*تا\\s*" + amt)))) {
    budgetMin = parseAmount(m[1], m[2]); budgetMax = parseAmount(m[3], m[4]);
  } else if ((m = low.match(new RegExp(amt + "\\s*تا\\s*" + amt + "\\s*(تومان|تومن)?")))) {
    budgetMin = parseAmount(m[1], m[2]); budgetMax = parseAmount(m[3], m[4]);
  } else if ((m = low.match(new RegExp("(زیر|کمتر از|تا|حداکثر|زیرِ)\\s*" + amt)))) {
    budgetMax = parseAmount(m[2], m[3]);
  } else if ((m = low.match(new RegExp("(بالای|بیشتر از|از|حداقل)\\s*" + amt)))) {
    budgetMin = parseAmount(m[2], m[3]);
  }
  if (budgetMin != null && !isFinite(budgetMin)) budgetMin = null;
  if (budgetMax != null && !isFinite(budgetMax)) budgetMax = null;

  // brand (only real brands present in the catalog)
  let brand: string | null = null;
  for (const b of knownBrands) {
    if (b && low.includes(normalize(b))) { brand = b; break; }
  }

  // in-stock intent
  const inStockOnly = /(فقط\s*)?موجود|قابل خرید|همین الان/.test(low);

  // remaining keywords
  const keywords = low.split(" ")
    .map((t) => t.replace(/[.,،؛:!؟"'()]/g, ""))
    .filter((t) => t.length >= 2 && !STOPWORDS.has(t) && !/^\d+$/.test(t));

  return {
    raw, categorySlug, categoryName: null,
    budgetMin, budgetMax, brand, inStockOnly, keywords,
  };
}

function toAssistantProduct(p: RawProduct): AssistantProduct {
  const priceStatus: PriceStatus = p.price != null ? "verified" : "unpriced";
  let purchaseStatus: PurchaseStatus;
  if (p.purchasable) purchaseStatus = "purchasable";
  else purchaseStatus = "inquiry-only";
  return {
    id: p.id, slug: p.slug, title: p.title_fa, brand: p.brand_fa,
    categorySlug: p.category_slug, categoryName: p.category_name_fa,
    price: p.price, currency: p.currency || "IRR", inStock: !!p.in_stock,
    priceStatus, purchaseStatus, imageUrl: p.image_url,
  };
}

export function runAssistant(
  raw: string,
  products: RawProduct[],
  categories: { slug: string; name_fa: string }[],
): AssistantResult {
  const knownBrands = Array.from(new Set(products.map((p) => p.brand_fa).filter(Boolean))) as string[];
  const parsed = parseQuery(raw, knownBrands);
  if (parsed.categorySlug) {
    parsed.categoryName = categories.find((c) => c.slug === parsed.categorySlug)?.name_fa ?? null;
  }

  const matches: AssistantMatch[] = [];
  for (const rp of products) {
    const p = toAssistantProduct(rp);
    const reasons: string[] = [];
    let score = 0;
    let disqualified = false;

    if (parsed.categorySlug) {
      if (p.categorySlug === parsed.categorySlug) { score += 4; reasons.push(`در دسته «${p.categoryName}»`); }
      else disqualified = true;
    }
    if (parsed.brand) {
      if (p.brand && normalize(p.brand) === normalize(parsed.brand)) { score += 4; reasons.push(`برند «${p.brand}»`); }
      else if (parsed.categorySlug || parsed.keywords.length === 0) disqualified = true;
    }
    if (parsed.inStockOnly && !p.inStock) disqualified = true;

    const titleN = normalize(p.title);
    let kwHits = 0;
    for (const kw of parsed.keywords) {
      if (titleN.includes(kw) || (p.brand && normalize(p.brand).includes(kw))) {
        kwHits++; score += 2; reasons.push(`عبارت «${kw}» در نام کالا`);
      }
    }
    // If the only signal is keywords and none hit, skip.
    if (!parsed.categorySlug && !parsed.brand && parsed.keywords.length > 0 && kwHits === 0) disqualified = true;

    // budget
    if (parsed.budgetMin != null || parsed.budgetMax != null) {
      if (p.priceStatus === "verified" && p.price != null) {
        const okMin = parsed.budgetMin == null || p.price >= parsed.budgetMin;
        const okMax = parsed.budgetMax == null || p.price <= parsed.budgetMax;
        if (okMin && okMax) { score += 3; reasons.push("قیمت در محدوده بودجه شما"); }
        else disqualified = true;
      } else {
        // unpriced: cannot confirm budget — keep only if another strong signal exists
        if (!parsed.categorySlug && !parsed.brand && kwHits === 0) disqualified = true;
        else reasons.push("قیمت این کالا هنوز اعلام نشده (خارج از مقایسه بودجه)");
      }
    }

    if (p.inStock) { score += 1; reasons.push("موجود در انبار"); }

    if (disqualified || score <= 0) continue;
    matches.push({ product: p, score, reasons });
  }

  matches.sort((a, b) => b.score - a.score || a.product.id - b.product.id);

  const disclaimers = [
    "این دستیار قاعده‌محور است و فقط از کاتالوگ واقعی فروشگاه استفاده می‌کند؛ هیچ کالا، قیمت یا موجودی ساختگی نمایش داده نمی‌شود.",
  ];
  if (matches.some((m) => m.product.priceStatus === "unpriced"))
    disclaimers.push("کالاهای «بدون قیمت» فعلاً فقط قابل مشاهده و استعلام هستند و خرید آنها فعال نیست.");
  if (matches.some((m) => m.product.purchaseStatus !== "purchasable"))
    disclaimers.push("برخی نتایج در حال حاضر «استعلامی» هستند و از طریق فرم درخواست پیگیری می‌شوند.");

  let note: string | null = null;
  if (matches.length === 0) {
    note = "هیچ کالایی در کاتالوگ واقعی با این شرایط پیدا نشد. شرایط را ساده‌تر کنید یا دسته دیگری را امتحان کنید.";
  }

  return { parsed, matches, total: matches.length, note, disclaimers };
}

// ─────────────────────────────────────────────────────────────────────────────
// Professional pack layer — extracts budget / recipient-count / tier / purpose
// from Persian free text and builds a REAL pack draft that Pack Builder consumes.
// No fabricated product/price/stock. Auto budget-optimised packs use ONLY
// verified-priced products; otherwise an honest inquiry draft is produced.
// ─────────────────────────────────────────────────────────────────────────────

const AMT_RE = "([\\d.,،]+)\\s*(میلیون|هزار)?";

// purpose word -> real category slugs
const PACK_PURPOSES: { words: string[]; label: string; groups: string[] }[] = [
  { words: ["معیشتی", "معیشت", "خوار و بار", "خواروبار", "سبد کالا", "ارزاق"], label: "معیشتی", groups: ["protein-fresh", "supermarket", "fresh-dairy-frozen", "nuts-local"] },
  { words: ["هدیه", "کادو", "کادویی"], label: "هدیه", groups: ["gift-seasonal", "nuts-local", "beauty-health"] },
  { words: ["مناسبتی", "یلدا", "نوروز", "عید", "شب چله"], label: "مناسبتی", groups: ["gift-seasonal", "nuts-local"] },
  { words: ["شرکتی", "سازمانی", "کارمندی", "پرسنلی"], label: "سازمانی", groups: ["office", "office-org", "digital", "gift-seasonal"] },
  { words: ["مدرسه", "دانش آموزی", "تحصیلی", "بازگشایی مدارس"], label: "مدرسه", groups: ["books-stationery", "digital"] },
  { words: ["خانه", "منزل", "لوازم خانه", "جهیزیه"], label: "خانه", groups: ["appliances", "appliance", "home-kitchen", "supermarket"] },
];

const TIER_WORDS: { tier: PackTier; words: string[] }[] = [
  { tier: "economic", words: ["اقتصادی", "ارزان", "کم هزینه", "صرفه جو"] },
  { tier: "balanced", words: ["متعادل", "معمولی", "استاندارد", "متوسط"] },
  { tier: "premium", words: ["باکیفیت", "با کیفیت", "ویژه", "لوکس", "درجه یک", "درجه ۱", "پریمیوم", "ممتاز"] },
];
const TIER_MULT: Record<PackTier, number> = { economic: 0.75, balanced: 1, premium: 1.35 };

export type PackTier = "economic" | "balanced" | "premium";

export interface PackConstraints {
  recipientCount: number | null;
  perPersonToman: number | null;
  totalToman: number | null;
  tier: PackTier | null;
  purposeLabel: string | null;
  groupSlugs: string[];
  addGroups: string[];
  removeGroups: string[];
}

export interface PackDraftItem {
  slug: string; title: string; categorySlug: string; categoryName: string;
  priceMinor: number | null; quantity: number; imageUrl: string | null;
}
export interface PackDraft {
  constraints: PackConstraints;
  effPerPersonToman: number | null;
  effTotalToman: number | null;
  items: PackDraftItem[];
  pricedCount: number;
  unpricedCount: number;
  needsPriceConfirmation: boolean;
  totalMinor: number | null;
  explanation: string[];
  followUps: string[];
  alternatives: { slug: string; title: string; priceMinor: number | null; note: string }[];
}

const GROUP_CONNECTORS = new Set(["و", "با", "رو", "را", "هم", "برای", "یک", "یه", "کن", "که", "این", "اون", "تا", "از", "به", "در"]);
function catWordToSlug(w: string): string | null {
  const n = normalize(w).trim();
  if (n.length < 3 || GROUP_CONNECTORS.has(n)) return null;
  for (const [slug, words] of Object.entries(CATEGORY_KEYWORDS)) {
    // exact keyword, or the user token *contains* a full keyword ("لپ‌تاپ‌ها" ⊇ "لپ تاپ").
    // The reverse (keyword ⊇ token) is deliberately NOT allowed — it let connectors like
    // "و" spuriously match "نوت بوک" → laptop.
    if (words.some((k) => { const nk = normalize(k); return n === nk || n.includes(nk); })) return slug;
  }
  return null;
}

export function parsePackConstraints(raw: string): PackConstraints {
  const low = normalize(raw);
  let m: RegExpMatchArray | null;

  let recipientCount: number | null = null;
  if ((m = low.match(/(\d+)\s*نفر/))) recipientCount = parseInt(m[1], 10);
  if (recipientCount != null && (!isFinite(recipientCount) || recipientCount <= 0)) recipientCount = null;

  let perPersonToman: number | null = null;
  if ((m = low.match(new RegExp("(نفری|هر\\s*نفر(?:\\s*(?:حداکثر|تا|نهایت))?|به\\s*ازای\\s*هر\\s*نفر(?:\\s*(?:حداکثر|تا))?)\\s*" + AMT_RE))))
    perPersonToman = parseAmount(m[2], m[3]);
  if (perPersonToman != null && !isFinite(perPersonToman)) perPersonToman = null;

  let totalToman: number | null = null;
  if ((m = low.match(new RegExp("(بودجه\\s*(?:کل|کلی|مجموع|جمعا|جمعاً)|کل\\s*بودجه|مجموع\\s*بودجه|مجموعا|مجموعاً|روی\\s*هم)\\s*" + AMT_RE))))
    totalToman = parseAmount(m[2], m[3]);
  // bare "بودجه X" only if no per-person and no total captured yet
  if (totalToman == null && perPersonToman == null && (m = low.match(new RegExp("بودجه\\s*" + AMT_RE))))
    totalToman = parseAmount(m[1], m[2]);
  if (totalToman != null && !isFinite(totalToman)) totalToman = null;

  let tier: PackTier | null = null;
  for (const t of TIER_WORDS) if (t.words.some((w) => low.includes(normalize(w)))) { tier = t.tier; break; }

  let purposeLabel: string | null = null;
  let groupSlugs: string[] = [];
  for (const p of PACK_PURPOSES) if (p.words.some((w) => low.includes(normalize(w)))) { purposeLabel = p.label; groupSlugs = [...p.groups]; break; }

  // explicit add / remove group — handles Persian SOV order (X را حذف کن) and (حذف کن X)
  const addGroups: string[] = [];
  const removeGroups: string[] = [];
  const W = "([؀-ۿ‌ ]{2,20}?)";
  const grab = (re: RegExp, sink: string[]) => {
    for (const mm of low.matchAll(re)) {
      const cand = (mm[1] || mm[2] || "").trim();
      const sl = catWordToSlug(cand);
      if (sl && !sink.includes(sl)) sink.push(sl);
    }
  };
  grab(new RegExp(W + "\\s*(?:رو|را|هم)?\\s*(?:اضافه\\s*کن|اضافه\\s*کردن|بذار|اضافه)", "g"), addGroups);
  grab(new RegExp("(?:اضافه\\s*کن|بذار|با)\\s+" + W, "g"), addGroups);
  grab(new RegExp(W + "\\s*(?:رو|را)?\\s*(?:حذف\\s*کن|حذف\\s*کردن|بردار|نمی\\s*خوام|نمیخوام|نخواستم)", "g"), removeGroups);
  grab(new RegExp("(?:حذف\\s*کن|بردار|بدون|منهای)\\s+" + W, "g"), removeGroups);

  return { recipientCount, perPersonToman, totalToman, tier, purposeLabel, groupSlugs, addGroups, removeGroups };
}

// Greedy fill of one per-person basket toward `targetToman`, priced items only.
function fillBasket(pricedSorted: RawProduct[], targetToman: number): RawProduct[] {
  const out: RawProduct[] = [];
  let total = 0;
  for (const p of pricedSorted) {
    const t = (p.price as number);
    if (out.length >= 8 && total >= targetToman * 0.6) break;
    if (total + t > targetToman * 1.15 && out.length > 0) continue;
    out.push(p); total += t;
    if (total >= targetToman * 0.85 && out.length >= 3) break;
  }
  return out;
}

export function buildPackDraft(
  raw: string,
  products: RawProduct[],
  categories: { slug: string; name_fa: string }[],
): PackDraft {
  const c = parsePackConstraints(raw);
  // also fold in generic parseQuery category if no purpose matched
  const pq = parseQuery(raw, []);
  let groups = c.groupSlugs.length ? [...c.groupSlugs] : (pq.categorySlug ? [pq.categorySlug] : []);
  for (const g of c.addGroups) if (!groups.includes(g)) groups.push(g);
  groups = groups.filter((g) => !c.removeGroups.includes(g));
  if (!groups.length) groups = ["protein-fresh", "supermarket", "fresh-dairy-frozen", "nuts-local"]; // معیشتی default

  const catName = (s: string) => categories.find((x) => x.slug === s)?.name_fa ?? s;
  const inGroups = products.filter((p) => groups.includes(p.category_slug));
  const priced = inGroups.filter((p) => p.price != null && (p.price as number) > 0);
  const unpriced = inGroups.filter((p) => p.price == null);

  const effPerPerson =
    c.perPersonToman != null ? c.perPersonToman
    : c.totalToman != null && c.recipientCount ? Math.floor(c.totalToman / c.recipientCount)
    : null;
  const effTotal =
    c.totalToman != null ? c.totalToman
    : c.perPersonToman != null && c.recipientCount ? c.perPersonToman * c.recipientCount
    : null;

  const explanation: string[] = [];
  const followUps: string[] = [];
  let items: PackDraftItem[] = [];
  let needsPriceConfirmation = false;

  const grpLabels = groups.map(catName).join("، ");
  explanation.push(`دسته‌های در نظر گرفته‌شده: ${grpLabels}.`);
  if (c.purposeLabel) explanation.push(`نوع پک: ${c.purposeLabel}${c.tier ? ` (${c.tier === "economic" ? "اقتصادی" : c.tier === "premium" ? "باکیفیت" : "متعادل"})` : ""}.`);
  if (c.recipientCount) explanation.push(`تعداد نفرات: ${c.recipientCount}.`);
  if (effPerPerson) explanation.push(`بودجه هر نفر: حدود ${effPerPerson.toLocaleString("fa-IR")} تومان.`);
  if (effTotal) explanation.push(`بودجه کل: حدود ${effTotal.toLocaleString("fa-IR")} تومان.`);

  const qty = c.recipientCount && c.recipientCount > 0 ? c.recipientCount : 1;

  if (priced.length >= 2 && effPerPerson) {
    const mult = c.tier ? TIER_MULT[c.tier] : 1;
    const target = Math.round(effPerPerson * mult);
    const chosen = fillBasket([...priced].sort((a, b) => (a.price as number) - (b.price as number)), target);
    items = chosen.map((p) => ({
      slug: p.slug, title: p.title_fa, categorySlug: p.category_slug, categoryName: p.category_name_fa,
      priceMinor: p.price_minor, quantity: qty, imageUrl: p.image_url,
    }));
    const perPersonMinor = items.reduce((s, i) => s + (i.priceMinor as number), 0);
    explanation.push(`پک بر اساس ${items.length} قلم کالای دارای قیمت رسمی ساخته شد؛ جمع هر نفر ${Math.round(perPersonMinor / 10).toLocaleString("fa-IR")} تومان.`);
    if (unpriced.length) explanation.push(`${unpriced.length} کالای دیگر این دسته‌ها هنوز قیمت رسمی ندارند و در محاسبه‌ی بودجه نیامده‌اند.`);
  } else {
    // Honest inquiry draft — real products, no fake total.
    needsPriceConfirmation = true;
    const pick = (priced.length ? priced : inGroups).slice(0, 8);
    items = pick.map((p) => ({
      slug: p.slug, title: p.title_fa, categorySlug: p.category_slug, categoryName: p.category_name_fa,
      priceMinor: p.price_minor, quantity: qty, imageUrl: p.image_url,
    }));
    if (!priced.length && inGroups.length) {
      explanation.push("هیچ‌کدام از کالاهای این دسته‌ها در حال حاضر قیمت رسمی ندارند؛ پک به‌صورت «استعلامی» ساخته شد و جمع دقیق آن پس از تأیید قیمت مشخص می‌شود.");
    } else if (!inGroups.length) {
      explanation.push("در این دسته‌ها کالایی در کاتالوگ یافت نشد.");
      followUps.push("کدام دسته‌ها مدنظرتان است؟ (مثلاً آجیل، برنج و روغن، لبنیات)");
    } else {
      explanation.push("برای ساخت خودکار پک نیازمند بودجه‌ی هر نفر و چند قلم کالای دارای قیمت رسمی هستیم.");
    }
    if (!effPerPerson && !effTotal) followUps.push("بودجه‌ی کل یا بودجه‌ی هر نفر چقدر است؟");
    if (!c.recipientCount) followUps.push("پک برای چند نفر می‌خواهید؟");
  }

  const pricedCount = items.filter((i) => i.priceMinor != null).length;
  const unpricedCount = items.length - pricedCount;
  const totalMinor = unpricedCount === 0 && items.length
    ? items.reduce((s, i) => s + (i.priceMinor as number) * i.quantity, 0)
    : null;
  if (unpricedCount > 0) needsPriceConfirmation = true;

  // cheaper / better alternatives from the same groups (real products only)
  const alternatives = priced
    .filter((p) => !items.some((i) => i.slug === p.slug))
    .sort((a, b) => (a.price as number) - (b.price as number))
    .slice(0, 4)
    .map((p) => ({ slug: p.slug, title: p.title_fa, priceMinor: p.price_minor, note: `${Math.round((p.price as number)).toLocaleString("fa-IR")} تومان` }));

  return {
    constraints: c, effPerPersonToman: effPerPerson, effTotalToman: effTotal,
    items, pricedCount, unpricedCount, needsPriceConfirmation, totalMinor,
    explanation, followUps, alternatives,
  };
}
