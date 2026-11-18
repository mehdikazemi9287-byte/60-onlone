"use client";

// Marketplace product page — faithful to Stitch 08 (desktop), 12 (mobile) and 20 (dark, via the site theme switch).
// Everything comes from /storefront/products/:slug — REAL products and sellers only. A price appears only from a
// seller offer whose price and stock were confirmed in the last 24h; otherwise the page offers a quote / purchase
// request instead of any estimated price. Stitch blocks without backing data (reviews, personalization, satisfaction
// score, hotline) are not rendered.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { addProductToOrgDraft } from "@/lib/procurement/draft";
import { apiRequest, cart as cartApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useOrganization } from "@/components/organization/Dashboard";
import { PRICING_MODE_FA, SALE_BLOCKER_FA, storefront, type Card, type Offer, type ProductPage, type SpecGroup } from "@/lib/storefront";
import { cn, faDate, toPersianNum } from "@/lib/utils";
import { isTinyImage, toman } from "@/components/product/ProductCard";
import { BuyBoxOffers } from "@/components/product/BuyBoxOffers";
import dark from "@/components/catalog/stitchDark.module.css";

const STOCK_FA: Record<Offer["stock_state"], string> = { in_stock: "موجود", out_of_stock: "ناموجود", unknown: "موجودی تأییدنشده" };
const Icon = ({ name, className, fill }: { name: string; className?: string; fill?: boolean }) =>
  <span aria-hidden className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;
const card = "flex flex-col rounded-xl bg-st-surface-container-lowest shadow-sm";

function StockAlert({ slug }: { slug: string }) {
  const { token } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<string | null>(null), [busy, setBusy] = useState(false);
  useEffect(() => { if (token) apiRequest<{ status: string | null }>(`/storefront/products/${encodeURIComponent(slug)}/alert`, { token }).then((r) => setStatus(r.status)).catch(() => {}); }, [token, slug]);
  const toggle = async () => {
    if (!token) { router.push(`/login?next=/products/${encodeURIComponent(slug)}`); return; }
    setBusy(true);
    try { const r = await apiRequest<{ status: string }>(`/storefront/products/${encodeURIComponent(slug)}/alert`, { token, method: status === "active" ? "DELETE" : "POST" }); setStatus(r.status); }
    catch { /* already available or not found: the page state stays honest */ } finally { setBusy(false); }
  };
  return (
    <button type="button" onClick={toggle} disabled={busy} className="flex h-11 w-full items-center justify-center gap-st-space-sm rounded-xl border border-st-outline-variant font-semibold text-st-primary disabled:opacity-60">
      <Icon name="notifications" className="text-[18px] text-st-secondary" />
      {status === "active" ? "خبرم می‌کنید ✓ (لغو)" : status === "notified" ? "موجود شد؛ اطلاع داده شد" : "موجود شد خبرم کن"}
    </button>
  );
}

function MiniCard({ c }: { c: Card }) {
  const [bad, setBad] = useState(false);
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => { const el = ref.current; if (el?.complete && (el.naturalWidth === 0 || isTinyImage(el))) setBad(true); }, []);
  return (
    <Link href={`/products/${c.slug}`} className="flex min-w-0 flex-col rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-sm shadow-[0_1px_3px_rgba(0,0,0,0.02)] transition-all hover:shadow-md">
      <span className="mb-2 flex aspect-square items-center justify-center overflow-hidden rounded-lg bg-st-surface-container-low">
        {c.image_url && !bad ? <img ref={ref} src={c.image_url} alt={c.title_fa} className="h-full w-full object-contain p-2"
          onError={() => setBad(true)} onLoad={(e) => { if (isTinyImage(e.currentTarget)) setBad(true); }} /> : <Icon name="inventory_2" className="text-[32px] text-st-outline" />}
      </span>
      <span className="line-clamp-2 min-h-[40px] text-[13px] font-semibold leading-5 text-st-primary-container">{c.title_fa}</span>
      <span className="mt-0.5 truncate text-[11px] text-st-on-surface-variant">{c.brand_fa}{c.variant_count > 1 ? ` · ${toPersianNum(c.variant_count)} مدل` : ""}</span>
      <span className="mt-1 text-st-label-lg text-st-primary">{c.price_minor != null ? `${toman(c.price_minor)} تومان` : "استعلام قیمت"}</span>
    </Link>
  );
}

function Stepper({ value, min, max, onChange, size = "md" }: { value: number; min: number; max: number; onChange: (n: number) => void; size?: "md" | "sm" }) {
  const b = cn("flex items-center justify-center rounded-lg text-lg font-bold text-st-primary transition-colors hover:bg-st-surface-container-low disabled:opacity-40", size === "sm" ? "h-8 w-8" : "h-9 w-9");
  return (
    <div className="flex items-center rounded-xl bg-st-surface-container-lowest p-1 shadow-sm">
      <button type="button" className={b} onClick={() => onChange(Math.min(max, value + 1))} disabled={value >= max} aria-label="افزایش تعداد">+</button>
      <input type="number" inputMode="numeric" min={min} max={max} value={value} aria-label="تعداد"
        onChange={(e) => onChange(Math.min(max, Math.max(min, Math.floor(Number(e.target.value)) || min)))}
        className={cn("border-0 bg-transparent p-0 text-center font-extrabold text-st-primary outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none", size === "sm" ? "w-9" : "w-12")} />
      <button type="button" className={b} onClick={() => onChange(Math.max(min, value - 1))} disabled={value <= min} aria-label="کاهش تعداد">−</button>
    </div>
  );
}

export default function ProductDetail({ initial }: { initial: ProductPage }) {
  const { token } = useAuth();
  const router = useRouter();
  const [d, setD] = useState(initial);
  const [img, setImg] = useState(0);
  const eligible = d.offers.find((o) => o.eligible);
  const moq = eligible?.min_order_quantity ?? 1;
  const maxQty = eligible?.max_order_quantity ?? (d.cta === "add_to_cart" ? 999 : 100000);
  const [qty, setQty] = useState(moq);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [orgLines, setOrgLines] = useState<number | null>(null);
  const p = d.product;
  const allowed = d.allowed_channels ?? p.allowed_channels ?? ["retail", "organization"];
  const personalAllowed = allowed.includes("retail"), orgAllowed = allowed.includes("organization");
  const [mode, setMode] = useState<"retail" | "org">(personalAllowed && !d.org_only ? "retail" : "org");
  // Broken or sub-200px source images are dropped so the gallery shows the explicit no-image state.
  const [badImages, setBadImages] = useState<string[]>([]);
  const images = p.images.filter((u) => !badImages.some((b) => b.endsWith(u)));
  const dropImage = (src: string) => { setBadImages((b) => (b.includes(src) ? b : [...b, src])); setImg(0); };
  // Server-rendered images can finish loading before hydration (no onLoad), so re-check them after mount.
  const gallery = useRef<HTMLDivElement>(null);
  useEffect(() => {
    gallery.current?.querySelectorAll("img").forEach((el) => {
      if (el.complete && (el.naturalWidth === 0 || isTinyImage(el))) dropImage(el.src);
    });
  });
  const org = useOrganization(!!token);
  const inOrg = org.orgs.length > 0;

  // Organization/contract tiers are only returned to signed-in organization members.
  useEffect(() => { if (token) storefront.product(p.slug, token).then(setD).catch(() => {}); }, [token, p.slug]);
  useEffect(() => { setImg(0); setQty(moq); setMsg(null); setOrgLines(null); }, [p.slug, moq]);

  const add = async () => {
    if (!token) { router.push(`/login?next=/products/${encodeURIComponent(p.slug)}`); return; }
    if (busy) return;
    setBusy(true); setMsg(null);
    try { await cartApi.add(token, p.sku_id, qty); setMsg({ ok: true, text: "به سبد خرید افزوده شد." }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "افزودن ناموفق بود" }); }
    finally { setBusy(false); }
  };

  const unit = d.price_minor != null ? (d.price_incl_vat_minor ?? d.price_minor) : null;
  const retailTiers = eligible?.tiers.retail ?? [], orgTiers = eligible?.tiers.organization ?? [];
  const orgFrom = orgTiers.length ? Math.min(...orgTiers.map((t) => t.unit_price_minor)) : null;
  const orgMin = orgTiers.length ? Math.min(...orgTiers.map((t) => t.min_qty)) : null;
  const tierFor = (q: number) => [...retailTiers].sort((a, b) => b.min_qty - a.min_qty).find((t) => q >= t.min_qty && (t.max_qty == null || q <= t.max_qty));
  const lineUnit = mode === "retail" && unit != null ? (tierFor(qty) ? Math.round(tierFor(qty)!.unit_price_minor * (1 + (d.vat_bps ?? 0) / 10000)) : unit) : null;
  const canBuy = mode === "retail" && d.cta === "add_to_cart";
  const specGroups = (d.spec_groups ?? []).filter((g) => g.items.length > 0);
  const requestHref = `/requests/new?slug=${encodeURIComponent(p.slug)}&quantity=${qty}`;
  const primary = () => {
    if (mode === "org") {
      if (!inOrg) { router.push("/org"); return; }
      setOrgLines(addProductToOrgDraft({ name: p.title_fa, master_product_id: p.master_product_id, image_url: p.images[0], sku: p.sku }, qty));
      return;
    }
    if (canBuy) add(); else router.push(requestHref);
  };
  const primaryLabel = mode === "org" ? (inOrg ? "افزودن به درخواست سازمانی" : "ورود به خرید سازمانی")
    : canBuy ? (busy ? "در حال افزودن…" : "افزودن به سبد خرید") : "استعلام قیمت / درخواست خرید";

  const titleBlock = (
    <div className="flex flex-col gap-st-space-xs">
      <div className="flex flex-wrap items-center gap-st-space-sm">
        {p.brand_fa && <span className="rounded-full bg-st-secondary-fixed px-st-space-sm py-1 text-st-on-secondary-fixed">{p.brand_fa}</span>}
        <span className="rounded-full bg-st-surface-container-high px-st-space-sm py-1 text-st-on-surface-variant">شناسه کالا: <span dir="ltr">{p.sku}</span></span>
        {p.variant_label && <span className="text-st-on-surface-variant">{p.variant_label}</span>}
      </div>
      <h1 className="font-bold tracking-tight text-st-primary lg:text-st-title-lg">{p.title_fa}</h1>
    </div>
  );

  return (
    <div className={cn(dark.root, "min-h-screen w-full bg-st-background pb-36 text-st-on-surface lg:pb-0")} dir="rtl">
      <div className="mx-auto w-full max-w-[1280px] lg:px-st-margin-md lg:py-st-space-lg xl:px-8">
        <nav aria-label="مسیر راهنما" className="mb-st-space-lg hidden flex-wrap items-center gap-st-space-xs text-st-on-surface-variant lg:flex">
          <Link href="/" className="transition-colors hover:text-st-primary">خانه</Link>
          {d.breadcrumbs.map((b) => <span key={b.slug} className="flex items-center gap-st-space-xs">
            <Icon name="chevron_left" className="text-[16px] text-st-outline" />
            <Link href={`/category/${b.slug}`} className="transition-colors hover:text-st-primary">{b.name_fa}</Link></span>)}
          <Icon name="chevron_left" className="text-[16px] text-st-outline" />
          <span aria-current="page" className="max-w-[24rem] truncate text-st-on-surface">{p.title_fa}</span>
        </nav>

        <div className="flex flex-col gap-st-space-md lg:grid lg:grid-cols-12 lg:items-start lg:gap-st-gutter-lg">
          {/* RIGHT COLUMN — gallery, specs, description, sellers */}
          <div className="contents lg:col-span-7 lg:flex lg:flex-col lg:gap-st-space-xl">
            <div className="hidden lg:block">{titleBlock}</div>

            <div ref={gallery} className="order-1 flex flex-col gap-st-space-sm lg:gap-st-space-md" aria-label="تصاویر کالا">
              <div className="group relative flex h-[300px] w-full items-center justify-center overflow-hidden bg-st-surface-container-lowest shadow-sm lg:h-[520px] lg:rounded-xl">
                {images[img] ? <img src={images[img]} alt={p.title_fa} className="h-full w-full object-contain p-6 transition-transform duration-700 ease-out group-hover:scale-105"
                    onError={(e) => dropImage(e.currentTarget.src)} onLoad={(e) => { if (isTinyImage(e.currentTarget)) dropImage(e.currentTarget.src); }} />
                  : <span className="flex flex-col items-center gap-2 text-st-outline"><Icon name="image" className="text-[48px]" />تصویر معتبر ثبت نشده است</span>}
                {d.price_minor != null && <div className="absolute bottom-st-space-md right-st-space-md flex items-center gap-st-space-xs rounded-xl bg-st-surface-container-lowest/95 px-st-space-md py-st-space-xs shadow-sm backdrop-blur-md">
                  <Icon name="verified" fill className="text-[20px] text-st-secondary" />
                  <div className="flex flex-col">
                    <span className="font-bold leading-tight text-st-on-surface">قیمت و موجودی تأییدشده</span>
                    <span className="text-st-label-md leading-tight text-st-on-surface-variant">اعلام فروشنده در ۲۴ ساعت اخیر</span>
                  </div>
                </div>}
                {images[img] && <a href={images[img]} target="_blank" rel="noreferrer" aria-label="بزرگ‌نمایی تصویر"
                  className="absolute left-st-space-md top-st-space-md flex h-10 w-10 items-center justify-center rounded-full bg-st-surface-container-lowest/90 text-st-on-surface-variant shadow-sm backdrop-blur-md"><Icon name="zoom_in" className="text-[20px]" /></a>}
                {images.length > 1 && <span className="absolute bottom-st-space-md left-st-space-md flex items-center gap-1 rounded-full bg-st-primary-container/80 px-2 py-0.5 text-st-label-sm text-st-on-primary lg:hidden">
                  <Icon name="photo_camera" className="text-[14px]" />{toPersianNum(img + 1)} از {toPersianNum(images.length)}</span>}
              </div>
              {images.length > 1 && <div className="flex justify-center gap-1.5 lg:hidden" aria-hidden>{images.map((u, i) => <span key={u} className={cn("h-1.5 w-1.5 rounded-full", i === img ? "bg-st-primary-container" : "bg-st-outline-variant")} />)}</div>}
              {images.length > 1 && <div className="hidden grid-cols-4 gap-st-space-sm lg:grid">{images.slice(0, 8).map((u, i) => (
                <button key={u} type="button" onClick={() => setImg(i)} aria-label={`تصویر ${toPersianNum(i + 1)}`} aria-pressed={i === img}
                  className={cn("h-24 overflow-hidden rounded-lg bg-st-surface-container-lowest p-1 shadow-sm outline-none transition-all", i === img ? "ring-2 ring-st-primary" : "opacity-70 hover:opacity-100")}>
                  <img src={u} alt="" className="h-full w-full rounded object-contain"
                    onError={(e) => dropImage(e.currentTarget.src)} onLoad={(e) => { if (isTinyImage(e.currentTarget)) dropImage(e.currentTarget.src); }} /></button>))}</div>}
            </div>

            {/* Mobile title card (Stitch 12) */}
            <div className={cn(card, "order-2 mx-st-margin gap-st-space-xs p-st-space-md lg:hidden")}>
              <div className="flex items-center justify-between gap-2">
                {p.brand_fa && <span className="text-st-label-md font-semibold text-st-secondary">{p.brand_fa}</span>}
                <span className="rounded-md bg-st-surface-container px-2 py-0.5 text-st-label-sm text-st-on-surface-variant">کد کالا: <span dir="ltr">{p.sku}</span></span>
              </div>
              <h1 className="text-st-headline-lg-mobile text-st-primary-container">{p.title_fa}</h1>
              {d.breadcrumbs.length > 0 && <nav aria-label="مسیر" className="flex flex-wrap items-center gap-1 text-st-label-sm text-st-on-surface-variant">
                {d.breadcrumbs.map((b, i) => <span key={b.slug} className="flex items-center gap-1">{i > 0 && <Icon name="chevron_left" className="text-[14px] text-st-outline" />}<Link href={`/category/${b.slug}`}>{b.name_fa}</Link></span>)}
              </nav>}
            </div>

            {(specGroups.length > 0 || p.specs.length > 0) && <div className="order-4"><SpecCard groups={specGroups} specs={p.specs} /></div>}
            {p.description_fa && <div className={cn(card, "order-5 mx-st-margin gap-st-space-md p-st-space-md lg:mx-0 lg:p-st-space-lg")}>
              <h2 className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="description" className="text-st-secondary" /><span>معرفی کالا</span></h2>
              <p className="leading-relaxed text-st-on-surface-variant">{p.description_fa}</p>
            </div>}

            <section aria-label="فروشندگان" className={cn(card, "order-6 mx-st-margin gap-st-space-md p-st-space-md lg:mx-0 lg:p-st-space-lg")}>
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="storefront" className="text-st-secondary" /><span>فروشندگان این کالا</span></h2>
                {d.offers.length > 0 && <span className="text-st-outline">{toPersianNum(d.offers.length)} پیشنهاد</span>}
              </div>
              {!d.offers.length ? (
                <p className="leading-relaxed text-st-on-surface-variant">با ثبت استعلام، درخواست شما برای تأمین‌کنندگان این کالا ارسال می‌شود و قیمت روز، موجودی و زمان تحویل به شما اعلام می‌شود.</p>
              ) : (
                <ul className="flex flex-col gap-st-space-sm">
                  {d.offers.map((o) => (
                    <li key={o.offer_id} className="flex flex-col gap-st-space-xs rounded-xl bg-st-surface-container-low p-st-space-md sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-st-space-xs font-bold text-st-on-surface">{o.seller}
                          {o.seller_city && <span className="text-st-label-md font-normal text-st-on-surface-variant">· {o.seller_city}</span>}
                          {o.eligible && <span className="rounded-full bg-st-secondary-fixed px-st-space-xs py-0.5 text-st-label-sm text-st-on-secondary-fixed">پیشنهاد منتخب</span>}
                          {o.provenance === "test" && <span className="rounded bg-violet-100 px-1.5 text-[10px] font-bold text-violet-800">TEST</span>}</p>
                        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-st-label-md text-st-on-surface-variant">
                          <span>{PRICING_MODE_FA[o.pricing_mode] ?? o.pricing_mode}</span>
                          <span className="flex items-center gap-1"><Icon name="inventory_2" className="text-[14px]" />{STOCK_FA[o.stock_state]}{o.available != null && o.stock_state === "in_stock" ? ` (${toPersianNum(o.available)})` : ""}</span>
                          <span>حداقل سفارش: {toPersianNum(o.min_order_quantity)}{o.max_order_quantity ? ` · حداکثر ${toPersianNum(o.max_order_quantity)}` : ""}</span>
                          {o.lead_time_days != null && <span className="flex items-center gap-1"><Icon name="schedule" className="text-[14px]" />تأمین {toPersianNum(o.lead_time_days)} روز</span>}
                        </p>
                        {(o.tiers.retail.length > 0 || o.tiers.organization.length > 0) && (
                          <div className="mt-2 flex flex-wrap gap-st-space-xs">
                            {o.tiers.retail.map((t, i) => <span key={`r${i}`} className="rounded bg-st-surface-container-lowest px-2 py-0.5 text-st-label-sm text-st-on-surface">{toPersianNum(t.min_qty)}{t.max_qty ? `–${toPersianNum(t.max_qty)}` : "+"} عدد: {toman(t.unit_price_minor)} تومان</span>)}
                            {o.tiers.organization.map((t, i) => <span key={`o${i}`} className="rounded bg-st-secondary-fixed px-2 py-0.5 text-st-label-sm text-st-on-secondary-fixed">سازمانی{t.contract ? " (قرارداد)" : ""} {toPersianNum(t.min_qty)}{t.max_qty ? `–${toPersianNum(t.max_qty)}` : "+"}: {toman(t.unit_price_minor)} تومان</span>)}
                          </div>)}
                      </div>
                      <div className="shrink-0 text-left">
                        {o.price_minor != null ? <span className="font-extrabold text-st-primary">{toman(o.price_minor)} <span className="text-st-label-md font-normal text-st-on-surface-variant">تومان</span></span>
                          : o.list_price_minor ? <span className="block font-extrabold text-st-primary">{toman(o.list_price_minor)} <span className="block text-[10px] font-normal text-st-on-surface-variant">قیمت فهرست{faDate(o.list_price_at) ? ` · ${faDate(o.list_price_at)}` : ""}</span></span>
                          : <span className="text-st-label-md font-bold text-st-on-tertiary-container">قیمت تأییدنشده</span>}
                      </div>
                    </li>))}
                </ul>
              )}
              {!d.sales_enabled && d.offers.some((o) => o.price_minor != null) && (
                <p className="flex items-start gap-1 text-st-label-md text-st-on-tertiary-container"><Icon name="report_problem" className="text-[18px]" /> خرید آنلاین تا اتصال درگاه پرداخت فعال نیست؛ از «درخواست خرید» استفاده کنید.</p>)}
            </section>
          </div>

          {/* LEFT COLUMN — sticky buy box (Stitch 08 / 12) */}
          <div className="order-3 flex flex-col gap-st-space-md px-st-margin lg:sticky lg:top-32 lg:col-span-5 lg:col-start-8 lg:row-start-1 lg:px-0">
            <div className={cn(card, "gap-st-space-lg p-st-space-md lg:p-st-space-lg")}>
              {eligible && <>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-st-space-sm">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-st-surface-container-low text-st-primary-container"><Icon name="storefront" className="text-[28px]" /></div>
                    <div className="flex flex-col">
                      <span className="font-bold text-st-primary">{eligible.seller}</span>
                      <span className="text-st-on-surface-variant">فروشندهٔ منتخب{eligible.seller_city ? ` · ${eligible.seller_city}` : ""}</span>
                    </div>
                  </div>
                  {d.offers.length > 1 && <span className="text-st-label-md text-st-outline">{toPersianNum(d.offers.length - 1)} فروشندهٔ دیگر</span>}
                </div>
                <div className="flex items-center gap-st-space-sm rounded-lg bg-st-surface-container-low px-st-space-md py-st-space-xs text-st-on-surface-variant">
                  <Icon name="local_shipping" className="text-[18px] text-st-secondary" />
                  <span>{STOCK_FA[eligible.stock_state]}{eligible.available != null && eligible.stock_state === "in_stock" ? ` (${toPersianNum(eligible.available)} عدد)` : ""}{eligible.lead_time_days != null ? ` | آماده‌سازی ${toPersianNum(eligible.lead_time_days)} روزه` : ""}</span>
                </div>
              </>}

              {d.variants.length > 1 && (
                <div className="flex flex-col gap-st-space-sm">
                  <span className="font-bold text-st-primary">انتخاب مدل / اندازه:</span>
                  <div className="flex flex-wrap gap-st-space-xs" role="radiogroup" aria-label="انتخاب مدل">
                    {d.variants.map((v) => (
                      <Link key={v.slug} href={`/products/${v.slug}`} role="radio" aria-checked={v.selected} scroll={false}
                        className={cn("rounded-xl px-3 py-2 font-semibold transition-colors", v.selected ? "bg-st-primary-container text-st-on-primary" : "bg-st-surface-container-low text-st-on-surface hover:bg-st-surface-container")}>
                        {v.label ?? v.title_fa}
                        {v.price_minor != null && <span className="block text-[11px] font-normal opacity-80">{toman(v.price_minor)} تومان</span>}
                      </Link>))}
                  </div>
                </div>
              )}

              <div className="flex flex-col gap-st-space-sm" role="radiogroup" aria-label="شیوه خرید">
                <span className="font-bold text-st-primary">انتخاب شیوه خرید و ساختار قیمت:</span>
                {personalAllowed && !d.org_only && (
                  <ModeOption on={mode === "retail"} onSelect={() => setMode("retail")} title="خرید تک و خانوار"
                    sub={unit != null ? "قیمت نهایی با مالیات بر ارزش افزوده" : d.list_price_minor ? `آخرین قیمت اعلامی تأمین‌کننده${faDate(d.list_price_at) ? ` · ${faDate(d.list_price_at)}` : ""}` : "قیمت پس از استعلام اعلام می‌شود"}
                    badge={retailTiers.length ? "تخفیف پلکانی" : "تک‌فروشی"} badgeHot={retailTiers.length > 0}
                    left={moq > 1 ? `حداقل سفارش: ${toPersianNum(moq)} عدد` : "بدون محدودیت حداقل تعداد"}
                    price={unit ?? d.list_price_minor ?? null} priceNote={unit == null && d.list_price_minor ? "قیمت فهرست" : undefined} />
                )}
                {orgAllowed && (
                  <ModeOption on={mode === "org"} onSelect={() => setMode("org")} title="خرید عمده و سازمانی"
                    sub="ثبت در میز سفارش سازمان و دریافت پیش‌فاکتور" badge={orgTiers.length ? "قیمت سازمانی" : "استعلام"} badgeHot={orgTiers.length > 0}
                    left={orgMin ? `حداقل سفارش: ${toPersianNum(orgMin)} عدد` : inOrg ? "قیمت پس از استعلام سازمانی" : "ویژه اعضای سازمان‌ها"}
                    price={orgFrom} priceNote={orgFrom != null ? "از" : undefined} />
                )}
                {!personalAllowed && !orgAllowed && <p className="text-st-on-surface-variant">این کالا در حال حاضر برای فروش عرضه نمی‌شود.</p>}
                {d.org_only && <p className="rounded-lg bg-st-secondary-fixed px-st-space-md py-st-space-xs text-st-label-md text-st-on-secondary-fixed">بسته‌بندی عمده / ویژه سازمان‌ها؛ فقط از مسیر خرید سازمانی قابل سفارش است.</p>}
                {mode === "retail" && unit == null && <p className="text-st-label-md leading-relaxed text-st-on-surface-variant">{SALE_BLOCKER_FA[d.sale_blocker ?? ""] ?? "خرید مستقیم این کالا فعلاً ممکن نیست."}</p>}
              </div>

              <div className="hidden flex-col gap-st-space-md rounded-xl bg-st-surface-container-low p-st-space-md lg:flex">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="font-bold text-st-primary">تعداد انتخابی:</span>
                    <span className="text-st-on-surface-variant">{mode === "org" && orgMin ? `حداقل مجاز برای تعرفه سازمانی: ${toPersianNum(orgMin)} عدد` : `حداقل سفارش: ${toPersianNum(moq)} عدد`}</span>
                  </div>
                  <Stepper value={qty} min={moq} max={maxQty} onChange={setQty} />
                </div>
                {lineUnit != null && <div className="flex items-center justify-between pt-st-space-xs">
                  <span className="font-bold text-st-on-surface">جمع کل برآورد:</span>
                  <div className="flex items-baseline gap-1"><span className="font-black tracking-tight text-st-primary">{toman(lineUnit * qty)}</span><span className="text-st-on-surface-variant">تومان</span></div>
                </div>}
              </div>

              <div className="flex flex-col gap-st-space-sm">
                {(mode === "org" ? orgAllowed : personalAllowed) && (orgLines == null || mode !== "org" ? (
                  <button type="button" onClick={primary} disabled={busy}
                    className="hidden lg:flex w-full items-center justify-center gap-st-space-sm rounded-xl bg-st-primary-container px-st-space-lg py-3.5 font-bold text-st-on-primary shadow-sm transition-all hover:bg-st-secondary active:scale-[0.99] disabled:opacity-60">
                    <Icon name={mode === "org" ? "domain" : canBuy ? "add_shopping_cart" : "request_quote"} className="text-[22px]" /><span>{primaryLabel}</span>
                  </button>
                ) : (
                  <Link href="/organization/compose" className="flex w-full items-center justify-center gap-st-space-sm rounded-xl bg-st-secondary px-st-space-lg py-3.5 font-bold text-st-on-secondary">
                    <Icon name="check_circle" className="text-[22px]" /><span>افزوده شد · ادامه در میز سفارش ({toPersianNum(orgLines)} قلم)</span></Link>
                ))}
                {personalAllowed && <Link href={requestHref}
                  className="flex h-12 w-full items-center justify-center gap-st-space-sm rounded-xl bg-st-surface-container-high px-st-space-lg py-3 font-semibold text-st-on-surface transition-all hover:bg-st-surface-variant">
                  <Icon name="request_quote" className="text-[20px] text-st-secondary" /><span>درخواست پیش‌فاکتور / استعلام تیراژ</span></Link>}
                {d.cta !== "add_to_cart" && personalAllowed && <StockAlert slug={p.slug} />}
              </div>
              {msg && <p role="status" className={cn("rounded-xl px-3 py-2", msg.ok ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-error-container text-st-on-error-container")}>{msg.text}{msg.ok && <> — <Link href="/cart" className="font-bold underline">مشاهده سبد</Link></>}</p>}

              <div className="flex flex-col gap-st-space-sm pt-st-space-xs">
                {unit != null && <div className="flex items-start gap-st-space-sm"><Icon name="verified" className="shrink-0 text-[20px] text-st-secondary" />
                  <span className="leading-relaxed text-st-on-surface-variant">قیمت و موجودی این پیشنهاد در ۲۴ ساعت اخیر توسط فروشنده تأیید شده است؛ قیمت تخمینی نمایش داده نمی‌شود.</span></div>}
                {d.vat_bps ? <div className="flex items-start gap-st-space-sm"><Icon name="receipt_long" className="shrink-0 text-[20px] text-st-secondary" />
                  <span className="leading-relaxed text-st-on-surface-variant">قیمت‌ها با احتساب {toPersianNum(d.vat_bps / 100)}٪ مالیات بر ارزش افزوده{d.unit_price ? ` · ${d.unit_price.label_fa}: ${toman(Math.round(d.unit_price.price_minor * (1 + (d.vat_bps ?? 0) / 10000)))} تومان` : ""}.</span></div> : null}
                {orgAllowed && <div className="flex items-start gap-st-space-sm"><Icon name="domain" className="shrink-0 text-[20px] text-st-secondary" />
                  <span className="leading-relaxed text-st-on-surface-variant">خرید سازمانی از مسیر میز سفارش سازمان با پیش‌فاکتور و گردش تأیید داخلی انجام می‌شود.</span></div>}
              </div>
            </div>
            <BuyBoxOffers slug={p.slug} vatBps={d.vat_bps} />
            <div className="flex items-center justify-between rounded-xl bg-st-surface-container-low p-st-space-md">
              <div className="flex items-center gap-st-space-sm">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name="support_agent" className="text-[20px]" /></div>
                <div className="flex flex-col"><span className="font-bold text-st-on-surface">پرسش دربارهٔ این کالا</span><span className="text-st-on-surface-variant">ارتباط با پشتیبانی ۶۰ آنلاین</span></div>
              </div>
              <Link href="/contact" className="rounded-lg bg-st-surface-container-lowest px-st-space-md py-st-space-xs font-bold text-st-primary shadow-sm transition-colors">تماس با ما</Link>
            </div>
          </div>
        </div>

        {d.alternatives.length > 0 && <section className="mt-st-space-xl px-st-margin lg:px-0"><h2 className="mb-st-space-sm text-st-title-lg text-st-primary-container">جایگزین‌های هم‌نوع</h2>
          <div className="grid grid-cols-2 gap-st-space-xs md:grid-cols-4 md:gap-st-space-sm">{d.alternatives.slice(0, 8).map((c) => <MiniCard key={c.slug} c={c} />)}</div></section>}
        {d.related.length > 0 && <section className="mt-st-space-xl px-st-margin pb-st-space-xl lg:px-0"><h2 className="mb-st-space-sm text-st-title-lg text-st-primary-container">کالاهای مرتبط</h2>
          <div className="grid grid-cols-2 gap-st-space-xs md:grid-cols-4 md:gap-st-space-sm">{d.related.slice(0, 8).map((c) => <MiniCard key={c.slug} c={c} />)}</div></section>}
      </div>

      {/* Mobile sticky purchase bar (Stitch 12) — sits above the site's bottom navigation. */}
      {(mode === "org" ? orgAllowed : personalAllowed) && (
        <div className="fixed inset-x-0 bottom-[68px] z-50 border-t border-st-surface-container bg-st-surface-container-lowest/95 px-st-margin py-st-space-sm shadow-[0_-6px_20px_rgba(0,0,0,0.06)] backdrop-blur-xl lg:hidden">
          <div className="flex items-center gap-st-space-sm">
            <Stepper value={qty} min={moq} max={maxQty} onChange={setQty} size="sm" />
            {mode === "org" && orgLines != null ? (
              <Link href="/organization/compose" className="flex h-12 flex-1 items-center justify-center gap-1 rounded-xl bg-st-secondary px-3 text-st-label-lg text-st-on-secondary">ادامه در میز سفارش ({toPersianNum(orgLines)})</Link>
            ) : (
              <button type="button" onClick={primary} disabled={busy}
                className="flex h-12 flex-1 items-center justify-between gap-2 rounded-xl bg-st-primary-container px-st-space-md text-st-on-primary disabled:opacity-60">
                <span className="flex items-center gap-1 text-st-label-lg"><Icon name={mode === "org" ? "domain" : canBuy ? "add_shopping_cart" : "request_quote"} className="text-[20px]" />{canBuy ? (busy ? "…" : "افزودن به سبد") : mode === "org" ? "خرید سازمانی" : "استعلام قیمت"}</span>
                {lineUnit != null && <span className="text-st-label-md"><b className="text-st-title-md">{toman(lineUnit * qty)}</b> تومان</span>}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ModeOption({ on, onSelect, title, sub, badge, badgeHot, left, price, priceNote }: {
  on: boolean; onSelect: () => void; title: string; sub: string; badge: string; badgeHot: boolean; left: string; price: number | null; priceNote?: string;
}) {
  return (
    <label className={cn("relative flex cursor-pointer flex-col gap-st-space-xs rounded-xl bg-st-surface-container-low p-st-space-md transition-all", on ? "ring-2 ring-st-primary-container" : "opacity-80 hover:opacity-100")}>
      <input type="radio" className="sr-only" checked={on} onChange={onSelect} />
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-st-space-sm">
          <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full", on ? "bg-st-primary" : "bg-st-surface-container-high")}><span className={cn("h-2 w-2 rounded-full", on ? "bg-st-on-primary" : "bg-transparent")} /></span>
          <div className="flex flex-col"><span className="font-bold text-st-primary">{title}</span><span className="text-st-label-md text-st-on-surface-variant">{sub}</span></div>
        </div>
        <span className={cn("shrink-0", badgeHot ? "rounded-full bg-st-tertiary-container px-2 py-0.5 text-st-label-sm font-bold text-st-on-tertiary" : "text-st-label-md text-st-outline")}>{badge}</span>
      </div>
      <div className="mt-st-space-xs flex items-baseline justify-between pt-st-space-xs">
        <span className="text-st-label-md font-medium text-st-on-surface-variant">{left}</span>
        {price != null ? <div className="flex items-baseline gap-1">{priceNote && <span className="text-st-label-sm text-st-on-surface-variant">{priceNote}</span>}
          <span className="font-extrabold tracking-tight text-st-primary">{toman(price)}</span><span className="text-st-label-md text-st-on-surface-variant">تومان</span></div>
          : <span className="text-st-label-md font-bold text-st-secondary">با استعلام</span>}
      </div>
    </label>
  );
}

/** Specification card (Stitch 08 «مشخصات فنی…»): typed spec groups as tiles; legacy specs as a fallback. */
function SpecCard({ groups, specs }: { groups: SpecGroup[]; specs: { label: string; value: unknown }[] }) {
  const tiles = groups.length ? groups : [{ group_fa: "", items: specs.map((s, i) => ({ code: String(i), label_fa: s.label, value_fa: typeof s.value === "object" ? JSON.stringify(s.value) : String(s.value) })) }];
  return (
    <div className="mx-st-margin flex flex-col gap-st-space-lg rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm lg:mx-0 lg:p-st-space-lg">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="inventory_2" className="text-st-secondary" /><span>مشخصات فنی</span></h2>
        <span className="text-st-label-md text-st-outline">از منبع رسمی برند</span>
      </div>
      {tiles.map((g) => (
        <div key={g.group_fa || "specs"} className="flex flex-col gap-st-space-sm">
          {g.group_fa && <span className="font-bold text-st-primary">{g.group_fa}:</span>}
          <dl className="grid grid-cols-1 gap-st-space-sm md:grid-cols-2 md:gap-st-space-md">
            {g.items.map((i) => (
              <div key={i.code} className="flex flex-col gap-st-space-xs rounded-lg bg-st-surface-container-low p-st-space-md">
                <dt className="text-st-on-surface-variant">{i.label_fa}</dt>
                <dd className="break-words font-bold text-st-on-surface">{i.value_fa}</dd>
              </div>))}
          </dl>
        </div>
      ))}
    </div>
  );
}
