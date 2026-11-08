"use client";

// Seller panel: «دیگر بهترین پیشنهاد نیستید». Shows only the seller's own status and own price per level —
// never a competitor's price or name.
import { useEffect, useState } from "react";
import { errText } from "@/lib/commerce";
import { priceWatch, type SellerAlerts } from "@/lib/priceWatch";
import { faDate, formatPrice } from "@/lib/utils";
import { Card, ListState, btnGhost, n } from "@/components/commerce/ui";

export function SellerPriceAlerts({ token }: { token: string }) {
  const [data, setData] = useState<SellerAlerts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    priceWatch.seller(token).then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(errText(e, "بارگذاری هشدارها ناموفق بود")); });
    return () => { cancelled = true; };
  }, [token, retry]);

  const toggleSms = async () => {
    if (!data) return;
    setBusy(true); setMsg(null);
    try {
      const r = await priceWatch.sellerSms(token, !data.sms_enabled);
      setData({ ...data, sms_enabled: r.sms_enabled });
      setMsg({ ok: true, text: r.sms_enabled ? "پیامک این هشدار روشن شد." : "پیامک این هشدار خاموش شد؛ اعلان داخل سایت ادامه دارد." });
    } catch (e) { setMsg({ ok: false, text: errText(e) }); } finally { setBusy(false); }
  };

  const lost = data?.items.filter((i) => !i.is_best) ?? null;
  return (
    <div id="price-alerts">
      <Card title="هشدار بهترین پیشنهاد" action={data && (
        <button type="button" className={btnGhost} disabled={busy} aria-pressed={data.sms_enabled} onClick={toggleSms}>
          پیامک: {data.sms_enabled ? "روشن" : "خاموش"}</button>
      )}>
        <p className="text-sm leading-7 text-neutral-600">
          هر ساعت بررسی می‌شود که پیشنهاد شما در هر سطح (خرده‌فروشی، سازمانی و عمده) بهترین است یا نه. اگر دیگر بهترین نباشید
          اعلان و پیامک خلاصه دریافت می‌کنید. قیمت و نام رقیب نمایش داده نمی‌شود.
        </p>
        {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-lg px-3 py-2 text-xs ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>}
        {data && !data.checked ? (
          <p className="rounded-xl bg-neutral-50 p-4 text-center text-sm text-neutral-500">هنوز بررسی‌ای انجام نشده؛ نتیجه حداکثر تا یک ساعت دیگر می‌آید.</p>
        ) : (
          <ListState items={error ? null : lost} error={error} empty="فعلاً در همهٔ کالاهای بررسی‌شده بهترین پیشنهاد شمایید." onRetry={() => setRetry((x) => x + 1)} />
        )}
        {lost && lost.length > 0 && (
          <ul className="divide-y text-sm">{lost.map((i) => (
            <li key={`${i.product.id}-${i.level}`} className="flex flex-wrap justify-between gap-2 py-2">
              <span className="min-w-0 font-bold">{i.product.title_fa} <span className="text-xs font-normal text-neutral-500">· سطح {i.level_fa}</span></span>
              <span className="text-xs text-neutral-600">قیمت شما: {i.own_price_minor != null ? formatPrice(i.own_price_minor) : "—"} · {faDate(i.updated_at)}</span>
            </li>
          ))}</ul>
        )}
        {data && data.recent.length > 0 && (
          <details className="text-sm"><summary className="cursor-pointer font-bold text-neutral-700">هشدارهای اخیر ({n(data.recent.length)})</summary>
            <ul className="mt-2 space-y-1 text-xs text-neutral-600">{data.recent.map((r, k) => <li key={k}>{faDate(r.created_at)} — {r.text}</li>)}</ul>
          </details>
        )}
      </Card>
    </div>
  );
}
