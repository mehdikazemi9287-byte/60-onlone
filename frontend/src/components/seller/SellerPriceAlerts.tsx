"use client";

// Seller panel: «دیگر بهترین پیشنهاد نیستی». Shows only the seller's own status and own price per level —
// never a competitor's price or name.
import { useEffect, useState } from "react";
import { errText } from "@/lib/commerce";
import { priceWatch, type SellerAlerts } from "@/lib/priceWatch";
import { faDate, formatPrice } from "@/lib/utils";
import { Card, ListState } from "@/components/commerce/ui";

export function SellerPriceAlerts({ token }: { token: string }) {
  const [data, setData] = useState<SellerAlerts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    priceWatch.seller(token).then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(errText(e, "بارگذاری هشدارها ناموفق بود")); });
    return () => { cancelled = true; };
  }, [token, retry]);
  const lost = data?.items.filter((i) => !i.is_best) ?? null;
  return (
    <div id="price-alerts">
      <Card title="هشدار بهترین پیشنهاد">
        <p className="text-sm leading-7 text-neutral-600">
          هر ساعت بررسی می‌شود که پیشنهاد شما در هر سطح (خرده‌فروشی، سازمانی و عمده) بهترین است یا نه. اگر دیگر بهترین نباشید
          اعلان و پیامک خلاصه می‌گیرید. قیمت و نام رقیب نمایش داده نمی‌شود.
        </p>
        <ListState items={error ? null : lost} error={error} empty="فعلاً در همهٔ کالاهای بررسی‌شده بهترین پیشنهاد شمایید." onRetry={() => setRetry((x) => x + 1)} />
        {lost && lost.length > 0 && (
          <ul className="divide-y text-sm">{lost.map((i) => (
            <li key={`${i.product.id}-${i.level}`} className="flex flex-wrap justify-between gap-2 py-2">
              <span className="min-w-0 font-bold">{i.product.title_fa} <span className="text-xs font-normal text-neutral-500">· سطح {i.level_fa}</span></span>
              <span className="text-xs text-neutral-600">قیمت شما: {i.own_price_minor != null ? formatPrice(i.own_price_minor) : "—"} · {faDate(i.updated_at)}</span>
            </li>
          ))}</ul>
        )}
        {data && data.recent.length > 0 && (
          <details className="text-sm"><summary className="cursor-pointer font-bold text-neutral-700">هشدارهای اخیر ({data.recent.length.toLocaleString("fa-IR")})</summary>
            <ul className="mt-2 space-y-1 text-xs text-neutral-600">{data.recent.map((r, k) => <li key={k}>{faDate(r.created_at)} — {r.text}</li>)}</ul>
          </details>
        )}
      </Card>
    </div>
  );
}
