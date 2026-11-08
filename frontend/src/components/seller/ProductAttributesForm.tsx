"use client";
// Phase 6 seller form: typed product attributes driven by the effective category schema.
// GET /supplier/offers → pick product → GET /supplier/catalog/products/<mid>/attributes (values + category)
// → GET /categories/<slug>/schema → live POST /supplier/catalog/validate (debounced) → PUT …/attributes.
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, apiRequest } from "@/lib/api";
import { latinDigits } from "@/lib/shops";
import { toPersianNum } from "@/lib/utils";
import { Card, Flash, ListState, btnCls, inputCls } from "@/components/commerce/ui";

type Attr = {
  code: string; name_fa: string; data_type: "text" | "number" | "integer" | "boolean" | "enum" | "multi_enum" | "measure" | "date";
  canonical_unit: string | null; units: { code: string; name_fa: string }[]; min_value: number | null; max_value: number | null;
  regex: string | null; help_fa: string | null; options: { code: string; label_fa: string }[]; required: boolean; display_group_fa: string;
};
type Check = { key: string; ok: boolean; message_fa: string; kind: string };
type Quality = { score: number; grade?: string; checklist: Check[]; missing_required: string[]; errors: { attribute: string; message: string }[]; suggested_title?: string | null };
type OfferRow = { id: number; product_name: string; master_product_id: number | null; status: string };
type Draft = { title: string; brand: string | null; model: string | null; description: string | null; images: string[] };
type Val = string | boolean | string[] | { value: string; unit: string } | null;
type Msg = { ok: boolean; text: string } | null;

const errText = (e: unknown, fb: string) => (e instanceof ApiError ? e.message || fb : fb);
const num = (v: string) => latinDigits(v).replace(/٫/g, ".").replace(/[,،٬\s]/g, "");
const isEmpty = (v: Val) => v == null || v === "" || (Array.isArray(v) && !v.length) || (typeof v === "object" && !Array.isArray(v) && !v.value.trim());

function initial(a: Attr, raw: unknown): Val {
  if (raw == null) return a.data_type === "multi_enum" ? [] : a.data_type === "measure" ? { value: "", unit: a.canonical_unit ?? a.units[0]?.code ?? "" } : a.data_type === "boolean" ? null : "";
  if (a.data_type === "multi_enum") return Array.isArray(raw) ? raw.map(String) : [String(raw)];
  if (a.data_type === "measure") return { value: String(raw), unit: a.canonical_unit ?? "" };
  if (a.data_type === "boolean") return Boolean(raw);
  return String(raw);
}

/** Client-side mirror of the server rules (server stays authoritative). */
function check(a: Attr, v: Val): string | null {
  if (isEmpty(v)) return a.required ? "این مشخصه الزامی است" : null;
  const t = a.data_type;
  if (t === "number" || t === "integer" || t === "measure") {
    const s = num(typeof v === "object" && v && !Array.isArray(v) ? v.value : String(v));
    const n = Number(s);
    if (!s || !Number.isFinite(n)) return "عدد معتبر وارد کنید";
    if (n < 0) return "عدد منفی مجاز نیست";
    if (t === "integer" && !Number.isInteger(n)) return "عدد صحیح وارد کنید";
    const inCanonical = t !== "measure" || (v as { unit: string }).unit === a.canonical_unit;
    if (inCanonical && ((a.min_value != null && n < a.min_value) || (a.max_value != null && n > a.max_value)))
      return `باید بین ${toPersianNum(a.min_value ?? 0)} و ${a.max_value != null ? toPersianNum(a.max_value) : "∞"} باشد`;
  }
  if (t === "text") {
    const s = String(v).trim();
    if (a.max_value != null && s.length > a.max_value) return `حداکثر ${toPersianNum(a.max_value)} نویسه`;
    if (a.regex) { try { if (!new RegExp(`^(?:${a.regex})$`).test(s)) return "قالب وارد شده معتبر نیست"; } catch { /* Python-only pattern: server decides */ } }
  }
  if (t === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(latinDigits(String(v)))) return "تاریخ میلادی را به شکل YYYY-MM-DD یا از تقویم انتخاب کنید";
  return null;
}

function payload(schema: Attr[], vals: Record<string, Val>, forSave: boolean): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const a of schema) {
    const v = vals[a.code];
    if (isEmpty(v)) { if (forSave) out[a.code] = ""; continue; } // "" on save clears a stored value
    if (a.data_type === "measure") { const m = v as { value: string; unit: string }; out[a.code] = { value: num(m.value), unit: m.unit || undefined }; }
    else if (a.data_type === "number" || a.data_type === "integer") out[a.code] = num(String(v));
    else if (a.data_type === "date") out[a.code] = latinDigits(String(v)).trim();
    else if (a.data_type === "text") out[a.code] = String(v).trim();
    else out[a.code] = v;
  }
  return out;
}

function Field({ a, v, set, err }: { a: Attr; v: Val; set: (v: Val) => void; err: string | null }) {
  const id = `pa-${a.code}`, hint = `${id}-hint`, errId = `${id}-err`;
  const described = [a.help_fa ? hint : "", err ? errId : ""].filter(Boolean).join(" ") || undefined;
  const label = <>{a.name_fa}{a.required && <span className="mr-0.5 text-red-600" aria-hidden>*</span>}{a.required && <span className="sr-only"> (الزامی)</span>}</>;
  const common = { "aria-invalid": err ? true : undefined, "aria-describedby": described, "aria-required": a.required || undefined };
  let control: React.ReactNode;
  switch (a.data_type) {
    case "boolean":
      control = (
        <div role="radiogroup" aria-labelledby={`${id}-l`} {...common} className="mt-1 flex flex-wrap gap-3 text-sm">
          {[["بله", true], ["خیر", false], ["نامشخص", null]].map(([l, b]) => (
            <label key={String(l)} className="inline-flex min-h-9 items-center gap-1"><input type="radio" name={id} checked={v === b} onChange={() => set(b as boolean | null)} />{l as string}</label>))}
        </div>);
      break;
    case "enum":
      control = (
        <select id={id} {...common} className={inputCls} value={String(v ?? "")} onChange={(e) => set(e.target.value)}>
          <option value="">— انتخاب کنید —</option>
          {a.options.map((o) => <option key={o.code} value={o.code}>{o.label_fa}</option>)}
        </select>);
      break;
    case "multi_enum": {
      const cur = Array.isArray(v) ? v : [];
      control = (
        <div role="group" aria-labelledby={`${id}-l`} {...common} className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          {a.options.map((o) => (
            <label key={o.code} className="inline-flex min-h-9 min-w-0 items-center gap-1"><input type="checkbox" checked={cur.includes(o.code)}
              onChange={() => set(cur.includes(o.code) ? cur.filter((x) => x !== o.code) : [...cur, o.code])} /><span className="truncate">{o.label_fa}</span></label>))}
        </div>);
      break;
    }
    case "measure": {
      const m = (v as { value: string; unit: string }) ?? { value: "", unit: a.canonical_unit ?? "" };
      control = (
        <div className="mt-1 flex gap-2">
          <input id={id} {...common} inputMode="decimal" className={inputCls.replace("mt-1 ", "") + " min-w-0 flex-1"} value={m.value} onChange={(e) => set({ ...m, value: e.target.value })} />
          <select aria-label={`واحد ${a.name_fa}`} className="w-28 shrink-0 rounded-xl border border-neutral-300 bg-white p-2 text-sm" value={m.unit} onChange={(e) => set({ ...m, unit: e.target.value })}>
            {a.units.map((u) => <option key={u.code} value={u.code}>{u.name_fa}</option>)}
          </select>
        </div>);
      break;
    }
    case "number": case "integer":
      control = <input id={id} {...common} inputMode={a.data_type === "integer" ? "numeric" : "decimal"} className={inputCls} value={String(v ?? "")} onChange={(e) => set(e.target.value)} />;
      break;
    case "date":
      control = <input id={id} {...common} type="date" dir="ltr" className={inputCls} value={latinDigits(String(v ?? ""))} onChange={(e) => set(e.target.value)} />;
      break;
    default:
      control = <input id={id} {...common} className={inputCls} maxLength={a.max_value ?? 500} value={String(v ?? "")} onChange={(e) => set(e.target.value)} />;
  }
  return (
    <div className="min-w-0">
      {a.data_type === "boolean" || a.data_type === "multi_enum"
        ? <span id={`${id}-l`} className="text-xs font-bold">{label}</span>
        : <label htmlFor={id} id={`${id}-l`} className="text-xs font-bold">{label}</label>}
      {control}
      {a.help_fa && <p id={hint} className="mt-1 text-[11px] text-neutral-500">{a.help_fa}</p>}
      {err && <p id={errId} role="alert" className="mt-1 text-[11px] font-bold text-red-700">{err}</p>}
    </div>
  );
}

export function ProductAttributesCard({ token }: { token: string }) {
  const [offers, setOffers] = useState<OfferRow[] | null>(null), [offErr, setOffErr] = useState<string | null>(null), [retry, setRetry] = useState(0);
  const [mid, setMid] = useState<number | null>(null);
  const [schema, setSchema] = useState<Attr[] | null>(null), [draft, setDraft] = useState<Draft | null>(null), [catSlug, setCatSlug] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null), [loading, setLoading] = useState(false);
  const [vals, setVals] = useState<Record<string, Val>>({}), [touched, setTouched] = useState(false);
  const [quality, setQuality] = useState<Quality | null>(null), [validating, setValidating] = useState(false);
  const [serverErr, setServerErr] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<Msg>(null);
  const seq = useRef(0);

  useEffect(() => {
    let on = true; setOffers(null); setOffErr(null);
    apiRequest<{ offers: OfferRow[] }>("/supplier/offers?limit=100", { token })
      .then((r) => on && setOffers(r.offers)).catch((e) => on && (e instanceof ApiError && e.status === 404 ? setOffers([]) : setOffErr(errText(e, "دریافت کالاها ناموفق بود"))));
    return () => { on = false; };
  }, [token, retry]);
  const products = useMemo(() => {
    const seen = new Map<number, string>();
    for (const o of offers ?? []) if (o.master_product_id && !seen.has(o.master_product_id)) seen.set(o.master_product_id, o.product_name);
    return [...seen.entries()].map(([id, name]) => ({ id, name }));
  }, [offers]);

  useEffect(() => {
    if (mid == null) return;
    let on = true;
    setLoading(true); setLoadErr(null); setSchema(null); setQuality(null); setServerErr({}); setMsg(null); setTouched(false);
    (async () => {
      const cur = await apiRequest<{ category_slug: string | null; product: Draft; values: Record<string, unknown>; quality: Quality }>(`/supplier/catalog/products/${mid}/attributes`, { token });
      if (!cur.category_slug) throw new Error("دستهٔ این کالا هنوز مشخص نشده است؛ با پشتیبانی تماس بگیرید.");
      const sc = await apiRequest<{ attributes: Attr[] }>(`/categories/${encodeURIComponent(cur.category_slug)}/schema`);
      if (!on) return;
      setCatSlug(cur.category_slug); setDraft(cur.product); setSchema(sc.attributes); setQuality(cur.quality);
      setVals(Object.fromEntries(sc.attributes.map((a) => [a.code, initial(a, cur.values[a.code])])));
    })().catch((e) => on && setLoadErr(errText(e, e instanceof Error ? e.message : "بارگذاری ناموفق بود"))).finally(() => on && setLoading(false));
    return () => { on = false; };
  }, [mid, token]);

  const clientErr = useMemo(() => Object.fromEntries((schema ?? []).map((a) => [a.code, check(a, vals[a.code] ?? null)]).filter(([, e]) => e)) as Record<string, string>, [schema, vals]);

  // Live validation (debounced); only the latest response is applied.
  useEffect(() => {
    if (!schema || !catSlug || !draft || !touched) return;
    const my = ++seq.current;
    const t = setTimeout(() => {
      setValidating(true);
      apiRequest<Quality>("/supplier/catalog/validate", { token, method: "POST", body: JSON.stringify({ category_slug: catSlug, title: draft.title, brand: draft.brand,
        model: draft.model, description: draft.description, images: draft.images, attributes: payload(schema, vals, false) }) })
        .then((q) => { if (my !== seq.current) return; setQuality(q); setServerErr(Object.fromEntries(q.errors.map((e) => [e.attribute, e.message]))); })
        .catch(() => {}).finally(() => my === seq.current && setValidating(false));
    }, 600);
    return () => clearTimeout(t);
  }, [schema, catSlug, draft, vals, touched, token]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!schema || mid == null) return;
    const bad = Object.entries(clientErr).filter(([c]) => !schema.find((a) => a.code === c)?.required || !isEmpty(vals[c]));
    if (bad.length) { setMsg({ ok: false, text: "چند مقدار نامعتبر است؛ موارد قرمز را اصلاح کنید." }); document.getElementById(`pa-${bad[0][0]}`)?.focus(); return; }
    setBusy(true); setMsg(null);
    try {
      const r = await apiRequest<{ quality: Quality }>(`/supplier/catalog/products/${mid}/attributes`, { token, method: "PUT", body: JSON.stringify({ attributes: payload(schema, vals, true) }) });
      setQuality(r.quality); setServerErr({});
      setMsg({ ok: true, text: r.quality.missing_required.length ? "ذخیره شد؛ هنوز چند مشخصهٔ الزامی کامل نشده است." : "مشخصات کالا ذخیره شد." });
    } catch (e2) {
      const errs = (e2 instanceof ApiError ? (e2.details as unknown as { errors?: { attribute: string; message: string }[] })?.errors : undefined) ?? [];
      if (errs.length) setServerErr(Object.fromEntries(errs.map((x) => [x.attribute, x.message])));
      setMsg({ ok: false, text: errText(e2, "ذخیرهٔ مشخصات ناموفق بود") });
    } finally { setBusy(false); }
  };

  const groups = useMemo(() => {
    const g = new Map<string, Attr[]>();
    for (const a of schema ?? []) g.set(a.display_group_fa, [...(g.get(a.display_group_fa) ?? []), a]);
    return [...g.entries()];
  }, [schema]);
  const reqMissing = (schema ?? []).filter((a) => a.required && isEmpty(vals[a.code])).length;
  const score = quality?.score ?? 0;

  return (
    <div id="attributes"><Card title="مشخصات کالاها">
      <p className="text-xs leading-6 text-neutral-600">مشخصات دقیق، کالای شما را در فیلترهای دسته و نتایج جستجو نشان می‌دهد. موارد ستاره‌دار الزامی‌اند.</p>
      {offErr || !offers ? <ListState items={offers} error={offErr} empty="" onRetry={() => setRetry((x) => x + 1)} />
        : !products.length ? <p className="rounded-xl bg-neutral-50 p-3 text-sm text-neutral-600">هنوز پیشنهاد فروشی ثبت نکرده‌اید؛ پس از ثبت پیشنهاد، مشخصات کالا را اینجا تکمیل کنید.</p>
        : (
          <label className="block text-xs font-bold">انتخاب کالا
            <select className={inputCls} value={mid ?? ""} onChange={(e) => setMid(e.target.value ? Number(e.target.value) : null)}>
              <option value="">— یکی از کالاهای خود را انتخاب کنید —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        )}
      {mid != null && (loading ? <ListState items={null} error={null} empty="" />
        : loadErr ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{loadErr}</p>
        : schema && !schema.length ? <p className="rounded-xl bg-neutral-50 p-3 text-sm text-neutral-600">برای دستهٔ این کالا هنوز مشخصه‌ای تعریف نشده است.</p>
        : schema && (
          <form onSubmit={save} noValidate className="space-y-4">
            {quality && (
              <section aria-label="کیفیت فهرست" aria-live="polite" className="rounded-xl border border-neutral-200 p-3">
                <div className="flex items-center justify-between gap-2 text-sm font-bold">
                  <span>امتیاز کیفیت: {toPersianNum(score)} از ۱۰۰{validating && <span className="mr-2 text-[11px] font-normal text-neutral-500">در حال بررسی…</span>}</span>
                  {reqMissing > 0 && <span className="text-[11px] text-amber-700">{toPersianNum(reqMissing)} مشخصهٔ الزامی خالی</span>}
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-neutral-100" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={score} aria-label="امتیاز کیفیت">
                  <div className={`h-full ${score >= 85 ? "bg-emerald-500" : score >= 65 ? "bg-sky-500" : score >= 40 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${score}%` }} />
                </div>
                <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs">
                  {quality.checklist.map((c) => (
                    <li key={c.key} className={`flex gap-1 ${c.ok ? "text-emerald-700" : c.kind === "required" ? "text-red-700" : "text-amber-700"}`}>
                      <span aria-hidden>{c.ok ? "✓" : "•"}</span><span className="sr-only">{c.ok ? "انجام شده:" : "مانده:"}</span>{c.message_fa}</li>))}
                </ul>
                {quality.suggested_title && <p className="mt-2 break-words text-[11px] text-neutral-500">عنوان پیشنهادی: {quality.suggested_title}</p>}
              </section>
            )}
            {groups.map(([g, attrs]) => (
              <fieldset key={g} className="min-w-0 space-y-3">
                <legend className="mb-1 text-sm font-black text-neutral-900">{g}</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  {attrs.map((a) => (
                    <Field key={a.code} a={a} v={vals[a.code] ?? null} err={(touched ? clientErr[a.code] : null) ?? serverErr[a.code] ?? null}
                      set={(v) => { setTouched(true); setServerErr((s) => { const n = { ...s }; delete n[a.code]; return n; }); setVals((s) => ({ ...s, [a.code]: v })); }} />
                  ))}
                </div>
              </fieldset>
            ))}
            <button type="submit" className={btnCls + " w-full sm:w-auto"} disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیرهٔ مشخصات"}</button>
          </form>
        ))}
      <Flash msg={msg} />
    </Card></div>
  );
}
