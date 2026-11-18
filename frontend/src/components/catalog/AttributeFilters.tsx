"use client";
// Listing filters — Stitch 23 «فیلترهای پیشرفته» sidebar (desktop) and Stitch 14 bottom sheet (mobile).
// Typed attribute facets (attr.<code>=a,b | lo..hi) + brand + price + stock/official/purchasable toggles.
// URL is the single source of truth; every option and count comes from the storefront facets.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { AttributeFacet, Facets } from "@/lib/storefront";
import { latinDigits } from "@/lib/shops";
import { cn, toPersianNum } from "@/lib/utils";

/** Toman input (Persian/Latin digits, separators) → Rial minor string; "" when empty/invalid. */
export const tomanToMinor = (v: string) => {
  const n = Number(latinDigits(v).replace(/[,،٬\s]/g, ""));
  return v.trim() && Number.isFinite(n) && n >= 0 ? String(Math.round(n * 10)) : "";
};
const cleanNum = (v: string) => latinDigits(v).replace(/[٫]/g, ".").replace(/[,،٬\s]/g, "");
const NUMERIC = new Set(["number", "integer", "measure"]);
const tomanStr = (minor: number) => Math.round(minor / 10).toLocaleString("fa-IR");
const Icon = ({ name, className, fill }: { name: string; className?: string; fill?: boolean }) =>
  <span aria-hidden className={cn("material-symbols-outlined", fill && "icon-fill", className)}>{name}</span>;

export type FilterState = {
  attrs: Record<string, string[]>; // code → tokens (option codes, "1"/"0", numbers or "lo..hi")
  brand: string; minPrice: string; maxPrice: string; inStock: boolean; official: boolean; purchasable: boolean;
};
export type CategoryLink = { slug: string; name: string; count: number; active: boolean; href: string };
export const SORTS: { value: string; label: string }[] = [
  { value: "relevance", label: "پیشنهادی" }, { value: "newest", label: "جدیدترین" },
  { value: "price_asc", label: "ارزان‌ترین" }, { value: "price_desc", label: "گران‌ترین" }, { value: "name", label: "نام کالا" },
];

/** Read `attr.*` keys from the URL. */
export function readAttrParams(params: URLSearchParams): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  params.forEach((v, k) => {
    if (k.startsWith("attr.") && k.length > 5) {
      const toks = latinDigits(v).split(",").map((x) => x.trim()).filter(Boolean);
      if (toks.length) out[k.slice(5)] = [...(out[k.slice(5)] ?? []), ...toks];
    }
  });
  return out;
}

const rangeLabel = (tok: string, unit: string | null) => {
  const [lo, hi] = tok.split("..");
  const u = unit ? ` ${unit}` : "";
  if (lo && hi) return `${toPersianNum(lo)} تا ${toPersianNum(hi)}${u}`;
  return lo ? `حداقل ${toPersianNum(lo)}${u}` : `حداکثر ${toPersianNum(hi)}${u}`;
};

type Change = (values: Record<string, string>) => void;

export const clearAllValues = (state: FilterState) =>
  ({ ...Object.fromEntries(Object.keys(state.attrs).map((c) => ["attr." + c, ""])), brand: "", min_price: "", max_price: "", in_stock: "", official: "", availability: "", page: "1" });
export const activeCount = (s: FilterState) =>
  Object.values(s.attrs).reduce((n, t) => n + t.length, 0) + [s.brand, s.minPrice || s.maxPrice, s.inStock, s.official, s.purchasable].filter(Boolean).length;

/** Stitch checkbox: 20px rounded square, filled primary-container with a check when on. */
function Check({ on, label, onChange, count }: { on: boolean; label: string; onChange: (v: boolean) => void; count?: number }) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-st-space-sm py-1">
      <input type="checkbox" className="peer sr-only" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded peer-focus-visible:ring-2 peer-focus-visible:ring-st-secondary",
        on ? "bg-st-primary-container text-st-on-primary" : "bg-st-surface-container-high text-transparent")}><Icon name="check" className="text-[16px]" /></span>
      <span className="min-w-0 flex-1 text-st-on-surface">{label}</span>
      {count != null && <span className="text-st-outline">{toPersianNum(count)}</span>}
    </label>
  );
}

function NumberRange({ f, tokens, onApply }: { f: AttributeFacet; tokens: string[]; onApply: (tok: string) => void }) {
  const cur = tokens.find((t) => t.includes("..")) ?? "";
  const [lo, setLo] = useState(cur.split("..")[0] ?? ""), [hi, setHi] = useState(cur.split("..")[1] ?? "");
  const [err, setErr] = useState("");
  useEffect(() => { setLo(cur.split("..")[0] ?? ""); setHi(cur.split("..")[1] ?? ""); }, [cur]);
  const id = useId();
  const box = "h-9 w-full min-w-0 rounded-lg border-0 bg-st-surface-container-low px-2 text-st-on-surface outline-none";
  return (
    <form className="mt-2 grid gap-1" onSubmit={(e) => {
      e.preventDefault();
      const a = cleanNum(lo), b = cleanNum(hi);
      if ((a && !Number.isFinite(Number(a))) || (b && !Number.isFinite(Number(b)))) return setErr("فقط عدد وارد کنید");
      if (a && b && Number(a) > Number(b)) return setErr("کمینه از بیشینه بزرگ‌تر است");
      setErr(""); onApply(a || b ? `${a}..${b}` : "");
    }}>
      <div className="flex items-end gap-st-space-xs">
        <label className="grid min-w-0 flex-1 gap-0.5 text-[10px] text-st-outline" htmlFor={id + "lo"}>از:
          <input id={id + "lo"} inputMode="decimal" value={lo} onChange={(e) => setLo(e.target.value)} placeholder={f.min ? toPersianNum(f.min) : ""} className={box} /></label>
        <label className="grid min-w-0 flex-1 gap-0.5 text-[10px] text-st-outline" htmlFor={id + "hi"}>تا:
          <input id={id + "hi"} inputMode="decimal" value={hi} onChange={(e) => setHi(e.target.value)} placeholder={f.max ? toPersianNum(f.max) : ""} className={box} /></label>
        <button className="h-9 shrink-0 rounded-lg bg-st-surface-container px-3 text-st-label-md text-st-primary">اعمال</button>
      </div>
      {f.unit && <span className="text-[11px] text-st-outline">واحد: {f.unit}</span>}
      {err && <span role="alert" className="text-[11px] text-st-error">{err}</span>}
    </form>
  );
}

const Divider = () => <div className="h-px w-full bg-st-surface-container" />;

function FilterBody({ facets, attrFacets, state, change, loading, total, categories, priceFormId, sort, onSort }: {
  facets: Facets | null; attrFacets: AttributeFacet[]; state: FilterState; change: Change; loading: boolean; total: number;
  categories?: CategoryLink[]; priceFormId: string; sort?: string; onSort?: (v: string) => void;
}) {
  const [pFrom, setPFrom] = useState(""), [pTo, setPTo] = useState("");
  const [brandQ, setBrandQ] = useState("");
  const [catOpen, setCatOpen] = useState(true);
  const setAttr = (code: string, toks: string[]) => change({ ["attr." + code]: toks.join(","), page: "1" });
  const toggle = (code: string, v: string) => {
    const cur = state.attrs[code] ?? [];
    setAttr(code, cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]);
  };
  const brands = useMemo(() => (facets?.brands ?? []).filter((b) => !brandQ || b.value.includes(brandQ)), [facets, brandQ]);
  const pr = facets?.price_range;
  // Slider visual = the applied range relative to the facet's real min/max (no invented bounds).
  const lo = state.minPrice ? Number(state.minPrice) : pr?.min, hi = state.maxPrice ? Number(state.maxPrice) : pr?.max;
  const span = pr && pr.max > pr.min ? pr.max - pr.min : 0;
  const pos = (v?: number) => (span && v != null ? Math.min(100, Math.max(0, ((v - pr!.min) / span) * 100)) : 0);
  const head = "font-bold text-st-primary";
  return (
    <div className="flex min-w-0 flex-col gap-st-space-lg">
      {onSort && (
        <div className="flex flex-col gap-st-space-xs">
          <span className="text-st-title-md text-st-primary-container">مرتب‌سازی نتایج بر اساس</span>
          <div className="mt-1 grid grid-cols-2 gap-st-space-xs">
            {SORTS.map((s) => <button key={s.value} type="button" onClick={() => onSort(s.value)} aria-pressed={sort === s.value}
              className={cn("rounded-xl px-3 py-2.5 text-center text-st-label-md transition-all", sort === s.value ? "bg-st-primary-container text-st-on-primary" : "bg-st-surface-container-low text-st-on-surface hover:bg-st-surface-container")}>{s.label}</button>)}
          </div>
        </div>
      )}
      {/* Purchase mode: the listing is the retail storefront; organizational buying lives in its own flow. */}
      <div className="flex flex-col gap-st-space-xs">
        <span className="font-bold text-st-on-surface-variant">حالت خرید و استعلام</span>
        <div className="grid grid-cols-2 gap-1 rounded-xl bg-st-surface-container-low p-1">
          <span aria-current="true" className="rounded-lg bg-st-primary-container px-st-space-sm py-st-space-xs text-center font-bold text-st-on-primary shadow-sm">خرید تک / خانوار</span>
          <Link href="/org" className="rounded-lg px-st-space-sm py-st-space-xs text-center text-st-on-surface-variant transition-all hover:text-st-primary">سازمانی با فاکتور</Link>
        </div>
      </div>
      {categories && categories.length > 0 && <>
        <Divider />
        <div className="flex flex-col gap-st-space-sm">
          <button type="button" onClick={() => setCatOpen((o) => !o)} aria-expanded={catOpen} className="flex items-center justify-between">
            <span className={head}>دسته‌بندی تخصصی</span>
            <Icon name={catOpen ? "expand_less" : "expand_more"} className="text-[18px] text-st-outline" />
          </button>
          {catOpen && <div className="flex flex-col gap-1 pr-st-space-xs text-st-on-surface-variant">
            {categories.map((c) => (
              <Link key={c.slug} href={c.href} aria-current={c.active ? "page" : undefined}
                className={cn("flex items-center justify-between rounded-lg px-st-space-sm py-1.5 transition-colors", c.active ? "bg-st-surface-container-low font-bold text-st-primary" : "hover:bg-st-surface-container-low")}>
                <span className="flex items-center gap-2"><span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", c.active ? "bg-st-secondary" : "bg-st-outline-variant")} />{c.name}</span>
                <span className="text-st-outline">{toPersianNum(c.count)}</span>
              </Link>))}
          </div>}
        </div>
      </>}

      {(pr || state.minPrice || state.maxPrice) && <>
        <Divider />
        <form id={priceFormId} className="flex flex-col gap-st-space-md" onSubmit={(e) => { e.preventDefault(); change({ min_price: tomanToMinor(pFrom), max_price: tomanToMinor(pTo), page: "1" }); }}>
          <div className="flex items-center justify-between">
            <span className={head}>محدوده بودجه هر واحد</span>
            <span className="text-st-secondary">تومان</span>
          </div>
          {span > 0 && <div className="relative w-full py-2" aria-hidden>
            <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-st-surface-container-high">
              <div className="absolute h-full bg-st-secondary" style={{ right: pos(lo) + "%", left: 100 - pos(hi) + "%" }} />
            </div>
            <div className="absolute top-1 h-4 w-4 translate-x-1/2 rounded-full bg-st-primary-container shadow" style={{ right: pos(lo) + "%" }} />
            <div className="absolute top-1 h-4 w-4 translate-x-1/2 rounded-full bg-st-primary-container shadow" style={{ right: pos(hi) + "%" }} />
          </div>}
          <div className="flex items-center justify-between gap-st-space-xs text-st-on-surface">
            <label className="w-1/2 rounded-lg bg-st-surface-container-low px-2 py-1.5 text-right">
              <span className="block text-[10px] text-st-outline">از:</span>
              <input inputMode="numeric" value={pFrom} onChange={(e) => setPFrom(e.target.value)} aria-label="حداقل قیمت (تومان)"
                placeholder={pr ? tomanStr(state.minPrice ? Number(state.minPrice) : pr.min) : ""} className="w-full border-0 bg-transparent p-0 font-bold outline-none placeholder:text-st-on-surface" />
            </label>
            <label className="w-1/2 rounded-lg bg-st-surface-container-low px-2 py-1.5 text-right">
              <span className="block text-[10px] text-st-outline">تا:</span>
              <input inputMode="numeric" value={pTo} onChange={(e) => setPTo(e.target.value)} aria-label="حداکثر قیمت (تومان)"
                placeholder={pr ? tomanStr(state.maxPrice ? Number(state.maxPrice) : pr.max) : ""} className="w-full border-0 bg-transparent p-0 font-bold outline-none placeholder:text-st-on-surface" />
            </label>
          </div>
          <p className="-mt-2 text-[11px] text-st-outline">فقط کالاهای دارای قیمت تأییدشده.</p>
        </form>
      </>}

      <Divider />
      <div className="flex flex-col gap-st-space-sm">
        <span className={head}>وضعیت و شرایط خرید</span>
        <div className="flex flex-col gap-st-space-xs">
          <Check on={state.inStock} label="فقط کالاهای موجود" onChange={(v) => change({ in_stock: v ? "1" : "", page: "1" })} />
          <Check on={state.purchasable} label="فقط قابل خرید آنلاین" onChange={(v) => change({ availability: v ? "purchasable" : "", page: "1" })} />
          <Check on={state.official} label="فروشندهٔ رسمی برند" onChange={(v) => change({ official: v ? "1" : "", page: "1" })} />
        </div>
      </div>

      {facets && (facets.brands.length > 0 || state.brand) && <>
        <Divider />
        <div className="flex flex-col gap-st-space-sm">
          <span className={head}>تأمین‌کننده / برند معتبر</span>
          {facets.brands.length > 6 && <div className="relative w-full">
            <input value={brandQ} onChange={(e) => setBrandQ(e.target.value)} aria-label="جستجوی برند" placeholder="جستجوی برند..."
              className="h-9 w-full rounded-lg border-0 bg-st-surface-container-low px-st-space-sm pr-8 text-st-on-surface outline-none placeholder:text-st-outline" />
            <Icon name="search" className="absolute right-2 top-2 text-[16px] text-st-outline" />
          </div>}
          <div className="flex max-h-36 flex-col gap-1 overflow-y-auto pr-1 text-st-body-sm">
            {brands.map((b) => (
              <label key={b.value} className="flex cursor-pointer items-center justify-between py-1 text-st-on-surface">
                <span className="flex items-center gap-2">
                  <input type="checkbox" className="h-4 w-4 rounded accent-st-primary" checked={state.brand === b.value}
                    onChange={(e) => change({ brand: e.target.checked ? b.value : "", page: "1" })} />
                  <span>{b.value}</span>
                </span>
                <span className="text-st-outline">{toPersianNum(b.count)}</span>
              </label>))}
          </div>
        </div>
      </>}

      {loading && !attrFacets.length && <p className="text-st-body-sm text-st-outline" aria-live="polite">در حال دریافت فیلترها…</p>}
      {attrFacets.map((f) => {
        const toks = state.attrs[f.code] ?? [];
        return (
          <div key={f.code} className="flex flex-col gap-st-space-sm">
            <Divider />
            <span className={head}>{f.name_fa}</span>
            <div className="flex max-h-56 flex-col gap-st-space-xs overflow-y-auto">
              {f.values.map((v) => <Check key={v.value} on={toks.includes(v.value)} label={toPersianNum(v.label_fa)} count={v.count} onChange={() => toggle(f.code, v.value)} />)}
            </div>
            {NUMERIC.has(f.data_type) && <NumberRange f={f} tokens={toks} onApply={(tok) => setAttr(f.code, [...toks.filter((t) => !t.includes("..")), ...(tok ? [tok] : [])])} />}
          </div>
        );
      })}
      {!onSort && (
        <button type="submit" form={pr || state.minPrice || state.maxPrice ? priceFormId : undefined}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-st-primary font-bold text-st-on-primary shadow-sm transition-colors hover:bg-st-secondary">
          <Icon name="done_all" className="text-[18px]" />
          <span>{loading ? "در حال به‌روزرسانی…" : `اعمال فیلترها (${toPersianNum(total)} کالا)`}</span>
        </button>
      )}
    </div>
  );
}

/** Active-filter chips (Stitch 23 «فیلترهای فعال»); each removes one token. */
export function ActiveFilterChips({ attrFacets, state, change }: { attrFacets: AttributeFacet[]; state: FilterState; change: Change }) {
  const chips: { key: string; label: string; remove: () => void }[] = [];
  const byCode = new Map(attrFacets.map((f) => [f.code, f]));
  for (const [code, toks] of Object.entries(state.attrs)) {
    const f = byCode.get(code);
    for (const t of toks) {
      const lbl = t.includes("..") ? rangeLabel(t, f?.unit ?? null) : toPersianNum(f?.values.find((v) => v.value === t)?.label_fa ?? t);
      chips.push({ key: code + t, label: `${f?.name_fa ?? code}: ${lbl}`, remove: () => change({ ["attr." + code]: toks.filter((x) => x !== t).join(","), page: "1" }) });
    }
  }
  if (state.brand) chips.push({ key: "brand", label: `برند: ${state.brand}`, remove: () => change({ brand: "", page: "1" }) });
  if (state.minPrice || state.maxPrice) chips.push({ key: "price", label: "بازهٔ قیمت", remove: () => change({ min_price: "", max_price: "", page: "1" }) });
  if (state.inStock) chips.push({ key: "stock", label: "فقط موجود", remove: () => change({ in_stock: "", page: "1" }) });
  if (state.official) chips.push({ key: "official", label: "فروشندهٔ رسمی", remove: () => change({ official: "", page: "1" }) });
  if (state.purchasable) chips.push({ key: "avail", label: "قابل خرید آنلاین", remove: () => change({ availability: "", page: "1" }) });
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-st-space-xs pt-st-space-xs" aria-label="فیلترهای فعال">
      <span className="text-st-on-surface-variant">فیلترهای فعال:</span>
      {chips.map((c) => (
        <span key={c.key} className="inline-flex max-w-full items-center gap-1 rounded-full bg-st-surface-container px-st-space-sm py-1 text-st-on-surface">
          <span className="truncate">{c.label}</span>
          <button type="button" onClick={c.remove} aria-label={`حذف فیلتر ${c.label}`} className="flex hover:text-st-error"><Icon name="close" className="text-[14px]" /></button>
        </span>
      ))}
      <button type="button" onClick={() => change(clearAllValues(state))} className="mr-st-space-xs text-st-secondary hover:underline">پاکسازی همه</button>
    </div>
  );
}

/** Desktop sidebar card (Stitch 23). */
export function FilterSidebar(props: { facets: Facets | null; attrFacets: AttributeFacet[]; state: FilterState; change: Change; loading: boolean; total: number; categories?: CategoryLink[] }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-st-space-lg rounded-xl bg-st-surface-container-lowest p-st-space-lg shadow-sm">
      <div className="flex items-center justify-between pb-st-space-sm">
        <div className="flex items-center gap-st-space-xs">
          <Icon name="tune" className="text-[20px] text-st-primary" />
          <h2 className="font-bold text-st-primary">فیلترهای پیشرفته</h2>
        </div>
        {activeCount(props.state) > 0 && <button type="button" onClick={() => props.change(clearAllValues(props.state))} className="text-st-on-tertiary-container transition-all hover:underline">حذف همه فیلترها</button>}
      </div>
      <FilterBody {...props} priceFormId={id + "price"} />
    </div>
  );
}

/** Mobile bottom sheet (Stitch 14): sort + filters, «نمایش N کالا» footer. */
export function FilterSheet(props: { open: boolean; onClose: () => void; facets: Facets | null; attrFacets: AttributeFacet[]; state: FilterState; change: Change;
  loading: boolean; total: number; sort: string; onSort: (v: string) => void; categories?: CategoryLink[] }) {
  const { open, onClose } = props;
  const sheet = useRef<HTMLDivElement>(null);
  const titleId = useId(), formId = useId();
  useEffect(() => {
    if (!open) return;
    const prevFocus = document.activeElement as HTMLElement | null;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sheet.current?.querySelector<HTMLElement>("button, input")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !sheet.current) return;
      const els = [...sheet.current.querySelectorAll<HTMLElement>("button, input, select, a[href]")].filter((x) => !x.hasAttribute("disabled"));
      if (!els.length) return;
      const first = els[0], last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prev; document.removeEventListener("keydown", onKey); prevFocus?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] md:hidden" dir="rtl">
      <div className="absolute inset-0 bg-st-primary/40 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div ref={sheet} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-2xl bg-st-surface-container-lowest text-st-body-md shadow-xl">
        <div className="flex justify-center pt-2"><span className="h-1 w-10 rounded-full bg-st-outline-variant" /></div>
        <div className="flex items-center justify-between px-st-space-md py-st-space-sm">
          <h2 id={titleId} className="text-st-title-lg text-st-primary-container">فیلتر و مرتب‌سازی</h2>
          <button type="button" onClick={onClose} aria-label="بستن فیلترها" className="flex h-8 w-8 items-center justify-center rounded-full text-st-on-surface-variant hover:bg-st-surface-container"><Icon name="close" className="text-[20px]" /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-st-space-md py-st-space-sm">
          <FilterBody {...props} priceFormId={formId} />
        </div>
        <div className="flex gap-st-space-sm border-t border-st-surface-container p-st-space-md">
          <button type="button" onClick={() => props.change(clearAllValues(props.state))} className="h-12 rounded-xl bg-st-surface-container-low px-st-space-md text-st-label-lg text-st-on-surface">حذف همه</button>
          <button type="button" onClick={onClose} className="h-12 flex-1 rounded-xl bg-st-primary-container text-st-label-lg text-st-on-primary">
            {props.loading ? "در حال به‌روزرسانی…" : `نمایش ${toPersianNum(props.total)} کالا`}
          </button>
        </div>
      </div>
    </div>
  );
}
