"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { cn, formatPrice, toPersianNum } from "@/lib/utils";
import { cart as cartApi, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Cart, CartItem } from "@/lib/types";

// ── Cart item row ─────────────────────────────────────────────────────────────

function CartRow({
  item,
  onQtyChange,
  onRemove,
  busy,
}: {
  item: CartItem;
  onQtyChange: (productId: number, qty: number) => void;
  onRemove: (productId: number) => void;
  busy: boolean;
}) {
  const available = item.quantity_available ?? Infinity;
  const overStock = item.quantity > available;

  return (
    <div className="flex gap-4 py-4 border-b border-neutral-100 last:border-0">
      {/* Image — real photo when the linked master product has one, same
          neutral placeholder pattern used everywhere else otherwise. */}
      <div className="w-20 h-20 md:w-24 md:h-24 flex-shrink-0 rounded-xl overflow-hidden bg-neutral-50 flex items-center justify-center text-3xl">
        {item.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={item.image_url} alt={item.title_fa} className="w-full h-full object-contain p-2" />
        ) : (
          item.image_emoji || "📦"
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <Link
          href={item.slug ? `/products/${item.slug}` : "#"}
          className="text-sm font-semibold text-neutral-900 hover:text-primary-700 transition-colors line-clamp-2"
        >
          {item.title_fa}
        </Link>
        <p className="text-sm font-bold text-neutral-900 mt-1 tabular-nums">
          {formatPrice(item.unit_price_minor)}
        </p>
        {overStock && (
          <p className="text-2xs text-danger-600 mt-1">
            فقط {toPersianNum(available)} عدد موجود است — تعداد را کاهش دهید
          </p>
        )}
      </div>

      {/* Controls */}
      <div className="flex flex-col items-end justify-between gap-2">
        {/* Qty */}
        <div className="flex items-center border border-neutral-200 rounded-lg overflow-hidden">
          <button
            disabled={busy}
            onClick={() => onQtyChange(item.product_id, item.quantity - 1)}
            className="w-8 h-8 flex items-center justify-center text-neutral-500 hover:bg-neutral-50 disabled:opacity-40"
          >
            {item.quantity === 1 ? (
              <svg className="w-3.5 h-3.5 text-danger-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.5 12h-15" />
              </svg>
            )}
          </button>
          <span className="w-8 text-center text-sm font-semibold tabular-nums">{toPersianNum(item.quantity)}</span>
          <button
            disabled={busy || item.quantity >= available}
            onClick={() => onQtyChange(item.product_id, item.quantity + 1)}
            className="w-8 h-8 flex items-center justify-center text-neutral-500 hover:bg-neutral-50 disabled:opacity-30"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </button>
        </div>

        {/* Line total */}
        <p className="text-sm font-bold text-primary-600 tabular-nums">
          {formatPrice(item.line_total_minor)}
        </p>

        {/* Remove */}
        <button
          disabled={busy}
          onClick={() => onRemove(item.product_id)}
          className="text-2xs text-neutral-400 hover:text-danger-500 transition-colors disabled:opacity-40"
        >
          حذف
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CartPage() {
  const { token, loading: authLoading } = useAuth();
  const [cart, setCart] = useState<Cart | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!token) {
      setCart(null);
      return;
    }
    cartApi
      .get(token)
      .then(setCart)
      .catch((e) => setError(e instanceof ApiError ? e.message : "خطا در دریافت سبد خرید"));
  }, [token, authLoading]);

  const handleQtyChange = async (productId: number, qty: number) => {
    if (!token) return;
    setBusyId(productId);
    setError(null);
    try {
      const updated =
        qty < 1 ? await cartApi.remove(token, productId) : await cartApi.update(token, productId, qty);
      setCart(updated);
    } catch (e) {
      // Real server-side rejection (e.g. requested qty exceeds real stock) —
      // the cart is re-fetched so the displayed quantity always matches what
      // the server actually holds, never a locally-guessed value.
      setError(e instanceof ApiError ? e.message : "به‌روزرسانی سبد ناموفق بود");
      cartApi.get(token).then(setCart).catch(() => {});
    } finally {
      setBusyId(null);
    }
  };

  const handleRemove = async (productId: number) => {
    if (!token) return;
    setBusyId(productId);
    setError(null);
    try {
      setCart(await cartApi.remove(token, productId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "حذف از سبد ناموفق بود");
    } finally {
      setBusyId(null);
    }
  };

  const handleClear = async () => {
    if (!token) return;
    setError(null);
    try {
      setCart(await cartApi.clear(token));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "پاک کردن سبد ناموفق بود");
    }
  };

  if (!authLoading && !token) {
    return (
      <div className="internal-page container-page py-24 text-center">
        <h2 className="text-lg font-bold text-neutral-900 mb-2">برای مشاهده سبد خرید وارد شوید</h2>
        <Link
          href="/login?next=/cart"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors mt-2"
        >
          ورود به حساب کاربری
        </Link>
      </div>
    );
  }

  const items = cart?.items ?? [];
  const hasStockIssue = items.some((i) => (i.quantity_available ?? Infinity) < i.quantity);

  return (
    <div className="internal-page container-page py-6 md:py-8">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-xs text-neutral-400 mb-6">
        <Link href="/" className="hover:text-primary-600">خانه</Link>
        <span>/</span>
        <span className="text-neutral-600">سبد خرید</span>
      </nav>

      <h1 className="text-2xl font-black text-neutral-900 mb-6">سبد خرید</h1>

      {error && (
        <div className="mb-4 text-sm text-danger-600 bg-danger-50 rounded-xl p-3">{error}</div>
      )}

      {cart === null ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 card p-6 h-64 animate-pulse bg-neutral-100" />
          <div className="card p-6 h-48 animate-pulse bg-neutral-100" />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-24">
          <div className="w-20 h-20 rounded-full bg-neutral-100 flex items-center justify-center mx-auto mb-4 text-neutral-300">
            <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" />
            </svg>
          </div>
          <h2 className="text-lg font-bold text-neutral-900 mb-2">سبد خرید شما خالی است</h2>
          <p className="text-sm text-neutral-500 mb-6">محصولات موردعلاقه‌تان را اضافه کنید</p>
          <Link
            href="/search"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors"
          >
            مشاهده محصولات
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Items */}
          <div className="lg:col-span-2 card p-4 md:p-6">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold text-neutral-900">
                {toPersianNum(cart.item_count)} کالا در سبد
              </h2>
              <button
                onClick={handleClear}
                className="text-xs text-neutral-400 hover:text-danger-500 transition-colors"
              >
                پاک کردن سبد
              </button>
            </div>
            {items.map((item) => (
              <CartRow
                key={item.product_id}
                item={item}
                onQtyChange={handleQtyChange}
                onRemove={handleRemove}
                busy={busyId === item.product_id}
              />
            ))}
          </div>

          {/* Summary — every number here comes straight from the server's
              cart response; nothing is computed client-side. Final tax/total
              (VAT, org credit, etc.) is computed again, authoritatively, on
              the checkout page via /checkout/quote. */}
          <div className="space-y-4">
            <div className="card p-5">
              <h2 className="font-bold text-neutral-900 mb-4">خلاصه سبد</h2>
              <div className="space-y-2.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-neutral-500">جمع کالاها</span>
                  <span className="font-medium tabular-nums">{formatPrice(cart.subtotal_minor)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-500">هزینه ارسال</span>
                  <span className={cn("font-medium tabular-nums", cart.shipping_fee_minor === 0 ? "text-success-600" : "")}>
                    {cart.shipping_fee_minor === 0 ? "رایگان" : formatPrice(cart.shipping_fee_minor)}
                  </span>
                </div>
                <p className="text-2xs text-neutral-400">مالیات در مرحله تسویه‌حساب محاسبه می‌شود</p>
              </div>

              {hasStockIssue ? (
                <p className="mt-5 text-xs text-center text-danger-600 bg-danger-50 rounded-xl p-3">
                  موجودی برخی کالاها کافی نیست — قبل از ادامه، تعداد را اصلاح کنید
                </p>
              ) : (
                <Link
                  href="/checkout"
                  className="mt-5 block w-full text-center py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors"
                >
                  ادامه و پرداخت
                </Link>
              )}
              <Link
                href="/search"
                className="mt-2 block w-full text-center py-2.5 rounded-xl text-sm text-neutral-500 hover:bg-neutral-50 transition-colors"
              >
                ادامه خرید
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
