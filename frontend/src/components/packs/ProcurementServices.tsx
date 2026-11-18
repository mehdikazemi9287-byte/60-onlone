"use client";
// Secondary modules — Stitch 62 (desktop card with segmented tabs: ستاد / لجستیک / CSR) and Stitch 63
// (mobile accordions «فرآیندهای حقوقی و زنجیره تأمین»). None of Setad, logistics estimation or charity
// delivery has a backend yet: inputs are disabled and marked «به‌زودی». The only figures shown are computed
// from the selected pack's real data (item weights, item count, min order).
import { useState } from "react";
import Link from "next/link";
import type { PackDetail } from "@/lib/storefront";
import { positiveInteger } from "@/lib/pack-input";
import { toPersianNum } from "@/lib/utils";
import { Icon, Soon } from "./studio-ui";

const kg = (g: number) => `${toPersianNum(+(g / 1000).toFixed(1))} کیلوگرم`;
type Tab = "setad" | "logistics" | "csr";
const TABS: [Tab, string][] = [["setad", "سامانه ستاد ایران"], ["logistics", "تخمین لجستیک"], ["csr", "مسئولیت اجتماعی (CSR)"]];

function SetadBody({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
        <Icon name="account_balance" className="!text-[20px] text-[#034EA2]" />
        <span className="flex-1">ثبت شماره نیاز ستاد، شناسه دستگاه و ارسال پیشنهاد قیمت از داخل شصت‌آنلاین هنوز فعال نشده است؛ تا آن زمان از مسیر <Link href="/business" className="font-bold text-[#034EA2] hover:underline">خرید سازمانی</Link> اقدام کنید.</span>
        <Soon />
      </div>
      {!compact && (
        <fieldset disabled className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-gray-700">شماره نیاز در سامانه ستاد:</span>
            <input className="h-10 rounded-lg border border-gray-200 bg-gray-50 px-3 text-xs" placeholder="کد ۱۹ رقمی استعلام" /></label>
          <label className="flex flex-col gap-1.5"><span className="text-xs font-medium text-gray-700">شناسه ملی دستگاه اجرایی:</span>
            <input className="h-10 rounded-lg border border-gray-200 bg-gray-50 px-3 text-xs" placeholder="شناسه ۱۱ رقمی ارگان" /></label>
          <div className="flex flex-col justify-end">
            <button type="button" className="flex h-10 cursor-not-allowed items-center justify-center gap-2 rounded-lg bg-[#034EA2]/40 px-4 text-xs font-bold text-white">
              <Icon name="sync" className="!text-[16px]" /><span>ثبت و تطبیق پیشنهاد قیمت در ستاد</span>
            </button>
          </div>
        </fieldset>
      )}
    </div>
  );
}

function LogisticsBody({ pack, n, cols }: { pack: PackDetail | null; n: number | null; cols: string }) {
  const tiles: [string, string][] = [
    ["وزن ثبت‌شده هر پک:", pack?.food_weight_g ? kg(pack.food_weight_g) : pack ? "ثبت نشده" : "—"],
    ["وزن کل اقلام (بدون بسته‌بندی):", pack?.food_weight_g && n ? kg(pack.food_weight_g * n) : "—"],
    ["تعداد اقلام هر پک:", pack ? `${toPersianNum(pack.unit_count)} واحد` : "—"],
    ["ناوگان و هزینه ارسال:", "در پاسخ استعلام"],
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className={`grid gap-4 ${cols}`}>
        {tiles.map(([k, v]) => <div key={k} className="flex flex-col rounded-lg border border-gray-200 bg-gray-50 p-3"><span className="text-[11px] text-gray-500">{k}</span><span className="mt-1 text-base font-bold text-gray-900">{v}</span></div>)}
      </div>
      <p className="flex items-center gap-2 text-[11px] text-gray-500"><Soon />برآورد خودکار حجم بار (CBM)، ناوگان و پالت‌بندی هنوز در سامانه محاسبه نمی‌شود.{!pack && " برای محاسبه وزن، یک پک را انتخاب کنید."}</p>
    </div>
  );
}

function CsrBody({ onCharity }: { onCharity: () => void }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-gray-200 bg-gray-50 p-4">
      <h4 className="flex items-center gap-2 text-xs font-bold text-gray-900">پک خیریه و مسئولیت اجتماعی شرکتی (CSR)</h4>
      <p className="text-xs leading-relaxed text-gray-600">پک خیریه را می‌توانید از کالاهای واقعی کاتالوگ و بر اساس بودجه بسازید. تحویل مستقیم به نهادهای خیریه و گزارش تحویل هنوز فعال نشده است.</p>
      <button type="button" onClick={onCharity} className="mt-1 flex h-9 w-fit items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 text-xs font-bold text-[#112D46] hover:border-[#034EA2] hover:text-[#034EA2]">
        <Icon name="volunteer_activism" className="!text-[16px] text-[#FF7A00]" /> ساخت پک خیریه بر اساس بودجه
      </button>
    </div>
  );
}

export function ProcurementServices({ pack, count, onCharity }: { pack: PackDetail | null; count: string; onCharity: () => void }) {
  const [tab, setTab] = useState<Tab>("setad");
  const n = positiveInteger(count);
  return (
    <>
      {/* Desktop — Stitch 62 */}
      <section aria-labelledby="proc-services-title" className="mt-4 hidden flex-col gap-6 rounded-xl border border-gray-200 bg-white p-6 shadow-sm md:flex">
        <div className="flex items-center justify-between gap-4 border-b border-gray-100 pb-4">
          <div>
            <h3 id="proc-services-title" className="text-sm font-bold text-gray-900">سرویس‌های تخصصی تدارکات و لجستیک</h3>
            <p className="mt-1 text-xs text-gray-500">تدارکات دولتی، برآورد بار و پروژه‌های مسئولیت اجتماعی</p>
          </div>
          <div role="tablist" aria-label="سرویس‌های تدارکات" className="flex shrink-0 items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1">
            {TABS.map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`rounded-md px-3 py-1.5 text-xs transition ${tab === k ? "bg-[#034EA2] font-bold text-white" : "font-semibold text-gray-600 hover:text-gray-900"}`}>{l}</button>
            ))}
          </div>
        </div>
        <div role="tabpanel">
          {tab === "setad" && <SetadBody />}
          {tab === "logistics" && <LogisticsBody pack={pack} n={n} cols="grid-cols-2 lg:grid-cols-4" />}
          {tab === "csr" && <CsrBody onCharity={onCharity} />}
        </div>
      </section>

      {/* Mobile — Stitch 63 */}
      <section aria-labelledby="proc-services-title-m" className="flex flex-col gap-2 pt-1 md:hidden">
        <h2 id="proc-services-title-m" className="px-1 text-[13px] font-bold text-[#112D46]">فرآیندهای حقوقی و زنجیره تأمین</h2>
        {([
          ["account_balance", "bg-blue-50 text-[#034EA2]", "خرید دولتی و سامانه ستاد ایران", "پیش‌فاکتور رسمی، شناسه ملی و ضمانت‌نامه", <SetadBody key="s" compact />],
          ["local_shipping", "bg-blue-50 text-[#034EA2]", "برآورد ناوگان و لجستیک", "تخمین وزن بار و شرایط ارسال", <LogisticsBody key="l" pack={pack} n={n} cols="grid-cols-2" />],
          ["volunteer_activism", "bg-orange-50 text-[#FF7A00]", "پویش مسئولیت اجتماعی و خیریه", "پک خیریه با بودجه مشخص", <CsrBody key="c" onCharity={onCharity} />],
        ] as const).map(([icon, tone, title, sub, body]) => (
          <details key={title} className="group overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <summary className="flex w-full cursor-pointer list-none items-center justify-between p-3.5 text-right [&::-webkit-details-marker]:hidden">
              <span className="flex items-center gap-2.5">
                <span className={`flex h-7 w-7 items-center justify-center rounded-lg ${tone}`}><Icon name={icon} className="!text-[18px]" /></span>
                <span><span className="block text-[13px] font-bold text-[#112D46]">{title}</span><span className="block text-[10px] text-gray-500">{sub}</span></span>
              </span>
              <Icon name="expand_more" className="!text-[20px] text-gray-400 transition-transform group-open:rotate-180" />
            </summary>
            <div className="border-t border-gray-100 px-3.5 pb-3.5 pt-3 text-[12px] text-gray-600">{body}</div>
          </details>
        ))}
      </section>
    </>
  );
}
