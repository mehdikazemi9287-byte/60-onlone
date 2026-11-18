"use client";
import { scopedDraftKey, pendingDraftKey } from "@/lib/client-draft-storage";
import { useAuth } from "@/lib/auth-context";
// The single Pack Builder (/pack-builder). Rebuilt 2026-11-18 as a FAITHFUL match of the approved Google
// Stitch screens 62 (desktop 1440) / 63 (mobile 390), with the content blocks of 55, customize popup 60 and
// catalog flipbook 58: stepper, mint hero + 60AI, three build methods, filter tabs + sort, pack cards, sticky
// «پیش‌نمایش سبد پک سازمانی», secondary services, mobile sticky inquiry bar. All data comes from the real
// storefront APIs; the editor/review/quote step is still the existing PackBuilderInteractive (protected, unchanged).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { PackBuilderInteractive, type PackDraft } from "@/components/home/PackBuilderInteractive";
import { BudgetBuilder, type BudgetPreset } from "./BudgetBuilder";
import { loadPackDetails } from "./PackCard";
import { PackGridCard } from "./PackGridCard";
import { PackCustomizeDialog } from "./PackCustomizeDialog";
import { PackSummaryPanel, PackSummaryBar } from "./PackSummaryPanel";
import { ProcurementServices } from "./ProcurementServices";
import { CatalogFlipbook } from "./CatalogFlipbook";
import { StudioHero } from "./StudioHero";
import { GROUPS } from "./pack-groups";
import type { PackIntent } from "./pack-intent";
import { btnPrimary, btnSecondary, card, Icon } from "./studio-ui";
import { useGoodImages } from "@/lib/imageQuality";
import { storefront, type PackDetail } from "@/lib/storefront";
import { toPersianNum } from "@/lib/utils";
import { positiveInteger } from "@/lib/pack-input";

type Method = "template" | "budget" | "scratch";
// Stitch 62 stepper labels; hints rewritten to what the flow really does (no Moadian/Setad claims).
const STEPS: [string, string, string][] = [["انتخاب روش ساخت", "پک آماده، بودجه یا دستی", "روش ساخت"], ["چیدمان و سفارشی‌سازی", "تغییر اقلام و تعداد", "چیدمان"],
  ["بازبینی و بررسی", "قیمت، موجودی و تیراژ", "بررسی"], ["استعلام و پیش‌فاکتور", "سبد خرید یا استعلام رسمی", "استعلام"]];

// Older links used these group keys.
const GROUP_ALIASES: Record<string, string> = { home: "livelihood", gift: "work" };
const SORTS: [string, string, (a: PackDetail, b: PackDetail) => number][] = [
  ["", "ترتیب پیشنهادی", () => 0],
  ["priced", "دارای قیمت قطعی", (a, b) => Number(b.price_minor != null) - Number(a.price_minor != null)],
  ["items", "بیشترین اقلام کالایی", (a, b) => b.item_count - a.item_count],
  ["min", "کمترین حداقل تیراژ", (a, b) => a.min_order_qty - b.min_order_qty],
];
const METHODS = [
  ["template", "پک‌های آماده سازمانی", "پک‌های آماده", "inventory_2", "ترکیب‌های منتشرشده از کالاهای واقعی کاتالوگ برای مناسبت‌ها و تیراژهای گوناگون؛ قابل انتخاب برای استعلام یا شخصی‌سازی.", "مشاهده و انتخاب پکیج", "استاندارد شرکتی"],
  ["budget", "ساخت بر اساس بودجه", "بر اساس بودجه", "payments", "سقف هزینه هر پک و تعداد پرسنل را بدهید تا ترکیب پیشنهادی از کالاهای واقعی کاتالوگ ساخته شود؛ قابل ویرایش.", "شروع برآورد بودجه", "تطبیق سرانه مالی"],
  ["scratch", "انتخاب دستی اقلام", "چیدمان دستی", "tune", "چینش آزاد اقلام از کاتالوگ شصت‌آنلاین، تعیین تعداد هر قلم و تیراژ پک، سپس استعلام یا افزودن به سبد.", "ورود به کاتالوگ کالاها", "انتخاب جزءبه‌جزء"],
] as const;

export function Steps({ active }: { active: number }) {
  return <>
    <ol aria-label="مراحل ساخت پک" className="hidden grid-cols-4 items-center gap-4 rounded-xl border border-gray-200 bg-white p-5 shadow-sm md:grid">
      {STEPS.map(([label, hint], i) => {
        const on = i === active, done = i < active;
        return <li key={label} aria-current={on ? "step" : undefined} className={`flex items-center gap-3 ${i ? "border-r border-gray-100 pr-4" : ""}`}>
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ${on ? "bg-[#034EA2] text-white" : done ? "bg-[#034EA2]/10 text-[#034EA2]" : "bg-gray-100 text-gray-500"}`}>{done ? <Icon name="check" className="!text-[18px]" /> : toPersianNum(i + 1)}</span>
          <span className="flex flex-col"><span className={`text-xs ${on ? "font-bold text-[#034EA2]" : "font-semibold text-gray-700"}`}>{label}</span><span className={`mt-0.5 text-[11px] ${on ? "text-gray-500" : "text-gray-400"}`}>{hint}</span></span>
        </li>;
      })}
    </ol>
    <ol aria-label="مراحل ساخت پک" className="relative flex items-center justify-between rounded-xl border border-gray-200 bg-white px-5 py-3 shadow-sm md:hidden">
      <span aria-hidden className="absolute left-10 right-10 top-[24px] h-[2px] bg-gray-200" />
      {STEPS.map(([label, , short], i) => {
        const on = i === active, done = i < active;
        return <li key={label} aria-current={on ? "step" : undefined} className="relative z-10 flex flex-col items-center gap-1">
          <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] ring-4 ring-white ${on || done ? "bg-[#034EA2] font-bold text-white" : "bg-gray-100 font-semibold text-gray-500"}`}>{toPersianNum(i + 1)}</span>
          <span className={`text-[11px] ${on ? "font-bold text-[#034EA2]" : "font-medium text-gray-500"}`}>{short}</span>
        </li>;
      })}
    </ol>
  </>;
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
  const [sort, setSort] = useState(""), [book, setBook] = useState(false), [bookAt, setBookAt] = useState(0);
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
  const select = (p: PackDetail) => { if (selected?.slug === p.slug) { setSelected(null); return; } setSelected(p); setCount(toPersianNum(Math.max(1, p.min_order_qty))); };
  const continueSelected = () => { const n = positiveInteger(count); if (selected && n) open(fromPack(selected, n)); };
  const chooseMethod = (key: Method) => { setMethod(key); if (key === "scratch") open({items: [], count: 1}); else contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const onIntent = useCallback((intent: PackIntent) => {
    setMethod("budget");
    setPreset({ nonce: Date.now(), ...intent });
    setTimeout(() => contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }, []);
  const used = new Set<string>();
  const sorted = useMemo(() => { const s = SORTS.find(x => x[0] === sort) ?? SORTS[0]; return shown ? [...shown].sort(s[2]) : null; }, [shown, sort]);

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

  const openCatalog = (at = 0) => { setBookAt(at); setBook(true); };
  const fromBook = (p: PackDetail) => { setBook(false); setMethod("template"); setSelected(p); setCount(toPersianNum(Math.max(1, p.min_order_qty))); };

  return <div className="flex flex-col gap-4 pb-28 md:gap-8 lg:pb-0" dir="rtl">
    <div className="flex flex-col gap-4 md:gap-8">
      <div className="order-2 md:order-1"><Steps active={0} /></div>
      <div className="order-1 md:order-2"><StudioHero onIntent={onIntent} /></div>
    </div>
    {pending && <PendingAlert pending={pending} onReplace={() => { setDraft(pending); setSaved(null); setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } setRevision(x => x+1); }} onKeep={() => { setPending(null); try { localStorage.removeItem(pendingDraftKey("60o_pack_builder_draft")); } catch { /* unavailable storage */ } if (saved?.items.length) setDraft(saved); }} />}

    {/* Build methods — Stitch 62 (3 large cards) / 63 (3 compact cards) */}
    <section aria-labelledby="methods-title" className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-1 md:hidden">
        <h2 id="methods-title" className="text-[14px] font-bold text-[#112D46]">مسیر طراحی و انتخاب</h2>
        <span className="text-[11px] font-medium text-[#034EA2]">۳ حالت دسترسی</span>
      </div>
      <div className="grid grid-cols-3 gap-2 md:gap-6" role="tablist" aria-label="روش ساخت پک">
        {METHODS.map(([key, label, short, icon, description, cta, sub], index) => {
          const on = method === key;
          return <button key={key} type="button" role="tab" aria-label={label} aria-selected={on} tabIndex={on ? 0 : -1}
            onKeyDown={e => { const move = e.key === "ArrowRight" ? -1 : e.key === "ArrowLeft" ? 1 : 0; if (move || e.key === "Home" || e.key === "End") { e.preventDefault(); const next = e.key === "Home" ? 0 : e.key === "End" ? 2 : (index + move + 3) % 3; const buttons = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button[role="tab"]'); buttons?.[next]?.focus(); buttons?.[next]?.click(); } }}
            onClick={() => chooseMethod(key)}
            className={`group relative flex h-[96px] flex-col justify-between rounded-xl bg-white p-2.5 text-right shadow-sm transition hover:shadow-md md:h-auto md:p-6 ${on ? "border-2 border-[#034EA2]" : "border border-gray-200 hover:border-gray-300"}`}>
            {key === "template" && <span className="absolute -top-3 right-5 hidden rounded-full bg-[#034EA2] px-3 py-0.5 text-[11px] font-bold text-white md:block">روش پیشنهادی</span>}
            {on && <span className="absolute left-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-[#034EA2] md:hidden" />}
            <span className="block">
              <span className={`flex h-7 w-7 items-center justify-center rounded-lg md:mb-4 md:h-12 md:w-12 md:rounded-xl ${on ? "bg-[#034EA2]/10 text-[#034EA2]" : "bg-gray-100 text-gray-600 md:text-gray-700"}`}><Icon name={icon} className="!text-[17px] md:!text-[24px]" /></span>
              <span className="mb-2 hidden text-base font-bold text-gray-900 md:block">{label}</span>
              <span className="hidden text-xs leading-relaxed text-gray-500 md:block">{description}</span>
            </span>
            <span className="block md:hidden">
              <span className={`block text-[12px] leading-tight ${on ? "font-extrabold text-[#034EA2]" : "font-bold text-[#112D46]"}`}>{short}</span>
              <span className="mt-0.5 block text-[10px] font-normal text-gray-500">{sub}</span>
            </span>
            <span className={`mt-6 hidden items-center justify-between border-t border-gray-100 pt-4 text-xs font-bold md:flex ${on ? "text-[#034EA2]" : "text-gray-700 group-hover:text-[#034EA2]"}`}>
              <span>{cta}</span><Icon name="chevron_left" className="!text-[16px] transition group-hover:-translate-x-1" />
            </span>
          </button>;
        })}
      </div>
    </section>

    {/* Catalog card — Stitch 63 (mobile). The PDF does not exist yet; the online flipbook is built from real packs. */}
    <div className="flex items-center justify-between gap-2 rounded-xl border border-gray-200/90 bg-white p-3 shadow-sm md:hidden">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-orange-50 text-[#FF7A00]"><Icon name="menu_book" className="!text-[20px]" /></span>
        <span className="flex min-w-0 flex-col">
          <span className="flex items-center gap-1.5"><span className="text-[12px] font-bold text-[#112D46]">کاتالوگ آنلاین پک‌ها</span><span className="rounded bg-orange-50 px-1.5 py-0.5 text-[9px] font-bold text-[#FF7A00]">ورق‌زدنی</span></span>
          <span className="text-[10px] font-medium text-gray-500">{packs ? `${toPersianNum(packs.length)} پک منتشرشده` : "در حال دریافت…"} • <Link href="/pack-builder/catalog" className="text-[#034EA2]">آرشیو و ارسال</Link></span>
        </span>
      </div>
      <button type="button" disabled={!packs?.length} onClick={() => openCatalog(0)} className="flex shrink-0 items-center gap-1 rounded-lg bg-gray-100 px-3 py-1.5 text-[11px] font-bold text-[#112D46] transition-colors hover:bg-[#034EA2] hover:text-white disabled:opacity-50">
        <Icon name="auto_stories" className="!text-[16px]" /><span>مشاهده</span>
      </button>
    </div>

    <div ref={contentRef} className="grid scroll-mt-40 grid-cols-1 items-start gap-4 md:gap-8 lg:grid-cols-12">
      <div className="flex min-w-0 flex-col gap-4 md:gap-6 lg:col-span-8">
        {method === "template" && <section aria-labelledby="packs-title" className="flex flex-col gap-3.5 md:gap-6">
          <h2 id="packs-title" className="sr-only">پک‌های آماده</h2>
          <div className="flex items-center justify-between px-1 md:hidden"><span className="text-[14px] font-bold text-[#112D46]">دسته‌بندی پک‌ها</span><span className="text-[11px] text-gray-500">انتخاب موضوعی</span></div>
          <div className="-mx-4 flex items-center gap-2 overflow-x-auto px-4 py-0.5 [scrollbar-width:none] md:mx-0 md:rounded-xl md:border md:border-gray-200 md:bg-white md:p-2 md:shadow-sm" role="group" aria-label="دسته‌بندی پک‌ها">
            {GROUPS.map(([k, l]) => { const on = group === k; return <button key={k || "all"} type="button" aria-pressed={on} onClick={() => setGroup(k)}
              className={`shrink-0 whitespace-nowrap rounded-full px-3.5 py-1.5 text-[12px] transition md:rounded-lg md:px-4 md:py-2 md:text-xs ${on ? "bg-[#112D46] font-bold text-white md:bg-[#034EA2]" : "border border-gray-200 bg-white font-medium text-gray-700 hover:bg-gray-50 md:border-0 md:text-gray-600 md:hover:bg-gray-100 md:hover:text-gray-900"}`}>{k === "" ? <><span className="md:hidden">همه موارد</span><span className="hidden md:inline">{l}{packs ? ` (${toPersianNum(counts[k] ?? 0)})` : ""}</span></> : <>{l}{packs && counts[k] ? <span className="md:hidden"> ({toPersianNum(counts[k])})</span> : null}</>}</button>; })}
          </div>
          <div className="hidden flex-wrap items-center justify-between gap-2 px-1 text-xs text-gray-500 md:flex">
            <span className="font-medium text-gray-700">{sorted ? `نمایش ${toPersianNum(sorted.length)} پک منتشرشده آماده استعلام و پیش‌فاکتور:` : "در حال دریافت پک‌ها…"}</span>
            <div className="flex items-center gap-3">
              <button type="button" disabled={!sorted?.length} onClick={() => openCatalog(0)} className="flex items-center gap-1 font-bold text-[#034EA2] hover:underline disabled:opacity-40"><Icon name="auto_stories" className="!text-[16px]" />کاتالوگ ورق‌زدنی</button>
              <Link href="/pack-builder/catalog" className="flex items-center gap-1 font-bold text-[#034EA2] hover:underline"><Icon name="collections_bookmark" className="!text-[16px]" />آرشیو کاتالوگ‌ها</Link>
              <label className="flex items-center gap-2"><span>مرتب‌سازی:</span>
                <select value={sort} onChange={e => setSort(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-800 focus:border-[#034EA2] focus:outline-none">
                  {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select></label>
            </div>
          </div>
          {saved?.items.length ? <button type="button" onClick={() => setDraft(saved)} className="self-start text-xs font-bold text-[#034EA2] hover:underline lg:hidden">ادامه پک ذخیره‌شده ({toPersianNum(saved.items.length)} نوع کالا)</button> : null}
          {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-800">{error}<button type="button" className="inline-flex min-h-9 items-center gap-1 font-bold underline" onClick={() => {setError("");setRevision(x => x+1);}}><Icon name="refresh" className="!text-[16px]" /> تلاش دوباره</button></div>}
          {sorted === null ? !error && <div role="status" aria-label="در حال دریافت پک‌ها" className="grid gap-3.5 md:grid-cols-2 md:gap-5 xl:grid-cols-3">{[0, 1, 2].map(i => <div key={i} className={`${card} h-[420px] animate-pulse`} />)}</div>
            : !sorted.length ? <div className={`${card} p-8 text-center`}><Icon name="inventory_2" className="!text-[32px] text-gray-400" /><p className="mt-3 text-sm text-gray-600">{packs?.length ? "پکی در این دسته منتشر نشده است." : "هنوز پک آماده‌ای منتشر نشده است."}</p><p className="mt-1 text-xs text-gray-500">دسته دیگری را ببینید، با بودجه پیشنهاد بگیرید یا پک را دستی بسازید.</p>
                <div className="mt-4 flex flex-wrap justify-center gap-2"><button type="button" className={btnSecondary} onClick={() => chooseMethod("budget")}>بر اساس بودجه</button><button type="button" className={btnSecondary} onClick={() => chooseMethod("scratch")}>انتخاب دستی</button></div></div>
            : <div className="grid gap-3.5 md:grid-cols-2 md:gap-5 xl:grid-cols-3">{sorted.map(p => <PackGridCard key={p.slug} p={p} good={good} used={used} selected={selected?.slug === p.slug}
                onSelect={() => select(p)} onCustomize={() => setCustomizing(p)} />)}</div>}
          {picked.length >= 2 ? <Link href={`/packs/compare?slugs=${picked.join(",")}`} className={`${btnPrimary} self-start`}><Icon name="compare_arrows" className="!text-[18px]" /> مقایسه {toPersianNum(picked.length)} پک</Link>
            : picked.length === 1 ? <p className="text-xs text-gray-500">برای مقایسه، پک دیگری را در کاتالوگ نشانه‌گذاری کنید (حداکثر ۴).</p> : null}
        </section>}
        {method === "budget" && <section aria-labelledby="budget-title" className="space-y-4">
          <div><h2 id="budget-title" className="text-sm font-bold text-gray-900 md:text-base">پک متناسب با بودجه شما</h2><p className="mt-1 text-xs text-gray-500">ترکیب پیشنهادی از کالاهای واقعی کاتالوگ ساخته می‌شود و قابل ویرایش است.</p></div>
          <BudgetBuilder preset={preset} onOpen={(items, n) => open({ items, count: n })} />
        </section>}
        <ProcurementServices pack={selected} count={count} onCharity={() => { setMethod("budget"); setPreset({ nonce: Date.now(), people: null, budgetToman: null, occasion: "charity" }); contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }} />
      </div>
      <div className="lg:col-span-4 lg:self-stretch">
        <PackSummaryPanel pack={selected} count={count} setCount={setCount} onContinue={continueSelected} onClear={() => setSelected(null)}
          savedItems={saved?.items.length ?? null} onResumeSaved={() => saved && setDraft(saved)} onCatalog={() => openCatalog(0)} />
      </div>
    </div>
    <PackSummaryBar pack={selected} count={count} onContinue={continueSelected} onCatalog={() => openCatalog(0)} />
    <PackCustomizeDialog pack={customizing} onClose={() => setCustomizing(null)} onApply={(d) => { setCustomizing(null); open(d); }} />
    <CatalogFlipbook open={book} title="کاتالوگ پک‌های فصلی و سازمانی شصت‌آنلاین" packs={sorted ?? []} start={bookAt} onClose={() => setBook(false)} onAdd={fromBook} picked={picked} onPick={toggle} />
  </div>;
}

function PendingAlert({ pending, onReplace, onKeep }: { pending: PackDraft; onReplace: () => void; onKeep: () => void }) {
  return <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4">
    <p className="text-sm text-[#111827]">یک پک ذخیره‌شده دارید. ترکیب جدید ({toPersianNum(pending.items.length)} نوع کالا) جایگزین آن شود؟</p>
    <div className="mt-3 flex flex-wrap gap-3"><button type="button" className={btnPrimary} onClick={onReplace}>جایگزینی پک</button><button type="button" className={btnSecondary} onClick={onKeep}>حفظ پک فعلی</button></div>
  </div>;
}
