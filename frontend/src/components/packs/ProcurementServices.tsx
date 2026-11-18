"use client";
// Low-priority sections (Stitch 55/62/63: ستاد, logistics, CSR/charity, catalog) collapsed in an accordion.
// None of these has a backend yet, so each shows an honest "not active yet" state — no fake forms or figures.
// The only number shown (food weight) is computed from the selected pack's real item weights.
import Link from "next/link";
import { Landmark, Truck, HeartHandshake, BookOpen, ChevronDown } from "lucide-react";
import type { PackDetail } from "@/lib/storefront";
import { positiveInteger } from "@/lib/pack-input";
import { toPersianNum } from "@/lib/utils";
import { btnSecondary, card } from "./studio-ui";

function kg(g: number) { return `${toPersianNum(+(g / 1000).toFixed(1))} کیلوگرم`; }
const Soon = () => <span className="rounded-md bg-[#F3F4F6] px-2 py-0.5 text-[10px] font-bold text-[#6B7280]">به‌زودی</span>;

function Item({ icon: Icon, title, sub, children, soon = true }: { icon: typeof Landmark; title: string; sub: string; children: React.ReactNode; soon?: boolean }) {
  return (
    <details className="group border-b border-[#F3F4F6] last:border-b-0">
      <summary className="flex min-h-16 cursor-pointer list-none items-center gap-3 px-4 py-3 md:px-5 [&::-webkit-details-marker]:hidden">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#F3F6FA] text-[#034EA2]"><Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /></span>
        <span className="min-w-0 flex-1"><span className="flex items-center gap-2 text-sm font-bold text-[#111827]">{title}{soon && <Soon />}</span><span className="mt-0.5 block line-clamp-1 text-xs text-[#6B7280]">{sub}</span></span>
        <ChevronDown className="h-4 w-4 shrink-0 text-[#9CA3AF] transition group-open:rotate-180" aria-hidden />
      </summary>
      <div className="px-4 pb-4 text-xs leading-6 text-[#4B5563] md:px-5 md:pr-[68px]">{children}</div>
    </details>
  );
}

export function ProcurementServices({ pack, count, onCharity }: { pack: PackDetail | null; count: string; onCharity: () => void }) {
  const n = positiveInteger(count);
  return (
    <section aria-labelledby="proc-services-title">
      <h2 id="proc-services-title" className="text-base font-extrabold text-[#112D46] md:text-lg">خرید دولتی، ارسال و خیریه</h2>
      <p className="mt-1 line-clamp-1 text-xs text-[#6B7280] md:text-sm">امکانات تکمیلی تدارکات سازمانی؛ بخش‌های غیرفعال با برچسب «به‌زودی» مشخص شده‌اند.</p>
      <div className={`${card} mt-4 overflow-hidden`}>
        <Item icon={Landmark} title="سامانه ستاد (خرید دستگاه‌های دولتی)" sub="ثبت شماره نیاز و پیش‌فاکتور مخصوص ستاد">
          <p>ثبت شماره نیاز ستاد، شناسه دستگاه و ارسال پیشنهاد قیمت از داخل شصت‌آنلاین هنوز فعال نشده است. تا آن زمان درخواست خود را از مسیر خرید سازمانی ثبت کنید.</p>
          <Link href="/business" className={`${btnSecondary} mt-3 h-10 min-h-10 text-xs`}>خرید سازمانی</Link>
        </Item>
        <Item icon={Truck} title="ارسال و لجستیک" sub="ارسال یکجا یا چند نقطه‌ای، زمان‌بندی تحویل">
          <p>برآورد خودکار حجم بار، ناوگان و هزینه ارسال هنوز در سامانه محاسبه نمی‌شود؛ زمان و شرایط ارسال در پاسخ استعلام اعلام می‌شود.</p>
          {pack?.food_weight_g && n
            ? <p className="mt-2 rounded-lg bg-[#F9FAFB] p-2.5">وزن مواد غذایی ثبت‌شده برای «{pack.title_fa}»: {kg(pack.food_weight_g)} در هر پک · حدود {kg(pack.food_weight_g * n)} برای {toPersianNum(n)} پک (بدون بسته‌بندی).</p>
            : null}
        </Item>
        <Item icon={HeartHandshake} title="خیریه و مسئولیت اجتماعی" sub="پک خیریه با بودجه مشخص؛ تحویل به نهاد" soon={false}>
          <p>پک خیریه را می‌توانید از کالاهای ماندگار کاتالوگ و بر اساس بودجه بسازید. تحویل مستقیم به نهاد خیریه و گزارش تحویل هنوز فعال نشده است.</p>
          <button type="button" onClick={onCharity} className={`${btnSecondary} mt-3 h-10 min-h-10 text-xs`}>ساخت پک خیریه بر اساس بودجه</button>
        </Item>
        <Item icon={BookOpen} title="کاتالوگ پک‌ها (PDF) و آرشیو" sub="دانلود و ارسال خودکار کاتالوگ فصلی">
          <p>کاتالوگ قابل‌دانلود و آرشیو کاتالوگ‌های فصلی هنوز منتشر نشده است. پک‌های منتشرشده را در همین صفحه ببینید.</p>
        </Item>
      </div>
    </section>
  );
}
