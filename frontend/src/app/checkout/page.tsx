"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn, formatPrice, toPersianNum } from "@/lib/utils";
import { cart as cartApi, checkout as checkoutApi, newIdempotencyKey, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Address, Cart, CheckoutQuote, PaymentMethod } from "@/lib/types";

// ── Step indicator (unchanged visual) ───────────────────────────────────────

function StepBar({ step }: { step: number }) {
  const steps = ["آدرس", "پرداخت", "تأیید"];
  return (
    <div className="flex items-center justify-center gap-0 mb-8">
      {steps.map((s, i) => (
        <div key={s} className="flex items-center">
          <div className={cn(
            "flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold transition-colors",
            i < step  ? "bg-primary-600 text-white"
            : i === step ? "bg-primary-600 text-white ring-4 ring-primary-100"
            : "bg-neutral-200 text-neutral-400"
          )}>
            {i < step ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            ) : toPersianNum(i + 1)}
          </div>
          <span className={cn("text-xs font-medium mr-2", i <= step ? "text-primary-700" : "text-neutral-400")}>{s}</span>
          {i < steps.length - 1 && (
            <div className={cn("w-12 md:w-20 h-0.5 mx-2", i < step ? "bg-primary-600" : "bg-neutral-200")} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Address step — real form, no fake saved-address picker (no such backend
//    concept exists; every order stores one real typed shipping address). ──

const EMPTY_ADDRESS: Address = {
  recipient_name: "", recipient_phone: "", province: "", city: "", line1: "", postal_code: "",
};

function AddressStep({
  address, onChange, onNext, fieldErrors,
}: {
  address: Address;
  onChange: (a: Address) => void;
  onNext: () => void;
  fieldErrors: Record<string, string>;
}) {
  const set = (k: keyof Address) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    onChange({ ...address, [k]: e.target.value });

  const valid = address.recipient_name.trim() && address.recipient_phone.trim() &&
    address.province.trim() && address.city.trim() && address.line1.trim();

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold text-neutral-900">آدرس تحویل</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="form-label">نام تحویل‌گیرنده</label>
          <input value={address.recipient_name} onChange={set("recipient_name")} className="form-input mt-1" />
          {fieldErrors.recipient_name && <p className="text-2xs text-danger-600 mt-1">{fieldErrors.recipient_name}</p>}
        </div>
        <div>
          <label className="form-label">شماره تماس</label>
          <input value={address.recipient_phone} onChange={set("recipient_phone")} dir="ltr" className="form-input mt-1" />
          {fieldErrors.recipient_phone && <p className="text-2xs text-danger-600 mt-1">{fieldErrors.recipient_phone}</p>}
        </div>
        <div>
          <label className="form-label">استان</label>
          <input value={address.province} onChange={set("province")} className="form-input mt-1" />
          {fieldErrors.province && <p className="text-2xs text-danger-600 mt-1">{fieldErrors.province}</p>}
        </div>
        <div>
          <label className="form-label">شهر</label>
          <input value={address.city} onChange={set("city")} className="form-input mt-1" />
          {fieldErrors.city && <p className="text-2xs text-danger-600 mt-1">{fieldErrors.city}</p>}
        </div>
        <div className="sm:col-span-2">
          <label className="form-label">نشانی کامل</label>
          <textarea value={address.line1} onChange={set("line1")} rows={3} className="form-input mt-1" />
          {fieldErrors.line1 && <p className="text-2xs text-danger-600 mt-1">{fieldErrors.line1}</p>}
        </div>
        <div>
          <label className="form-label">کد پستی (اختیاری)</label>
          <input value={address.postal_code} onChange={set("postal_code")} dir="ltr" className="form-input mt-1" />
        </div>
      </div>

      <button
        onClick={onNext}
        disabled={!valid}
        className="w-full py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        ادامه
      </button>
    </div>
  );
}

// ── Payment step — options shown are only those the server's own quote says
//    are real for this customer (has_organization_credit). Never offers a
//    fake credit balance to a customer with none. ─────────────────────────

function PaymentStep({
  quote, method, onMethod, onNext, onBack,
}: {
  quote: CheckoutQuote;
  method: PaymentMethod;
  onMethod: (m: PaymentMethod) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const options = [
    {
      id: "card" as const,
      title: "پرداخت آنلاین با کارت",
      desc: "پرداخت کامل از طریق درگاه بانکی",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z" />
        </svg>
      ),
    },
    ...(quote.has_organization_credit
      ? [
          {
            id: "credit" as const,
            title: "اعتبار سازمانی",
            desc: `موجودی قابل استفاده: ${formatPrice(quote.eligible_credit_minor)}`,
            icon: (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                  d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
              </svg>
            ),
          },
          {
            id: "split" as const,
            title: "ترکیبی (اعتبار + کارت)",
            desc: "ابتدا از اعتبار سازمانی، مابقی با کارت",
            icon: (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                  d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
              </svg>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-bold text-neutral-900">روش پرداخت</h2>

      <div className="space-y-3">
        {options.map((opt) => (
          <label
            key={opt.id}
            className={cn(
              "flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all",
              method === opt.id ? "border-primary-500 bg-primary-50/50" : "border-neutral-200 hover:border-neutral-300"
            )}
          >
            <input type="radio" name="payment" checked={method === opt.id} onChange={() => onMethod(opt.id)} className="accent-primary-600" />
            <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0",
              method === opt.id ? "bg-primary-100 text-primary-600" : "bg-neutral-100 text-neutral-500")}>
              {opt.icon}
            </div>
            <div>
              <p className="text-sm font-semibold text-neutral-900">{opt.title}</p>
              <p className="text-xs text-neutral-500">{opt.desc}</p>
            </div>
          </label>
        ))}
      </div>

      {/* Real, server-computed breakdown for the currently selected method */}
      <div className={cn("card p-4 bg-neutral-50 space-y-2 text-sm", method === "card" && "hidden")}>
        <p className="font-semibold text-neutral-900 mb-1">تفکیک پرداخت</p>
        <div className="flex justify-between">
          <span className="text-neutral-500">اعتبار سازمانی</span>
          <span className="font-medium text-success-600 tabular-nums">−{formatPrice(quote.credit_to_use_minor)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">پرداخت آنلاین</span>
          <span className="font-medium tabular-nums">{formatPrice(quote.cash_due_minor)}</span>
        </div>
        <div className="border-t border-neutral-200 pt-2 flex justify-between font-bold">
          <span>جمع کل</span>
          <span className="tabular-nums">{formatPrice(quote.final_payable_minor)}</span>
        </div>
      </div>

      <div className="flex gap-3">
        <button onClick={onBack} className="flex-1 py-3 rounded-xl border border-neutral-200 text-sm text-neutral-600 font-medium hover:bg-neutral-50 transition-colors">
          بازگشت
        </button>
        <button onClick={onNext} className="flex-[2] py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors">
          ادامه و تأیید
        </button>
      </div>
    </div>
  );
}

// ── Confirm step — the only step that actually calls the server to place
//    a real order. Idempotency key is generated once per checkout attempt
//    and only regenerated after a definitively-failed (not network-error)
//    attempt, so a retry after a timeout replays the same request instead
//    of risking a double order. ──────────────────────────────────────────

function ConfirmStep({
  cart, quote, address, method, onBack, token,
}: {
  cart: Cart;
  quote: CheckoutQuote;
  address: Address;
  method: PaymentMethod;
  onBack: () => void;
  token: string;
}) {
  const [placing, setPlacing] = useState(false);
  const [placedOrderNumber, setPlacedOrderNumber] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey());
  const router = useRouter();

  const handlePlace = async () => {
    setPlacing(true);
    setError(null);
    try {
      const { order } = await checkoutApi.place(token, idempotencyKey, address, method);
      setPlacedOrderNumber(order.order_number);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        // A genuine rejection (validation, stock, PSP decline) means the
        // next attempt is a real new request, not a retry of this one.
        if (err.status !== 0) setIdempotencyKey(newIdempotencyKey());
      } else {
        setError("ثبت سفارش ناموفق بود");
      }
    } finally {
      setPlacing(false);
    }
  };

  if (placedOrderNumber) {
    return (
      <div className="text-center py-8 space-y-4">
        <div className="w-20 h-20 rounded-full bg-success-100 text-success-600 flex items-center justify-center mx-auto">
          <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <div>
          <h2 className="text-xl font-black text-neutral-900">سفارش ثبت شد!</h2>
          <p className="text-sm text-neutral-500 mt-1">شماره سفارش: {placedOrderNumber}</p>
        </div>
        <p className="text-sm text-neutral-600 max-w-sm mx-auto">
          سفارش شما ثبت شد. وضعیت پرداخت را در صفحه سفارش مشاهده کنید.
        </p>
        <div className="flex justify-center gap-3 pt-2">
          <button
            onClick={() => router.push(`/orders/${placedOrderNumber}`)}
            className="px-5 py-2.5 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors"
          >
            مشاهده سفارش
          </button>
          <Link href="/" className="px-5 py-2.5 rounded-xl border border-neutral-200 text-neutral-600 font-medium text-sm hover:bg-neutral-50 transition-colors">
            بازگشت به خانه
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-bold text-neutral-900">تأیید نهایی سفارش</h2>

      {error && <p className="text-sm text-center text-danger-600 bg-danger-50 rounded-xl p-3">{error}</p>}

      <div className="card p-4 space-y-3">
        {cart.items.map((item) => (
          <div key={item.product_id} className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-lg bg-neutral-50 flex items-center justify-center text-xl flex-shrink-0">
              {item.image_emoji || "📦"}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-neutral-900 line-clamp-1">{item.title_fa}</p>
              <p className="text-xs text-neutral-400">× {toPersianNum(item.quantity)}</p>
            </div>
            <p className="text-sm font-semibold tabular-nums">{formatPrice(item.line_total_minor)}</p>
          </div>
        ))}
      </div>

      <div className="card p-4">
        <p className="text-xs font-semibold text-neutral-500 uppercase mb-1.5">آدرس تحویل</p>
        <p className="text-sm font-medium text-neutral-900">{address.recipient_name} — {address.recipient_phone}</p>
        <p className="text-xs text-neutral-500 mt-0.5">{address.province}، {address.city}، {address.line1}</p>
      </div>

      <div className="card p-4 space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-neutral-500">جمع کالاها</span>
          <span className="tabular-nums">{formatPrice(quote.cart.subtotal_minor)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">ارسال</span>
          <span className={quote.cart.shipping_fee_minor === 0 ? "text-success-600" : ""}>
            {quote.cart.shipping_fee_minor === 0 ? "رایگان" : formatPrice(quote.cart.shipping_fee_minor)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">مالیات (٪{(quote.tax_rate_bps / 100).toFixed(0)})</span>
          <span className="tabular-nums">{formatPrice(quote.tax_minor)}</span>
        </div>
        {method !== "card" && quote.credit_to_use_minor > 0 && (
          <div className="flex justify-between text-success-600">
            <span>اعتبار سازمانی</span>
            <span className="tabular-nums">−{formatPrice(quote.credit_to_use_minor)}</span>
          </div>
        )}
        <div className="border-t border-neutral-100 pt-2 flex justify-between font-bold text-neutral-900">
          <span>پرداختی نهایی</span>
          <span className="text-primary-700 text-base tabular-nums">{formatPrice(quote.cash_due_minor)}</span>
        </div>
        <p className="text-2xs text-neutral-400 text-left">
          روش پرداخت: {method === "card" ? "کارت بانکی" : method === "credit" ? "اعتبار سازمانی" : "ترکیبی"}
        </p>
      </div>

      <div className="flex gap-3">
        <button onClick={onBack} disabled={placing} className="flex-1 py-3 rounded-xl border border-neutral-200 text-sm text-neutral-600 font-medium hover:bg-neutral-50 transition-colors disabled:opacity-50">
          بازگشت
        </button>
        <button
          onClick={handlePlace}
          disabled={placing}
          className="flex-[2] py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-70"
        >
          {placing ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              در حال ثبت سفارش…
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              ثبت سفارش
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CheckoutPage() {
  const { token, loading: authLoading } = useAuth();
  const [step, setStep] = useState(0);
  const [address, setAddress] = useState<Address>(EMPTY_ADDRESS);
  const [method, setMethod] = useState<PaymentMethod>("card");
  const [cart, setCart] = useState<Cart | null>(null);
  const [quote, setQuote] = useState<CheckoutQuote | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading || !token) return;
    Promise.all([cartApi.get(token), checkoutApi.quote(token)])
      .then(([c, q]) => {
        setCart(c);
        setQuote(q);
      })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : "خطا در دریافت اطلاعات تسویه‌حساب"));
  }, [token, authLoading]);

  if (!authLoading && !token) {
    return (
      <div className="internal-page container-page py-24 text-center">
        <h2 className="text-lg font-bold text-neutral-900 mb-2">برای تسویه‌حساب وارد شوید</h2>
        <Link href="/login?next=/checkout" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors mt-2">
          ورود به حساب کاربری
        </Link>
      </div>
    );
  }

  if (loadError) {
    return <div className="internal-page container-page py-24 text-center text-danger-600">{loadError}</div>;
  }

  if (!cart || !quote) {
    return (
      <div className="internal-page container-page py-6 md:py-8 max-w-5xl">
        <div className="card p-6 h-96 animate-pulse bg-neutral-100" />
      </div>
    );
  }

  if (cart.items.length === 0) {
    return (
      <div className="internal-page container-page py-24 text-center">
        <h2 className="text-lg font-bold text-neutral-900 mb-2">سبد خرید شما خالی است</h2>
        <Link href="/search" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary-600 text-white font-semibold text-sm hover:bg-primary-700 transition-colors mt-2">
          مشاهده محصولات
        </Link>
      </div>
    );
  }

  return (
    <div className="internal-page container-page py-6 md:py-8 max-w-5xl">
      <nav className="flex items-center gap-2 text-xs text-neutral-400 mb-6">
        <Link href="/" className="hover:text-primary-600">خانه</Link>
        <span>/</span>
        <Link href="/cart" className="hover:text-primary-600">سبد خرید</Link>
        <span>/</span>
        <span className="text-neutral-600">پرداخت</span>
      </nav>

      <h1 className="text-2xl font-black text-neutral-900 mb-6">تکمیل خرید</h1>
      <StepBar step={step} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 card p-5 md:p-6">
          {step === 0 && (
            <AddressStep address={address} onChange={setAddress} onNext={() => setStep(1)} fieldErrors={{}} />
          )}
          {step === 1 && (
            <PaymentStep quote={quote} method={method} onMethod={setMethod} onNext={() => setStep(2)} onBack={() => setStep(0)} />
          )}
          {step === 2 && (
            <ConfirmStep cart={cart} quote={quote} address={address} method={method} onBack={() => setStep(1)} token={token!} />
          )}
        </div>

        {/* Mini summary sidebar — server-sourced totals, same as the address/
            payment steps use, never recomputed here. */}
        <div className="card p-4 h-fit">
          <h3 className="font-semibold text-neutral-900 mb-3 text-sm">خلاصه سفارش</h3>
          <div className="space-y-2.5 text-sm">
            {cart.items.map((item) => (
              <div key={item.product_id} className="flex justify-between gap-2">
                <span className="text-neutral-600 line-clamp-1 flex-1">{item.title_fa} × {toPersianNum(item.quantity)}</span>
                <span className="flex-shrink-0 tabular-nums font-medium">{formatPrice(item.line_total_minor)}</span>
              </div>
            ))}
            <div className="border-t border-neutral-100 pt-2 flex justify-between font-bold text-neutral-900">
              <span>مجموع</span>
              <span className="text-primary-700 tabular-nums">{formatPrice(quote.final_payable_minor)}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
