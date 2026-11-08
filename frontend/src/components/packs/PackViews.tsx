"use client";
// Packs: merchandising compositions of real catalog products. Priced only when every required item has a
// verified seller offer; otherwise "quote only". Never the storefront's main surface.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, CheckSquare, ImageOff, Repeat } from "lucide-react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { addProductToOrgDraft } from "@/lib/procurement/draft";
import { storefront, type PackDetail, type PackSummary } from "@/lib/storefront";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { useGoodImages } from "@/lib/imageQuality";
import { UI } from "./PackCard";
import { Steps } from "./PackStudio";

const weight = (g: number | null) => (g ? (g >= 1000 ? `${toPersianNum(+(g / 1000).toFixed(1))} کیلوگرم` : `${toPersianNum(g)} گرم`) : "—");
const price = (p: PackSummary) => (p.price_minor != null ? formatPrice(p.price_minor) : "قیمت با استعلام");

export function PackPage({ slug }: { slug: string }) {
  const { token } = useAuth();
  const router = useRouter();
  const [p, setP] = useState<PackDetail | null>(null), [error, setError] = useState("");
  const [qty, setQty] = useState(1), [busy, setBusy] = useState(false), [done, setDone] = useState<string>(""), [doneBad, setDoneBad] = useState(false);
  useEffect(() => { storefront.pack(slug).then((r) => { setP(r.pack); setQty(r.pack.min_order_qty); }).catch((e) => setError(e.message)); }, [slug]);
  const good = useGoodImages(p?.items.map((i) => i.image_url) ?? []);
  if (error) return <div className="container-page py-8"><p role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">{error}</p><Link href="/pack-builder" className="mt-4 inline-flex min-h-11 items-center text-sm font-bold text-brand-blue">همه پک‌ها</Link></div>;
  if (!p) return <div className="container-page py-8"><div className="min-h-64 animate-pulse rounded-xl bg-neutral-100" /></div>;
  const request = async () => {
    if (!token) { router.push(`/login?next=/packs/${slug}`); return; }
    if (busy) return;
    setBusy(true);
    try {
      const r = await apiRequest<{ request: { id: number } }>("/requests", { token, method: "POST", headers: { "Idempotency-Key": newIdempotencyKey() },
        body: JSON.stringify({ kind: "price", subject: `استعلام ${p.title_fa} × ${qty}`, message: `درخواست ${toPersianNum(qty)} پک «${p.title_fa}»`,
          items: p.items.filter((i) => i.slug).map((i) => ({ slug: i.slug, quantity: i.quantity * qty })) }) });
      router.push(`/requests/${r.request.id}`);
    } catch (e) { setDoneBad(true); setDone(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  };
  const toOrg = () => { setDoneBad(false); let n = 0; for (const i of p.items) n = addProductToOrgDraft({ name: i.title_fa, master_product_id: i.master_product_id, image_url: i.image_url }, i.quantity * qty); setDone(`${toPersianNum(n)} قلم به درخواست سازمانی افزوده شد.`); };
  const allowed=p.allowed_channels??["retail","organization"];
  const units = p.items.reduce((n, i) => n + i.quantity, 0);
  const customize = p.customizable && p.items.some((i) => i.slug);
  return (
    <div className="container-page space-y-5 py-6 md:py-8" dir="rtl">
      <Link href="/pack-builder" className="inline-flex min-h-11 items-center gap-1 text-sm" style={{ color: UI.muted }}>پک‌های پیشنهادی <ArrowLeft className="h-4 w-4" /></Link>
      <div>
        <p className="text-xs" style={{ color: UI.muted }}>{p.kind_fa}{p.tier_fa ? ` · ${p.tier_fa}` : ""}{p.occasion ? ` · ${p.occasion}` : ""}</p>
        <h1 className="mt-1 text-[26px] font-black leading-[1.55] md:text-[32px]" style={{ color: UI.ink }}>{p.title_fa}</h1>
        <p className="mt-1 text-sm leading-7 md:text-base" style={{ color: UI.ink }}>{p.purpose_fa}</p>
      </div>
      <Steps active={1} />
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_364px]">
        <section className="min-w-0 space-y-4">
          <div className="rounded-2xl border bg-white p-4" style={{ borderColor: UI.line }}>
            <h2 className="mb-2 text-xl font-black" style={{ color: UI.ink }}>ترکیب هر پک</h2>
            <ul className="divide-y" style={{ borderColor: UI.line }}>
              {p.items.map((i) => (
                <li key={i.master_product_id} className="grid grid-cols-[56px_minmax(0,1fr)_auto] items-center gap-3 py-3">
                  <span className="flex h-16 w-14 items-center justify-center overflow-hidden rounded-xl bg-white">{i.image_url && good?.has(i.image_url) ? <img src={i.image_url} alt="" className="h-full w-full object-contain" /> : <ImageOff className="h-5 w-5 text-neutral-300" aria-label="تصویر مناسب موجود نیست" />}</span>
                  <div className="min-w-0">
                    {i.slug ? <Link href={`/products/${i.slug}`} className="line-clamp-2 text-sm font-bold hover:text-brand-blue" style={{ color: UI.ink }}>{i.title_fa}</Link> : <span className="text-sm font-bold">{i.title_fa}</span>}
                    <p className="text-xs" style={{ color: UI.muted }}>{i.brand_fa}{i.variant_label ? ` · ${i.variant_label}` : ""}{i.required ? "" : " · اختیاری"}{" · "}{i.line_total_minor != null ? formatPrice(i.line_total_minor) : "استعلام قیمت"}</p>
                    {!!i.alternatives?.length && <details className="mt-1 text-xs"><summary className="flex min-h-8 cursor-pointer items-center gap-1 text-brand-blue"><Repeat className="h-3.5 w-3.5" /> جایگزین‌های هم‌نوع ({toPersianNum(i.alternatives.length)})</summary>
                      <ul className="mt-1 space-y-1">{i.alternatives.map((a) => <li key={a.master_product_id}>{a.slug ? <Link href={`/products/${a.slug}`} className="hover:text-brand-blue">{a.title_fa}</Link> : a.title_fa}{a.variant_label ? ` · ${a.variant_label}` : ""}</li>)}</ul></details>}
                  </div>
                  <b className="text-sm" style={{ color: UI.ink }}>{toPersianNum(i.quantity)} عدد</b>
                </li>))}
            </ul>
            {p.price_minor == null && <p className="mt-2 text-xs" style={{ color: UI.muted }}>قیمت اقلام با استعلام مشخص می‌شود</p>}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-2xl border bg-white p-4 text-sm sm:grid-cols-3" style={{ borderColor: UI.line }}>
            {([["مناسب برای", p.household_size ? `${toPersianNum(p.household_size)} نفر` : p.audience_fa], ["وزن مواد غذایی", weight(p.food_weight_g)], ["برندها", p.brands.join("، ") || "—"],
              ["بسته‌بندی", p.packaging_fa ?? "—"], ["جایگزینی", p.substitution_policy === "none" ? "بدون جایگزینی" : p.substitution_policy === "ask" ? "با هماهنگی" : "فقط کالای هم‌نوع"], ["حداقل سفارش", `${toPersianNum(p.min_order_qty)} پک`]] as const)
              .map(([k, v]) => <div key={k}><dt className="text-xs" style={{ color: UI.muted }}>{k}</dt><dd className="font-bold" style={{ color: UI.ink }}>{v}</dd></div>)}
          </dl>
          {customize && <Link href={`/pack-builder?pack=${encodeURIComponent(p.slug)}`} className="flex h-11 items-center justify-center rounded-xl text-sm font-bold text-white lg:w-64" style={{ background: UI.ink }}>شخصی‌سازی این پک</Link>}
        </section>
        <aside className="min-w-0 space-y-3 rounded-2xl p-4 lg:sticky lg:top-44" style={{ background: UI.warm }} aria-label="خلاصه پک">
          <h2 className="text-xl font-black" style={{ color: UI.ink }}>خلاصه پک شما</h2>
          <p className="text-sm" style={{ color: UI.ink }}>{toPersianNum(p.item_count)} نوع کالا · {toPersianNum(units)} قلم در هر پک</p>
          <label className="grid grid-cols-2 items-center gap-3 text-sm" style={{ color: UI.ink }}>تعداد پک
            <input aria-label="تعداد پک" type="number" min={p.min_order_qty} value={qty} onChange={(e) => setQty(Math.max(p.min_order_qty, Math.floor(Number(e.target.value)) || p.min_order_qty))} className="h-11 rounded-xl border bg-white px-3 text-center font-bold" style={{ borderColor: UI.line }} /></label>
          <p className="text-sm font-bold" style={{ color: UI.ink }}>قیمت هر پک: {p.price_minor != null ? formatPrice(p.price_minor) : "استعلام قیمت"}</p>
          <p className="text-base font-black" style={{ color: UI.ink }}>جمع کل: {p.price_minor != null ? formatPrice(p.price_minor * qty) : "پس از استعلام"}</p>
          {p.availability === "purchasable"
            ? <button type="button" disabled={busy} onClick={async () => {
                if (!token) { router.push(`/login?next=/packs/${slug}`); return; }
                setBusy(true);
                try { await apiRequest(`/cart/packs/${slug}`, { token, method: "POST", body: JSON.stringify({ count: qty }), headers: { "Idempotency-Key": newIdempotencyKey() } }); router.push("/cart"); }
                catch (e) { setDoneBad(true); setDone(e instanceof Error ? e.message : "افزودن ناموفق بود"); } finally { setBusy(false); } }}
                className="h-11 w-full rounded-xl text-sm font-bold text-white disabled:opacity-60" style={{ background: UI.ink }}>افزودن پک به سبد</button>
            : <button type="button" onClick={request} disabled={busy||!allowed.includes("retail")} className="h-11 w-full rounded-xl text-sm font-bold text-white disabled:opacity-60" style={{ background: UI.ink }}>{busy ? "در حال ثبت…" : "ثبت استعلام قیمت"}</button>}
          <button type="button" onClick={toOrg} disabled={!allowed.includes("organization")} className="flex h-11 w-full items-center justify-center gap-1 rounded-xl border bg-white text-sm font-bold" style={{ color: UI.ink, borderColor: UI.line }}><CheckSquare className="h-4 w-4" /> افزودن به درخواست سازمانی</button>
          <p className="text-xs" style={{ color: UI.muted }}>قیمت و موجودی در زمان ثبت بررسی می‌شود.</p>
          {done && <p role="status" className={`rounded-xl p-2 text-xs ${doneBad ? "bg-red-50 text-red-800" : "bg-emerald-50 text-emerald-800"}`}>{done} {done.includes("سازمانی") && <Link href="/organization/compose" className="font-bold underline">ادامه</Link>}</p>}
        </aside>
      </div>
    </div>
  );
}

export function PackCompare() {
  const slugs = (useSearchParams().get("slugs") ?? "").split(",").filter(Boolean);
  const [items, setItems] = useState<PackDetail[] | null>(null), [error, setError] = useState("");
  useEffect(() => { storefront.compare(slugs).then((r) => setItems(r.items)).catch((e) => setError(e.message)); }, [slugs.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows: [string, (p: PackDetail) => string][] = [
    ["قیمت", price], ["تعداد اقلام", (p) => `${toPersianNum(p.item_count)} قلم`], ["تعداد واحد", (p) => toPersianNum(p.unit_count)],
    ["وزن مواد غذایی", (p) => weight(p.food_weight_g)], ["برندها", (p) => p.brands.join("، ") || "—"], ["سطح", (p) => p.tier_fa ?? "—"],
    ["قابل تغییر", (p) => (p.customizable ? "بله" : "خیر")], ["حداقل سفارش", (p) => `${toPersianNum(p.min_order_qty)} پک`],
    ["زمان تأمین", (p) => (p.lead_time_days != null ? `${toPersianNum(p.lead_time_days)} روز` : "با استعلام")], ["بسته‌بندی", (p) => p.packaging_fa ?? "—"],
  ];
  return (
    <div className="container-page py-8" dir="rtl">
      <h1 className="mb-4 text-2xl font-black text-brand-navy">مقایسه پک‌ها</h1>
      {error ? <p role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">{error}</p> : !items ? <div className="min-h-64 animate-pulse rounded-xl bg-neutral-100" /> : (
        <div className="overflow-x-auto rounded-2xl border border-neutral-200 bg-white">
          <table className="w-full min-w-[560px] text-sm">
            <thead><tr><th className="p-3 text-right text-neutral-500">ویژگی</th>{items.map((p) => <th key={p.slug} className="p-3 text-right"><Link href={`/packs/${p.slug}`} className="text-brand-navy hover:text-brand-blue">{p.title_fa}</Link></th>)}</tr></thead>
            <tbody>{rows.map(([label, f]) => <tr key={label} className="border-t border-neutral-100"><td className="p-3 text-neutral-500">{label}</td>{items.map((p) => <td key={p.slug} className="p-3 font-bold">{f(p)}</td>)}</tr>)}
              <tr className="border-t border-neutral-100 align-top"><td className="p-3 text-neutral-500">اقلام</td>{items.map((p) => <td key={p.slug} className="p-3 text-xs leading-6">{p.items.map((i) => `${i.title_fa} ×${toPersianNum(i.quantity)}`).join("، ")}</td>)}</tr></tbody>
          </table>
        </div>)}
    </div>
  );
}
