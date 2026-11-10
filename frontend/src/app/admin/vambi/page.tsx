"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, toPersianNum } from "@/lib/utils";

// آمادگی راه‌اندازی و سنجش استفادهٔ وامبی (docs/vambi-comms-plan.md بخش ۲ و ۶). فقط خواندنی.
type Check = { key: string; label_fa: string; ok: boolean; detail: string };
type Readiness = { ready: boolean; checks: Check[] };
type Daily = { total: number; daily: { day: string; count: number }[] };
type Metrics = {
  days: number; from_day: string; to_day: string; searches: Daily; buy_clicks: Daily;
  watches: { created: number; active: number; active_sms_off: number };
  alerts: { total: number; by_type: Record<string, number>; sms_digests_sent: number; sellers_sms_off: number };
  vambi_orders: { referral_landings: number; orders: number; total_minor: number };
  seller_price_update: { alerts: number; followed_by_price_change: number; pending: number; rate: number | null; window_hours: number };
};
const ALERT_FA: Record<string, string> = {
  price_target: "ارزان شد", back_in_stock: "موجود شد", welfare_added: "به سبد رفاهی اضافه شد", price_drop: "کاهش قیمت",
  new_seller: "فروشندهٔ تازه", contract_expiring: "پایان قیمت قراردادی", new_tier: "پلهٔ تخفیف جدید",
  lost_best_offer: "دیگر بهترین پیشنهاد نیستید",
};
const RANGES = [7, 30, 90];
const card = "rounded-xl bg-white p-4 ring-1 ring-neutral-200";
const n = (v: number) => toPersianNum(v.toLocaleString("en-US"));

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={card}>
      <p className="text-xs text-neutral-500">{label}</p>
      <p className="mt-1 text-2xl font-black tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}

export default function VambiAdmin() {
  const { token } = useAuth();
  const [days, setDays] = useState(30);
  const [ready, setReady] = useState<Readiness | null>(null);
  const [m, setM] = useState<Metrics | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let alive = true;
    setMsg(null);
    Promise.all([
      apiRequest<Readiness>("/admin/vambi/readiness", { token }),
      apiRequest<Metrics>(`/admin/vambi/metrics?days=${days}`, { token }),
    ]).then(([r, x]) => { if (alive) { setReady(r); setM(x); } })
      .catch((e) => { if (alive) setMsg((e as Error).message); });
    return () => { alive = false; };
  }, [token, days]);

  if (!token || !ready || !m) return <p className="p-6 text-sm text-neutral-500">{msg ?? "در حال بارگذاری…"}</p>;
  const rate = m.seller_price_update;
  const maxDay = Math.max(1, ...m.searches.daily.map((d) => d.count));
  return (
    <section dir="rtl" className="space-y-5 p-4">
      <h1 className="text-xl font-black">وامبی: آمادگی راه‌اندازی و سنجش استفاده</h1>
      {msg && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{msg}</p>}

      <div className={card}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold">پیش‌شرط‌های شروع اطلاع‌رسانی</h2>
          <span className={`rounded-full px-3 py-1 text-sm font-bold ${ready.ready ? "bg-green-50 text-green-800" : "bg-amber-50 text-amber-800"}`}>
            {ready.ready ? "آماده" : "هنوز آماده نیست"}
          </span>
        </div>
        <ul className="mt-3 space-y-2 text-sm">
          {ready.checks.map((c) => (
            <li key={c.key} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-neutral-50 p-2">
              <span><span aria-hidden="true">{c.ok ? "✅" : "⏳"}</span> {c.label_fa}<span className="sr-only">{c.ok ? " (انجام شده)" : " (انجام نشده)"}</span></span>
              <span dir="ltr" className="text-xs text-neutral-600">{c.detail}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-neutral-500">تنظیمات فقط «set/unset» نشان داده می‌شوند. همین بررسی روی سرور: <span dir="ltr">python3 -m scripts.vambi_readiness</span></p>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="بازهٔ زمانی">
        <span className="text-sm text-neutral-600">بازه:</span>
        {RANGES.map((d) => (
          <button key={d} onClick={() => setDays(d)} aria-pressed={days === d}
            className={`rounded-lg px-3 py-1.5 text-sm font-bold ${days === d ? "bg-[#102B7A] text-white" : "bg-white ring-1 ring-neutral-200"}`}>
            {toPersianNum(d)} روز
          </button>
        ))}
        <span className="text-xs text-neutral-500" dir="ltr">{m.from_day} → {m.to_day}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="جستجو در وامبی" value={n(m.searches.total)} hint="فقط عدد؛ بدون متن جستجو و کاربر" />
        <Stat label="کلیک «مشاهده و خرید»" value={n(m.buy_clicks.total)} />
        <Stat label="«زیر نظر بگیر» تازه" value={n(m.watches.created)} hint={`فعال: ${n(m.watches.active)} · بدون پیامک: ${n(m.watches.active_sms_off)}`} />
        <Stat label="سفارش از مسیر وامبی" value={n(m.vambi_orders.orders)}
          hint={`${formatPrice(m.vambi_orders.total_minor)} · ورود از لینک وامبی: ${n(m.vambi_orders.referral_landings)}`} />
      </div>

      <div className={card}>
        <h2 className="font-bold">نرخ به‌روزرسانی قیمت فروشنده بعد از «دیگر بهترین پیشنهاد نیستید»</h2>
        <p className="mt-1 text-2xl font-black tabular-nums">{rate.rate == null ? "—" : `${toPersianNum(Math.round(rate.rate * 100))}٪`}</p>
        <p className="text-xs text-neutral-500">
          {n(rate.followed_by_price_change)} از {n(rate.alerts)} هشدار در {toPersianNum(rate.window_hours)} ساعت بعد تغییر قیمت داشتند
          {rate.pending > 0 && ` · ${n(rate.pending)} هشدار هنوز در بازهٔ ${toPersianNum(rate.window_hours)} ساعته است`}
        </p>
      </div>

      <div className={card}>
        <h2 className="font-bold">هشدارهای فرستاده‌شده: {n(m.alerts.total)}</h2>
        <ul className="mt-2 grid gap-1 text-sm md:grid-cols-2">
          {Object.entries(m.alerts.by_type).map(([k, v]) => <li key={k}>{ALERT_FA[k] ?? k}: {n(v)}</li>)}
          {Object.keys(m.alerts.by_type).length === 0 && <li className="text-neutral-500">هشداری در این بازه نیست.</li>}
        </ul>
        <p className="mt-2 text-xs text-neutral-500">پیامک‌های خلاصهٔ فرستاده‌شده: {n(m.alerts.sms_digests_sent)} · فروشنده‌هایی که پیامک را خاموش کرده‌اند: {n(m.alerts.sellers_sms_off)}</p>
      </div>

      <div className={card}>
        <h2 className="font-bold">جستجوی روزانه</h2>
        {m.searches.daily.length === 0 ? <p className="mt-2 text-sm text-neutral-500">هنوز جستجویی ثبت نشده است.</p> : (
          <ul className="mt-2 space-y-1 text-xs">
            {m.searches.daily.map((d) => (
              <li key={d.day} className="flex items-center gap-2">
                <span dir="ltr" className="w-24 shrink-0 text-neutral-600">{d.day}</span>
                <span className="h-3 rounded bg-[#1748C9]" style={{ width: `${Math.max(2, (d.count / maxDay) * 100)}%` }} aria-hidden="true" />
                <span className="tabular-nums">{n(d.count)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
