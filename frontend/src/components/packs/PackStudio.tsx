"use client";
import { scopedDraftKey, pendingDraftKey } from "@/lib/client-draft-storage";
import { useAuth } from "@/lib/auth-context";
// The single Pack Builder (/pack-builder). Redesigned 2026-11-17 to the approved Google Stitch look
// (screens 62 desktop / 63 mobile, content of 55, customize popup 60): mint hero with 60AI input, 4-step
// stepper, three build methods, occasion filters, uniform pack cards, sticky summary, collapsed
// procurement/logistics sections. All data comes from the real storefront APIs; the editor/review/quote
// step is still the existing PackBuilderInteractive (protected, unchanged).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Scale, Package, WalletCards, SlidersHorizontal, ArrowLeft, RefreshCw } from "lucide-react";
import { PackBuilderInteractive, type PackDraft } from "@/components/home/PackBuilderInteractive";
import { BudgetBuilder, type BudgetPreset } from "./BudgetBuilder";
import { loadPackDetails } from "./PackCard";
import { PackGridCard } from "./PackGridCard";
import { PackCustomizeDialog } from "./PackCustomizeDialog";
import { PackSummaryPanel, PackSummaryBar } from "./PackSummaryPanel";
import { ProcurementServices } from "./ProcurementServices";
import { StudioHero } from "./StudioHero";
import type { PackIntent } from "./pack-intent";
import { btnPrimary, btnSecondary, card, sectionSub, sectionTitle } from "./studio-ui";
import { useGoodImages } from "@/lib/imageQuality";
import { storefront, type PackDetail } from "@/lib/storefront";
import { toPersianNum } from "@/lib/utils";

type Method = "template" | "budget" | "scratch";
const STEPS: [string, string][] = [["انتخاب روش", "پک آماده، بودجه یا دستی"], ["ساخت پک", "تغییر اقلام و تعداد"], ["بررسی", "قیمت، موجودی و تعداد"], ["خرید / استعلام", "سبد خرید یا پیش‌فاکتور"]];

const text = (p: PackDetail) => `${p.title_fa} ${p.purpose_fa} ${p.occasion ?? ""} ${p.kind_fa}`;
const has = (re: RegExp) => (p: PackDetail) => re.test(text(p));
// Occasion filters (Stitch 55/62). Matching is on real pack fields only; an empty group shows an honest empty state.
const GROUPS: [string, string, (p: PackDetail) => boolean][] = [
  ["", "همه پک‌ها", () => true],
  ["livelihood", "معیشتی و ارزاق", (p) => p.kind === "livelihood" || (p.audience === "household" && p.kind !== "occasion")],
  ["occasion", "مناسبت‌ها و نذورات", (p) => p.kind === "occasion" || !!p.occasion || has(/نذر|محرم|افطار/)(p)],
  ["cultural", "فرهنگی و مدارس", has(/فرهنگ|کتاب|مدرس|تحصیل|نوشت.?افزار|تحریر/)],
  ["premium", "هدایای فاخر", (p) => ["premium", "executive"].includes(p.tier ?? "")],
  ["work", "سازمانی و کارکنان", (p) => ["organization", "office", "employee_gift"].includes(p.audience)],
  ["hotel", "هتل و پذیرایی", has(/هتل|پذیرایی|مهمانسرا/)],
  ["charity", "خیریه", has(/خیریه|نیازمند|مستمند|مهربانی/)],
];
// Older links used these group keys.
const GROUP_ALIASES: Record<string, string> = { home: "livelihood", gift: "work" };
const METHODS = [
  ["template", "پک‌های آماده", Package, "ترکیب‌های منتشرشده را انتخاب و شخصی‌سازی کنید", "مشاهده پک‌ها"],
  ["budget", "بر اساس بودجه", WalletCards, "سقف هزینه هر پک و تعداد پک‌ها را مشخص کنید", "شروع برآورد"],
  ["scratch", "انتخاب دستی", SlidersHorizontal, "اقلام دلخواه را از کاتالوگ واقعی کنار هم بچینید", "ورود به کاتالوگ"],
] as const;

export function Steps({ active }: { active: number }) {
  return <ol aria-label="مراحل ساخت پک" className={`${card} grid grid-cols-4 gap-1 p-2 md:gap-2 md:p-3`}>
    {STEPS.map(([label, hint], i) => {
      const on = i === active, done = i < active;
      return <li key={label} aria-current={on ? "step" : undefined} className={`flex min-h-12 flex-col items-center gap-1 rounded-lg px-1 py-2 text-center md:flex-row md:gap-3 md:px-3 md:text-right ${on ? "bg-[#F3F6FA]" : ""}`}>
        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${on ? "bg-[#112D46] text-white" : done ? "bg-[#EDF3EE] text-[#112D46]" : "border border-[#E5E7EB] text-[#6B7280]"}`}>{toPersianNum(i + 1)}</span>
        <span className="min-w-0"><b className={`block text-[11px] md:text-sm ${on ? "font-extrabold text-[#112D46]" : "font-medium text-[#374151]"}`}>{label}</b><span className="hidden text-[11px] text-[#6B7280] md:block">{hint}</span></span>
      </li>;
    })}
  </ol>;
}

export function PackStudio(){const{user}=useAuth();return <PackStudioBody key={user?.id??"guest"}/>;}
function PackStudioBody() {
  const [method, setMethod] = useState<Method>("template"), [draft, setDraft] = useState<PackDraft | null>(null);
  const [saved, setSaved] = useState<PackDraft | null>(null), [pending, setPending] = useState<PackDraft | null>(null);
  const [packs, setPacks] = useState<PackDetail[] | null>(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0), [step, setStep] = useState(1), [group, setGroup] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [selected, setSelected] = useState<PackDetail | null>(null), [count, setCount] = useState("1");
  const [customizing, setCustomizing] = useState<PackDetail | null>(null);
  const [preset, setPreset] = useState<BudgetPreset | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const readDraft = (raw: string | null): PackDraft | null => { try { const d = JSON.parse(raw ?? "null"); return d && Array.isArray(d.items) && d.items.every((i: { slug?: string; quantity?: number }) => typeof i.slug === "string" && Number.isInteger(i.quantity) && Number(i.quantity) > 0) ? {items: d.items, count: Number.isInteger(d.count) && d.count > 0 && d.count <= 100000 ? d.count : 1} : null; } catch { return null; } };
  const fromPack = (p: PackDetail, n?: number): PackDraft => ({ count: n ?? Math.max(1, p.min_order_qty), items: p.items.filter(i => i.slug).map(i => ({ slug: i.slug!, title: i.title_fa, quantity: i.quantity, imageUrl: i.image_url, priceMinor: null })) });
  useEffect(() => {
    // Query is read on mount (not via useSearchParams) so the page shell is server-rendered instead of
    // bailing out to client-only rendering.
    const params = new URLSearchParams(window.location.search);
    const g = params.get("group"), key = g ? GROUP_ALIASES[g] ?? g : ""; if (GROUPS.some(([k]) => k === key)) setGroup(key);
    let stored: PackDraft | null = null, handoff: PackDraft | null = null;
    try { stored = readDraft(localStorage.getItem(scopedDraftKey("60o_pack_builder_draft"))); handoff = readDraft(sessionStorage.getItem(scopedDraftKey("60o_pack_draft"))); sessionStorage.removeItem(scopedDraftKey("60o_pack_draft")); } catch { /* unavailable storage */ }
    try { handoff ??= readDraft(localStorage.getItem(pendingDraftKey("60o_pack_builder_draft"))); } catch { /* unavailable storage */ }
    const packSlug = params.get("pack");
    if (packSlug) {
      // "شخصی‌سازی این پک" from a ready-pack page: open that pack's real items in the editor.
      if (stored?.items.length) setSaved(stored);
      storefront.pack(packSlug).then(r => { const next = fromPack(r.pack); if (!next.items.length) return; if (stored?.items.length) { setDraft(stored); setPending(next); } else setDraft(next); })
        .catch(() => setError("دریافت این پک ناموفق بود؛ از فهرست پک‌ها انتخاب کنید."));
      return;
    }
    // A saved draft is offered ("ادامه پک ذخیره‌شده"), not forced open, so the redesigned landing stays visible.
    if (stored?.items.length) { setSaved(stored); if (handoff) setPending(handoff); }
    else if (handoff) setDraft(handoff);
    else if (params.get("mode") === "scratch") { setMethod("scratch"); setDraft({items: [], count: 1}); }
    else if (params.get("mode") === "budget") setMethod("budget");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { let active = true; loadPackDetails().then(p => { if (active) setPacks(p.filter(x => x.items.length)); }).catch(() => { if (active) setError("دریافت پک‌های آماده ناموفق بود. دوباره تلاش کنید."); }); return () => { active = false; }; }, [revision]);
  const top = () => { if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" }); };
  const open = (next: PackDraft) => { if (saved?.items.length) setPending(next); else { setDraft(next); setRevision(x => x+1); } top(); };
  const back = () => { try { setSaved(readDraft(localStorage.getItem(scopedDraftKey("60o_pack_builder_draft")))); } catch { /* unavailable */ } setDraft(null); setMethod("template"); };
  const filter = GROUPS.find(g => g[0] === group) ?? GROUPS[0];
  const counts = useMemo(() => Object.fromEntries(GROUPS.map(([k, , f]) => [k, packs?.filter(f).length ?? 0])), [packs]);
  const shown = useMemo(() => packs?.filter(filter[2]) ?? null, [packs, filter]);
  const good = useGoodImages((shown ?? []).flatMap(p => p.items.map(i => i.image_url)));
  const toggle = (slug: string) => setPicked(x => x.includes(slug) ? x.filter(s => s !== slug) : x.length >= 4 ? x : [...x, slug]);
  const select = (p: PackDetail) => { if (selected?.slug === p.slug) { setSelected(null); return; } setSelected(p); setCount(String(Math.max(1, p.min_order_qty))); };
  const continueSelected = () => { const n = Number(count); if (selected && Number.isInteger(n) && n > 0) open(fromPack(selected, n)); };
  const chooseMethod = (key: Method) => { setMethod(key); if (key === "scratch") open({items: [], count: 1}); else contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const onIntent = useCallback((intent: PackIntent) => {
    setMethod("budget");
    setPreset({ nonce: Date.now(), ...intent });
    setTimeout(() => contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }, []);
  const used = new Set<string>();

  if (draft) {
    const reviewing = step >= 2;
    return <div className="space-y-6" dir="rtl">
      <Steps active={step} />
      <header className={`${card} flex flex-col gap-1 p-5 md:p-6`}>
        <h1 id="pack-studio-title" tabIndex={-1} className="text-xl font-extrabold text-[#112D46] outline-none md:text-2xl">{reviewing ? "بررسی نهایی پک" : "پک دلخواه شما"}</h1>
        <p className="line-clamp-1 text-sm text-[#6B7280]">{reviewing ? "اقلام، تعداد و مبلغ را بررسی کنید؛ برای اقلام فاقد قیمت درخواست استعلام ثبت می‌شود." : "حذف، افزودن و تغییر تعداد اقلام؛ همه در همین پک."}</p>
      </header>
      {pending && <PendingAlert pending={pending} onReplace={() => { setDraft(pending); setSaved(null); setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } setRevision(x => x+1); }} onKeep={() => { setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } }} />}
      <PackBuilderInteractive key={revision} draft={draft} onBack={back} onStep={setStep} />
    </div>;
  }

  return <div className="space-y-8 pb-24 lg:pb-0" dir="rtl">
    <div className="flex flex-col gap-4">
      <div className="order-2 lg:order-1"><Steps active={0} /></div>
      <div className="order-1 lg:order-2"><StudioHero onIntent={onIntent} /></div>
    </div>
    {pending && <PendingAlert pending={pending} onReplace={() => { setDraft(pending); setSaved(null); setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } setRevision(x => x+1); }} onKeep={() => { setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } if (saved?.items.length) setDraft(saved); }} />}

    <section aria-labelledby="methods-title">
      <h2 id="methods-title" className={sectionTitle}>روش ساخت پک</h2>
      <p className={sectionSub}>از پک آماده شروع کنید، با بودجه پیشنهاد بگیرید یا اقلام را خودتان بچینید.</p>
      <div className="mt-4 grid grid-cols-3 gap-2 md:gap-5" role="tablist" aria-label="روش ساخت پک">
        {METHODS.map(([key, label, Icon, description, cta], index) => {
          const on = method === key;
          return <button key={key} type="button" role="tab" aria-label={label} aria-selected={on} tabIndex={on ? 0 : -1}
            onKeyDown={e => { const move = e.key === "ArrowRight" ? -1 : e.key === "ArrowLeft" ? 1 : 0; if (move || e.key === "Home" || e.key === "End") { e.preventDefault(); const next = e.key === "Home" ? 0 : e.key === "End" ? 2 : (index + move + 3) % 3; const buttons = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button[role="tab"]'); buttons?.[next]?.focus(); buttons?.[next]?.click(); } }}
            onClick={() => chooseMethod(key)}
            className={`group flex min-h-24 flex-col items-start rounded-xl border bg-white p-3 text-right transition md:min-h-40 md:p-5 ${on ? "border-[#034EA2] shadow-[0_0_0_1px_#034EA2,0_8px_24px_rgba(3,78,162,0.08)]" : "border-[#E5E7EB] shadow-[0_1px_2px_rgba(17,24,39,0.04)] hover:border-[#C7D2E0]"}`}>
            <span className={`flex h-9 w-9 items-center justify-center rounded-lg md:h-11 md:w-11 ${on ? "bg-[#034EA2] text-white" : "bg-[#F3F6FA] text-[#034EA2]"}`}><Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden /></span>
            <b className="mt-2 text-xs font-extrabold text-[#112D46] md:mt-4 md:text-base">{label}</b>
            <span className="mt-1 hidden text-xs leading-6 text-[#6B7280] md:block">{description}</span>
            <span className="mt-auto hidden items-center gap-1 pt-3 text-xs font-bold text-[#034EA2] md:inline-flex">{cta} <ArrowLeft className="h-3.5 w-3.5" aria-hidden /></span>
          </button>;
        })}
      </div>
    </section>

    <div ref={contentRef} className="grid scroll-mt-40 grid-cols-1 items-start gap-8 lg:grid-cols-12">
      <div className="flex min-w-0 flex-col gap-8 lg:col-span-8">
        {method === "template" && <section aria-labelledby="packs-title" className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div><h2 id="packs-title" className={sectionTitle}>پک‌های آماده</h2><p className={sectionSub}>پک‌های منتشرشده از کالاهای واقعی کاتالوگ؛ برای استعلام انتخاب یا شخصی‌سازی کنید.</p></div>
            {saved?.items.length ? <button type="button" onClick={() => setDraft(saved)} className="min-h-9 text-xs font-bold text-[#034EA2] hover:underline lg:hidden">ادامه پک ذخیره‌شده ({toPersianNum(saved.items.length)} نوع کالا)</button> : null}
          </div>
          <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:flex-wrap md:px-0" role="group" aria-label="دسته‌بندی پک‌ها">
            {GROUPS.map(([k, l]) => { const on = group === k; return <button key={k || "all"} type="button" aria-pressed={on} onClick={() => setGroup(k)}
              className={`min-h-9 shrink-0 rounded-lg px-3.5 text-xs font-bold transition ${on ? "bg-[#034EA2] text-white" : "border border-[#E5E7EB] bg-white text-[#4B5563] hover:text-[#111827]"}`}>{l}{packs ? ` (${toPersianNum(counts[k] ?? 0)})` : ""}</button>; })}
          </div>
          {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-800">{error}<button type="button" className="inline-flex min-h-9 items-center gap-1 font-bold underline" onClick={() => {setError("");setRevision(x => x+1);}}><RefreshCw className="h-4 w-4" aria-hidden /> تلاش دوباره</button></div>}
          {shown === null ? !error && <div role="status" aria-label="در حال دریافت پک‌ها" className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map(i => <div key={i} className={`${card} h-[420px] animate-pulse`} />)}</div>
            : !shown.length ? <div className={`${card} p-8 text-center`}><Package className="mx-auto h-8 w-8 text-[#9CA3AF]" strokeWidth={1.25} aria-hidden /><p className="mt-3 text-sm text-[#4B5563]">پکی در این دسته منتشر نشده است.</p><p className="mt-1 text-xs text-[#6B7280]">دسته دیگری را ببینید، با بودجه پیشنهاد بگیرید یا پک را دستی بسازید.</p>
                <div className="mt-4 flex flex-wrap justify-center gap-2"><button type="button" className={btnSecondary} onClick={() => chooseMethod("budget")}>بر اساس بودجه</button><button type="button" className={btnSecondary} onClick={() => chooseMethod("scratch")}>انتخاب دستی</button></div></div>
            : <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{shown.map(p => <PackGridCard key={p.slug} p={p} good={good} used={used} selected={selected?.slug === p.slug}
                onSelect={() => select(p)} onCustomize={() => setCustomizing(p)} compare={{ picked: picked.includes(p.slug), onPick: () => toggle(p.slug) }} />)}</div>}
          {picked.length >= 2 ? <Link href={`/packs/compare?slugs=${picked.join(",")}`} className={btnPrimary}><Scale className="h-4 w-4" aria-hidden /> مقایسه {toPersianNum(picked.length)} پک</Link>
            : picked.length === 1 ? <p className="text-xs text-[#6B7280]">برای مقایسه حداقل یک پک دیگر انتخاب کنید (حداکثر ۴).</p> : null}
        </section>}
        {method === "budget" && <section aria-labelledby="budget-title" className="space-y-4">
          <div><h2 id="budget-title" className={sectionTitle}>پک متناسب با بودجه شما</h2><p className={sectionSub}>ترکیب پیشنهادی از کالاهای واقعی کاتالوگ ساخته می‌شود و قابل ویرایش است.</p></div>
          <BudgetBuilder preset={preset} onOpen={(items, n) => open({ items, count: n })} />
        </section>}
        <ProcurementServices pack={selected} count={count} onCharity={() => { setMethod("budget"); setPreset({ nonce: Date.now(), people: null, budgetToman: null, occasion: "charity" }); contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }} />
      </div>
      <div className="lg:col-span-4 lg:self-stretch">
        <PackSummaryPanel pack={selected} count={count} setCount={setCount} onContinue={continueSelected} onClear={() => setSelected(null)}
          savedItems={saved?.items.length ?? null} onResumeSaved={() => saved && setDraft(saved)} />
      </div>
    </div>
    <PackSummaryBar pack={selected} count={count} onContinue={continueSelected} />
    <PackCustomizeDialog pack={customizing} onClose={() => setCustomizing(null)} onApply={(d) => { setCustomizing(null); open(d); }} />
  </div>;
}

function PendingAlert({ pending, onReplace, onKeep }: { pending: PackDraft; onReplace: () => void; onKeep: () => void }) {
  return <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4">
    <p className="text-sm text-[#111827]">یک پک ذخیره‌شده دارید. ترکیب جدید ({toPersianNum(pending.items.length)} نوع کالا) جایگزین آن شود؟</p>
    <div className="mt-3 flex flex-wrap gap-3"><button type="button" className={btnPrimary} onClick={onReplace}>جایگزینی پک</button><button type="button" className={btnSecondary} onClick={onKeep}>حفظ پک فعلی</button></div>
  </div>;
}
