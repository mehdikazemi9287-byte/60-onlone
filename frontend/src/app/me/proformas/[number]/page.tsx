"use client";

// Official proforma (پیش‌فاکتور رسمی) — faithful to Stitch screen 28 (mobile; dark palette via the site theme toggle,
// mapped in stitch.module.css). «دانلود PDF» prints the A4 sheet laid out after Stitch screen 53.
// Data: GET /me/proformas/{number} (owner-only). Buyer legal ids, delivery address and the follow-up contact shown in
// the Stitch sample are not part of the proforma snapshot, so they are not displayed.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn, faDate } from "@/lib/utils";
import { PrintSheet } from "@/components/print/PrintSheet";
import ProformaSheet, { faWords, type ProformaDoc } from "@/components/organization/ProformaSheet";
import st from "@/components/organization/stitch.module.css";

const fa = (v: number) => v.toLocaleString("fa-IR");
const toman = (m: number) => fa(Math.round(m / 10));
const Icon = ({ name, className }: { name: string; className?: string }) => <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;

export default function ProformaPage({ params }: { params: Promise<{ number: string }> }) {
  const { token, user } = useAuth();
  const router = useRouter();
  const [pf, setPf] = useState<ProformaDoc | null>(null);
  const [err, setErr] = useState(false);
  const [printing, setPrinting] = useState(false), [copied, setCopied] = useState(false);
  const done = useCallback(() => setPrinting(false), []);
  useEffect(() => {
    if (!token) return;
    params.then((p) => apiRequest<ProformaDoc>(`/me/proformas/${encodeURIComponent(p.number)}`, { token })
      .then((d) => { setPf(d); if (new URLSearchParams(window.location.search).get("print") === "1") setPrinting(true); })
      .catch(() => setErr(true)));
  }, [params, token]);
  if (err) return <main className="p-10 text-center text-ink-muted">پیش‌فاکتور یافت نشد.</main>;
  if (!pf) return <main className="p-10 text-center text-ink-faint" role="status">در حال بارگذاری…</main>;

  const valid = !pf.used && !pf.expired;
  const share = async () => {
    const url = window.location.origin + window.location.pathname;
    try {
      if (navigator.share) { await navigator.share({ title: `پیش‌فاکتور ${pf.number}`, url }); return; }
      await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000);
    } catch { /* user cancelled share */ }
  };
  const discount = pf.items.reduce((s, i) => s + Math.max(0, i.unit_price_minor * i.quantity - i.line_total_minor), 0);

  return (
    <main dir="rtl" className={cn(st.shell, "mx-auto max-w-3xl bg-st-background pb-40 text-st-on-surface md:pb-st-space-xl")}>
      {/* Top bar */}
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-st-surface-container bg-st-surface-container-lowest px-st-space-md">
        <button type="button" onClick={() => router.push("/me/proformas")} aria-label="بازگشت به پیش‌فاکتورها" className="flex h-10 w-10 items-center justify-center rounded-full text-st-primary hover:bg-st-surface-container"><Icon name="arrow_forward" className="text-[22px]" /></button>
        <h1 className="font-bold text-st-primary">پیش‌فاکتور رسمی</h1>
        <button type="button" onClick={share} aria-label={copied ? "پیوند کپی شد" : "اشتراک‌گذاری"} className="flex h-10 w-10 items-center justify-center rounded-full text-st-primary hover:bg-st-surface-container"><Icon name={copied ? "check" : "share"} className="text-[22px]" /></button>
      </header>

      <div className="flex flex-col gap-st-space-md p-st-space-md">
        {/* Status banner */}
        <div className="flex items-center justify-between gap-st-space-sm rounded-xl border border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-st-space-sm">
          <div className="flex items-center gap-st-space-xs"><span className={cn("h-2.5 w-2.5 rounded-full", valid ? "bg-emerald-500" : pf.used ? "bg-st-outline" : "bg-st-on-tertiary-container")} />
            <div><p className="text-[14px] font-bold text-st-primary">{pf.used ? "این پیش‌فاکتور استفاده شده است" : pf.expired ? "مهلت این پیش‌فاکتور تمام شده است" : "معتبر جهت پرداخت"}</p>
              <p className="text-[12px] text-st-on-surface-variant">اعتبار نرخ و موجودی تا {faDate(pf.valid_until)}</p></div></div>
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-st-surface-container px-st-space-sm py-0.5 text-[12px] text-st-on-surface-variant"><Icon name="verified" className="text-[14px]" />سند رسمی ۶۰ آنلاین</span>
        </div>

        {/* Hero */}
        <section className="rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-md">
          <div className="flex items-start justify-between gap-st-space-sm">
            <div className="flex items-center gap-st-space-sm">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/brand/60online-mark.png" alt="" className="h-12 w-12 rounded-lg bg-white object-contain p-1" />
              <div><p className="flex items-center gap-1 font-bold text-st-primary">۶۰ آنلاین <span className="rounded bg-st-surface-container px-1.5 text-[11px] text-st-on-surface-variant">سامانه B2B</span></p>
                <p className="text-[12px] text-st-on-surface-variant">تأمین هوشمند سازمانی و خانوار</p></div>
            </div>
            <button type="button" onClick={() => navigator.clipboard?.writeText(pf.number)} title="کپی شماره" className="text-left">
              <span className="block text-[12px] text-st-outline">شماره پیش‌فاکتور</span>
              <span className="block font-mono text-[15px] font-bold text-st-secondary" dir="ltr">{pf.number}</span></button>
          </div>
          <dl className="mt-st-space-md grid grid-cols-2 gap-st-space-sm border-t border-st-surface-container pt-st-space-sm text-[13px]">
            <div><dt className="text-st-outline">تاریخ صدور:</dt><dd className="font-bold text-st-primary">{faDate(pf.created_at)}</dd></div>
            <div><dt className="text-st-outline">تعداد اقلام:</dt><dd className="font-bold text-st-primary">{fa(pf.items.length)} قلم</dd></div>
            <div className="col-span-2 flex items-center justify-between rounded-lg bg-st-surface-container-low px-st-space-sm py-1.5"><dt className="flex items-center gap-1 text-st-on-surface-variant"><Icon name="timer" className="text-[16px] text-st-on-tertiary-container" />مهلت قطعی‌سازی موجودی:</dt>
              <dd className="font-bold text-st-on-tertiary-container">{faDate(pf.valid_until)}</dd></div>
          </dl>
        </section>

        {/* Buyer */}
        <section className="rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-md">
          <div className="flex items-center justify-between"><h2 className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="apartment" className="text-[20px] text-st-secondary" />طرف حساب و خریدار</h2>
            <span className="rounded-full bg-st-surface-container px-st-space-sm py-0.5 text-[12px] text-st-on-surface-variant">{pf.organization ? "حساب سازمانی" : "حساب شخصی"}</span></div>
          <p className="mt-st-space-sm text-[17px] font-bold text-st-primary">{pf.organization ?? user?.full_name ?? "خرید شخصی"}</p>
          {user && <p className="mt-1 flex items-center gap-1 text-[13px] text-st-on-surface-variant"><Icon name="person" className="text-[16px]" />صادرکننده: {user.full_name}</p>}
        </section>

        {/* Items */}
        <section aria-labelledby="items-h">
          <div className="mb-st-space-sm flex items-center justify-between"><h2 id="items-h" className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="inventory_2" className="text-[20px]" />اقلام پیش‌فاکتور <span className="rounded-full bg-st-surface-container px-2 text-[12px] font-normal text-st-on-surface-variant">{fa(pf.items.length)} قلم کالا</span></h2>
            <span className="text-[12px] text-st-outline">واحد: تومان</span></div>
          <ul className="flex flex-col gap-st-space-sm">{pf.items.map((i) => { const base = i.unit_price_minor * i.quantity, off = base > i.line_total_minor ? Math.round((1 - i.line_total_minor / base) * 100) : 0; return (
            <li key={i.product_id} className="rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-md">
              <div className="flex items-start justify-between gap-st-space-sm"><div className="min-w-0"><p className="font-mono text-[11px] text-st-outline" dir="ltr" style={{ textAlign: "right" }}>{i.sku}</p><p className="font-bold leading-7 text-st-primary">{i.title_fa}</p></div>
                {off > 0 && <span className="shrink-0 rounded bg-st-tertiary-fixed px-1.5 text-[12px] font-bold text-st-tertiary-container">-٪{fa(off)}</span>}</div>
              <div className="mt-st-space-sm flex items-end justify-between border-t border-st-surface-container-low pt-st-space-sm">
                <div><p className="text-[12px] text-st-outline">تعداد و نرخ واحد</p><p className="text-[14px] text-st-on-surface">{fa(i.quantity)} عدد × {toman(i.unit_price_minor)}</p></div>
                <div className="text-left"><p className="text-[12px] text-st-outline">مبلغ نهایی</p><p className="font-bold text-st-primary">{toman(i.line_total_minor)} <span className="text-[12px] font-normal">تومان</span></p></div>
              </div>
            </li>); })}</ul>
        </section>

        {/* Financial summary */}
        <section className="rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-md" aria-labelledby="sum-h">
          <div className="flex items-center justify-between"><h2 id="sum-h" className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name="receipt_long" className="text-[20px]" />خلاصه حسابرسی مالی</h2><span className="font-mono text-[12px] text-st-outline">IRR (تومان)</span></div>
          <dl className="mt-st-space-sm flex flex-col gap-1.5 text-[14px]">
            <div className="flex justify-between"><dt className="text-st-on-surface-variant">جمع بهای اقلام:</dt><dd className="font-mono font-bold">{toman(pf.subtotal_minor)} تومان</dd></div>
            {discount > 0 && <div className="flex justify-between text-st-on-tertiary-container"><dt>تخفیف‌های اعمال‌شده:</dt><dd className="font-mono font-bold">-{toman(discount)} تومان</dd></div>}
            <div className="flex justify-between"><dt className="text-st-on-surface-variant">هزینه ارسال:</dt><dd className="font-mono font-bold">{pf.shipping_fee_minor ? `${toman(pf.shipping_fee_minor)} تومان` : <span className="text-emerald-600">رایگان</span>}</dd></div>
            <div className="flex justify-between"><dt className="text-st-on-surface-variant">مالیات بر ارزش افزوده:</dt><dd className="font-mono font-bold">{toman(pf.tax_minor)} تومان</dd></div>
          </dl>
          <div className="mt-st-space-md flex items-baseline justify-between border-t border-st-surface-container pt-st-space-sm"><span className="font-bold text-st-primary">مبلغ کل قابل پرداخت:</span><span className="font-mono text-[22px] font-extrabold text-st-primary">{toman(pf.total_minor)} <span className="text-[12px] font-normal">تومان</span></span></div>
          <p className="mt-st-space-sm rounded-lg bg-st-surface-container-low p-st-space-sm text-[13px] text-st-on-surface-variant">به حروف: {faWords(Math.round(pf.total_minor / 10))} تومان</p>
          <p className="mt-st-space-sm text-[12px] leading-6 text-st-outline">اگر هنگام پرداخت مبلغ سبد از این پیش‌فاکتور بیشتر شده باشد، پرداخت انجام نمی‌شود تا بی‌خبر بیشتر نپردازید.</p>
        </section>
        <Link href="/me/proformas" className="text-center text-[13px] text-st-on-surface-variant hover:text-st-primary">همهٔ پیش‌فاکتورها و دانلود گروهی</Link>
      </div>

      {/* Sticky bottom actions */}
      <div className="fixed inset-x-0 bottom-[calc(76px+env(safe-area-inset-bottom))] z-30 mx-auto max-w-3xl border-t border-st-surface-container bg-st-surface-container-lowest p-st-space-sm md:sticky md:bottom-0">
        {valid && <Link href={`/checkout?proforma=${encodeURIComponent(pf.number)}`} className="mb-st-space-xs flex h-12 w-full items-center justify-center gap-st-space-xs rounded-full bg-st-primary-container font-bold text-st-on-primary"><Icon name="account_balance_wallet" className="text-[20px]" />پرداخت با همین پیش‌فاکتور</Link>}
        <div className="grid grid-cols-3 gap-st-space-xs">
          <button type="button" onClick={() => setPrinting(true)} className="flex h-11 items-center justify-center gap-1 rounded-xl bg-st-surface-container text-[13px] font-semibold text-st-primary"><Icon name="download" className="text-[18px]" />دریافت PDF</button>
          <Link href="/org" className="flex h-11 items-center justify-center gap-1 rounded-xl bg-st-surface-container text-[13px] font-semibold text-st-primary"><Icon name="apartment" className="text-[18px]" />میز کار سازمان</Link>
          <button type="button" onClick={share} className="flex h-11 items-center justify-center gap-1 rounded-xl bg-st-surface-container text-[13px] font-semibold text-st-primary"><Icon name="share" className="text-[18px]" />{copied ? "کپی شد" : "اشتراک امن"}</button>
        </div>
      </div>

      {printing && <PrintSheet onDone={done}><ProformaSheet p={pf} buyer={user?.full_name} /></PrintSheet>}
    </main>
  );
}
