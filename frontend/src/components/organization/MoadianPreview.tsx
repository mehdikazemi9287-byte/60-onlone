"use client";
// Moadian (سامانه مودیان) e-invoice PREVIEW — faithful to Stitch screen 13 (modal over the orders page).
// Data: the real buyer invoice read model GET /orgs/{id}/orders/{oid}/invoice. UI ONLY: signing, the 22-digit tax id,
// XML export and submission to the tax authority are NOT implemented in the backend, so the modal says so plainly,
// shows «صادر نشده» for the tax id and keeps XML / send disabled («به‌زودی»). Print uses the global .moadian-modal rules.
import { useEffect, useRef } from "react";
import type { OrgInvoice } from "@/lib/commerce";
import { cn, faDate, toPersianNum } from "@/lib/utils";

type Inv = Omit<OrgInvoice, "lines"> & { tax_rate_bps?: number; lines: (OrgInvoice["lines"][number] & { sku?: string })[] };
const fa = (v: number) => v.toLocaleString("fa-IR");
const t = (m: number) => fa(Math.round(m / 10));
const Icon = ({ name, className }: { name: string; className?: string }) => <span aria-hidden className={cn("material-symbols-outlined", className)}>{name}</span>;

export default function MoadianPreview({ inv, onClose }: { inv: Inv; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const rate = inv.tax_rate_bps != null ? inv.tax_rate_bps / 100 : null;
  const pay = inv.credit_minor && inv.cash_minor ? "ترکیبی (اعتبار + نقد)" : inv.credit_minor ? "اعتبار سازمانی" : "نقدی";
  return (
    <div className="moadian-modal fixed inset-0 z-[90] flex items-end justify-center bg-st-primary/40 md:items-center md:p-st-space-lg" role="dialog" aria-modal="true" aria-labelledby="md-title" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} tabIndex={-1} className="moadian-sheet flex max-h-[94dvh] w-full max-w-[900px] flex-col overflow-hidden rounded-t-2xl bg-st-surface-container-lowest text-st-on-surface shadow-2xl outline-none md:rounded-xl">
        <header className="flex items-start justify-between gap-st-space-sm border-b border-st-surface-container p-st-space-md">
          <div className="flex items-start gap-st-space-sm">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-st-primary-container text-st-on-primary"><Icon name="account_balance" className="text-[22px]" /></div>
            <div><div className="flex flex-wrap items-center gap-st-space-xs"><h2 id="md-title" className="font-bold text-st-primary">پیش‌نمایش صورتحساب الکترونیکی سامانه مودیان</h2>
              <span className="rounded bg-st-secondary-fixed px-st-space-xs text-[13px] font-semibold text-st-on-secondary-fixed">الگوی اول - فروش</span></div>
              <p className="text-[13px] text-st-on-surface-variant">شناسه یکتای مالیاتی (۲۲ رقمی): <b className="text-st-primary">صادر نشده</b></p></div>
          </div>
          <div className="flex items-center gap-st-space-xs">
            <span className="inline-flex items-center gap-1 rounded-full bg-st-surface-container px-st-space-sm py-1 text-[13px] font-semibold text-st-on-surface-variant"><span className="h-1.5 w-1.5 rounded-full bg-st-on-tertiary-container" />پیش‌نمایش — به کارپوشه ارسال نشده</span>
            <button type="button" onClick={onClose} aria-label="بستن" className="flex h-9 w-9 items-center justify-center rounded-full hover:bg-st-surface-container print:hidden"><Icon name="close" className="text-[20px]" /></button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-st-space-md">
          <dl className="grid grid-cols-2 gap-st-space-sm rounded-xl border border-st-surface-container bg-st-surface p-st-space-md text-[14px] md:grid-cols-4">
            <div><dt className="text-st-outline">شماره سریال صورتحساب:</dt><dd className="font-bold text-st-primary" dir="ltr" style={{ textAlign: "right" }}>{inv.invoice_number}</dd></div>
            <div><dt className="text-st-outline">تاریخ صدور:</dt><dd className="font-bold text-st-primary">{faDate(inv.issued_at)}</dd></div>
            <div><dt className="text-st-outline">مرجع خرید (PO):</dt><dd className="font-bold text-st-primary">{inv.po_reference ?? "—"}</dd></div>
            <div><dt className="text-st-outline">روش تسویه فاکتور:</dt><dd className="font-bold text-st-secondary">{pay}</dd></div>
          </dl>
          <div className="mt-st-space-md grid gap-st-space-md md:grid-cols-2">
            <section className="rounded-xl border border-st-surface-container p-st-space-md text-[14px]">
              <div className="mb-st-space-xs flex items-center justify-between"><h3 className="flex items-center gap-1 font-bold text-st-primary"><Icon name="storefront" className="text-[18px] text-st-secondary" />مشخصات فروشنده</h3>
                <span className="rounded bg-st-surface-container px-st-space-xs text-[12px] text-st-on-surface-variant">مودی اصلی</span></div>
              <p><span className="text-st-outline">نام: </span><b>شصت‌آنلاین</b></p>
              <p className="mt-1 text-[13px] text-st-on-surface-variant">شناسه ملی، کد اقتصادی و نشانی فروشنده پس از تنظیم اتصال سامانه مودیان در صورتحساب درج می‌شود.</p>
            </section>
            <section className="rounded-xl border border-st-surface-container p-st-space-md text-[14px]">
              <div className="mb-st-space-xs flex items-center justify-between"><h3 className="flex items-center gap-1 font-bold text-st-primary"><Icon name="apartment" className="text-[18px] text-st-secondary" />مشخصات خریدار (سازمان طرف حساب)</h3>
                <span className="rounded bg-st-secondary-fixed px-st-space-xs text-[12px] text-st-on-secondary-fixed">نوع ۱ — حقوقی</span></div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-st-space-sm gap-y-0.5">
                <dt className="text-st-outline">نام حقوقی:</dt><dd className="font-bold">{inv.buyer.legal_name ?? inv.buyer.display_name}</dd>
                <dt className="text-st-outline">شناسه ملی:</dt><dd className="font-bold">{inv.buyer.national_id ? toPersianNum(inv.buyer.national_id) : "ثبت نشده"}</dd>
                <dt className="text-st-outline">درخواست خرید:</dt><dd className="font-bold" dir="ltr" style={{ textAlign: "right" }}>{inv.purchase_request_number ?? "—"}</dd>
              </dl>
            </section>
          </div>
          <div className="mt-st-space-md overflow-x-auto rounded-xl border border-st-surface-container">
            <table className="w-full min-w-[680px] border-collapse text-right text-[14px]">
              <thead><tr className="bg-st-surface-container-low text-[13px] text-st-on-surface-variant">{["ردیف", "شناسه کالا / خدمت", "شرح کالا یا خدمت", "تعداد", "مبلغ واحد (تومان)", "مبلغ پس از تخفیف", "نرخ مالیات"].map((h) => <th key={h} className="p-st-space-sm font-semibold">{h}</th>)}</tr></thead>
              <tbody>{inv.lines.map((l, i) => <tr key={l.id} className="border-t border-st-surface-container-low">
                <td className="p-st-space-sm">{fa(i + 1)}</td><td className="p-st-space-sm font-mono text-[12px] text-st-outline" dir="ltr" style={{ textAlign: "right" }}>{l.sku ?? "—"}</td>
                <td className="p-st-space-sm font-bold text-st-primary">{l.title_fa}</td><td className="p-st-space-sm font-bold">{fa(l.quantity)}</td>
                <td className="p-st-space-sm">{t(l.unit_price_minor)}</td><td className="p-st-space-sm font-bold">{t(l.line_total_minor)}</td>
                <td className="p-st-space-sm">{rate != null ? `٪${fa(rate)}` : "—"}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="mt-st-space-md grid gap-st-space-md md:grid-cols-2">
            <section className="rounded-xl border border-st-surface-container p-st-space-md text-[13px] leading-6 text-st-on-surface-variant">
              <h3 className="mb-1 flex items-center gap-1 font-bold text-st-secondary"><Icon name="verified_user" className="text-[18px]" />وضعیت قانونی این برگه</h3>
              <p>این برگه پیش‌نمایشِ داده‌های سفارش در قالب صورتحساب نوع اول است. امضای دیجیتال، شناسه یکتای مالیاتی و ارسال به کارپوشه سامانه مودیان هنوز در سامانه فعال نشده‌اند؛ بنابراین این برگه صورتحساب الکترونیکی رسمی نیست.</p>
            </section>
            <dl className="flex flex-col gap-1 rounded-xl bg-st-surface-container-low p-st-space-md text-[14px]">
              <div className="flex justify-between"><dt className="text-st-on-surface-variant">جمع کل ناخالص اقلام:</dt><dd className="font-bold">{t(inv.subtotal_minor)} تومان</dd></div>
              <div className="flex justify-between"><dt className="text-st-on-surface-variant">هزینه ارسال:</dt><dd className="font-bold">{t(inv.shipping_fee_minor)} تومان</dd></div>
              <div className="flex justify-between"><dt className="text-st-on-surface-variant">مالیات بر ارزش افزوده{rate != null ? ` (٪${fa(rate)})` : ""}:</dt><dd className="font-bold">{t(inv.tax_minor)} تومان</dd></div>
              <div className="mt-1 flex justify-between border-t border-st-surface-container pt-st-space-xs"><dt className="font-bold text-st-primary">مبلغ کل قابل پرداخت نهایی:</dt><dd className="font-bold text-st-primary">{t(inv.total_minor)} تومان</dd></div>
            </dl>
          </div>
        </div>
        <footer className="flex flex-wrap items-center gap-st-space-xs border-t border-st-surface-container bg-st-surface p-st-space-md print:hidden">
          <button type="button" onClick={() => window.print()} className="inline-flex items-center gap-1 rounded-lg bg-st-primary-container px-st-space-md py-st-space-xs font-semibold text-st-on-primary"><Icon name="print" className="text-[18px]" />چاپ پیش‌نمایش صورتحساب</button>
          <button type="button" disabled title="به‌زودی" className="inline-flex cursor-not-allowed items-center gap-1 rounded-lg border border-st-surface-container px-st-space-md py-st-space-xs text-st-outline opacity-60"><Icon name="download" className="text-[18px]" />دانلود فایل XML کارپوشه (به‌زودی)</button>
          <button type="button" disabled title="به‌زودی" className="inline-flex cursor-not-allowed items-center gap-1 rounded-lg border border-st-surface-container px-st-space-md py-st-space-xs text-st-outline opacity-60"><Icon name="send" className="text-[18px]" />ارسال به سامانه مودیان (به‌زودی)</button>
          <button type="button" onClick={onClose} className="mr-auto rounded-lg bg-st-surface-container px-st-space-md py-st-space-xs text-st-primary">بستن پنجره</button>
        </footer>
      </div>
    </div>
  );
}
