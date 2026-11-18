"use client";

// Homepage — faithful rebuild of Google Stitch screen 30 «خانه» (desktop 1440) and screen 16 (mobile 390),
// owner instruction 2026-11-18. Structure, spacing, tokens (st-*) and Material Symbols icons follow the Stitch
// markup; every product, pack, category, price and photo comes from the live API:
//   products  → GET /storefront/products (catalog.list, family grouping) — per category when a chip is picked
//   packs     → GET /storefront/packs + /storefront/packs/:slug (loadPackDetails)
//   chips     → GET /storefront/taxonomy (top-level nodes with real products)
//   hero copy → GET /content/pages/homepage (content panel block "hero"), else the defaults below
// Stitch's sample products, prices, people, organizations and photos are not shipped. Claims Stitch makes that
// the platform cannot back (30-day credit terms, 7-day guarantee, dedicated fleet…) are replaced by real
// features with links. Prices follow the existing rule: verified price, otherwise «قیمت با استعلام».
// Content-panel keys kept: hero, categories (chips), packs, today (product grid), why (value strip).

import type { PageContent } from "@/lib/content-types";
import { apiRequest, catalog } from "@/lib/api";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useGoodImages } from "@/lib/imageQuality";
import type { PackDetail } from "@/lib/storefront";
import type { Product } from "@/lib/types";
import { cn, toPersianNum } from "@/lib/utils";
import { loadPackDetails, packImages } from "@/components/packs/PackCard";
import { useTaxonomy } from "@/components/layout/MegaMenu";

const W = "mx-auto w-full max-w-[1440px] px-st-margin md:px-st-margin-md xl:px-st-margin-lg";
const Icon = ({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) =>
  <span aria-hidden className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;
const num = (minor: number) => toPersianNum(Math.round(minor / 10).toLocaleString("en-US"));
const realImg = (u?: string | null) => !!u && !u.includes("picsum.photos");
const discountPct = (p: Product) => (p.purchasable && p.price_minor && p.original_price_minor && p.original_price_minor > p.price_minor
  ? Math.round((1 - p.price_minor / p.original_price_minor) * 100) : 0);

function Photo({ src, alt = "", className = "" }: { src?: string | null; alt?: string; className?: string }) {
  // Real catalog photo, or an honest empty frame (never a stock/placeholder photo).
  // eslint-disable-next-line @next/next/no-img-element
  return realImg(src) ? <img src={src!} alt={alt} loading="lazy" className={cn("h-full w-full object-contain mix-blend-multiply transition-transform duration-300 group-hover:scale-105", className)} />
    : <span className="flex h-full w-full items-center justify-center text-st-outline-variant"><Icon name="image" className="text-[40px]" /></span>;
}

// ── Data ────────────────────────────────────────────────────────────────────
const listCache = new Map<string, Promise<Product[]>>();
function useProducts(category: string | null) {
  const [items, setItems] = useState<Product[] | null>(null);
  useEffect(() => {
    let off = false; setItems(null);
    const key = category ?? "*";
    if (!listCache.has(key)) listCache.set(key, catalog.list({ page: 1, page_size: 48, group: "family", sort: "relevance", ...(category ? { category } : {}) })
      .then((r) => r.items).catch(() => { listCache.delete(key); return []; }));
    listCache.get(key)!.then((r) => !off && setItems(r));
    return () => { off = true; };
  }, [category]);
  return items;
}
/** Products whose photo passes the quality gate first, one per photo; then the rest (honest empty frame). */
function useShowcase(items: Product[] | null, limit: number): Product[] | null {
  const good = useGoodImages((items ?? []).map((p) => p.image_url));
  return useMemo(() => {
    if (!items) return null;
    if (items.some((p) => realImg(p.image_url)) && !good) return null;
    const seen = new Set<string>(), withImg: Product[] = [], rest: Product[] = [];
    for (const p of items) {
      if (p.image_url && good?.has(p.image_url) && !seen.has(p.image_url)) { seen.add(p.image_url); withImg.push(p); }
      else if (!realImg(p.image_url)) rest.push(p);
    }
    return [...withImg, ...rest].slice(0, limit);
  }, [items, good, limit]);
}

// ── Hero (screen 30 desktop / screen 16 mobile banner) ─────────────────────
type HeroContent = { title?: string; body?: string; link?: string; button_label?: string; image_url?: string };
const HERO_IMAGE = "/images/catalog/33c657bae8d646702dc50726178d374197ef7aad2114a858bb5b0e51c129e4c2.jpg"; // real catalog photo (gift box)
const KPIS: [string, string, string, string][] = [
  ["receipt_long", "پیش‌فاکتور رسمی", "برای خرید سازمانی و عمده", "/me/proformas"],
  ["verified", "قیمت تأییدشده", "قیمت ثبت‌شده یا «با استعلام»", "/help/buying"],
  ["credit_score", "اعتبار سازمانی", "برای سازمان‌های طرف قرارداد", "/org"],
];
function Hero({ content }: { content?: HeroContent }) {
  const title = content?.title || "تأمین هوشمند، اختصاصی و شفاف نیازهای سازمانی و خانوار";
  const body = content?.body || "از پک‌های پذیرایی و هدیه‌ی کارکنان تا سبد اقلام مصرفی ماهانه؛ خرید از کاتالوگ واقعی تأمین‌کنندگان با قیمت مشخص و پیش‌فاکتور رسمی برای سازمان‌ها.";
  const link = content?.link || "/packs", label = content?.button_label || "مشاهده پک‌های سازمانی";
  return <>
    {/* Desktop */}
    <section className="relative hidden w-full overflow-hidden bg-st-surface-container-lowest md:block" aria-labelledby="home-hero">
      <div className="pointer-events-none absolute -left-20 -top-32 h-96 w-96 rounded-full bg-st-secondary-fixed/25 blur-3xl" />
      <div className="pointer-events-none absolute -right-24 top-1/2 h-[32rem] w-[32rem] rounded-full bg-st-tertiary-fixed/30 blur-3xl" />
      <div className={cn(W, "pb-16 pt-st-space-xl")}>
        <div className="grid grid-cols-1 items-center gap-st-gutter-lg lg:grid-cols-12">
          <div className="z-10 flex flex-col gap-st-space-lg lg:col-span-7">
            <div className="inline-flex w-fit items-center gap-st-space-xs rounded-full bg-st-surface-container-low px-st-space-md py-st-space-xs text-st-secondary shadow-sm">
              <span className="h-2 w-2 animate-pulse rounded-full bg-st-on-tertiary-container" />
              <span className="text-st-on-surface">بازار تأمین کالای سازمانی و خانگی شصت‌آنلاین</span>
            </div>
            <div className="flex flex-col gap-st-space-xs">
              <h1 id="home-hero" className="whitespace-pre-line font-bold tracking-tight text-st-primary">{title}</h1>
              <p className="max-w-2xl leading-relaxed text-st-on-surface-variant">{body}</p>
            </div>
            <div className="flex flex-wrap items-center gap-st-space-md pt-st-space-xs">
              <Link href={link} className="inline-flex h-12 items-center justify-center gap-st-space-sm rounded-full bg-st-primary-container px-st-space-xl text-white shadow-sm transition-all hover:bg-st-secondary">
                <span>{label}</span><Icon name="arrow_forward" className="-scale-x-100 text-[18px]" /></Link>
              <Link href="/business/catalog" className="inline-flex h-12 items-center justify-center gap-st-space-sm rounded-full bg-st-surface-container-lowest px-st-space-xl text-st-primary shadow-sm transition-all hover:bg-st-surface-container-low">
                <Icon name="menu_book" className="text-[18px]" /><span>کاتالوگ تأمین سازمانی</span></Link>
            </div>
            <div className="mt-st-space-md grid grid-cols-3 gap-st-gutter pt-st-space-md">
              {KPIS.map(([icon, head, sub, href]) => (
                <Link key={head} href={href} className="flex items-center gap-st-space-sm rounded-xl bg-st-surface-container-low/70 p-st-space-sm transition-colors hover:bg-st-surface-container-low">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-st-surface-container-lowest text-st-secondary shadow-sm"><Icon name={icon} className="text-[20px]" /></span>
                  <span className="flex flex-col"><span className="text-st-on-surface">{head}</span><span className="text-st-on-surface-variant">{sub}</span></span>
                </Link>))}
            </div>
          </div>
          <div className="relative flex justify-center lg:col-span-5">
            <Link href="/packs/employee-gift" className="group relative block aspect-[4/5] w-full max-w-md overflow-hidden rounded-3xl bg-st-surface-container shadow-xl">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={content?.image_url || HERO_IMAGE} alt="جعبه‌ی هدیه‌ی کارکنان" className="h-full w-full object-cover" />
              <span className="absolute inset-0 bg-gradient-to-t from-[#00111a]/80 via-[#00111a]/20 to-transparent" />
              <span className="absolute inset-x-6 bottom-6 flex items-center justify-between gap-st-space-sm rounded-2xl bg-st-surface-container-lowest/95 p-st-space-md shadow-md backdrop-blur-md">
                <span className="flex items-center gap-st-space-sm">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name="stars" className="text-[22px]" /></span>
                  <span className="flex flex-col"><span className="font-bold text-st-primary">هدیه‌ی کارکنان، به تعداد</span><span className="text-st-on-surface-variant">جعبه‌های آجیل و خشکبار با بسته‌بندی کادویی</span></span>
                </span>
                <span className="shrink-0 rounded-full bg-st-tertiary-fixed px-st-space-sm py-1 font-bold text-st-on-tertiary-fixed">هدیه پایان سال</span>
              </span>
            </Link>
          </div>
        </div>
      </div>
    </section>
    {/* Mobile banner */}
    <section className="mt-st-space-md px-st-margin md:hidden" aria-label="معرفی">
      <div className="relative flex min-h-[170px] flex-col justify-between overflow-hidden rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
        <div className="pointer-events-none absolute -bottom-8 -left-6 h-44 w-44 rounded-full bg-st-secondary-fixed/40 blur-2xl" />
        <div className="pointer-events-none absolute left-4 top-4 select-none text-st-outline-variant/30">
          <svg fill="none" height="90" viewBox="0 0 100 100" width="90" aria-hidden><circle cx="50" cy="50" r="45" stroke="currentColor" strokeDasharray="4 6" strokeWidth="1.5" /><circle cx="50" cy="50" r="28" stroke="currentColor" strokeWidth="1" /><path d="M50 15V85M15 50H85" stroke="currentColor" strokeWidth="1" /></svg>
        </div>
        <div className="relative z-10 flex max-w-[85%] flex-col">
          <div className="mb-1.5 flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-st-on-tertiary-container" /><span className="text-st-label-sm font-medium tracking-wide text-st-secondary">ویژه سازمان‌ها و شرکت‌ها</span></div>
          <h1 className="text-st-headline-lg-mobile font-bold leading-snug text-st-primary-container">{content?.title || "تأمین هوشمند نیازهای خانه و سازمان"}</h1>
          <p className="mt-1 text-st-body-sm leading-relaxed text-st-on-surface-variant">{content?.body || "پک‌های آماده، خرید عمده و پیش‌فاکتور رسمی برای کارکنان و سازمان‌ها."}</p>
        </div>
        <div className="relative z-10 mt-st-space-md flex items-center justify-between gap-st-space-sm">
          <Link href={link} className="flex h-10 items-center gap-1.5 rounded-full bg-st-secondary px-5 text-st-label-lg text-st-on-secondary shadow-sm transition-opacity hover:opacity-95">
            <span>{content?.button_label || "مشاهده بسته‌ها"}</span><Icon name="arrow_forward" className="-scale-x-100 text-[16px]" /></Link>
          <Link href="/me/proformas" className="text-st-label-sm text-st-outline">پیش‌فاکتور رسمی سازمانی</Link>
        </div>
      </div>
    </section>
  </>;
}

// ── Category chips (sticky on desktop, horizontal scroll on mobile) ────────
function Chips({ cats, value, onChange }: { cats: { slug: string; name: string }[] | null; value: string | null; onChange: (v: string | null) => void }) {
  if (cats && !cats.length) return null;
  const all = [{ slug: null as string | null, name: "همه دسته‌ها", short: "همه" }, ...(cats ?? []).map((c) => ({ slug: c.slug as string | null, name: c.name, short: c.name }))];
  return <>
    <section className="sticky top-28 z-40 hidden w-full bg-st-surface-container-lowest shadow-sm md:block" aria-label="دسته‌بندی‌ها">
      <div className={cn(W, "py-st-space-sm")}>
        <div className="no-scrollbar flex items-center gap-st-space-sm overflow-x-auto py-1">
          {all.map((c) => <button key={c.slug ?? "all"} type="button" onClick={() => onChange(c.slug)} aria-pressed={value === c.slug}
            className={cn("h-9 shrink-0 rounded-full px-st-space-lg transition-all", value === c.slug ? "bg-st-primary text-st-on-primary shadow-sm" : "bg-st-surface-container-low text-st-on-surface-variant hover:bg-st-surface-container hover:text-st-on-surface")}>{c.name}</button>)}
          {!cats && Array.from({ length: 5 }, (_, i) => <span key={i} className="h-9 w-32 shrink-0 animate-pulse rounded-full bg-st-surface-container-low" />)}
        </div>
      </div>
    </section>
    <section className="mt-st-space-sm md:hidden" aria-label="دسته‌بندی‌ها">
      <div className="no-scrollbar flex items-center gap-2 overflow-x-auto px-st-margin py-1">
        {all.map((c) => <button key={c.slug ?? "all"} type="button" onClick={() => onChange(c.slug)} aria-pressed={value === c.slug}
          className={cn("flex h-8 shrink-0 items-center justify-center rounded-full px-4 text-st-label-md shadow-sm transition-all", value === c.slug ? "bg-st-primary-container text-white" : "bg-st-surface-container-lowest text-st-on-surface-variant hover:text-st-primary")}>{c.short}</button>)}
      </div>
    </section>
  </>;
}

// ── Packs (3 showcase cards desktop / horizontal list mobile) ──────────────
const FEATURED = ["employee-gift", "gathering-tea", "family-daily"];
function Packs() {
  const [packs, setPacks] = useState<PackDetail[] | null>(null);
  useEffect(() => { let off = false; loadPackDetails().then((p) => !off && setPacks(p)).catch(() => !off && setPacks([])); return () => { off = true; }; }, []);
  const shown = useMemo(() => {
    if (!packs) return null;
    const real = packs.filter((p) => p.items.length);
    const first = FEATURED.map((s) => real.find((p) => p.slug === s)).filter((p): p is PackDetail => !!p);
    return [...first, ...real.filter((p) => !first.includes(p))].slice(0, 3);
  }, [packs]);
  const good = useGoodImages((shown ?? []).flatMap((p) => [p.image_url, ...p.items.map((i) => i.image_url)]));
  if (shown && !shown.length) return null;
  const used = new Set<string>();
  const cards = (shown ?? [null, null, null]).map((p, i) => {
    if (!p) return { key: `s${i}`, p: null, img: null };
    const img = p.image_url && good?.has(p.image_url) ? p.image_url : packImages(p, good, 1, used)[0] ?? null;
    return { key: p.slug, p, img };
  });
  const meta = (p: PackDetail): [string, string] => p.min_order_qty > 1 ? ["verified", `حداقل سفارش: ${toPersianNum(p.min_order_qty)} بسته`] : ["inventory_2", `${toPersianNum(p.item_count)} نوع کالا در پک`];
  const quote = (p: PackDetail) => p.availability !== "purchasable" || !p.price_minor;
  return <>
    <section className={cn(W, "hidden py-st-space-xl md:block")} aria-labelledby="home-packs">
      <div className="mb-st-space-lg flex items-end justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-st-space-xs text-st-secondary"><Icon name="inventory_2" className="text-[18px]" /><span>ویژه سازمان‌ها، شرکت‌ها و نهادها</span></div>
          <h2 id="home-packs" className="font-bold text-st-primary">پک‌های سازمانی و رفاهی کارکنان</h2>
        </div>
        <Link href="/packs" className="inline-flex items-center gap-st-space-xs text-st-secondary transition-colors hover:text-st-primary"><span>مشاهده همه پک‌ها</span><Icon name="arrow_forward" className="-scale-x-100 text-[16px]" /></Link>
      </div>
      <div className="grid grid-cols-1 gap-st-gutter-lg md:grid-cols-3">
        {cards.map(({ key, p, img }) => !p ? <span key={key} className="h-[440px] animate-pulse rounded-2xl bg-st-surface-container-lowest shadow-sm" /> : (
          <article key={key} className="group flex flex-col overflow-hidden rounded-2xl bg-st-surface-container-lowest shadow-sm transition-all duration-300 hover:shadow-md">
            <Link href={`/packs/${p.slug}`} className="relative block h-64 w-full overflow-hidden bg-st-surface-container">
              <Photo src={img} alt={p.title_fa} className="p-st-space-md" />
              <span className="absolute right-4 top-4 rounded-full bg-st-primary px-st-space-sm py-1 text-st-on-primary">{p.kind_fa}</span>
              {(p.tier_fa || p.customizable) && <span className="absolute left-4 top-4 rounded-full bg-st-tertiary-fixed px-st-space-sm py-1 font-bold text-st-on-tertiary-fixed">{p.tier_fa || "قابل سفارشی‌سازی"}</span>}
            </Link>
            <div className="flex flex-1 flex-col justify-between gap-st-space-md p-st-space-lg">
              <div className="flex flex-col gap-st-space-xs">
                <h3 className="font-bold text-st-primary"><Link href={`/packs/${p.slug}`}>{p.title_fa}</Link></h3>
                <p className="line-clamp-2 text-st-on-surface-variant">{p.description_fa || p.purpose_fa}</p>
              </div>
              <div className="flex flex-col gap-st-space-sm pt-st-space-sm">
                <div className="flex items-center justify-between text-st-on-surface-variant">
                  <span className="flex items-center gap-1"><Icon name={meta(p)[0]} className="text-[16px] text-st-secondary" />{meta(p)[1]}</span>
                  {p.packaging_fa && <span className="truncate text-st-outline">{p.packaging_fa}</span>}
                </div>
                <div className="flex items-center justify-between gap-st-space-sm">
                  {p.price_minor ? <div className="flex items-baseline gap-1"><span className="font-bold text-st-primary">{num(p.price_minor)}</span><span className="text-st-on-surface-variant">تومان</span></div>
                    : <span className="font-bold text-st-primary">قیمت با استعلام</span>}
                  <Link href={`/packs/${p.slug}`} className="flex h-10 items-center gap-st-space-xs rounded-xl bg-st-primary px-st-space-md text-st-on-primary transition-colors hover:bg-st-secondary">
                    <Icon name={quote(p) ? "request_quote" : "add_shopping_cart"} className="text-[18px]" /><span>{quote(p) ? "ثبت پیش‌فاکتور" : "مشاهده و سفارش"}</span></Link>
                </div>
              </div>
            </div>
          </article>))}
      </div>
    </section>
    <section className="mt-st-space-lg flex flex-col md:hidden" aria-label="پک‌های سازمانی و رفاهی کارکنان">
      <div className="mb-st-space-sm flex items-center justify-between px-st-margin">
        <div className="flex items-center gap-2"><span className="h-4 w-1 rounded-full bg-st-primary-container" /><h2 className="text-st-title-lg font-semibold text-st-primary-container">پک‌های سازمانی و رفاهی کارکنان</h2></div>
        <Link href="/packs" className="flex items-center gap-0.5 text-st-label-md text-st-secondary hover:text-st-primary-container"><span>مشاهده همه</span><Icon name="arrow_forward_ios" className="-scale-x-100 text-[14px]" /></Link>
      </div>
      <div className="no-scrollbar flex gap-st-space-md overflow-x-auto px-st-margin py-1">
        {cards.map(({ key, p, img }) => !p ? <span key={key} className="h-[330px] w-[290px] shrink-0 animate-pulse rounded-2xl bg-st-surface-container-lowest shadow-sm" /> : (
          <article key={key} className="group flex w-[290px] shrink-0 flex-col justify-between rounded-2xl bg-st-surface-container-lowest p-st-space-sm shadow-sm">
            <Link href={`/packs/${p.slug}`} className="relative mb-st-space-sm block h-44 overflow-hidden rounded-xl bg-st-surface-container-low">
              <Photo src={img} alt={p.title_fa} className="p-st-space-sm" />
              {(p.tier_fa || p.customizable) && <span className="absolute right-2.5 top-2.5 rounded-full bg-st-on-tertiary-container px-2.5 py-1 text-st-label-sm font-bold text-white shadow-sm">{p.tier_fa || "سفارشی‌سازی"}</span>}
              <span className="absolute bottom-2.5 left-2.5 rounded-md bg-st-surface-container-lowest/90 px-2 py-0.5 text-st-label-sm font-medium text-st-primary-container backdrop-blur-md">{p.kind_fa}</span>
            </Link>
            <div className="flex flex-col px-st-space-xs">
              <h3 className="text-st-title-md font-bold leading-tight text-st-primary-container">{p.title_fa}</h3>
              <p className="mt-1 line-clamp-2 text-st-body-sm leading-relaxed text-st-on-surface-variant">{p.description_fa || p.purpose_fa}</p>
              <div className="mt-st-space-md flex items-baseline justify-between pt-st-space-xs">
                {p.price_minor ? <div className="flex items-baseline gap-1"><span className="text-st-title-lg font-bold text-st-primary-container">{num(p.price_minor)}</span><span className="text-st-label-sm font-normal text-st-on-surface-variant">تومان</span></div>
                  : <span className="text-st-title-md font-bold text-st-primary-container">قیمت با استعلام</span>}
                <Link href={`/packs/${p.slug}`} className="flex h-9 items-center gap-1 rounded-xl bg-st-surface-container-low px-3 text-st-label-md font-medium text-st-secondary transition-colors hover:bg-st-surface-container">
                  <Icon name={quote(p) ? "request_quote" : "add"} className="text-[16px]" /><span>{quote(p) ? "پیش‌فاکتور" : "مشاهده"}</span></Link>
              </div>
            </div>
          </article>))}
      </div>
    </section>
  </>;
}

// ── Product grid «کالاهای منتخب و روزمره» ─────────────────────────────────
function Price({ p, mobile = false }: { p: Product; mobile?: boolean }) {
  const pct = discountPct(p);
  if (!p.purchasable || !p.price_minor) return <div className="flex flex-col"><span className={cn("font-bold text-st-primary", mobile ? "text-st-body-md text-st-primary-container" : "")}>قیمت با استعلام</span></div>;
  return (
    <div className="flex flex-col">
      {pct > 0 ? <span className={cn("text-st-outline line-through", mobile && "text-[10px]")}>{num(p.original_price_minor!)}{mobile ? "" : " تومان"}</span> : mobile ? null : null}
      <div className={cn("flex items-baseline", mobile ? "gap-0.5" : "gap-1")}>
        {p.price_from && <span className={cn("text-st-on-surface-variant", mobile && "text-[10px]")}>از</span>}
        <span className={cn("font-bold", mobile ? "text-st-title-md text-st-primary-container" : "text-st-primary")}>{num(p.price_minor)}</span>
        <span className={cn("text-st-on-surface-variant", mobile && "text-[10px]")}>تومان</span>
      </div>
    </div>
  );
}
function ProductCard({ p }: { p: Product | null }) {
  if (!p) return <span className="h-[380px] animate-pulse rounded-2xl bg-st-surface-container-lowest shadow-sm" />;
  const pct = discountPct(p), href = `/products/${p.slug}`;
  return (
    <article className="group flex flex-col rounded-2xl bg-st-surface-container-lowest p-st-space-md shadow-sm transition-all hover:shadow-md">
      <Link href={href} className="relative mb-st-space-sm block aspect-square w-full overflow-hidden rounded-xl bg-st-surface">
        <Photo src={p.image_url} alt={p.name} className="p-st-space-sm" />
        {pct > 0 && <span className="absolute left-2 top-2 rounded-full bg-st-on-tertiary-container px-2 py-0.5 font-bold text-white">{toPersianNum(pct)}٪ تخفیف</span>}
        {p.brand && <span className="absolute bottom-2 right-2 max-w-[85%] truncate rounded-md bg-st-surface-container-lowest/90 px-2 py-0.5 text-st-on-surface backdrop-blur-sm">{p.brand}</span>}
      </Link>
      <div className="flex flex-1 flex-col justify-between">
        <div className="flex flex-col gap-1">
          {p.category?.name && <span className="text-st-outline">{p.category.name}</span>}
          <h3 className="line-clamp-2 font-bold leading-snug text-st-on-surface"><Link href={href}>{p.name}</Link></h3>
        </div>
        <div className="mt-st-space-md flex items-center justify-between pt-st-space-sm">
          <Price p={p} />
          <Link href={href} aria-label={`مشاهده و افزودن ${p.name} به سبد`} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-st-surface-container-low text-st-primary transition-colors hover:bg-st-primary hover:text-st-on-primary"><Icon name="add" className="text-[20px]" /></Link>
        </div>
      </div>
    </article>
  );
}
function ProductCardMobile({ p }: { p: Product | null }) {
  if (!p) return <span className="h-[260px] animate-pulse rounded-2xl bg-st-surface-container-lowest shadow-sm" />;
  const pct = discountPct(p), href = `/products/${p.slug}`;
  return (
    <article className="flex flex-col justify-between rounded-2xl bg-st-surface-container-lowest p-3 shadow-sm">
      <Link href={href} className="group relative mb-2.5 block aspect-square w-full overflow-hidden rounded-xl bg-st-surface-container-low">
        <Photo src={p.image_url} alt={p.name} className="p-1.5" />
        {pct > 0 && <span className="absolute right-2 top-2 rounded-full bg-st-on-tertiary-container px-1.5 py-0.5 text-[10px] font-bold text-white">{toPersianNum(pct)}٪</span>}
      </Link>
      <div className="flex flex-1 flex-col justify-between">
        <div>
          {!!p.review_count && !!p.rating && <div className="mb-1 flex items-center gap-1 text-st-outline">
            <Icon name="star" fill className="text-[14px] text-st-tertiary-fixed-dim" />
            <span className="text-[11px] text-st-on-surface-variant">{toPersianNum(p.rating.toFixed(1))}</span>
            <span className="text-[10px] text-st-outline">({toPersianNum(p.review_count)} نظر)</span></div>}
          <h3 className="line-clamp-2 text-st-body-md font-medium leading-snug text-st-primary-container"><Link href={href}>{p.name}</Link></h3>
        </div>
        <div className="mt-3 flex items-center justify-between pt-1">
          <Price p={p} mobile />
          <Link href={href} aria-label={`مشاهده و افزودن ${p.name} به سبد`} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-st-primary-container text-white shadow-sm transition-colors hover:bg-st-secondary"><Icon name="add" className="text-[18px]" /></Link>
        </div>
      </div>
    </article>
  );
}
function Today({ items, activeName }: { items: Product[] | null; activeName: string }) {
  if (items && !items.length) return (
    <section className={cn(W, "py-st-space-xl")}><p className="rounded-2xl bg-st-surface-container-lowest p-st-space-lg text-center text-st-on-surface-variant shadow-sm">در این دسته هنوز کالایی برای نمایش نیست.</p></section>);
  const list = items ?? Array.from({ length: 8 }, () => null);
  return <>
    <section className={cn(W, "hidden py-st-space-xl md:block")} aria-labelledby="home-today">
      <div className="mb-st-space-lg flex items-center justify-between">
        <div className="flex flex-col gap-1"><span className="text-st-secondary">عرضه مستقیم از تأمین‌کنندگان</span><h2 id="home-today" className="font-bold text-st-primary">کالاهای منتخب و روزمره</h2></div>
        <div className="hidden items-center gap-st-space-xs sm:flex"><span className="text-st-on-surface-variant">دسته‌بندی فعال:</span><span className="rounded-full bg-st-surface-container px-st-space-md py-1 font-bold text-st-on-surface">{activeName}</span></div>
      </div>
      <div className="grid grid-cols-1 gap-st-gutter sm:grid-cols-2 lg:grid-cols-4">{list.map((p, i) => <ProductCard key={p?.id ?? i} p={p} />)}</div>
    </section>
    <section className="mt-st-space-lg px-st-margin md:hidden" aria-label="کالاهای منتخب و روزمره">
      <div className="mb-st-space-sm flex items-center justify-between">
        <div className="flex items-center gap-2"><span className="h-4 w-1 rounded-full bg-st-primary-container" /><h2 className="text-st-title-lg font-semibold text-st-primary-container">کالاهای منتخب و روزمره</h2></div>
        <span className="text-st-label-sm text-st-outline">{activeName}</span>
      </div>
      <div className="grid grid-cols-2 gap-3">{list.slice(0, 6).map((p, i) => <ProductCardMobile key={p?.id ?? i} p={p} />)}</div>
    </section>
  </>;
}

// ── Value strip (desktop) / trust banner (mobile) ──────────────────────────
const WHY: [string, string, string, string][] = [
  ["receipt_long", "پیش‌فاکتور و فاکتور رسمی", "صدور پیش‌فاکتور رسمی برای خرید سازمانی و پیگیری آن از حساب کاربری.", "/me/proformas"],
  ["published_with_changes", "بازگشت و انصراف از خرید", "شرایط مرجوعی و انصراف از خرید، شفاف و مطابق قوانین تجارت الکترونیکی.", "/help/returns"],
  ["payments", "اعتبار و بودجه سازمانی", "خرید کارکنان با اعتبار تخصیص‌یافته از سوی سازمان طرف قرارداد.", "/org"],
  ["support_agent", "پشتیبانی خرید", "راهنمایی در انتخاب کالا، ثبت درخواست قیمت عمده و پیگیری سفارش.", "/contact"],
];
function Why() {
  return <>
    <section className="hidden w-full bg-st-surface-container-lowest py-st-space-xl md:block" aria-label="مزیت‌های خرید">
      <div className={W}>
        <div className="grid grid-cols-1 gap-st-gutter md:grid-cols-2 lg:grid-cols-4">
          {WHY.map(([icon, head, body, href]) => (
            <Link key={head} href={href} className="flex items-start gap-st-space-md rounded-2xl bg-st-surface-container-low/50 p-st-space-md transition-colors hover:bg-st-surface-container-low">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-st-surface-container-lowest text-st-primary shadow-sm"><Icon name={icon} className="text-[24px]" /></span>
              <span className="flex flex-col gap-1"><span className="font-bold text-st-primary">{head}</span><span className="leading-relaxed text-st-on-surface-variant">{body}</span></span>
            </Link>))}
        </div>
      </div>
    </section>
    <section className="mt-st-space-lg px-st-margin md:hidden">
      <Link href="/me/proformas" className="flex items-center gap-3 rounded-2xl bg-st-surface-container-low p-st-space-md shadow-sm">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-st-surface-container-lowest text-st-secondary shadow-sm"><Icon name="verified" className="text-[24px]" /></span>
        <span className="flex flex-col"><span className="text-st-body-md font-semibold text-st-primary-container">تأمین از غرفه‌ها و تأمین‌کنندگان معتبر</span><span className="text-st-body-sm text-st-on-surface-variant">پیش‌فاکتور رسمی برای خرید سازمانی و قیمت‌های تأییدشده</span></span>
      </Link>
    </section>
  </>;
}

export default function FigmaHome({ previewContent }: { previewContent?: PageContent } = {}) {
  const tree = useTaxonomy();
  const cats = useMemo(() => tree ? tree.slice().sort((a, b) => b.product_count - a.product_count).slice(0, 8).map((n) => ({ slug: n.slug, name: n.name_fa })) : null, [tree]);
  const [cat, setCat] = useState<string | null>(null);
  const raw = useProducts(cat);
  const shown = useShowcase(raw, 8);
  const [published, setPublished] = useState<PageContent | null>(null);
  useEffect(() => {
    if (previewContent) return;
    const c = new AbortController();
    apiRequest<{ content: PageContent }>("/content/pages/homepage", { signal: c.signal })
      .then((r) => { if (!c.signal.aborted && Array.isArray(r.content?.blocks)) setPublished(r.content); }).catch(() => {});
    return () => c.abort();
  }, [previewContent]);
  const configured = previewContent ?? published;
  // The content panel can hide a section it knows about; new sections are always shown.
  const hidden = new Set((configured?.blocks ?? []).filter((b) => b.type === "home_section" && !b.enabled).map((b) => b.key ?? ""));
  const hero = configured?.blocks.find((b) => b.key === "hero");
  const activeName = cat ? cats?.find((c) => c.slug === cat)?.name ?? "" : "همه دسته‌ها";
  return (
    <div className="flex w-full flex-col bg-st-background pb-st-space-lg md:pb-0" dir="rtl">
      {!hidden.has("hero") && <div className="order-2 md:order-1"><Hero content={hero} /></div>}
      {!hidden.has("categories") && <div className="order-1 md:sticky md:top-28 md:z-40 md:order-2"><Chips cats={cats} value={cat} onChange={setCat} /></div>}
      {!hidden.has("packs") && <div className="order-3"><Packs /></div>}
      {!hidden.has("today") && <div className="order-4"><Today items={shown} activeName={activeName} /></div>}
      {!hidden.has("why") && <div className="order-5"><Why /></div>}
    </div>
  );
}
