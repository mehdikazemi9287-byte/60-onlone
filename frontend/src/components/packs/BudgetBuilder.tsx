"use client";
import { positiveInteger, tomanBudgetMinor } from "@/lib/pack-input";
// Budget-driven pack builder over the REAL catalog: options A–D. Totals appear only when every item has a
// verified seller offer; otherwise the option is "quote required" and can be sent as a quote request.
// Restyled 2026-11-17 to the approved Stitch look (62/63); the API contract and logic are unchanged.
import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { ImageOff, AlertCircle } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useGoodImages } from "@/lib/imageQuality";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { btnPrimary, card, input as inp } from "./studio-ui";

type Line = { slug: string; title_fa: string; brand_fa: string; variant_label: string | null; image_url: string | null; quantity: number; unit_price_minor: number | null; required: boolean };
type Option = { key: string; label_fa: string; items: Line[]; item_count: number; food_weight_g: number | null; priced: boolean; price_per_person_minor: number | null;
  total_minor: number | null; within_budget: boolean | null; trimmed_for_budget: string[]; customizable: boolean; note: string | null };
// Primary bulk occasions shown as quick chips. These are livelihood / occasion packs ordered in bulk by
// organizations — not gift boxes.
const PRIMARY_OCCASIONS = ["livelihood", "ramadan", "nowruz", "yalda", "religious", "charity", "cultural", "stationery"];
const COUNT_PRESETS = [50, 100, 250, 500, 1000];
const BUDGET_PRESETS_TOMAN = [1000000, 2000000, 3000000, 5000000];
const OCCASIONS: [string, string][] = [["livelihood", "معیشتی"], ["ramadan", "رمضان"], ["nowruz", "نوروز"], ["yalda", "یلدا"], ["religious", "مذهبی و نذری"], ["charity", "خیریه"], ["cultural", "فرهنگی (کتاب)"], ["stationery", "لوازم‌التحریر"], ["hospitality", "پذیرایی سازمانی"], ["office", "تجهیزات اداری"], ["women_day", "روز زن"], ["men_day", "روز مرد"], ["management_gift", "هدایای مدیریتی"], ["employee_gift", "هدایای کارکنان"], ["welfare", "پک رفاهی"]];
const OCCASION_KEYS = new Set(OCCASIONS.map(([k]) => k));

/** Prefill from the hero 60AI input; `nonce` changes on every submit so the same text can be re-run. */
export type BudgetPreset = { nonce: number; people: number | null; budgetToman: number | null; occasion: string | null };

const chip = (on: boolean) => `min-h-9 rounded-full border px-3.5 text-xs font-bold transition ${on ? "border-[#112D46] bg-[#112D46] text-white" : "border-[#E5E7EB] bg-white text-[#374151] hover:border-[#034EA2] hover:text-[#034EA2]"}`;

export function BudgetBuilder({ onOpen, preset }: { onOpen: (items: { slug: string; title: string; quantity: number; imageUrl: string | null; priceMinor: number | null }[], count: number) => void; preset?: BudgetPreset | null }) {
  const [people, setPeople] = useState("10"), [budget, setBudget] = useState(""), [occasion, setOccasion] = useState("livelihood");
  const [brands, setBrands] = useState(""), [excluded, setExcluded] = useState("");
  const [res, setRes] = useState<{ options: Option[]; people: number } | null>(null), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [category, setCategory] = useState(""), [categories, setCategories] = useState<{slug:string;name_fa:string}[]>([]);
  const [autoRun, setAutoRun] = useState(0);
  useEffect(() => { apiRequest<{items:{slug:string;name_fa:string}[]}>("/storefront/taxonomy").then(r => setCategories(r.items)).catch(() => {}); }, []);
  const list = (v: string) => v.split(/[،,]/).map((x) => x.trim()).filter(Boolean);
  const requestVersion = useRef(0);
  const peopleCount = positiveInteger(people), budgetMinor = tomanBudgetMinor(budget);
  const plannedMinor = peopleCount && budgetMinor ? peopleCount*budgetMinor : null;
  const validBudget = peopleCount !== null && budgetMinor !== null && Number.isSafeInteger(plannedMinor);
  useEffect(() => {
    if (!preset) return;
    if (preset.people) setPeople(String(preset.people));
    if (preset.budgetToman) setBudget(String(preset.budgetToman));
    if (preset.occasion && OCCASION_KEYS.has(preset.occasion)) setOccasion(preset.occasion);
    if (preset.budgetToman) setAutoRun(preset.nonce);
  }, [preset]);
  useEffect(()=>{requestVersion.current++;setRes(null);setErr("");setBusy(false);},[people,budget,occasion,brands,excluded,category]);
  const run = async () => {
    if(!validBudget){setErr("تعداد پک و بودجه را با عدد صحیح معتبر وارد کنید.");return;}
    const version=++requestVersion.current;
    setBusy(true); setErr(""); setRes(null);
    try {
      const result = await apiRequest<{options: Option[]; people: number}>("/storefront/pack-builder", { method: "POST", body: JSON.stringify({ people: peopleCount,
        budget_per_person_minor: budgetMinor, occasion, ...(category ? {categories:[category]} : {}), preferred_brands: list(brands), excluded: list(excluded) }) });
      if(version===requestVersion.current)setRes(result);
    } catch (e) { if(version===requestVersion.current)setErr(e instanceof Error ? e.message : "ساخت پیشنهاد ناموفق بود"); } finally { if(version===requestVersion.current)setBusy(false); }
  };
  // Runs after the reset effect above (declaration order), so the prefilled values are used.
  useEffect(() => { if (autoRun) { setAutoRun(0); void run(); } }, [autoRun]); // eslint-disable-line react-hooks/exhaustive-deps
  const good = useGoodImages(res?.options.flatMap((o) => o.items.map((i) => i.image_url)) ?? []);

  const label = "grid gap-1.5 text-xs font-bold text-[#374151]";
  return (
    <section className="space-y-5" dir="rtl" aria-label="پیشنهاد پک بر اساس بودجه">
      <div className={`${card} p-4 md:p-6`}>
        <div className="space-y-4">
          <div><p className="mb-2 text-xs font-bold text-[#6B7280]">نوع پک</p>
            <div role="group" aria-label="نوع پک" className="flex flex-wrap gap-2">{OCCASIONS.filter(([k]) => PRIMARY_OCCASIONS.includes(k)).map(([k, v]) => <button key={k} type="button" aria-pressed={occasion === k} onClick={() => setOccasion(k)} className={chip(occasion === k)}>{v}</button>)}</div></div>
          <div className="grid gap-4 md:grid-cols-2">
            <div><p className="mb-2 text-xs font-bold text-[#6B7280]">تعداد پک</p>
              <div className="flex flex-wrap gap-2">{COUNT_PRESETS.map(n => <button key={n} type="button" aria-pressed={peopleCount === n} onClick={() => setPeople(String(n))} className={chip(peopleCount === n)}>{toPersianNum(n)}</button>)}</div></div>
            <div><p className="mb-2 text-xs font-bold text-[#6B7280]">بودجه هر پک</p>
              <div className="flex flex-wrap gap-2">{BUDGET_PRESETS_TOMAN.map(t => <button key={t} type="button" aria-pressed={budgetMinor === t * 10} onClick={() => setBudget(String(t))} className={chip(budgetMinor === t * 10)}>{formatPrice(t * 10)}</button>)}</div></div>
          </div>
        </div>
        <div className="mt-5 grid gap-3 border-t border-[#F3F4F6] pt-5 sm:grid-cols-2 lg:grid-cols-3">
          <label className={label}>بودجه هر پک (تومان)<input className={inp} inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} /></label>
          <label className={label}>تعداد پک<input className={inp} type="text" inputMode="numeric" role="spinbutton" aria-valuemin={1} aria-valuemax={100000} aria-valuenow={peopleCount??undefined} value={people} onChange={(e) => setPeople(e.target.value)} /></label>
          <label className={label}>نوع پک<select className={inp} value={occasion} onChange={(e) => setOccasion(e.target.value)}>{OCCASIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={label}>دسته ترجیحی — اختیاری<select className={inp} value={category} onChange={e => setCategory(e.target.value)}><option value="">متناسب با کاربرد</option>{categories.map(c => <option key={c.slug} value={c.slug}>{c.name_fa}</option>)}</select></label>
          <label className={label}>برند ترجیحی — اختیاری<input className={inp} value={brands} onChange={(e) => setBrands(e.target.value)} /></label>
          <label className={label}>موارد ممنوع (نام کالا یا برند) — اختیاری<input className={inp} value={excluded} onChange={(e) => setExcluded(e.target.value)} /></label>
        </div>
        <div className="mt-5 flex flex-col gap-3 border-t border-[#F3F4F6] pt-5 sm:flex-row sm:items-center sm:justify-between">
          {validBudget ? <div><p className="text-base font-extrabold text-[#112D46] md:text-lg">{toPersianNum(peopleCount!)} × {formatPrice(budgetMinor!)} = {formatPrice(plannedMinor!)}</p><p className="text-[11px] text-[#6B7280]">سقف بودجه شما؛ مبلغ نهایی پس از مشخص شدن قیمت اقلام</p></div>
            : <p className="text-xs text-[#6B7280]">تعداد پک و بودجه هر پک را مشخص کنید.</p>}
          <button type="button" onClick={run} disabled={busy || !validBudget} className={`${btnPrimary} sm:min-w-44`}>{busy ? "در حال ساخت…" : "پیشنهاد پک"}</button>
        </div>
      </div>
      {err && <p role="alert" className="flex items-start gap-2 rounded-xl border border-red-100 bg-red-50 p-3 text-sm text-red-800"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />{err}</p>}
      {busy && <p role="status" className="py-6 text-center text-sm text-[#6B7280]">در حال ساخت ترکیب از کاتالوگ…</p>}
      {res && res.options.length === 0 && <p role="status" className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-sm text-amber-800">با این بودجه و ترجیحات ترکیب قابل ارائه‌ای یافت نشد؛ بودجه یا کاربرد را تغییر دهید.</p>}
      {res && res.options.length > 0 && <div><h2 className="text-base font-extrabold text-[#112D46] md:text-lg">ترکیب پیشنهادی قابل ویرایش</h2><p className="mt-1 text-xs text-[#6B7280]">یک گزینه را انتخاب و در مرحله بعد ویرایش کنید.</p></div>}
      {res && <div className="grid gap-4 lg:grid-cols-2">{res.options.map((o) => (
        <article key={o.key} className={`${card} flex flex-col p-4 md:p-5`}>
          <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-extrabold text-[#112D46]">گزینه {o.key}: {o.label_fa}</h3>
            <span className="text-[11px] text-[#6B7280]">{toPersianNum(o.item_count)} قلم{o.food_weight_g ? ` · ${toPersianNum(+(o.food_weight_g / 1000).toFixed(1))} کیلوگرم` : ""}</span></div>
          <ul className="my-3 divide-y divide-[#F3F4F6]">{o.items.map((i) => (
            <li key={i.slug} className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-2 py-2 text-sm">
              <span className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg border border-[#F3F4F6] bg-white">{i.image_url && good?.has(i.image_url) ? // eslint-disable-next-line @next/next/no-img-element
<img src={i.image_url} alt="" className="h-full w-full object-contain" /> : <ImageOff className="h-4 w-4 text-[#D1D5DB]" />}</span>
              <Link href={`/products/${i.slug}`} className="min-w-0 truncate text-xs text-[#111827] hover:text-[#034EA2] md:text-sm">{i.title_fa} · {toPersianNum(i.quantity)} واحد</Link>
              <span className="text-[11px] text-[#4B5563]">{i.unit_price_minor != null ? formatPrice(i.unit_price_minor) : "استعلام"}</span></li>))}</ul>
          <div className="mt-auto space-y-2">
            {o.priced ? <p className="text-sm text-[#111827]">برآورد <b>{formatPrice(o.price_per_person_minor!)}</b> هر پک · جمع {formatPrice(o.total_minor!)} {o.within_budget === false && <span className="text-red-700">(بیش از بودجه)</span>}</p>
              : <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">{o.note}</p>}
            {o.priced && <p className="text-[11px] leading-5 text-[#6B7280]">برآورد برای انتخاب ترکیب است؛ قیمت نهایی، موجودی و شرایط مالی در استعلام تأیید می‌شود.</p>}
            {o.trimmed_for_budget.length > 0 && <p className="text-[11px] text-[#6B7280]">برای رعایت بودجه حذف شد: {o.trimmed_for_budget.join("، ")}</p>}
            <button type="button" disabled={!o.items.length} onClick={() => onOpen(o.items.map((i) => ({ slug: i.slug, title: i.title_fa, quantity: i.quantity, imageUrl: i.image_url, priceMinor: i.unit_price_minor })), res.people)}
              className={`${btnPrimary} w-full sm:w-auto`}>انتخاب و ویرایش پک</button>
          </div>
        </article>))}</div>}
    </section>
  );
}
