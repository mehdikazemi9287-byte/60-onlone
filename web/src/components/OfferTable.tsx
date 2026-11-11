import type { Offer } from "@/lib/catalog";
import { STOCK_FA } from "@/lib/catalog";
import { formatPrice, toPersianNum } from "@/lib/ui";

export function OfferTable({ offers, caption }: { offers: Offer[]; caption?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead><tr className="text-right text-xs text-neutral-600"><th scope="col" className="py-1 font-medium">فروشنده</th><th scope="col" className="font-medium">قیمت (با مالیات)</th><th scope="col" className="font-medium">تحویل</th><th scope="col" className="font-medium">موجودی</th></tr></thead>
        <tbody>
          {offers.map((o, i) => (
            <tr key={i} className="border-t border-[#E6EBF8]">
              <td className="py-2">{o.seller}{o.city ? <span className="text-xs text-neutral-600"> · {o.city}</span> : null}{o.best && <span className="mr-2 inline-block whitespace-nowrap rounded-full bg-[#FFB21E] px-2 text-[11px] font-bold text-[#102B7A]">پیشنهاد برتر</span>}</td>
              <td className="tabular-nums">{o.price_incl_vat_minor != null ? formatPrice(o.price_incl_vat_minor) : "—"}</td>
              <td>{o.lead_time_days != null ? `${toPersianNum(o.lead_time_days)} روز` : "—"}</td>
              <td>{STOCK_FA[o.stock_state] ?? o.stock_state}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
