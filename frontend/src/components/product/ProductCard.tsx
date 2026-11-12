"use client";

import { addProductToOrgDraft } from "@/lib/procurement/draft";

import Link from "next/link";
import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { formatPrice, toPersianNum } from "@/lib/utils";
import type { Product } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { cart as cartApi, ApiError } from "@/lib/api";
import { useWishlist } from "@/lib/wishlist";

// ── Star rating ───────────────────────────────────────────────────────────────

function Stars({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <svg
          key={i}
          className={cn("w-3.5 h-3.5", i <= Math.round(rating) ? "text-amber-400" : "text-neutral-200")}
          viewBox="0 0 24 24"
          fill="currentColor"
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
      ))}
    </div>
  );
}

// ── Add to cart button ────────────────────────────────────────────────────────

function AddToCartButton({ productId, onAdd }: { productId: number; onAdd?: (id: number) => void }) {
  const { token } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [added, setAdded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handle = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!token) {
      router.push(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await cartApi.add(token, productId, 1);
      setAdded(true);
      onAdd?.(productId);
      setTimeout(() => setAdded(false), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "افزودن به سبد ناموفق بود");
      setTimeout(() => setError(null), 3000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex-shrink-0">
      <button
        onClick={handle}
        disabled={loading}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200",
          error
            ? "bg-danger-100 text-danger-700"
            : added
            ? "bg-success-100 text-success-700"
            : "bg-amber-400 text-brand-navy hover:bg-amber-300 active:scale-95",
          loading && "opacity-60 cursor-wait"
        )}
      >
        {loading ? (
          <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
        ) : added ? (
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" />
          </svg>
        )}
        {error ? "خطا" : added ? "افزوده شد" : "افزودن"}
      </button>
      {error && (
        <span className="absolute top-full mt-1 right-0 z-10 w-40 text-2xs text-danger-600 bg-white border border-danger-100 rounded-lg p-2 shadow-lg">
          {error}
        </span>
      )}
    </div>
  );
}

// ── Product card ──────────────────────────────────────────────────────────────

/** Source images under 200px (e.g. 40×40 supplier thumbnails) look broken when scaled up; show the no-image state instead. */
export const isTinyImage = (el: HTMLImageElement) => el.naturalWidth > 0 && Math.min(el.naturalWidth, el.naturalHeight) < 200;

interface ProductCardProps {
  product: Product;
  onAddToCart?: (id: number) => void;
}

/** Unpriced catalog item: add it to the organizational order draft (not a sale). */
export function ProductCard({ product, onAddToCart }: ProductCardProps) {
  const wishlist = useWishlist();
  const [imageFailed, setImageFailed] = useState(false);
  const discountPct = product.original_price_minor
    && product.price_minor != null
    ? Math.round((1 - product.price_minor / product.original_price_minor) * 100)
    : 0;
  const hasRealImage = !!product.image_url && !product.image_url.includes("picsum.photos") && !imageFailed;

  return (
    <Link
      href={`/products/${product.slug}`}
      className="group card card-hover overflow-hidden flex flex-col h-full block border-neutral-200/70"
    >
      {/* Image — fixed-height, Fit/Contain so every card reads at a consistent scale */}
      <div className={`relative overflow-hidden bg-neutral-50 flex-shrink-0 border-b border-neutral-100 ${hasRealImage ? "aspect-square" : "aspect-[5/2]"}`}>
        {hasRealImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            loading="lazy"
            decoding="async"
            src={product.image_url}
            alt={product.name}
            onError={() => setImageFailed(true)}
            onLoad={(e) => { if (isTinyImage(e.currentTarget)) setImageFailed(true); }}
            className="w-full h-full object-contain p-6 md:p-7 group-hover:scale-[1.03] transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-[radial-gradient(circle_at_30%_20%,#fff7e6,#eef3f7_70%)]" aria-hidden>
            {/* No verified photo: a compact brand/category band instead of a large empty box. */}
            <span className="flex items-center gap-2 px-3 text-right">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-base font-black text-brand-navy shadow-sm ring-1 ring-neutral-200/70">{(product.brand || product.name).slice(0, 1)}</span>
              <span className="min-w-0"><span className="block truncate text-xs font-black text-brand-navy">{product.brand || ""}</span><span className="block truncate text-[11px] text-neutral-500">{product.category?.name ?? ""}</span></span>
            </span>
          </div>
        )}

        {/* Discount badge */}
        {discountPct > 0 && (
          <span className="absolute top-2 right-2 bg-brand-coral text-white text-2xs font-bold px-1.5 py-0.5 rounded-md">
            ٪{toPersianNum(discountPct)} تخفیف
          </span>
        )}

        {/* Wishlist button */}
        <button
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); wishlist.toggle(product.slug); }}
          className={cn(
            "absolute top-2 left-2 w-8 h-8 rounded-lg bg-white/80 backdrop-blur-sm",
            "flex items-center justify-center hover:text-brand-coral",
            wishlist.has(product.slug) ? "text-brand-coral opacity-100" : "text-neutral-400 opacity-100 md:opacity-0 md:group-hover:opacity-100",
            "transition-all duration-200"
          )}
          aria-label={wishlist.has(product.slug) ? "حذف از علاقه‌مندی‌ها" : "افزودن به علاقه‌مندی‌ها"}
          aria-pressed={wishlist.has(product.slug)}
        >
          <svg className="w-4 h-4" fill={wishlist.has(product.slug) ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
              d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
          </svg>
        </button>
      </div>

      {/* Body — fixed heights on title/rating so every card ends up the same height */}
      <div className="flex flex-col flex-1 p-4 gap-2">
        {product.category && (
          <span className="text-[11px] font-medium text-neutral-500">
            {product.category.name}
          </span>
        )}

        <h3 className="text-sm font-semibold text-neutral-900 leading-snug line-clamp-2 h-10 group-hover:text-brand-blue transition-colors">
          {product.name}
        </h3>

        {(product.variant_count ?? 0) > 1 && (
          <span className="w-fit rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-bold text-sky-800 ring-1 ring-sky-100">
            {toPersianNum(product.variant_count!)} مدل/اندازه{product.variant_labels?.length ? `: ${product.variant_labels[0]} تا ${product.variant_labels[product.variant_labels.length - 1]}` : ""}
          </span>
        )}
        <div className="h-4 flex items-center gap-1.5">
          {product.rating != null && product.rating > 0 && (
            <>
              <Stars rating={product.rating} />
              <span className="text-2xs text-neutral-400">({toPersianNum(product.review_count ?? 0)})</span>
            </>
          )}
        </div>

        <div className="flex-1" />

        <div className="flex items-end justify-between gap-2 pt-1">
          <div className="flex flex-col">
            {product.price_minor != null && product.original_price_minor && product.original_price_minor > product.price_minor && (
              <span className="text-2xs text-neutral-400 line-through tabular-nums">
                {formatPrice(product.original_price_minor)}
              </span>
            )}
            {(product as { price_hidden?: boolean }).price_hidden ? (
              <a href="/business" className="inline-flex w-fit items-center rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-bold text-neutral-700">قیمت فقط برای مشتریان سازمانی</a>
            ) : product.price_minor == null && product.list_price_minor ? (
              <>
                <span className="text-[10px] font-bold text-neutral-500">آخرین قیمت اعلامی تأمین‌کننده</span>
                <span className="text-base font-black text-brand-navy tabular-nums">{product.price_from || (product.variant_count ?? 1) > 1 ? "از " : ""}{formatPrice(product.list_price_minor)}</span>
              </>
            ) : product.price_minor == null ? (
              <span className="inline-flex w-fit items-center rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-bold text-amber-700 ring-1 ring-amber-200">قیمت با استعلام</span>
            ) : (
              <span className="text-base font-black text-brand-navy tabular-nums">{product.price_from ? "از " : ""}{formatPrice(product.price_minor)}</span>
            )}
          </div>
          {product.purchasable && product.stock !== 0 && (product.variant_count ?? 1) <= 1 && <AddToCartButton productId={product.id} onAdd={onAddToCart} />}
          {product.purchasable && (product.variant_count ?? 1) > 1 && <span className="rounded-lg bg-brand-navy px-2.5 py-1.5 text-xs font-bold text-white">انتخاب اندازه</span>}
        </div>
        {product.price_minor == null && (
          <span className="flex min-h-10 items-center justify-center rounded-lg bg-[#C4461C] px-2 text-center text-xs font-bold text-white">{product.org_only ? "ویژه خرید سازمانی" : product.list_price_minor ? "انتخاب و استعلام" : "درخواست قیمت روز"}</span>
        )}

        {product.stock != null && product.stock < 10 && product.stock > 0 && (
          <p className="text-2xs text-brand-coral">تنها {toPersianNum(product.stock)} عدد باقی مانده</p>
        )}
        {product.stock === 0 && product.price_minor != null && <p className="rounded-lg bg-neutral-100 px-2 py-1 text-center text-xs font-bold text-neutral-500">در حال حاضر ناموجود</p>}
      </div>
    </Link>
  );
}

// ── Category card ─────────────────────────────────────────────────────────────

interface CategoryCardProps {
  name: string;
  href: string;
  count?: number;
  icon?: React.ReactNode;
  color?: string;
}

export function CategoryCard({ name, href, count, icon, color = "bg-brand-blueLight" }: CategoryCardProps) {
  return (
    <Link
      href={href}
      className="group card card-hover p-4 flex flex-col items-center text-center gap-3"
    >
      <div className={cn(
        "w-14 h-14 rounded-2xl flex items-center justify-center text-brand-blue transition-all duration-300",
        color,
        "group-hover:bg-brand-blue group-hover:text-white"
      )}>
        {icon ?? (
          <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
          </svg>
        )}
      </div>
      <div>
        <p className="text-sm font-semibold text-neutral-900 group-hover:text-brand-blue transition-colors">{name}</p>
        {count != null && <p className={cn("text-2xs mt-0.5", count > 0 ? "text-neutral-400" : "text-amber-600")}>{count > 0 ? `${count} محصول` : "در حال تکمیل محصولات"}</p>}
      </div>
    </Link>
  );
}

// ── Product grid ──────────────────────────────────────────────────────────────

export function ProductGrid({
  products,
  onAddToCart,
  cols = 4,
}: {
  products: Product[];
  onAddToCart?: (id: number) => void;
  cols?: 2 | 3 | 4 | 5 | 6;
}) {
  const gridCols = {
    2: "grid-cols-1 sm:grid-cols-2",
    3: "grid-cols-2 lg:grid-cols-3",
    4: "grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4",
    5: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5",
    6: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
  }[cols];

  return (
    <div className={cn("grid gap-4 md:gap-5", gridCols)}>
      {products.map((p) => (
        <ProductCard key={p.id} product={p} onAddToCart={onAddToCart} />
      ))}
    </div>
  );
}
