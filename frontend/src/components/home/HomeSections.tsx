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
import { UI, loadPackDetails, packImages } from "@/components/packs/PackCard";

const ACCENT = "#C4461C"; // used by the protected pack section
const C = { blue: "#034EA2", navy: "#0A2735", orange: "#E0501F", orangeL: "#FF6D41", ink: "#1B2430", gray: "#5F6875", line: "#E4E8EE", bg: "#F3F5F8", blueL: "#E8F0FB", orangeT: "#FDECE5" };
// Framing: the project's Tailwind `white` is #F9F9F9, so cards use true white plus a hairline and soft shadow.
const FRAME = "border border-[#E3E8EF] bg-[#FFFFFF] shadow-[0_1px_2px_rgba(16,24,40,0.04),0_6px_18px_rgba(16,24,40,0.06)]";
const TILE = "border border-[#E3E8EF] bg-[#FFFFFF] transition hover:-translate-y-0.5 hover:border-[#BFD3EE] hover:shadow-[0_8px_22px_rgba(3,78,162,0.12)]";
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
const Card = ({ children, className = "", label }: { children: React.ReactNode; className?: string; label?: string }) => <section aria-label={label} className={`rounded-[20px] p-4 md:p-6 ${FRAME} ${className}`}>{children}</section>;
function Title({ children, href, more = "مشاهده‌ی همه" }: { children: React.ReactNode; href?: string; more?: string }) {
  return <div className="mb-4 flex items-center justify-between gap-3">
    <h2 className="flex items-center gap-2.5 text-lg font-black md:text-[22px]" style={{ color: C.ink }}><span className="h-6 w-1.5 rounded-full" style={{ background: `linear-gradient(${C.blue}, ${C.orangeL})` }} />{children}</h2>
    {href && <Link href={href} className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold" style={{ color: C.blue }}>{more}<ArrowLeft className="h-4 w-4" /></Link>}
  </div>;
}

// ── Hero: employee gifts (copy can be overridden from the content panel) ──
const HERO_IMAGES = ["/images/catalog/33c657bae8d646702dc50726178d374197ef7aad2114a858bb5b0e51c129e4c2.jpg", "/images/catalog/3a30bc8720ae582140060b6ea6cdb03e7c59e85276fff904402d576c95b3635f.jpg"];
function Hero({ content }: { content?: { title?: string; body?: string; link?: string; button_label?: string } }) {
  return (
    <section className={`relative grid overflow-hidden rounded-[24px] p-1.5 md:grid-cols-[1.15fr_1fr] ${FRAME}`} aria-labelledby="home-hero">
      <div className="relative flex flex-col items-start justify-center gap-4 overflow-hidden rounded-[19px] p-6 md:rounded-l-none md:p-12" style={{ background: `radial-gradient(120% 90% at 100% 0%, #0A63C9 0%, ${C.blue} 55%, #023B7A 100%)` }}>
        <span aria-hidden className="pointer-events-none absolute -left-16 -top-16 h-56 w-56 rounded-full border-[18px] border-white/10" />
        <span aria-hidden className="pointer-events-none absolute -bottom-20 left-1/3 h-48 w-48 rounded-full bg-[#FF6D41]/15 blur-2xl" />
        <span aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.07]" style={{ backgroundImage: "radial-gradient(#fff 1px, transparent 1px)", backgroundSize: "14px 14px" }} />
        <span className="relative rounded-full px-3.5 py-1.5 text-sm font-bold shadow-sm" style={{ background: C.orangeL, color: C.navy }}>هدیه‌ی پایان سال</span>
        <h1 id="home-hero" className="relative whitespace-pre-line text-[28px] font-black leading-[1.45] text-white md:text-[40px]">{content?.title || "هدیه‌ی کارکنان، به تعداد،\nبا بسته‌بندی کادویی"}</h1>
        <p className="relative text-sm leading-7 text-[#DCE7F7] md:text-[17px]">{content?.body || "جعبه‌های آجیل و خشکبار و پک‌های آماده، برای همه‌ی پرسنل سازمان"}</p>
        <Link href={content?.link || "/packs/employee-gift"} className="relative mt-2 inline-flex h-12 items-center gap-2 rounded-xl bg-[#FFFFFF] px-5 shadow-[0_6px_16px_rgba(0,0,0,0.18)] text-base font-bold" style={{ color: C.blue }}>{content?.button_label || "مشاهده‌ی هدیه‌ها"}<ArrowLeft className="h-5 w-5" /></Link>
      </div>
      <div className="relative mt-1.5 flex min-h-[220px] items-center justify-center gap-2 overflow-hidden rounded-[19px] p-6 md:mt-0 md:mr-1.5 md:rounded-r-none" style={{ background: "radial-gradient(80% 80% at 50% 55%, #FFFDF9 0%, #F6EDE2 70%, #EFE2D2 100%)" }}>
        <span aria-hidden className="pointer-events-none absolute left-1/2 top-1/2 h-[78%] w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-dashed border-[#D9C3A5]/70" />
        <span className="block aspect-square w-[58%] max-w-[300px]"><Img src={HERO_IMAGES[0]} alt="جعبه‌ی هدیه‌ی آجیل" /></span>
        <span className="block aspect-square w-[36%] max-w-[210px] self-end"><Img src={HERO_IMAGES[1]} alt="جعبه‌ی کادویی آجیل" /></span>
      </div>
    </section>
  );
}

// ── Service shortcuts ──────────────────────────────────────────────────────
const SERVICES: [typeof Gift, string, string][] = [
  [Building2, "خرید سازمانی", "/org"], [Boxes, "پک‌ساز", "/pack-builder"], [Gift, "هدیه‌ی کارکنان", "/packs/employee-gift"], [Wallet, "کیف پول رفاهی", "/benefits"],
  [ClipboardList, "درخواست قیمت عمده", "/requests/new"], [Coins, "وامبی", "/vambi"], [Store, "غرفه‌ها", "/shops"], [Truck, "پیگیری سفارش", "/orders"],
];
function Services() {
  return (
    <Card label="خدمات" className="grid grid-cols-4 gap-y-5 md:grid-cols-8 md:[&>a+a]:border-r md:[&>a+a]:border-[#EDF0F4]">
      {SERVICES.map(([Icon, label, href], i) => (
        <Link key={href} href={href} className="group flex flex-col items-center gap-2.5 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full ring-4 ring-[#FFFFFF] shadow-[0_0_0_1px_#E3E8EF] transition group-hover:scale-105 md:h-[68px] md:w-[68px]" style={{ background: i % 2 ? C.orangeT : C.blueL, color: i % 2 ? C.orange : C.blue }}><Icon className="h-7 w-7" strokeWidth={1.8} /></span>
          <span className="text-xs font-semibold leading-5 md:text-sm" style={{ color: C.ink }}>{label}</span>
        </Link>))}
    </Card>
  );
}

// ── Organization prices strip ──────────────────────────────────────────────
function OrgPrices({ items }: { items: Product[] | null }) {
  if (items && !items.length) return null;
  return (
    <section className="relative overflow-hidden rounded-[22px] p-4 shadow-[0_10px_28px_rgba(224,80,31,0.25)] md:p-5" style={{ background: `linear-gradient(135deg, #F06A33 0%, ${C.orange} 55%, #C9431A 100%)` }} aria-labelledby="org-prices">
      <span aria-hidden className="pointer-events-none absolute -left-10 -top-10 h-40 w-40 rounded-full border-[14px] border-white/10" />
      <div className="mb-4 flex items-center justify-between gap-3">
        <div><h2 id="org-prices" className="text-xl font-black text-white md:text-[26px]">قیمت سازمانی</h2>
          <p className="mt-0.5 text-xs font-medium text-[#FFE9DF] md:text-sm">قیمت قراردادی سازمان شما پس از ورود نمایش داده می‌شود</p></div>
        <Link href="/business/catalog" className="inline-flex min-h-11 shrink-0 items-center gap-1 text-sm font-semibold text-white">مشاهده‌ی همه<ArrowLeft className="h-4 w-4" /></Link>
      </div>
      <div className="-mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-1 md:overflow-visible">
        {(items ?? Array.from({ length: 6 }, () => null)).map((p, i) => (
          <Link key={p?.id ?? i} href={p ? `/products/${p.slug}` : "#"} className="flex w-40 shrink-0 snap-start flex-col items-center gap-1.5 rounded-[14px] bg-[#FFFFFF] p-2.5 text-center shadow-[0_4px_12px_rgba(0,0,0,0.12)] transition hover:-translate-y-0.5 md:w-[calc((100%-60px)/6)]">
            <span className="block aspect-square w-full rounded-[10px] bg-[#F7F9FC] p-2"><Img src={p?.image_url} alt={p?.name} /></span>
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
        <Link key={c?.cat.slug ?? i} href={c ? `/category/${c.cat.slug}` : "#"} className="relative flex h-40 overflow-hidden rounded-[18px] border border-[#FFFFFF]/70 p-4 shadow-[0_1px_2px_rgba(16,24,40,0.05),0_6px_16px_rgba(16,24,40,0.07)] transition hover:-translate-y-0.5 md:h-44" style={{ background: TILE_BG[i] }}>
          <span aria-hidden className="absolute -bottom-8 -left-8 h-36 w-36 rounded-full bg-[#FFFFFF]/70 md:h-44 md:w-44" />
          <span className="z-10 flex h-full flex-col justify-between">
            <b className="line-clamp-2 max-w-[9rem] text-base font-black leading-7 md:text-xl" style={{ color: C.navy }}>{c?.cat.name ?? ""}</b>
            <span className="inline-flex w-fit items-center gap-1 rounded-full bg-[#FFFFFF] px-3 py-1.5 text-xs font-bold shadow-sm" style={{ color: C.navy }}>مشاهده‌ی کالاها<ArrowLeft className="h-3.5 w-3.5" /></span>
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
          <Link key={c?.cat.slug ?? i} href={c ? `/category/${c.cat.slug}` : "#"} className="group flex flex-col items-center gap-1.5 text-center">
            <span className="mb-1 flex aspect-square w-full max-w-[132px] items-center justify-center overflow-hidden rounded-full border-4 border-[#FFFFFF] p-4 shadow-[0_0_0_1px_#E3E8EF,0_6px_14px_rgba(16,24,40,0.08)] transition group-hover:shadow-[0_0_0_2px_#034EA2,0_8px_18px_rgba(3,78,162,0.15)]" style={{ background: "radial-gradient(circle at 50% 35%, #FFFFFF 0%, #EEF3F9 75%)" }}>
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
          <Link key={p?.id ?? i} href={p ? `/products/${p.slug}` : "#"} className={`flex items-center gap-3 rounded-[14px] p-3 ${TILE}`}>
            <span className="min-w-0 flex-1">
              <b className="line-clamp-2 text-sm leading-6" style={{ color: C.ink }}>{p?.name ?? " "}</b>
              <span className="block text-xs" style={{ color: C.gray }}>{p?.brand ?? ""}</span>
              <span className="mt-1 block text-[15px] font-black tabular-nums" style={{ color: C.ink }}>{p ? priceLabel(p) : ""}</span>
            </span>
            <span className="block h-24 w-24 shrink-0 rounded-[12px] bg-[#F7F9FC] p-1.5"><Img src={p?.image_url} alt={p?.name} /></span>
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
          <Link key={b.name} href={`/search?brand=${encodeURIComponent(b.name)}`} className={`flex flex-col items-center gap-1.5 rounded-[14px] px-1 py-3 text-center md:px-2 md:py-4 ${TILE}`}>
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
    <section className="relative flex flex-col gap-4 overflow-hidden rounded-[20px] border border-[#CFE0F5] p-5 shadow-[0_6px_18px_rgba(3,78,162,0.08)] md:flex-row md:items-center md:justify-between md:px-8" style={{ background: "linear-gradient(90deg, #EAF2FC 0%, #DCEAFB 100%)" }}>
      <span aria-hidden className="pointer-events-none absolute -left-12 -bottom-16 h-44 w-44 rounded-full border-[16px] border-[#034EA2]/[0.06]" />
      <span className="flex items-center gap-4">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[#FFFFFF] shadow-[0_0_0_6px_rgba(255,255,255,0.6)]" style={{ color: C.blue }}><Store className="h-8 w-8" strokeWidth={1.8} /></span>
        <span><b className="block text-xl font-black md:text-[22px]" style={{ color: C.navy }}>در شصت‌آنلاین بفروشید</b>
          <span className="mt-1 block text-sm md:text-[15px]" style={{ color: C.gray }}>غرفه بگیرید و به اعضای سازمان‌های طرف قرارداد بفروشید</span></span>
      </span>
      <Link href="/sell" className="relative inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl px-6 text-base font-bold text-white" style={{ background: C.blue }}>درخواست غرفه<ArrowLeft className="h-5 w-5" /></Link>
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
  // Compact band (user, 2026-11-10: the full pack cards took too much of the homepage). The full cards
  // stay on /pack-builder; here each pack is one small tile linking to its page.
  return (
    <section id="packs" className="scroll-mt-28 grid gap-4 rounded-[20px] border border-[#D6E4D9] p-4 shadow-[0_6px_18px_rgba(16,24,40,0.06)] md:grid-cols-[minmax(0,350px)_1fr] md:items-center md:p-5" style={{ background: UI.mint }}>
      <div className="flex flex-col gap-2">
        <p className="text-xs font-bold" style={{ color: ACCENT }}>پک‌ساز شصت‌آنلاین</p>
        <H2>بودجه یا نیازت را بگو؛<br className="hidden md:block" /> پک مناسب بساز.</H2>
        <div className="mt-1 flex flex-wrap items-center gap-x-3.5 gap-y-1 text-sm font-bold" style={{ color: UI.ink }}>
          <Link href="/pack-builder" className="inline-flex h-11 items-center justify-center rounded-xl px-4 text-sm font-bold text-[#FFFFFF]" style={{ background: UI.ink }}>شروع پک‌سازی</Link>
          <Link href="/pack-builder?mode=budget" className="inline-flex min-h-11 items-center gap-1">بر اساس بودجه <ArrowLeft className="h-4 w-4" /></Link>
          <Link href="/pack-builder?mode=scratch" className="inline-flex min-h-11 items-center gap-1">ساخت دستی <ArrowLeft className="h-4 w-4" /></Link>
        </div>
      </div>
      <div className="-mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-1 md:grid md:grid-cols-3 md:overflow-visible">
        {(shown ?? [null, null, null]).map((p, i) => {
          if (!p) return <span key={i} className="h-28 w-64 shrink-0 animate-pulse rounded-2xl bg-white/70 md:w-auto" />;
          const pics = packImages(p, good, 3, used);
          return (
            <Link key={p.slug} href={`/packs/${p.slug}`} className="flex w-64 shrink-0 snap-start items-center gap-3 rounded-2xl border border-[#E3E8EF] bg-[#FFFFFF] p-3 transition hover:-translate-y-0.5 hover:shadow-md md:w-auto">
              <span className="min-w-0 flex-1">
                <b className="line-clamp-1 text-sm font-black" style={{ color: UI.ink }}>{p.title_fa}</b>
                <span className="mt-0.5 block line-clamp-1 text-xs" style={{ color: UI.muted }}>{p.purpose_fa}</span>
                <span className="mt-1 block text-xs font-bold" style={{ color: UI.muted }}>{toPersianNum(p.item_count)} نوع کالا</span>
              </span>
              <span className="flex h-16 w-24 shrink-0 items-center justify-center gap-1 rounded-xl p-1" style={{ background: UI.warm }}>
                {pics.length ? pics.slice(0, 2).map((src) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={src} src={src} alt="" loading="lazy" className="h-full w-1/2 rounded-lg bg-[#FFFFFF] object-contain p-0.5" />))
                  : <Boxes className="h-7 w-7" style={{ color: UI.muted }} strokeWidth={1.4} />}
              </span>
            </Link>);
        })}
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
  return <div style={{ background: "linear-gradient(180deg, #EAF0F7 0%, #F3F5F8 420px)" }}><div className="mx-auto flex w-full max-w-[1280px] flex-col gap-5 px-4 py-4 md:px-8 md:py-6" dir="rtl">{order.map(key=><Fragment key={key}>{sections[key]}</Fragment>)}</div></div>;
}
