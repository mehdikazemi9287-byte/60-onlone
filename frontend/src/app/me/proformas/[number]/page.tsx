"use client";

// Official proforma (پیش‌فاکتور رسمی). Data: GET /me/proformas/{number} (owner-only). Layout from Stitch 2026-11:
// stacked item cards on mobile, table on desktop, light/dark aware; «دانلود PDF» prints an A4 sheet on white paper.
import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { CalendarClock, Check, Copy, FileDown, Share2 } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn, formatPrice, faDate, toPersianNum } from "@/lib/utils";
import { PrintHead, PrintSheet } from "@/components/print/PrintSheet";

type Proforma = { number: string; organization: string | null; created_at: string; valid_until: string; expired: boolean; used: boolean;
  items: { product_id: number; title_fa: string; sku: string; quantity: number; unit_price_minor: number; line_total_minor: number }[];
  subtotal_minor: number; shipping_fee_minor: number; tax_minor: number; total_minor: number };

export default function ProformaPage({ params }: { params: Promise<{ number: string }> }) {
  const { token } = useAuth();
  const [pf, setPf] = useState<Proforma | null>(null);
  const [err, setErr] = useState(false);
  const [printing, setPrinting] = useState(false), [copied, setCopied] = useState(false);
  const done = useCallback(() => setPrinting(false), []);
  useEffect(() => {
    if (!token) return;
    params.then((p) => apiRequest<Proforma>(`/me/proformas/${encodeURIComponent(p.number)}`, { token }).then(setPf).catch(() => setErr(true)));
  }, [params, token]);
  if (err) return <main className="p-10 text-center text-ink-muted">پیش‌فاکتور یافت نشد.</main>;
  if (!pf) return <main className="p-10 text-center text-ink-faint" role="status">در حال بارگذاری…</main>;

  const status = pf.used ? ["استفاده‌شده", "bg-canvas-sunken text-ink-soft"] : pf.expired ? ["منقضی‌شده", "bg-amber-50 text-amber-800"] : ["معتبر", "bg-emerald-50 text-emerald-800"];
  const share = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) { await navigator.share({ title: `پیش‌فاکتور ${pf.number}`, url }); return; }
      await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000);
    } catch { /* user cancelled share */ }
  };
  const totals: [string, number][] = [["جمع کالاها", pf.subtotal_minor], ["ارسال", pf.shipping_fee_minor], ["مالیات بر ارزش افزوده", pf.tax_minor]];

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-6 md:py-10">
      <Link href="/me/proformas" className="mb-3 inline-flex items-center text-xs font-semibold text-ink-muted hover:text-ink">همهٔ پیش‌فاکتورها و دانلود گروهی ←</Link>
      <section className="rounded-3xl border border-line bg-white p-5 md:p-7">
        <div className="flex items-start gap-3">
          <Image src="/brand/60online-mark.png" alt="" width={256} height={241} className="brand-mark h-12 w-auto shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold text-ink-faint">شصت‌آنلاین</p>
            <h1 className="text-xl font-extrabold text-ink md:text-2xl">پیش‌فاکتور رسمی</h1>
            <button type="button" onClick={() => navigator.clipboard?.writeText(pf.number)} className="mt-1 inline-flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink" title="کپی شماره">
              <span dir="ltr" className="font-mono">{pf.number}</span><Copy className="h-3 w-3" /></button>
          </div>
          <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold", status[1])}>{status[0]}</span>
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-3 rounded-2xl bg-canvas p-3 text-sm md:grid-cols-3">
          <div><dt className="text-[11px] text-ink-faint">تاریخ صدور</dt><dd className="font-semibold text-ink">{faDate(pf.created_at)}</dd></div>
          <div><dt className="flex items-center gap-1 text-[11px] text-ink-faint"><CalendarClock className="h-3 w-3" />معتبر تا</dt><dd className="font-semibold text-ink">{faDate(pf.valid_until)}</dd></div>
          <div className="col-span-2 md:col-span-1"><dt className="text-[11px] text-ink-faint">خریدار</dt><dd className="font-semibold text-ink">{pf.organization ?? "خرید شخصی"}</dd></div>
        </dl>
      </section>

      {pf.expired && !pf.used && <p role="alert" className="mt-4 rounded-2xl bg-amber-50 p-3 text-sm text-amber-800">مهلت این پیش‌فاکتور تمام شده است.</p>}

      <section aria-label="اقلام" className="mt-4 overflow-hidden rounded-3xl border border-line bg-white">
        <ul className="divide-y divide-line md:hidden">{pf.items.map((i) => (
          <li key={i.product_id} className="p-4">
            <p className="font-semibold leading-7 text-ink">{i.title_fa}</p>
            <p className="text-[11px] text-ink-faint" dir="ltr" style={{ textAlign: "right" }}>{i.sku}</p>
            <div className="mt-2 flex items-end justify-between text-sm">
              <span className="text-ink-muted">{toPersianNum(i.quantity)} × {formatPrice(i.unit_price_minor)}</span>
              <b className="text-ink tabular-nums">{formatPrice(i.line_total_minor)}</b>
            </div>
          </li>))}</ul>
        <table className="hidden w-full text-right text-sm md:table">
          <thead><tr>{["کالا", "تعداد", "فی", "جمع"].map((h) => <th key={h} scope="col" className="px-5 py-3">{h}</th>)}</tr></thead>
          <tbody>{pf.items.map((i) => (
            <tr key={i.product_id} className="text-ink"><td className="px-5 py-3"><span className="block font-semibold">{i.title_fa}</span><span className="text-[11px] text-ink-faint" dir="ltr">{i.sku}</span></td>
              <td className="px-5 py-3 tabular-nums">{toPersianNum(i.quantity)}</td><td className="px-5 py-3 tabular-nums">{formatPrice(i.unit_price_minor)}</td>
              <td className="px-5 py-3 font-bold tabular-nums">{formatPrice(i.line_total_minor)}</td></tr>))}</tbody>
        </table>
      </section>

      <section aria-label="جمع" className="mt-4 rounded-3xl border border-line bg-white p-5">
        <dl className="space-y-2 text-sm">
          {totals.map(([k, v]) => <div key={k} className="flex justify-between text-ink-soft"><dt>{k}</dt><dd className="tabular-nums">{formatPrice(v)}</dd></div>)}
          <div className="flex justify-between border-t border-line pt-3 text-base font-extrabold text-ink"><dt>مبلغ قابل پرداخت</dt><dd className="tabular-nums">{formatPrice(pf.total_minor)}</dd></div>
        </dl>
        <p className="mt-3 text-xs leading-6 text-ink-muted">اگر هنگام پرداخت مبلغ سبد از این پیش‌فاکتور بیشتر شده باشد، پرداخت انجام نمی‌شود تا بی‌خبر بیشتر نپردازید.</p>
      </section>

      <div className="sticky bottom-[calc(76px+env(safe-area-inset-bottom))] z-10 mt-4 flex gap-2 rounded-3xl border border-line bg-white/95 p-3 backdrop-blur md:static md:border-0 md:bg-transparent md:p-0">
        {!pf.expired && !pf.used && <Link href={`/checkout?proforma=${encodeURIComponent(pf.number)}`} className="inline-flex min-h-11 flex-1 items-center justify-center rounded-full bg-ink px-6 text-sm font-bold text-white md:flex-none">پرداخت با همین پیش‌فاکتور</Link>}
        <button type="button" onClick={() => setPrinting(true)} aria-label="دانلود PDF" className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-full border border-line-strong bg-white px-3 text-sm font-bold text-ink hover:border-ink md:px-4"><FileDown className="h-4 w-4" /><span className="hidden md:inline">دانلود PDF</span></button>
        <button type="button" onClick={share} aria-label={copied ? "پیوند کپی شد" : "اشتراک"} className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-full border border-line-strong bg-white px-3 text-sm font-bold text-ink hover:border-ink md:px-4">
          {copied ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}<span className="hidden md:inline">{copied ? "پیوند کپی شد" : "اشتراک"}</span></button>
      </div>

      {printing && <PrintSheet onDone={done}>
        <PrintHead title="پیش‌فاکتور رسمی" number={pf.number} date={faDate(pf.created_at)} />
        <table className="cp-kv"><tbody>
          <tr><th>خریدار</th><td>{pf.organization ?? "خرید شخصی"}</td><th>معتبر تا</th><td>{faDate(pf.valid_until)}</td></tr>
        </tbody></table>
        <table className="cp-items">
          <thead><tr><th>ردیف</th><th>کالا</th><th>کد کالا</th><th>تعداد</th><th>فی</th><th>جمع</th></tr></thead>
          <tbody>{pf.items.map((i, k) => <tr key={i.product_id}><td>{toPersianNum(k + 1)}</td><td>{i.title_fa}</td><td dir="ltr" style={{ textAlign: "right" }}>{i.sku}</td>
            <td>{toPersianNum(i.quantity)}</td><td>{formatPrice(i.unit_price_minor)}</td><td>{formatPrice(i.line_total_minor)}</td></tr>)}</tbody>
          <tfoot>
            {totals.map(([k, v]) => <tr key={k}><td colSpan={5}>{k}</td><td>{formatPrice(v)}</td></tr>)}
            <tr><td colSpan={5}>مبلغ قابل پرداخت</td><td>{formatPrice(pf.total_minor)}</td></tr>
          </tfoot>
        </table>
        <p className="cp-note">اعتبار این پیش‌فاکتور تا تاریخ ذکرشده است. اگر هنگام پرداخت مبلغ سبد از این پیش‌فاکتور بیشتر شده باشد، پرداخت انجام نمی‌شود.</p>
      </PrintSheet>}
    </main>
  );
}
