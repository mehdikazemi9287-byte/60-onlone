"use client";
// Uniform pack card for the redesigned /pack-builder (Stitch 62/63): fixed 4:3 media made only of the pack's
// real item photos (quality-gated), name, item count, minimum quantity, real price or «قیمت پس از استعلام»,
// one primary (navy) and one secondary (outlined) action. No sample products, prices or stock photos.
import Link from "next/link";
import { Package, Check, SlidersHorizontal, Layers } from "lucide-react";
import type { PackDetail } from "@/lib/storefront";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { packImages } from "./PackCard";
import { btnPrimary, btnSecondary, card } from "./studio-ui";

export function PackGridCard({ p, good, used, selected, onSelect, onCustomize, compare }: {
  p: PackDetail; good: Set<string> | null; used?: Set<string>; selected: boolean;
  onSelect: () => void; onCustomize: () => void; compare: { picked: boolean; onPick: () => void };
}) {
  const pics = packImages(p, good, 3, used);
  const href = `/packs/${p.slug}`;
  const orgChannel = p.allowed_channels?.includes("organization");
  return (
    <article className={`${card} flex min-w-0 flex-col overflow-hidden transition hover:shadow-[0_8px_24px_rgba(17,45,70,0.08)] ${selected ? "ring-2 ring-[#034EA2]" : ""}`}>
      <Link href={href} aria-label={p.title_fa} className="relative block aspect-[4/3] bg-[#F3F4F6]">
        {good === null ? <span className="absolute inset-3 animate-pulse rounded-lg bg-white/70" />
          : pics.length ? (
            <span className="absolute inset-0 grid grid-cols-3 items-center gap-2 p-4">
              {pics.map((src) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={src} src={src} alt="" loading="lazy" className="aspect-square w-full rounded-lg bg-white object-contain p-1.5" />
              ))}
            </span>)
          : <span className="absolute inset-0 flex items-center justify-center"><Package className="h-10 w-10 text-[#9CA3AF]" strokeWidth={1.25} aria-hidden /></span>}
        {orgChannel && <span className="absolute right-3 top-3 rounded-md bg-[#F26B1D] px-2 py-0.5 text-[10px] font-bold text-white">قیمت سازمانی</span>}
      </Link>
      <div className="flex flex-1 flex-col p-4">
        <p className="text-[11px] font-medium text-[#6B7280]">{p.kind_fa}{p.tier_fa ? ` · ${p.tier_fa}` : ""}{p.occasion ? ` · ${p.occasion}` : ""}</p>
        <h3 className="mt-1 line-clamp-1 text-sm font-bold text-[#111827] md:text-[15px]"><Link href={href} className="hover:text-[#034EA2]">{p.title_fa}</Link></h3>
        <p className="mt-1 line-clamp-2 min-h-[40px] text-xs leading-5 text-[#6B7280]">{p.purpose_fa}</p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
          <div className="flex items-center gap-1 rounded-lg bg-[#F9FAFB] px-2 py-1.5"><Layers className="h-3.5 w-3.5 text-[#034EA2]" strokeWidth={1.75} aria-hidden /><dt className="sr-only">تعداد اقلام</dt><dd className="font-bold text-[#112D46]">{toPersianNum(p.item_count)} قلم کالا</dd></div>
          <div className="rounded-lg bg-[#F9FAFB] px-2 py-1.5"><dt className="inline text-[#6B7280]">حداقل: </dt><dd className="inline font-bold text-[#112D46]">{toPersianNum(p.min_order_qty)} پک</dd></div>
        </dl>
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-[#F3F4F6] pt-3">
          <span className="text-[11px] text-[#6B7280]">قیمت هر پک</span>
          <b className="text-sm font-extrabold text-[#112D46]">{p.price_minor != null ? formatPrice(p.price_minor) : "قیمت پس از استعلام"}</b>
        </div>
        <div className="mt-3 grid gap-2">
          <button type="button" onClick={onSelect} aria-pressed={selected} className={`${btnPrimary} h-10 min-h-10 text-xs`}>
            {selected ? <><Check className="h-4 w-4" aria-hidden /> انتخاب شد</> : "انتخاب برای استعلام"}
          </button>
          <button type="button" onClick={onCustomize} className={`${btnSecondary} h-10 min-h-10 text-xs`}>
            <SlidersHorizontal className="h-4 w-4" strokeWidth={1.75} aria-hidden /> مشاهده و شخصی‌سازی
          </button>
        </div>
        <label className="mt-2 flex min-h-9 cursor-pointer items-center gap-1.5 self-start text-[11px] text-[#6B7280]">
          <input type="checkbox" checked={compare.picked} onChange={compare.onPick} className="h-4 w-4 accent-[#034EA2]" /> افزودن به مقایسه
        </label>
      </div>
    </article>
  );
}
