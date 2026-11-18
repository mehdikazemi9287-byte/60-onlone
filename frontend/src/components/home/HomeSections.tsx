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
import { categorySymbol } from "@/components/layout/categoryIcon";
import { Band, EmptyState, IconTile, Section, StatChip, ST_W, TONE_CYCLE } from "@/components/ui/st";

const W = ST_W;
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
// «ویترین سازمانی گرم»: navy panel + image card + stat chips (same copy, links and content-panel fields).
type HeroContent = { title?: string; body?: string; link?: string; button_label?: string; image_url?: string };
const HERO_IMAGE = "/images/catalog/33c657bae8d646702dc50726178d374197ef7aad2114a858bb5b0e51c129e4c2.jpg"; // real catalog photo (gift box)
const KPIS: [string, string, string, string][] = [
  ["receipt_long", "پیش‌فاکتور رسمی", "برای خرید سازمانی و عمده", "/me/proformas"],
  ["verified", "قیمت تأییدشده", "قیمت ثبت‌شده یا «با استعلام»", "/help/buying"],
  ["credit_score", "اعتبار سازمانی", "برای سازمان‌های طرف قرارداد", "/org"],
];
const NavyDecor = () => <>
  <span aria-hidden className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-st-secondary/40 blur-3xl" />
  <span aria-hidden className="pointer-events-none absolute -bottom-28 right-1/3 h-64 w-64 rounded-full bg-st-accent/20 blur-3xl" />
  <span aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:radial-gradient(#fff_1px,transparent_1px)] [background-size:18px_18px]" />
</>;
function Hero({ content }: { content?: HeroContent }) {
  const title = content?.title || "تأمین هوشمند، اختصاصی و شفاف نیازهای سازمانی و خانوار";
  const body = content?.body || "از پک‌های پذیرایی و هدیه‌ی کارکنان تا سبد اقلام مصرفی ماهانه؛ خرید از کاتالوگ واقعی تأمین‌کنندگان با قیمت مشخص و پیش‌فاکتور رسمی برای سازمان‌ها.";
  const link = content?.link || "/packs", label = content?.button_label || "مشاهده پک‌های سازمانی";
  return <>
    {/* Desktop */}
    <section className={cn(W, "hidden pt-5 md:block")} aria-labelledby="home-hero">
      <div className="relative overflow-hidden rounded-3xl bg-st-navy text-white shadow-st-raise">
        <NavyDecor />
        <div className="relative grid grid-cols-12 items-center gap-6 p-8 lg:p-10">
          <div className="col-span-12 flex flex-col gap-5 lg:col-span-7">
            <span className="inline-flex w-fit items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-st-label-md text-st-on-navy-muted ring-1 ring-white/15">
              <span className="h-2 w-2 animate-pulse rounded-full bg-st-accent" />بازار تأمین کالای سازمانی و خانگی شصت‌آنلاین</span>
            <div className="flex flex-col gap-2">
              <h1 id="home-hero" className="whitespace-pre-line text-st-headline-lg font-extrabold leading-[1.45] text-white xl:text-[32px]">{title}</h1>
              <p className="max-w-2xl text-st-body-md leading-7 text-st-on-navy-muted">{body}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Link href={link} className="inline-flex h-11 items-center gap-2 rounded-full bg-st-accent px-6 text-st-label-lg font-bold text-white shadow-[0_10px_24px_-10px_rgb(255_122_0/0.8)] transition-transform hover:-translate-y-0.5">
                <span>{label}</span><Icon name="arrow_back" className="text-[18px]" /></Link>
              <Link href="/business/catalog" className="inline-flex h-11 items-center gap-2 rounded-full bg-white/10 px-5 text-st-label-lg font-semibold text-white ring-1 ring-white/20 transition-colors hover:bg-white/20">
                <Icon name="menu_book" className="text-[18px]" /><span>کاتالوگ تأمین سازمانی</span></Link>
            </div>
            <div className="grid grid-cols-3 gap-2 pt-1">
              {KPIS.map(([icon, head, sub, href]) => <StatChip key={head} icon={icon} value={head} label={sub} href={href} onNavy />)}
            </div>
          </div>
          <div className="col-span-12 lg:col-span-5">
            <Link href="/packs/employee-gift" className="group relative mx-auto block aspect-[5/4] w-full max-w-md overflow-hidden rounded-2xl bg-white p-2 shadow-2xl ring-1 ring-white/20 lg:rotate-[-1.5deg] lg:transition-transform lg:hover:rotate-0">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={content?.image_url || HERO_IMAGE} alt="جعبه‌ی هدیه‌ی کارکنان" className="h-full w-full rounded-xl object-cover" />
              <span className="absolute inset-x-4 bottom-4 flex items-center justify-between gap-2 rounded-xl bg-white/95 p-3 shadow-lg backdrop-blur-md">
                <span className="flex items-center gap-2">
                  <IconTile icon="stars" tone="accent" size="sm" />
                  <span className="flex flex-col leading-tight"><span className="text-st-label-lg font-bold text-[#112D46]">هدیه‌ی کارکنان، به تعداد</span><span className="text-st-label-sm text-[#4A5765]">جعبه‌های آجیل و خشکبار با بسته‌بندی کادویی</span></span>
                </span>
                <span className="shrink-0 rounded-full bg-st-accent px-2.5 py-1 text-st-label-sm font-bold text-white">هدیه پایان سال</span>
              </span>
            </Link>
          </div>
        </div>
      </div>
    </section>
    {/* Mobile banner */}
    <section className="mt-3 px-4 md:hidden" aria-label="معرفی">
      <div className="relative overflow-hidden rounded-2xl bg-st-navy p-4 text-white shadow-st-raise">
        <NavyDecor />
        <div className="relative flex gap-3">
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="mb-1 flex items-center gap-1.5 text-st-label-sm text-st-on-navy-muted"><span className="h-1.5 w-1.5 rounded-full bg-st-accent" />ویژه سازمان‌ها و شرکت‌ها</span>
            <h1 className="text-st-title-lg font-extrabold leading-snug text-white">{content?.title || "تأمین هوشمند نیازهای خانه و سازمان"}</h1>
            <p className="mt-1 line-clamp-2 text-st-body-sm text-st-on-navy-muted">{content?.body || "پک‌های آماده، خرید عمده و پیش‌فاکتور رسمی برای کارکنان و سازمان‌ها."}</p>
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={content?.image_url || HERO_IMAGE} alt="" className="h-24 w-24 shrink-0 rounded-xl object-cover ring-2 ring-white/20" />
        </div>
        <div className="relative mt-3 flex items-center gap-2">
          <Link href={link} className="flex h-10 items-center gap-1.5 rounded-full bg-st-accent px-4 text-st-label-lg font-bold text-white">
            <span>{content?.button_label || "مشاهده بسته‌ها"}</span><Icon name="arrow_back" className="text-[16px]" /></Link>
          <Link href="/me/proformas" className="flex h-10 items-center gap-1 rounded-full bg-white/10 px-3 text-st-label-md text-white ring-1 ring-white/15"><Icon name="receipt_long" className="text-[16px]" />پیش‌فاکتور رسمی</Link>
        </div>
      </div>
    </section>
  </>;
}

// ── Category tiles (filter the product grid below; same chips behaviour) ──
function Chips({ cats, value, onChange }: { cats: { slug: string; name: string; count: number }[] | null; value: string | null; onChange: (v: string | null) => void }) {
  if (cats && !cats.length) return null;
  const all = [{ slug: null as string | null, name: "همه دسته‌ها", count: 0 }, ...(cats ?? []).map((c) => ({ slug: c.slug as string | null, name: c.name, count: c.count }))];
  return (
    <section className={cn(W, "pt-4 md:pt-6")} aria-label="دسته‌بندی‌ها">
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:grid-cols-[repeat(auto-fit,minmax(118px,1fr))] md:gap-3 md:overflow-visible md:px-0">
        {all.map((c, i) => {
          const on = value === c.slug;
          return <button key={c.slug ?? "all"} type="button" onClick={() => onChange(c.slug)} aria-pressed={on}
            className={cn("group flex w-[84px] shrink-0 flex-col items-center gap-1.5 rounded-xl p-2 text-center transition-all md:w-auto md:p-3",
              on ? "bg-st-navy text-white shadow-st-raise" : "bg-st-surface-container-lowest text-st-primary shadow-st-card hover:-translate-y-0.5 hover:shadow-st-raise")}>
            <IconTile icon={c.slug ? categorySymbol(c.slug, c.name) : "apps"} tone={on ? "accent" : TONE_CYCLE[i % TONE_CYCLE.length]} className={on ? "bg-white/15 text-white" : ""} />
            <span className="line-clamp-1 text-st-label-md font-semibold">{c.slug ? c.name : "همه"}</span>
            {c.count > 0 && <span className={cn("hidden text-st-label-sm md:block", on ? "text-st-on-navy-muted" : "text-st-outline")}>{toPersianNum(c.count)} کالا</span>}
          </button>;
        })}
        {!cats && Array.from({ length: 6 }, (_, i) => <span key={i} className="h-[92px] w-[84px] shrink-0 animate-pulse rounded-xl bg-st-surface-container-lowest md:w-auto" />)}
      </div>
    </section>
  );
}

// ── Packs (3 showcase cards desktop / horizontal list mobile) — on a warm sand band ──
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
  return (
    <Section band="sand" className="mt-6" id="home-packs" title="پک‌های سازمانی و رفاهی کارکنان" eyebrow="ویژه سازمان‌ها، شرکت‌ها و نهادها" icon="inventory_2" href="/packs" linkLabel="همه پک‌ها">
      <div className="no-scrollbar -mx-4 flex gap-3 overflow-x-auto px-4 md:mx-0 md:grid md:grid-cols-3 md:gap-4 md:overflow-visible md:px-0">
        {cards.map(({ key, p, img }) => !p ? <span key={key} className="h-[300px] w-[270px] shrink-0 animate-pulse rounded-xl bg-st-surface-container-lowest md:w-auto" /> : (
          <article key={key} className="group flex w-[270px] shrink-0 flex-col overflow-hidden rounded-xl bg-st-surface-container-lowest shadow-st-card transition-shadow hover:shadow-st-raise md:w-auto">
            <Link href={`/packs/${p.slug}`} className="relative block h-40 w-full overflow-hidden bg-st-surface-container-low md:h-48">
              <Photo src={img} alt={p.title_fa} className="p-3" />
              <span className="absolute right-3 top-3 rounded-full bg-st-navy px-2.5 py-0.5 text-st-label-sm font-semibold text-white">{p.kind_fa}</span>
              {(p.tier_fa || p.customizable) && <span className="absolute left-3 top-3 rounded-full bg-st-accent px-2.5 py-0.5 text-st-label-sm font-bold text-white">{p.tier_fa || "قابل سفارشی‌سازی"}</span>}
            </Link>
            <div className="flex flex-1 flex-col justify-between gap-3 p-3 md:p-4">
              <div className="flex flex-col gap-1">
                <h3 className="text-st-title-md font-bold text-st-primary"><Link href={`/packs/${p.slug}`}>{p.title_fa}</Link></h3>
                <p className="line-clamp-2 text-st-body-sm text-st-on-surface-variant">{p.description_fa || p.purpose_fa}</p>
              </div>
              <div className="flex items-center justify-between text-st-label-md text-st-on-surface-variant">
                <span className="flex items-center gap-1"><Icon name={meta(p)[0]} className="text-[16px] text-st-secondary" />{meta(p)[1]}</span>
                {p.packaging_fa && <span className="truncate text-st-outline">{p.packaging_fa}</span>}
              </div>
              <div className="flex items-center justify-between gap-2 border-t border-st-hairline-border pt-3">
                {p.price_minor ? <div className="flex items-baseline gap-1"><span className="text-st-title-lg font-extrabold text-st-primary">{num(p.price_minor)}</span><span className="text-st-label-sm text-st-on-surface-variant">تومان</span></div>
                  : <span className="text-st-label-lg font-bold text-st-primary">قیمت با استعلام</span>}
                <Link href={`/packs/${p.slug}`} className="flex h-9 items-center gap-1 rounded-full bg-st-secondary px-3.5 text-st-label-md font-bold text-white transition-colors hover:bg-st-navy">
                  <Icon name={quote(p) ? "request_quote" : "add_shopping_cart"} className="text-[16px]" /><span>{quote(p) ? "ثبت پیش‌فاکتور" : "مشاهده و سفارش"}</span></Link>
              </div>
            </div>
          </article>))}
      </div>
    </Section>
  );
}

// ── Product grid «کالاهای منتخب و روزمره» — dense: 2 cols mobile, 4–5 desktop ──
function Price({ p }: { p: Product }) {
  const pct = discountPct(p);
  if (!p.purchasable || !p.price_minor) return <span className="text-st-label-lg font-bold text-st-primary">قیمت با استعلام</span>;
  return (
    <div className="flex flex-col leading-tight">
      {pct > 0 && <span className="text-[11px] text-st-outline line-through">{num(p.original_price_minor!)}</span>}
      <div className="flex items-baseline gap-1">
        {p.price_from && <span className="text-[11px] text-st-on-surface-variant">از</span>}
        <span className="text-st-title-md font-extrabold text-st-primary">{num(p.price_minor)}</span>
        <span className="text-[11px] text-st-on-surface-variant">تومان</span>
      </div>
    </div>
  );
}
function ProductCard({ p }: { p: Product | null }) {
  if (!p) return <span className="h-[280px] animate-pulse rounded-xl bg-st-surface-container-lowest md:h-[320px]" />;
  const pct = discountPct(p), href = `/products/${p.slug}`;
  return (
    <article className="group flex flex-col rounded-xl bg-st-surface-container-lowest p-2.5 shadow-st-card transition-all hover:-translate-y-0.5 hover:shadow-st-raise md:p-3">
      <Link href={href} className="relative mb-2 block aspect-square w-full overflow-hidden rounded-lg bg-st-surface-container-low">
        <Photo src={p.image_url} alt={p.name} className="p-2" />
        {pct > 0 && <span className="absolute right-2 top-2 rounded-full bg-st-accent px-2 py-0.5 text-[11px] font-bold text-white">{toPersianNum(pct)}٪</span>}
        {p.brand && <span className="absolute bottom-2 right-2 hidden max-w-[85%] truncate rounded-md bg-white/90 px-2 py-0.5 text-st-label-sm font-medium text-[#112D46] md:block">{p.brand}</span>}
      </Link>
      <div className="flex flex-1 flex-col justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          {p.category?.name && <span className="hidden text-st-label-sm text-st-secondary md:block">{p.category.name}</span>}
          {!!p.review_count && !!p.rating && <span className="flex items-center gap-1 text-st-label-sm text-st-on-surface-variant">
            <Icon name="star" fill className="text-[14px] text-st-accent" />{toPersianNum(p.rating.toFixed(1))}<span className="text-st-outline">({toPersianNum(p.review_count)})</span></span>}
          <h3 className="line-clamp-2 text-st-body-md font-semibold leading-6 text-st-on-surface"><Link href={href}>{p.name}</Link></h3>
        </div>
        <div className="flex items-end justify-between gap-1">
          <Price p={p} />
          <Link href={href} aria-label={`مشاهده و افزودن ${p.name} به سبد`} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-st-secondary text-white transition-colors hover:bg-st-navy md:h-9 md:w-9"><Icon name="add" className="text-[20px]" /></Link>
        </div>
      </div>
    </article>
  );
}
function Today({ items, activeName }: { items: Product[] | null; activeName: string }) {
  if (items && !items.length) return (
    <section className={cn(W, "py-6")}><EmptyState icon="category" title="در این دسته هنوز کالایی برای نمایش نیست." body="دستهٔ دیگری را انتخاب کنید یا نیازتان را به صورت درخواست خرید ثبت کنید." action={{ href: "/requests/new", label: "ثبت درخواست خرید", icon: "request_quote" }} secondary={{ href: "/category", label: "همه دسته‌بندی‌ها" }} /></section>);
  const list = items ?? Array.from({ length: 10 }, () => null);
  return (
    <Section id="home-today" title="کالاهای منتخب و روزمره" eyebrow="عرضه مستقیم از تأمین‌کنندگان" icon="storefront" href="/category" linkLabel="همه کالاها"
      extra={<span className="hidden rounded-full bg-st-surface-container-low px-3 py-1 text-st-label-md text-st-on-surface-variant sm:inline">{activeName}</span>}>
      <div className="grid grid-cols-2 gap-2.5 max-sm:[&>*:nth-child(n+7)]:hidden sm:grid-cols-3 md:gap-3 lg:grid-cols-4 xl:grid-cols-5">{list.map((p, i) => <ProductCard key={p?.id ?? i} p={p} />)}</div>
    </Section>
  );
}

// ── Value strip — compact icon row on a mint band ──────────────────────────
const WHY: [string, string, string, string][] = [
  ["receipt_long", "پیش‌فاکتور و فاکتور رسمی", "صدور پیش‌فاکتور رسمی برای خرید سازمانی و پیگیری آن از حساب کاربری.", "/me/proformas"],
  ["published_with_changes", "بازگشت و انصراف از خرید", "شرایط مرجوعی و انصراف از خرید، شفاف و مطابق قوانین تجارت الکترونیکی.", "/help/returns"],
  ["payments", "اعتبار و بودجه سازمانی", "خرید کارکنان با اعتبار تخصیص‌یافته از سوی سازمان طرف قرارداد.", "/org"],
  ["support_agent", "پشتیبانی خرید", "راهنمایی در انتخاب کالا، ثبت درخواست قیمت عمده و پیگیری سفارش.", "/contact"],
];
function Why() {
  return (
    <Band tone="mint" aria-label="مزیت‌های خرید" className="mt-2">
      <div className={cn(W, "grid grid-cols-2 gap-2 py-4 md:gap-3 md:py-6 lg:grid-cols-4")}>
        {WHY.map(([icon, head, body, href], i) => (
          <Link key={head} href={href} className="flex items-center gap-2.5 rounded-xl bg-st-surface-container-lowest/80 p-2.5 transition-colors hover:bg-st-surface-container-lowest md:p-3">
            <IconTile icon={icon} tone={(["navy", "accent", "brand", "mint"] as const)[i]} />
            <span className="flex min-w-0 flex-col"><span className="text-st-label-lg font-bold text-st-primary">{head}</span><span className="line-clamp-1 hidden text-st-label-md text-st-on-surface-variant md:block">{body}</span></span>
          </Link>))}
      </div>
    </Band>
  );
}

export default function FigmaHome({ previewContent }: { previewContent?: PageContent } = {}) {
  const tree = useTaxonomy();
  const cats = useMemo(() => tree ? tree.slice().sort((a, b) => b.product_count - a.product_count).slice(0, 8).map((n) => ({ slug: n.slug, name: n.name_fa, count: n.product_count })) : null, [tree]);
  const [cat, setCat] = useState<string | null>(null);
  const raw = useProducts(cat);
  const shown = useShowcase(raw, 10);
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
    <div className="flex w-full flex-col bg-st-background pb-4 md:pb-0" dir="rtl">
      {!hidden.has("hero") && <div className="order-1"><Hero content={hero} /></div>}
      {!hidden.has("categories") && <div className="order-2"><Chips cats={cats} value={cat} onChange={setCat} /></div>}
      {!hidden.has("packs") && <div className="order-3"><Packs /></div>}
      {!hidden.has("today") && <div className="order-4"><Today items={shown} activeName={activeName} /></div>}
      {!hidden.has("why") && <div className="order-5"><Why /></div>}
    </div>
  );
}
