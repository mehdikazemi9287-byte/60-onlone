"use client";
// Recurring supply contract draft — Stitch screens 32 (A4 sheet in an inspection viewer) and 10 (same sheet with
// the buyer's stamp & signature panel). Real data only: the organization (GET /organizations), the recurring list,
// its live quote (GET /me/recurring/{id}/quote) and the organization credit contract (finance roles).
// Stamp / signature images stay in this page's memory as data: URLs — never uploaded or stored.
// Printing uses the shared PrintSheet portal (globals.css prints only .print-doc, on white paper).
import { useCallback, useEffect, useRef, useState } from "react";
import { PrintSheet } from "@/components/print/PrintSheet";
import { FREQ_FA, RECUR_FA, type CreditContract, type DraftQuote, type RecurringList } from "@/lib/commerce";
import { cn, faDate, toPersianNum } from "@/lib/utils";
import { Icon, fa, tomanDigits } from "./OrgDashboard";

export type DraftOrg = { display_name: string; legal_name?: string | null; national_id?: string | null };
type Props = { org: DraftOrg; contract: CreditContract | null; list: RecurringList; quote: DraftQuote | null; onClose: () => void };

const todayIso = () => new Date().toISOString().slice(0, 10);

/** The A4 sheet itself (screen 32 layout). Used on screen and inside the print portal. */
export function ContractSheet({ org, contract, list, quote, stamp, sign, print }: Omit<Props, "onClose"> & { stamp: string | null; sign: string | null; print?: boolean }) {
  const line = (pid: number) => quote?.lines.find((x) => x.product_id === pid);
  const number = `RC-${toPersianNum(list.id)}`;
  return (
    <article dir="rtl" className={cn("mx-auto w-full max-w-[820px] bg-white text-[#0f172a]", print ? "" : "min-h-[1160px] rounded-sm border border-slate-200 p-12 shadow-xl")}>
      <header className="flex items-start justify-between gap-6 border-b border-slate-200 pb-6">
        <div className="flex flex-col gap-1">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/60online-mark.png" alt="۶۰ آنلاین" className="h-12 w-auto object-contain" />
          <span className="text-[13px] text-slate-500">سامانه تأمین هوشمند ۶۰ آنلاین (شصت‌آنلاین)</span>
        </div>
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="rounded-full bg-[#c9e6ff] px-3 py-0.5 text-[12px] font-semibold text-[#001e2f]">امور حقوقی و بازرگانی B2B</span>
          <h1 className="text-[22px] font-extrabold leading-9">پیش‌نویس قرارداد تأمین و شارژ دوره‌ای اقلام سازمانی</h1>
        </div>
        <dl className="grid shrink-0 grid-cols-[auto_auto] gap-x-2 gap-y-1 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[12px]">
          <dt className="text-slate-500">شماره پیش‌نویس:</dt><dd className="font-bold" dir="ltr" style={{ textAlign: "right" }}>{number}</dd>
          <dt className="text-slate-500">تاریخ صدور:</dt><dd className="font-bold">{faDate(todayIso())}</dd>
          <dt className="text-slate-500">پیوست:</dt><dd className="font-bold">جدول مشخصات اقلام</dd>
        </dl>
      </header>

      <div className="mt-6 flex items-start gap-3 rounded-lg border border-[#ffdad6] bg-[#fff8f6] p-4">
        <span aria-hidden className="material-symbols-outlined text-[24px] text-[#ba1a1a]">warning</span>
        <div><p className="text-[13px] font-bold text-[#ba1a1a]">اخطار رسمی و ضوابط حقوقی سند</p>
          <p className="text-[14px] leading-7">توجه: این سند صرفاً پیش‌نویس اداری بوده و تا پیش از امضای رسمی نمایندگان مجاز طرفین و مبادله نسخه چاپی یا دیجیتال معتبر، فاقد هرگونه تعهد حقوقی و وجاهت قراردادی است. قیمت‌ها پیش‌برآورد با قیمت روز تهیه‌اند و در هر نوبت دوباره محاسبه می‌شوند.</p></div>
      </div>

      <h2 className="mt-8 flex items-center gap-2 text-[16px] font-bold"><span aria-hidden className="material-symbols-outlined text-[20px] text-[#266489]">apartment</span>مشخصات طرفین و شرایط بنیادین پیمان</h2>
      <div className="mt-3 grid grid-cols-2 overflow-hidden rounded-lg border border-slate-200 text-[14px]">
        {([
          ["طرف خریدار (کارفرما)", org.legal_name || org.display_name, org.national_id ? `شناسه ملی: ${toPersianNum(org.national_id)}` : "شناسه ملی ثبت نشده"],
          ["عنوان فهرست تأمین", list.title, `${fa(list.items.length)} قلم کالا`],
          ["دوره و تناوب تحویل", FREQ_FA[list.frequency], "طبق تقویم نوبت‌های سامانه"],
          ["تاریخ نخستین موعد تحویل", list.status === "active" ? faDate(list.next_run_on) : "—", list.status === "active" ? "نوبت بعدی برنامه‌ریزی‌شده" : `وضعیت فهرست: ${RECUR_FA[list.status]}`],
          ["شرایط پرداخت و تسویه", contract ? `اعتبار سازمانی · مهلت ${fa(contract.due_days)} روزه` : "پرداخت هر نوبت پس از تأیید پیش‌فاکتور", contract ? `قرارداد ${contract.contract_number || contract.reference}` : "قرارداد اعتباری فعال ثبت نشده"],
          ["وضعیت قرارداد", "پیش‌نویس (در انتظار امضا)", "تا امضای طرفین فاقد اعتبار قراردادی"],
        ] as [string, string, string][]).map(([k, v, sub], i) => (
          <div key={k} className={cn("p-4", i % 2 === 0 ? "bg-slate-50" : "bg-white", i < 4 && "border-b border-slate-200", i % 2 === 0 && "border-l border-slate-200")}>
            <p className="text-[12px] text-slate-500">{k}:</p><p className="font-bold">{v}</p><p className="text-[12px] text-slate-500">{sub}</p>
          </div>))}
      </div>

      <div className="mt-8 flex items-end justify-between"><h2 className="flex items-center gap-2 text-[16px] font-bold"><span aria-hidden className="material-symbols-outlined text-[20px] text-[#266489]">receipt_long</span>جدول اقلام مصرفی هر محموله دوره‌ای</h2>
        <span className="text-[12px] text-slate-500">ارقام به تومان (پیش‌برآورد با قیمت روز)</span></div>
      <table className="mt-3 w-full border-collapse overflow-hidden rounded-lg text-[14px]">
        <thead><tr className="bg-slate-100 text-[13px] text-slate-600">{["ردیف", "شرح و شناسه کالا", "تعداد در هر تحویل", "بهای واحد پایه (تومان)", "تخفیف دوره‌ای", "مبلغ نهایی (تومان)"].map((h) => <th key={h} className="p-3 text-right font-semibold">{h}</th>)}</tr></thead>
        <tbody>{list.items.map((it, i) => { const ln = line(it.product_id); const base = ln ? ln.unit_price_minor * ln.quantity : 0;
          const pct = ln && base ? Math.round((1 - ln.line_after_discounts_minor / base) * 100) : 0; return (
          <tr key={it.product_id} className={i % 2 ? "bg-slate-50" : "bg-white"}>
            <td className="p-3 text-slate-500">{fa(i + 1)}</td>
            <td className="p-3"><p className="font-bold">{it.title_fa}</p><p className="text-[12px] text-slate-500" dir="ltr" style={{ textAlign: "right" }}>{it.slug}</p></td>
            <td className="p-3">{fa(it.quantity)}</td>
            <td className="p-3">{ln ? tomanDigits(ln.unit_price_minor) : "—"}</td>
            <td className="p-3">{pct > 0 ? <span className="rounded-full bg-[#ffdbd1] px-2 py-0.5 text-[12px] font-bold text-[#4a0f00]">٪{fa(pct)}</span> : "—"}</td>
            <td className="p-3 text-[16px] font-extrabold">{ln ? tomanDigits(ln.line_after_discounts_minor) : "قابل فروش نیست"}</td>
          </tr>); })}</tbody>
      </table>
      {quote && <div className="mt-4 w-full max-w-[320px] rounded-lg bg-slate-50 p-4 text-[14px]">
        <div className="flex justify-between gap-3"><span>جمع ناخالص اقلام:</span><span>{tomanDigits(quote.totals.base_line_minor)} تومان</span></div>
        {quote.totals.discount_total_minor > 0 && <div className="flex justify-between gap-3 text-[#eb5f34]"><span>تخفیف دوره‌ای:</span><span>- {tomanDigits(quote.totals.discount_total_minor)} تومان</span></div>}
        <div className="mt-2 flex justify-between gap-3 border-t border-slate-200 pt-2 font-extrabold"><span>خالص هر نوبت تحویل:</span><span className="text-[#266489]">{tomanDigits(quote.totals.payable_minor)} تومان</span></div>
        <p className="mt-1 text-[12px] text-slate-500">مالیات و هزینه ارسال در پیش‌فاکتور هر نوبت محاسبه می‌شود.</p>
      </div>}

      <div className="mt-14 grid grid-cols-2 gap-6">
        {[{ t: "نماینده مجاز سازمان خریدار (طرف اول)", s: org.display_name, imgs: true }, { t: "سامانه تجارت دیجیتال ۶۰ آنلاین (تأمین‌کننده)", s: "واحد قراردادهای سازمانی", imgs: false }].map((b) => (
          <div key={b.t} className="relative min-h-[170px] rounded-lg border border-dashed border-slate-300 p-5">
            <p className="text-[15px] font-bold">{b.t}</p><p className="text-[12px] text-slate-500">{b.s}</p>
            <p className="mt-4 text-[13px] text-slate-600">نام و سمت نماینده: ................................</p>
            <p className="text-[13px] text-slate-600">تاریخ تأیید و امضا: ................................</p>
            {b.imgs && (stamp || sign) && <div className="pointer-events-none absolute bottom-3 left-4 flex items-end gap-2">
              {/* eslint-disable @next/next/no-img-element */}
              {stamp && <img src={stamp} alt="مهر سازمان" className="h-20 w-20 object-contain opacity-90" />}
              {sign && <img src={sign} alt="امضای نماینده" className="h-16 w-28 object-contain" />}
              {/* eslint-enable @next/next/no-img-element */}
            </div>}
            <div className="absolute bottom-3 right-5 flex gap-6 text-[11px] text-slate-400"><span>محل مهر رسمی</span><span>محل امضای مجاز</span></div>
          </div>))}
      </div>
      <p className="mt-6 text-center text-[11px] text-slate-400">برگه ۱ از ۱ — سند از طریق درگاه قراردادهای ۶۰ آنلاین ایجاد شده و منوط به امضای رسمی و بارگذاری نسخه تأییدشده است.</p>
    </article>
  );
}

/** Full-screen inspection viewer: toolbar + (screen 10) stamp & signature panel + A4 sheet. */
export default function ContractDraftViewer({ org, contract, list, quote, onClose }: Props) {
  const [stamp, setStamp] = useState<string | null>(null), [sign, setSign] = useState<string | null>(null);
  const [imgErr, setImgErr] = useState<string | null>(null), [printing, setPrinting] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const done = useCallback(() => setPrinting(false), []);
  useEffect(() => {
    box.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc); const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", esc); document.body.style.overflow = prev; };
  }, [onClose]);
  const pick = (set: (u: string | null) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = ""; setImgErr(null);
    if (!f) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) { setImgErr("فقط تصویر PNG، JPG یا WebP"); return; }
    if (f.size > 2 * 1024 * 1024) { setImgErr("حجم تصویر باید کمتر از ۲ مگابایت باشد"); return; }
    const r = new FileReader(); r.onload = () => set(typeof r.result === "string" ? r.result : null); r.onerror = () => setImgErr("خواندن تصویر ناموفق بود"); r.readAsDataURL(f);
  };
  const slot = (label: string, sub: string, url: string | null, set: (u: string | null) => void, icon: string) => (
    <div className="flex flex-col gap-st-space-sm">
      <div className="flex items-center justify-between"><span className="flex items-center gap-1 font-bold text-st-primary"><Icon name={icon} className="text-[18px] text-st-secondary" />{label}</span>
        <span className={cn("rounded px-2 py-0.5 text-[12px]", url ? "bg-st-secondary-fixed text-st-on-secondary-fixed" : "bg-st-surface-container text-st-on-surface-variant")}>{url ? "آماده درج" : "بارگذاری نشده"}</span></div>
      <div className="flex items-center gap-st-space-md rounded-xl border border-st-surface-container bg-st-surface p-st-space-sm">
        <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-st-surface-container bg-white">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {url ? <img src={url} alt={label} className="max-h-full max-w-full object-contain" /> : <Icon name={icon} className="text-[28px] text-st-outline" />}
        </div>
        <div className="flex min-w-0 flex-col gap-1"><span className="text-[13px] text-st-on-surface-variant">{sub}</span>
          <div className="flex flex-wrap gap-st-space-xs">
            <label className="cursor-pointer rounded-lg bg-st-surface-container px-st-space-sm py-1 text-[13px] font-semibold text-st-primary hover:bg-st-surface-container-high">{url ? "تغییر فایل" : "انتخاب تصویر"}
              <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={pick(set)} /></label>
            {url && <button type="button" onClick={() => set(null)} className="rounded-lg px-st-space-sm py-1 text-[13px] text-st-outline hover:bg-st-error-container hover:text-st-error">حذف</button>}
          </div></div>
      </div>
    </div>);

  return (
    <div className="fixed inset-0 z-[80] flex flex-col bg-st-background" role="dialog" aria-modal="true" aria-label="پیش‌نویس قرارداد تأمین دوره‌ای" ref={box} tabIndex={-1}>
      <div className="flex flex-wrap items-center justify-between gap-st-space-sm border-b border-st-surface-container bg-st-surface-container-lowest px-st-space-lg py-st-space-sm shadow-sm">
        <nav aria-label="مسیر" className="flex items-center gap-st-space-xs text-[14px] text-st-on-surface-variant">
          <span>سامانه قراردادها</span><Icon name="chevron_left" className="text-[16px]" /><span>تأمین دوره‌ای</span><Icon name="chevron_left" className="text-[16px]" />
          <span className="font-bold text-st-primary">پیش‌نویس نهایی و بارگذاری امضا</span>
          <span className="mr-st-space-sm rounded-full bg-st-secondary-fixed px-2 py-0.5 text-[12px] text-st-on-secondary-fixed">اندازه استاندارد چاپی A4</span>
        </nav>
        <div className="flex items-center gap-st-space-xs">
          <button type="button" onClick={() => setPrinting(true)} className="inline-flex items-center gap-1 rounded-lg bg-st-primary-container px-st-space-md py-st-space-xs font-semibold text-st-on-primary hover:bg-st-secondary"><Icon name="print" className="text-[18px]" />چاپ سند رسمی (A4)</button>
          <button type="button" onClick={() => setPrinting(true)} className="inline-flex items-center gap-1 rounded-lg bg-st-surface-container px-st-space-md py-st-space-xs font-semibold text-st-primary hover:bg-st-surface-container-high" title="در پنجره چاپ «ذخیره به PDF» را انتخاب کنید"><Icon name="download" className="text-[18px]" />خروجی PDF</button>
          <button type="button" onClick={onClose} className="inline-flex items-center gap-1 rounded-lg px-st-space-sm py-st-space-xs text-st-on-surface-variant hover:bg-st-surface-container"><Icon name="close" className="text-[18px]" />بستن پیش‌نمایش</button>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-st-space-lg overflow-y-auto p-st-space-lg lg:flex-row">
        <aside className="flex w-full shrink-0 flex-col gap-st-space-md self-start rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:sticky lg:top-0 lg:w-[360px]">
          <div className="flex items-center gap-st-space-sm border-b border-st-surface-container pb-st-space-sm">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-st-secondary-fixed text-st-on-secondary-fixed"><Icon name="verified_user" className="text-[22px]" /></div>
            <div><p className="font-bold text-st-primary">پنل مهر و امضای سازمان خریدار</p><p className="text-[13px] text-st-on-surface-variant">افزودن مهر و امضا جهت درج در برگه چاپی</p></div>
          </div>
          {slot("مهر رسمی سازمان", "PNG شفاف بهترین نتیجه را می‌دهد", stamp, setStamp, "approval")}
          {slot("امضای نماینده مجاز", "تصویر امضا با زمینه سفید یا شفاف", sign, setSign, "draw")}
          {imgErr && <p role="alert" className="text-[13px] text-st-error">{imgErr}</p>}
          <div className="flex gap-st-space-sm rounded-xl bg-st-surface-container-low p-st-space-md text-[13px] leading-6 text-st-on-surface-variant">
            <Icon name="lock" className="text-[20px] text-st-secondary" />
            <p><b className="text-st-primary">حریم خصوصی و پردازش محلی:</b> تصاویر مهر و امضا فقط در حافظه همین صفحه نگه داشته می‌شوند و به هیچ عنوان به سرور ارسال یا ذخیره نمی‌شوند. این امضای تصویری جایگزین امضای الکترونیکی معتبر قانونی نیست.</p>
          </div>
          <dl className="grid grid-cols-2 gap-y-1 text-[13px]"><dt className="text-st-outline">استاندارد خروجی:</dt><dd className="font-semibold text-st-primary">کاغذ A4 (۲۱۰×۲۹۷ میلی‌متر)</dd>
            <dt className="text-st-outline">دوره تحویل:</dt><dd className="font-semibold text-st-primary">{FREQ_FA[list.frequency]}</dd>
            <dt className="text-st-outline">قیمت‌گذاری:</dt><dd className="font-semibold text-st-primary">{quote ? "پیش‌برآورد قیمت روز" : "قیمت در دسترس نیست"}</dd></dl>
        </aside>
        <div className="min-w-0 flex-1 overflow-x-auto"><ContractSheet org={org} contract={contract} list={list} quote={quote} stamp={stamp} sign={sign} /></div>
      </div>
      {printing && <PrintSheet onDone={done}><ContractSheet org={org} contract={contract} list={list} quote={quote} stamp={stamp} sign={sign} print /></PrintSheet>}
    </div>
  );
}
