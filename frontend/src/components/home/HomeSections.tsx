"use client";

// Organization-first refinement explicitly requested by the user; original Figma is a baseline, not a current pixel-parity claim.
// Original homepage — implemented from the final Figma frames (file Q4lD8SJ0MfZzHTAM94NUpQ,
// 166:219 desktop / 166:220 mobile): store hero, real categories, today's products,
// one pack section (→ /pack-builder), 60AI shopping assistant and a short organization entry.
// Every product, image, category, pack and price comes from the live catalog API;
// photos pass the card-quality gate and unverified prices read "استعلام قیمت".

import BusinessHero from "./BusinessHero";
import type {PageContent} from "@/lib/content-types";
import {apiRequest} from "@/lib/api";
import { Fragment, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Boxes, Building2, LayoutGrid, MessageSquareText, Sparkles, Tag } from "lucide-react";
import { catalog, categories as categoriesApi } from "@/lib/api";
import { useGoodImages } from "@/lib/imageQuality";
import { storefront, type PackDetail } from "@/lib/storefront";
import type { Category, Product } from "@/lib/types";
import { formatTomanExact, toPersianNum } from "@/lib/utils";
import { PackCard, UI, loadPackDetails } from "@/components/packs/PackCard";

const ACCENT = "#C4461C"; // brand coral, darkened to AA contrast (≥4.5:1) with white; reserved for conversion actions
const hasImage = (p: Product) => !!p.image_url && !p.image_url.includes("picsum.photos");

// ── Live catalog, fetched once per page view ───────────────────────────────
let poolRequest: Promise<Product[]> | null = null;
let catsRequest: Promise<Category[]> | null = null;
function useCatalog() {
  const [pool, setPool] = useState<Product[] | null>(null);
  const [cats, setCats] = useState<Category[] | null>(null);
  useEffect(() => {
    let off = false;
    poolRequest ??= (async () => {
      const first = await catalog.list({ page: 1, page_size: 48, group: "family", sort: "relevance" });
      const pages = Math.min(4, Math.ceil((first.total ?? first.items.length) / 48));
      const rest = await Promise.all(Array.from({ length: Math.max(0, pages - 1) }, (_, i) => catalog.list({ page: i + 2, page_size: 48, group: "family", sort: "relevance" }).then((r) => r.items).catch(() => [])));
      return [...first.items, ...rest.flat()];
    })().catch(() => { poolRequest = null; return []; });
    catsRequest ??= categoriesApi.list().then((c) => c.filter((x) => x.product_count > 0)).catch(() => { catsRequest = null; return []; });
    poolRequest.then((p) => !off && setPool(p));
    catsRequest.then((c) => !off && setCats(c));
    return () => { off = true; };
  }, []);
  return { pool, cats };
}

const family = (name: string) => name.replace(/[0-9۰-۹]+/g, " ").replace(/(کیلویی|گرمی|گرم|کیلو|عددی|بسته|شماره|لیتری|اینچ)/g, " ").split(/\s+/).filter(Boolean).slice(0, 2).join(" ");
/** Category round-robin, one product per near-duplicate family and per photo. */
function diversify(list: Product[], limit: number): Product[] {
  const seen = new Set<string>(), groups = new Map<string, Product[]>();
  for (const p of list) {
    const f = family(p.name);
    if (seen.has(f) || seen.has(p.image_url ?? "")) continue;
    seen.add(f); if (p.image_url) seen.add(p.image_url);
    const k = p.category?.slug ?? "other";
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(p);
  }
  const lists = [...groups.values()], out: Product[] = [];
  for (let r = 0; out.length < limit && lists.some((l) => l.length > r); r++) for (const l of lists) if (l[r] && out.length < limit) out.push(l[r]);
  return out;
}
/** Products whose photo passes the card-quality gate (null while checking). */
function useVerified(pool: Product[] | null): Product[] | null {
  const good = useGoodImages((pool ?? []).filter(hasImage).map((p) => p.image_url));
  return pool && good ? pool.filter((p) => p.image_url && good.has(p.image_url)) : null;
}

function Img({ src, alt = "", className = "" }: { src: string | null | undefined; alt?: string; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt={alt} loading="lazy" className={`h-full w-full object-contain ${className}`} /> : <span className="block h-full w-full animate-pulse rounded-xl bg-white/70" />;
}
const H2 = ({ children }: { children: React.ReactNode }) => <h2 className="text-xl font-black md:text-2xl" style={{ color: UI.ink }}>{children}</h2>;
const priceLabel = (p: Product) => (p.purchasable && p.price_minor ? formatTomanExact(p.price_minor / 10) : "قیمت با استعلام");

// ── Store hero (Figma "Store hero") + 60AI shopping assistant entry ───────
function Hero({ picks }: { picks: Product[] | null }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const ask = (e: FormEvent) => { e.preventDefault(); router.push(q.trim() ? `/assistant?q=${encodeURIComponent(q.trim())}` : "/assistant"); };
  return (
    <section className="grid items-center gap-5 overflow-hidden rounded-[20px] p-4 md:grid-cols-2 md:gap-8 md:p-8" style={{ background: UI.mint }}>
      <div className="grid grid-cols-3 gap-3 md:order-2">
        {(picks ?? [null, null, null]).map((p, i) => (
          <Link key={p?.id ?? i} href={p ? `/products/${p.slug}` : "#today"} aria-label={p?.name ?? "محصولات"} className={`aspect-square overflow-hidden rounded-2xl bg-white p-2 shadow-sm ${i === 1 ? "md:-translate-y-3" : ""}`}>
            <Img src={p?.image_url} alt={p?.name} />
          </Link>
        ))}
      </div>
      <div className="flex flex-col gap-3 md:order-1">
        <h1 className="text-[28px] font-black leading-[1.55] md:text-[40px]" style={{ color: UI.ink }}>برای زندگی، برای کار.</h1>
        <p className="-mt-2 text-xs font-bold" style={{ color: ACCENT }}>فروشگاه آنلاین خرید خانه و تأمین کالای سازمان</p>
        <p className="text-sm leading-7 md:text-base" style={{ color: UI.ink }}>کالای روزمره، دیجیتال و هدیه را با قیمت واقعی بخرید، یا برای قیمت روز استعلام بگیرید.</p>
        <Link href="#today" className="mt-1 flex h-12 w-full items-center justify-center rounded-xl text-sm font-bold text-white shadow-sm md:w-60" style={{ background: ACCENT }}>شروع خرید</Link>
        <form id="ai" onSubmit={ask} className="mt-2 flex scroll-mt-28 items-center gap-2 rounded-xl bg-white p-1.5 shadow-sm" aria-label="60AI">
          <span className="flex h-9 shrink-0 items-center gap-1 rounded-lg px-2 text-xs font-black text-white" style={{ background: UI.ink }}><Sparkles className="h-4 w-4" />60AI</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="دستیار خرید: مثلاً برنج ۱۰ کیلویی برای خانواده" aria-label="درخواست از دستیار خرید 60AI" className="h-9 min-w-0 flex-1 bg-transparent px-1 text-sm focus:outline-none" />
          <button type="submit" className="h-9 shrink-0 rounded-lg px-3 text-sm font-bold" style={{ color: UI.ink, background: UI.warm }}>بپرس</button>
        </form>
      </div>
    </section>
  );
}

// ── Real categories ────────────────────────────────────────────────────────
function Categories({ cats }: { cats: Category[] | null }) {
  const list = (cats ?? []).slice().sort((a, b) => b.product_count - a.product_count).slice(0, 9);
  const tile = "flex min-h-14 flex-col items-center justify-center rounded-xl border bg-white px-2 py-2 text-center";
  return (
    <section className="space-y-4">
      <H2>دسته‌بندی‌های فروشگاه</H2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {cats === null ? Array.from({ length: 10 }).map((_, i) => <span key={i} className={`${tile} animate-pulse`} style={{ borderColor: UI.line }} />)
          : list.map((c) => (
            <Link key={c.slug} href={`/category/${c.slug}`} className={tile} style={{ borderColor: UI.line }}>
              <b className="text-sm" style={{ color: UI.ink }}>{c.name}</b>
              <span className="text-[11px]" style={{ color: UI.muted }}>{toPersianNum(c.product_count)} کالا</span>
            </Link>))}
        {cats !== null && <Link href="/category" className={`${tile} gap-1`} style={{ borderColor: UI.line }}>
          <b className="flex items-center gap-1.5 text-sm" style={{ color: UI.ink }}><LayoutGrid className="h-4 w-4" /> همه دسته‌ها</b>
        </Link>}
      </div>
    </section>
  );
}

// ── Today's products (Figma "Product cards") ───────────────────────────────
function Today({ items }: { items: Product[] | null }) {
  return (
    <section id="today" className="scroll-mt-28 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <H2>برای خرید امروز</H2>
        <Link href="/search" className="inline-flex min-h-11 items-center gap-1 text-sm" style={{ color: UI.muted }}>مشاهده همه <ArrowLeft className="h-4 w-4" /></Link>
      </div>
      {items && !items.length ? (
        <p className="rounded-xl py-10 text-center text-sm" style={{ background: UI.warm, color: UI.muted }}>فعلاً کالایی با تصویر مناسب منتشر نشده است. <Link href="/search" className="font-bold underline">همه کالاها</Link></p>
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4 lg:grid-cols-5">
          {(items ?? Array.from({ length: 10 }).map(() => null)).map((p, i) => (
            <article key={p?.id ?? i} className={`flex min-w-0 flex-col gap-2 rounded-2xl border bg-white p-3 md:p-4 ${i >= 6 ? "hidden lg:flex" : ""}`} style={{ borderColor: UI.line }}>
              <Link href={p ? `/products/${p.slug}` : "#"} className="block aspect-square overflow-hidden rounded-xl bg-white" aria-label={p?.name}>
                <Img src={p?.image_url} alt={p?.name} className="p-2" />
              </Link>
              <Link href={p ? `/products/${p.slug}` : "#"} className="line-clamp-2 min-h-[40px] text-sm font-bold leading-5" style={{ color: UI.ink }}>{p?.name ?? " "}</Link>
              <span className="min-h-[20px] text-sm font-black tabular-nums" style={{ color: UI.ink }}>{p ? priceLabel(p) : ""}</span>
              <Link href={p ? `/products/${p.slug}` : "#"} className="mt-auto flex h-11 items-center justify-center rounded-xl border text-sm font-bold" style={p && !(p.purchasable && p.price_minor) ? { color: ACCENT, borderColor: ACCENT } : { color: UI.ink, borderColor: UI.line }}>{p && !(p.purchasable && p.price_minor) ? "درخواست قیمت روز" : "مشاهده و خرید"}</Link>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Why 60Online: only claims the product itself backs ─────────────────────
const WHY: [typeof Tag, string, string][] = [
  [Tag, "قیمت واقعی، نه تخمینی", "قیمت فقط از پیشنهاد تأییدشده فروشنده نمایش داده می‌شود."],
  [MessageSquareText, "استعلام قیمت روز", "برای کالای بدون قیمت، درخواست ثبت کنید تا قیمت و زمان تحویل اعلام شود."],
  [Boxes, "پک‌ساز هوشمند", "پک آماده، پک بر اساس بودجه یا پک دلخواه از کالاهای واقعی."],
  [Building2, "شخصی و سازمانی", "خرید خانه و تأمین کالای سازمان در یک فروشگاه."],
];
function Why() {
  return (
    <section aria-label="چرا 60Online" className="grid grid-cols-2 gap-3 rounded-[20px] p-4 md:grid-cols-4 md:gap-4 md:p-6" style={{ background: UI.warm }}>
      {WHY.map(([Icon, t, d]) => (
        <div key={t} className="flex flex-col gap-2 md:flex-row md:items-start md:gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white" style={{ background: UI.ink }}><Icon className="h-5 w-5" /></span>
          <span><b className="block text-sm font-black" style={{ color: UI.ink }}>{t}</b><span className="mt-0.5 block text-xs leading-5" style={{ color: UI.muted }}>{d}</span></span>
        </div>))}
    </section>
  );
}

// ── Product groups: real categories with their own real photos ──────────────
function Groups({ pool, used }: { pool: Product[] | null; used: Set<string> }) {
  const groups = useMemo(() => {
    if (!pool) return null;
    const by = new Map<string, Product[]>();
    for (const p of pool) if (p.category && p.image_url && !used.has(p.image_url)) { const k = p.category.slug; if (!by.has(k)) by.set(k, []); by.get(k)!.push(p); }
    return [...by.values()].filter((l) => l.length >= 3).sort((a, b) => b.length - a.length).slice(0, 3)
      .map((l) => ({ cat: l[0].category!, items: diversify(l, 3).length >= 3 ? diversify(l, 3) : l.slice(0, 3), count: l.length }));
  }, [pool, used]);
  if (groups && !groups.length) return null;
  return (
    <section className="space-y-4">
      <H2>پیشنهادهای فروشگاه</H2>
      <div className="grid gap-4 md:grid-cols-3">
        {(groups ?? [null, null, null]).map((g, i) => g ? (
          <Link key={g.cat.slug} href={`/category/${g.cat.slug}`} className="flex flex-col gap-3 rounded-2xl p-4" style={{ background: UI.warm }}>
            <span className="flex items-center justify-between gap-2"><b className="text-base font-black" style={{ color: UI.ink }}>{g.cat.name}</b>
              <span className="inline-flex items-center gap-1 text-xs" style={{ color: UI.muted }}>مشاهده همه <ArrowLeft className="h-4 w-4" /></span></span>
            <span className="grid grid-cols-3 gap-2">{g.items.map((p) => <span key={p.id} className="aspect-square overflow-hidden rounded-xl bg-white p-1.5"><Img src={p.image_url} alt={p.name} /></span>)}</span>
          </Link>) : <span key={i} className="h-44 animate-pulse rounded-2xl" style={{ background: UI.warm }} />)}
      </div>
    </section>
  );
}

// ── Real brands (monogram; product photos stay on product cards) ──────────
function Brands() {
  const [items, setItems] = useState<{ name: string; product_count: number; image_url: string | null }[] | null>(null);
  useEffect(() => { storefront.brands().then((r) => setItems(r.items.slice(0, 8))).catch(() => setItems([])); }, []);
  if (items && !items.length) return null;
  return (
    <section className="space-y-4" aria-label="برندها">
      <H2>برندهای فروشگاه</H2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        {(items ?? Array.from({ length: 8 }, () => null)).map((b, i) => b ? (
          <Link key={b.name} href={`/search?brand=${encodeURIComponent(b.name)}`} className="flex items-center gap-3 rounded-2xl border bg-white p-2.5 lg:flex-col lg:text-center" style={{ borderColor: UI.line }}>
            <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl text-lg font-black" style={{ background: UI.warm, color: UI.ink }}>
              {b.name.slice(0, 1)}</span>
            <span className="min-w-0"><b className="line-clamp-1 text-sm" style={{ color: UI.ink }}>{b.name}</b><span className="block text-[11px]" style={{ color: UI.muted }}>{toPersianNum(b.product_count)} کالا</span></span>
          </Link>) : <span key={i} className="h-[68px] animate-pulse rounded-2xl" style={{ background: UI.warm }} />)}
      </div>
    </section>
  );
}

// ── The single homepage pack section (Figma "Single homepage pack section") ─
const FEATURED = ["family-daily", "gathering-tea", "employee-gift"];
function Packs() {
  const [packs, setPacks] = useState<PackDetail[] | null>(null);
  useEffect(() => { let off = false; loadPackDetails().then((p) => !off && setPacks(p)).catch(() => !off && setPacks([])); return () => { off = true; }; }, []);
  const shown = useMemo(() => {
    if (!packs) return null;
    const real = packs.filter((p) => p.items.length);
    const first = FEATURED.map((s) => real.find((p) => p.slug === s)).filter((p): p is PackDetail => !!p);
    return [...first, ...real.filter((p) => !first.includes(p))].slice(0, 3);
  }, [packs]);
  const good = useGoodImages((shown ?? []).flatMap((p) => p.items.map((i) => i.image_url)));
  const used = new Set<string>();
  if (shown && !shown.length) return null;
  return (
    <section id="packs" className="scroll-mt-28 space-y-4 rounded-[20px] p-4 md:p-6" style={{ background: UI.mint }}>
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between"><div><p className="text-xs font-bold" style={{ color: ACCENT }}>پک‌ساز 60Online</p><H2>بودجه یا نیازت را بگو؛ پک مناسب بساز.</H2>
        <p className="mt-1 text-sm leading-6" style={{ color: UI.ink }}>برای خانه، هدیه، مناسبت یا سازمان؛ پک آماده را انتخاب کنید، بر اساس بودجه بسازید یا اقلام را خودتان بچینید.</p></div>
        <Link href="/pack-builder" className="flex h-12 shrink-0 items-center justify-center rounded-xl px-8 text-sm font-bold text-white" style={{ background: UI.ink }}>شروع پک‌سازی</Link></div>
      <div className="grid gap-4 md:grid-cols-3">
        {(shown ?? [null, null, null]).map((p, i) => p ? <PackCard key={p.slug} p={p} good={good} used={used} /> : <span key={i} className="h-96 animate-pulse rounded-2xl bg-white/70" />)}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm font-bold" style={{ color: UI.ink }}>
        <Link href="/pack-builder" className="inline-flex min-h-11 items-center gap-1">همه پک‌های آماده <ArrowLeft className="h-4 w-4" /></Link>
        <Link href="/pack-builder?mode=budget" className="inline-flex min-h-11 items-center gap-1">ساخت بر اساس بودجه <ArrowLeft className="h-4 w-4" /></Link>
        <Link href="/pack-builder?mode=scratch" className="inline-flex min-h-11 items-center gap-1">ساخت دستی <ArrowLeft className="h-4 w-4" /></Link>
      </div>
    </section>
  );
}

// ── Organization entry (details live in the independent /org area) ─────────
function Org() {
  return (
    <section className="flex flex-col gap-4 rounded-[20px] p-5 text-white md:flex-row md:items-center md:justify-between md:p-6" style={{ background: UI.ink }}>
      <div><p className="text-xs font-bold text-white/70">خرید سازمانی</p><h2 className="text-xl font-black md:text-2xl">برای سازمان‌ها، شرکت‌ها و مجموعه‌ها</h2>
        <p className="mt-1 text-sm leading-7 text-white/85">تأمین کالا، پک سازمانی و خرید با تأیید و پیگیری در پنل جداگانه سازمان</p></div>
      <Link href="/org" className="flex h-11 flex-none items-center justify-center gap-2 rounded-xl bg-white px-6 text-sm font-bold md:w-64" style={{ color: UI.ink }}><Building2 className="h-4 w-4" /> مشاهده خدمات سازمانی</Link>
    </section>
  );
}

export default function FigmaHome({previewContent}:{previewContent?:PageContent}={}) {
  const { pool: raw, cats } = useCatalog();
  const pool = useVerified(raw);
  // Hero and rail share one diversified list so no photo appears twice on the page.
  const picks = useMemo(() => (pool ? diversify(pool, 13) : null), [pool]);
  const used = useMemo(() => new Set((picks ?? []).map((p) => p.image_url!)), [picks]);

  const [published,setPublished]=useState<PageContent|null>(null);
  useEffect(()=>{if(previewContent)return;const c=new AbortController();apiRequest<{content:PageContent}>("/content/pages/homepage",{signal:c.signal}).then(r=>{if(!c.signal.aborted&&Array.isArray(r.content?.blocks))setPublished(r.content)}).catch(()=>{});return()=>c.abort()},[previewContent]);
  const configured=previewContent??published;
  const order=configured?configured.blocks.filter(b=>b.type==="home_section"&&b.enabled).map(b=>b.key??""):["hero","collections","categories","today","why","groups","brands","packs","organization"];
  const hero=configured?.blocks.find(b=>b.key==="hero");
  const sections:Record<string,React.ReactNode>={
   hero:<BusinessHero content={hero}/>,
   collections:<section className="grid gap-3 sm:grid-cols-3" aria-label="کاتالوگ مجموعه‌ها">{[{name:"آریا",href:"/business/catalog?supplier=آریا",desc:"نوشت‌افزار و لوازم آموزشی"},{name:"پویا پروتئین",href:"/business/catalog?supplier=پویا%20پروتئین",desc:"مواد پروتئینی"},{name:"کاله",href:"/business/catalog?q=کاله",desc:"لبنیات و محصولات غذایی"}].map(c=><Link key={c.name} href={c.href} className="flex items-center justify-between rounded-2xl border border-[#dce5df] bg-[#faf9f6] p-5"><span><b className="text-base text-[#0a2735]">{c.name}</b><span className="mt-2 block text-xs text-[#52616a]">{c.desc}</span></span><ArrowLeft size={18} className="text-[#004e72]"/></Link>)}</section>,
   categories:<Categories cats={cats}/>,
   today:<Today items={picks&&picks.slice(0,10)}/>,
   why:<Why/>,groups:<Groups pool={pool} used={used}/>,brands:<Brands/>,packs:<Packs/>,organization:<Org/>
  };
  return <div className="bg-white"><div className="mx-auto flex w-full max-w-[1440px] flex-col gap-8 px-4 py-4 md:px-8 md:py-8 xl:px-16" dir="rtl">{order.map(key=><Fragment key={key}>{sections[key]}</Fragment>)}</div></div>;
}
