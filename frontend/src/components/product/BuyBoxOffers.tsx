"use client";

// Buy Box winner + other sellers for a product (GET /storefront/products/:slug/offers). Additive to the product page.
import { useEffect, useState } from "react";
import Link from "next/link";
import { BadgeCheck, Trophy } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { apiRequest, grossMinor, type BuyBox, type BuyBoxOffer } from "@/lib/commerce";
import { formatPrice, toPersianNum } from "@/lib/utils";

function price(o: BuyBoxOffer, vatBps?: number): number | null {
  if (o.landed_unit_incl_vat_minor != null) return o.landed_unit_incl_vat_minor;
  if (o.price_incl_vat_minor != null) return o.price_incl_vat_minor;
  return grossMinor(o.landed_unit_minor ?? o.unit_price_minor, vatBps);
}

export function BuyBoxOffers({ slug, vatBps }: { slug: string; vatBps?: number }) {
  const { token, loading } = useAuth();
  const [data, setData] = useState<BuyBox | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    setData(null); setFailed(false);
    apiRequest<BuyBox>(`/storefront/products/${encodeURIComponent(slug)}/offers`, { token: token ?? undefined })
      .then((r) => { if (!cancelled) setData(r); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [slug, token, loading]);

  // Quiet section: the main sellers list above already covers the empty/failed case.
  if (failed || !data || data.eligible_count < 1) return null;
  const others = data.offers.filter((o) => o.eligible && !o.is_winner);
  const w = data.winner;

  return (
    <section aria-label="فروشندگان دیگر" className="rounded-2xl border border-neutral-200 bg-white p-4">
      {w && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-emerald-50 p-3">
          <p className="flex min-w-0 items-center gap-1 text-sm font-bold text-emerald-900">
            <Trophy className="h-4 w-4 flex-none" aria-hidden="true" />
            <span className="truncate">بهترین پیشنهاد: <SellerName o={w} /></span>
          </p>
          <PriceTag value={price(w, vatBps)} />
        </div>
      )}
      {others.length > 0 && (
        <>
          <h2 className="mb-2 text-sm font-black text-neutral-900">فروشندگان دیگر ({toPersianNum(others.length)})</h2>
          <ul className="divide-y divide-neutral-100">
            {others.map((o) => (
              <li key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span className="min-w-0">
                  <SellerName o={o} />
                  <span className="block text-xs text-neutral-500">
                    {o.in_stock ? "موجود" : "ناموجود"}{o.lead_time_days != null ? ` · ارسال ${toPersianNum(o.lead_time_days)} روزه` : ""}
                  </span>
                </span>
                <PriceTag value={price(o, vatBps)} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function SellerName({ o }: { o: BuyBoxOffer }) {
  const label = <>{o.seller_name}{o.official && <BadgeCheck className="mr-1 inline h-4 w-4 text-emerald-600" aria-label="برند رسمی" />}</>;
  return o.shop_slug ? <Link href={`/shops/${encodeURIComponent(o.shop_slug)}`} className="font-bold hover:underline">{label}</Link> : <span className="font-bold">{label}</span>;
}

function PriceTag({ value }: { value: number | null }) {
  if (value == null) return <span className="text-xs text-neutral-500">استعلام قیمت</span>;
  return <span className="text-left font-black text-neutral-900">{formatPrice(value)}<span className="block text-[10px] font-normal text-neutral-500">با مالیات بر ارزش افزوده</span></span>;
}
