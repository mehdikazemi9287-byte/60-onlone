"use client";
// Pack summary: sticky sidebar on desktop, sticky bottom bar on mobile (Stitch 62/63).
// Shows only real data of the selected published pack; totals only when the backend returned a real price.
import Link from "next/link";
import { ClipboardList, Minus, Plus, X, FolderOpen, ArrowLeft } from "lucide-react";
import type { PackDetail } from "@/lib/storefront";
import { positiveInteger } from "@/lib/pack-input";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { btnPrimary, btnSecondary, card } from "./studio-ui";

type Props = {
  pack: PackDetail | null; count: string; setCount: (v: string) => void; onContinue: () => void; onClear: () => void;
  savedItems: number | null; onResumeSaved: () => void;
};

export function useSummaryTotals(pack: PackDetail | null, count: string) {
  const n = positiveInteger(count);
  const min = pack ? Math.max(1, pack.min_order_qty) : 1;
  const valid = !!pack && !!n && n >= min;
  const total = valid && pack!.price_minor != null && Number.isSafeInteger(pack!.price_minor * n!) ? pack!.price_minor * n! : null;
  return { n, min, valid, total };
}

export function PackSummaryPanel({ pack, count, setCount, onContinue, onClear, savedItems, onResumeSaved }: Props) {
  const { n, min, valid, total } = useSummaryTotals(pack, count);
  const step = (d: number) => setCount(String(Math.min(100000, Math.max(min, (n ?? min) + d))));
  return (
    <aside aria-label="خلاصه پک شما" className={`${card} hidden p-5 lg:sticky lg:top-40 lg:block`}>
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-extrabold text-[#112D46]"><ClipboardList className="h-4 w-4 text-[#034EA2]" strokeWidth={1.75} aria-hidden /> خلاصه پک شما</h2>
        {pack && <button type="button" onClick={onClear} aria-label="حذف انتخاب" className="flex h-8 w-8 items-center justify-center rounded-lg text-[#9CA3AF] hover:bg-[#F3F4F6] hover:text-[#111827]"><X className="h-4 w-4" /></button>}
      </div>
      {!pack ? (
        <div className="mt-4 rounded-xl border border-dashed border-[#E5E7EB] p-4 text-center">
          <p className="text-xs leading-6 text-[#6B7280]">یک پک آماده را «انتخاب برای استعلام» کنید یا با بودجه و انتخاب دستی پک بسازید.</p>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div>
            <p className="text-[11px] text-[#6B7280]">{pack.kind_fa}{pack.tier_fa ? ` · ${pack.tier_fa}` : ""}</p>
            <p className="mt-0.5 line-clamp-2 text-sm font-bold text-[#111827]">{pack.title_fa}</p>
            <p className="mt-1 text-[11px] text-[#6B7280]">{toPersianNum(pack.item_count)} قلم کالا · {toPersianNum(pack.unit_count)} واحد در هر پک</p>
          </div>
          <div>
            <label htmlFor="summary-count" className="text-xs font-bold text-[#112D46]">تعداد پک</label>
            <div className="mt-1 flex items-center gap-2">
              <button type="button" aria-label="کاهش" onClick={() => step(-10)} className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#E5E7EB] bg-white"><Minus className="h-4 w-4" /></button>
              <input id="summary-count" inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value)} className="h-10 min-w-0 flex-1 rounded-lg border border-[#E5E7EB] bg-white text-center text-sm font-bold" />
              <button type="button" aria-label="افزایش" onClick={() => step(10)} className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#E5E7EB] bg-white"><Plus className="h-4 w-4" /></button>
            </div>
            <p className={`mt-1 text-[11px] ${n && n < min ? "text-[#B45309]" : "text-[#6B7280]"}`}>حداقل سفارش: {toPersianNum(min)} پک</p>
          </div>
          <dl className="space-y-2 border-t border-[#F3F4F6] pt-3 text-xs">
            <div className="flex justify-between"><dt className="text-[#6B7280]">قیمت هر پک</dt><dd className="font-bold text-[#112D46]">{pack.price_minor != null ? formatPrice(pack.price_minor) : "پس از استعلام"}</dd></div>
            <div className="flex justify-between"><dt className="text-[#6B7280]">مبلغ کل</dt><dd className="text-sm font-extrabold text-[#112D46]">{total != null ? formatPrice(total) : "پس از استعلام"}</dd></div>
          </dl>
          <p className="text-[11px] leading-5 text-[#6B7280]">قیمت، موجودی و شرایط ارسال در مرحله بررسی دوباره از سامانه گرفته می‌شود.</p>
          <button type="button" disabled={!valid} onClick={onContinue} className={`${btnPrimary} w-full`}>ادامه به بررسی و استعلام <ArrowLeft className="h-4 w-4" aria-hidden /></button>
          <Link href={`/packs/${pack.slug}`} className={`${btnSecondary} w-full`}>جزئیات کامل پک</Link>
        </div>
      )}
      <div className="mt-4 space-y-1 border-t border-[#F3F4F6] pt-3">
        {savedItems ? <button type="button" onClick={onResumeSaved} className="flex min-h-9 items-center gap-1.5 text-xs font-bold text-[#034EA2] hover:underline">ادامه پک ذخیره‌شده ({toPersianNum(savedItems)} نوع کالا)</button> : null}
        <Link href="/account/packs" className="flex min-h-9 items-center gap-1.5 text-xs font-bold text-[#034EA2] hover:underline"><FolderOpen className="h-4 w-4" strokeWidth={1.75} aria-hidden /> پک‌های ذخیره‌شده در حساب</Link>
      </div>
    </aside>
  );
}

// Sits above the site's mobile bottom nav (globals.css .mobile-bottom-nav: 68px, <768px); bottom of viewport on tablets.
export function PackSummaryBar({ pack, count, onContinue }: Pick<Props, "pack" | "count" | "onContinue">) {
  const { n, valid, total } = useSummaryTotals(pack, count);
  if (!pack) return null;
  return (
    <div className="fixed inset-x-0 bottom-[68px] z-40 border-t border-[#E5E7EB] bg-white/95 px-4 pb-3 pt-3 md:bottom-0 md:pb-[calc(env(safe-area-inset-bottom)+12px)] shadow-[0_-4px_16px_rgba(17,24,39,0.06)] backdrop-blur-md lg:hidden" dir="rtl">
      <div className="mx-auto flex max-w-xl items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="line-clamp-1 text-xs font-bold text-[#111827]">{pack.title_fa}{n ? ` · ${toPersianNum(n)} پک` : ""}</p>
          <p className="text-[11px] text-[#6B7280]">مبلغ کل: {total != null ? formatPrice(total) : "پس از استعلام"}</p>
        </div>
        <button type="button" disabled={!valid} onClick={onContinue} className={`${btnPrimary} shrink-0 text-xs`}>ادامه و استعلام</button>
      </div>
    </div>
  );
}
