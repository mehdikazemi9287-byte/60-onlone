"use client";
// Seller shipment documents — Stitch screens 03 (exit slip + waybill, A4), 01/04 (driver sheet, mobile),
// 31/37/34 (delivery discrepancy case + document zoom). Data: the stored shipment label + GET /supplier/orders/{id}
// items. Nothing here writes to the server: the driver checklist and discrepancy entries live in this page only and
// the reports are printed / saved as PDF. (No backend endpoint records handover, driver, seal or discrepancy yet.)
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { Shipment } from "@/lib/commerce";
import { SHIP_STATUS_FA } from "@/lib/commerce";
import { cn, faDate, formatPrice, toPersianNum } from "@/lib/utils";
import { Code128, PrintSheet } from "@/components/print/PrintSheet";

export type FoItem = { product_id: number; title_fa: string; quantity: number };
type Party = { name?: string; phone?: string; province?: string; city?: string; address?: string; postal_code?: string };
type Label = { carrier?: { name_fa?: string; service_level?: string }; sender?: Party; receiver?: Party;
  reference?: { order_number?: string; fulfillment_order_id?: number }; parcel_count?: number; billable_weight_g?: number; cod_amount_minor?: number };
const place = (p?: Party) => [p?.province, p?.city, p?.address].filter(Boolean).join("، ");
const n = (v: number) => toPersianNum(v);
const LEVEL_FA: Record<string, string> = { same_day: "همان روز", express: "سریع (اکسپرس)", economy: "اقتصادی" };
const kg = (g?: number) => (g != null ? `${toPersianNum((Math.round(g / 100) / 10).toString()).replace(".", "٫")} کیلوگرم` : "—");
const today = () => faDate(new Date().toISOString().slice(0, 10));
const Icon = ({ name, className = "", fill = false }: { name: string; className?: string; fill?: boolean }) =>
  <span aria-hidden="true" className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;
const Ltr = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => <span dir="ltr" className={cn("inline-block", className)}>{children}</span>;

/** Full-screen overlay (portal) with Esc-to-close and body scroll lock. */
function Overlay({ label, onClose, children, className = "" }: { label: string; onClose: () => void; children: React.ReactNode; className?: string }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); document.body.style.overflow = prev; };
  }, [onClose]);
  return createPortal(<div role="dialog" aria-modal="true" aria-label={label} dir="rtl"
    className={cn("fixed inset-0 z-[95] overflow-y-auto bg-st-background text-base text-st-on-surface", className)}>{children}</div>, document.body);
}

// ── Screen 03: حواله خروج انبار و بارنامه (A4) ─────────────────────────────────────────────
function WaybillPaper({ s, items }: { s: Shipment; items: FoItem[] }) {
  const l = s.label as Label;
  const total = items.reduce((t, i) => t + i.quantity, 0);
  const box = "flex flex-col justify-between rounded-xl bg-st-surface-container-low/60 p-st-space-md";
  const head = (icon: string, title: string, tag?: React.ReactNode) => <div className="flex items-center justify-between pb-st-space-xs">
    <div className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name={icon} className="text-[18px]" /><span>{title}</span></div>{tag}</div>;
  return (
    <section className="flex w-full max-w-[960px] flex-col gap-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-lg text-st-on-surface shadow-md md:p-st-space-xl print:max-w-none print:p-0 print:shadow-none">
      <div className="flex items-center justify-between gap-st-space-md pb-st-space-sm">
        <div className="flex flex-1 items-center gap-st-space-sm">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="شصت‌آنلاین" className="h-14 w-auto object-contain" src="/brand/60online-mark.png" />
        </div>
        <div className="flex flex-[2] flex-col items-center text-center">
          <span className="text-st-label-sm tracking-wider text-st-on-surface-variant">شصت‌آنلاین | سامانهٔ فروش و ارسال فروشندگان</span>
          <h1 className="mt-1 text-st-title-lg font-bold text-st-primary md:text-st-headline-md">حوالهٔ خروج انبار و بارنامهٔ حمل</h1>
          <span className="mt-0.5 text-st-label-sm font-semibold text-st-secondary">نسخهٔ انبار، حامل و تحویل‌گیرنده</span>
        </div>
        <div className="flex flex-1 items-center justify-end gap-st-space-md text-left">
          <div className="flex flex-col items-end gap-1 text-st-label-sm">
            <div className="flex items-center gap-1.5"><span className="text-st-on-surface-variant">شماره حواله:</span><Ltr className="font-bold tracking-wide text-st-primary">EX-{s.fulfillment_order_id}</Ltr></div>
            <div className="flex items-center gap-1.5"><span className="text-st-on-surface-variant">کد رهگیری:</span><Ltr className="font-semibold text-st-secondary">{s.tracking_number}</Ltr></div>
            <div className="flex items-center gap-1.5"><span className="text-st-on-surface-variant">تاریخ چاپ:</span><span>{today()}</span></div>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-st-space-sm rounded-lg bg-st-surface-container-low px-st-space-md py-st-space-xs text-st-body-sm">
        <div className="flex items-center gap-st-space-xs"><span className="text-st-on-surface-variant">شمارهٔ سفارش مبنا:</span><Ltr className="font-bold text-st-primary">{l.reference?.order_number || "—"}</Ltr></div>
        <div className="flex items-center gap-st-space-xs"><span className="text-st-on-surface-variant">شناسهٔ پیگیری حمل:</span><Ltr className="font-semibold text-st-secondary">{s.tracking_number}</Ltr></div>
        <div className="flex items-center gap-st-space-xs"><span className="text-st-on-surface-variant">سطح خدمت:</span><span className="font-medium">{LEVEL_FA[l.carrier?.service_level || s.service_level] ?? s.service_level}</span></div>
        <div className="flex items-center gap-st-space-xs"><span className="text-st-on-surface-variant">مهلت تحویل:</span><span className="font-bold text-st-error">{s.deliver_by_at ? faDate(s.deliver_by_at.slice(0, 10)) : "—"}</span></div>
      </div>
      <div className="grid grid-cols-1 gap-st-space-sm md:grid-cols-2 print:grid-cols-2">
        <div className={box}>{head("domain", "مبدأ و فرستنده", <span className="rounded bg-st-surface-container px-st-space-xs py-0.5 text-st-label-sm font-medium text-st-on-surface-variant">فروشنده</span>)}
          <div className="flex flex-col gap-1 text-st-body-sm"><span className="font-bold text-st-primary">{l.sender?.name || "—"}</span><span className="text-st-label-md text-st-on-surface-variant">نشانی: {place(l.sender) || "—"}</span></div></div>
        <div className={box}>{head("badge", "انباردار مسئول و صادرکننده")}
          <div className="flex flex-col gap-1 text-st-body-sm"><span className="text-st-label-md text-st-on-surface-variant">نام و امضای انباردار در کادر «تحویل‌دهنده» پایین برگه ثبت می‌شود.</span></div></div>
        <div className={box}>{head("location_on", "تحویل‌گیرنده و مقصد نهایی")}
          <div className="flex flex-col gap-1 text-st-body-sm"><span className="font-bold text-st-primary">{l.receiver?.name || "—"}</span>
            <span className="text-st-label-md text-st-on-surface-variant">نشانی: {place(l.receiver) || "—"}</span>
            <div className="mt-1 flex flex-wrap items-center gap-st-space-md text-st-label-sm text-st-on-surface-variant">
              {l.receiver?.postal_code && <span>کد پستی: <Ltr>{l.receiver.postal_code}</Ltr></span>}{l.receiver?.phone && <span>همراه: <Ltr>{l.receiver.phone}</Ltr></span>}</div></div></div>
        <div className={box}>{head("local_shipping", "مشخصات حامل بار", <span className="rounded bg-st-secondary-fixed/60 px-st-space-xs py-0.5 text-st-label-sm text-st-secondary">{l.carrier?.name_fa || s.provider_code}</span>)}
          <div className="flex flex-col gap-1 text-st-body-sm"><span className="font-bold text-st-primary">{l.carrier?.name_fa || s.provider_code}</span>
            <span className="text-st-label-md text-st-on-surface-variant">وضعیت مرسوله: {SHIP_STATUS_FA[s.status] ?? s.status}</span>
            <span className="text-st-label-sm text-st-on-surface-variant">نام راننده/مأمور و پلاک در کادر «متصدی حمل» ثبت می‌شود.</span></div></div>
      </div>
      <div className="overflow-hidden rounded-xl bg-st-surface-container-lowest">
        <div className="flex items-center justify-between bg-st-primary-container px-st-space-md py-st-space-xs text-st-on-primary">
          <span className="flex items-center gap-1.5 text-st-title-md font-bold"><Icon name="inventory_2" className="text-[18px]" />مشخصات تفکیکی اقلام خروجی و آمادهٔ بارگیری</span>
          <span className="text-st-label-sm opacity-80">{n(items.length)} ردیف کالایی</span>
        </div>
        <div className="overflow-x-auto"><table className="w-full text-right text-st-body-sm">
          <thead className="bg-st-surface-container text-st-label-md text-st-on-surface-variant"><tr>
            <th className="w-10 px-st-space-sm py-2.5 text-center">ردیف</th><th className="px-st-space-md py-2.5">شرح کالا</th><th className="px-st-space-sm py-2.5 text-center">کد کالا</th>
            <th className="px-st-space-sm py-2.5 text-center">تعداد سفارش</th><th className="px-st-space-sm py-2.5 text-center">تعداد خروج</th><th className="px-st-space-sm py-2.5 text-center">وضعیت فیزیکی</th></tr></thead>
          <tbody className="divide-y divide-st-surface-container text-st-on-surface">{items.length ? items.map((it, i) => <tr key={`${it.product_id}-${i}`}>
            <td className="px-st-space-sm py-st-space-sm text-center">{n(i + 1)}</td><td className="px-st-space-md py-st-space-sm font-bold text-st-primary">{it.title_fa}</td>
            <td className="px-st-space-sm py-st-space-sm text-center text-st-secondary"><Ltr>{it.product_id}</Ltr></td><td className="px-st-space-sm py-st-space-sm text-center font-bold">{n(it.quantity)}</td>
            <td className="bg-st-surface-container-low/60 px-st-space-sm py-st-space-sm text-center text-st-outline">……</td>
            <td className="px-st-space-sm py-st-space-sm text-center"><span className="inline-flex items-center gap-1 text-st-label-sm text-st-outline"><span className="inline-block h-3.5 w-3.5 rounded border border-st-outline" />سالم</span></td></tr>)
            : <tr><td colSpan={6} className="px-st-space-md py-st-space-md text-center text-st-on-surface-variant">اقلامی برای این سفارش دریافت نشد.</td></tr>}</tbody>
        </table></div>
      </div>
      <div className="grid grid-cols-1 gap-st-space-md rounded-xl bg-st-surface-container-low p-st-space-md md:grid-cols-3 print:grid-cols-3">
        {[["inventory", "مجموع بسته‌ها و اقلام:", `${l.parcel_count != null ? `${n(l.parcel_count)} بسته` : "—"} · ${n(total)} قلم`, "text-st-primary"],
          ["scale", "وزن قابل‌محاسبهٔ حامل:", kg(l.billable_weight_g), "text-st-primary"],
          ["payments", "پرداخت در محل:", l.cod_amount_minor ? formatPrice(l.cod_amount_minor) : "ندارد", "text-st-error"]].map(([i, t, v, c]) =>
          <div key={t} className="flex items-center gap-st-space-sm"><div className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-surface-container-lowest text-st-primary"><Icon name={i} /></div>
            <div className="flex flex-col"><span className="text-st-label-sm text-st-on-surface-variant">{t}</span><span className={cn("text-st-title-md font-bold", c)}>{v}</span></div></div>)}
      </div>
      <div className="flex flex-col gap-1 rounded-lg bg-st-surface-container-lowest p-st-space-sm text-st-label-sm text-st-on-surface-variant">
        <div className="flex items-center gap-1 font-bold text-st-primary"><Icon name="info" className="text-[16px]" />نکات تحویل و بازرسی کالا:</div>
        <p className="leading-relaxed">۱. حامل هنگام بارگیری تعداد بسته‌ها را با این برگه تطبیق می‌دهد و هر کسری را در همین برگه یادداشت می‌کند.<br />
          ۲. تحویل‌گیرنده در صورت کسری، آسیب یا اشتباه ارسالی، گزارش مغایرت تحویل را با تصویر بارنامهٔ امضاشده تهیه کند.<br />
          ۳. این برگه از برچسب ارسال ثبت‌شده در سامانه تولید شده و با امضای سه طرف معتبر است.</p>
      </div>
      <div className="grid grid-cols-1 gap-st-space-md pt-st-space-xs md:grid-cols-3 print:grid-cols-3">
        {[["۱. تحویل‌دهنده (انباردار)", "assignment_turned_in", l.sender?.name || "فروشنده"], ["۲. متصدی حمل", "directions_car", l.carrier?.name_fa || s.provider_code], ["۳. تحویل‌گیرندهٔ مقصد", "how_to_reg", l.receiver?.name || "—"]].map(([t, i, who]) =>
          <div key={t} className="relative flex min-h-[170px] flex-col justify-between overflow-hidden rounded-xl bg-st-surface-container-low/70 p-st-space-md">
            <div className="flex flex-col gap-0.5"><div className="flex items-center justify-between"><span className="text-st-title-md font-bold text-st-primary">{t}</span><Icon name={i} className="text-[20px] text-st-secondary" /></div>
              <span className="text-st-label-sm text-st-on-surface-variant">{who}</span></div>
            <div className="my-2 flex h-12 w-28 select-none items-center justify-center self-center rounded-lg border border-dashed border-st-outline-variant text-[10px] text-st-outline">محل مهر و امضا</div>
            <div className="flex items-center justify-between pt-st-space-xs text-st-label-sm text-st-on-surface-variant"><span>امضا و تاریخ:</span><span className="font-mono text-st-outline">____/__/__</span></div>
          </div>)}
      </div>
      <div className="flex flex-col items-center justify-between gap-st-space-sm pt-st-space-sm text-st-label-sm text-st-on-surface-variant md:flex-row print:flex-row">
        <span className="flex items-center gap-1"><Icon name="verified_user" className="text-[16px] text-st-secondary" />کد رهگیری حامل: <Ltr className="font-bold text-st-primary">{s.tracking_number}</Ltr></span>
        <div className="flex flex-col items-center"><Code128 data={s.tracking_number} height={34} /><Ltr className="font-mono tracking-widest text-st-primary">{s.tracking_number}</Ltr></div>
        <span>صفحه ۱ از ۱ · نسخهٔ بایگانی فروشنده</span>
      </div>
    </section>
  );
}

export function WaybillDoc({ s, items, onClose }: { s: Shipment; items: FoItem[]; onClose: () => void }) {
  const l = s.label as Label;
  const [printing, setPrinting] = useState(false);
  const done = useCallback(() => setPrinting(false), []);
  const btn = "flex items-center gap-st-space-xs rounded-lg px-st-space-md py-st-space-xs text-st-label-lg shadow-sm transition-colors";
  return <Overlay label="حوالهٔ خروج انبار و بارنامه" onClose={onClose}>
    <div className="sticky top-0 z-10 w-full bg-st-surface-container px-st-space-md py-st-space-sm lg:px-st-margin-lg">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-st-space-sm">
        <div className="flex flex-wrap items-center gap-st-space-xs text-st-label-md text-st-on-surface-variant">
          <Icon name="warehouse" className="text-[18px]" /><span>ارسال سفارش‌ها</span><span className="text-st-outline">/</span><span className="font-bold text-st-primary">حوالهٔ خروج انبار و بارنامهٔ حمل</span>
          <span className="rounded-full bg-st-secondary-fixed px-st-space-sm py-0.5 text-st-label-sm font-bold text-st-on-secondary-fixed">سفارش متصل: <Ltr>{l.reference?.order_number || `#${s.fulfillment_order_id}`}</Ltr></span>
        </div>
        <div className="flex flex-wrap items-center gap-st-space-xs">
          <button type="button" onClick={() => setPrinting(true)} className={cn(btn, "bg-st-primary-container text-st-on-primary hover:bg-st-secondary")}><Icon name="print" className="text-[18px]" />چاپ سند (A4)</button>
          <button type="button" onClick={() => setPrinting(true)} className={cn(btn, "bg-st-surface-container-lowest text-st-on-surface hover:bg-st-surface-container-high")}><Icon name="picture_as_pdf" className="text-[18px] text-st-error" />ذخیرهٔ PDF</button>
          <button type="button" onClick={onClose} className={cn(btn, "bg-st-surface-container-high px-st-space-sm text-st-on-surface-variant shadow-none hover:bg-st-surface-container-highest")}><Icon name="close" className="text-[18px]" />بستن</button>
        </div>
      </div>
    </div>
    <div className="w-full px-st-space-md pt-st-space-md lg:px-st-margin-lg">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-st-space-md rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm">
        <div className="flex items-center gap-st-space-sm"><div className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-secondary-fixed text-st-secondary"><Icon name="published_with_changes" /></div>
          <div className="flex flex-col"><span className="text-st-title-md font-bold text-st-primary">برچسب ارسال صادر شده — {SHIP_STATUS_FA[s.status] ?? s.status}</span>
            <span className="text-st-label-sm text-st-on-surface-variant">اطلاعات این برگه از برچسب ثبت‌شدهٔ مرسوله و اقلام سفارش تأمین خوانده می‌شود.</span></div></div>
        <div className="flex items-center gap-st-space-lg text-st-label-sm text-st-on-surface-variant">
          <div className="flex flex-col"><span>مهلت تحویل</span><span className="text-st-title-md font-bold text-st-primary">{s.deliver_by_at ? faDate(s.deliver_by_at.slice(0, 10)) : "—"}</span></div>
          <div className="h-8 w-px bg-st-outline-variant/40" />
          <div className="flex flex-col"><span>کد رهگیری حامل</span><Ltr className="text-st-title-md font-bold text-st-secondary">{s.tracking_number}</Ltr></div>
        </div>
      </div>
    </div>
    <div className="flex w-full items-start justify-center px-st-space-md py-st-space-lg"><WaybillPaper s={s} items={items} /></div>
    {printing && <PrintSheet onDone={done}><WaybillPaper s={s} items={items} /></PrintSheet>}
  </Overlay>;
}

// ── Screens 01/04: برگه تحویل ناوگان راننده (mobile) ──────────────────────────────────────
/** Mobile exit slip for the fleet driver: barcode, call, copy address, items checklist. */
export function DriverSheet({ s, items, onClose, onDiscrepancy }: { s: Shipment; items: FoItem[]; onClose: () => void; onDiscrepancy?: () => void }) {
  const l = s.label as Label;
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState(false);
  const allDone = items.length > 0 && checked.size === items.length;
  const addr = place(l.receiver);
  const card = "rounded-2xl bg-st-surface-container-lowest p-st-space-md shadow-sm";
  return <Overlay label="برگهٔ خروج — نسخهٔ راننده" onClose={onClose} className="bg-st-surface-container-low">
    <div className="mx-auto flex min-h-full max-w-md flex-col">
      <header className="sticky top-0 z-10 flex h-14 items-center justify-between bg-st-surface-container-lowest px-st-space-sm shadow-sm">
        <button type="button" onClick={onClose} aria-label="بازگشت" className="flex h-10 w-10 items-center justify-center rounded-full text-st-primary"><Icon name="arrow_forward" /></button>
        <h1 className="text-st-title-md font-bold text-st-primary">برگهٔ تحویل راننده</h1>
        <span className="h-10 w-10" />
      </header>
      <div className="flex flex-1 flex-col gap-st-space-md p-st-space-md pb-36">
        <section className={card}>
          <div className="flex items-start justify-between gap-st-space-sm">
            <div className="flex items-center gap-st-space-sm"><div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-st-surface-container text-st-primary"><Icon name="local_shipping" /></div>
              <div className="flex flex-col"><span className="text-st-title-md font-bold text-st-primary">{l.carrier?.name_fa || s.provider_code}</span>
                <span className="text-st-label-sm text-st-on-surface-variant">حوالهٔ تحویل و خروج انبار فروشنده</span></div></div>
            <span className="rounded-md bg-st-surface-container px-2 py-0.5 text-st-label-sm text-st-on-surface-variant">{LEVEL_FA[l.carrier?.service_level || s.service_level] ?? s.service_level}</span>
          </div>
          <div className="mt-st-space-sm flex items-center justify-between rounded-xl bg-st-surface-container-low px-st-space-sm py-st-space-xs text-st-label-sm">
            <span className="flex items-center gap-1 text-st-on-surface-variant"><span className="h-2 w-2 rounded-full bg-st-on-tertiary-container" />وضعیت: {SHIP_STATUS_FA[s.status] ?? s.status}</span>
            {s.deliver_by_at && <span className="rounded-md bg-st-surface-container-lowest px-2 py-0.5 text-st-on-surface-variant">مهلت {faDate(s.deliver_by_at.slice(0, 10))}</span>}
          </div>
        </section>
        <section className={card}>
          <div className="mb-st-space-sm flex items-center justify-between"><h2 className="flex items-center gap-1 text-st-title-md font-bold text-st-primary"><Icon name="qr_code_scanner" className="text-[20px]" />شناسهٔ حواله و بارکد خروج</h2>
            <span className="rounded-md bg-st-surface-container px-2 py-0.5 text-st-label-sm text-st-on-surface-variant">بارکد فعال</span></div>
          <div className="flex flex-col items-center gap-1 rounded-xl p-st-space-sm" style={{ background: "#fff" }}>
            <Code128 data={s.tracking_number} height={64} /><span className="font-mono text-sm tracking-[0.2em] text-[#0A2735]" dir="ltr">*{s.tracking_number}*</span></div>
          <div className="mt-st-space-sm flex items-center justify-between rounded-xl bg-st-primary-container px-st-space-md py-st-space-sm text-st-on-primary">
            <span className="text-st-label-sm opacity-80">شمارهٔ سفارش</span><Ltr className="text-st-title-lg font-bold">{l.reference?.order_number || "—"}</Ltr></div>
        </section>
        <section className={card}>
          <div className="mb-st-space-xs flex items-center justify-between"><h2 className="flex items-center gap-1 text-st-title-md font-bold text-st-primary"><Icon name="apartment" className="text-[20px]" />تحویل‌گیرنده و مقصد</h2></div>
          <p className="text-st-title-md font-bold text-st-on-surface">{l.receiver?.name || "—"}</p>
          {l.receiver?.phone && <a href={`tel:${l.receiver.phone}`} className="mt-st-space-sm flex min-h-12 items-center justify-center gap-st-space-xs rounded-xl bg-st-secondary-fixed px-st-space-md text-st-title-md font-bold text-st-on-secondary-fixed">
            <Icon name="call" />تماس با تحویل‌گیرنده <Ltr>({toPersianNum(l.receiver.phone)})</Ltr></a>}
          <div className="mt-st-space-sm flex items-start gap-st-space-xs rounded-xl bg-st-surface-container-low p-st-space-sm">
            <Icon name="location_on" className="text-[20px] text-st-tertiary-container" />
            <div className="flex-1"><p className="text-st-body-md leading-7 text-st-on-surface">{addr || "—"}</p>
              {l.receiver?.postal_code && <p className="text-st-label-sm text-st-on-surface-variant">کد پستی: <Ltr>{l.receiver.postal_code}</Ltr></p>}</div>
          </div>
          {addr && <button type="button" onClick={() => navigator.clipboard?.writeText(addr).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1800); })}
            className="mt-st-space-sm flex min-h-11 w-full items-center justify-center gap-st-space-xs rounded-xl bg-st-surface-container text-st-label-lg text-st-on-surface"><Icon name="content_copy" className="text-[18px]" />{copied ? "کپی شد" : "کپی آدرس"}</button>}
        </section>
        <section className={card}>
          <h2 className="mb-st-space-sm flex items-center gap-1 text-st-title-md font-bold text-st-primary"><Icon name="inventory_2" className="text-[20px]" />خلاصهٔ بار و بسته‌بندی</h2>
          <div className="grid grid-cols-3 gap-st-space-xs text-center">
            {[["تعداد بسته‌ها", l.parcel_count != null ? `${n(l.parcel_count)} مرسوله` : "—", "طبق برچسب"], ["وزن قابل‌محاسبه", kg(l.billable_weight_g), "اعلام حامل"], ["اقلام سفارش", `${n(items.reduce((t, i) => t + i.quantity, 0))} عدد`, `${n(items.length)} ردیف`]].map(([t, v, sub]) =>
              <div key={t} className="flex flex-col gap-0.5 rounded-xl bg-st-surface-container-low p-st-space-xs"><span className="text-st-label-sm text-st-on-surface-variant">{t}</span><b className="text-st-title-md text-st-primary">{v}</b><span className="text-st-label-sm text-st-outline">{sub}</span></div>)}
          </div>
        </section>
        <section className={card}>
          <div className="mb-st-space-xs flex items-center justify-between"><h2 className="flex items-center gap-1 text-st-title-md font-bold text-st-primary"><Icon name="fact_check" className="text-[20px]" />چک‌لیست اقلام هنگام بارگیری</h2>
            <span className="rounded-full bg-st-surface-container px-2 py-0.5 text-st-label-sm text-st-on-surface-variant">{n(checked.size)} از {n(items.length)}</span></div>
          <p className="mb-st-space-sm text-st-body-sm text-st-on-surface-variant">هر ردیف را پس از شمارش روی بار تیک بزنید.</p>
          <ul className="flex flex-col gap-st-space-xs">{items.map((it) => {
            const on = checked.has(it.product_id);
            return <li key={it.product_id}><label className={cn("flex min-h-14 cursor-pointer items-center gap-st-space-sm rounded-xl px-st-space-sm py-st-space-xs", on ? "bg-st-secondary-fixed/60" : "bg-st-surface-container-low")}>
              <input type="checkbox" className="h-6 w-6 shrink-0 accent-[#0a2735]" checked={on} onChange={() => setChecked((c) => { const x = new Set(c); if (x.has(it.product_id)) x.delete(it.product_id); else x.add(it.product_id); return x; })} />
              <span className="flex flex-1 flex-col"><b className="text-st-title-md text-st-on-surface">{it.title_fa}</b><span className="text-st-label-sm text-st-on-surface-variant">{n(it.quantity)} عدد · کد کالا <Ltr>{it.product_id}</Ltr></span></span></label></li>;
          })}</ul>
        </section>
        {onDiscrepancy && <button type="button" onClick={onDiscrepancy} className="flex min-h-14 items-center justify-between rounded-2xl bg-st-surface-container-lowest px-st-space-md text-st-title-md font-bold text-st-error shadow-sm">
          <span className="flex items-center gap-st-space-xs"><Icon name="warning" />ثبت مغایرت، کسری اقلام یا آسیب بسته</span><Icon name="chevron_left" className="text-st-outline" /></button>}
        <p className="flex items-center gap-1 text-st-label-sm text-st-on-surface-variant"><Icon name="shield" className="text-[16px]" />این چک‌لیست فقط روی همین صفحه است و وضعیت مرسوله را در سامانه تغییر نمی‌دهد.</p>
      </div>
      <div className="fixed inset-x-0 bottom-0 bg-st-surface-container-lowest/95 px-st-space-md pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-st-space-sm shadow-[0_-4px_16px_rgba(0,0,0,0.06)]">
        <div className={cn("mx-auto flex min-h-14 max-w-md items-center justify-center gap-st-space-xs rounded-2xl text-st-title-md font-bold", allDone ? "bg-st-on-tertiary-container text-st-on-primary" : "bg-st-surface-container text-st-on-surface-variant")} role="status">
          <Icon name={allDone ? "task_alt" : "pending_actions"} />{allDone ? "همهٔ اقلام کنترل شد" : `${n(checked.size)} از ${n(items.length)} قلم کنترل شده`}</div>
      </div>
    </div>
  </Overlay>;
}

// ── Screens 31 / 37 / 34: پروندهٔ مغایرت بارنامه در برابر سفارش ───────────────────────────
const REASONS = ["کسری", "آسیب‌دیده", "اشتباه ارسالی", "مازاد"] as const;
type Line = { delivered: string; reason: string; note: string };

function DiscrepancyPaper({ s, rows, photo, totals }: { s: Shipment; rows: Row[]; photo: string | null; totals: Totals }) {
  const l = s.label as Label;
  return <section className="flex flex-col gap-st-space-md rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-md print:p-0 print:shadow-none">
    <div className="flex items-center justify-between rounded-lg bg-st-surface-container-low px-st-space-md py-st-space-xs text-st-label-sm text-st-on-surface-variant">
      <span className="flex items-center gap-1"><Icon name="gavel" className="text-[16px]" />گزارش تهیه‌شده توسط فروشنده بر اساس شمارش هنگام تحویل</span><span className="font-bold">نسخهٔ قابل چاپ</span></div>
    <div className="flex items-start justify-between gap-st-space-md">
      <div className="flex items-center gap-st-space-sm">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img alt="شصت‌آنلاین" className="h-12 w-auto" src="/brand/60online-mark.png" />
        <div className="flex flex-col"><h1 className="text-st-headline-md font-bold text-st-primary">صورت‌جلسهٔ مغایرت تحویل کالا</h1><span className="text-st-label-sm text-st-on-surface-variant">شصت‌آنلاین · سامانهٔ فروش و ارسال فروشندگان</span></div>
      </div>
      <dl className="grid grid-cols-[auto_auto] gap-x-st-space-sm gap-y-0.5 rounded-lg bg-st-surface-container-low p-st-space-sm text-st-label-sm">
        <dt className="text-st-on-surface-variant">شمارهٔ صورت‌جلسه:</dt><dd className="font-bold text-st-primary"><Ltr>DR-{s.fulfillment_order_id}</Ltr></dd>
        <dt className="text-st-on-surface-variant">تاریخ تنظیم:</dt><dd className="font-bold">{today()}</dd>
        <dt className="text-st-on-surface-variant">شناسهٔ مرسوله:</dt><dd className="font-bold text-st-secondary"><Ltr>{s.tracking_number}</Ltr></dd>
      </dl>
    </div>
    <div className="grid grid-cols-2 gap-st-space-sm">
      {[["store", "فروشنده و مبدأ ارسال", l.sender], ["apartment", "تحویل‌گیرنده و مقصد", l.receiver]].map(([icon, t, p]) => {
        const party = p as Party | undefined;
        return <div key={t as string} className="flex flex-col gap-1 rounded-xl bg-st-surface-container-low/60 p-st-space-md text-st-label-md text-st-on-surface-variant">
          <span className="flex items-center gap-1 text-st-title-md font-bold text-st-primary"><Icon name={icon as string} className="text-[18px]" />{t as string}:</span>
          <span>نام: {party?.name || "—"}</span><span>نشانی: {place(party) || "—"}</span>
          {t === "فروشنده و مبدأ ارسال" ? <span>شمارهٔ سفارش: <Ltr>{l.reference?.order_number || "—"}</Ltr></span> : <span>حامل: {l.carrier?.name_fa || s.provider_code}</span>}
        </div>;
      })}
    </div>
    <div className="flex items-center justify-between"><h2 className="text-st-title-md font-bold text-st-primary">جدول اقلام سفارش در برابر تحویل فیزیکی:</h2><span className="text-st-label-sm text-st-on-surface-variant">واحد: عدد</span></div>
    <table className="w-full overflow-hidden rounded-lg text-right text-st-body-sm">
      <thead className="bg-st-surface-container text-st-label-md text-st-on-surface-variant"><tr>
        <th className="px-st-space-xs py-2">ردیف</th><th className="px-st-space-xs py-2">شرح کالا</th><th className="px-st-space-xs py-2">سفارش</th><th className="px-st-space-xs py-2">تحویل</th><th className="px-st-space-xs py-2">مغایرت</th><th className="px-st-space-xs py-2">علت و توضیح</th><th className="px-st-space-xs py-2">وضعیت</th></tr></thead>
      <tbody className="divide-y divide-st-surface-container">{rows.map((r, i) => <tr key={r.it.product_id}>
        <td className="px-st-space-xs py-st-space-sm">{n(i + 1)}</td><td className="px-st-space-xs py-st-space-sm font-bold text-st-primary">{r.it.title_fa}<span className="block text-st-label-sm font-normal text-st-on-surface-variant">کد کالا <Ltr>{r.it.product_id}</Ltr></span></td>
        <td className="px-st-space-xs py-st-space-sm">{n(r.it.quantity)}</td><td className="px-st-space-xs py-st-space-sm font-bold text-st-secondary">{Number.isNaN(r.d) ? "—" : n(r.d)}</td>
        <td className={cn("px-st-space-xs py-st-space-sm font-bold", r.diff ? "text-st-error" : "text-st-on-surface-variant")}>{r.diff === 0 ? "۰" : r.diff > 0 ? `+${n(r.diff)}` : `−${n(-r.diff)}`}</td>
        <td className={cn("px-st-space-xs py-st-space-sm", r.diff || r.reason ? "text-st-error" : "text-st-on-surface-variant")}>{[r.reason, r.note].filter(Boolean).join(" — ") || "مطابق"}</td>
        <td className="px-st-space-xs py-st-space-sm"><span className={cn("rounded px-1.5 py-0.5 text-st-label-sm font-bold", r.diff === 0 && !r.reason ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-error text-st-on-error")}>{r.diff === 0 && !r.reason ? "تطابق" : r.reason || "مغایرت"}</span></td></tr>)}</tbody>
    </table>
    <div className="flex items-start gap-st-space-md rounded-xl bg-st-surface-container-low p-st-space-md">
      <div className="flex h-24 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-st-surface-container">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {photo ? <img src={photo} alt="تصویر بارنامهٔ امضاشده" className="h-full w-full object-cover" /> : <Icon name="image" className="text-st-outline" />}</div>
      <div className="flex flex-col gap-1 text-st-label-md text-st-on-surface-variant"><span className="flex items-center gap-1 font-bold text-st-primary"><Icon name="verified" className="text-[16px]" />ضمیمه: تصویر بارنامهٔ امضاشده</span>
        <span>{photo ? "تصویر بارنامهٔ امضاشده به این گزارش ضمیمه شده است." : "تصویری ضمیمه نشده است."}</span></div>
    </div>
    <div className="rounded-xl bg-st-primary p-st-space-md text-st-on-primary">
      <span className="flex items-center gap-1 font-bold"><Icon name="fact_check" className="text-[18px]" />خلاصهٔ مغایرت:</span>
      <p className="mt-1 text-st-body-sm">اقلام بدون مغایرت: {n(totals.matched)} · کسری: {n(totals.short)} عدد · مازاد: {n(totals.extra)} عدد · ردیف آسیب‌دیده: {n(totals.damaged)}</p>
    </div>
    <div className="grid grid-cols-3 gap-st-space-sm rounded-xl bg-st-surface-container-low p-st-space-sm">
      {["تحویل‌گیرنده / نمایندهٔ خریدار", "نمایندهٔ حمل", "فروشنده / انباردار"].map((t) => <div key={t} className="flex min-h-[120px] flex-col items-center justify-between rounded-lg bg-st-surface-container-lowest p-st-space-sm text-center">
        <span className="text-st-label-sm text-st-on-surface-variant">{t}</span><span className="text-st-label-sm text-st-outline">نام، امضا و تاریخ</span></div>)}
    </div>
  </section>;
}

type Row = { it: FoItem; d: number; diff: number } & Line;
type Totals = { matched: number; short: number; extra: number; damaged: number };

/** Waybill-vs-order delivery discrepancy: photo of the signed waybill + delivered qty per item → printable report. */
export function DiscrepancySheet({ s, items, onClose }: { s: Shipment; items: FoItem[]; onClose: () => void }) {
  const l = s.label as Label;
  const [lines, setLines] = useState<Record<number, Line>>(() => Object.fromEntries(items.map((i) => [i.product_id, { delivered: String(i.quantity), reason: "", note: "" }])));
  const [photo, setPhoto] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [printing, setPrinting] = useState(false), [zoom, setZoom] = useState(false);
  const [scale, setScale] = useState(1), [rot, setRot] = useState(0);
  const done = useCallback(() => setPrinting(false), []);
  const qty = (pid: number) => { const v = Number((lines[pid]?.delivered ?? "").replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))); return Number.isFinite(v) && v >= 0 && (lines[pid]?.delivered ?? "") !== "" ? Math.floor(v) : NaN; };
  const rows: Row[] = items.map((it) => { const d = qty(it.product_id); return { it, d, diff: Number.isNaN(d) ? 0 : d - it.quantity, ...lines[it.product_id] }; });
  const invalid = rows.some((r) => Number.isNaN(r.d));
  const flagged = rows.filter((r) => r.diff !== 0 || r.reason);
  const missingReason = rows.some((r) => r.diff !== 0 && !r.reason);
  const set = (pid: number, k: keyof Line, v: string) => setLines((c) => ({ ...c, [pid]: { ...c[pid], [k]: v } }));
  const bump = (pid: number, by: number) => { const cur = qty(pid); set(pid, "delivered", String(Math.max(0, (Number.isNaN(cur) ? 0 : cur) + by))); };
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = ""; setErr(null);
    if (!f) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) { setErr("فقط تصویر PNG، JPG یا WebP"); return; }
    if (f.size > 5 * 1024 * 1024) { setErr("حجم تصویر باید کمتر از ۵ مگابایت باشد"); return; }
    const r = new FileReader(); r.onload = () => setPhoto(typeof r.result === "string" ? r.result : null); r.readAsDataURL(f);
  };
  const totals: Totals = { matched: rows.length - flagged.length, short: rows.filter((r) => r.diff < 0).reduce((t, r) => t - r.diff, 0),
    extra: rows.filter((r) => r.diff > 0).reduce((t, r) => t + r.diff, 0), damaged: rows.filter((r) => r.reason === "آسیب‌دیده").length };
  const canPrint = !invalid && !missingReason;
  const card = "rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-sm";

  return <Overlay label="پروندهٔ مغایرت تحویل" onClose={onClose} className="bg-st-surface">
    <header className="sticky top-0 z-10 border-b border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-st-space-sm lg:px-st-margin-lg">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-st-space-sm lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-st-space-sm">
          <button type="button" onClick={onClose} aria-label="بازگشت" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-st-surface-container text-st-primary lg:hidden"><Icon name="arrow_forward" /></button>
          <div className="flex flex-col gap-0.5">
            <span className="hidden text-st-label-sm text-st-on-surface-variant lg:block">ارسال سفارش‌ها / ثبت مغایرت سفارش <Ltr>{l.reference?.order_number || ""}</Ltr></span>
            <h1 className="flex items-center gap-st-space-xs text-st-title-lg font-bold text-st-primary"><span className="h-2 w-2 rounded-full bg-st-tertiary-container" />پروندهٔ مغایرت: <Ltr>DR-{s.fulfillment_order_id}</Ltr></h1>
            <div className="flex flex-wrap items-center gap-st-space-sm text-st-label-sm text-st-on-surface-variant">
              <span className="flex items-center gap-1"><Icon name="local_shipping" className="text-[16px]" />بارنامه: <Ltr>{s.tracking_number}</Ltr></span>
              {flagged.length > 0 && <span className="rounded-full bg-st-error-container px-2 py-0.5 font-bold text-st-on-error-container">{n(flagged.length)} ردیف نیازمند بررسی</span>}
            </div>
          </div>
        </div>
        <div className="hidden items-center gap-st-space-sm lg:flex">
          <button type="button" onClick={onClose} className="flex items-center gap-st-space-xs rounded-xl bg-st-surface-container px-st-space-md py-st-space-sm text-st-label-lg text-st-on-surface"><Icon name="close" className="text-[18px]" />بستن</button>
          <button type="button" disabled={!canPrint} onClick={() => setPrinting(true)} className="flex items-center gap-st-space-xs rounded-xl bg-st-surface-container-high px-st-space-md py-st-space-sm text-st-label-lg text-st-on-surface disabled:opacity-40"><Icon name="picture_as_pdf" className="text-[18px] text-st-error" />ذخیرهٔ PDF</button>
          <button type="button" disabled={!canPrint} onClick={() => setPrinting(true)} className="flex items-center gap-st-space-xs rounded-xl bg-st-primary px-st-space-lg py-st-space-sm text-st-label-lg font-bold text-st-on-primary disabled:opacity-40"><Icon name="print" className="text-[18px]" />چاپ سند A4 مغایرت</button>
        </div>
      </div>
    </header>

    <div className="mx-auto grid max-w-[1440px] grid-cols-1 gap-st-space-xl px-st-space-md py-st-space-lg pb-40 lg:grid-cols-12 lg:px-st-margin-lg lg:pb-st-space-xl">
      <div className="hidden lg:order-2 lg:col-span-7 lg:block"><DiscrepancyPaper s={s} rows={rows} photo={photo} totals={totals} /></div>
      <div className="flex flex-col gap-st-space-lg lg:order-1 lg:col-span-5">
        <section className={card}>
          <div className="flex items-start justify-between"><div className="flex items-center gap-st-space-sm">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-st-primary text-st-on-primary"><Icon name="assignment" /></div>
            <div className="flex flex-col"><h2 className="text-st-title-lg font-bold text-st-primary">اطلاعات پروندهٔ تحویل کالا</h2><span className="text-st-label-sm text-st-on-surface-variant">بررسی تطبیق اقلام تحویلی در محل مشتری</span></div></div>
            <span className="rounded-full bg-st-secondary-fixed px-2 py-0.5 text-st-label-sm font-bold text-st-on-secondary-fixed">{SHIP_STATUS_FA[s.status] ?? s.status}</span></div>
          <dl className="mt-st-space-md grid grid-cols-2 gap-st-space-sm rounded-xl bg-st-surface-container-low p-st-space-md text-st-label-sm">
            <div><dt className="text-st-on-surface-variant">شمارهٔ سفارش مبدأ:</dt><dd className="break-all text-st-title-md font-bold text-st-primary"><Ltr>{l.reference?.order_number || "—"}</Ltr></dd></div>
            <div><dt className="text-st-on-surface-variant">کد رهگیری:</dt><dd className="text-st-title-md font-bold text-st-secondary"><Ltr>{s.tracking_number}</Ltr></dd></div>
            <div><dt className="text-st-on-surface-variant">حامل:</dt><dd className="font-bold text-st-on-surface">{l.carrier?.name_fa || s.provider_code}</dd></div>
            <div><dt className="text-st-on-surface-variant">تحویل‌گیرنده:</dt><dd className="font-bold text-st-on-surface">{l.receiver?.name || "—"}</dd></div>
          </dl>
        </section>

        <section className={card}>
          <div className="flex items-center justify-between"><h2 className="flex items-center gap-st-space-xs text-st-title-lg font-bold text-st-primary"><Icon name="document_scanner" className="text-st-secondary" />مستندات فیزیکی و بارنامه</h2>
            <span className="text-st-label-sm text-st-on-surface-variant">{photo ? "۱ فایل ضمیمه" : "بدون ضمیمه"}</span></div>
          <p className="mt-1 text-st-body-sm text-st-on-surface-variant">تصویر بارنامهٔ امضاشده توسط تحویل‌گیرنده (JPG/PNG/WebP، حداکثر ۵ مگابایت)؛ فقط در همین گزارش استفاده می‌شود.</p>
          <div className="mt-st-space-sm overflow-hidden rounded-xl bg-st-surface-container">
            {photo ? <button type="button" onClick={() => setZoom(true)} className="relative block h-52 w-full">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={photo} alt="تصویر بارنامهٔ امضاشده" className="h-full w-full object-cover" />
              <span className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1 bg-gradient-to-t from-black/60 to-transparent py-st-space-sm text-st-label-lg font-bold text-white"><Icon name="zoom_in" />مشاهده و بزرگ‌نمایی تصویر بارنامه</span></button>
              : <label className="flex h-44 cursor-pointer flex-col items-center justify-center gap-st-space-xs border-2 border-dashed border-st-outline-variant text-st-on-surface-variant">
                <Icon name="photo_camera" className="text-[32px] text-st-outline" /><b className="text-st-title-md text-st-primary">افزودن تصویر بارنامهٔ امضاشده</b><span className="text-st-label-sm">عکس یا اسکن</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" capture="environment" className="sr-only" onChange={pick} /></label>}
          </div>
          {photo && <label className="mt-st-space-xs flex cursor-pointer items-center justify-center gap-1 text-st-label-md text-st-secondary"><Icon name="cached" className="text-[16px]" />تغییر تصویر
            <input type="file" accept="image/png,image/jpeg,image/webp" capture="environment" className="sr-only" onChange={pick} /></label>}
          {err && <p role="alert" className="mt-st-space-xs text-st-label-md text-st-error">{err}</p>}
        </section>

        <section className={card}>
          <div className="flex items-center justify-between"><div><h2 className="text-st-title-lg font-bold text-st-primary">ثبت اقلام و تطبیق فیزیکی</h2><span className="text-st-label-sm text-st-on-surface-variant">ثبت تفکیکی کسری، خسارت و سلامت کالا</span></div>
            <button type="button" aria-label="بازنشانی شمارش" onClick={() => setLines(Object.fromEntries(items.map((i) => [i.product_id, { delivered: String(i.quantity), reason: "", note: "" }])))} className="flex h-9 w-9 items-center justify-center rounded-full text-st-on-surface-variant hover:bg-st-surface-container"><Icon name="refresh" /></button></div>
          <ul className="mt-st-space-md flex flex-col gap-st-space-md">{rows.map((r, i) => {
            const bad = r.diff !== 0 || !!r.reason;
            return <li key={r.it.product_id} className={cn("rounded-xl p-st-space-md", bad ? (r.reason === "آسیب‌دیده" ? "bg-st-surface-container-high" : "bg-st-error-container/40") : "")}>
              <div className="flex items-start justify-between gap-st-space-sm">
                <div className="flex items-start gap-st-space-xs"><span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-st-label-sm font-bold", bad ? "bg-st-error text-st-on-error" : "bg-st-surface-container text-st-on-surface-variant")}>{n(i + 1)}</span>
                  <div className="flex flex-col"><b className="text-st-title-md text-st-primary">{r.it.title_fa}</b><span className="text-st-label-sm text-st-on-surface-variant">کد کالا: <Ltr>{r.it.product_id}</Ltr></span></div></div>
                <span className={cn("flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-st-label-sm font-bold", bad ? "bg-st-error text-st-on-error" : "bg-st-secondary-fixed text-st-on-secondary-fixed")}>
                  <Icon name={bad ? "remove_circle" : "check_circle"} className="text-[14px]" />{bad ? (r.reason || (r.diff < 0 ? `کسری (${n(-r.diff)})` : `مازاد (${n(r.diff)})`)) : "تطابق کامل"}</span>
              </div>
              {!bad && <div className="mt-st-space-sm grid grid-cols-3 gap-st-space-xs rounded-lg bg-st-surface-container-low p-st-space-sm text-st-label-sm">
                <div><span className="text-st-on-surface-variant">سفارش:</span><b className="block text-st-title-md text-st-primary">{n(r.it.quantity)}</b></div>
                <div><span className="text-st-on-surface-variant">تحویل فیزیکی:</span><b className="block text-st-title-md text-st-secondary">{n(r.d)}</b></div>
                <div><span className="text-st-on-surface-variant">مغایرت:</span><b className="block text-st-title-md">۰</b></div></div>}
              <div className="mt-st-space-sm grid grid-cols-2 gap-st-space-sm">
                <div className="flex flex-col gap-1"><span className="text-st-label-sm text-st-on-surface-variant">تعداد تحویل‌شده:</span>
                  <div className="flex items-stretch overflow-hidden rounded-lg border border-st-outline-variant bg-st-surface-container-lowest">
                    <button type="button" aria-label="افزودن" onClick={() => bump(r.it.product_id, 1)} className="px-2 text-st-on-surface-variant"><Icon name="add" className="text-[18px]" /></button>
                    <input aria-label={`تعداد تحویل‌شدهٔ ${r.it.title_fa}`} inputMode="numeric" value={r.delivered} onChange={(e) => set(r.it.product_id, "delivered", e.target.value)} aria-invalid={Number.isNaN(r.d)}
                      className={cn("min-w-0 flex-1 border-x border-st-outline-variant bg-transparent py-2 text-center text-st-title-md font-bold outline-none", bad ? "text-st-error" : "text-st-primary")} />
                    <button type="button" aria-label="کم کردن" onClick={() => bump(r.it.product_id, -1)} className="px-2 text-st-on-surface-variant"><Icon name="remove" className="text-[18px]" /></button></div></div>
                <label className="flex flex-col gap-1 text-st-label-sm text-st-on-surface-variant">علت مغایرت:
                  <select value={r.reason} onChange={(e) => set(r.it.product_id, "reason", e.target.value)} className="rounded-lg border border-st-outline-variant bg-st-surface-container-lowest px-2 py-2 text-st-body-md text-st-on-surface">
                    <option value="">بدون مغایرت</option>{REASONS.map((x) => <option key={x}>{x}</option>)}</select></label>
              </div>
              {r.diff !== 0 && <p className="mt-1 text-st-label-sm font-semibold text-st-error">{r.diff < 0 ? `${n(-r.diff)} عدد کمتر از سفارش` : `${n(r.diff)} عدد بیشتر از سفارش`}{!r.reason && " — علت را انتخاب کنید"}</p>}
              {bad && <input value={r.note} onChange={(e) => set(r.it.product_id, "note", e.target.value)} maxLength={200} placeholder="شرح مغایرت (اختیاری)" className="mt-st-space-sm w-full rounded-lg border border-st-outline-variant bg-st-surface-container-lowest px-st-space-sm py-2 text-st-body-sm" />}
            </li>;
          })}</ul>
        </section>

        <section className="rounded-2xl bg-st-primary p-st-space-lg text-st-on-primary shadow-xl">
          <div className="flex items-center justify-between"><h2 className="flex items-center gap-st-space-xs text-st-title-lg font-bold"><Icon name="analytics" />خلاصهٔ مغایرت اقلام</h2>
            <span className="rounded-full bg-st-primary-container px-2 py-0.5 text-st-label-sm">محاسبه از شمارش شما</span></div>
          <div className="mt-st-space-md grid grid-cols-3 gap-st-space-sm">
            {[["اقلام تطابق کامل", `${n(totals.matched)} قلم`, `از ${n(rows.length)} ردیف`], ["کسری / مازاد", `${n(totals.short)} / ${n(totals.extra)}`, "عدد"], ["آسیب‌دیده", `${n(totals.damaged)} ردیف`, "با علت آسیب‌دیده"]].map(([t, v, sub]) =>
              <div key={t} className="rounded-xl bg-st-primary-container p-st-space-sm"><span className="text-st-label-sm opacity-80">{t}:</span><b className="block text-st-headline-md">{v}</b><span className="text-st-label-sm opacity-70">{sub}</span></div>)}
          </div>
          <p className="mt-st-space-md flex items-start gap-1 rounded-xl bg-st-primary-container/60 p-st-space-sm text-st-label-sm opacity-90"><Icon name="info" className="text-[16px]" />این پرونده در سامانه ذخیره نمی‌شود و برآورد ریالی خسارت ندارد؛ PDF آن را برای پیگیری با حامل یا پشتیبانی نگه دارید.</p>
        </section>
      </div>
    </div>

    <div className="fixed inset-x-0 bottom-0 flex flex-col gap-st-space-xs bg-st-surface-container-lowest px-st-space-md pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-st-space-sm shadow-[0_-4px_16px_rgba(0,0,0,0.06)] lg:hidden">
      <button type="button" disabled={!canPrint} onClick={() => setPrinting(true)} className="flex min-h-12 items-center justify-center gap-st-space-xs rounded-2xl bg-st-primary text-st-title-md font-bold text-st-on-primary disabled:opacity-40"><Icon name="print" />مشاهدهٔ صورت‌جلسه و چاپ A4</button>
      <button type="button" onClick={onClose} className="self-start rounded-xl bg-st-surface-container px-st-space-md py-st-space-xs text-st-label-lg text-st-on-surface">بستن</button>
    </div>

    {zoom && photo && createPortal(<div role="dialog" aria-modal="true" aria-label="بزرگ‌نمایی تصویر بارنامه" dir="rtl" className="fixed inset-0 z-[96] flex flex-col bg-[#101c22] text-white">
      <div className="flex items-center justify-between gap-st-space-sm p-st-space-sm">
        <button type="button" onClick={() => setZoom(false)} aria-label="بستن" className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10"><Icon name="close" /></button>
        <div className="flex min-w-0 flex-1 flex-col"><b className="truncate">بررسی تصویر بارنامه</b><span className="truncate text-st-label-sm opacity-70">مرسوله <Ltr>{s.tracking_number}</Ltr></span></div>
        <button type="button" aria-label="چرخش" onClick={() => setRot((r) => (r + 90) % 360)} className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10"><Icon name="rotate_right" /></button>
        <div className="flex h-11 items-center gap-1 rounded-xl bg-white/10 px-1">
          <button type="button" aria-label="بزرگ‌نمایی" onClick={() => setScale((x) => Math.min(3, x + 0.25))} className="flex h-9 w-9 items-center justify-center"><Icon name="zoom_in" /></button>
          <span className="w-12 text-center text-st-label-md" dir="ltr">{toPersianNum(Math.round(scale * 100))}٪</span>
          <button type="button" aria-label="کوچک‌نمایی" onClick={() => setScale((x) => Math.max(0.5, x - 0.25))} className="flex h-9 w-9 items-center justify-center"><Icon name="zoom_out" /></button></div>
      </div>
      <div className="flex flex-1 items-center justify-center overflow-auto p-st-space-sm">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={photo} alt="تصویر بارنامهٔ امضاشده" style={{ transform: `scale(${scale}) rotate(${rot}deg)` }} className="max-h-full max-w-full object-contain transition-transform" /></div>
      <div className="flex flex-col gap-st-space-xs p-st-space-sm">
        <a href={photo} download={`waybill-${s.tracking_number}.jpg`} className="flex min-h-12 items-center justify-center gap-st-space-xs rounded-xl bg-white font-bold text-[#0a2735]"><Icon name="download" />ذخیرهٔ تصویر</a>
        <button type="button" onClick={() => setZoom(false)} className="py-st-space-xs text-st-label-md opacity-80">بازگشت به برگهٔ پرونده</button></div>
    </div>, document.body)}

    {printing && <PrintSheet onDone={done}><DiscrepancyPaper s={s} rows={rows} photo={photo} totals={totals} /></PrintSheet>}
  </Overlay>;
}
