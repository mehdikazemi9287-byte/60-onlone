"use client";
import { positiveInteger, tomanBudgetMinor } from "@/lib/pack-input";
// Budget-driven pack builder over the REAL catalog: options A–D. Totals appear only when every item has a
// verified seller offer; otherwise the option is "quote required" and can be sent as a quote request.
import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { ImageOff } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useGoodImages } from "@/lib/imageQuality";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { UI } from "./PackCard";

type Line = { slug: string; title_fa: string; brand_fa: string; variant_label: string | null; image_url: string | null; quantity: number; unit_price_minor: number | null; required: boolean };
type Option = { key: string; label_fa: string; items: Line[]; item_count: number; food_weight_g: number | null; priced: boolean; price_per_person_minor: number | null;
  total_minor: number | null; within_budget: boolean | null; trimmed_for_budget: string[]; customizable: boolean; note: string | null };
const OCCASIONS: [string, string][] = [["livelihood", "معیشتی"], ["ramadan", "رمضان"], ["nowruz", "نوروز"], ["yalda", "یلدا"], ["hospitality", "پذیرایی سازمانی"], ["office", "تجهیزات اداری"], ["women_day", "روز زن"], ["men_day", "روز مرد"], ["management_gift", "هدایای مدیریتی"], ["employee_gift", "هدایای کارکنان"], ["welfare", "پک رفاهی"]];

export function BudgetBuilder({ onOpen }: { onOpen: (items: { slug: string; title: string; quantity: number; imageUrl: string | null; priceMinor: number | null }[], count: number) => void }) {
  const [people, setPeople] = useState("10"), [budget, setBudget] = useState(""), [occasion, setOccasion] = useState("livelihood");
  const [brands, setBrands] = useState(""), [excluded, setExcluded] = useState("");
  const [res, setRes] = useState<{ options: Option[]; people: number } | null>(null), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [category, setCategory] = useState(""), [categories, setCategories] = useState<{slug:string;name_fa:string}[]>([]);
  useEffect(() => { apiRequest<{items:{slug:string;name_fa:string}[]}>("/storefront/taxonomy").then(r => setCategories(r.items)).catch(() => {}); }, []);
  const list = (v: string) => v.split(/[،,]/).map((x) => x.trim()).filter(Boolean);
  const requestVersion = useRef(0);
  const peopleCount = positiveInteger(people), budgetMinor = tomanBudgetMinor(budget);
  const plannedMinor = peopleCount && budgetMinor ? peopleCount*budgetMinor : null;
  const validBudget = peopleCount !== null && budgetMinor !== null && Number.isSafeInteger(plannedMinor);
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
  const good = useGoodImages(res?.options.flatMap((o) => o.items.map((i) => i.image_url)) ?? []);

  const inp = "h-11 w-full rounded-xl border border-neutral-200 bg-white px-3 text-sm";
  return (
    <section className="space-y-5" dir="rtl" aria-label="پیشنهاد پک بر اساس بودجه">
      <div className="rounded-2xl p-4 md:p-6" style={{ background: UI.warm }}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="grid gap-1 text-xs font-bold">بودجه هر پک (تومان)<input className={inp} inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} /></label>
        <label className="grid gap-1 text-xs font-bold">تعداد پک<input className={inp} type="text" inputMode="numeric" role="spinbutton" aria-valuemin={1} aria-valuemax={100000} aria-valuenow={peopleCount??undefined} value={people} onChange={(e) => setPeople(e.target.value)} /></label>
        <label className="grid gap-1 text-xs font-bold">نوع پک<select className={inp} value={occasion} onChange={(e) => setOccasion(e.target.value)}>{OCCASIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">دسته ترجیحی — اختیاری<select className={inp} value={category} onChange={e => setCategory(e.target.value)}><option value="">متناسب با کاربرد</option>{categories.map(c => <option key={c.slug} value={c.slug}>{c.name_fa}</option>)}</select></label>
        <label className="grid gap-1 text-xs font-bold">برند ترجیحی — اختیاری<input className={inp} value={brands} onChange={(e) => setBrands(e.target.value)} /></label>
        <label className="grid gap-1 text-xs font-bold">موارد ممنوع (نام کالا یا برند) — اختیاری<input className={inp} value={excluded} onChange={(e) => setExcluded(e.target.value)} /></label>
        <button type="button" onClick={run} disabled={busy || !validBudget} className="h-11 self-end rounded-xl text-sm font-bold text-white disabled:opacity-60" style={{ background: UI.ink }}>{busy ? "در حال ساخت…" : "پیشنهاد پک"}</button>
      </div>
      {validBudget && <div className="mt-4"><p className="text-base font-black md:text-xl" style={{ color: UI.ink }}>{toPersianNum(peopleCount!)} × {formatPrice(budgetMinor!)} = {formatPrice(plannedMinor!)}</p><p className="text-xs" style={{ color: UI.muted }}>سقف بودجه شما؛ مبلغ نهایی پس از مشخص شدن قیمت اقلام</p></div>}
      </div>
      {err && <p role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      {res && res.options.length === 0 && <p role="status" className="mt-4 text-sm text-amber-800">با این بودجه و ترجیحات ترکیب قابل ارائه‌ای یافت نشد؛ بودجه یا کاربرد را تغییر دهید.</p>}
      {res && res.options.length > 0 && <h2 className="text-xl font-black md:text-2xl" style={{ color: UI.ink }}>ترکیب پیشنهادی قابل ویرایش</h2>}
      {res && <div className="grid gap-4 lg:grid-cols-2">{res.options.map((o) => (
        <article key={o.key} className="rounded-2xl border bg-white p-4" style={{ borderColor: UI.line }}>
          <div className="flex items-center justify-between gap-2"><h3 className="font-black text-brand-navy">گزینه {o.key}: {o.label_fa}</h3>
            <span className="text-xs text-neutral-500">{toPersianNum(o.item_count)} قلم{o.food_weight_g ? ` · ${toPersianNum(+(o.food_weight_g / 1000).toFixed(1))} کیلوگرم` : ""}</span></div>
          <ul className="my-3 space-y-2">{o.items.map((i) => (
            <li key={i.slug} className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-2 text-sm">
              <span className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg bg-neutral-50">{i.image_url && good?.has(i.image_url) ? <img src={i.image_url} alt="" className="h-full w-full object-contain" /> : <ImageOff className="h-4 w-4 text-neutral-300" />}</span>
              <Link href={`/products/${i.slug}`} className="min-w-0 truncate hover:text-brand-blue">{i.title_fa} · {toPersianNum(i.quantity)} واحد درخواست</Link>
              <span className="text-xs text-neutral-600">{i.unit_price_minor != null ? formatPrice(i.unit_price_minor) : "استعلام"}</span></li>))}</ul>
          {o.priced ? <p className="text-sm">برآورد <b>{formatPrice(o.price_per_person_minor!)}</b> هر پک · جمع {formatPrice(o.total_minor!)} {o.within_budget === false && <span className="text-red-700">(بیش از بودجه)</span>}</p>
            : <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">{o.note}</p>}
          {o.priced&&<p className="mt-2 text-xs leading-6 text-neutral-500">برآورد برای انتخاب ترکیب است؛ قیمت نهایی، موجودی و شرایط مالی در استعلام تأیید می‌شود.</p>}
          {o.trimmed_for_budget.length > 0 && <p className="mt-1 text-xs text-neutral-500">برای رعایت بودجه حذف شد: {o.trimmed_for_budget.join("، ")}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" disabled={!o.items.length} onClick={() => onOpen(o.items.map((i) => ({ slug: i.slug, title: i.title_fa, quantity: i.quantity, imageUrl: i.image_url, priceMinor: i.unit_price_minor })), res.people)}
              className="min-h-11 rounded-xl px-4 disabled:opacity-40 text-sm font-bold text-white" style={{ background: UI.ink }}>انتخاب و ویرایش پک</button>
          </div>
        </article>))}</div>}
    </section>
  );
}
