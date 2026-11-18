"use client";
// Pack card — Stitch 62 (desktop: 4:3 photo, orange corner badge, title, gray meta chips, item list, price
// line, navy + outlined buttons) and Stitch 63 (mobile: 16:10 photo, badge + code chip, title + min-qty
// chip, purpose, item tags, gray price/packaging strip, two-column buttons).
// Every value is the published pack's real data; photos are only the pack's own quality-gated item photos.
import Link from "next/link";
import type { PackDetail } from "@/lib/storefront";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { packImages } from "./PackCard";
import { Icon } from "./studio-ui";

export const packCode = (p: PackDetail) => `PK-${p.id}`;
export const packPrice = (p: PackDetail) => (p.price_minor != null ? formatPrice(p.price_minor) : "پس از استعلام");
export const packBadge = (p: PackDetail) => p.tier_fa ?? (p.occasion ? `پک ${p.occasion}` : `پک ${p.kind_fa}`);

function Media({ p, good, used, ratio }: { p: PackDetail; good: Set<string> | null; used?: Set<string>; ratio: string }) {
  const pics = packImages(p, good, 3, used);
  return (
    <span className={`relative block w-full overflow-hidden bg-gray-100 ${ratio}`}>
      {good === null ? <span className="absolute inset-3 animate-pulse rounded-lg bg-white/70" />
        : pics.length === 1 ? // eslint-disable-next-line @next/next/no-img-element
          <img src={pics[0]} alt="" loading="lazy" className="absolute inset-0 h-full w-full bg-white object-contain p-4" />
        : pics.length ? (
          <span className="absolute inset-0 grid grid-cols-3 items-center gap-2 bg-white p-4">
            {pics.map((src) => // eslint-disable-next-line @next/next/no-img-element
              <img key={src} src={src} alt="" loading="lazy" className="aspect-square w-full rounded-lg object-contain" />)}
          </span>)
        : <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-gray-400"><Icon name="inventory_2" className="!text-[40px]" /><span className="text-[10px]">تصویر تأییدشده‌ای برای اقلام ثبت نشده</span></span>}
    </span>
  );
}

type Props = { p: PackDetail; good: Set<string> | null; used?: Set<string>; selected: boolean; onSelect: () => void; onCustomize: () => void };

export function PackGridCard({ p, good, used, selected, onSelect, onCustomize }: Props) {
  const href = `/packs/${p.slug}`;
  const items = p.items.map((i) => i.title_fa);
  return (
    <>
      {/* Desktop — Stitch 62 */}
      <article className={`group hidden flex-col justify-between overflow-hidden rounded-xl border bg-white shadow-sm transition hover:shadow-md md:flex ${selected ? "border-[#034EA2] ring-1 ring-[#034EA2]" : "border-gray-200"}`}>
        <div>
          <Link href={href} aria-label={p.title_fa} className="relative block">
            <Media p={p} good={good} used={used} ratio="aspect-[4/3]" />
            <span className="absolute right-3 top-3 rounded bg-[#FF7A00] px-2.5 py-0.5 text-[11px] font-bold text-white">{packBadge(p)}</span>
          </Link>
          <div className="flex flex-col gap-2 p-4">
            <h2 className="line-clamp-1 text-sm font-bold text-gray-900 transition group-hover:text-[#034EA2]"><Link href={href}>{p.title_fa}</Link></h2>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">شامل {toPersianNum(p.item_count)} قلم کالا</span>
              <span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">حداقل تیراژ: {toPersianNum(Math.max(1, p.min_order_qty))} بسته</span>
            </div>
            <p className="mt-1 line-clamp-2 text-[11px] leading-normal text-gray-500">{items.join("، ")}.</p>
          </div>
        </div>
        <div className="flex flex-col gap-3 p-4 pt-0">
          <div className="flex items-center justify-between border-t border-gray-100 pt-3">
            <span className="text-[11px] text-gray-400">ارزش محاسباتی:</span>
            <span className="text-xs font-bold text-[#034EA2]">{packPrice(p)}</span>
          </div>
          <div className="flex flex-col gap-2">
            <button type="button" onClick={onSelect} aria-pressed={selected} className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-[#112D46] text-xs font-bold text-white transition hover:bg-[#0A1C2C]">
              <Icon name={selected ? "check_circle" : "description"} className="!text-[15px]" />
              <span>{selected ? "انتخاب شد برای استعلام" : "استعلام قیمت و پیش‌فاکتور"}</span>
            </button>
            <button type="button" onClick={onCustomize} className="h-8 w-full rounded-lg border border-gray-200 text-[11px] font-semibold text-gray-700 transition hover:bg-gray-50">مشاهده و شخصی‌سازی</button>
          </div>
        </div>
      </article>

      {/* Mobile — Stitch 63 */}
      <article className={`flex flex-col overflow-hidden rounded-xl border bg-white shadow-sm md:hidden ${selected ? "border-[#034EA2] ring-1 ring-[#034EA2]" : "border-gray-200"}`}>
        <Link href={href} aria-label={p.title_fa} className="relative block">
          <Media p={p} good={good} ratio="aspect-[16/10]" />
          <span className="absolute right-2.5 top-2.5 flex items-center gap-1 rounded-md bg-[#FF7A00] px-2.5 py-0.5 text-[11px] font-bold text-white"><Icon name="local_offer" className="!text-[13px]" />{packBadge(p)}</span>
          <span dir="ltr" className="absolute bottom-2 left-2 rounded bg-[#112D46]/85 px-2 py-0.5 text-[10px] font-medium text-white">{packCode(p)} :کد</span>
        </Link>
        <div className="flex flex-col gap-2.5 p-3.5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="line-clamp-1 text-[15px] font-extrabold text-[#112D46]"><Link href={href}>{p.title_fa}</Link></h3>
            <span className="shrink-0 rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-[11px] font-bold text-[#034EA2]">حداقل تیراژ: {toPersianNum(Math.max(1, p.min_order_qty))} عدد</span>
          </div>
          <p className="line-clamp-2 text-[12px] leading-relaxed text-gray-600">{p.purpose_fa}</p>
          <div className="flex flex-wrap gap-1.5 py-0.5">
            {items.slice(0, 4).map((t, i) => <span key={i} className="line-clamp-1 max-w-full rounded-md border border-gray-200 bg-[#F9F9F9] px-2 py-1 text-[11px] text-gray-700">{t}</span>)}
            {items.length > 4 && <span className="rounded-md border border-gray-200 bg-[#F9F9F9] px-2 py-1 text-[11px] text-gray-500">+{toPersianNum(items.length - 4)} قلم</span>}
          </div>
          <div className="flex items-center justify-between rounded-lg border border-gray-200/80 bg-[#F9F9F9] p-2.5">
            <div>
              <span className="block text-[10px] leading-tight text-gray-500">ارزش محاسباتی واحد:</span>
              <span className="text-[13px] font-extrabold text-[#034EA2]">{packPrice(p)}</span>
            </div>
            <div className="flex items-center gap-1 text-[11px] font-medium text-gray-600">
              <Icon name="inventory" className="!text-[16px] text-gray-500" /><span>{p.packaging_fa ?? `${toPersianNum(p.unit_count)} واحد در هر پک`}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 pt-1">
            <button type="button" onClick={onCustomize} className="flex items-center justify-center gap-1 rounded-lg border border-gray-300 bg-white py-2 text-[12px] font-bold text-[#112D46] transition-colors hover:bg-gray-50">
              <Icon name="tune" className="!text-[17px]" /><span>شخصی‌سازی</span>
            </button>
            <button type="button" onClick={onSelect} aria-pressed={selected} className="flex items-center justify-center gap-1 rounded-lg bg-[#112D46] py-2 text-[12px] font-bold text-white transition-colors active:bg-[#034EA2]">
              <Icon name={selected ? "check_circle" : "request_quote"} className="!text-[17px]" /><span>{selected ? "انتخاب شد" : "استعلام قیمت"}</span>
            </button>
          </div>
        </div>
      </article>
    </>
  );
}
