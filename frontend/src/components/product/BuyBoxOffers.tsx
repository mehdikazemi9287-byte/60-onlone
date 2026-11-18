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
    <section aria-label="فروشندگان دیگر" className="flex flex-col gap-st-space-sm rounded-xl bg-st-surface-container-lowest p-st-space-md shadow-sm lg:p-st-space-lg">
      {w && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-st-secondary-fixed p-st-space-md">
          <p className="flex min-w-0 items-center gap-1 font-bold text-st-on-secondary-fixed">
            <Trophy className="h-4 w-4 flex-none" aria-hidden="true" />
            <span className="truncate">بهترین پیشنهاد: <SellerName o={w} /></span>
          </p>
          <PriceTag value={price(w, vatBps)} />
        </div>
      )}
      {others.length > 0 && (
        <>
          <h2 className="font-bold text-st-primary">فروشندگان دیگر ({toPersianNum(others.length)})</h2>
          <ul className="flex flex-col gap-st-space-xs">
            {others.map((o) => (
              <li key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-st-surface-container-low px-st-space-md py-st-space-sm">
                <span className="min-w-0">
                  <SellerName o={o} />
                  <span className="block text-st-label-md text-st-on-surface-variant">
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
  const label = <>{o.seller_name}{o.official && <BadgeCheck className="mr-1 inline h-4 w-4 text-st-secondary" aria-label="برند رسمی" />}</>;
  return o.shop_slug ? <Link href={`/shops/${encodeURIComponent(o.shop_slug)}`} className="font-bold hover:underline">{label}</Link> : <span className="font-bold">{label}</span>;
}

function PriceTag({ value }: { value: number | null }) {
  if (value == null) return <span className="text-st-label-md text-st-on-surface-variant">استعلام قیمت</span>;
  return <span className="text-left font-extrabold text-st-primary">{formatPrice(value)}<span className="block text-[10px] font-normal text-st-on-surface-variant">با مالیات بر ارزش افزوده</span></span>;
}
