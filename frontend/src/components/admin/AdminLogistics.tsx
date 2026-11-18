"use client";
// Logistics analytics — Stitch screens 36 (supply-chain reports) and 38 (fleet error dashboard).
// Real data: GET /admin/carriers/tariffs (carrier tariff table). Delivery-discrepancy cases are produced as
// printable reports in the seller panel and are NOT stored by the backend, so every discrepancy/OTIF/damage
// metric, trend and root-cause chart here is an honest «به‌زودی» state — never a sample number.
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, toPersianNum } from "@/lib/utils";

type Tariff = { id: number; provider_code: string; service_level: string; name_fa: string; base_minor: number; per_kg_minor: number;
  transit_days_min: number; transit_days_max: number; is_active: number; supports_cod: number; max_weight_g: number | null; zones?: unknown[] };
const LEVEL_FA: Record<string, string> = { same_day: "همان روز", express: "سریع", economy: "اقتصادی" };
const Icon = ({ name, className = "" }: { name: string; className?: string }) => <span aria-hidden="true" className={`material-symbols-outlined ${className}`}>{name}</span>;
const card = "rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-lg shadow-sm";
const Soon = ({ children }: { children: React.ReactNode }) => <span className="inline-flex items-center gap-1 rounded-full bg-st-surface-container-high px-2 py-0.5 text-st-label-sm font-bold text-st-on-surface-variant"><Icon name="hourglass_top" className="text-[14px]" />{children}</span>;

export default function AdminLogistics() {
  const { token } = useAuth();
  const [tariffs, setTariffs] = useState<Tariff[] | null>(null), [err, setErr] = useState<string | null>(null), [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!token) return;
    let off = false; setTariffs(null); setErr(null);
    apiRequest<{ tariffs: Tariff[] }>("/admin/carriers/tariffs", { token, cache: "no-store" })
      .then((r) => { if (!off) setTariffs(Array.isArray(r.tariffs) ? r.tariffs : []); })
      .catch((e: unknown) => { if (!off) setErr(e instanceof Error ? e.message : "دریافت تعرفه‌ها ناموفق بود."); });
    return () => { off = true; };
  }, [token, retry]);
  const active = tariffs?.filter((t) => t.is_active) ?? [];
  const carriers = new Set(active.map((t) => t.provider_code));
  const kpis = [
    { t: "تعرفه‌های فعال حامل", v: tariffs ? toPersianNum(active.length) : "…", u: "تعرفه", i: "receipt_long", tone: "bg-st-secondary-fixed/50 text-st-secondary", foot: <span className="text-st-on-surface-variant">از {tariffs ? toPersianNum(tariffs.length) : "…"} تعرفهٔ ثبت‌شده</span> },
    { t: "حامل‌های دارای تعرفه", v: tariffs ? toPersianNum(carriers.size) : "…", u: "حامل", i: "local_shipping", tone: "bg-st-primary-fixed/40 text-st-primary-container", foot: <Link href="/logistics/estimate" className="font-bold text-st-secondary hover:underline">محاسبه‌گر کرایه</Link> },
    { t: "نرخ مغایرت بارنامه و آسیب", v: "—", u: "", i: "rule", tone: "bg-st-surface-container-high text-st-on-surface-variant", foot: <Soon>به‌زودی — ثبت پرونده در سرور</Soon> },
    { t: "تحویل سالم و به‌موقع (OTIF)", v: "—", u: "", i: "verified", tone: "bg-st-tertiary-fixed/60 text-st-on-tertiary-fixed-variant", foot: <Soon>به‌زودی</Soon> },
  ];
  return <div className="flex w-full flex-col gap-st-space-lg text-base">
    <div className="flex flex-col justify-between gap-st-space-md rounded-xl border border-st-surface-container bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:flex-row lg:items-start">
      <div className="flex items-start gap-st-space-sm">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-st-primary-container text-st-on-primary"><Icon name="monitoring" /></div>
        <div className="flex flex-col gap-st-space-xs">
          <div className="flex flex-wrap items-center gap-st-space-sm"><h1 className="font-black text-st-primary">تحلیل عملکرد لجستیک و نرخ مغایرت تحویل</h1><Soon>تحلیل خودکار به‌زودی</Soon></div>
          <p className="max-w-3xl text-st-on-surface-variant">تعرفه‌های حامل‌ها از سامانه خوانده می‌شود. گزارش‌های مغایرت تحویل فعلاً در پنل فروشنده به‌صورت PDF ساخته می‌شوند و در سرور ذخیره نمی‌شوند؛ شاخص‌ها و نمودارهای مغایرت پس از ثبت پرونده‌ها فعال می‌شوند.</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-st-space-sm">
        <button type="button" onClick={() => setRetry((x) => x + 1)} className="flex items-center gap-st-space-xs rounded-xl border border-st-surface-container px-st-space-md py-2 text-st-on-surface hover:bg-st-surface"><Icon name="refresh" className="text-[18px] text-st-outline" />بروزرسانی</button>
        <Link href="/logistics/estimate" className="flex items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-md py-2 text-st-on-primary hover:bg-st-secondary"><Icon name="calculate" className="text-[18px]" />محاسبه‌گر وزن و کرایه</Link>
      </div>
    </div>

    <section aria-label="شاخص‌های لجستیک" className="grid grid-cols-1 gap-st-space-md md:grid-cols-2 xl:grid-cols-4">
      {kpis.map((k) => <div key={k.t} className={`${card} flex flex-col justify-between`}>
        <div className="flex items-start justify-between">
          <div className="flex flex-col gap-st-space-xs"><span className="text-st-on-surface-variant">{k.t}</span>
            <div className="flex items-baseline gap-st-space-xs"><span className="text-st-headline-lg font-extrabold text-st-primary">{k.v}</span><span className="text-st-outline">{k.u}</span></div></div>
          <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${k.tone}`}><Icon name={k.i} className="text-[24px]" /></div>
        </div>
        <div className="mt-st-space-md flex items-center justify-between border-t border-st-surface-container-low pt-st-space-sm text-st-label-md">{k.foot}</div>
      </div>)}
    </section>

    <div className="grid grid-cols-1 gap-st-space-md lg:grid-cols-12">
      <section className={`${card} lg:col-span-7`} aria-labelledby="trend-t">
        <div className="flex items-start justify-between"><div><h2 id="trend-t" className="font-bold text-st-primary">روند هفتگی نرخ مغایرت و انطباق SLA</h2><p className="text-st-label-md text-st-on-surface-variant">مقایسهٔ نرخ مغایرت بارنامه با سقف مجاز</p></div><Soon>به‌زودی</Soon></div>
        <div className="mt-st-space-md flex h-56 flex-col items-center justify-center gap-st-space-xs rounded-xl border border-dashed border-st-outline-variant bg-st-surface-container-low text-center text-st-on-surface-variant">
          <Icon name="bar_chart" className="text-[36px] text-st-outline" /><span>داده‌ای برای رسم روند وجود ندارد.</span><span className="text-st-label-md">پرونده‌های مغایرت هنوز در سامانه ثبت نمی‌شوند.</span></div>
      </section>
      <section className={`${card} lg:col-span-5`} aria-labelledby="cause-t">
        <div className="flex items-start justify-between"><div><h2 id="cause-t" className="font-bold text-st-primary">توزیع ساختار علل مغایرت و آسیب</h2><p className="text-st-label-md text-st-on-surface-variant">کسری، آسیب‌دیده، اشتباه ارسالی، مازاد</p></div><Soon>به‌زودی</Soon></div>
        <div className="mt-st-space-md flex items-center gap-st-space-lg">
          <div className="relative flex h-36 w-36 shrink-0 items-center justify-center rounded-full border-[14px] border-st-surface-container"><span className="text-center text-st-label-md text-st-outline">بدون داده</span></div>
          <ul className="flex flex-1 flex-col gap-st-space-xs">{["کسری محموله", "آسیب‌دیدگی فیزیکی", "اشتباه ارسالی", "مازاد"].map((x) =>
            <li key={x} className="flex items-center justify-between rounded-lg bg-st-surface-container-low px-st-space-sm py-st-space-xs"><span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-st-outline-variant" />{x}</span><b className="text-st-outline">—</b></li>)}</ul>
        </div>
      </section>
    </div>

    <section className={card} aria-labelledby="flow-t">
      <div className="flex items-center gap-st-space-sm"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-st-primary text-st-on-primary"><Icon name="route" /></div>
        <div><h2 id="flow-t" className="font-bold text-st-primary">جریان فعلی اسناد لجستیک</h2><p className="text-st-label-md text-st-on-surface-variant">آنچه امروز در سامانه کار می‌کند</p></div></div>
      <div className="mt-st-space-md grid grid-cols-1 gap-st-space-md md:grid-cols-3">
        {[["description", "حوالهٔ خروج و بارنامه (A4)", "فروشنده از «ارسال سفارش‌ها» در پنل فروش، برگهٔ رسمی را از برچسب مرسوله چاپ می‌کند."],
          ["fact_check", "برگهٔ تحویل راننده", "چک‌لیست موبایلی اقلام، تماس با گیرنده و بارکد رهگیری؛ وضعیت را در سرور تغییر نمی‌دهد."],
          ["report_problem", "پروندهٔ مغایرت تحویل", "شمارش تحویل، علت مغایرت و تصویر بارنامه → صورت‌جلسهٔ PDF. ذخیرهٔ سروری و تحلیل: به‌زودی."]].map(([i, t, d]) =>
          <div key={t} className="flex flex-col gap-st-space-xs rounded-xl bg-st-surface-container-low p-st-space-md"><span className="flex items-center gap-st-space-xs font-bold text-st-primary"><Icon name={i} className="text-st-secondary" />{t}</span><p className="text-st-label-md leading-6 text-st-on-surface-variant">{d}</p></div>)}
      </div>
    </section>

    <section className="flex flex-col overflow-hidden rounded-xl border border-st-surface-container bg-st-surface-container-lowest shadow-sm" aria-labelledby="tariff-t" aria-busy={!tariffs && !err}>
      <div className="flex flex-col justify-between gap-st-space-sm border-b border-st-surface-container p-st-space-lg sm:flex-row sm:items-center">
        <div><h2 id="tariff-t" className="font-extrabold text-st-primary">جدول تعرفه‌ها و سطح خدمت حامل‌ها</h2><p className="text-st-label-md text-st-on-surface-variant">مبنای برآورد کرایه در محاسبه‌گر و صدور برچسب ارسال (قیمت‌ها پیش از حاشیه و هزینه‌های جانبی)</p></div>
        {tariffs && <span className="rounded-full bg-st-surface-container px-2 py-0.5 font-bold text-st-on-surface-variant">{toPersianNum(tariffs.length)} تعرفه</span>}
      </div>
      {err ? <div role="alert" className="flex flex-col items-start gap-st-space-sm p-st-space-lg"><b className="text-st-error">تعرفه‌ها دریافت نشد</b><p className="text-st-on-surface-variant">{err}</p>
        <button type="button" onClick={() => setRetry((x) => x + 1)} className="rounded-xl border border-st-surface-container px-st-space-md py-st-space-xs">تلاش دوباره</button></div>
        : <div className="overflow-x-auto"><table className="w-full border-collapse text-right">
          <thead><tr className="border-b border-st-surface-container bg-st-surface text-st-on-surface-variant">
            {["حامل و سرویس", "سطح خدمت", "کرایهٔ پایه", "هر کیلوگرم", "زمان تحویل", "مناطق ویژه", "پرداخت در محل", "وضعیت"].map((h) => <th key={h} className="px-st-space-md py-st-space-md font-bold">{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-st-surface-container">
            {!tariffs ? <tr><td colSpan={8} role="status" className="px-st-space-lg py-st-space-xl text-center text-st-on-surface-variant">در حال دریافت تعرفه‌ها…</td></tr>
              : tariffs.length === 0 ? <tr><td colSpan={8} className="px-st-space-lg py-st-space-xl text-center text-st-on-surface-variant">تعرفه‌ای ثبت نشده است.</td></tr>
              : tariffs.map((t) => <tr key={t.id} className="transition-colors hover:bg-st-surface/60">
                <td className="px-st-space-md py-st-space-md"><div className="flex items-center gap-st-space-sm"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-st-surface-container text-st-primary"><Icon name="local_shipping" className="text-[20px]" /></span>
                  <div className="flex flex-col"><b className="text-st-primary">{t.name_fa}</b><span className="text-st-label-sm text-st-outline" dir="ltr">{t.provider_code}</span></div></div></td>
                <td className="px-st-space-md py-st-space-md">{LEVEL_FA[t.service_level] ?? t.service_level}</td>
                <td className="px-st-space-md py-st-space-md font-bold text-st-primary">{formatPrice(t.base_minor)}</td>
                <td className="px-st-space-md py-st-space-md">{formatPrice(t.per_kg_minor)}</td>
                <td className="px-st-space-md py-st-space-md">{t.transit_days_max === 0 ? "همان روز" : `${toPersianNum(t.transit_days_min)} تا ${toPersianNum(t.transit_days_max)} روز`}</td>
                <td className="px-st-space-md py-st-space-md text-st-on-surface-variant">{toPersianNum(t.zones?.length ?? 0)} منطقه</td>
                <td className="px-st-space-md py-st-space-md">{t.supports_cod ? <Icon name="check_circle" className="text-[20px] text-st-secondary" /> : <span className="text-st-outline">—</span>}</td>
                <td className="px-st-space-md py-st-space-md"><span className={`rounded-full px-st-space-sm py-1 text-st-label-sm font-bold ${t.is_active ? "bg-st-secondary-fixed/60 text-st-secondary" : "bg-st-surface-container text-st-on-surface-variant"}`}>{t.is_active ? "فعال" : "غیرفعال"}</span></td>
              </tr>)}
          </tbody></table></div>}
    </section>
  </div>;
}
