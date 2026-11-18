"use client";

// Product listing card — faithful to Stitch 23 (desktop grid card) and 14 (mobile row card).
// Every value comes from the storefront row: price/old price/list price, brand, category, SKU, rating,
// stock, variants. Stitch's sample perks (logo printing, credit sale, tier price…) have no per-product
// data in the listing API, so they are not shown.

import Link from "next/link";
import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { cn, toPersianNum } from "@/lib/utils";
import type { Product } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { cart as cartApi, ApiError } from "@/lib/api";
import { useWishlist } from "@/lib/wishlist";

/** Source images under 200px (e.g. 40×40 supplier thumbnails) look broken when scaled up; show the no-image state instead. */
export const isTinyImage = (el: HTMLImageElement) => el.naturalWidth > 0 && Math.min(el.naturalWidth, el.naturalHeight) < 200;

/** Toman amount without the unit (the Stitch cards print «تومان» separately). */
export const toman = (minor: number) => Math.round(minor / 10).toLocaleString("fa-IR", { maximumFractionDigits: 0 });

const Icon = ({ name, className, fill }: { name: string; className?: string; fill?: boolean }) =>
  <span aria-hidden className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;

function useAddToCart(productId: number, onAdd?: (id: number) => void) {
  const { token } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<"idle" | "loading" | "added" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const add = async () => {
    if (!token) { router.push(`/login?next=${encodeURIComponent(pathname)}`); return; }
    setState("loading"); setError(null);
    try {
      await cartApi.add(token, productId, 1);
      setState("added"); onAdd?.(productId);
      setTimeout(() => setState("idle"), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "افزودن به سبد ناموفق بود");
      setState("error");
      setTimeout(() => { setState("idle"); setError(null); }, 3000);
    }
  };
  return { state, error, add };
}

type PriceView = { main: number | null; old: number | null; label: string; quote: boolean; hidden: boolean; from: boolean };
function priceView(p: Product): PriceView {
  const hidden = !!(p as { price_hidden?: boolean }).price_hidden;
  const old = p.price_minor != null && p.original_price_minor && p.original_price_minor > p.price_minor ? p.original_price_minor : null;
  const from = !!p.price_from || (p.variant_count ?? 1) > 1;
  if (hidden) return { main: null, old: null, label: "قیمت فقط برای مشتریان سازمانی", quote: true, hidden, from };
  if (p.price_minor != null) return { main: p.price_minor, old, label: from ? "قیمت از" : "قیمت هر عدد", quote: false, hidden, from };
  if (p.list_price_minor) return { main: p.list_price_minor, old: null, label: "آخرین قیمت اعلامی تأمین‌کننده", quote: false, hidden, from };
  return { main: null, old: null, label: "قیمت با استعلام", quote: true, hidden, from };
}

function tags(p: Product): string[] {
  const t: string[] = [];
  if ((p.variant_count ?? 0) > 1) t.push(`${toPersianNum(p.variant_count!)} مدل/اندازه`);
  if (p.org_only) t.push("ویژه خرید سازمانی");
  else if (p.purchasable && p.price_minor != null) t.push("قابل خرید آنلاین");
  else t.push("خرید با استعلام");
  if (p.stock != null && p.stock > 0 && p.stock < 10) t.push(`تنها ${toPersianNum(p.stock)} عدد موجود`);
  if (p.stock === 0 && p.price_minor != null) t.push("ناموجود");
  return t;
}

function Media({ p, className, imgClass }: { p: Product; className: string; imgClass: string }) {
  const [failed, setFailed] = useState(false);
  const ok = !!p.image_url && !p.image_url.includes("picsum.photos") && !failed;
  return (
    <div className={cn("relative overflow-hidden bg-st-surface-container", className)}>
      {ok ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.image_url} alt={p.name} loading="lazy" onError={() => setFailed(true)}
          onLoad={(e) => { if (isTinyImage(e.currentTarget)) setFailed(true); }}
          className={cn("h-full w-full object-contain transition-transform duration-500 group-hover:scale-105", imgClass)} />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-st-outline" role="img" aria-label={`تصویر ${p.name} ثبت نشده است`}>
          <Icon name="inventory_2" className="text-[32px]" />
          <span className="text-[11px]">تصویر ثبت نشده</span>
        </div>
      )}
    </div>
  );
}

function discountPct(p: Product) {
  return p.original_price_minor && p.price_minor != null && p.original_price_minor > p.price_minor
    ? Math.round((1 - p.price_minor / p.original_price_minor) * 100) : 0;
}

function WishButton({ slug, className }: { slug: string; className?: string }) {
  const wishlist = useWishlist();
  const on = wishlist.has(slug);
  return (
    <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); wishlist.toggle(slug); }}
      aria-label={on ? "حذف از علاقه‌مندی‌ها" : "افزودن به علاقه‌مندی‌ها"} aria-pressed={on}
      className={cn("flex h-8 w-8 items-center justify-center rounded-full bg-st-surface-container-lowest/90 shadow-sm backdrop-blur hover:text-st-on-tertiary-container",
        on ? "text-st-on-tertiary-container" : "text-st-outline", className)}>
      <Icon name="favorite" fill={on} className="text-[18px]" />
    </button>
  );
}

/** Primary action: add to cart (single purchasable SKU) · choose variant · request a quote. */
function PrimaryAction({ p, onAdd, compact }: { p: Product; onAdd?: (id: number) => void; compact?: boolean }) {
  const { state, error, add } = useAddToCart(p.id, onAdd);
  const multi = (p.variant_count ?? 1) > 1;
  const canAdd = p.purchasable && p.price_minor != null && p.stock !== 0 && !multi;
  const base = compact
    ? "flex items-center gap-1 rounded-lg px-3 py-1.5 text-st-label-md transition-colors active:scale-95"
    : "flex h-10 flex-1 items-center justify-center gap-1.5 rounded-lg text-st-label-lg font-bold transition-colors";
  const dark = "bg-st-secondary text-white hover:bg-st-navy";
  if (canAdd) return (
    <span className={cn("relative", !compact && "flex flex-1")}>
      <button type="button" onClick={add} disabled={state === "loading"}
        className={cn(base, state === "error" ? "bg-st-error-container text-st-on-error-container" : state === "added" ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : dark, state === "loading" && "cursor-wait opacity-60")}>
        <Icon name={state === "added" ? "check" : "add_shopping_cart"} className="text-[18px]" />
        <span>{state === "error" ? "خطا" : state === "added" ? "افزوده شد" : compact ? "افزودن" : "افزودن به سبد"}</span>
      </button>
      {error && <span role="alert" className="absolute right-0 top-full z-10 mt-1 w-44 rounded-lg bg-st-surface-container-lowest p-2 text-[11px] text-st-error shadow-sm">{error}</span>}
    </span>
  );
  if (p.purchasable && multi) return (
    <Link href={`/products/${p.slug}`} className={cn(base, dark)}><Icon name="tune" className="text-[18px]" /><span>انتخاب مدل</span></Link>
  );
  return (
    <Link href={`/products/${p.slug}`} className={cn(base, compact ? "bg-st-surface-container text-st-primary-container hover:bg-st-surface-container-high" : dark)}>
      <Icon name={p.org_only ? "domain" : "request_quote"} className="text-[18px]" />
      <span>{p.org_only ? "خرید سازمانی" : "استعلام قیمت"}</span>
    </Link>
  );
}

interface ProductCardProps { product: Product; onAddToCart?: (id: number) => void; layout?: "auto" | "grid" | "list" }

export function ProductCard({ product: p, onAddToCart, layout = "grid" }: ProductCardProps) {
  if (layout === "list") return <ProductRow p={p} onAdd={onAddToCart} />;
  if (layout === "auto") return <><div className="md:hidden"><ProductRow p={p} onAdd={onAddToCart} /></div><div className="hidden h-full md:block"><ProductTile p={p} onAdd={onAddToCart} /></div></>;
  return <ProductTile p={p} onAdd={onAddToCart} />;
}

/** Stitch 23 grid card. */
function ProductTile({ p, onAdd }: { p: Product; onAdd?: (id: number) => void }) {
  const pv = priceView(p);
  const pct = discountPct(p);
  return (
    <article className="group flex h-full flex-col justify-between overflow-hidden rounded-xl bg-st-surface-container-lowest shadow-st-card transition-all hover:-translate-y-0.5 hover:shadow-st-raise">
      <div className="flex flex-col">
        <div className="relative">
          <Link href={`/products/${p.slug}`} className="block" tabIndex={-1} aria-hidden>
            <Media p={p} className="m-2 aspect-[4/3] w-[calc(100%-1rem)] rounded-lg !bg-st-surface-container-low" imgClass="p-3" />
          </Link>
          {pct > 0 && <span className="absolute left-st-space-sm top-st-space-sm rounded-full bg-st-accent px-2 py-0.5 text-st-label-md font-bold text-white">٪{toPersianNum(pct)} تخفیف</span>}
          {p.brand && <span className="absolute bottom-st-space-sm right-st-space-sm flex items-center gap-1 rounded-md bg-st-surface-container-lowest/90 px-2 py-0.5 font-bold text-st-secondary shadow-sm backdrop-blur">
            <Icon name="sell" className="text-[14px]" /><span>{p.brand}</span></span>}
          <WishButton slug={p.slug} className="absolute right-st-space-sm top-st-space-sm" />
        </div>
        <div className="flex flex-col gap-1 px-3 pb-2 pt-1 text-st-body-sm">
          <div className="flex items-center justify-between text-st-outline">
            <span className="truncate">{p.sku ? <>شناسه کالا: <span dir="ltr">{p.sku}</span></> : ""}</span>
            {p.rating != null && p.rating > 0 && <div className="flex shrink-0 items-center gap-1">
              <span className="font-bold text-st-on-surface">{toPersianNum(p.rating.toFixed(1))}</span>
              <Icon name="star" fill className="text-[14px] text-amber-500" />
              <span className="text-st-outline">({toPersianNum(p.review_count ?? 0)})</span>
            </div>}
          </div>
          <h3 className="line-clamp-2 text-st-body-md font-bold leading-6 text-st-primary transition-colors group-hover:text-st-secondary">
            <Link href={`/products/${p.slug}`}>{p.name}</Link>
          </h3>
          {p.category?.name && <span className="text-st-on-surface-variant">{p.category.name}</span>}
          <div className="mt-1 flex flex-col gap-0.5 rounded-lg bg-st-surface-container-low px-2 py-1.5">
            {pv.old != null && <div className="flex items-center justify-between text-st-outline">
              <span>قیمت قبل:</span><span className="line-through">{toman(pv.old)} تومان</span></div>}
            <div className="flex items-center justify-between gap-2">
              <span className="font-bold text-st-secondary">{pv.quote ? pv.label : pv.label + ":"}</span>
              {pv.main != null ? <div className="text-left"><span className="text-st-title-md font-extrabold text-st-primary">{toman(pv.main)}</span> <span className="text-st-label-sm text-st-on-surface-variant">تومان</span></div>
                : pv.hidden ? <Link href="/business" className="text-st-secondary underline">ورود سازمانی</Link> : <Icon name="request_quote" className="text-[18px] text-st-outline" />}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1 pt-st-space-xs text-st-outline">
            {tags(p).map((t) => <span key={t} className="rounded bg-st-surface-container px-1.5 py-0.5">{t}</span>)}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1.5 p-3 pt-1">
        <PrimaryAction p={p} onAdd={onAdd} />
        <Link href={`/requests/new?slug=${encodeURIComponent(p.slug)}`} title="درخواست پیش‌فاکتور / استعلام تیراژ بالا" aria-label="درخواست پیش‌فاکتور / استعلام تیراژ بالا"
          className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-tertiary-fixed text-st-on-tertiary-fixed transition-colors hover:bg-st-accent hover:text-white">
          <Icon name="request_quote" className="text-[18px]" />
        </Link>
      </div>
    </article>
  );
}

/** Stitch 14 mobile row card. */
function ProductRow({ p, onAdd }: { p: Product; onAdd?: (id: number) => void }) {
  const pv = priceView(p);
  const pct = discountPct(p);
  const side = p.stock != null && p.stock > 0 && p.stock < 10 ? `تنها ${toPersianNum(p.stock)} عدد` : p.rating ? null : p.org_only ? "ویژه سازمانی" : (p.variant_count ?? 1) > 1 ? `${toPersianNum(p.variant_count!)} مدل` : null;
  return (
    <article className="group relative flex flex-col overflow-hidden rounded-xl bg-st-surface-container-lowest p-3 shadow-st-card">
      <div className="flex gap-st-space-md">
        <Link href={`/products/${p.slug}`} className="relative block shrink-0" tabIndex={-1} aria-hidden>
          <Media p={p} className="h-24 w-24 rounded-lg !bg-st-surface-container-low" imgClass="p-1.5" />
          {pct > 0 && <span className="absolute right-1.5 top-1.5 rounded-full bg-st-on-tertiary-container px-1.5 py-0.5 text-[10px] font-bold text-st-on-tertiary">٪{toPersianNum(pct)} تخفیف</span>}
        </Link>
        <div className="flex min-w-0 flex-1 flex-col justify-between">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-st-label-sm font-medium text-st-secondary">{p.brand || p.category?.name || ""}</span>
              {p.rating != null && p.rating > 0 ? <span className="inline-flex items-center gap-0.5 text-[11px] text-st-on-surface-variant">
                <Icon name="star" fill className="text-[13px] text-st-tertiary-fixed-dim" />{toPersianNum(p.rating.toFixed(1))}</span>
                : side ? <span className="shrink-0 text-st-label-sm text-st-outline">{side}</span> : null}
            </div>
            <h3 className="truncate text-st-title-md text-st-primary-container"><Link href={`/products/${p.slug}`}>{p.name}</Link></h3>
            <p className="line-clamp-1 text-st-body-sm text-st-on-surface-variant">{[p.category?.name, p.sku].filter(Boolean).join(" · ")}</p>
          </div>
          <div className="mt-st-space-xs flex items-end justify-between gap-2">
            <div className="flex min-w-0 flex-col">
              {pv.old != null ? <span className="text-st-label-sm text-st-outline line-through">{toman(pv.old)}</span>
                : <span className="truncate text-st-label-sm text-st-outline">{pv.main != null ? pv.label : ""}</span>}
              {pv.main != null ? <div className="flex items-baseline gap-1">
                <span className="text-st-headline-md font-extrabold text-st-primary-container">{toman(pv.main)}</span>
                <span className="text-st-label-sm text-st-on-surface-variant">تومان</span></div>
                : <span className="text-st-label-md font-bold text-st-primary-container">{pv.label}</span>}
            </div>
            <PrimaryAction p={p} onAdd={onAdd} compact />
          </div>
        </div>
      </div>
    </article>
  );
}

// ── Category card (kept for existing callers) ────────────────────────────────

interface CategoryCardProps { name: string; href: string; count?: number; icon?: React.ReactNode; color?: string }

export function CategoryCard({ name, href, count, icon }: CategoryCardProps) {
  return (
    <Link href={href} className="flex flex-col items-center gap-3 rounded-xl bg-st-surface-container-lowest p-4 text-center shadow-sm hover:shadow-md">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-st-secondary-fixed text-st-on-secondary-fixed-variant">
        {icon ?? <Icon name="category" className="text-[26px]" />}
      </div>
      <div>
        <p className="text-st-label-lg text-st-primary-container">{name}</p>
        {count != null && <p className="mt-0.5 text-st-label-sm text-st-on-surface-variant">{count > 0 ? `${toPersianNum(count)} کالا` : "در حال تکمیل کالاها"}</p>}
      </div>
    </Link>
  );
}

// ── Product grid ──────────────────────────────────────────────────────────────

export function ProductGrid({ products, onAddToCart, cols = 4, view = "grid" }: {
  products: Product[]; onAddToCart?: (id: number) => void; cols?: 2 | 3 | 4 | 5 | 6;
  /** grid = Stitch 23 tiles; list = Stitch 14 rows; auto = rows on mobile, tiles from md. */
  view?: "auto" | "grid" | "list";
}) {
  if (view === "list") return <div className="flex w-full flex-col gap-st-space-sm">{products.map((p) => <ProductCard key={p.id} product={p} onAddToCart={onAddToCart} layout="list" />)}</div>;
  const gridCols = {
    2: "md:grid-cols-2",
    3: "md:grid-cols-2 xl:grid-cols-3",
    4: "md:grid-cols-3 xl:grid-cols-4",
    5: "md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5",
    6: "md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
  }[cols];
  return (
    <div className={cn("grid gap-2.5 md:gap-3", view === "auto" ? "grid-cols-1" : "grid-cols-2", gridCols)}>
      {products.map((p) => <ProductCard key={p.id} product={p} onAddToCart={onAddToCart} layout={view} />)}
    </div>
  );
}
