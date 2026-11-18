"use client";
// Shipping weight & cost calculator — Stitch screen 54. Costs come only from POST /api/v1/shipping/quote
// (active carrier tariffs; buyer-facing price, no internal cost). Weight/volume tiles are arithmetic on the
// user's own inputs. Stitch's fleet recommendation, pack presets, multi-part split and schedule have no backend:
// they are shown as «به‌زودی», never with sample numbers.
import { useMemo, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { formatPrice, toPersianNum } from "@/lib/utils";

type Option = { provider_code: string; service_level: string; service_name_fa: string; price_minor: number;
  eta_days_min: number; eta_days_max: number; billable_weight_g?: number; cod?: number };
type Quote = { strategy: string; selected: Option; options: Option[] };
const LEVELS = [["same_day", "همان روز (درون‌شهری)"], ["express", "سریع (اکسپرس)"], ["economy", "اقتصادی"]] as const;
const PROVINCES = ["تهران", "البرز", "اصفهان", "خراسان رضوی", "فارس", "آذربایجان شرقی", "آذربایجان غربی", "خوزستان", "مازندران", "گیلان", "کرمان", "قم", "مرکزی", "یزد", "همدان", "کرمانشاه", "قزوین", "زنجان", "سمنان", "گلستان", "اردبیل", "لرستان", "هرمزگان", "بوشهر", "کردستان", "سیستان و بلوچستان", "چهارمحال و بختیاری", "کهگیلویه و بویراحمد", "ایلام", "خراسان شمالی", "خراسان جنوبی"];
const Icon = ({ name, className = "" }: { name: string; className?: string }) => <span aria-hidden="true" className={`material-symbols-outlined ${className}`}>{name}</span>;
const fa = (v: number, d = 0) => toPersianNum(v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d })).replace(/,/g, "٬").replace(/\./g, "٫");
const num = (s: string) => { const v = Number(s.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٬,]/g, "")); return Number.isFinite(v) ? v : NaN; };
const box = "flex flex-col gap-st-space-md rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-sm";
const input = "w-full rounded-xl border border-st-outline-variant bg-st-surface-container-lowest px-3 py-2.5 text-st-body-md text-st-on-surface outline-none focus:border-st-primary-container";
const step = (n: string, title: string, aside?: React.ReactNode) => <div className="flex items-center justify-between pb-st-space-xs">
  <div className="flex items-center gap-st-space-xs"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-st-surface-container-high text-st-title-md font-bold text-st-primary">{n}</span>
    <h2 className="text-st-title-lg font-bold text-st-primary">{title}</h2></div>{aside}</div>;

export function ShippingEstimator() {
  const [dims, setDims] = useState({ l: "40", w: "30", h: "25", kg: "8.5" });
  const [qty, setQty] = useState(10);
  const [flags, setFlags] = useState({ fragile: false, cold: false });
  const [origin, setOrigin] = useState({ province: "تهران", city: "تهران" });
  const [dest, setDest] = useState({ province: "", city: "" });
  const [levels, setLevels] = useState<string[]>(["same_day", "express", "economy"]);
  const [strategy, setStrategy] = useState<"cheapest" | "fastest">("cheapest");
  const [cod, setCod] = useState(""), [ins, setIns] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [quote, setQuote] = useState<Quote | null>(null);

  const L = num(dims.l), W = num(dims.w), H = num(dims.h), KG = num(dims.kg);
  const valid = [L, W, H, KG].every((v) => v > 0) && qty >= 1 && qty <= 1000;
  const totalKg = valid ? KG * qty : 0, cbm = valid ? (L * W * H * qty) / 1e6 : 0, volKg = valid ? (L * W * H * qty) / 5000 : 0;
  const reset = () => { setDims({ l: "40", w: "30", h: "25", kg: "8.5" }); setQty(10); setFlags({ fragile: false, cold: false }); setDest({ province: "", city: "" }); setCod(""); setIns(""); setQuote(null); setErr(null); };
  const stale = useMemo(() => JSON.stringify([dims, qty, flags, origin, dest, levels, strategy, cod, ins]), [dims, qty, flags, origin, dest, levels, strategy, cod, ins]);
  const [quotedFor, setQuotedFor] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null);
    if (!valid) { setErr("ابعاد، وزن و تعداد (۱ تا ۱۰۰۰) را درست وارد کنید."); return; }
    if (!origin.province.trim() || !origin.city.trim() || !dest.province.trim() || !dest.city.trim()) { setErr("استان و شهر مبدأ و مقصد را وارد کنید."); return; }
    if (!levels.length) { setErr("دست‌کم یک سطح خدمت را انتخاب کنید."); return; }
    const codT = cod ? num(cod) : 0, insT = ins ? num(ins) : 0;
    if (!(codT >= 0) || !(insT >= 0)) { setErr("مبلغ پرداخت در محل یا ارزش بیمه نامعتبر است."); return; }
    setBusy(true);
    try {
      const r = await apiRequest<Quote>("/shipping/quote", { method: "POST", body: JSON.stringify({
        origin: { province: origin.province.trim(), city: origin.city.trim() }, destination: { province: dest.province.trim(), city: dest.city.trim() },
        parcels: [{ length_mm: Math.round(L * 10), width_mm: Math.round(W * 10), height_mm: Math.round(H * 10), gross_weight_g: Math.round(KG * 1000), is_fragile: flags.fragile, requires_cold_chain: flags.cold, quantity: qty }],
        service_levels: levels, strategy, cod_value_minor: Math.round(codT * 10), insurance_value_minor: Math.round(insT * 10) }) });
      setQuote(r); setQuotedFor(stale);
    } catch (e2) { setQuote(null); setErr(e2 instanceof Error ? e2.message : "استعلام کرایه ناموفق بود."); } finally { setBusy(false); }
  };
  const outdated = quote && quotedFor !== stale;
  const billKg = quote?.selected?.billable_weight_g != null ? quote.selected.billable_weight_g / 1000 : null;

  return <div className="min-h-[calc(100vh-80px)] w-full bg-st-surface" dir="rtl">
    <form onSubmit={submit} className="mx-auto flex w-full max-w-[1440px] flex-col gap-st-space-xl px-st-space-md py-st-space-xl lg:px-st-gutter-lg">
      {/* Header band */}
      <div className="relative overflow-hidden rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-sm lg:p-st-space-xl">
        <div className="pointer-events-none absolute -right-20 -top-20 h-80 w-80 rounded-full bg-st-secondary-fixed/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-12 -left-12 h-64 w-64 rounded-full bg-st-primary-fixed/20 blur-2xl" />
        <div className="relative z-10 flex flex-col items-start justify-between gap-st-space-lg lg:flex-row lg:items-center">
          <div className="flex max-w-3xl flex-col gap-st-space-xs">
            <div className="flex flex-wrap items-center gap-st-space-sm">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-st-primary-container px-3 py-1 text-st-label-md text-st-on-primary"><Icon name="local_shipping" className="text-sm" />محاسبه‌گر حمل و بارسنجی</span>
              <span className="flex items-center gap-1 text-st-label-sm text-st-outline"><span className="inline-block h-2 w-2 rounded-full bg-st-secondary" />استعلام از تعرفهٔ حامل‌های فعال</span>
            </div>
            <h1 className="mt-1 text-st-headline-xl-mobile tracking-tight text-st-primary lg:text-st-headline-xl">محاسبه‌گر وزن بار و کرایهٔ حمل ۶۰ آنلاین</h1>
            <p className="text-st-body-lg leading-relaxed text-st-on-surface-variant">وزن ناخالص، حجم مکعبی (CBM) و وزن حجمی محموله را حساب کنید و کرایهٔ ارسال را از تعرفهٔ حامل‌های فعال، بر اساس مسیر و سطح خدمت، استعلام بگیرید.</p>
          </div>
          <div className="flex items-center justify-end gap-st-space-md self-stretch lg:self-auto">
            <div className="hidden flex-col items-end rounded-xl bg-st-surface-container-low p-st-space-md sm:flex">
              <span className="text-st-label-sm text-st-outline">مرجع نرخ</span>
              <span className="text-st-title-md font-bold text-st-primary">تعرفه‌های ثبت‌شدهٔ حامل‌ها</span>
              <span className="text-st-label-sm text-st-secondary">قیمت قطعی هنگام صدور بارنامه</span>
            </div>
            <button type="button" onClick={reset} className="flex items-center gap-st-space-xs rounded-xl bg-st-surface-container px-4 py-3 text-st-label-lg text-st-primary transition-colors hover:bg-st-surface-container-high"><Icon name="restart_alt" className="text-st-title-md" /><span>تنظیمات پیش‌فرض</span></button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-st-space-xl lg:grid-cols-12">
        {/* Inputs */}
        <div className="flex flex-col gap-st-space-lg lg:col-span-5">
          <section className={box} aria-label="نوع محموله و بسته‌ها">
            {step("۱", "نوع محموله و بسته‌های سفارش", <span className="text-st-label-sm text-st-outline">واحد: بسته</span>)}
            <div className="grid grid-cols-2 gap-st-space-xs rounded-xl bg-st-surface-container-low p-1 text-center">
              <span className="rounded-lg bg-st-surface-container-lowest py-2 text-st-label-lg font-bold text-st-primary shadow-sm">بسته با ابعاد مشخص</span>
              <span className="py-2 text-st-label-lg text-st-outline" title="به‌زودی">کالای کاتالوگ · به‌زودی</span>
            </div>
            <div className="flex flex-col gap-st-space-sm rounded-xl bg-st-surface-container-low p-st-space-md">
              <div className="grid grid-cols-3 gap-st-space-sm">
                {([["l", "طول (سانتی‌متر)"], ["w", "عرض (سانتی‌متر)"], ["h", "ارتفاع (سانتی‌متر)"]] as const).map(([k, label]) =>
                  <label key={k} className="flex flex-col gap-1 text-st-label-md text-st-outline">{label}<input inputMode="decimal" dir="ltr" required value={dims[k]} onChange={(e) => setDims({ ...dims, [k]: e.target.value })} className={`${input} text-center`} /></label>)}
              </div>
              <label className="flex flex-col gap-1 text-st-label-md text-st-outline">وزن ناخالص هر بسته (کیلوگرم)<input inputMode="decimal" dir="ltr" required value={dims.kg} onChange={(e) => setDims({ ...dims, kg: e.target.value })} className={`${input} text-center`} /></label>
              <div className="flex flex-wrap gap-st-space-md text-st-body-sm text-st-on-surface-variant">
                <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-[#0a2735]" checked={flags.fragile} onChange={(e) => setFlags({ ...flags, fragile: e.target.checked })} />شکستنی</label>
                <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4 accent-[#0a2735]" checked={flags.cold} onChange={(e) => setFlags({ ...flags, cold: e.target.checked })} />نیازمند زنجیرهٔ سرما</label>
              </div>
            </div>
            <div className="mt-st-space-xs flex flex-col gap-st-space-xs">
              <div className="flex items-center justify-between"><span className="text-st-label-md text-st-outline">تعداد کل بسته‌ها</span><span className="text-st-label-md font-bold text-st-secondary">{toPersianNum(qty)} بسته</span></div>
              <div className="flex items-center gap-st-space-xs rounded-xl bg-st-surface-container-low p-1">
                <button type="button" aria-label="کم کردن" onClick={() => setQty((q) => Math.max(1, q - 1))} className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-surface-container-lowest text-st-primary"><Icon name="remove" /></button>
                <input aria-label="تعداد بسته" inputMode="numeric" dir="ltr" value={qty} onChange={(e) => { const v = Math.floor(num(e.target.value)); setQty(Number.isFinite(v) ? Math.min(1000, Math.max(1, v)) : 1); }} className="h-10 flex-1 rounded-lg border border-st-outline-variant bg-st-surface-container-lowest text-center text-st-title-lg font-bold text-st-primary outline-none" />
                <button type="button" aria-label="افزودن" onClick={() => setQty((q) => Math.min(1000, q + 1))} className="flex h-10 w-10 items-center justify-center rounded-lg bg-st-surface-container-lowest text-st-primary"><Icon name="add" /></button>
              </div>
              <div className="flex flex-wrap gap-st-space-xs">{[1, 10, 50, 100].map((v) =>
                <button key={v} type="button" onClick={() => setQty(v)} className={qty === v ? "rounded-full bg-st-primary px-3 py-1 text-st-label-sm text-st-on-primary" : "rounded-full bg-st-surface-container px-3 py-1 text-st-label-sm text-st-on-surface-variant hover:bg-st-surface-container-high"}>{toPersianNum(v)} بسته</button>)}</div>
            </div>
          </section>

          <section className={box} aria-label="مبدا و مقصد">
            {step("۲", "مبدأ و مقصد باربری", <span className="flex items-center gap-1 text-st-label-md text-st-outline" title="به‌زودی"><Icon name="add_circle" className="text-sm" />چند مقصدی · به‌زودی</span>)}
            <datalist id="provinces">{PROVINCES.map((p) => <option key={p} value={p} />)}</datalist>
            <div className="flex flex-col gap-st-space-xs">
              <span className="text-st-label-md text-st-outline">مبدأ بارگیری محموله</span>
              <div className="flex items-center gap-st-space-sm rounded-xl bg-st-surface-container-low p-st-space-sm">
                <Icon name="warehouse" className="text-st-secondary" />
                <div className="grid flex-1 grid-cols-2 gap-st-space-xs">
                  <input aria-label="استان مبدأ" list="provinces" required placeholder="استان" value={origin.province} onChange={(e) => setOrigin({ ...origin, province: e.target.value })} className={input} />
                  <input aria-label="شهر مبدأ" required placeholder="شهر" value={origin.city} onChange={(e) => setOrigin({ ...origin, city: e.target.value })} className={input} />
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-st-space-sm rounded-xl bg-st-surface-container-low p-st-space-md">
              <div className="flex items-center gap-2"><span className="flex h-6 w-6 items-center justify-center rounded-md bg-st-secondary-fixed text-st-label-sm font-bold text-st-on-secondary-fixed">پ۱</span><span className="text-st-title-md font-semibold text-st-primary">مقصد نهایی</span></div>
              <div className="grid grid-cols-2 gap-st-space-xs">
                <input aria-label="استان مقصد" list="provinces" required placeholder="استان" value={dest.province} onChange={(e) => setDest({ ...dest, province: e.target.value })} className={input} />
                <input aria-label="شهر مقصد" required placeholder="شهر" value={dest.city} onChange={(e) => setDest({ ...dest, city: e.target.value })} className={input} />
              </div>
            </div>
          </section>

          <section className={box} aria-label="شرایط خدمت">
            {step("۳", "سطح خدمت و پوشش‌ها")}
            <div className="grid grid-cols-1 gap-st-space-sm sm:grid-cols-2">
              {(["cheapest", "fastest"] as const).map((s) => <label key={s} className={`flex cursor-pointer items-start gap-st-space-sm rounded-xl p-st-space-sm ${strategy === s ? "bg-st-surface-container" : "bg-st-surface-container-low"}`}>
                <input type="radio" name="strategy" className="mt-1 h-4 w-4 accent-[#0a2735]" checked={strategy === s} onChange={() => setStrategy(s)} />
                <span className="flex flex-col"><b className="text-st-title-md text-st-primary">{s === "cheapest" ? "ارزان‌ترین گزینه" : "سریع‌ترین گزینه"}</b><small className="text-st-label-sm text-st-outline">{s === "cheapest" ? "پیشنهاد بر اساس کمترین کرایه" : "پیشنهاد بر اساس کمترین زمان تحویل"}</small></span></label>)}
            </div>
            <div className="flex flex-col gap-st-space-xs">
              <span className="text-st-label-md text-st-outline">سطح‌های خدمت مورد استعلام</span>
              {LEVELS.map(([v, label]) => <label key={v} className="flex items-center gap-st-space-sm rounded-xl bg-st-surface-container-low px-st-space-sm py-2 text-st-body-md text-st-primary">
                <input type="checkbox" className="h-4 w-4 accent-[#0a2735]" checked={levels.includes(v)} onChange={(e) => setLevels((l) => e.target.checked ? [...l, v] : l.filter((x) => x !== v))} />{label}</label>)}
            </div>
            <div className="grid grid-cols-2 gap-st-space-sm">
              <label className="flex flex-col gap-1 text-st-label-md text-st-outline">پرداخت در محل (تومان)<input inputMode="numeric" dir="ltr" placeholder="0" value={cod} onChange={(e) => setCod(e.target.value)} className={input} /></label>
              <label className="flex flex-col gap-1 text-st-label-md text-st-outline">ارزش بیمهٔ محموله (تومان)<input inputMode="numeric" dir="ltr" placeholder="0" value={ins} onChange={(e) => setIns(e.target.value)} className={input} /></label>
            </div>
          </section>
        </div>

        {/* Results */}
        <div className="flex flex-col gap-st-space-lg lg:col-span-7">
          <div className="grid grid-cols-1 gap-st-space-md md:grid-cols-2">
            <div className="relative flex flex-col justify-between overflow-hidden rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
              <div className="flex items-start justify-between">
                <div className="flex flex-col"><span className="text-st-label-md text-st-outline">وزن ناخالص کل محموله (Gross Weight)</span>
                  <div className="mt-1 flex items-baseline gap-st-space-xs"><span className="text-st-headline-xl font-extrabold text-st-primary">{valid ? (totalKg >= 1000 ? fa(totalKg / 1000, 2) : fa(totalKg, 1)) : "—"}</span><span className="text-st-title-lg text-st-on-surface-variant">{totalKg >= 1000 ? "تـن" : "کیلوگرم"}</span></div>
                  <span className="text-st-label-md font-semibold text-st-secondary">{valid ? `${toPersianNum(qty)} بسته × ${fa(KG, 2)} کیلوگرم` : "ابعاد و وزن را وارد کنید"}</span></div>
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-st-secondary-fixed/50 text-st-secondary"><Icon name="scale" className="text-st-headline-md" /></div>
              </div>
              <div className="mt-st-space-md flex flex-col gap-1.5 pt-st-space-sm">
                <div className="flex items-center justify-between text-st-label-sm text-st-on-surface-variant"><span>وزن حجمی (ضریب ۵۰۰۰): <b className="text-st-primary">{valid ? `${fa(volKg, 1)} کیلوگرم` : "—"}</b></span>
                  <span>وزن قابل‌محاسبهٔ حامل: <b className="text-st-primary">{billKg != null && !outdated ? `${fa(billKg, 1)} کیلوگرم` : "—"}</b></span></div>
                <div className="flex h-2 w-full overflow-hidden rounded-full bg-st-surface-container-high">{valid && <><div className="h-full bg-st-primary" style={{ width: `${(100 * totalKg) / Math.max(totalKg, volKg)}%` }} /></>}</div>
              </div>
            </div>
            <div className="relative flex flex-col justify-between overflow-hidden rounded-2xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
              <div className="flex items-start justify-between">
                <div className="flex flex-col"><span className="text-st-label-md text-st-outline">مکعب فضایی اشغال‌شده (CBM Volume)</span>
                  <div className="mt-1 flex items-baseline gap-st-space-xs"><span className="text-st-headline-xl font-extrabold text-st-primary">{valid ? fa(cbm, cbm < 1 ? 3 : 2) : "—"}</span><span className="text-st-title-lg text-st-on-surface-variant">متر مکعب</span></div>
                  <span className="text-st-label-md font-semibold text-st-secondary">{valid ? `هر بسته ${fa((L * W * H) / 1e6, 3)} متر مکعب` : "—"}</span></div>
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-st-primary-fixed text-st-primary"><Icon name="view_in_ar" className="text-st-headline-md" /></div>
              </div>
              <div className="mt-st-space-md flex flex-col gap-1.5 pt-st-space-sm">
                <div className="flex items-center justify-between text-st-label-sm text-st-on-surface-variant"><span>وزن مبنای کرایه:</span><span className="font-bold text-st-primary">{valid ? (volKg > totalKg ? "وزن حجمی" : "وزن واقعی") : "—"}</span></div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-st-surface-container-high">{valid && <div className="h-full bg-st-secondary" style={{ width: `${(100 * volKg) / Math.max(totalKg, volKg)}%` }} />}</div>
              </div>
            </div>
          </div>

          <section className={box} aria-label="پیشنهاد ناوگان">
            <div className="flex items-center justify-between pb-st-space-xs"><div className="flex items-center gap-st-space-xs"><Icon name="fire_truck" className="text-st-title-lg text-st-secondary" /><h3 className="text-st-title-lg font-bold text-st-primary">پیشنهاد هوشمند ناوگان و خودروی حمل</h3></div>
              <span className="rounded-full bg-st-surface-container-high px-2.5 py-1 text-st-label-sm text-st-on-surface-variant">به‌زودی</span></div>
            <p className="rounded-xl bg-st-surface-container-low p-st-space-md text-st-body-sm text-st-on-surface-variant">پیشنهاد نوع خودرو و ظرفیت بارگیری به اطلاعات ناوگان نیاز دارد که هنوز در سامانه ثبت نمی‌شود. برای محموله‌های سنگین با پشتیبانی هماهنگ کنید.</p>
          </section>

          <section className={box} aria-live="polite" aria-label="برآورد کرایه">
            <div className="flex flex-col justify-between gap-st-space-xs pb-st-space-xs sm:flex-row sm:items-center">
              <div className="flex items-center gap-st-space-xs"><Icon name="receipt_long" className="text-st-title-lg text-st-secondary" /><h3 className="text-st-title-lg font-bold text-st-primary">برآورد کرایهٔ حمل و هزینه‌های جانبی</h3></div>
              <span className="inline-flex items-center gap-1 rounded-full bg-st-surface-container-high px-2.5 py-1 text-st-label-sm text-st-on-tertiary-container"><span className="h-1.5 w-1.5 rounded-full bg-st-on-tertiary-container" />تخمین — قیمت قطعی هنگام صدور بارنامه</span>
            </div>
            {err && <p role="alert" className="rounded-xl bg-st-error-container/50 p-st-space-sm text-st-body-sm text-st-on-error-container">{err}</p>}
            {!quote ? <div className="flex flex-col items-center gap-st-space-xs rounded-xl bg-st-surface-container-low p-st-space-lg text-center text-st-body-md text-st-on-surface-variant">
              <Icon name="calculate" className="text-[32px] text-st-outline" />{busy ? "در حال استعلام از حامل‌ها…" : "برای دریافت کرایه، مقصد را وارد و «استعلام کرایه» را بزنید."}</div>
              : quote.options.length === 0 ? <p className="rounded-xl bg-st-surface-container-low p-st-space-md text-st-body-md text-st-on-surface-variant">برای این مسیر و شرایط، تعرفهٔ فعالی پیدا نشد.</p>
              : <>
                {outdated && <p className="rounded-xl bg-st-tertiary-fixed/50 p-st-space-sm text-st-body-sm text-st-on-tertiary-fixed-variant">ورودی‌ها تغییر کرده‌اند؛ برای برآورد تازه دوباره استعلام بگیرید.</p>}
                <div className="flex flex-col divide-y divide-st-surface-container-high">{quote.options.map((o, i) => {
                  const sel = o.provider_code === quote.selected.provider_code && o.service_level === quote.selected.service_level;
                  return <div key={`${o.provider_code}-${o.service_level}-${i}`} className="flex items-center justify-between py-st-space-sm">
                    <div className="flex flex-col"><span className="flex items-center gap-st-space-xs text-st-title-md font-semibold text-st-primary">{o.service_name_fa}{sel && <span className="rounded-full bg-st-secondary-fixed px-2 py-0.5 text-st-label-sm text-st-on-secondary-fixed">پیشنهاد</span>}</span>
                      <span className="text-st-label-sm text-st-outline">{LEVELS.find(([v]) => v === o.service_level)?.[1] ?? o.service_level} · تحویل {o.eta_days_max === 0 ? "همان روز" : o.eta_days_min === o.eta_days_max ? `${toPersianNum(o.eta_days_max)} روز کاری` : `${toPersianNum(o.eta_days_min)} تا ${toPersianNum(o.eta_days_max)} روز کاری`}</span></div>
                    <span className="text-st-title-lg font-bold text-st-primary">{formatPrice(o.price_minor)}</span>
                  </div>;})}</div>
                <div className="mt-st-space-xs flex flex-col justify-between gap-st-space-md rounded-xl bg-st-surface-container-high p-st-space-md sm:flex-row sm:items-center">
                  <div className="flex flex-col"><span className="text-st-label-md text-st-outline">کرایهٔ گزینهٔ پیشنهادی ({quote.strategy === "fastest" ? "سریع‌ترین" : "ارزان‌ترین"})</span><span className="text-st-label-sm text-st-secondary">{quote.selected.service_name_fa} · شامل هزینه‌های جانبی تعرفه</span></div>
                  <div className="flex items-baseline gap-2"><span className="text-st-label-md font-bold text-st-primary">جمع کرایه:</span><span className="text-st-headline-lg font-extrabold text-st-primary">{formatPrice(quote.selected.price_minor).replace(" تومان", "")}</span><span className="text-st-title-md font-bold text-st-on-surface-variant">تومان</span></div>
                </div>
              </>}
          </section>

          <div className="flex flex-col items-center justify-between gap-st-space-lg rounded-2xl bg-st-primary p-st-space-lg text-st-on-primary shadow-xl md:flex-row">
            <div className="flex items-center gap-st-space-md">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-st-primary-container text-st-on-primary"><Icon name="verified_user" className="text-st-headline-md" /></div>
              <div className="flex flex-col"><span className="text-st-title-md font-bold text-st-on-primary">استعلام کرایه از حامل‌های فعال</span><span className="text-st-label-sm text-st-on-primary-container">برای خرید عمده یا محمولهٔ ویژه، درخواست استعلام ثبت کنید.</span></div>
            </div>
            <div className="flex w-full flex-wrap items-center justify-end gap-st-space-sm md:w-auto">
              <Link href="/requests/new" className="flex flex-1 items-center justify-center gap-st-space-xs rounded-xl bg-st-surface-container-highest/20 px-5 py-3 text-st-label-lg text-st-on-primary transition-colors hover:bg-st-surface-container-highest/30 md:flex-none"><Icon name="request_quote" className="text-st-title-md" /><span>ثبت درخواست استعلام</span></Link>
              <button type="submit" disabled={busy} className="flex w-full items-center justify-center gap-st-space-xs rounded-xl bg-st-on-tertiary-container px-7 py-3 text-st-label-lg font-bold text-st-on-primary shadow-lg transition-colors hover:bg-st-on-tertiary-fixed-variant disabled:opacity-60 md:w-auto"><Icon name="local_shipping" className="text-st-title-md" /><span>{busy ? "در حال استعلام…" : "استعلام کرایه"}</span></button>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-st-space-sm grid grid-cols-1 gap-st-space-md md:grid-cols-4">
        {[["speed", "مقایسهٔ سرعت و قیمت", "گزینه‌ها بر اساس راهبرد شما مرتب می‌شوند"], ["scale", "محاسبهٔ وزن حجمی", "کرایه بر مبنای وزن واقعی یا حجمی، هر کدام بیشتر"],
          ["payments", "پرداخت در محل و بیمه", "کارمزد و حق بیمه در کرایه لحاظ می‌شود"], ["task_alt", "قیمت قطعی در بارنامه", "این صفحه برآورد است و سفارشی ثبت نمی‌کند"]].map(([i, t, d]) =>
          <div key={t} className="flex items-center gap-st-space-sm rounded-xl bg-st-surface-container-lowest p-st-space-md"><Icon name={i} className="text-st-headline-md text-st-secondary" />
            <div className="flex flex-col"><span className="text-st-title-md font-bold text-st-primary">{t}</span><span className="text-st-body-sm text-st-outline">{d}</span></div></div>)}
      </div>
    </form>
  </div>;
}
