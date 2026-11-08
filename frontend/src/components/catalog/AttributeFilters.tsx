"use client";
// Phase 6 listing filters: typed attribute facets (attr.<code>=a,b | lo..hi) + brand + price + stock/official toggles.
// Same body renders as a side panel (md+) and as a bottom-sheet dialog on mobile. URL is the single source of truth.
import { useEffect, useId, useRef, useState } from "react";
import type { AttributeFacet, Facets } from "@/lib/storefront";
import { latinDigits } from "@/lib/shops";
import { formatPrice, toPersianNum } from "@/lib/utils";

/** Toman input (Persian/Latin digits, separators) → Rial minor string; "" when empty/invalid. */
export const tomanToMinor = (v: string) => {
  const n = Number(latinDigits(v).replace(/[,،٬\s]/g, ""));
  return v.trim() && Number.isFinite(n) && n >= 0 ? String(Math.round(n * 10)) : "";
};
const cleanNum = (v: string) => latinDigits(v).replace(/[٫]/g, ".").replace(/[,،٬\s]/g, "");
const NUMERIC = new Set(["number", "integer", "measure"]);

export type FilterState = {
  attrs: Record<string, string[]>; // code → tokens (option codes, "1"/"0", numbers or "lo..hi")
  brand: string; minPrice: string; maxPrice: string; inStock: boolean; official: boolean; purchasable: boolean;
};

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

function NumberRange({ f, tokens, onApply }: { f: AttributeFacet; tokens: string[]; onApply: (tok: string) => void }) {
  const cur = tokens.find((t) => t.includes("..")) ?? "";
  const [lo, setLo] = useState(cur.split("..")[0] ?? ""), [hi, setHi] = useState(cur.split("..")[1] ?? "");
  const [err, setErr] = useState("");
  useEffect(() => { setLo(cur.split("..")[0] ?? ""); setHi(cur.split("..")[1] ?? ""); }, [cur]);
  const id = useId();
  return (
    <form className="mt-2 grid gap-1" onSubmit={(e) => {
      e.preventDefault();
      const a = cleanNum(lo), b = cleanNum(hi);
      if ((a && !Number.isFinite(Number(a))) || (b && !Number.isFinite(Number(b)))) return setErr("فقط عدد وارد کنید");
      if (a && b && Number(a) > Number(b)) return setErr("کمینه از بیشینه بزرگ‌تر است");
      setErr(""); onApply(a || b ? `${a}..${b}` : "");
    }}>
      <div className="flex items-end gap-2">
        <label className="grid min-w-0 flex-1 gap-1 text-[11px] font-bold text-neutral-600" htmlFor={id + "lo"}>از
          <input id={id + "lo"} inputMode="decimal" value={lo} onChange={(e) => setLo(e.target.value)} placeholder={f.min ? toPersianNum(f.min) : ""}
            className="h-10 w-full min-w-0 rounded-lg border px-2 text-sm" /></label>
        <label className="grid min-w-0 flex-1 gap-1 text-[11px] font-bold text-neutral-600" htmlFor={id + "hi"}>تا
          <input id={id + "hi"} inputMode="decimal" value={hi} onChange={(e) => setHi(e.target.value)} placeholder={f.max ? toPersianNum(f.max) : ""}
            className="h-10 w-full min-w-0 rounded-lg border px-2 text-sm" /></label>
        <button className="h-10 shrink-0 rounded-lg border border-brand-navy px-3 text-xs font-bold text-brand-navy">اعمال</button>
      </div>
      {f.unit && <span className="text-[11px] text-neutral-500">واحد: {f.unit}</span>}
      {err && <span role="alert" className="text-[11px] text-red-700">{err}</span>}
    </form>
  );
}

function FilterBody({ facets, attrFacets, state, change, loading }: { facets: Facets | null; attrFacets: AttributeFacet[]; state: FilterState; change: Change; loading: boolean }) {
  const [pFrom, setPFrom] = useState(""), [pTo, setPTo] = useState("");
  const setAttr = (code: string, toks: string[]) => change({ ["attr." + code]: toks.join(","), page: "1" });
  const toggle = (code: string, v: string) => {
    const cur = state.attrs[code] ?? [];
    setAttr(code, cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]);
  };
  const box = "border-b border-neutral-100 py-3";
  const legend = "mb-2 text-sm font-black text-brand-navy";
  const opt = "flex min-h-9 cursor-pointer items-center gap-2 text-sm text-neutral-700";
  return (
    <div className="min-w-0">
      <fieldset className={box}>
        <legend className={legend}>وضعیت کالا</legend>
        <label className={opt}><input type="checkbox" checked={state.inStock} onChange={(e) => change({ in_stock: e.target.checked ? "1" : "", page: "1" })} /> فقط کالاهای موجود</label>
        <label className={opt}><input type="checkbox" checked={state.purchasable} onChange={(e) => change({ availability: e.target.checked ? "purchasable" : "", page: "1" })} /> فقط قابل خرید آنلاین</label>
        <label className={opt}><input type="checkbox" checked={state.official} onChange={(e) => change({ official: e.target.checked ? "1" : "", page: "1" })} /> فروشندهٔ رسمی</label>
      </fieldset>

      {facets && (facets.brands.length > 0 || state.brand) && (
        <fieldset className={box}>
          <legend className={legend}>برند</legend>
          <div className="max-h-48 overflow-y-auto">
            <label className={opt}><input type="radio" name="brand-filter" checked={!state.brand} onChange={() => change({ brand: "", page: "1" })} /> همه برندها</label>
            {facets.brands.map((b) => (
              <label key={b.value} className={opt}><input type="radio" name="brand-filter" checked={state.brand === b.value} onChange={() => change({ brand: b.value, page: "1" })} />
                <span className="min-w-0 flex-1 truncate">{b.value}</span><span className="text-xs text-neutral-400">{toPersianNum(b.count)}</span></label>
            ))}
          </div>
        </fieldset>
      )}

      {(facets?.price_range || state.minPrice || state.maxPrice) && (
        <fieldset className={box}>
          <legend className={legend}>قیمت (تومان)</legend>
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); change({ min_price: tomanToMinor(pFrom), max_price: tomanToMinor(pTo), page: "1" }); }}>
            <label className="grid min-w-0 flex-1 gap-1 text-[11px] font-bold text-neutral-600">از
              <input inputMode="numeric" value={pFrom} onChange={(e) => setPFrom(e.target.value)} className="h-10 w-full min-w-0 rounded-lg border px-2 text-sm"
                placeholder={facets?.price_range ? formatPrice(facets.price_range.min).replace(" تومان", "") : ""} /></label>
            <label className="grid min-w-0 flex-1 gap-1 text-[11px] font-bold text-neutral-600">تا
              <input inputMode="numeric" value={pTo} onChange={(e) => setPTo(e.target.value)} className="h-10 w-full min-w-0 rounded-lg border px-2 text-sm"
                placeholder={facets?.price_range ? formatPrice(facets.price_range.max).replace(" تومان", "") : ""} /></label>
            <button className="h-10 shrink-0 rounded-lg border border-brand-navy px-3 text-xs font-bold text-brand-navy">اعمال</button>
          </form>
          <p className="mt-1 text-[11px] text-neutral-500">فقط کالاهای دارای قیمت تأییدشده.</p>
        </fieldset>
      )}

      {loading && !attrFacets.length && <p className="py-3 text-xs text-neutral-500" aria-live="polite">در حال دریافت فیلترها…</p>}
      {attrFacets.map((f) => {
        const toks = state.attrs[f.code] ?? [];
        return (
          <fieldset key={f.code} className={box}>
            <legend className={legend}>{f.name_fa}</legend>
            <div className="max-h-56 overflow-y-auto">
              {f.values.map((v) => (
                <label key={v.value} className={opt}>
                  <input type="checkbox" checked={toks.includes(v.value)} onChange={() => toggle(f.code, v.value)} />
                  <span className="min-w-0 flex-1 truncate">{toPersianNum(v.label_fa)}</span>
                  <span className="text-xs text-neutral-400" aria-label={`${toPersianNum(v.count)} کالا`}>{toPersianNum(v.count)}</span>
                </label>
              ))}
            </div>
            {NUMERIC.has(f.data_type) && (
              <NumberRange f={f} tokens={toks} onApply={(tok) => setAttr(f.code, [...toks.filter((t) => !t.includes("..")), ...(tok ? [tok] : [])])} />
            )}
          </fieldset>
        );
      })}
    </div>
  );
}

/** Active-filter chips; each removes one token. */
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
  const clearAll = () => change({ ...Object.fromEntries(Object.keys(state.attrs).map((c) => ["attr." + c, ""])), brand: "", min_price: "", max_price: "", in_stock: "", official: "", availability: "", page: "1" });
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="فیلترهای فعال">
      {chips.map((c) => (
        <button key={c.key} type="button" onClick={c.remove} aria-label={`حذف فیلتر ${c.label}`}
          className="inline-flex max-w-full items-center gap-1 rounded-full border border-brand-navy/30 bg-brand-navy/5 px-3 py-1.5 text-xs font-bold text-brand-navy">
          <span className="truncate">{c.label}</span><span aria-hidden>×</span>
        </button>
      ))}
      <button type="button" onClick={clearAll} className="px-2 text-xs font-bold text-brand-blue">حذف همه</button>
    </div>
  );
}

/** Desktop side panel + mobile trigger/bottom sheet. */
export function FilterPanel(props: { facets: Facets | null; attrFacets: AttributeFacet[]; state: FilterState; change: Change; loading: boolean; total: number }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null), sheet = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const active = Object.values(props.state.attrs).reduce((n, t) => n + t.length, 0)
    + [props.state.brand, props.state.minPrice || props.state.maxPrice, props.state.inStock, props.state.official, props.state.purchasable].filter(Boolean).length;
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sheet.current?.querySelector<HTMLElement>("button, input")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); return; }
      if (e.key !== "Tab" || !sheet.current) return;
      const els = [...sheet.current.querySelectorAll<HTMLElement>("button, input, select, a[href]")].filter((x) => !x.hasAttribute("disabled"));
      if (!els.length) return;
      const first = els[0], last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prev; document.removeEventListener("keydown", onKey); trigger.current?.focus(); };
  }, [open]);
  return (
    <>
      <button ref={trigger} type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}
        className="mb-3 inline-flex min-h-11 items-center gap-2 rounded-xl border border-neutral-200 bg-white px-4 text-sm font-bold text-brand-navy md:hidden">
        فیلترها{active > 0 && <span className="rounded-full bg-brand-navy px-2 text-[11px] text-white">{toPersianNum(active)}</span>}
      </button>
      <aside className="hidden md:block" aria-label="فیلترها">
        <div className="card sticky top-24 max-h-[calc(100vh-7rem)] overflow-y-auto p-4">
          <h2 className="mb-1 text-base font-black text-brand-navy">فیلترها</h2>
          <FilterBody {...props} />
        </div>
      </aside>
      {open && (
        <div className="fixed inset-0 z-50 md:hidden" dir="rtl">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
          <div ref={sheet} role="dialog" aria-modal="true" aria-labelledby={titleId}
            className="absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h2 id={titleId} className="text-base font-black text-brand-navy">فیلترها</h2>
              <button type="button" onClick={() => setOpen(false)} aria-label="بستن فیلترها" className="min-h-11 min-w-11 rounded-lg text-xl">×</button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4">
              <FilterBody {...props} />
            </div>
            <div className="border-t p-3">
              <button type="button" onClick={() => setOpen(false)} className="min-h-12 w-full rounded-xl bg-primary-600 font-bold text-white">
                {props.loading ? "در حال به‌روزرسانی…" : `نمایش ${toPersianNum(props.total)} کالا`}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
