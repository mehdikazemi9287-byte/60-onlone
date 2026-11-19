"use client";

// Homepage — «مگامارکت» (Stitch screens 65 desktop / 66 mobile, approved by the owner on 2026-11-19).
// Personal shopping comes first; organizational and bulk buying has its own separate box near the end.
// Every product, category, pack, shop, brand, count, photo and price comes from the live API. Prices follow the existing
// rule: a verified seller price, otherwise «قیمت پس از استعلام». Sections without real data are hidden, never faked:
// there is no deal end time (so no countdown), no sales ranking (so «منتخب» rather than «پرفروش») and no club statistics
// for guests. The three shopping modes only change what each card offers; the page and the cart are never reset.

import type { PageContent } from "@/lib/content-types";
import { apiRequest, cart as cartApi, ApiError, catalog, categories as categoriesApi } from "@/lib/api";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, BadgeCheck, Boxes, Building2, ChevronLeft, ChevronRight, ClipboardList, Coins, FileText, Layers, LayoutGrid, MapPin,
  Package, PackageCheck, Plus, ShieldCheck, ShoppingCart, Sparkles, Store, Truck, Undo2, Users, Wallet, Zap } from "lucide-react";
import { useGoodImages } from "@/lib/imageQuality";
import { storefront, type PackDetail } from "@/lib/storefront";
import { shops as shopsApi, type Shop } from "@/lib/shops";
import type { Category, Product } from "@/lib/types";
import { cn, formatPrice, toPersianNum } from "@/lib/utils";
import { loadPackDetails, packImages } from "@/components/packs/PackCard";
import { useAuth } from "@/lib/auth-context";
import { useModeAccess, useShoppingMode, type ModeAccess, type ShoppingMode } from "@/lib/shopping-mode";

const WRAP = "mx-auto flex w-full max-w-[1360px] flex-col gap-6 px-4 py-4 md:gap-8 md:px-10 md:py-6";
const CARD = "rounded-lg bg-white shadow-[0_1px_6px_rgba(17,24,39,0.05)]";
const BTN = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-4 text-sm font-bold transition";
const PRIMARY = `${BTN} bg-honey text-mm-deep hover:bg-honey-hover`;
const SECONDARY = `${BTN} border border-mm-navy/25 bg-white text-mm-navy hover:border-mm-navy`;
const PASTEL = ["#E8F1FB", "#FFF6DC", "#FDECEF", "#EFEBFA", "#E6F4EC", "#FDEFE3"];
const hasImage = (p: Product) => !!p.image_url && !p.image_url.includes("picsum.photos");
const retail = (p: Product) => !p.org_only && (p.allowed_channels ?? ["retail"]).includes("retail");
const orgChannel = (p: Product) => (p.allowed_channels ?? ["organization"]).includes("organization");
const priceText = (p: Product) => (p.purchasable && p.price_minor ? `${p.price_from ? "از " : ""}${formatPrice(p.price_minor)}` : "قیمت پس از استعلام");
const bulkHref = (p: Product) => `/requests/new?slug=${encodeURIComponent(p.slug)}&quantity=1`;

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

/** A few real products from each of the largest categories (the relevance pool alone is dominated by one brand). */
const catLists = new Map<string, Promise<Product[]>>();
function useCategoryProducts(cats: Category[] | null, n = 8): Product[] | null {
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

const family = (name: string) => name.replace(/[0-9۰-۹]+/g, " ").replace(/(کیلویی|گرمی|گرم|کیلو|عددی|بسته|شماره|لیتری|اینچ)/g, " ").split(/\s+/).filter(Boolean).slice(0, 2).join(" ");
/** Category round-robin, one product per near-duplicate family and per photo. */
function diversify(list: Product[], limit: number, skip?: Set<number>): Product[] {
  const seen = new Set<string>(), groups = new Map<string, Product[]>();
  for (const p of list) {
    if (skip?.has(p.id)) continue;
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

function Img({ src, alt = "", className = "" }: { src: string | null | undefined; alt?: string; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt={alt} loading="lazy" className={cn("h-full w-full object-contain mix-blend-multiply", className)} /> : <span className="block h-full w-full animate-pulse rounded-lg bg-black/5" />;
}
function Title({ icon: Icon, title, sub, href, more = "مشاهده‌ی همه", dark = false }: { icon?: typeof Zap; title: string; sub?: string; href?: string; more?: string; dark?: boolean }) {
  return <div className="mb-4 flex items-center justify-between gap-3">
    <div className="flex min-w-0 items-center gap-3">
      {Icon && <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", dark ? "bg-white/15 text-honey" : "bg-mm-blue text-white")}><Icon className="h-5 w-5" /></span>}
      <div className="min-w-0"><h2 className={cn("text-lg font-black md:text-[22px]", dark ? "text-white" : "text-mm-text")}>{title}</h2>
        {sub && <p className={cn("mt-0.5 text-sm", dark ? "text-white/75" : "text-mm-muted")}>{sub}</p>}</div>
    </div>
    {href && <Link href={href} className={cn("inline-flex min-h-11 shrink-0 items-center gap-1 text-sm font-bold", dark ? "text-honey" : "text-mm-blue")}>{more}<ArrowLeft className="h-4 w-4" /></Link>}
  </div>;
}

// ── Add to cart (real cart API; guests are sent to login and come back) ──
function AddToCart({ p, label = "افزودن به سبد", className }: { p: Product; label?: string; className?: string }) {
  const { token } = useAuth();
  const router = useRouter(), path = usePathname();
  const [state, setState] = useState<"idle" | "busy" | "done" | string>("idle");
  if ((p.variant_count ?? 1) > 1) return <Link href={`/products/${p.slug}`} className={cn(PRIMARY, className)}>انتخاب مدل</Link>;
  const add = async () => {
    if (!token) { router.push(`/login?next=${encodeURIComponent(path || "/")}`); return; }
    setState("busy");
    try { await cartApi.add(token, p.id, 1); setState("done"); setTimeout(() => setState("idle"), 2000); }
    catch (e) { setState(e instanceof ApiError ? e.message : "افزودن ناموفق بود"); setTimeout(() => setState("idle"), 3500); }
  };
  const msg = state === "done" ? "به سبد اضافه شد" : state === "busy" ? "در حال افزودن…" : state === "idle" ? label : state;
  return <button type="button" onClick={add} disabled={state === "busy"} aria-live="polite" className={cn(PRIMARY, state !== "idle" && state !== "busy" && state !== "done" && "bg-danger-50 text-danger-700", className)}>
    {state === "idle" && <ShoppingCart className="h-4 w-4" />}<span className="line-clamp-1">{msg}</span></button>;
}

// ── Mode context strip: what the selected mode offers, or how to get access ──
function ModeStrip({ mode, access }: { mode: ShoppingMode; access: ModeAccess }) {
  if (mode === "personal") return (
    <section className="flex flex-col gap-3 rounded-lg bg-gradient-to-l from-mm-blue to-mm-navy px-4 py-3 text-white md:flex-row md:items-center md:justify-between md:px-6" aria-label="خرید شخصی">
      <div className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/15"><BadgeCheck className="h-5 w-5 text-honey" /></span>
        <p className="text-sm leading-6 md:text-[15px]"><b className="font-black">خرید مستقیم برای همه</b> <span className="text-white/80">— بدون نیاز به کد سازمان؛ تکی بخرید یا عمده استعلام بگیرید.</span></p></div>
      <a href="#today" className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-lg bg-white px-4 text-sm font-bold text-mm-blue">پیشنهادهای امروز</a>
    </section>);
  const staff = mode === "staff";
  const ok = staff ? access.staff : access.org;
  const title = staff ? "خرید پرسنل سازمان" : "خرید سازمانی و عمده";
  let body: React.ReactNode, actions: React.ReactNode;
  if (access.loading) { body = "در حال بررسی دسترسی شما…"; actions = null; }
  else if (ok && staff) {
    body = <>{access.orgName ? `کارمند ${access.orgName}؛ ` : ""}{access.openPrograms ? `${toPersianNum(access.openPrograms)} برنامه‌ی مزایای باز دارید.` : "برنامه‌ی مزایای باز ندارید؛ خرید عادی هم ممکن است."}</>;
    actions = <Link href="/benefits" className={PRIMARY}><Wallet className="h-4 w-4" />مزایای من</Link>;
  } else if (ok) {
    body = <>{access.orgName ? `${access.orgName}؛ ` : ""}پک‌ساز، استعلام قیمت عمده و پنل سازمان در دسترس شماست.</>;
    actions = <><Link href="/pack-builder" className={PRIMARY}><Boxes className="h-4 w-4" />پک‌ساز</Link><Link href="/requests/new" className={SECONDARY}>استعلام قیمت</Link><Link href="/organization" className={SECONDARY}>پنل سازمان</Link></>;
  } else if (!access.signedIn) {
    body = staff ? "برای دیدن مزایا و اعتبار کارکنان وارد شوید." : "برای خرید سازمانی وارد شوید یا سازمان خود را ثبت کنید.";
    actions = <><Link href={`/login?next=${staff ? "/benefits" : "/organization"}`} className={PRIMARY}>ورود / عضویت</Link>{!staff && <Link href="/business" className={SECONDARY}>ثبت سازمان</Link>}</>;
  } else {
    body = staff ? "حساب شما هنوز عضو سازمان طرف قرارداد نیست؛ لینک دعوت را از مدیر سازمان بگیرید." : "حساب شما هنوز سازمانی نیست. سازمان خود را ثبت کنید یا بدون حساب سازمانی استعلام قیمت بگیرید.";
    actions = staff ? <Link href="/business" className={SECONDARY}>ثبت سازمان</Link> : <><Link href="/business" className={PRIMARY}><Building2 className="h-4 w-4" />ثبت سازمان</Link><Link href="/requests/new" className={SECONDARY}>استعلام قیمت</Link></>;
  }
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-honey/50 bg-honey-tint px-4 py-3 md:flex-row md:items-center md:justify-between md:px-6" aria-live="polite" aria-label={title}>
      <div className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-mm-navy text-honey">{staff ? <Users className="h-5 w-5" /> : <Building2 className="h-5 w-5" />}</span>
        <p className="text-sm leading-6 text-mm-text md:text-[15px]"><b className="font-black">{title}:</b> {body}</p></div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </section>);
}

// ── Hero slider (admin-editable first slide + the largest real categories with their own photo) ──
type Slide = { key: string; tag: string; title: string; body: string; href: string; cta: string; img?: string };
function Hero({ slides, side }: { slides: Slide[]; side: React.ReactNode }) {
  const [i, setI] = useState(0);
  const paused = useRef(false);
  useEffect(() => {
    if (slides.length < 2) return;
    const t = setInterval(() => { if (!paused.current) setI((x) => (x + 1) % slides.length); }, 6000);
    return () => clearInterval(t);
  }, [slides.length]);
  const s = slides[Math.min(i, slides.length - 1)];
  return (
    <section className="grid gap-4 lg:grid-cols-12 lg:gap-6" aria-roledescription="carousel" aria-label="پیشنهادهای ویژه">
      <div className="relative flex min-h-[300px] overflow-hidden rounded-lg bg-mm-deep text-white lg:col-span-8 lg:min-h-[420px]"
        onMouseEnter={() => (paused.current = true)} onMouseLeave={() => (paused.current = false)}>
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_80%,rgba(3,78,162,0.55),transparent_55%)]" aria-hidden />
        <div className="relative z-10 flex w-full flex-col justify-between gap-5 p-5 md:flex-row md:items-center md:p-10">
          <div className="max-w-lg space-y-3 md:space-y-4" key={s.key}>
            <span className="inline-flex items-center gap-2 rounded-full bg-honey px-3 py-1 text-[13px] font-bold text-mm-deep"><Zap className="h-3.5 w-3.5" />{s.tag}</span>
            <h1 className="whitespace-pre-line text-[24px] font-black leading-[1.55] md:text-[36px]">{s.title}</h1>
            <p className="text-[15px] leading-7 text-white/80 md:text-base">{s.body}</p>
            <div className="flex flex-wrap gap-2 pt-1">
              <Link href={s.href} className={cn(PRIMARY, "px-6")}>{s.cta}<ArrowLeft className="h-4 w-4" /></Link>
              <Link href="/packs" className={`${BTN} bg-white/10 text-white hover:bg-white/20`}>پک‌های مناسبتی</Link>
            </div>
          </div>
          {s.img && <span className="mx-auto block h-40 w-40 shrink-0 rounded-lg bg-white p-3 md:h-64 md:w-64"><Img src={s.img} alt="" /></span>}
        </div>
        {slides.length > 1 && <div className="absolute bottom-3 left-4 z-10 flex items-center gap-1.5">
          <button type="button" aria-label="اسلاید قبلی" onClick={() => setI((x) => (x - 1 + slides.length) % slides.length)} className="flex h-11 w-11 items-center justify-center rounded-full bg-white/10 hover:bg-white/20"><ChevronRight className="h-5 w-5" /></button>
          {slides.map((x, n) => <button key={x.key} type="button" aria-label={`اسلاید ${toPersianNum(n + 1)}`} aria-current={n === i} onClick={() => setI(n)} className="flex h-11 w-6 items-center justify-center"><span className={cn("h-2 rounded-full transition-all", n === i ? "w-5 bg-honey" : "w-2 bg-white/40")} /></button>)}
          <button type="button" aria-label="اسلاید بعدی" onClick={() => setI((x) => (x + 1) % slides.length)} className="flex h-11 w-11 items-center justify-center rounded-full bg-white/10 hover:bg-white/20"><ChevronLeft className="h-5 w-5" /></button>
        </div>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:col-span-4 lg:grid-cols-1 lg:gap-6">{side}</div>
    </section>);
}
function SideCard({ href, icon: Icon, tag, title, body, cta, tone }: { href: string; icon: typeof Zap; tag: string; title: string; body: string; cta: string; tone: "mint" | "honey" }) {
  return <Link href={href} className={cn("group flex flex-col justify-between gap-3 rounded-lg p-5 shadow-[0_1px_6px_rgba(17,24,39,0.05)] transition hover:-translate-y-0.5", tone === "mint" ? "bg-mm-mint" : "bg-honey-tint")}>
    <span className="flex items-start justify-between"><span className="flex h-11 w-11 items-center justify-center rounded-lg bg-mm-navy text-white"><Icon className="h-5 w-5" /></span>
      <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-mm-navy">{tag}</span></span>
    <span><b className="block text-lg font-black text-mm-text">{title}</b><span className="mt-1 block text-sm leading-6 text-mm-muted">{body}</span></span>
    <span className="inline-flex items-center gap-1 text-sm font-bold text-mm-blue">{cta}<ArrowLeft className="h-4 w-4 transition group-hover:-translate-x-0.5" /></span>
  </Link>;
}

// ── Daily categories (pastel cards, real photo + real count) ───────────────
type CatPick = { cat: Category; img?: string };
function Categories({ picks }: { picks: CatPick[] | null }) {
  if (picks && !picks.length) return null;
  return (
    <section aria-labelledby="home-cats">
      <div className="mb-4 flex items-center justify-between gap-3"><div><h2 id="home-cats" className="text-lg font-black text-mm-text md:text-[22px]">دسته‌بندی‌های خرید روزانه</h2>
        <p className="mt-0.5 text-sm text-mm-muted">انتخاب سریع از دسته‌های دارای کالا</p></div>
        <Link href="/category" className="inline-flex min-h-11 items-center gap-1 text-sm font-bold text-mm-blue">همه‌ی دسته‌ها<ArrowLeft className="h-4 w-4" /></Link></div>
      <div className="grid grid-cols-3 gap-3 md:grid-cols-4 lg:grid-cols-8 lg:gap-4">
        {(picks ?? Array.from({ length: 8 }, () => null)).slice(0, 8).map((c, i) => c ? (
          <Link key={c.cat.slug} href={`/category/${c.cat.slug}`} className="group flex flex-col items-center gap-2 rounded-lg p-3 text-center transition hover:-translate-y-0.5 hover:shadow-md" style={{ background: PASTEL[i % PASTEL.length] }}>
            <span className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-full bg-white p-2 md:h-20 md:w-20">{c.img ? <Img src={c.img} alt="" /> : <LayoutGrid className="h-7 w-7 text-mm-blue" strokeWidth={1.6} />}</span>
            <b className="line-clamp-2 text-sm leading-6 text-mm-text">{c.cat.name}</b>
            <span className="text-xs text-mm-muted">{toPersianNum(c.cat.product_count)} کالا</span>
          </Link>) : <span key={i} className="h-36 animate-pulse rounded-lg bg-black/5" />)}
      </div>
    </section>);
}

// ── Daily offers: real products with a verified price; org mode shows the organizational channel instead ──
function Today({ items, mode }: { items: Product[] | null; mode: ShoppingMode }) {
  if (items && !items.length) return null;
  const org = mode === "org";
  return (
    <section id="today" className={cn("scroll-mt-40 rounded-lg p-4 md:p-6", org ? "bg-gradient-to-l from-[#F26B3A] via-[#F28C38] to-[#F5B041]" : "bg-mm-deep")} aria-label={org ? "قیمت سازمانی" : "پیشنهادهای امروز"}>
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-lg bg-white/15">{org ? <Building2 className="h-6 w-6 text-white" /> : <Zap className="h-6 w-6 text-honey" />}</span>
          <div><h2 className="text-lg font-black text-white md:text-[22px]">{org ? "قیمت سازمانی" : "پیشنهادهای امروز"}</h2>
            <p className="mt-0.5 text-sm text-white/80">{org ? "کالاهای قابل‌عرضه به سازمان‌ها؛ قیمت عمده پس از استعلام اعلام می‌شود" : "کالاهای موجود با قیمت تأییدشده‌ی فروشنده؛ تکی بخرید یا عمده سفارش دهید"}</p></div></div>
        <Link href={org ? "/business/catalog" : "/category"} className="inline-flex min-h-11 items-center gap-1 self-start rounded-lg bg-white/15 px-4 text-sm font-bold text-white hover:bg-white/25 md:self-auto">مشاهده‌ی همه<ArrowLeft className="h-4 w-4" /></Link>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
        {(items ?? Array.from({ length: 4 }, () => null)).map((p, i) => p ? (
          <article key={p.id} className="flex gap-3 rounded-lg bg-white p-3 lg:flex-col lg:p-4">
            <Link href={`/products/${p.slug}`} className="relative block h-28 w-28 shrink-0 rounded-lg bg-[#F5F7FA] p-2 lg:h-48 lg:w-full">
              <Img src={p.image_url} alt={p.name} />
              {!org && p.purchasable && <span className="absolute right-1.5 top-1.5 rounded-full bg-honey px-2 py-0.5 text-[11px] font-black text-mm-deep">موجود</span>}
            </Link>
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="line-clamp-1 text-xs text-mm-muted">{[p.brand, p.category?.name].filter(Boolean).join(" • ")}</span>
              <Link href={`/products/${p.slug}`} className="mt-1 line-clamp-2 text-[15px] font-bold leading-6 text-mm-text">{p.name}</Link>
              <b className="mt-2 text-base font-black tabular-nums text-mm-blue">{org ? "قیمت پس از استعلام" : priceText(p)}</b>
              <div className="mt-auto grid grid-cols-2 gap-2 pt-3">
                {org ? <Link href={bulkHref(p)} className={cn(PRIMARY, "col-span-2 px-2")}><ClipboardList className="h-4 w-4" />درخواست قیمت عمده</Link>
                  : <>{p.purchasable ? <AddToCart p={p} className="px-2" /> : <Link href={`/products/${p.slug}`} className={cn(PRIMARY, "px-2")}>مشاهده</Link>}
                    <Link href={bulkHref(p)} className={cn(SECONDARY, "px-2")}><Layers className="h-4 w-4" />خرید عمده</Link></>}
              </div>
            </div>
          </article>) : <span key={i} className="h-40 animate-pulse rounded-lg bg-white/20 lg:h-[380px]" />)}
      </div>
    </section>);
}

// ── Occasion / family packs as photo cards ──────────────────────────────────
function Packs({ mode }: { mode: ShoppingMode }) {
  const [packs, setPacks] = useState<PackDetail[] | null>(null);
  useEffect(() => { let off = false; loadPackDetails().then((p) => !off && setPacks(p)).catch(() => !off && setPacks([])); return () => { off = true; }; }, []);
  const shown = useMemo(() => packs ? packs.filter((p) => p.items.length).slice(0, 3) : null, [packs]);
  const good = useGoodImages((shown ?? []).flatMap((p) => p.items.map((i) => i.image_url)));
  if (shown && !shown.length) return null;
  const used = new Set<string>();
  return (
    <section id="packs" className="scroll-mt-40 rounded-lg bg-[#EEF2F6] p-4 md:p-6" aria-labelledby="home-packs">
      <div className="mb-4 flex items-center justify-between gap-3"><div>
        <div className="flex flex-wrap items-center gap-2"><span className="rounded-md bg-honey px-2.5 py-0.5 text-xs font-black text-mm-deep">مناسبتی و معیشتی</span>
          <h2 id="home-packs" className="text-lg font-black text-mm-text md:text-[22px]">پک‌های مناسبتی و خانواده</h2></div>
        <p className="mt-1 text-sm text-mm-muted">یک بسته برای خانه یا چندتایی برای سازمان؛ اقلام و قیمت از کاتالوگ واقعی</p></div>
        <Link href="/packs" className="inline-flex min-h-11 shrink-0 items-center gap-1 text-sm font-bold text-mm-blue">همه‌ی پک‌ها<ArrowLeft className="h-4 w-4" /></Link></div>
      <div className="grid gap-4 md:grid-cols-3">
        {(shown ?? [null, null, null]).map((p, i) => {
          if (!p) return <span key={i} className="h-96 animate-pulse rounded-lg bg-white/70" />;
          const pics = packImages(p, good, 3, used);
          const href = `/packs/${p.slug}`;
          const price = p.price_minor != null ? (p.availability === "quote_only" ? `برآورد ${formatPrice(p.price_minor)}` : formatPrice(p.price_minor)) : "قیمت پس از استعلام";
          return (
            <article key={p.slug} className={cn(CARD, "flex flex-col p-4")}>
              <Link href={href} className="relative flex h-44 items-center justify-center gap-2 overflow-hidden rounded-lg bg-[#F8F7F4] p-3 md:h-52" aria-label={p.title_fa}>
                {good === null ? <span className="h-full w-full animate-pulse rounded-lg bg-white/70" />
                  : pics.length ? pics.map((src) => (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img key={src} src={src} alt="" loading="lazy" className="aspect-square h-full max-w-[32%] rounded-lg bg-white object-contain p-1.5" />))
                  : <Package className="h-12 w-12 text-mm-muted" strokeWidth={1.4} />}
                <span className="absolute right-3 top-3 rounded-full bg-mm-navy px-3 py-1 text-xs font-bold text-white">{toPersianNum(p.item_count)} قلم کالا</span>
              </Link>
              <p className="mt-3 text-xs text-mm-muted">{[p.kind_fa, p.tier_fa, p.occasion].filter(Boolean).join(" · ")}</p>
              <h3 className="mt-1 text-lg font-black leading-8 text-mm-text"><Link href={href}>{p.title_fa}</Link></h3>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-mm-muted">{p.purpose_fa}</p>
              <div className="mt-3 flex items-baseline justify-between gap-2 border-t border-[#EEF0F3] pt-3"><span className="text-sm text-mm-muted">{p.min_order_qty > 1 ? `حداقل ${toPersianNum(p.min_order_qty)} پک` : "خرید تکی ممکن است"}</span>
                <b className="text-base font-black tabular-nums text-mm-blue">{price}</b></div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Link href={href} className={cn(mode === "org" ? SECONDARY : PRIMARY, "px-2")}>{mode === "org" ? "مشاهده‌ی اقلام" : "مشاهده و خرید"}</Link>
                <Link href="/pack-builder" className={cn(mode === "org" ? PRIMARY : SECONDARY, "px-2")}><Boxes className="h-4 w-4" />{mode === "org" ? "سفارش در پک‌ساز" : "خرید عمده"}</Link>
              </div>
            </article>);
        })}
      </div>
    </section>);
}

// ── Curated picks (no sales ranking exists in the API, so they are labelled «منتخب», not «پرفروش») ──
function Picks({ items, mode }: { items: Product[] | null; mode: ShoppingMode }) {
  const [tab, setTab] = useState("");
  const tabs = useMemo(() => {
    if (!items) return [];
    const m = new Map<string, { name: string; n: number }>();
    for (const p of items) if (p.category) m.set(p.category.slug, { name: p.category.name, n: (m.get(p.category.slug)?.n ?? 0) + 1 });
    return [...m.entries()].filter(([, v]) => v.n >= 2).sort((a, b) => b[1].n - a[1].n).slice(0, 3);
  }, [items]);
  if (items && items.length < 4) return null;
  const list = (items ?? Array.from({ length: 10 }, () => null)).filter((p) => !tab || p?.category?.slug === tab).slice(0, 10);
  return (
    <section aria-labelledby="home-picks">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-mm-blue text-white"><Sparkles className="h-5 w-5" /></span>
          <div><h2 id="home-picks" className="text-lg font-black text-mm-text md:text-[22px]">منتخب سبد خانوار</h2><p className="mt-0.5 text-sm text-mm-muted">کالاهای دارای عکس و قیمت از دسته‌های مختلف</p></div></div>
        {tabs.length > 1 && <div className="-mx-1 flex gap-2 overflow-x-auto px-1" role="tablist" aria-label="فیلتر دسته">
          {[["", "همه"] as [string, string], ...tabs.map(([slug, v]) => [slug, v.name] as [string, string])].map(([slug, name]) =>
            <button key={slug || "all"} type="button" role="tab" aria-selected={tab === slug} onClick={() => setTab(slug)} className={cn("min-h-11 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-bold transition", tab === slug ? "bg-mm-blue text-white" : "bg-[#EEF2F6] text-mm-muted hover:text-mm-text")}>{name}</button>)}
        </div>}
      </div>
      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-5 lg:gap-4">
        {list.map((p, i) => p ? (
          <article key={p.id} className={cn(CARD, "flex items-center gap-3 p-3 md:flex-col md:items-stretch md:p-4")}>
            <Link href={`/products/${p.slug}`} className="block h-20 w-20 shrink-0 rounded-lg bg-[#F5F7FA] p-1.5 md:h-40 md:w-full md:p-3"><Img src={p.image_url} alt={p.name} /></Link>
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="line-clamp-1 text-xs text-mm-muted">{p.brand || p.category?.name || " "}</span>
              <Link href={`/products/${p.slug}`} className="mt-0.5 line-clamp-2 text-sm font-bold leading-6 text-mm-text md:min-h-[48px]">{p.name}</Link>
              <b className="mt-1 text-[15px] font-black tabular-nums text-mm-blue">{mode === "org" ? "قیمت پس از استعلام" : priceText(p)}</b>
            </div>
            <div className="shrink-0 md:mt-3">
              {mode !== "org" && p.purchasable
                ? <AddToCart p={p} label="افزودن" className="px-3 md:w-full" />
                : <Link href={bulkHref(p)} aria-label={`استعلام ${p.name}`} className={cn(SECONDARY, "px-3 md:w-full")}><Plus className="h-4 w-4" />استعلام</Link>}
            </div>
          </article>) : <span key={i} className="h-28 animate-pulse rounded-lg bg-black/5 md:h-[300px]" />)}
      </div>
    </section>);
}

// ── Brands & booths (real shops and brands; logos only when supplied) ──────
function Booths() {
  const [shopList, setShops] = useState<Shop[] | null>(null);
  const [brands, setBrands] = useState<{ name: string; product_count: number; image_url: string | null }[] | null>(null);
  useEffect(() => {
    shopsApi.list().then((r) => setShops(r.items.slice(0, 3))).catch(() => setShops([]));
    storefront.brands().then((r) => setBrands(r.items.slice(0, 8))).catch(() => setBrands([]));
  }, []);
  if (shopList && brands && !shopList.length && !brands.length) return null;
  return (
    <section aria-labelledby="home-booths">
      <Title icon={Store} title="غرفه‌ها و برندها" sub="خرید از فروشندگان و برندهای حاضر در شصت‌آنلاین" href="/shops" more="همه‌ی غرفه‌ها" />
      {(shopList === null || shopList.length > 0) && <div className="mb-4 grid gap-3 md:grid-cols-3 md:gap-4">
        {(shopList ?? [null, null, null]).map((s, i) => s ? (
          <article key={s.id} className={cn(CARD, "flex flex-col gap-3 p-4")}>
            <div className="flex items-center gap-3">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[#EEF2F6] text-xl font-black text-mm-blue">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {s.logo_url ? <img src={s.logo_url} alt="" className="h-full w-full object-contain" /> : s.title.slice(0, 1)}</span>
              <div className="min-w-0"><b className="flex items-center gap-1 text-base font-black text-mm-text"><span className="truncate">{s.title}</span>{s.official && <BadgeCheck className="h-4 w-4 shrink-0 text-mm-blue" aria-label="غرفه‌ی رسمی" />}</b>
                <span className="text-sm text-mm-muted">{[s.city, s.province].filter(Boolean).join("، ") || " "}</span></div>
            </div>
            {s.bio && <p className="line-clamp-2 text-sm leading-6 text-mm-muted">{s.bio}</p>}
            {s.slug && <Link href={`/shops/${s.slug}`} className={cn(SECONDARY, "mt-auto")}>ورود به غرفه<ArrowLeft className="h-4 w-4" /></Link>}
          </article>) : <span key={i} className="h-40 animate-pulse rounded-lg bg-black/5" />)}
      </div>}
      {(brands === null || brands.length > 0) && <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8 lg:gap-3">
        {(brands ?? Array.from({ length: 8 }, () => null)).map((b, i) => b ? (
          <Link key={b.name} href={`/search?brand=${encodeURIComponent(b.name)}`} className={cn(CARD, "flex min-h-11 items-center gap-2 p-2.5 transition hover:shadow-md")}>
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-honey-tint text-base font-black text-mm-navy">{b.name.slice(0, 1)}</span>
            <span className="min-w-0"><b className="block truncate text-sm text-mm-text">{b.name}</b><span className="text-xs text-mm-muted">{toPersianNum(b.product_count)} کالا</span></span>
          </Link>) : <span key={i} className="h-14 animate-pulse rounded-lg bg-black/5" />)}
      </div>}
    </section>);
}

// ── 60Club: real balance/tier for members; for guests only a sign-in prompt (no invented numbers) ──
type Loyalty = { balance_coins: number; tier: { name_fa: string } | null };
function Club() {
  const { token, loading } = useAuth();
  const [w, setW] = useState<Loyalty | null>(null);
  useEffect(() => { setW(null); if (token) apiRequest<Loyalty>("/me/loyalty", { token }).then(setW).catch(() => setW(null)); }, [token]);
  return (
    <section className="grid gap-4 overflow-hidden rounded-lg bg-mm-navy p-5 text-white md:grid-cols-[1fr_auto] md:items-center md:p-8" aria-labelledby="home-club">
      <div className="flex items-start gap-4">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-honey text-mm-deep"><Coins className="h-6 w-6" /></span>
        <div><p className="text-sm font-bold text-honey">باشگاه مشتریان</p><h2 id="home-club" className="mt-1 text-xl font-black md:text-2xl">۶۰کلاب</h2>
          <p className="mt-2 max-w-xl text-[15px] leading-7 text-white/80">با خرید از شصت‌آنلاین سکه‌ی ۶۰کوین جمع کنید و در خریدهای بعدی از آن استفاده کنید.</p></div>
      </div>
      <div className="flex flex-col gap-3 md:min-w-[260px]">
        {token && w ? <div className="grid grid-cols-2 gap-2 rounded-lg bg-white/10 p-3 text-center">
          <span><b className="block text-2xl font-black tabular-nums text-honey">{toPersianNum(w.balance_coins.toLocaleString("en-US"))}</b><span className="text-sm text-white/75">سکه‌ی شما</span></span>
          <span><b className="block text-lg font-black">{w.tier?.name_fa ?? "—"}</b><span className="text-sm text-white/75">سطح شما</span></span></div> : null}
        <div className="flex flex-wrap gap-2">
          {!loading && !token ? <Link href="/login?next=/60club" className={cn(PRIMARY, "flex-1")}>ورود و عضویت</Link> : <Link href="/60club" className={cn(PRIMARY, "flex-1")}>ورود به ۶۰کلاب</Link>}
          <Link href="/60coin" className={`${BTN} flex-1 bg-white/10 text-white hover:bg-white/20`}>۶۰کوین چیست؟</Link>
        </div>
      </div>
    </section>);
}

// ── Separate box: organizational & bulk buying (pack builder, RFQ, org panel, provinces network) ──
type StoreRow = { province: string };
function OrgBox({ access }: { access: ModeAccess }) {
  const [stores, setStores] = useState<StoreRow[] | null>(null);
  useEffect(() => { apiRequest<{ items: StoreRow[] }>("/stores").then((r) => setStores(r.items)).catch(() => setStores([])); }, []);
  const provinces = useMemo(() => new Set((stores ?? []).map((s) => s.province).filter(Boolean)).size, [stores]);
  const tiles: [typeof Zap, string, string, string][] = [
    [ClipboardList, "استعلام قیمت (RFQ)", "قیمت عمده و زمان تحویل را از فروشندگان بگیرید", "/requests/new"],
    [FileText, "پیش‌فاکتورها", "پیش‌فاکتورهای صادرشده و وضعیت آن‌ها", "/me/proformas"],
    [Building2, "پنل سازمان", "اعتبار، گردش تأیید، سفارش‌ها و مزایای کارکنان", access.org ? "/organization" : "/org"],
    [MapPin, "شبکه‌ی فروشگاه‌های استانی", stores && stores.length ? `${toPersianNum(stores.length)} فروشگاه در ${toPersianNum(provinces)} استان` : "فروشگاه‌های طرف قرارداد برای تحویل و بازدید", "/stores"],
  ];
  return (
    <section id="org" className="scroll-mt-40 overflow-hidden rounded-lg border-2 border-mm-navy bg-white" aria-labelledby="home-org">
      <div className="flex flex-col gap-3 bg-mm-deep px-5 py-4 text-white md:flex-row md:items-center md:justify-between md:px-8">
        <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-lg bg-white/15"><Building2 className="h-6 w-6 text-honey" /></span>
          <div><h2 id="home-org" className="text-lg font-black md:text-[22px]">خرید سازمانی و عمده</h2>
            <p className="mt-0.5 text-sm text-white/75">سازمان‌ها، هتل‌ها، مساجد و هیئت‌ها، مراسم و خیریه‌ها؛ پک‌های معیشتی و مناسبتی به تعداد</p></div></div>
        {!access.loading && !access.org && <Link href="/business" className={cn(PRIMARY, "self-start md:self-auto")}>ثبت سازمان</Link>}
      </div>
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-6">
        {/* Pack-builder entry — same three routes as before (/pack-builder, ?mode=budget, ?mode=scratch); its internals are untouched. */}
        <div className="flex flex-col justify-between gap-4 rounded-lg bg-mm-mint p-5 md:p-6">
          <div><p className="text-sm font-bold text-[#2F6B4F]">پک‌ساز شصت‌آنلاین</p>
            <h3 className="mt-1 text-xl font-black leading-9 text-mm-navy md:text-2xl">بودجه یا نیازت را بگو؛ پک مناسب بساز.</h3>
            <p className="mt-2 text-[15px] leading-7 text-mm-muted">پک آماده انتخاب کنید، بر اساس بودجه بسازید یا اقلام را دستی بچینید؛ سپس خرید کنید یا پیش‌فاکتور بگیرید.</p></div>
          <div className="flex flex-wrap gap-2">
            <Link href="/pack-builder" className={PRIMARY}><Boxes className="h-4 w-4" />شروع پک‌سازی</Link>
            <Link href="/pack-builder?mode=budget" className={SECONDARY}>بر اساس بودجه</Link>
            <Link href="/pack-builder?mode=scratch" className={SECONDARY}>ساخت دستی</Link>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {tiles.map(([Icon, t, d, href]) => (
            <Link key={t} href={href} className="group flex flex-col gap-2 rounded-lg border border-[#E3E8EE] p-4 transition hover:border-mm-blue hover:shadow-md">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#EEF2F6] text-mm-blue group-hover:bg-mm-blue group-hover:text-white"><Icon className="h-5 w-5" /></span>
              <b className="text-[15px] font-black text-mm-text">{t}</b><span className="text-sm leading-6 text-mm-muted">{d}</span>
            </Link>))}
        </div>
      </div>
    </section>);
}

// ── Trust badges: only commitments the platform actually implements ───────
const TRUST: [typeof Zap, string, string, string][] = [
  [ShieldCheck, "قیمت تأییدشده", "قیمت فقط از پیشنهاد تأییدشده‌ی فروشنده؛ در غیر این صورت استعلام", "/help/buying"],
  [Undo2, "۷ روز کاری حق انصراف", "انصراف از خرید طبق قانون تجارت الکترونیکی", "/help/returns"],
  [Truck, "پیگیری سفارش", "وضعیت ارسال و تحویل هر سفارش را ببینید", "/orders"],
  [PackageCheck, "پیش‌فاکتور برای سازمان‌ها", "استعلام، پیش‌فاکتور و سفارش سازمانی در یک مسیر", "/me/proformas"],
];
function Trust() {
  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4" aria-label="تعهدهای شصت‌آنلاین">
      {TRUST.map(([Icon, t, d, href]) => (
        <Link key={t} href={href} className={cn(CARD, "flex items-center gap-3 p-4")}>
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-honey-tint text-mm-navy"><Icon className="h-6 w-6" /></span>
          <span><b className="block text-[15px] font-black text-mm-text">{t}</b><span className="mt-0.5 block text-sm leading-6 text-mm-muted">{d}</span></span>
        </Link>))}
    </section>);
}

/** Products whose photo passes the card-quality gate (null while checking). */
function useVerified(pool: Product[] | null): Product[] | null {
  const good = useGoodImages((pool ?? []).filter(hasImage).map((p) => p.image_url));
  return pool && good ? pool.filter((p) => p.image_url && good.has(p.image_url)) : null;
}

export default function FigmaHome({ previewContent }: { previewContent?: PageContent } = {}) {
  const [mode] = useShoppingMode();
  const access = useModeAccess();
  const { pool: base, cats } = useCatalog();
  const extra = useCategoryProducts(cats);
  const raw = useMemo(() => {
    if (!base || !extra) return base && cats && !cats.length ? base : null;
    const seen = new Set<number>(), out: Product[] = [];
    for (const p of [...base, ...extra]) if (!seen.has(p.id)) { seen.add(p.id); out.push(p); }
    return out;
  }, [base, extra, cats]);
  const pool = useVerified(raw);
  const inMode = useMemo(() => pool ? pool.filter(mode === "org" ? orgChannel : retail) : null, [pool, mode]);
  const today = useMemo(() => {
    if (!inMode) return null;
    const sellable = inMode.filter((p) => mode === "org" || (p.purchasable && p.price_minor && (p.stock ?? 1) > 0));
    return diversify(sellable, 4);
  }, [inMode, mode]);
  const picks = useMemo(() => inMode && today ? diversify(inMode, 15, new Set(today.map((p) => p.id))) : null, [inMode, today]);
  const catPicks = useMemo<CatPick[] | null>(() => {
    if (!cats || !pool) return null;
    const taken = new Set<string>();
    return cats.slice().sort((a, b) => b.product_count - a.product_count).map((cat) => {
      const own = pool.filter((x) => x.category?.slug === cat.slug && x.image_url);
      const p = own.find((x) => !taken.has(x.image_url!)) ?? own[0];
      if (p?.image_url) taken.add(p.image_url);
      return { cat, img: p?.image_url };
    });
  }, [cats, pool]);

  const [published, setPublished] = useState<PageContent | null>(null);
  useEffect(() => { if (previewContent) return; const c = new AbortController(); apiRequest<{ content: PageContent }>("/content/pages/homepage", { signal: c.signal }).then((r) => { if (!c.signal.aborted && Array.isArray(r.content?.blocks)) setPublished(r.content); }).catch(() => {}); return () => c.abort(); }, [previewContent]);
  const configured = previewContent ?? published;
  // The content panel can still hide a section it knows about; new sections are always shown.
  const hidden = new Set((configured?.blocks ?? []).filter((b) => b.type === "home_section" && !b.enabled).map((b) => b.key ?? ""));
  const hero = configured?.blocks.find((b) => b.key === "hero");
  const slides = useMemo<Slide[]>(() => {
    const first: Slide = { key: "main", tag: "خرید روزانه‌ی خانه", title: hero?.title || "خرید روزانه‌ی خانه،\nاز فروشندگان تأییدشده",
      body: hero?.body || "هر کالا را تکی بخرید یا برای خانواده و سازمان عمده سفارش دهید؛ قیمت فقط از پیشنهاد تأییدشده‌ی فروشنده.",
      href: hero?.link || "/category", cta: hero?.button_label || "شروع خرید", img: hero?.image_url || catPicks?.find((c) => c.img)?.img };
    const more = (catPicks ?? []).filter((c) => c.img && c.img !== first.img).slice(0, 3).map((c): Slide => ({ key: c.cat.slug, tag: "دسته‌ی پرکالا",
      title: c.cat.name, body: `${toPersianNum(c.cat.product_count)} کالا در این دسته؛ قیمت و موجودی از فروشندگان واقعی.`, href: `/category/${c.cat.slug}`, cta: "مشاهده‌ی کالاها", img: c.img }));
    return [first, ...more];
  }, [hero, catPicks]);

  const order = ["mode", "hero", "categories", "today", "packs", "picks", "brands", "club", "organization", "trust"].filter((k) => !hidden.has(k));
  const sections: Record<string, React.ReactNode> = {
    mode: <ModeStrip mode={mode} access={access} />,
    hero: <Hero slides={slides} side={<>
      <SideCard href="/packs" icon={Package} tone="mint" tag="خرید تکی یا عمده" title="پک‌های مناسبتی و معیشتی" body="یلدا، نوروز، رمضان و پک ماهانه‌ی خانواده؛ با اقلام واقعی کاتالوگ" cta="مشاهده‌ی پک‌ها" />
      <SideCard href="/assistant" icon={Sparkles} tone="honey" tag="60AI" title="دستیار خرید هوشمند" body="نیازتان را بنویسید؛ از کاتالوگ واقعی پیشنهاد پک یا کالا می‌گیرید" cta="گفت‌وگو با دستیار" />
    </>} />,
    categories: <Categories picks={catPicks} />,
    today: <Today items={today} mode={mode} />,
    packs: <Packs mode={mode} />,
    picks: <Picks items={picks} mode={mode} />,
    brands: <Booths />,
    club: <Club />,
    organization: <OrgBox access={access} />,
    trust: <Trust />,
  };
  return <div className="bg-mm-bg"><div className={WRAP} dir="rtl">{order.map((key) => <Fragment key={key}>{sections[key]}</Fragment>)}</div></div>;
}
