"use client";

// Smart 60 Pack Builder — Candidate A visual/UX (3-step flow, suggestion cards,
// Customizer) wired to the REAL current storefront APIs. No static bundled
// catalog, no hardcoded prices/stock, no fake cart/save/proforma.
//   products  -> GET /api/v1/products   (catalog.list)
//   add-to-cart -> POST /api/v1/cart/items  (cart.add)
//   proforma  -> POST /api/v1/requests  (kind=procurement)
//   save pack -> no production backend -> control disabled ("به‌زودی")
// PRICE RULE: no verified price => never invented; unpriced items are shown as
// "استعلام قیمت", excluded from every numeric total and from recommendations.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Search, Plus, Minus, X, RefreshCw, Check, ShoppingCart, FileText,
  Smartphone, Home as HomeIcon, ShoppingBasket, Snowflake, Gift, Pencil,
  Wheat, Leaf, PackagePlus, Laptop, Sparkles,
} from "lucide-react";
import { catalog, categories as categoriesApi, cart as cartApi, apiRequest, newIdempotencyKey } from "@/lib/api";
import { formatTomanExact, toPersianNum } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import type { Product } from "@/lib/types";

// ── Model ────────────────────────────────────────────────────────────────────
interface PackItem {
  id: number;
  slug: string;
  name: string;
  priceMinor: number | null; // IRR minor; null = no verified price
  groupSlug: string;
  imageUrl?: string;
  inStock: boolean;
}
const toToman = (m: number) => Math.round(m / 10);
const priced = (i: PackItem): i is PackItem & { priceMinor: number } =>
  typeof i.priceMinor === "number" && i.priceMinor > 0;

function fromProduct(p: Product): PackItem {
  return {
    id: p.id,
    slug: p.slug,
    name: p.name,
    priceMinor: p.price_minor != null && p.price_minor > 0 ? p.price_minor : null,
    groupSlug: p.category?.slug ?? "other",
    imageUrl: p.image_url || undefined,
    inStock: p.stock !== 0,
  };
}

const GROUP_ICON: Record<string, LucideIcon> = {
  digital: Smartphone, laptop: Laptop, mobile: Smartphone,
  appliances: HomeIcon, appliance: HomeIcon, "home-kitchen": HomeIcon,
  "protein-fresh": Wheat, "nuts-local": Leaf, supermarket: ShoppingBasket,
  "fresh-dairy-frozen": Snowflake, "gift-seasonal": Gift, "books-stationery": Pencil,
};
const iconFor = (slug: string) => GROUP_ICON[slug] ?? PackagePlus;

// occasion step — real category slugs only
const PURPOSES = [
  { key: "family", label: "معیشتی", groups: ["protein-fresh", "supermarket", "fresh-dairy-frozen"] },
  { key: "gift", label: "هدیه", groups: ["gift-seasonal", "nuts-local", "beauty-health"] },
  { key: "school", label: "مدرسه", groups: ["books-stationery", "digital"] },
  { key: "corporate", label: "شرکتی", groups: ["office", "office-org", "digital", "gift-seasonal"] },
  { key: "occasion", label: "مناسبتی", groups: ["gift-seasonal", "nuts-local"] },
  { key: "home", label: "خانه", groups: ["appliances", "appliance", "home-kitchen", "supermarket"] },
  { key: "custom", label: "سایر / پک سفارشی", groups: [] as string[] },
] as const;
type PurposeKey = (typeof PURPOSES)[number]["key"];

const BUDGET_TIERS = [
  { label: "۲ میلیون", ceilingToman: 2_000_000 },
  { label: "۵ میلیون", ceilingToman: 5_000_000 },
  { label: "۱۰ میلیون", ceilingToman: 10_000_000 },
];

// ── Recommendation engine (Candidate A concept; PRICED items only) ────────────
interface SuggestedPack { key: string; title: string; items: PackItem[]; totalToman: number; recommended?: boolean; insufficient: boolean; }

function pickItems(pool: (PackItem & { priceMinor: number })[], targetToman: number, countHint: number): PackItem[] {
  const sorted = [...pool].sort((a, b) => a.priceMinor - b.priceMinor);
  const out: PackItem[] = [];
  let total = 0;
  for (const it of sorted) {
    const t = toToman(it.priceMinor);
    if (out.length >= countHint && total >= targetToman * 0.6) break;
    if (total + t > targetToman * 1.2 && out.length > 0) continue;
    out.push(it); total += t;
    if (total >= targetToman * 0.85 && out.length >= Math.min(3, countHint)) break;
  }
  return out;
}

function buildSuggestions(pool: PackItem[], budgetToman: number, excludeIds: Set<number>): SuggestedPack[] {
  const eligible = pool.filter((i) => priced(i) && i.inStock && !excludeIds.has(i.id)) as (PackItem & { priceMinor: number })[];
  const tiers = [
    { key: "economic", title: "اقتصادی", mult: 0.75, count: 4 },
    { key: "balanced", title: "متعادل", mult: 1, count: 6, recommended: true },
    { key: "premium", title: "ویژه", mult: 1.35, count: 8 },
  ];
  return tiers.map((t) => {
    const items = eligible.length >= 2 ? pickItems(eligible, budgetToman * t.mult, t.count) : [];
    const totalToman = items.reduce((s, i) => s + toToman(i.priceMinor as number), 0);
    return { key: t.key, title: t.title, items, totalToman, recommended: t.recommended, insufficient: items.length < 2 };
  });
}

// ── Thumb ────────────────────────────────────────────────────────────────────
function Thumb({ item, size = "sm" }: { item: PackItem; size?: "sm" | "xs" }) {
  const dim = size === "sm" ? "w-full h-full" : "w-9 h-9";
  if (item.imageUrl) {
    // eslint-disable-next-line @next/next/no-img-element
    return <div className={`${dim} bg-white flex items-center justify-center overflow-hidden`}><img src={item.imageUrl} alt={item.name} className="w-full h-full object-contain p-1.5" /></div>;
  }
  const Icon = iconFor(item.groupSlug);
  return <div className={`${dim} bg-brand-blueLight flex items-center justify-center`}><Icon className={size === "sm" ? "w-6 h-6" : "w-4 h-4"} strokeWidth={1.6} color="#1677FF" /></div>;
}

// ── Suggestion card ──────────────────────────────────────────────────────────
function SuggestionCard({ pack, active, onAdopt, onEdit, onSwap }: {
  pack: SuggestedPack; active: boolean; onAdopt: () => void; onEdit: () => void; onSwap: () => void;
}) {
  if (pack.insufficient) {
    return (
      <div className="relative flex flex-col justify-center rounded-lg border border-neutral-200 bg-white p-3 min-h-[72px] h-full">
        {pack.recommended && <span className="absolute -top-2 right-3 px-1.5 py-0.5 rounded-full bg-brand-blue text-white text-[10px] font-bold">پیشنهاد محبوب</span>}
        <p className="text-sm font-bold text-neutral-900">{pack.title}</p>
        <p className="text-2xs text-neutral-400 mt-1 leading-5">کالای دارای قیمت رسمی کافی برای این بودجه یافت نشد</p>
      </div>
    );
  }
  return (
    <div className={`relative flex flex-col rounded-xl border-2 p-3 h-[280px] transition-colors ${active ? "border-brand-blue bg-brand-blueLight" : "border-neutral-200 bg-white"}`}>
      {pack.recommended && <span className="absolute -top-2 right-3 px-1.5 py-0.5 rounded-full bg-brand-blue text-white text-[10px] font-bold">پیشنهاد محبوب</span>}
      <div className="grid grid-cols-3 gap-1.5 h-14 mb-2">
        {pack.items.slice(0, 3).map((it) => <div key={it.id} className="rounded-lg overflow-hidden bg-brand-gray"><Thumb item={it} /></div>)}
      </div>
      <p className="text-sm font-bold text-neutral-900">{pack.title}</p>
      <p className="text-2xs text-neutral-500 mt-0.5">{toPersianNum(pack.items.length)} قلم کالا</p>
      <div className="flex-1" />
      <p className="text-sm font-black text-neutral-900 tabular-nums mb-2">{formatTomanExact(pack.totalToman)}</p>
      <button onClick={onAdopt} className={`w-full inline-flex items-center justify-center gap-1.5 h-8 rounded-lg text-2xs font-semibold mb-1 transition-colors ${active ? "bg-brand-blue text-white" : "bg-brand-gray text-neutral-700 hover:bg-brand-blueLight"}`}>
        {active && <Check className="w-3.5 h-3.5" />}انتخاب این پیشنهاد
      </button>
      <div className="grid grid-cols-2 gap-1.5">
        <button onClick={onEdit} className="inline-flex items-center justify-center gap-1 h-7 rounded-lg text-[10px] font-semibold border border-neutral-200 text-neutral-600 hover:border-brand-blue hover:text-brand-blue transition-colors">ویرایش محتویات</button>
        <button onClick={onSwap} className="inline-flex items-center justify-center gap-1 h-7 rounded-lg text-[10px] font-semibold border border-neutral-200 text-neutral-600 hover:border-brand-blue hover:text-brand-blue transition-colors"><RefreshCw className="w-3 h-3" />تعویض کالا</button>
      </div>
    </div>
  );
}

// ── Customizer ───────────────────────────────────────────────────────────────
type WorkingLine = { itemId: number; qty: number };

function Customizer({
  pool, catList, workingPack, setWorkingPack, replaceTargetId, setReplaceTargetId, maxBudget, setMaxBudget, itemById,
}: {
  pool: PackItem[];
  catList: { slug: string; name: string }[];
  workingPack: WorkingLine[];
  setWorkingPack: React.Dispatch<React.SetStateAction<WorkingLine[]>>;
  replaceTargetId: number | null;
  setReplaceTargetId: (id: number | null) => void;
  maxBudget: number | "";
  setMaxBudget: (v: number | "") => void;
  itemById: Map<number, PackItem>;
}) {
  const { token } = useAuth();
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [browse, setBrowse] = useState<PackItem[]>(pool.slice(0, 48));
  const [cartResult, setCartResult] = useState<string | null>(null);
  const [proformaState, setProformaState] = useState<"idle" | "sending" | "done" | "err">("idle");
  const [proformaMsg, setProformaMsg] = useState<string>("");

  const runBrowse = useCallback(async (q: string, cat: string) => {
    try {
      const r = await catalog.list({ q: q.trim() || undefined, category: cat === "all" ? undefined : cat, page_size: 48 });
      setBrowse(r.items.map(fromProduct));
    } catch { /* keep prior */ }
  }, []);
  useEffect(() => { const t = setTimeout(() => runBrowse(search, categoryFilter), 250); return () => clearTimeout(t); }, [search, categoryFilter, runBrowse]);

  function addItem(id: number) {
    if (replaceTargetId != null) {
      setWorkingPack((p) => p.map((x) => (x.itemId === replaceTargetId ? { itemId: id, qty: x.qty } : x)));
      setReplaceTargetId(null);
      return;
    }
    setWorkingPack((p) => {
      const e = p.find((x) => x.itemId === id);
      return e ? p.map((x) => (x.itemId === id ? { ...x, qty: x.qty + 1 } : x)) : [...p, { itemId: id, qty: 1 }];
    });
  }
  const removeItem = (id: number) => { setWorkingPack((p) => p.filter((x) => x.itemId !== id)); if (replaceTargetId === id) setReplaceTargetId(null); };
  const setQty = (id: number, qty: number) => setWorkingPack((p) => p.map((x) => (x.itemId === id ? { ...x, qty: Math.max(1, qty) } : x)));

  const lines = workingPack.map((w) => ({ ...w, item: itemById.get(w.itemId) })).filter((l): l is WorkingLine & { item: PackItem } => !!l.item);
  const pricedLines = lines.filter((l) => priced(l.item));
  const unpricedCount = lines.length - pricedLines.length;
  const runningTotal = pricedLines.reduce((s, l) => s + toToman(l.item.priceMinor as number) * l.qty, 0);
  const budgetNum = typeof maxBudget === "number" ? maxBudget : null;
  const remaining = budgetNum != null ? budgetNum - runningTotal : null;
  const over = remaining != null && remaining < 0;

  async function addPackToCart() {
    if (!token) { setCartResult("برای افزودن پک به سبد ابتدا وارد شوید."); return; }
    let ok = 0; const fail: string[] = []; const skipUnpriced = unpricedCount;
    for (const l of pricedLines) {
      try { await cartApi.add(token, l.item.id, l.qty); ok++; }
      catch (e) { fail.push(`${l.item.name}: ${e instanceof Error ? e.message : "افزوده نشد"}`); }
    }
    setCartResult(
      `${toPersianNum(ok)} قلم به سبد افزوده شد` +
      (fail.length ? ` — ${toPersianNum(fail.length)} قلم افزوده نشد (${fail[0]})` : "") +
      (skipUnpriced ? ` — ${toPersianNum(skipUnpriced)} قلم بدون قیمت رسمی، از طریق «استعلام قیمت» پیگیری کنید` : ""),
    );
  }

  async function requestProforma() {
    if (!token) { setProformaState("err"); setProformaMsg("برای درخواست پیش‌فاکتور ابتدا وارد شوید."); return; }
    if (!lines.length) return;
    setProformaState("sending");
    try {
      await apiRequest("/requests", {
        method: "POST", token,
        headers: { "Idempotency-Key": newIdempotencyKey() },
        body: JSON.stringify({
          kind: "procurement",
          subject: "درخواست پیش‌فاکتور پک سفارشی (پک‌ساز ۶۰)",
          message: "درخواست پیش‌فاکتور برای اقلام پک ساخته‌شده در پک‌ساز.",
          items: lines.map((l) => ({ slug: l.item.slug, quantity: l.qty })),
        }),
      });
      setProformaState("done"); setProformaMsg("درخواست پیش‌فاکتور ثبت شد؛ در «درخواست‌های من» قابل پیگیری است.");
    } catch (e) {
      setProformaState("err"); setProformaMsg(e instanceof Error ? e.message : "ثبت درخواست ناموفق بود.");
    }
  }

  const cats = ["all", ...catList.map((c) => c.slug)];
  const catName = (s: string) => (s === "all" ? "همه دسته‌ها" : catList.find((c) => c.slug === s)?.name ?? s);

  return (
    <div className="mt-4 rounded-xl border border-neutral-200 bg-brand-gray/40 p-3 md:p-4">
      <div className="grid lg:grid-cols-[1fr_320px] gap-4">
        {/* Browse */}
        <div>
          <div className="relative mb-3">
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="جستجوی کالا..."
              className="w-full h-10 pr-4 pl-10 rounded-lg border border-neutral-200 bg-white text-sm placeholder:text-neutral-400 focus:outline-none focus:border-brand-blue" />
            <Search className="w-4 h-4 absolute top-1/2 -translate-y-1/2 left-3 text-neutral-400" />
          </div>
          <div className="flex flex-wrap gap-1.5 mb-4">
            {cats.map((c) => (
              <button key={c} onClick={() => setCategoryFilter(c)}
                className={`px-3 h-8 rounded-lg text-2xs font-semibold border transition-colors ${categoryFilter === c ? "bg-brand-blue text-white border-brand-blue" : "bg-white text-neutral-600 border-neutral-200 hover:border-neutral-300"}`}>
                {catName(c)}
              </button>
            ))}
          </div>
          {replaceTargetId != null && (
            <div className="flex items-center justify-between mb-3 px-3 py-2 rounded-lg bg-brand-blueLight text-brand-blue text-xs font-semibold">
              <span>یک کالا برای جایگزینی انتخاب کنید</span>
              <button onClick={() => setReplaceTargetId(null)} className="underline">انصراف</button>
            </div>
          )}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-[300px] overflow-y-auto pr-1">
            {browse.map((item) => (
              <button key={item.id} onClick={() => addItem(item.id)}
                className="text-right rounded-xl border border-neutral-200 bg-white p-2.5 hover:border-brand-blue transition-colors flex flex-col">
                <div className="rounded-lg overflow-hidden h-16 mb-2"><Thumb item={item} /></div>
                <p className="text-2xs font-semibold text-neutral-800 line-clamp-2 h-8">{item.name}</p>
                <p className="text-2xs text-neutral-400 mt-0.5">{catName(item.groupSlug)}</p>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-2xs font-bold text-neutral-900 tabular-nums">
                    {priced(item) ? formatTomanExact(toToman(item.priceMinor)) : <span className="text-amber-600 font-semibold">استعلام قیمت</span>}
                  </span>
                  <span className="w-6 h-6 rounded-md bg-brand-blueLight text-brand-blue flex items-center justify-center"><Plus className="w-3.5 h-3.5" /></span>
                </div>
              </button>
            ))}
            {browse.length === 0 && <p className="col-span-full text-center text-xs text-neutral-400 py-8">کالایی با این مشخصات یافت نشد</p>}
          </div>
        </div>

        {/* Pack composition */}
        <div className="rounded-xl bg-white border border-neutral-200 p-4 flex flex-col">
          <p className="text-sm font-bold text-neutral-900 mb-3">ترکیب پک شما</p>
          <div className="flex-1 overflow-y-auto max-h-[200px] -mx-1 px-1 space-y-2 mb-3">
            {lines.length === 0 && <p className="text-2xs text-neutral-400 text-center py-6">هنوز کالایی به پک اضافه نکرده‌اید</p>}
            {lines.map((l) => (
              <div key={l.itemId} className="flex items-center gap-2 rounded-lg border border-neutral-100 p-2">
                <div className="w-9 h-9 rounded-md overflow-hidden flex-shrink-0"><Thumb item={l.item} size="xs" /></div>
                <div className="min-w-0 flex-1">
                  <p className="text-2xs font-semibold text-neutral-800 line-clamp-1">{l.item.name}</p>
                  <p className="text-2xs tabular-nums">{priced(l.item) ? <span className="text-neutral-400">{formatTomanExact(toToman(l.item.priceMinor))}</span> : <span className="text-amber-600">استعلام قیمت</span>}</p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button onClick={() => setQty(l.itemId, l.qty - 1)} className="w-6 h-6 rounded-md border border-neutral-200 flex items-center justify-center text-neutral-500 hover:border-brand-blue"><Minus className="w-3 h-3" /></button>
                  <span className="text-2xs font-bold w-4 text-center tabular-nums">{toPersianNum(l.qty)}</span>
                  <button onClick={() => setQty(l.itemId, l.qty + 1)} className="w-6 h-6 rounded-md border border-neutral-200 flex items-center justify-center text-neutral-500 hover:border-brand-blue"><Plus className="w-3 h-3" /></button>
                </div>
                <button onClick={() => setReplaceTargetId(l.itemId)} title="تعویض کالا" className="w-6 h-6 rounded-md flex items-center justify-center text-neutral-400 hover:text-brand-blue flex-shrink-0"><RefreshCw className="w-3.5 h-3.5" /></button>
                <button onClick={() => removeItem(l.itemId)} title="حذف" className="w-6 h-6 rounded-md flex items-center justify-center text-neutral-400 hover:text-brand-coral flex-shrink-0"><X className="w-3.5 h-3.5" /></button>
              </div>
            ))}
          </div>
          <div className="border-t border-neutral-100 pt-3 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-neutral-500">جمع کل (اقلام دارای قیمت رسمی)</span>
              <span className="font-bold text-neutral-900 tabular-nums">{formatTomanExact(runningTotal)}</span>
            </div>
            {unpricedCount > 0 && <div className="flex items-center justify-between text-xs text-amber-600"><span>اقلام بدون قیمت رسمی</span><span className="font-bold">{toPersianNum(unpricedCount)} قلم — استعلامی</span></div>}
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="text-neutral-500 flex-shrink-0">سقف بودجه</span>
              <input type="number" value={maxBudget} onChange={(e) => setMaxBudget(e.target.value === "" ? "" : Number(e.target.value))} placeholder="تومان"
                className="w-28 h-8 px-2 rounded-md border border-neutral-200 text-left text-xs tabular-nums focus:outline-none focus:border-brand-blue" />
            </div>
            {remaining != null && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-neutral-500">{over ? "مازاد بر بودجه" : "باقی‌مانده بودجه"}</span>
                <span className={`font-bold tabular-nums ${over ? "text-brand-coral" : "text-brand-blue"}`}>{formatTomanExact(Math.abs(remaining))}</span>
              </div>
            )}
          </div>
          <div className="grid grid-cols-1 gap-2 mt-4">
            <button disabled title="این قابلیت هنوز فعال نیست" className="h-9 rounded-lg text-xs font-semibold border border-neutral-200 text-neutral-400 flex items-center justify-center gap-1.5 cursor-not-allowed">
              ذخیره پک سفارشی <span className="text-2xs">(به‌زودی)</span>
            </button>
            <button onClick={addPackToCart} disabled={pricedLines.length === 0}
              className="h-10 rounded-lg text-sm font-semibold bg-brand-blue text-white hover:bg-brand-blueDark disabled:opacity-40 flex items-center justify-center gap-1.5">
              <ShoppingCart className="w-4 h-4" /> افزودن پک به سبد خرید
            </button>
            <button onClick={requestProforma} disabled={lines.length === 0 || proformaState === "sending"}
              className="h-9 rounded-lg text-2xs font-semibold text-neutral-500 hover:text-brand-blue disabled:opacity-40 flex items-center justify-center gap-1.5">
              <FileText className="w-3.5 h-3.5" />
              {proformaState === "done" ? "درخواست پیش‌فاکتور ثبت شد" : proformaState === "sending" ? "در حال ارسال…" : "درخواست پیش‌فاکتور سازمانی برای تعداد بالا"}
            </button>
          </div>
          {cartResult && <p className="mt-2 text-2xs text-neutral-600">{cartResult} {" "}<Link href="/cart" className="text-brand-blue underline">سبد خرید</Link></p>}
          {proformaMsg && <p className={`mt-2 text-2xs ${proformaState === "err" ? "text-brand-coral" : "text-brand-blue"}`}>{proformaMsg}</p>}
        </div>
      </div>
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────
export function PackBuilderInteractive() {
  const [step, setStep] = useState<"budget" | "occasion" | "result">("budget");
  const [budgetIdx, setBudgetIdx] = useState(1);
  const [purposeKey, setPurposeKey] = useState<PurposeKey>("family");
  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [workingPack, setWorkingPack] = useState<WorkingLine[]>([]);
  const [activeSuggestionKey, setActiveSuggestionKey] = useState<string | null>(null);
  const [maxBudget, setMaxBudget] = useState<number | "">(BUDGET_TIERS[1].ceilingToman);
  const [replaceTargetId, setReplaceTargetId] = useState<number | null>(null);

  const [pool, setPool] = useState<PackItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [catList, setCatList] = useState<{ slug: string; name: string }[]>([]);

  useEffect(() => { categoriesApi.list().then((c) => setCatList(c.map((x) => ({ slug: x.slug, name: x.name })))).catch(() => {}); }, []);

  // Receive a structured selection from the Shopping Assistant (sessionStorage handoff).
  useEffect(() => {
    let raw: string | null = null;
    try { raw = sessionStorage.getItem("60o_pack_draft"); sessionStorage.removeItem("60o_pack_draft"); } catch { /* ignore */ }
    if (!raw) return;
    try {
      const d = JSON.parse(raw) as { items: { slug: string; title: string; priceMinor: number | null; quantity: number; categoryName?: string; imageUrl?: string | null }[]; perPersonToman?: number | null };
      if (!Array.isArray(d.items) || !d.items.length) return;
      const injected: PackItem[] = d.items.map((it, i) => ({
        id: 9_000_000 + i, slug: it.slug, name: it.title,
        priceMinor: typeof it.priceMinor === "number" && it.priceMinor > 0 ? it.priceMinor : null,
        groupSlug: "other", imageUrl: it.imageUrl || undefined, inStock: true,
      }));
      setPool((prev) => [...injected, ...prev.filter((p) => p.id < 9_000_000)]);
      setWorkingPack(d.items.map((it, i) => ({ itemId: 9_000_000 + i, qty: Math.max(1, Math.round(it.quantity || 1)) })));
      setPurposeKey("custom");
      setCustomizerOpen(true);
      setStep("result");
    } catch { /* ignore */ }
  }, []);

  const loadPool = useCallback(async (pk: PurposeKey) => {
    const purpose = PURPOSES.find((p) => p.key === pk)!;
    const slugs = purpose.groups.length ? purpose.groups : ["nuts-local", "supermarket", "digital", "appliances"];
    setLoading(true);
    try {
      const lists = await Promise.all(slugs.map((s) => catalog.list({ category: s, page_size: 24 })));
      const seen = new Set<number>();
      const items: PackItem[] = [];
      for (const l of lists) for (const p of l.items) if (!seen.has(p.id)) { seen.add(p.id); items.push(fromProduct(p)); }
      setPool((prev) => { const inj = prev.filter((x) => x.id >= 9_000_000); const ex = new Set(inj.map((x) => x.id)); return [...inj, ...items.filter((x) => !ex.has(x.id))]; });
    } catch { setPool([]); } finally { setLoading(false); }
  }, []);
  useEffect(() => { loadPool(purposeKey); }, [purposeKey, loadPool]);

  const itemById = useMemo(() => {
    const m = new Map<number, PackItem>();
    for (const i of pool) m.set(i.id, i);
    return m;
  }, [pool]);
  const excludeIds = useMemo(() => new Set(workingPack.map((w) => w.itemId)), [workingPack]);
  const suggestions = useMemo(() => buildSuggestions(pool, BUDGET_TIERS[budgetIdx].ceilingToman, excludeIds), [pool, budgetIdx, excludeIds]);

  function adopt(pack: SuggestedPack, openPanel: boolean, focusReplace = false) {
    if (pack.insufficient) return;
    setWorkingPack(pack.items.map((i) => ({ itemId: i.id, qty: 1 })));
    setActiveSuggestionKey(pack.key);
    setMaxBudget(Math.round(pack.totalToman * 1.1));
    setCustomizerOpen(openPanel);
    setReplaceTargetId(focusReplace && pack.items[0] ? pack.items[0].id : null);
    setStep("result");
  }
  function openBlank() { setPurposeKey("custom"); setCustomizerOpen(true); setReplaceTargetId(null); }

  const steps: { key: typeof step; label: string }[] = [
    { key: "budget", label: "بودجه" }, { key: "occasion", label: "مناسبتی" }, { key: "result", label: "نتیجه" },
  ];
  const anyPriced = pool.some(priced);

  return (
    <section className="py-7 md:py-9 bg-brand-gray/60" id="pack-builder">
      <div className="container-page">
        <div className="card p-4 md:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-xl md:text-2xl font-black text-neutral-900">پک‌ساز هوشمند ۶۰</h2>
              <p className="text-sm text-neutral-500 mt-1">بودجه و مناسبت خود را انتخاب کنید یا از صفر یک پک ترکیبی از هر دسته‌ای بسازید</p>
            </div>
            <div className="flex items-center rounded-xl bg-brand-gray p-1">
              {steps.map((s) => (
                <button key={s.key} onClick={() => setStep(s.key)}
                  className={`px-4 h-9 rounded-lg text-sm font-semibold transition-colors ${step === s.key ? "bg-white text-brand-blue shadow-sm" : "text-neutral-500"}`}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid lg:grid-cols-[minmax(0,260px)_1fr] gap-x-6 gap-y-4">
            {/* Controls */}
            <div>
              <p className="text-xs font-semibold text-neutral-700 mb-2">بودجه شما</p>
              <div className="flex flex-wrap gap-2 mb-4">
                {BUDGET_TIERS.map((b, i) => (
                  <button key={b.label} onClick={() => { setBudgetIdx(i); setStep("occasion"); }}
                    className={`px-3.5 h-9 rounded-lg text-sm font-semibold border transition-colors ${budgetIdx === i ? "bg-brand-blue text-white border-brand-blue" : "bg-white text-neutral-600 border-neutral-200 hover:border-neutral-300"}`}>
                    {b.label} تومان
                  </button>
                ))}
              </div>
              <p className="text-xs font-semibold text-neutral-700 mb-2">مناسبت</p>
              <div className="flex flex-wrap gap-2">
                {PURPOSES.map((p) => (
                  <button key={p.key} onClick={() => { setPurposeKey(p.key); if (p.key === "custom") openBlank(); else setStep("result"); }}
                    className={`px-3.5 h-9 rounded-lg text-sm font-medium border transition-colors ${purposeKey === p.key ? "bg-brand-blueLight text-brand-blue border-brand-blue" : "bg-white text-neutral-600 border-neutral-200 hover:border-neutral-300"}`}>
                    {p.label}
                  </button>
                ))}
              </div>
              <button onClick={openBlank}
                className="w-full mt-4 inline-flex items-center justify-center gap-2 h-9 rounded-xl border-2 border-dashed border-neutral-300 text-neutral-500 text-sm font-semibold hover:border-brand-blue hover:text-brand-blue transition-colors">
                <PackagePlus className="w-4 h-4" /> ساخت پک سفارشی از صفر
              </button>
            </div>

            {/* Result */}
            <div>
              <p className="text-xs font-semibold text-neutral-700 mb-2.5">پیشنهادهای آماده برای شما</p>
              {loading ? (
                <div className="flex gap-3 mb-4 overflow-x-auto -mx-1 px-1 sm:grid sm:grid-cols-3 sm:overflow-visible sm:mx-0 sm:px-0">{[0, 1, 2].map((i) => <div key={i} className="w-[70%] shrink-0 sm:w-auto sm:shrink rounded-xl border border-neutral-200 h-[120px] animate-pulse bg-neutral-100" />)}</div>
              ) : (
                <div className="flex gap-3 mb-3 overflow-x-auto -mx-1 px-1 snap-x sm:grid sm:grid-cols-3 sm:gap-2 sm:overflow-visible sm:mx-0 sm:px-0 items-start">
                  {suggestions.map((pack) => (
                    <div key={pack.key} className="w-[72%] shrink-0 snap-start sm:w-auto sm:shrink">
                      <SuggestionCard pack={pack} active={activeSuggestionKey === pack.key}
                        onAdopt={() => adopt(pack, false)} onEdit={() => adopt(pack, true)} onSwap={() => adopt(pack, true, true)} />
                    </div>
                  ))}
                </div>
              )}

              {!loading && !anyPriced && (
                <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-2xs leading-5 text-amber-900">
                  <b>در حال حاضر برای این دسته‌ها قیمت رسمی ثبت نشده است.</b> پک پیشنهادی با قیمت واقعی ساخته نمی‌شود؛ اما می‌توانید از «ساخت پک سفارشی از صفر» کالاها را انتخاب کنید و برای آن‌ها «درخواست پیش‌فاکتور» ثبت کنید. هیچ قیمت یا موجودی ساختگی نمایش داده نمی‌شود.
                </div>
              )}

              {customizerOpen && (
                <Customizer pool={pool} catList={catList} workingPack={workingPack} setWorkingPack={setWorkingPack}
                  replaceTargetId={replaceTargetId} setReplaceTargetId={setReplaceTargetId}
                  maxBudget={maxBudget} setMaxBudget={setMaxBudget} itemById={itemById} />
              )}
              {!customizerOpen && (
                <button onClick={() => setCustomizerOpen(true)} disabled={workingPack.length === 0}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 h-10 rounded-xl bg-brand-blue text-white font-semibold text-sm hover:bg-brand-blueDark disabled:opacity-40 transition-colors">
                  <Sparkles className="w-4 h-4" /> ویرایش و افزودن پک به سبد خرید
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
