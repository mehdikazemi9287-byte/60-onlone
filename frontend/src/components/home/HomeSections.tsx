"use client";

// Homepage — retail layout requested by the user on 2026-11-08 (Canva draft, corrected in Figma:
// https://www.figma.com/design/U2wFUAhjMdD8qBg0KaNH6y). Header and footer stay in the shared layout.
// Every product, category, brand, count, photo and price comes from the live catalog API; the two hero
// photos are real catalog images. Prices follow the existing rule: verified price or "قیمت با استعلام".
// The pack section below is the existing protected pack section, unchanged.

import type {PageContent} from "@/lib/content-types";
import {apiRequest} from "@/lib/api";
import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Boxes, Building2, ClipboardList, Coins, Gift, LayoutGrid, Store, Truck, Wallet } from "lucide-react";
import { catalog, categories as categoriesApi } from "@/lib/api";
import { useGoodImages } from "@/lib/imageQuality";
import { storefront, type PackDetail } from "@/lib/storefront";
import type { Category, Product } from "@/lib/types";
import { formatTomanExact, toPersianNum } from "@/lib/utils";
import { PackCard, UI, loadPackDetails } from "@/components/packs/PackCard";

const ACCENT = "#C4461C"; // used by the protected pack section
const C = { blue: "#034EA2", navy: "#0A2735", orange: "#E0501F", orangeL: "#FF6D41", ink: "#1B2430", gray: "#5F6875", line: "#E4E8EE", bg: "#F3F5F8", blueL: "#E8F0FB", orangeT: "#FDECE5" };
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

/** A few real products from each of the largest categories (the relevance pool alone is dominated by one brand). */
const catLists = new Map<string, Promise<Product[]>>();
function useCategoryProducts(cats: Category[] | null, n = 6): Product[] | null {
  const [items, setItems] = useState<Product[] | null>(null);
  const slugs = useMemo(() => (cats ? cats.slice().sort((a, b) => b.product_count - a.product_count).slice(0, n).map((c) => c.slug) : null), [cats, n]);
  useEffect(() => {
    if (!slugs) return;
    let off = false;
    Promise.all(slugs.map((slug) => {
      if (!catLists.has(slug)) catLists.set(slug, catalog.list({ category: slug, page: 1, page_size: 24, group: "family", sort: "relevance" }).then((r) => r.items).catch(() => { catLists.delete(slug); return []; }));
      return catLists.get(slug)!;
    })).then((lists) => !off && setItems(lists.flat()));
    return () => { off = true; };
  }, [slugs]);
  return items;
}

function Img({ src, alt = "", className = "" }: { src: string | null | undefined; alt?: string; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt={alt} loading="lazy" className={`h-full w-full object-contain mix-blend-multiply ${className}`} /> : <span className="block h-full w-full animate-pulse rounded-xl bg-black/5" />;
}
const H2 = ({ children }: { children: React.ReactNode }) => <h2 className="text-xl font-black md:text-2xl" style={{ color: UI.ink }}>{children}</h2>;
const priceLabel = (p: Product) => (p.purchasable && p.price_minor ? formatTomanExact(p.price_minor / 10) : "قیمت با استعلام");
const Card = ({ children, className = "", label }: { children: React.ReactNode; className?: string; label?: string }) => <section aria-label={label} className={`rounded-[20px] bg-white p-4 md:p-6 ${className}`}>{children}</section>;
function Title({ children, href, more = "مشاهده‌ی همه" }: { children: React.ReactNode; href?: string; more?: string }) {
  return <div className="mb-4 flex items-center justify-between gap-3">
    <h2 className="flex items-center gap-2.5 text-lg font-black md:text-[22px]" style={{ color: C.ink }}><span className="h-6 w-1 rounded-full" style={{ background: C.blue }} />{children}</h2>
    {href && <Link href={href} className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold" style={{ color: C.blue }}>{more}<ArrowLeft className="h-4 w-4" /></Link>}
  </div>;
}

// ── Hero: employee gifts (copy can be overridden from the content panel) ──
const HERO_IMAGES = ["/images/catalog/33c657bae8d646702dc50726178d374197ef7aad2114a858bb5b0e51c129e4c2.jpg", "/images/catalog/3a30bc8720ae582140060b6ea6cdb03e7c59e85276fff904402d576c95b3635f.jpg"];
function Hero({ content }: { content?: { title?: string; body?: string; link?: string; button_label?: string } }) {
  return (
    <section className="grid overflow-hidden rounded-[24px] bg-white md:grid-cols-[1.15fr_1fr]" aria-labelledby="home-hero">
      <div className="flex flex-col items-start justify-center gap-4 p-6 md:p-12" style={{ background: C.blue }}>
        <span className="rounded-full px-3.5 py-1.5 text-sm font-bold" style={{ background: C.orangeL, color: C.navy }}>هدیه‌ی پایان سال</span>
        <h1 id="home-hero" className="whitespace-pre-line text-[28px] font-black leading-[1.45] text-white md:text-[40px]">{content?.title || "هدیه‌ی کارکنان، به تعداد،\nبا بسته‌بندی کادویی"}</h1>
        <p className="text-sm leading-7 text-[#DCE7F7] md:text-[17px]">{content?.body || "جعبه‌های آجیل و خشکبار و پک‌های آماده، برای همه‌ی پرسنل سازمان"}</p>
        <Link href={content?.link || "/packs/employee-gift"} className="mt-2 inline-flex h-12 items-center gap-2 rounded-xl bg-white px-5 text-base font-bold" style={{ color: C.blue }}>{content?.button_label || "مشاهده‌ی هدیه‌ها"}<ArrowLeft className="h-5 w-5" /></Link>
      </div>
      <div className="relative flex min-h-[220px] items-center justify-center gap-2 p-6" style={{ background: "#F6F1EA" }}>
        <span className="block aspect-square w-[58%] max-w-[300px]"><Img src={HERO_IMAGES[0]} alt="جعبه‌ی هدیه‌ی آجیل" /></span>
        <span className="block aspect-square w-[36%] max-w-[210px] self-end"><Img src={HERO_IMAGES[1]} alt="جعبه‌ی کادویی آجیل" /></span>
      </div>
    </section>
  );
}

// ── Service shortcuts ──────────────────────────────────────────────────────
const SERVICES: [typeof Gift, string, string][] = [
  [Building2, "خرید سازمانی", "/org"], [Boxes, "پک‌ساز", "/pack-builder"], [Gift, "هدیه‌ی کارکنان", "/packs/employee-gift"], [Wallet, "کیف پول رفاهی", "/wallet"],
  [ClipboardList, "درخواست قیمت عمده", "/requests/new"], [Coins, "وامبی", "/vambi"], [Store, "غرفه‌ها", "/shops"], [Truck, "پیگیری سفارش", "/orders"],
];
function Services() {
  return (
    <Card label="خدمات" className="grid grid-cols-4 gap-y-5 md:grid-cols-8">
      {SERVICES.map(([Icon, label, href], i) => (
        <Link key={href} href={href} className="flex flex-col items-center gap-2.5 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full md:h-[68px] md:w-[68px]" style={{ background: i % 2 ? C.orangeT : C.blueL, color: i % 2 ? C.orange : C.blue }}><Icon className="h-7 w-7" strokeWidth={1.8} /></span>
          <span className="text-xs font-semibold leading-5 md:text-sm" style={{ color: C.ink }}>{label}</span>
        </Link>))}
    </Card>
  );
}

// ── Organization prices strip ──────────────────────────────────────────────
function OrgPrices({ items }: { items: Product[] | null }) {
  if (items && !items.length) return null;
  return (
    <section className="rounded-[22px] p-4 md:p-5" style={{ background: C.orange }} aria-labelledby="org-prices">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div><h2 id="org-prices" className="text-xl font-black text-white md:text-[26px]">قیمت سازمانی</h2>
          <p className="mt-0.5 text-xs font-medium text-[#FFE9DF] md:text-sm">قیمت‌ها فقط برای اعضای سازمان‌های طرف قرارداد نمایش داده می‌شود</p></div>
        <Link href="/business/catalog" className="inline-flex min-h-11 shrink-0 items-center gap-1 text-sm font-semibold text-white">مشاهده‌ی همه<ArrowLeft className="h-4 w-4" /></Link>
      </div>
      <div className="-mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-1 md:overflow-visible">
        {(items ?? Array.from({ length: 6 }, () => null)).map((p, i) => (
          <Link key={p?.id ?? i} href={p ? `/products/${p.slug}` : "#"} className="flex w-40 shrink-0 snap-start flex-col items-center gap-1.5 rounded-[14px] bg-white p-3 text-center md:w-[calc((100%-60px)/6)]">
            <span className="block aspect-square w-full p-1"><Img src={p?.image_url} alt={p?.name} /></span>
            <b className="line-clamp-2 min-h-[42px] text-sm leading-[21px]" style={{ color: C.ink }}>{p?.name ?? " "}</b>
            <span className="text-xs" style={{ color: C.gray }}>{p?.brand || p?.category?.name || " "}</span>
            <span className="mt-auto text-[15px] font-black tabular-nums" style={{ color: C.ink }}>{p ? priceLabel(p) : ""}</span>
          </Link>))}
      </div>
    </section>
  );
}

// ── Category promo tiles (largest real categories with their own photo) ───
const TILE_BG = ["#E3EDFA", "#FFF2D2", "#FCE6D8", "#ECEEFA"];
type CatPick = { cat: Category; img?: string };
function Promos({ picks }: { picks: CatPick[] | null }) {
  if (picks && !picks.length) return null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
      {(picks ?? Array.from({ length: 4 }, () => null)).slice(0, 4).map((c, i) => (
        <Link key={c?.cat.slug ?? i} href={c ? `/category/${c.cat.slug}` : "#"} className="relative flex h-40 overflow-hidden rounded-[18px] p-4 md:h-44" style={{ background: TILE_BG[i] }}>
          <span className="z-10 flex h-full flex-col justify-between">
            <b className="line-clamp-2 max-w-[9rem] text-base font-black leading-7 md:text-xl" style={{ color: C.navy }}>{c?.cat.name ?? ""}</b>
            <span className="inline-flex w-fit items-center gap-1 rounded-full bg-white px-3 py-1.5 text-xs font-bold" style={{ color: C.navy }}>مشاهده‌ی کالاها<ArrowLeft className="h-3.5 w-3.5" /></span>
          </span>
          <span className="absolute bottom-3 left-2 block h-24 w-24 md:h-32 md:w-32">{c?.img && <Img src={c.img} alt="" />}</span>
        </Link>))}
    </div>
  );
}

// ── Shop by category ───────────────────────────────────────────────────────
function Categories({ picks }: { picks: CatPick[] | null }) {
  return (
    <Card label="دسته‌بندی‌ها">
      <Title href="/category" more="همه‌ی دسته‌ها">خرید بر اساس دسته‌بندی</Title>
      <div className="grid grid-cols-3 gap-x-3 gap-y-5 md:grid-cols-6">
        {(picks ?? Array.from({ length: 6 }, () => null)).slice(0, 6).map((c, i) => (
          <Link key={c?.cat.slug ?? i} href={c ? `/category/${c.cat.slug}` : "#"} className="flex flex-col items-center gap-1.5 text-center">
            <span className="mb-1 flex aspect-square w-full max-w-[132px] items-center justify-center overflow-hidden rounded-full p-4" style={{ background: "#F1F4F8" }}>
              {c?.img ? <Img src={c.img} alt="" /> : <LayoutGrid className="h-10 w-10" style={{ color: i % 2 ? C.orange : C.blue }} strokeWidth={1.6} />}</span>
            <b className="text-sm leading-6 md:text-[15px]" style={{ color: C.ink }}>{c?.cat.name ?? " "}</b>
            <span className="text-xs" style={{ color: C.gray }}>{c ? `${toPersianNum(c.cat.product_count)} کالا` : " "}</span>
          </Link>))}
      </div>
    </Card>
  );
}

// ── One brand's products (کاله when present, otherwise the largest brand) ─
function BrandRow({ brand, items }: { brand: string | null; items: Product[] | null }) {
  if (items && items.length < 2) return null;
  return (
    <Card label={brand ?? "برند"}>
      <Title href={brand ? `/search?brand=${encodeURIComponent(brand)}` : "/search"}>{brand ? `محصولات ${brand}` : " "}</Title>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(items ?? Array.from({ length: 4 }, () => null)).slice(0, 4).map((p, i) => (
          <Link key={p?.id ?? i} href={p ? `/products/${p.slug}` : "#"} className="flex items-center gap-3 rounded-[14px] border p-3" style={{ borderColor: C.line }}>
            <span className="min-w-0 flex-1">
              <b className="line-clamp-2 text-sm leading-6" style={{ color: C.ink }}>{p?.name ?? " "}</b>
              <span className="block text-xs" style={{ color: C.gray }}>{p?.brand ?? ""}</span>
              <span className="mt-1 block text-[15px] font-black tabular-nums" style={{ color: C.ink }}>{p ? priceLabel(p) : ""}</span>
            </span>
            <span className="block h-24 w-24 shrink-0"><Img src={p?.image_url} alt={p?.name} /></span>
          </Link>))}
      </div>
    </Card>
  );
}

// ── Shops and brands (name + real count; brand logos only when supplied) ──
function Brands() {
  const [items, setItems] = useState<{ name: string; product_count: number; image_url: string | null }[] | null>(null);
  useEffect(() => { storefront.brands().then((r) => setItems(r.items.slice(0, 8))).catch(() => setItems([])); }, []);
  if (items && !items.length) return null;
  return (
    <Card label="غرفه‌ها و برندها">
      <Title href="/shops" more="همه‌ی غرفه‌ها">غرفه‌ها و برندها</Title>
      <div className="grid grid-cols-4 gap-2 md:gap-3 lg:grid-cols-8">
        {(items ?? Array.from({ length: 8 }, () => null)).map((b, i) => b ? (
          <Link key={b.name} href={`/search?brand=${encodeURIComponent(b.name)}`} className="flex flex-col items-center gap-1.5 rounded-[14px] border px-1 py-3 text-center md:px-2 md:py-4" style={{ borderColor: C.line }}>
            <span className="mb-1 flex h-11 w-11 items-center justify-center rounded-full text-lg font-black md:h-14 md:w-14 md:text-xl" style={{ background: C.blueL, color: C.blue }}>{b.name.slice(0, 1)}</span>
            <b className="line-clamp-1 text-sm md:text-base" style={{ color: C.ink }}>{b.name}</b>
            <span className="text-xs" style={{ color: C.gray }}>{toPersianNum(b.product_count)} کالا</span>
          </Link>) : <span key={i} className="h-[132px] animate-pulse rounded-[14px] bg-black/5" />)}
      </div>
    </Card>
  );
}

// ── Sell on 60Online ───────────────────────────────────────────────────────
function Seller() {
  return (
    <section className="flex flex-col gap-4 rounded-[20px] p-5 md:flex-row md:items-center md:justify-between md:px-8" style={{ background: "#E3EDFA" }}>
      <span className="flex items-center gap-4">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-white" style={{ color: C.blue }}><Store className="h-8 w-8" strokeWidth={1.8} /></span>
        <span><b className="block text-xl font-black md:text-[22px]" style={{ color: C.navy }}>در شصت‌آنلاین بفروشید</b>
          <span className="mt-1 block text-sm md:text-[15px]" style={{ color: C.gray }}>غرفه بگیرید و به اعضای سازمان‌های طرف قرارداد بفروشید</span></span>
      </span>
      <Link href="/sell" className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl px-6 text-base font-bold text-white" style={{ background: C.blue }}>درخواست غرفه<ArrowLeft className="h-5 w-5" /></Link>
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


export default function FigmaHome({previewContent}:{previewContent?:PageContent}={}) {
  const { pool: base, cats } = useCatalog();
  const extra = useCategoryProducts(cats);
  const raw = useMemo(() => {
    if (!base || !extra) return base && cats && !cats.length ? base : null;
    const seen = new Set<number>(), out: Product[] = [];
    for (const p of [...base, ...extra]) if (!seen.has(p.id)) { seen.add(p.id); out.push(p); }
    return out;
  }, [base, extra, cats]);
  const pool = useVerified(raw);
  const brandRow = useMemo(() => {
    if (!pool) return { brand: null, items: null };
    const counts = new Map<string, number>();
    for (const p of pool) if (p.brand) counts.set(p.brand, (counts.get(p.brand) ?? 0) + 1);
    const brand = counts.has("کاله") ? "کاله" : [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
    return { brand, items: brand ? diversify(pool.filter((p) => p.brand === brand), 4) : [] };
  }, [pool]);
  const orgItems = useMemo(() => {
    if (!pool) return null;
    const inRow = new Set((brandRow.items ?? []).map((p) => p.id));
    const rest = diversify(pool.filter((p) => !inRow.has(p.id)), 6);
    return rest.length >= 4 ? rest : diversify(pool, 6);
  }, [pool, brandRow]);
  const used = useMemo(() => new Set((orgItems ?? []).map((p) => p.image_url!)), [orgItems]);
  // Largest real categories, each with one of its own verified photos not already shown above.
  const catPicks = useMemo<CatPick[] | null>(() => {
    if (!cats || !pool) return null;
    const taken = new Set(used);
    return cats.slice().sort((a, b) => b.product_count - a.product_count).map((cat) => {
      const own = pool.filter((x) => x.category?.slug === cat.slug && x.image_url);
      const p = own.find((x) => !taken.has(x.image_url!)) ?? own[0];
      if (p?.image_url) taken.add(p.image_url);
      return { cat, img: p?.image_url };
    });
  }, [cats, pool, used]);
  const [published,setPublished]=useState<PageContent|null>(null);
  useEffect(()=>{if(previewContent)return;const c=new AbortController();apiRequest<{content:PageContent}>("/content/pages/homepage",{signal:c.signal}).then(r=>{if(!c.signal.aborted&&Array.isArray(r.content?.blocks))setPublished(r.content)}).catch(()=>{});return()=>c.abort()},[previewContent]);
  const configured=previewContent??published;
  // The content panel can still hide a section it knows about; new sections are always shown.
  const hidden=new Set((configured?.blocks??[]).filter(b=>b.type==="home_section"&&!b.enabled).map(b=>b.key??""));
  const hero=configured?.blocks.find(b=>b.key==="hero");
  const order=["hero","services","organization","collections","categories","packs","today","brands","seller"].filter(k=>!hidden.has(k));
  const sections:Record<string,React.ReactNode>={
   hero:<Hero content={hero}/>,services:<Services/>,organization:<OrgPrices items={orgItems}/>,collections:<Promos picks={catPicks}/>,
   categories:<Categories picks={catPicks}/>,packs:<Packs/>,today:<BrandRow brand={brandRow.brand} items={brandRow.items}/>,brands:<Brands/>,seller:<Seller/>
  };
  return <div style={{ background: C.bg }}><div className="mx-auto flex w-full max-w-[1280px] flex-col gap-5 px-4 py-4 md:px-8 md:py-6" dir="rtl">{order.map(key=><Fragment key={key}>{sections[key]}</Fragment>)}</div></div>;
}
