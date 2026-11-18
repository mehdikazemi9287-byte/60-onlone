"use client";

// Checkout — Stitch screens 24 (desktop 1440), 29 (mobile 390) and 09 (desktop dark, via the site's
// html[data-theme=dark] switch) rebuilt faithfully. PRESENTATION ONLY: the order-placing logic is the
// same as before this redesign — server-authoritative quote, one idempotency key per attempt (renewed
// only after a definitive rejection), buyer-terms acceptance, welfare opt-in, card/external-credit
// provider choice, org credit (credit / split), ?proforma= pass-through, bank redirect (Sepehr two-step
// via goToPaymentGateway), the "gateway unavailable" purchase-request fallback and ?payment=failed notices.
// Stitch blocks with no backend (delivery time slots, legal-entity tax profile toggle) degrade honestly.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toPersianNum } from "@/lib/utils";
// clsx, not twMerge: tailwind-merge does not know the st- font-size tokens and drops them next to st- colors.
import { clsx as cn } from "clsx";
import { cart as cartApi, checkout as checkoutApi, newIdempotencyKey, ApiError, apiRequest, goToPaymentGateway } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { Address, Cart, CheckoutQuote, PaymentMethod } from "@/lib/types";
import { Icon, stRoot, toman } from "@/components/checkout/st";

type PayOption = { provider: string; kind: string; label: string; note?: string };

const EMPTY_ADDRESS: Address = {
  recipient_name: "", recipient_phone: "", province: "", city: "", line1: "", postal_code: "",
};
const addressValid = (a: Address) =>
  !!(a.recipient_name.trim() && a.recipient_phone.trim() && a.province.trim() && a.city.trim() && a.line1.trim());

// ── Shared card chrome (screen 24 card; on phones screen 29 puts the title above the card) ────────────

function Card({ icon, title, aside, children }: { icon: string; title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="lg:bg-st-surface-container-lowest lg:rounded-xl lg:p-5 lg:shadow-st-card">
      <div className="flex items-center justify-between gap-st-space-sm mb-st-space-xs lg:mb-st-space-md">
        <div className="flex items-center gap-st-space-xs lg:gap-st-space-sm">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-st-secondary-fixed text-st-secondary lg:h-9 lg:w-9"><Icon name={icon} className="text-[18px] lg:text-[20px]" /></span>
          <h2 className="text-st-title-md lg:text-base text-st-primary-container lg:text-st-primary font-bold">{title}</h2>
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Radio({ on }: { on: boolean }) {
  return (
    <span className={cn("w-5 h-5 rounded-full flex items-center justify-center mt-1 shrink-0 border-2",
      on ? "border-st-secondary bg-st-secondary" : "border-st-outline-variant bg-st-surface-container-lowest")}>
      <span className={cn("w-2 h-2 rounded-full", on ? "bg-st-on-secondary" : "bg-transparent")} />
    </span>
  );
}

/** Selectable option row: own white card on phones (29), tinted row inside the section card on desktop (24). */
function Option({ on, onSelect, name, children }: { on: boolean; onSelect: () => void; name: string; children: React.ReactNode }) {
  return (
    <label className={cn(
      "flex items-start gap-st-space-sm lg:gap-st-space-md p-st-space-md rounded-xl cursor-pointer transition-all",
      on ? "st-selected bg-st-secondary-fixed/40 shadow-md lg:shadow-none lg:bg-st-surface-container-low"
         : "bg-st-surface-container-lowest shadow-sm lg:shadow-none lg:bg-st-surface hover:bg-st-surface-container-low",
    )}>
      <input type="radio" name={name} checked={on} onChange={onSelect} className="sr-only" />
      <Radio on={on} />
      <div className="flex flex-col gap-st-space-xs flex-1 min-w-0">{children}</div>
    </label>
  );
}

// ── Stepper (24 desktop, 29 mobile) ─────────────────────────────────────────────────────────────────

function Stepper({ addressDone }: { addressDone: boolean }) {
  const steps = [
    { label: "سبد خرید", sub: "مرحله ۱ (تکمیل شد)", icon: "check", state: "done" as const },
    { label: "نشانی و زمان ارسال", sub: addressDone ? "مرحله ۲ (تکمیل شد)" : "مرحله جاری", icon: "local_shipping", state: addressDone ? "done" as const : "active" as const },
    { label: "پرداخت و فاکتور نهایی", sub: addressDone ? "مرحله جاری" : "مرحله نهایی", icon: "receipt_long", state: addressDone ? "active" as const : "todo" as const },
  ];
  return (
    <>
      <section className="hidden lg:block w-full mb-5">
        <div className="bg-st-navy text-white rounded-xl px-6 py-4 shadow-st-raise flex items-center justify-between relative overflow-hidden">
          <div className="absolute -left-10 -top-16 h-40 w-40 rounded-full bg-st-accent/20 blur-3xl pointer-events-none" />
          {steps.map((s, i) => (
            <div key={s.label} className="contents">
              <div className={cn("flex items-center gap-st-space-sm z-10", s.state === "todo" && "opacity-60")}>
                <div className={cn("w-10 h-10 rounded-full flex items-center justify-center font-bold",
                  s.state === "done" && "bg-st-secondary text-white",
                  s.state === "active" && "bg-st-accent text-white ring-4 ring-st-accent/25",
                  s.state === "todo" && "bg-white/10 text-st-on-navy-muted")}>
                  {s.state === "done" ? <Icon name="check" className="text-[20px]" /> : <span className="leading-none">{toPersianNum(i + 1)}</span>}
                </div>
                <div className="flex flex-col">
                  <span className={cn("text-st-label-md", s.state === "active" ? "text-st-accent font-bold" : "text-st-on-navy-muted")}>{s.sub}</span>
                  <span className={s.state === "todo" ? "text-st-on-navy-muted" : "text-white font-bold"}>{s.label}</span>
                </div>
              </div>
              {i < steps.length - 1 && (
                <div className={cn("flex-1 h-0.5 mx-st-space-md", steps[i + 1].state === "todo" ? "bg-white/15" : "bg-st-accent/70")} />
              )}
            </div>
          ))}
        </div>
      </section>
      <section className="lg:hidden pt-st-space-md pb-st-space-sm">
        <div className="bg-st-surface-container-lowest rounded-xl p-3 shadow-st-card">
          <div className="relative flex items-center justify-between">
            <div className="absolute top-4 left-6 right-6 -translate-y-1/2 h-0.5 bg-st-surface-container-high z-0">
              <div className={cn("h-full bg-st-secondary transition-all duration-300", addressDone ? "w-full" : "w-1/2")} />
            </div>
            {steps.map((s) => (
              <div key={s.label} className="relative z-10 flex flex-col items-center gap-st-space-xs">
                <div className={cn("w-8 h-8 rounded-full flex items-center justify-center",
                  s.state === "done" && "bg-st-secondary text-st-on-secondary shadow-sm",
                  s.state === "active" && "bg-st-navy text-white shadow-sm ring-4 ring-st-accent/30",
                  s.state === "todo" && "bg-st-surface-container-high text-st-outline")}>
                  <Icon name={s.state === "done" ? "check" : s.icon} className={s.state === "done" ? "text-[18px]" : "text-[16px]"} />
                </div>
                <span className={cn("text-st-label-sm", s.state === "done" ? "text-st-secondary font-bold" : s.state === "active" ? "text-st-primary-container font-bold" : "text-st-outline")}>
                  {s.label === "پرداخت و فاکتور نهایی" ? "پرداخت و فاکتور" : s.label === "نشانی و زمان ارسال" ? "نشانی و ارسال" : s.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

// ── Address — real typed form (no saved-address backend exists); collapses to the Stitch summary card. ─

function AddressCard({ address, onChange, editing, setEditing }: {
  address: Address; onChange: (a: Address) => void; editing: boolean; setEditing: (v: boolean) => void;
}) {
  const set = (k: keyof Address) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    onChange({ ...address, [k]: e.target.value });
  const valid = addressValid(address);
  const input = "form-input mt-1 !h-12 !rounded-xl !border-transparent !bg-st-surface-container-low !text-st-on-surface";
  const label = "text-st-label-md text-st-on-surface-variant";

  return (
    <Card
      icon="location_on"
      title="نشانی تحویل‌گیرنده"
      aside={!editing && (
        <button type="button" onClick={() => setEditing(true)} className="lg:hidden flex items-center gap-st-space-xs text-st-label-md font-semibold text-st-secondary hover:text-st-on-secondary-container transition-colors">
          <span>+ تغییر نشانی</span>
        </button>
      )}
    >
      {editing ? (
        <div className="bg-st-surface-container-lowest shadow-sm lg:shadow-none lg:bg-st-surface rounded-xl p-st-space-md">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-st-space-md">
            <div>
              <label className={label}>نام تحویل‌گیرنده</label>
              <input value={address.recipient_name} onChange={set("recipient_name")} className={input} autoComplete="name" />
            </div>
            <div>
              <label className={label}>شماره تماس</label>
              <input value={address.recipient_phone} onChange={set("recipient_phone")} dir="ltr" className={input} autoComplete="tel" inputMode="tel" />
            </div>
            <div>
              <label className={label}>استان</label>
              <input value={address.province} onChange={set("province")} className={input} />
            </div>
            <div>
              <label className={label}>شهر</label>
              <input value={address.city} onChange={set("city")} className={input} />
            </div>
            <div className="sm:col-span-2">
              <label className={label}>نشانی کامل</label>
              <textarea value={address.line1} onChange={set("line1")} rows={3} className="form-input mt-1 !rounded-xl !border-transparent !bg-st-surface-container-low !text-st-on-surface" />
            </div>
            <div>
              <label className={label}>کد پستی (اختیاری)</label>
              <input value={address.postal_code} onChange={set("postal_code")} dir="ltr" className={input} inputMode="numeric" />
            </div>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={!valid}
                className="w-full h-12 rounded-xl bg-st-primary-container text-st-on-primary text-st-label-lg flex items-center justify-center gap-st-space-xs hover:bg-st-secondary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Icon name="check" className="text-[18px]" />
                تأیید نشانی
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-st-surface-container-lowest shadow-sm lg:shadow-none lg:bg-st-surface rounded-xl p-st-space-md">
          <div className="flex items-start justify-between gap-st-space-md">
            <div className="flex gap-st-space-md items-start min-w-0">
              <div className="hidden lg:flex w-6 h-6 rounded-full bg-st-primary-container text-st-on-primary items-center justify-center mt-1 flex-shrink-0">
                <Icon name="check" className="text-[14px]" />
              </div>
              <div className="flex flex-col gap-st-space-xs min-w-0">
                <div className="flex items-center gap-st-space-sm">
                  <span className="px-st-space-sm py-0.5 rounded-full bg-st-secondary-fixed text-st-on-secondary-fixed text-st-label-sm font-semibold">
                    {address.province}، {address.city}
                  </span>
                </div>
                <p className="text-st-on-surface lg:text-st-on-surface-variant font-medium lg:font-normal leading-relaxed">{address.line1}</p>
                <div className="flex flex-wrap items-center gap-x-st-space-lg gap-y-st-space-xs mt-st-space-xs text-st-on-surface-variant lg:text-st-on-surface text-st-label-md lg:text-base">
                  <span className="flex items-center gap-st-space-xs">
                    <Icon name="person" className="text-st-outline text-[16px]" />
                    <span>{address.recipient_name}</span>
                  </span>
                  <span className="flex items-center gap-st-space-xs">
                    <Icon name="call" className="text-st-outline text-[16px]" />
                    <span className="tracking-wide" dir="ltr">{address.recipient_phone}</span>
                  </span>
                  {address.postal_code.trim() && (
                    <span className="flex items-center gap-st-space-xs">
                      <Icon name="mail" className="text-st-outline text-[16px]" />
                      <span>کد پستی: <span dir="ltr">{address.postal_code}</span></span>
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="lg:hidden w-8 h-8 rounded-full bg-st-secondary/10 flex items-center justify-center shrink-0 text-st-secondary">
              <Icon name="check_circle" className="text-[20px]" />
            </div>
            <button type="button" onClick={() => setEditing(true)} className="hidden lg:block px-st-space-md py-st-space-xs rounded-lg bg-st-surface-container hover:bg-st-surface-container-high text-st-primary transition-colors flex-shrink-0">
              تغییر یا ویرایش
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const REFUND_NOTE = "اگر مبلغی از حسابتان کسر شده باشد، به‌صورت خودکار به حسابتان برمی‌گردد.";
const PAYMENT_FAILURE_MESSAGES: Record<string, string> = {
  payment_failed: `پرداخت انجام نشد یا لغو شد. ${REFUND_NOTE}`,
  payment_expired: `مهلت پرداخت تمام شده بود و سفارش ثبت نشد. ${REFUND_NOTE}`,
  verify_unavailable: `تأیید پرداخت از بانک ممکن نشد و سفارش ثبت نشد. ${REFUND_NOTE}`,
  order_failed: `پرداخت انجام شد ولی ثبت سفارش ممکن نشد؛ مبلغ برگشت داده می‌شود. ${REFUND_NOTE}`,
  unknown_payment: `این پرداخت شناخته نشد. ${REFUND_NOTE}`,
  unknown_gateway: "درگاه پرداخت شناخته نشد.",
};

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className={cn(stRoot, "min-h-[60vh] text-base")}>
      <div className="max-w-[1280px] mx-auto w-full px-st-gutter lg:px-8 lg:py-5">{children}</div>
    </div>
  );
}

function Notice({ title, cta }: { title: string; cta: { href: string; label: string } }) {
  return (
    <Shell>
      <div className="py-24">
        <div className="mx-auto max-w-md bg-st-surface-container-lowest rounded-2xl p-st-space-lg shadow-sm text-center">
          <h2 className="text-st-title-lg text-st-primary-container mb-st-space-md">{title}</h2>
          <Link href={cta.href} className="inline-flex h-12 items-center gap-2 px-6 rounded-xl bg-st-primary-container text-st-on-primary text-st-label-lg hover:bg-st-secondary transition-colors">
            {cta.label}
          </Link>
        </div>
      </div>
    </Shell>
  );
}

export default function CheckoutPage() {
  const { token, loading: authLoading } = useAuth();
  const [cart, setCart] = useState<Cart | null>(null);
  const [quote, setQuote] = useState<CheckoutQuote | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [paymentResult, setPaymentResult] = useState<string | null>(null);

  // The bank returns here with ?payment=failed&reason=… when no order could be created.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("payment") !== "failed") return;
    setPaymentResult(PAYMENT_FAILURE_MESSAGES[params.get("reason") ?? ""] ?? PAYMENT_FAILURE_MESSAGES.payment_failed);
  }, []);

  useEffect(() => {
    if (authLoading || !token) return;
    Promise.all([cartApi.get(token), checkoutApi.quote(token)])
      .then(([c, q]) => {
        setCart(c);
        setQuote(q);
      })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : "خطا در دریافت اطلاعات تسویه‌حساب"));
  }, [token, authLoading]);

  if (!authLoading && !token) return <Notice title="برای تسویه‌حساب وارد شوید" cta={{ href: "/login?next=/checkout", label: "ورود به حساب کاربری" }} />;

  if (loadError) {
    return (
      <Shell>
        <p role="alert" className="my-24 mx-auto max-w-md rounded-xl bg-st-error-container text-st-on-error-container p-st-space-md text-center">{loadError}</p>
      </Shell>
    );
  }

  if (!cart || !quote) {
    return (
      <Shell>
        <div className="py-st-space-md grid grid-cols-12 gap-st-gutter-lg">
          <div className="col-span-12 lg:col-span-8 h-96 rounded-xl bg-st-surface-container animate-pulse" />
          <div className="col-span-12 lg:col-span-4 h-72 rounded-xl bg-st-surface-container animate-pulse" />
        </div>
      </Shell>
    );
  }

  if (cart.items.length === 0) return <Notice title="سبد خرید شما خالی است" cta={{ href: "/search", label: "مشاهده محصولات" }} />;

  return <CheckoutForm cart={cart} quote={quote} token={token!} paymentResult={paymentResult} />;
}

function CheckoutForm({ cart, quote, token, paymentResult }: { cart: Cart; quote: CheckoutQuote; token: string; paymentResult: string | null }) {
  const [address, setAddress] = useState<Address>(EMPTY_ADDRESS);
  const [editingAddress, setEditingAddress] = useState(true);
  const [method, setMethod] = useState<PaymentMethod>("card");
  const [placing, setPlacing] = useState(false);
  const [placedOrderNumber, setPlacedOrderNumber] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [boundary, setBoundary] = useState(false);
  // Buyer terms + statutory withdrawal notice, accepted before paying (recorded as evidence).
  const [terms, setTerms] = useState<{ version: string; url: string } | null>(null);
  const [acceptTerms, setAcceptTerms] = useState(false);
  // Employee welfare wallet (کیف پول رفاهی): opt-in; the server decides the exact share.
  const [welfare, setWelfare] = useState<{ available: boolean; allowed_minor: number } | null>(null);
  const [useWelfare, setUseWelfare] = useState(false);
  useEffect(() => { checkoutApi.welfare(token).then(setWelfare).catch(() => setWelfare(null)); }, [token]);
  // Card gateway or an external credit provider (Tara pattern: the lender funds, we only accept).
  const [payOptions, setPayOptions] = useState<PayOption[]>([]);
  const [provider, setProvider] = useState<string | null>(null);
  useEffect(() => {
    apiRequest<{ options: PayOption[] }>("/checkout/payment-options")
      .then((r) => setPayOptions(r.options)).catch(() => {});
  }, []);
  useEffect(() => {
    apiRequest<{ documents: { doc_key: string; version: string; url: string }[] }>("/legal/terms")
      .then((r) => { const d = r.documents.find((x) => x.doc_key === "buyer_terms"); if (d) setTerms(d); })
      .catch(() => {});
  }, []);
  const [proformaNo, setProformaNo] = useState<string | null>(null);
  useEffect(() => { try { setProformaNo(new URLSearchParams(window.location.search).get("proforma")); } catch {} }, []);
  const [redirecting, setRedirecting] = useState(false);
  const [requestKey] = useState(() => newIdempotencyKey());
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey());
  const router = useRouter();

  const valid = addressValid(address);

  // Payment boundary: no online gateway is connected, so no payment is attempted or simulated.
  // The same cart can be submitted as a tracked purchase request instead.
  const submitRequest = async () => {
    setPlacing(true);
    setError(null);
    try {
      const lines = (cart.items as unknown as { slug: string; quantity: number }[]).map((i) => ({ slug: i.slug, quantity: i.quantity }));
      const a = address as unknown as Record<string, string>;
      const r = await apiRequest<{ request: { id: number } }>("/requests", {
        token, method: "POST", headers: { "Idempotency-Key": requestKey },
        body: JSON.stringify({ kind: "procurement", subject: "درخواست خرید از سبد", items: lines,
          message: `تحویل: ${a.province ?? ""}، ${a.city ?? ""}، ${a.line1 ?? ""} — گیرنده: ${a.recipient_name ?? ""} (${a.recipient_phone ?? ""})` }),
      });
      router.push(`/requests/${r.request.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ثبت درخواست ناموفق بود");
    } finally {
      setPlacing(false);
    }
  };

  const handlePlace = async () => {
    setPlacing(true);
    setError(null);
    try {
      const external = payOptions.find((o) => o.provider === provider && o.kind !== "card");
      let proforma: string | undefined;
      try { proforma = new URLSearchParams(window.location.search).get("proforma") ?? undefined; } catch {}
      const placed = await checkoutApi.place(token, idempotencyKey, address, method, terms?.version, external?.provider, useWelfare, proforma);
      if (placed.payment_redirect) {
        // Pay on the bank page; the bank sends the customer back to the order or here with the result.
        setRedirecting(true);
        goToPaymentGateway(placed.payment_redirect);
        return;
      }
      setPlacedOrderNumber(placed.order.order_number);
    } catch (err) {
      if (err instanceof ApiError && err.code === "payment_gateway_unavailable") {
        setBoundary(true);
      } else if (err instanceof ApiError) {
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
      <Shell>
        <div className="py-st-space-xl">
          <div className="mx-auto max-w-lg bg-st-surface-container-lowest rounded-xl p-st-space-lg shadow-sm text-center space-y-st-space-md">
            <div className="w-20 h-20 rounded-full bg-st-secondary-fixed text-st-secondary flex items-center justify-center mx-auto">
              <Icon name="task_alt" className="text-[44px]" />
            </div>
            <div>
              <h2 className="text-st-headline-md text-st-primary-container">سفارش ثبت شد!</h2>
              <p className="text-st-body-md text-st-on-surface-variant mt-1">شماره سفارش: {placedOrderNumber}</p>
            </div>
            <p className="text-st-body-md text-st-on-surface-variant max-w-sm mx-auto">سفارش شما ثبت شد. وضعیت پرداخت را در صفحه سفارش مشاهده کنید.</p>
            <div className="flex justify-center gap-st-space-sm pt-st-space-xs">
              <button onClick={() => router.push(`/orders/${placedOrderNumber}`)} className="h-12 px-6 rounded-xl bg-st-primary-container text-st-on-primary text-st-label-lg hover:bg-st-secondary transition-colors">
                مشاهده سفارش
              </button>
              <Link href="/" className="h-12 px-6 inline-flex items-center rounded-xl bg-st-surface-container-low text-st-primary text-st-label-lg hover:bg-st-surface-container transition-colors">
                بازگشت به خانه
              </Link>
            </div>
          </div>
        </div>
      </Shell>
    );
  }

  // Payment options: only what the server says is real for this customer.
  const cardOptions: PayOption[] = payOptions.length ? payOptions : [{ provider: "", kind: "card", label: "پرداخت آنلاین با کارت" }];
  const selectedProvider = provider ?? payOptions[0]?.provider ?? "";
  const leadDays = Math.max(0, ...cart.items.map((i) => Number((i as unknown as { lead_time_days?: number | null }).lead_time_days) || 0));
  const payable = useWelfare && welfare ? Math.max(0, quote.cash_due_minor - welfare.allowed_minor) : quote.cash_due_minor;
  const canPlace = valid && !placing && !boundary && !(!!terms && !acceptTerms);
  const methodLabel = method === "card" ? "کارت بانکی" : method === "credit" ? "اعتبار سازمانی" : "ترکیبی";

  return (
    <Shell>
      <div className="pb-56 lg:pb-0">
        <Stepper addressDone={valid && !editingAddress} />

        {paymentResult && (
          <div role="alert" className="mb-st-space-md lg:mb-st-space-lg flex items-start gap-st-space-sm rounded-xl bg-st-error-container text-st-on-error-container p-st-space-md leading-7">
            <Icon name="error" className="text-[20px] mt-1" />
            <span>{paymentResult}</span>
          </div>
        )}

        {quote.organization && (
          <div className="lg:hidden pb-st-space-sm">
            <div className="flex items-center gap-st-space-sm px-st-space-md py-st-space-xs rounded-full bg-st-secondary-fixed/50 text-st-on-secondary-fixed-variant">
              <Icon name="verified_user" className="text-[18px] text-st-secondary" />
              <p className="text-st-label-sm font-medium">عضو {quote.organization.display_name}؛ مبالغ و اعتبار توسط سرور محاسبه می‌شود</p>
            </div>
          </div>
        )}

        <div className="grid grid-cols-12 gap-st-space-md lg:gap-5 items-start">
          {/* Right column: form cards */}
          <div className="col-span-12 lg:col-span-8 flex flex-col gap-st-space-md lg:gap-st-space-lg">
            <AddressCard address={address} onChange={setAddress} editing={editingAddress} setEditing={setEditingAddress} />

            {/* Delivery — no time-slot backend: one honest option from the server cart (fee, lead time). */}
            <Card
              icon="local_shipping"
              title="شیوه و زمان‌بندی ارسال"
              aside={<span className="hidden lg:inline bg-st-surface-container px-st-space-sm py-1 rounded-full text-st-on-surface-variant text-st-label-md">انتخاب بازه زمانی: به‌زودی</span>}
            >
              <div className="flex flex-col gap-st-space-sm">
                <Option on name="shipping_slot" onSelect={() => {}}>
                  <div className="flex flex-wrap items-center justify-between gap-st-space-xs">
                    <div className="flex items-center gap-st-space-sm">
                      <span className="text-st-primary-container lg:text-st-primary font-bold">ارسال توسط فروشنده</span>
                      {leadDays > 0 && (
                        <span className="bg-st-secondary-fixed text-st-on-secondary-fixed px-st-space-sm py-0.5 rounded-full font-bold text-st-label-sm">
                          حداکثر {toPersianNum(leadDays)} روز کاری
                        </span>
                      )}
                    </div>
                    <span className="text-st-secondary font-bold">
                      {quote.cart.shipping_fee_minor === 0 ? "رایگان" : `${toman(quote.cart.shipping_fee_minor)} تومان`}
                    </span>
                  </div>
                  <p className="text-st-on-surface-variant text-st-body-md lg:text-base">
                    {leadDays > 0
                      ? `زمان آماده‌سازی اعلام‌شده فروشنده ${toPersianNum(leadDays)} روز کاری است؛ زمان دقیق تحویل پس از ثبت سفارش هماهنگ می‌شود.`
                      : "زمان دقیق تحویل پس از ثبت سفارش با شما هماهنگ می‌شود."}
                  </p>
                </Option>
              </div>
            </Card>

            {/* Official tax invoice — checkout has no legal-entity invoice field yet: toggle disabled, honest note. */}
            <Card
              icon="receipt_long"
              title="اطلاعات فاکتور رسمی سامانه مودیان (B2B)"
              aside={
                <div aria-disabled="true" title="به‌زودی" className="hidden lg:flex items-center gap-st-space-sm bg-st-surface-container-low px-st-space-md py-st-space-xs rounded-full select-none opacity-70">
                  <span className="text-st-primary font-bold text-st-label-lg">صدور فاکتور رسمی حقوقی (به‌زودی)</span>
                  <div className="w-10 h-6 bg-st-surface-container-highest rounded-full p-1 flex items-center justify-start">
                    <div className="w-4 h-4 rounded-full bg-st-surface-container-lowest shadow-sm" />
                  </div>
                </div>
              }
            >
              <div className="bg-st-surface-container-lowest shadow-sm lg:shadow-none lg:bg-st-surface rounded-xl p-st-space-md">
                <div className="flex flex-wrap items-center justify-between gap-st-space-xs bg-st-surface-container-low px-st-space-sm py-st-space-xs rounded-lg mb-st-space-sm">
                  <div className="flex items-center gap-st-space-xs text-st-secondary font-bold text-st-label-lg">
                    <Icon name="info" className="text-[18px]" />
                    <span>{proformaNo ? `پرداخت بر اساس پیش‌فاکتور ${proformaNo}` : "صدور فاکتور رسمی حقوقی در خرید آنلاین به‌زودی فعال می‌شود"}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-st-space-sm md:gap-st-gutter-md text-st-label-md lg:text-base">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-st-outline">خریدار:</span>
                    <span className="text-st-primary font-bold">{quote.organization ? quote.organization.display_name : "حساب شخصی"}</span>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-st-outline">نرخ مالیات بر ارزش افزوده:</span>
                    <span className="text-st-primary font-bold">٪{toPersianNum((quote.tax_rate_bps / 100).toFixed(0))}</span>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-st-outline">پیش‌فاکتور رسمی:</span>
                    <Link href="/cart" className="text-st-secondary font-bold hover:underline">دریافت از سبد خرید</Link>
                  </div>
                </div>
              </div>
            </Card>

            {/* Payment */}
            <Card
              icon="account_balance_wallet"
              title="شیوه پرداخت"
              aside={
                <span className="text-st-on-surface-variant flex items-center gap-st-space-xs text-st-label-md lg:text-base">
                  <Icon name="lock" className="text-st-secondary text-[16px]" />
                  <span className="hidden sm:inline">پرداخت امن از درگاه بانکی</span>
                </span>
              }
            >
              <div className="flex flex-col gap-st-space-sm lg:gap-st-space-md" id="payment-methods">
                {quote.has_organization_credit && (
                  <>
                    <Option name="payment_type" on={method === "credit"} onSelect={() => { setMethod("credit"); setProvider(null); }}>
                      <div className="flex flex-wrap items-center justify-between gap-st-space-xs">
                        <div className="flex items-center gap-st-space-sm">
                          <span className="text-st-primary-container lg:text-st-primary font-bold">اعتبار سازمانی</span>
                          {quote.organization && (
                            <span className="bg-st-secondary-fixed text-st-on-secondary-fixed px-st-space-sm py-0.5 rounded-full font-bold text-st-label-sm">{quote.organization.display_name}</span>
                          )}
                        </div>
                        <span className="text-st-secondary font-bold">موجودی قابل استفاده: {toman(quote.eligible_credit_minor)} تومان</span>
                      </div>
                      <p className="text-st-on-surface-variant text-st-body-sm lg:text-base">پرداخت از اعتبار تخصیص‌یافته سازمان شما</p>
                    </Option>
                    <Option name="payment_type" on={method === "split"} onSelect={() => { setMethod("split"); setProvider(null); }}>
                      <div className="flex flex-wrap items-center justify-between gap-st-space-xs">
                        <span className="text-st-on-surface font-bold">ترکیبی (اعتبار + کارت)</span>
                        <span className="text-st-label-sm lg:text-base text-st-secondary font-medium">پرداخت ترکیبی</span>
                      </div>
                      <p className="text-st-on-surface-variant text-st-body-md lg:text-base">ابتدا از اعتبار سازمانی، مابقی با کارت</p>
                      <p className="text-st-outline text-st-body-sm">مابقی مبلغ ({toman(quote.cash_due_minor)} تومان) از طریق درگاه بانکی اخذ خواهد شد.</p>
                    </Option>
                  </>
                )}
                {cardOptions.map((o) => (
                  <Option key={o.provider || "card"} name="payment_type"
                    on={method === "card" && selectedProvider === o.provider}
                    onSelect={() => { setMethod("card"); setProvider(o.provider || null); }}>
                    <div className="flex flex-wrap items-center justify-between gap-st-space-xs">
                      <span className="text-st-on-surface font-bold">{o.label}</span>
                      <span className="text-st-outline text-st-label-sm lg:text-base">{o.kind === "card" ? "کارت‌های عضو شتاب" : "خرید اعتباری"}</span>
                    </div>
                    <p className="text-st-on-surface-variant text-st-body-md lg:text-base">{o.note || "پرداخت کامل از طریق درگاه بانکی"}</p>
                  </Option>
                ))}

                {/* Real, server-computed breakdown for credit / split */}
                {method !== "card" && (
                  <div className="rounded-xl bg-st-surface-container-low p-st-space-md space-y-st-space-xs text-st-body-md lg:text-base">
                    <p className="font-bold text-st-primary-container">تفکیک پرداخت</p>
                    <div className="flex justify-between">
                      <span className="text-st-on-surface-variant">اعتبار سازمانی</span>
                      <span className="font-medium text-st-secondary tabular-nums">−{toman(quote.credit_to_use_minor)} تومان</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-st-on-surface-variant">پرداخت آنلاین</span>
                      <span className="font-medium tabular-nums">{toman(quote.cash_due_minor)} تومان</span>
                    </div>
                    <div className="border-t border-st-surface-container-high pt-st-space-xs flex justify-between font-bold">
                      <span>جمع کل</span>
                      <span className="tabular-nums">{toman(quote.final_payable_minor)} تومان</span>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>

          {/* Left column: order summary (sticky on desktop; on phones the 29-style breakdown + fixed CTA bar) */}
          <div className="col-span-12 lg:col-span-4 lg:sticky lg:top-[124px] flex flex-col gap-st-space-md">
            <div className="bg-st-surface-container-lowest rounded-xl p-st-space-md lg:p-5 shadow-st-card">
              <div className="hidden lg:flex items-center justify-between mb-st-space-md pb-st-space-sm border-b border-st-surface-container-low">
                <h3 className="text-st-primary font-bold">خلاصه سفارش</h3>
                <span className="bg-st-surface-container-low text-st-on-surface-variant px-st-space-sm py-0.5 rounded-full font-bold text-st-label-md">
                  {toPersianNum(cart.items.length)} قلم کالا
                </span>
              </div>
              <div className="hidden lg:flex flex-col gap-st-space-sm mb-st-space-lg pb-st-space-md border-b border-st-surface-container-low">
                {cart.items.map((item) => (
                  <div key={item.product_id} className="flex items-center gap-st-space-sm">
                    <div className="w-12 h-12 rounded-lg bg-st-surface overflow-hidden flex-shrink-0 flex items-center justify-center text-xl">
                      {item.image_url
                        // eslint-disable-next-line @next/next/no-img-element
                        ? <img className="w-full h-full object-contain" src={item.image_url} alt="" />
                        : <span aria-hidden="true">{item.image_emoji || "📦"}</span>}
                    </div>
                    <div className="flex flex-col flex-1 min-w-0">
                      <span className="text-st-on-surface truncate">{item.title_fa}</span>
                      <span className="text-st-outline text-st-label-md">تعداد: {toPersianNum(item.quantity)}</span>
                    </div>
                    <span className="text-st-primary font-bold flex-shrink-0 tabular-nums">{toman(item.line_total_minor)}</span>
                  </div>
                ))}
              </div>

              <div className="flex flex-col gap-st-space-xs lg:gap-st-space-sm text-st-label-md lg:text-base">
                <div className="flex items-center justify-between text-st-on-surface-variant">
                  <span>مجموع اقلام سبد<span className="lg:hidden"> ({toPersianNum(cart.items.length)} قلم کالا)</span></span>
                  <span className="text-st-on-surface font-bold tabular-nums">{toman(quote.cart.subtotal_minor)} تومان</span>
                </div>
                {!!quote.recurring_discount_minor && (
                  <div className="flex items-center justify-between text-st-on-tertiary-container">
                    <span className="flex items-center gap-st-space-xs font-bold"><Icon name="percent" className="text-[18px]" />تخفیف خرید دوره‌ای (اعمال‌شده در جمع کالاها)</span>
                    <span className="font-bold tabular-nums">−{toman(quote.recurring_discount_minor)} تومان</span>
                  </div>
                )}
                <div className="flex items-center justify-between text-st-on-surface-variant">
                  <span>هزینه بسته‌بندی و ارسال</span>
                  {quote.cart.shipping_fee_minor === 0
                    ? <span className="text-st-secondary font-bold lg:bg-st-secondary-fixed lg:px-st-space-sm lg:py-0.5 rounded-full">رایگان</span>
                    : <span className="text-st-on-surface font-bold tabular-nums">{toman(quote.cart.shipping_fee_minor)} تومان</span>}
                </div>
                <div className="flex items-center justify-between text-st-on-surface-variant">
                  <span>مالیات بر ارزش افزوده (٪{toPersianNum((quote.tax_rate_bps / 100).toFixed(0))})</span>
                  <span className="text-st-on-surface font-bold tabular-nums">{toman(quote.tax_minor)} تومان</span>
                </div>
                <div className="flex items-center justify-between text-st-on-surface-variant">
                  <span>جمع کل سفارش</span>
                  <span className="text-st-on-surface font-bold tabular-nums">{toman(quote.final_payable_minor)} تومان</span>
                </div>
                {quote.credit_to_use_minor > 0 && (
                  <div className="flex items-center justify-between text-st-secondary">
                    <span className="font-bold">اعتبار سازمانی</span>
                    <span className="font-bold tabular-nums">−{toman(quote.credit_to_use_minor)} تومان</span>
                  </div>
                )}
                {welfare?.available && (
                  <label className="flex items-start gap-2 rounded-lg bg-st-secondary-fixed/50 p-st-space-sm text-st-on-secondary-fixed-variant text-st-body-sm">
                    <input type="checkbox" className="mt-1" checked={useWelfare} onChange={(e) => setUseWelfare(e.target.checked)} />
                    <span>پرداخت با کیف پول رفاهی (تا {toman(welfare.allowed_minor)} تومان از این سبد). سهم رفاهی را سازمان می‌پردازد و از کارت کم می‌شود.</span>
                  </label>
                )}
                <div className="hidden lg:block h-0.5 bg-st-surface-container my-st-space-xs" />
                <div className="hidden lg:flex items-center justify-between rounded-xl bg-st-navy px-4 py-3 text-white">
                  <span className="font-bold">مبلغ نهایی قابل پرداخت:</span>
                  <div className="flex items-baseline gap-st-space-xs">
                    <span className="font-black text-[24px] leading-none tabular-nums">{toman(payable)}</span>
                    <span className="text-st-on-navy-muted">تومان</span>
                  </div>
                </div>
                {useWelfare && <p className="text-st-label-sm text-st-on-surface-variant">مبلغ نهایی کارت پس از اعمال کیف پول رفاهی توسط سرور قطعی می‌شود.</p>}
                <p className="text-st-label-sm text-st-outline text-left">روش پرداخت: {methodLabel}</p>
              </div>

              {terms && (
                <label className="mt-st-space-md flex items-start gap-2 text-st-body-sm text-st-on-surface-variant">
                  <input type="checkbox" className="mt-1" checked={acceptTerms} onChange={(e) => setAcceptTerms(e.target.checked)} />
                  <span>
                    <a href={terms.url} target="_blank" rel="noopener" className="underline text-st-secondary">شرایط خرید</a> را می‌پذیرم. می‌دانم تا ۷ روز کاری بعد از تحویل، بدون ذکر دلیل حق انصراف دارم (به‌جز کالاهای استثنا).
                  </span>
                </label>
              )}

              {error && <p role="alert" className="mt-st-space-sm text-st-body-sm text-center rounded-xl bg-st-error-container text-st-on-error-container p-st-space-sm">{error}</p>}
              {redirecting && (
                <p role="status" className="mt-st-space-sm text-st-body-sm text-center rounded-xl bg-st-secondary-fixed text-st-on-secondary-fixed p-st-space-sm">در حال انتقال به درگاه بانک…</p>
              )}
              {boundary && (
                <div role="alert" className="mt-st-space-sm rounded-xl bg-st-tertiary-fixed p-st-space-md text-st-body-sm leading-7 text-st-on-tertiary-fixed">
                  <b className="block">پرداخت آنلاین هنوز فعال نیست</b>
                  درگاه پرداخت به فروشگاه متصل نشده است؛ هیچ مبلغی دریافت یا ثبت نشد. می‌توانید همین سبد را به‌صورت «درخواست خرید» ثبت کنید تا کارشناسان
                  قیمت نهایی، موجودی و روش پرداخت را هماهنگ کنند و وضعیت را در «درخواست‌های من» پیگیری کنید.
                  <button type="button" onClick={submitRequest} disabled={placing} className="mt-3 block w-full h-12 rounded-xl bg-st-primary-container font-bold text-st-on-primary disabled:opacity-60">
                    {placing ? "در حال ثبت…" : "ثبت درخواست خرید با همین سبد"}</button>
                </div>
              )}
              {!valid && <p className="mt-st-space-sm text-st-label-md text-st-on-tertiary-container">برای ثبت سفارش، ابتدا نشانی تحویل را کامل کنید.</p>}

              {/* CTA: fixed above the site's mobile bottom nav on phones (screen 29), inline on desktop (24). */}
              <div className="fixed bottom-[68px] md:bottom-0 inset-x-0 z-40 bg-st-surface-container-lowest/95 backdrop-blur-md px-st-gutter py-st-space-sm shadow-[0_-4px_16px_rgba(0,0,0,0.06)] lg:static lg:z-auto lg:bg-transparent lg:backdrop-blur-none lg:shadow-none lg:p-0 lg:mt-st-space-lg">
                <div className="flex items-center justify-between gap-st-space-md max-w-md mx-auto lg:max-w-none">
                  <div className="flex flex-col lg:hidden">
                    <span className="text-st-label-sm text-st-outline">مبلغ نهایی قابل پرداخت:</span>
                    <div className="flex items-baseline gap-1">
                      <span className="text-st-headline-md text-st-primary-container font-bold tabular-nums">{toman(payable)}</span>
                      <span className="text-st-label-sm text-st-on-surface-variant">تومان</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={handlePlace}
                    disabled={!canPlace}
                    className="flex-1 lg:w-full h-12 lg:h-[52px] px-3 whitespace-nowrap bg-st-secondary hover:bg-st-navy text-white rounded-xl flex items-center justify-center gap-st-space-sm text-st-label-lg lg:text-base font-bold transition-all active:scale-[0.98] shadow-sm lg:shadow-md disabled:opacity-60 disabled:cursor-not-allowed disabled:active:scale-100"
                  >
                    {placing ? (
                      <>
                        <Icon name="progress_activity" className="text-[20px] animate-spin" />
                        در حال ثبت سفارش…
                      </>
                    ) : (
                      <>
                        <span className="lg:hidden flex"><Icon name="verified" className="text-[20px]" /></span>
                        <span><span className="hidden lg:inline">تأیید نهایی و </span>ثبت سفارش<span className="lg:hidden"> نهایی</span></span>
                        <span className="hidden lg:flex"><Icon name="arrow_back" className="text-[20px] rotate-180" /></span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Trust lines — true statements only. */}
              <div className="hidden lg:flex mt-st-space-lg pt-st-space-md border-t border-st-surface-container-low flex-col gap-st-space-sm text-st-outline text-st-body-md">
                <div className="flex items-center gap-st-space-xs"><Icon name="shield" className="text-st-secondary text-[18px]" /><span>مبالغ، مالیات و اعتبار توسط سرور محاسبه و هنگام ثبت دوباره کنترل می‌شود</span></div>
                <div className="flex items-center gap-st-space-xs"><Icon name="security" className="text-st-secondary text-[18px]" /><span>پرداخت کارتی فقط در صفحه درگاه بانک انجام می‌شود</span></div>
                <div className="flex items-center gap-st-space-xs"><Icon name="published_with_changes" className="text-st-secondary text-[18px]" /><span>حق انصراف تا ۷ روز کاری پس از تحویل (طبق شرایط خرید)</span></div>
              </div>
            </div>

            <div className="hidden lg:flex bg-st-surface-container-low rounded-xl p-st-space-md items-center justify-between gap-st-space-sm">
              <div className="flex items-center gap-st-space-sm">
                <Icon name="support_agent" className="text-st-secondary" />
                <div className="flex flex-col">
                  <span className="text-st-primary font-bold">نیاز به هماهنگی پیش‌فاکتور دارید؟</span>
                  <span className="text-st-on-surface-variant text-st-body-md">پیش‌فاکتور ۷۲ ساعته را از سبد خرید بگیرید یا با پشتیبانی تماس بگیرید</span>
                </div>
              </div>
              <Link href="/contact" className="text-st-secondary hover:underline font-bold shrink-0">تماس</Link>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
