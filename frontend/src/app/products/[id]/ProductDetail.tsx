"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { cn, formatPrice, toPersianNum } from "@/lib/utils";
import { catalog, cart as cartApi, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Product } from "@/lib/types";
import { ProductMedia } from "@/components/product/ProductMedia";

// Real product-detail integration: the [id] route segment is actually the
// product's real slug (matches ProductCard's link and the backend's
// slug-keyed GET /api/v1/products/:slug). Nothing here is fabricated — a
// missing field (image/brand/description) is shown as an honest empty
// state, never invented.

function Stars({
  rating,
  size = "md",
}: {
  rating: number;
  size?: "sm" | "md";
}) {
  const w = size === "sm" ? "w-3.5 h-3.5" : "w-5 h-5";
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <svg
          key={i}
          className={cn(
            w,
            i <= Math.round(rating) ? "text-amber-400" : "text-neutral-200",
          )}
          viewBox="0 0 24 24"
          fill="currentColor"
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
      ))}
    </div>
  );
}

export default function ProductDetailPage({
  initialProduct,
}: {
  initialProduct: Product;
}) {
  const params = useParams<{ id: string }>();
  const slug = params.id;
  const router = useRouter();
  const { token } = useAuth();

  const [product, setProduct] = useState<Product | null>(initialProduct);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [qty, setQty] = useState(1);
  const [addedToCart, setAddedToCart] = useState(false);
  const [cartError, setCartError] = useState<string | null>(null);
  const [addingToCart, setAddingToCart] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setProduct(initialProduct);
    setNotFound(false);
    setError(null);
    setQty(1);

    catalog
      .get(slug)
      .then((res) => {
        if (!cancelled) setProduct(res.product);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e?.status === 404) setNotFound(true);
        else
          setError(
            e instanceof Error ? e.message : "خطا در دریافت اطلاعات محصول",
          );
      });

    return () => {
      cancelled = true;
    };
  }, [slug]);

  const handleAddToCart = async (goToCheckout = false) => {
    if (!product) return;
    if (!token) {
      router.push(`/login?next=${encodeURIComponent(`/products/${slug}`)}`);
      return;
    }
    setCartError(null);
    setAddingToCart(true);
    try {
      await cartApi.add(token, product.id, qty);
      if (goToCheckout) {
        router.push("/checkout");
        return;
      }
      setAddedToCart(true);
      setTimeout(() => setAddedToCart(false), 2500);
    } catch (err) {
      // Real server-side rejection (e.g. out of stock right now) — never
      // shown as a fake success.
      setCartError(
        err instanceof ApiError ? err.message : "افزودن به سبد ناموفق بود",
      );
    } finally {
      setAddingToCart(false);
    }
  };

  if (notFound) {
    return (
      <div className="container-page py-20 text-center text-neutral-400">
        <p className="font-medium">این محصول یافت نشد</p>
        <Link
          href="/search"
          className="text-brand-blue text-sm mt-2 inline-block"
        >
          بازگشت به محصولات
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container-page py-20 text-center text-neutral-400">
        <p className="font-medium">خطا در بارگذاری محصول</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (!product) {
    return (
      <div className="product-detail container-page py-6 md:py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">
          <div className="card aspect-[4/3] animate-pulse bg-neutral-100" />
          <div className="space-y-3">
            <div className="h-6 w-2/3 bg-neutral-100 rounded animate-pulse" />
            <div className="h-4 w-1/3 bg-neutral-100 rounded animate-pulse" />
            <div className="h-10 w-1/2 bg-neutral-100 rounded animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  const discount =
    product.original_price_minor && product.price_minor != null
      ? Math.round(
          (1 - product.price_minor / product.original_price_minor) * 100,
        )
      : 0;
  const stock = product.purchasable ? (product.stock ?? null) : null;

  return (
    <div className="product-detail container-page py-6 md:py-8">
      {/* Breadcrumb */}
      <nav aria-label="مسیر صفحه" className="flex flex-wrap items-center gap-2 text-xs text-neutral-600 mb-6">
        <Link href="/" className="hover:text-primary-600 transition-colors">
          خانه
        </Link>
        <span>/</span>
        <Link
          href="/search"
          className="hover:text-primary-600 transition-colors"
        >
          محصولات
        </Link>
        {product.category && (
          <>
            <span>/</span>
            <Link
              href={`/category/${product.category.slug}`}
              className="hover:text-primary-600 transition-colors"
            >
              {product.category.name}
            </Link>
          </>
        )}
        <span>/</span>
        <span className="text-neutral-600 truncate max-w-[200px]">
          {product.name}
        </span>
      </nav>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12 mb-10">
        {/* ── Image ──────────────────────────────────────────────────────────── */}
        <div>
          <ProductMedia src={product.image_url} name={product.name} priority className="product-detail-media" />
        </div>

        {/* ── Info ────────────────────────────────────────────────────────────── */}
        <div className="product-detail-info flex flex-col gap-4">
          {/* Category / brand */}
          <div className="flex items-center gap-2 text-xs">
            {product.category && (
              <span className="text-primary-600 font-medium">
                {product.category.name}
              </span>
            )}
            {product.brand && (
              <>
                <span className="text-neutral-300">|</span>
                <span className="text-neutral-500">برند: {product.brand}</span>
              </>
            )}
          </div>

          {/* Name */}
          <h1 className="product-detail-title">
            {product.name}
          </h1>

          {/* Rating — only shown when the backend actually returned one */}
          {product.rating != null && product.rating > 0 && (
            <div className="flex items-center gap-3">
              <Stars rating={product.rating} />
              <span className="text-sm font-semibold text-neutral-700">
                {toPersianNum(product.rating.toFixed(1))}
              </span>
            </div>
          )}

          {/* Price */}
          <div className="product-detail-price flex flex-wrap items-center gap-3">
            <span className="text-3xl font-black text-neutral-900 tabular-nums">
              {product.price_minor == null
                ? "استعلام قیمت"
                : formatPrice(product.price_minor)}
            </span>
            {discount > 0 && (
              <div className="flex flex-col items-end">
                <span className="text-sm text-neutral-400 line-through tabular-nums">
                  {formatPrice(product.original_price_minor!)}
                </span>
                <span className="text-xs font-bold text-brand-navy bg-accent-500 px-2 py-0.5 rounded-md">
                  ٪{discount} تخفیف
                </span>
              </div>
            )}
          </div>

          {/* Stock — only rendered when the backend reported a real stock/status value */}
          {stock != null && (
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "w-2 h-2 rounded-full flex-shrink-0",
                  stock > 0 ? "bg-success-500" : "bg-danger-500",
                )}
              />
              <span className="text-sm text-neutral-600">
                {stock > 0
                  ? stock < 10
                    ? `تنها ${toPersianNum(stock)} عدد در انبار`
                    : "موجود در انبار"
                  : "ناموجود"}
              </span>
            </div>
          )}

          {/* Qty + Add to cart */}
          {product.purchasable && stock !== 0 ? (
            <div className="flex flex-col gap-3 pt-2 sm:flex-row sm:items-center">
              <div className="flex items-center border border-neutral-200 rounded-xl overflow-hidden">
                <button
                  aria-label="کاهش تعداد"
                  onClick={() => setQty(Math.max(1, qty - 1))}
                  className="w-11 h-11 flex items-center justify-center text-neutral-500 hover:bg-neutral-50 transition-colors"
                >
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19.5 12h-15"
                    />
                  </svg>
                </button>
                <span className="w-10 text-center text-sm font-semibold text-neutral-900 tabular-nums">
                  {toPersianNum(qty)}
                </span>
                <button
                  aria-label="افزایش تعداد"
                  onClick={() =>
                    setQty(Math.min(stock && stock > 0 ? stock : 99, qty + 1))
                  }
                  className="w-11 h-11 flex items-center justify-center text-neutral-500 hover:bg-neutral-50 transition-colors"
                >
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 4.5v15m7.5-7.5h-15"
                    />
                  </svg>
                </button>
              </div>

              <button
                onClick={() => handleAddToCart(false)}
                disabled={stock === 0 || addingToCart}
                className={cn(
                  "flex-1 h-11 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all",
                  addedToCart
                    ? "bg-success-500 text-white"
                    : "bg-brand-navy text-white hover:bg-brand-blue",
                  (stock === 0 || addingToCart) &&
                    "opacity-50 cursor-not-allowed",
                )}
              >
                {addingToCart ? (
                  <svg
                    className="w-4 h-4 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8v8H4z"
                    />
                  </svg>
                ) : addedToCart ? (
                  <>
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2.5}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                    افزوده شد به سبد
                  </>
                ) : (
                  <>
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z"
                      />
                    </svg>
                    افزودن به سبد
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={() => handleAddToCart(true)}
                disabled={stock === 0 || addingToCart}
                className="h-11 px-4 rounded-xl border-2 border-primary-600 text-primary-700 font-semibold text-sm flex items-center justify-center hover:bg-primary-50 transition-colors"
              >
                خرید فوری
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4 text-sm font-semibold text-neutral-600">
              {stock === 0
                ? "این کالا در حال حاضر ناموجود است و امکان خرید ندارد."
                : "قیمت و موجودی این کالا نیازمند استعلام است."}
            </div>
          )}

          {cartError && <p role="alert" className="text-sm text-danger-600">{cartError}</p>}

          <Link
            href={"/requests/new?slug=" + encodeURIComponent(product.slug)}
            className="mt-4 inline-flex min-h-12 items-center rounded-xl bg-primary-600 px-5 font-bold text-white"
          >
            استعلام قیمت و شرایط تأمین
          </Link>

          {product.sku && (
            <p className="text-xs text-neutral-400">کد محصول: {product.sku}</p>
          )}
        </div>
      </div>

      {/* ── Description ──────────────────────────────────────────────────────── */}
      <div className="product-detail-description">
        <h2 className="text-lg font-bold text-neutral-900 mb-3">
          توضیحات محصول
        </h2>
        {product.description ? (
          <p className="text-sm text-neutral-600 leading-7">
            {product.description}
          </p>
        ) : (
          <p className="text-sm text-neutral-400">
            توضیحاتی برای این محصول ثبت نشده است.
          </p>
        )}
      </div>
    </div>
  );
}
