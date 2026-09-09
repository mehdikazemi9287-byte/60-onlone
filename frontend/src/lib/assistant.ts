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
