"use client";
// Official proforma A4 sheet — layout of Stitch screen 53 (برگه رسمی استعلام بها و پیش‌فاکتور A4), bound to the real
// proforma snapshot (GET /me/proformas/{number}). Setad (ستاد) fields, QR verification, the seller's legal ids and
// digital stamps in the Stitch sample have no backend here: they are NOT printed. A Code128 barcode of the real
// proforma number is printed instead.
import { Code128 } from "@/components/print/PrintSheet";
import { cn, faDate, toPersianNum } from "@/lib/utils";

export type ProformaDoc = { number: string; organization: string | null; created_at: string; valid_until: string; expired: boolean; used: boolean;
  items: { product_id: number; title_fa: string; sku: string; quantity: number; unit_price_minor: number; line_total_minor: number }[];
  subtotal_minor: number; shipping_fee_minor: number; tax_minor: number; total_minor: number };

const fa = (v: number) => v.toLocaleString("fa-IR");
const t = (minor: number) => fa(Math.round(minor / 10));
export const proformaState = (p: { used: boolean; expired: boolean }) => (p.used ? "استفاده‌شده" : p.expired ? "منقضی‌شده" : "معتبر");

const ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"];
const TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"];
const TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"];
const HUNDREDS = ["", "یکصد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"];
function three(n: number): string {
  const h = Math.floor(n / 100), r = n % 100, out: string[] = [];
  if (h) out.push(HUNDREDS[h]);
  if (r >= 10 && r < 20) out.push(TEENS[r - 10]);
  else { if (Math.floor(r / 10)) out.push(TENS[Math.floor(r / 10)]); if (r % 10) out.push(ONES[r % 10]); }
  return out.join(" و ");
}
/** Persian words for a non-negative integer (up to trillions). */
export function faWords(n: number): string {
  n = Math.floor(Math.abs(n));
  if (!n) return "صفر";
  const units = ["", "هزار", "میلیون", "میلیارد", "هزار میلیارد"], parts: string[] = [];
  for (let i = 0; n > 0 && i < units.length; i++, n = Math.floor(n / 1000)) {
    const g = n % 1000; if (g) parts.unshift(three(g) + (units[i] ? " " + units[i] : ""));
  }
  return parts.join(" و ");
}

export default function ProformaSheet({ p, buyer, className }: { p: ProformaDoc; buyer?: string | null; className?: string }) {
  const tot = Math.round(p.total_minor / 10);
  return (
    <article dir="rtl" className={cn("mx-auto w-full max-w-[840px] bg-white text-[#0f172a]", className)} style={{ breakAfter: "page" }}>
      <header className="flex items-start justify-between gap-6">
        <div className="flex items-center gap-3">
          <div className="flex h-14 w-14 flex-col items-center justify-center rounded-xl bg-[#0a2735] text-white"><b className="text-[20px] leading-none">۶۰</b><span className="text-[8px]">B2B CORE</span></div>
          <div><p className="text-[12px] text-slate-500">شصت‌آنلاین · سامانه تدارکات سازمانی</p><h1 className="text-[20px] font-extrabold">پیش‌فاکتور رسمی</h1>
            <p className="text-[12px] font-semibold text-[#266489]">برگه رسمی پیش‌فاکتور معتبر (نسخه قابل چاپ A4)</p></div>
        </div>
        <div className="flex flex-col items-center gap-1"><Code128 data={p.number} height={40} /><span className="font-mono text-[10px] tracking-widest text-slate-500" dir="ltr">{p.number}</span></div>
      </header>
      <dl className="mt-5 grid grid-cols-4 gap-3 rounded-lg bg-slate-50 p-3 text-[12px]">
        <div><dt className="text-slate-500">شماره پیش‌فاکتور:</dt><dd className="font-bold" dir="ltr" style={{ textAlign: "right" }}>{p.number}</dd></div>
        <div><dt className="text-slate-500">تاریخ صدور:</dt><dd className="font-bold">{faDate(p.created_at)}</dd></div>
        <div><dt className="text-slate-500">وضعیت:</dt><dd className="font-bold">{proformaState(p)}</dd></div>
        <div><dt className="text-slate-500">مهلت اعتبار نرخ‌ها:</dt><dd className="font-bold text-[#ba1a1a]">{faDate(p.valid_until)}</dd></div>
      </dl>
      <div className="mt-5 grid grid-cols-2 gap-4 text-[13px]">
        <section className="rounded-lg border border-slate-200 p-4">
          <h2 className="mb-2 flex items-center gap-2 font-bold"><span className="h-2 w-2 rounded-full bg-[#266489]" />مشخصات فروشنده / تأمین‌کننده</h2>
          <p><span className="text-slate-500">نام: </span><b>شصت‌آنلاین</b></p>
          <p className="text-[12px] text-slate-500">مشخصات حقوقی کامل فروشنده (شناسه ملی، کد اقتصادی) در فاکتور نهایی پس از پرداخت درج می‌شود.</p>
        </section>
        <section className="rounded-lg border border-slate-200 p-4">
          <h2 className="mb-2 flex items-center gap-2 font-bold"><span className="h-2 w-2 rounded-full bg-[#0a2735]" />مشخصات خریدار</h2>
          <p><span className="text-slate-500">خریدار: </span><b>{p.organization ?? buyer ?? "خرید شخصی"}</b></p>
          <p className="text-[12px] text-slate-500">{p.organization ? "خرید سازمانی (طرف قرارداد حقوقی)" : "خرید شخصی"}</p>
        </section>
      </div>
      <div className="mt-6 flex items-end justify-between"><h2 className="text-[15px] font-bold">فهرست اقلام و بهای پیشنهادی رسمی</h2><span className="text-[11px] text-slate-500">(کلیه مبالغ به تومان)</span></div>
      <table className="mt-2 w-full border-collapse text-[12px]">
        <thead><tr className="bg-slate-100 text-slate-600">{["ردیف", "کد کالا", "شرح کامل کالا", "تعداد", "بهای واحد", "مبلغ کل"].map((h) => <th key={h} className="p-2 text-right font-semibold">{h}</th>)}</tr></thead>
        <tbody>{p.items.map((i, k) => <tr key={i.product_id} className={k % 2 ? "bg-slate-50" : ""}>
          <td className="p-2">{fa(k + 1)}</td><td className="p-2 font-mono text-[11px] text-[#266489]" dir="ltr" style={{ textAlign: "right" }}>{i.sku}</td>
          <td className="p-2 font-bold">{i.title_fa}</td><td className="p-2 text-[14px] font-bold">{fa(i.quantity)}</td>
          <td className="p-2">{t(i.unit_price_minor)}</td><td className="p-2 font-bold">{t(i.line_total_minor)}</td></tr>)}</tbody>
      </table>
      <div className="mt-5 grid grid-cols-2 gap-4 text-[13px]">
        <section className="rounded-lg border border-slate-200 p-4">
          <p className="text-slate-500">مبلغ به حروف:</p><p className="text-[15px] font-bold text-[#266489]">{faWords(tot)} تومان</p>
          <p className="mt-1 text-[11px] text-slate-500">معادل {fa(p.total_minor)} ریال</p>
        </section>
        <section className="rounded-lg bg-slate-50 p-4">
          {([["جمع کل بهای اقلام", p.subtotal_minor], ["هزینه ارسال", p.shipping_fee_minor], ["مالیات بر ارزش افزوده", p.tax_minor]] as [string, number][]).map(([k, v]) =>
            <div key={k} className="flex justify-between gap-3 py-0.5"><span>{k}:</span><b>{t(v)} تومان</b></div>)}
          <div className="mt-2 flex items-center justify-between gap-3 rounded-lg bg-[#0a2735] p-3 text-white"><span className="font-bold">مبلغ نهایی قابل پرداخت:</span><b className="text-[18px]">{t(p.total_minor)} تومان</b></div>
        </section>
      </div>
      <section className="mt-5 rounded-lg border border-slate-200 p-4 text-[12px] leading-6">
        <h2 className="mb-1 text-[13px] font-bold">شرایط اعتبار پیش‌فاکتور</h2>
        <p>• اعتبار نرخ‌ها و موجودی این پیش‌فاکتور تا {faDate(p.valid_until)} است.</p>
        <p>• اگر هنگام پرداخت، مبلغ سبد از این پیش‌فاکتور بیشتر شده باشد، پرداخت انجام نمی‌شود.</p>
        <p>• صورتحساب رسمی پس از پرداخت و نهایی شدن سفارش صادر می‌شود.</p>
      </section>
      <div className="mt-8 grid grid-cols-2 gap-6 text-[12px]">
        {["مهر و امضای فروشنده", "تأیید ذی‌حساب / کارپرداز خریدار"].map((l) => <div key={l} className="min-h-[110px] rounded-lg border border-dashed border-slate-300 p-4"><b>{l}</b><p className="mt-8 text-slate-400">نام، امضا و تاریخ: ......................</p></div>)}
      </div>
      <p className="mt-4 flex justify-between text-[10px] text-slate-400"><span>صفحه ۱ از ۱ · استاندارد چاپ A4</span><span dir="ltr">{toPersianNum(p.number)}</span></p>
    </article>
  );
}
