"use client";
// Sticky summary — Stitch 62 sidebar «پیش‌نمایش سبد پک سازمانی» (desktop) and Stitch 63 sticky bottom
// inquiry bar (mobile). Real data only: the selected published pack, its real items, real min order,
// and a total only when the backend priced every required item. No invented discounts or perks.
import Link from "next/link";
import type { PackDetail } from "@/lib/storefront";
import { positiveInteger } from "@/lib/pack-input";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { Icon, Soon } from "./studio-ui";

type Props = {
  pack: PackDetail | null; count: string; setCount: (v: string) => void; onContinue: () => void; onClear: () => void;
  savedItems: number | null; onResumeSaved: () => void; onCatalog: () => void;
};

export function useSummaryTotals(pack: PackDetail | null, count: string) {
  const n = positiveInteger(count);
  const min = pack ? Math.max(1, pack.min_order_qty) : 1;
  const valid = !!pack && !!n && n >= min && n <= 100000;
  const total = valid && pack!.price_minor != null && Number.isSafeInteger(pack!.price_minor * n!) ? pack!.price_minor * n! : null;
  return { n, min, valid, total };
}

export function PackSummaryPanel({ pack, count, setCount, onContinue, onClear, savedItems, onResumeSaved }: Props) {
  const { n, min, valid, total } = useSummaryTotals(pack, count);
  const stepBy = pack && min >= 50 ? 50 : 10;
  const step = (d: number) => setCount(toPersianNum(Math.min(100000, Math.max(min, (n ?? min) + d))));
  return (
    <div className="hidden flex-col gap-5 lg:sticky lg:top-28 lg:flex">
      <aside aria-label="پیش‌نمایش سبد پک سازمانی" className="flex flex-col gap-5 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-100 pb-3">
          <div className="flex items-center gap-2">
            <Icon name="receipt_long" className="!text-[20px] text-[#034EA2]" />
            <h3 className="text-sm font-bold text-gray-900">پیش‌نمایش سبد پک سازمانی</h3>
          </div>
          {pack ? <button type="button" onClick={onClear} aria-label="حذف انتخاب" className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-700"><Icon name="close" className="!text-[18px]" /></button>
            : <span className="rounded bg-[#034EA2]/10 px-2 py-0.5 text-[11px] font-bold text-[#034EA2]">پیش‌فاکتور رسمی</span>}
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label htmlFor="summary-count" className="text-xs font-semibold text-gray-700">تیراژ سفارش (تعداد پک):</label>
            <span className="text-[11px] text-gray-400">حداقل تیراژ: {toPersianNum(min)} بسته</span>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-gray-50 p-1.5">
            <button type="button" aria-label="افزایش تیراژ" disabled={!pack} onClick={() => step(stepBy)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white font-bold text-gray-700 transition hover:bg-gray-100 disabled:opacity-40">+</button>
            <div className="flex items-center gap-1.5">
              <input id="summary-count" inputMode="numeric" disabled={!pack} value={pack ? count : ""} placeholder="—" onChange={(e) => setCount(e.target.value)} className="w-20 bg-transparent text-center text-base font-extrabold text-gray-900 focus:outline-none" />
              <span className="text-xs font-medium text-gray-500">بسته</span>
            </div>
            <button type="button" aria-label="کاهش تیراژ" disabled={!pack} onClick={() => step(-stepBy)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white font-bold text-gray-700 transition hover:bg-gray-100 disabled:opacity-40">-</button>
          </div>
          {pack && n != null && n < min && <p role="alert" className="text-[11px] text-[#B45309]">تیراژ کمتر از حداقل سفارش این پک است.</p>}
        </div>

        <div className="flex flex-col gap-1.5 rounded-xl border border-[#D5E4D8] bg-[#EDF3EE] p-3">
          <div className="flex items-center justify-between text-xs font-bold text-[#112D46]">
            <span>تخفیف پلکانی سازمانی:</span>
            <span className="text-[#FF7A00]">بر اساس تیراژ در پاسخ استعلام</span>
          </div>
          <p className="text-[11px] leading-normal text-gray-600">قیمت پلکانی و شرایط ارسال پس از ثبت استعلام از فروشندگان تأییدشده اعلام می‌شود؛ تخفیفی از پیش اعمال نشده است.</p>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-gray-700">اقلام انتخاب‌شده:</span>
          {!pack ? (
            <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-3 text-center text-[11px] leading-6 text-gray-500">
              روی «استعلام قیمت و پیش‌فاکتور» یکی از پک‌ها بزنید یا با بودجه و انتخاب دستی پک بسازید.
            </div>
          ) : (
            <div className="flex flex-col gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs">
              <div className="flex items-center justify-between gap-2 font-medium text-gray-800">
                <span className="line-clamp-1">{pack.title_fa}</span>
                <span className="shrink-0 font-bold text-[#034EA2]">{n ? `${toPersianNum(n)} بسته` : "—"}</span>
              </div>
              <ul className="flex flex-col gap-1.5 border-t border-gray-200 pt-2 text-[11px] text-gray-700">
                {pack.items.slice(0, 4).map((i) => (
                  <li key={i.master_product_id} className="flex items-center gap-1.5"><Icon name="check" className="!text-[14px] text-[#034EA2]" /><span className="line-clamp-1">{i.title_fa}</span><span className="mr-auto shrink-0 text-gray-400">×{toPersianNum(i.quantity)}</span></li>
                ))}
                {pack.items.length > 4 && <li className="text-gray-400">و {toPersianNum(pack.items.length - 4)} قلم دیگر</li>}
              </ul>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 border-t border-gray-100 pt-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">مبلغ کل نهایی:</span>
            <span className="text-sm font-bold text-[#034EA2]">{total != null ? formatPrice(total) : "پس از استعلام قیمت"}</span>
          </div>
          <p className="text-[11px] leading-normal text-gray-400">قیمت، موجودی و تعداد در مرحله بررسی دوباره از سامانه دریافت و سپس استعلام یا پیش‌فاکتور ثبت می‌شود.</p>
        </div>

        <div className="flex flex-col gap-2.5">
          <button type="button" disabled={!valid} onClick={onContinue} className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#112D46] text-xs font-bold text-white shadow-sm transition hover:bg-[#0A1C2C] disabled:cursor-not-allowed disabled:opacity-50">
            <Icon name="description" className="!text-[16px]" /><span>ثبت استعلام و دریافت پیش‌فاکتور</span>
          </button>
          <button type="button" disabled title="چاپ پیش‌نویس هنوز فعال نشده است" className="flex h-10 w-full cursor-not-allowed items-center justify-center gap-2 rounded-xl border border-gray-200 text-xs font-semibold text-gray-400">
            <Icon name="print" className="!text-[16px]" /><span>چاپ پیش‌نویس (PDF)</span><Soon />
          </button>
        </div>

        {savedItems ? <button type="button" onClick={onResumeSaved} className="flex min-h-9 items-center gap-1.5 text-xs font-bold text-[#034EA2] hover:underline"><Icon name="history" className="!text-[16px]" /> ادامه پک ذخیره‌شده ({toPersianNum(savedItems)} نوع کالا)</button> : null}

        <div className="flex items-center justify-between border-t border-gray-100 pt-3 text-xs text-gray-500">
          <span>مشاوره تخصصی تدارکات:</span>
          <Link href="/contact" className="font-bold text-gray-800 hover:text-[#034EA2]">تماس با ما</Link>
        </div>
      </aside>

      <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-4 text-xs text-gray-600">
        <Icon name="verified_user" className="!text-[20px] text-[#034EA2]" />
        <span className="text-[11px] leading-relaxed">همه اقلام پک‌ها کالاهای واقعی کاتالوگ شصت‌آنلاین‌اند؛ <Link href="/account/packs" className="font-bold text-[#034EA2] hover:underline">پک‌های ذخیره‌شده در حساب</Link></span>
      </div>
    </div>
  );
}

// Stitch 63 sticky inquiry bar. Sits above the site's mobile bottom nav (globals.css .mobile-bottom-nav: 68px).
export function PackSummaryBar({ pack, count, onContinue, onCatalog }: Pick<Props, "pack" | "count" | "onContinue" | "onCatalog">) {
  const { n, valid, total } = useSummaryTotals(pack, count);
  return (
    <div className="fixed inset-x-0 bottom-[68px] z-40 border-t border-gray-200/90 bg-white/95 px-4 py-2.5 shadow-[0_-4px_16px_rgba(0,0,0,0.05)] backdrop-blur-md md:bottom-0 md:pb-[calc(env(safe-area-inset-bottom)+10px)] lg:hidden" dir="rtl">
      <div className="mx-auto flex max-w-[430px] items-center justify-between gap-3 md:max-w-xl">
        <div className="flex min-w-0 flex-col">
          <div className="flex items-center gap-1.5">
            <span className={`h-2 w-2 shrink-0 rounded-full ${pack ? "animate-pulse bg-[#034EA2]" : "bg-gray-300"}`} />
            <span className="line-clamp-1 text-[13px] font-bold text-[#112D46]">{pack ? `سبد استعلام: ${n ? toPersianNum(n) : "—"} پک` : "سبد استعلام خالی است"}</span>
          </div>
          <span className="line-clamp-1 text-[11px] font-bold text-[#034EA2]">{pack ? `برآورد: ${total != null ? formatPrice(total) : "پس از استعلام"}` : "یک پک را برای استعلام انتخاب کنید"}</span>
        </div>
        <button type="button" onClick={onCatalog} title="کاتالوگ ورق‌زدنی پک‌ها" className="flex shrink-0 items-center gap-1 rounded-xl border border-gray-200 bg-gray-100 px-2.5 py-2.5 text-[11px] font-bold text-gray-700 transition-all hover:bg-gray-200">
          <Icon name="menu_book" className="!text-[18px] text-[#FF7A00]" /><span className="hidden text-xs sm:inline">کاتالوگ</span>
        </button>
        <button type="button" disabled={!valid} onClick={onContinue} className="flex shrink-0 items-center gap-1.5 rounded-xl bg-[#112D46] px-4 py-2.5 text-[12px] font-bold text-white shadow-sm transition-all hover:bg-[#034EA2] disabled:opacity-50">
          <Icon name="description" className="!text-[17px]" /><span>دریافت پیش‌فاکتور</span>
        </button>
      </div>
    </div>
  );
}
