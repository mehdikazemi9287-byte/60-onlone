"use client";

// Cart — Stitch screen 11 (سبد خرید, mobile 390) rebuilt faithfully; the desktop layout uses the same
// cards in the 8/4 grid of screen 24. Every number comes from the server's cart response; nothing is
// computed client-side. Final tax/credit/total is computed authoritatively on /checkout (/checkout/quote).

import { useEffect, useState } from "react";
import Link from "next/link";
import { toPersianNum } from "@/lib/utils";
// clsx, not twMerge: tailwind-merge does not know the st- font-size tokens and drops them next to st- colors.
import { clsx as cn } from "clsx";
import { cart as cartApi, ApiError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Cart, CartItem } from "@/lib/types";
import { Icon, stRoot, toman } from "@/components/checkout/st";
import { EmptyState, StepBar } from "@/components/ui/st";

// ── Cart item card (screen 11) ───────────────────────────────────────────────

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
    <div className="bg-st-surface-container-lowest rounded-2xl p-st-space-md shadow-sm relative flex flex-col gap-st-space-sm">
      <div className="flex items-start gap-st-space-md">
        {/* Thumbnail — real photo when the linked master product has one, otherwise the item's own emoji. */}
        <div className="relative w-24 h-24 rounded-xl overflow-hidden bg-st-surface-container shrink-0 flex items-center justify-center text-4xl">
          {item.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={item.image_url} alt={item.title_fa} className="w-full h-full object-contain p-2" />
          ) : (
            <span aria-hidden="true">{item.image_emoji || "📦"}</span>
          )}
        </div>
        <div className="flex flex-col flex-1 min-w-0">
          <div className="flex items-start justify-between gap-1">
            <Link
              href={item.slug ? `/products/${item.slug}` : "#"}
              className="text-st-title-md text-st-on-surface line-clamp-1 hover:text-st-secondary transition-colors"
            >
              {item.title_fa}
            </Link>
            <button
              aria-label="حذف کالا"
              disabled={busy}
              onClick={() => onRemove(item.product_id)}
              className="text-st-on-surface-variant hover:text-st-error transition-colors p-1 -mt-1 -ml-1 disabled:opacity-40"
              type="button"
            >
              <Icon name="close" className="text-[20px]" />
            </button>
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-st-label-sm text-st-on-surface-variant" dir="ltr">{item.sku}</span>
          </div>
          <div className="mt-2 flex flex-col">
            <div className="flex items-baseline gap-1 text-st-on-surface-variant text-st-body-sm">
              <span>قیمت واحد:</span>
              <span className="font-medium text-st-on-surface">{toman(item.unit_price_minor)} تومان</span>
            </div>
            {overStock && (
              <div className="flex items-center gap-1 text-st-error text-st-label-sm mt-0.5">
                <Icon name="warning" className="text-[14px]" />
                <span>فقط {toPersianNum(available)} عدد موجود است — تعداد را کاهش دهید</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between pt-st-space-xs mt-0.5">
        <div className="inline-flex items-center bg-st-surface-container-low rounded-xl p-1 gap-2 shadow-inner">
          <button
            aria-label="افزایش تعداد"
            disabled={busy || item.quantity >= available}
            onClick={() => onQtyChange(item.product_id, item.quantity + 1)}
            className="w-8 h-8 rounded-lg bg-st-surface-container-lowest text-st-primary-container flex items-center justify-center font-bold text-lg shadow-sm active:scale-95 transition-transform disabled:opacity-30"
            type="button"
          >
            +
          </button>
          <span className="text-st-title-md text-st-primary-container min-w-[28px] text-center font-semibold tabular-nums">
            {toPersianNum(item.quantity)}
          </span>
          <button
            aria-label={item.quantity === 1 ? "حذف کالا از سبد" : "کاهش تعداد"}
            disabled={busy}
            onClick={() => onQtyChange(item.product_id, item.quantity - 1)}
            className={cn(
              "w-8 h-8 rounded-lg bg-st-surface-container-lowest flex items-center justify-center font-bold text-lg shadow-sm active:scale-95 transition-transform disabled:opacity-40",
              item.quantity === 1 ? "text-st-error" : "text-st-primary-container",
            )}
            type="button"
          >
            {item.quantity === 1 ? <Icon name="delete" className="text-[18px]" /> : "-"}
          </button>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-st-label-sm text-st-on-surface-variant">مجموع ردیف</span>
          <div className="flex items-baseline gap-1">
            <span className="text-st-headline-md text-st-primary-container font-bold tabular-nums">{toman(item.line_total_minor)}</span>
            <span className="text-st-label-sm text-st-on-surface-variant font-normal">تومان</span>
          </div>
        </div>
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
      <div className={cn(stRoot, "min-h-[60vh] px-st-gutter py-24 text-center")}>
        <div className="mx-auto max-w-md bg-st-surface-container-lowest rounded-2xl p-st-space-lg shadow-sm">
          <Icon name="shopping_bag" className="text-[40px] text-st-secondary" />
          <h2 className="mt-st-space-sm text-st-title-lg text-st-primary-container">برای مشاهده سبد خرید وارد شوید</h2>
          <Link
            href="/login?next=/cart"
            className="mt-st-space-md inline-flex h-12 items-center gap-2 px-6 rounded-xl bg-st-primary-container text-st-on-primary text-st-label-lg hover:bg-st-secondary transition-colors"
          >
            ورود به حساب کاربری
          </Link>
        </div>
      </div>
    );
  }

  const items = cart?.items ?? [];
  const hasStockIssue = items.some((i) => (i.quantity_available ?? Infinity) < i.quantity);
  const freeShipping = cart?.shipping_fee_minor === 0;
  // The server's own cart total (pre-tax); never recomputed here. Tax is added on /checkout by the server quote.
  const cartTotal = cart?.total_minor;

  return (
    <div className={cn(stRoot, "min-h-[60vh] pb-48 lg:pb-st-space-xl")}>
      <div className="max-w-[1280px] mx-auto w-full lg:px-8 lg:py-st-space-xl">
        {/* Free-shipping banner — only when the server's cart says shipping is free. */}
        {cart && items.length > 0 && freeShipping && (
          <div className="px-st-gutter lg:px-0 pt-st-space-sm pb-st-space-xs lg:pb-st-space-md">
            <div className="bg-st-mint text-st-on-secondary-container rounded-xl p-3 flex items-start gap-st-space-sm ring-1 ring-st-hairline-border">
              <Icon name="local_shipping" fill className="text-[22px] text-st-mint-ink shrink-0 mt-0.5" />
              <div className="flex flex-col">
                <span className="text-st-label-lg text-st-mint-ink leading-snug">ارسال رایگان فعال شد ✓</span>
                <span className="text-st-body-sm text-st-on-surface-variant mt-0.5">
                  هزینه ارسال این سبد طبق محاسبه سرور صفر است.
                </span>
              </div>
            </div>
          </div>
        )}

        {cart && items.length > 0 && <div className="px-st-gutter lg:px-0 pt-st-space-sm">
          <StepBar className="rounded-xl bg-st-surface-container-lowest px-3 py-2.5 shadow-st-card" current={0}
            steps={[{ label: "سبد خرید", icon: "shopping_bag" }, { label: "نشانی و ارسال", icon: "local_shipping" }, { label: "پرداخت", icon: "payments" }]} />
        </div>}
        {/* Cart header meta */}
        <div className="px-st-gutter lg:px-0 py-st-space-sm flex items-center justify-between">
          <div className="flex items-center gap-st-space-xs">
            <span aria-hidden className="h-7 w-1.5 rounded-full bg-st-accent" />
            <h1 className="text-st-title-lg font-extrabold lg:text-st-headline-md text-st-primary-container">سبد خرید شما</h1>
            {cart && items.length > 0 && (
              <span className="text-st-label-sm px-2 py-0.5 rounded-full bg-st-accent text-white font-bold">
                ({toPersianNum(cart.item_count)} کالا)
              </span>
            )}
          </div>
          {cart && items.length > 0 && (
            <button
              onClick={handleClear}
              className="flex items-center gap-1 text-st-on-surface-variant hover:text-st-error transition-colors text-st-label-md py-1 px-2 rounded-lg"
              type="button"
            >
              <Icon name="delete_sweep" className="text-[18px]" />
              <span>خالی کردن سبد</span>
            </button>
          )}
        </div>

        {error && (
          <div className="mx-st-gutter lg:mx-0 mb-st-space-sm flex items-start gap-2 rounded-xl bg-st-error-container text-st-on-error-container p-st-space-sm text-st-body-sm" role="alert">
            <Icon name="error" className="text-[18px]" />
            <span>{error}</span>
          </div>
        )}

        {cart === null ? (
          <div className="px-st-gutter lg:px-0 grid grid-cols-1 lg:grid-cols-12 gap-st-space-md lg:gap-st-gutter-lg">
            <div className="lg:col-span-8 h-64 rounded-2xl bg-st-surface-container animate-pulse" />
            <div className="lg:col-span-4 h-48 rounded-2xl bg-st-surface-container animate-pulse" />
          </div>
        ) : items.length === 0 ? (
          <div className="px-st-gutter lg:px-0 py-st-space-lg">
            <EmptyState className="mx-auto max-w-md" icon="shopping_bag" title="سبد خرید شما خالی است"
              body="کالاها را از دسته‌بندی‌ها یا پک‌های آماده اضافه کنید؛ برای خرید سازمانی هم می‌توانید پیش‌فاکتور بگیرید."
              action={{ href: "/search", label: "مشاهده محصولات", icon: "storefront" }} secondary={{ href: "/packs", label: "پک‌های آماده" }} />
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-12 lg:gap-st-gutter-lg items-start">
            {/* Items */}
            <div className="lg:col-span-8 px-st-gutter lg:px-0 flex flex-col gap-st-space-md">
              {items.map((item) => (
                <CartRow
                  key={item.product_id}
                  item={item}
                  onQtyChange={handleQtyChange}
                  onRemove={handleRemove}
                  busy={busyId === item.product_id}
                />
              ))}

              {/* Coupon block — no coupon/gift-card endpoint exists for the online cart yet: shown disabled. */}
              <div className="bg-st-surface-container-lowest rounded-2xl p-st-space-md shadow-sm">
                <label className="block text-st-title-md text-st-primary-container mb-2" htmlFor="coupon-code">
                  کد تخفیف یا کارت هدیه
                </label>
                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <input
                      id="coupon-code"
                      disabled
                      className="w-full h-12 bg-st-surface-container-low rounded-xl px-4 text-right text-st-body-md text-st-on-surface placeholder:text-st-outline focus:outline-none disabled:cursor-not-allowed"
                      placeholder="ثبت کد تخفیف به‌زودی"
                      type="text"
                    />
                  </div>
                  <button disabled className="h-12 px-5 bg-st-secondary text-st-on-secondary rounded-xl text-st-label-lg opacity-50 cursor-not-allowed" type="button">
                    اعمال
                  </button>
                </div>
                <div className="flex items-center gap-1.5 mt-2.5 text-st-on-surface-variant text-st-label-sm">
                  <Icon name="info" className="text-[16px] text-st-secondary" />
                  <span>اعمال کد تخفیف روی سبد آنلاین هنوز فعال نشده است (به‌زودی).</span>
                </div>
              </div>
            </div>

            {/* Summary — server numbers only. */}
            <div className="lg:col-span-4 lg:sticky lg:top-[124px] px-st-gutter lg:px-0 mt-st-space-md lg:mt-0 flex flex-col gap-st-space-md">
              <div className="bg-st-surface-container-lowest rounded-2xl p-st-space-md shadow-sm flex flex-col gap-st-space-sm">
                <div className="flex items-center justify-between pb-st-space-xs">
                  <div className="flex items-center gap-2">
                    <Icon name="receipt_long" className="text-[20px] text-st-primary-container" />
                    <h2 className="text-st-title-lg text-st-primary-container">خلاصه سبد</h2>
                  </div>
                  <span className="text-st-label-sm text-st-secondary bg-st-secondary-fixed/50 px-2 py-0.5 rounded-full font-medium">
                    مالیات در تسویه‌حساب
                  </span>
                </div>
                <div className="flex items-center justify-between py-1 text-st-on-surface-variant text-st-body-md">
                  <span>مجموع قیمت کالاها</span>
                  <span className="font-medium text-st-on-surface tabular-nums">{toman(cart.subtotal_minor)} تومان</span>
                </div>
                <div className="flex items-center justify-between py-1 text-st-on-surface-variant text-st-body-md">
                  <span>هزینه بسته‌بندی و ارسال</span>
                  {freeShipping ? (
                    <span className="text-st-secondary font-semibold">رایگان</span>
                  ) : (
                    <span className="text-st-on-surface tabular-nums">{toman(cart.shipping_fee_minor)} تومان</span>
                  )}
                </div>
                <div className="flex items-center justify-between py-1 text-st-on-surface-variant text-st-body-md">
                  <span>مالیات بر ارزش افزوده</span>
                  <span className="text-st-on-surface text-st-body-sm">در مرحله تسویه‌حساب محاسبه می‌شود</span>
                </div>
                {cartTotal !== undefined && <div className="mt-1 bg-st-navy rounded-xl p-3 flex items-center justify-between text-white">
                  <div className="flex flex-col">
                    <span className="text-st-title-md text-white">جمع سبد</span>
                    <span className="text-st-label-sm text-st-on-navy-muted">بدون احتساب مالیات</span>
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-st-headline-lg-mobile text-white font-extrabold tabular-nums">{toman(cartTotal)}</span>
                    <span className="text-st-label-md text-st-on-navy-muted font-medium">تومان</span>
                  </div>
                </div>}

                {/* CTA bar: fixed above the site's mobile bottom nav (68px) on phones, inline on desktop. */}
                <div className="fixed bottom-[68px] md:bottom-0 inset-x-0 z-40 bg-st-surface-container-lowest/95 backdrop-blur-md shadow-[0_-4px_16px_rgba(10,39,53,0.06)] px-st-gutter py-st-space-sm lg:static lg:z-auto lg:bg-transparent lg:backdrop-blur-none lg:shadow-none lg:p-0 lg:mt-st-space-sm">
                  <div className="flex items-center justify-between gap-st-space-md max-w-lg mx-auto lg:max-w-none">
                    {cartTotal !== undefined && <div className="flex flex-col lg:hidden">
                      <span className="text-st-label-sm text-st-on-surface-variant">جمع سبد (بدون مالیات)</span>
                      <div className="flex items-baseline gap-1">
                        <span className="text-st-headline-lg-mobile text-st-primary-container font-extrabold tabular-nums">{toman(cartTotal)}</span>
                        <span className="text-st-label-sm text-st-on-surface font-normal">تومان</span>
                      </div>
                    </div>}
                    {hasStockIssue ? (
                      <p className="flex-1 text-st-label-md text-center text-st-on-error-container bg-st-error-container rounded-xl p-st-space-sm">
                        موجودی برخی کالاها کافی نیست — قبل از ادامه، تعداد را اصلاح کنید
                      </p>
                    ) : (
                      <Link
                        href="/checkout"
                        className="h-12 min-w-0 flex-1 px-4 bg-st-secondary text-white rounded-xl text-st-label-lg font-bold flex items-center justify-center gap-2 shadow-[0_10px_24px_-12px_rgb(3_78_162/0.8)] hover:bg-st-navy active:scale-[0.98] transition-all lg:w-full"
                      >
                        <span className="truncate"><span className="lg:hidden">ادامه و ثبت نشانی</span><span className="hidden lg:inline">ادامه فرایند خرید و ثبت نشانی</span></span>
                        <Icon name="arrow_back" className="text-[18px] rotate-180" />
                      </Link>
                    )}
                  </div>
                </div>

                <ProformaButton />
                <Link
                  href="/search"
                  className="block w-full text-center py-2.5 rounded-xl text-st-label-lg text-st-on-surface-variant hover:bg-st-surface-container-low transition-colors"
                >
                  ادامه خرید
                </Link>
                {/* 60AI contextual entry point — additive only. */}
                <Link
                  href="/assistant"
                  className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-st-secondary-fixed/50 py-2.5 text-st-label-md text-st-on-secondary-fixed-variant hover:bg-st-secondary-fixed transition-colors"
                >
                  <Icon name="auto_awesome" className="text-[16px]" /> هزینه را با 60AI کمتر کن
                </Link>
              </div>

              {/* Trust badges — statements that are true for the site (buyer terms: 7-day withdrawal). */}
              <div className="grid grid-cols-2 gap-st-space-sm">
                <div className="bg-st-surface-container-low rounded-xl p-3 flex items-center gap-2.5">
                  <Icon name="request_quote" className="text-st-secondary text-[22px]" />
                  <div className="flex flex-col">
                    <span className="text-st-label-md text-st-primary-container font-semibold">پیش‌فاکتور رسمی</span>
                    <span className="text-st-label-sm text-st-on-surface-variant">۷۲ ساعت معتبر</span>
                  </div>
                </div>
                <div className="bg-st-surface-container-low rounded-xl p-3 flex items-center gap-2.5">
                  <Icon name="security" className="text-st-secondary text-[22px]" />
                  <div className="flex flex-col">
                    <span className="text-st-label-md text-st-primary-container font-semibold">حق انصراف</span>
                    <span className="text-st-label-sm text-st-on-surface-variant">۷ روز کاری پس از تحویل</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ProformaButton() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const make = async () => {
    setBusy(true); setErr(null);
    try {
      const t = window.localStorage.getItem("60online_token") ?? undefined;
      const r = await apiRequest<{ number: string }>("/me/proformas", { token: t, method: "POST", body: "{}" });
      window.location.href = `/me/proformas/${encodeURIComponent(r.number)}`;
    } catch (e) { setErr(e instanceof ApiError ? e.message : "ناموفق بود"); setBusy(false); }
  };
  return (
    <>
      <button type="button" disabled={busy} onClick={make}
        className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-st-surface-container-low py-2.5 text-center text-st-label-lg text-st-primary-container hover:bg-st-surface-container disabled:opacity-50">
        <Icon name="request_quote" className="text-[18px]" />
        دریافت پیش‌فاکتور (۷۲ ساعت معتبر)
      </button>
      {err && <p role="alert" className="text-center text-st-label-md text-st-error">{err}</p>}
    </>
  );
}
