"use client";
import { scopedDraftKey } from "@/lib/client-draft-storage";
import { exactPackTotals, positiveInteger } from "@/lib/pack-input";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ImageOff, Plus, Minus, Trash2 } from "lucide-react";
import { apiRequest, cart, newIdempotencyKey } from "@/lib/api";
import { storefront, type Card, type ProductPage, type TaxNode } from "@/lib/storefront";
import { useAuth } from "@/lib/auth-context";
import { formatPrice, toPersianNum } from "@/lib/utils";
import { PackOrgRequest } from "./PackOrgRequest";
import { useGoodImages } from "@/lib/imageQuality";
import { UI } from "@/components/packs/PackCard";

export type DraftLine = { slug: string; title: string; quantity: number; imageUrl: string | null; priceMinor: number | null };
export type PackDraft = { items: DraftLine[]; count?: number };
const DRAFT_KEY = "60o_pack_builder_draft";
const inputClass = "h-11 w-full rounded-xl border border-neutral-200 bg-white px-3 text-sm";
export function ProductImage({ src, title }: { src: string | null; title: string }) {
  const good = useGoodImages([src]);
  const ok = !!src && !!good?.has(src);
  return <div className="flex h-full w-full items-center justify-center rounded-xl bg-white p-2">{ok ? <img src={src!} alt={title} className="h-full w-full object-contain" /> : good === null && src ? <span className="h-full w-full animate-pulse rounded-lg bg-neutral-50" /> : <span className="flex flex-col items-center gap-1 text-neutral-400"><ImageOff className="h-7 w-7" /><span className="text-[10px]">تصویر مناسب موجود نیست</span></span>}</div>;
}

export function PackBuilderInteractive({ draft, onBack, onStep }: { draft: PackDraft; onBack: () => void; onStep: (step: number) => void }) {
  const { token } = useAuth();
  const router = useRouter();
  const [lines, setLines] = useState(draft.items);
  const [count, setCount] = useState(String(draft.count ?? 1));
  const [details, setDetails] = useState<Record<string, ProductPage>>({});
  const [query, setQuery] = useState(""), [category, setCategory] = useState("");
  const [categories, setCategories] = useState<TaxNode[]>([]), [products, setProducts] = useState<Card[]>([]);
  const [page,setPage]=useState(1),[pages,setPages]=useState(1),[productTotal,setProductTotal]=useState(0);
  const [loading, setLoading] = useState(true), [searchError, setSearchError] = useState("");
  const [refresh, setRefresh] = useState(0), [refreshing, setRefreshing] = useState(false), [error, setError] = useState("");
  const [review, setReview] = useState(false), [busy, setBusy] = useState(false), [done, setDone] = useState<"cart" | "request" | null>(null);
  const [orgOpen, setOrgOpen] = useState(false);
  const requestKey = useRef<string>("");
  const added = useRef(new Set<string>());
  const packCount = positiveInteger(count) ?? NaN;
  const validCount = Number.isInteger(packCount) && packCount > 0 && packCount <= 100000;
  const slugs = lines.map(l => l.slug).join("|");
  useEffect(() => { apiRequest<{ items: TaxNode[] }>("/storefront/taxonomy").then(r => setCategories(r.items)).catch(() => {}); }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setSearchError("");
    const timer = setTimeout(() => { const qs = new URLSearchParams({ q: query, category, page_size: "12", page: String(page), sort: "relevance" });
      apiRequest<{ items: Card[]; total: number; total_pages: number }>(`/storefront/products?${qs}`).then(r => { if (active) {setProducts(r.items);setPages(Math.max(1,r.total_pages));setProductTotal(r.total);} })
        .catch(e => { if (active) { setProducts([]); setSearchError(e.message); } }).finally(() => { if (active) setLoading(false); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [query, category, page]);
  useEffect(() => {
    let active = true;
    setRefreshing(true);
    Promise.all(lines.map(l => storefront.product(l.slug, token).then(d => [l.slug, d] as const).catch(() => [l.slug, null] as const)))
      .then(rows => { if (active) { setDetails(Object.fromEntries(rows.filter((r): r is readonly [string, ProductPage] => r[1] !== null))); setRefreshing(false); } });
    return () => { active = false; };
  }, [slugs, token, refresh]); // Quantity edits do not require a new catalog read.
  useEffect(() => { try { localStorage.setItem(scopedDraftKey(DRAFT_KEY), JSON.stringify({ items: lines, count: validCount ? packCount : 1 })); } catch { /* storage may be unavailable */ } }, [lines, count]);
  const update = (next: DraftLine[]) => { setLines(next); setReview(false); setDone(null); requestKey.current = ""; };
  const changeQty = (slug: string, delta: number) => update(lines.map(l => l.slug === slug ? { ...l, quantity: Math.max(1, Math.min(100000, l.quantity + delta)) } : l));
  const add = (p: Card) => {
    if (lines.some(l => l.slug === p.slug)) changeQty(p.slug, 1);
    else update([...lines, { slug: p.slug, title: p.title_fa, quantity: 1, imageUrl: p.image_url, priceMinor: null }]);
  };
  const unpriced = lines.filter(l => details[l.slug]?.price_minor == null);
  const unavailable = lines.filter(l => details[l.slug] && details[l.slug].cta !== "add_to_cart");
  const unresolved = lines.filter(l => !details[l.slug]);
  const totals=exactPackTotals(lines.map(l=>({quantity:l.quantity,priceMinor:details[l.slug]?.price_minor??null})),packCount);
  const total=totals.perPackMinor??0;
  // Estimate from the latest known supplier/list prices — never a sale price (carts use live offers only).
  const knownPrice = (slug: string) => details[slug]?.price_minor ?? details[slug]?.list_price_minor ?? null;
  const estimatedTotals=exactPackTotals(lines.map(l=>({quantity:l.quantity,priceMinor:knownPrice(l.slug)})),packCount);
  const estimate=!refreshing && estimatedTotals.status==="exact"?estimatedTotals.perPackMinor:null;
  const orgOnly = lines.filter(l => !(details[l.slug]?.allowed_channels??["retail","organization"]).includes("retail"));
  const orgAllowed=lines.every(l=>(details[l.slug]?.allowed_channels??["retail","organization"]).includes("organization"));
  const personalAllowed=lines.every(l=>(details[l.slug]?.allowed_channels??["retail","organization"]).includes("retail"));
  const completePrice = lines.length > 0 && !refreshing && !unpriced.length && totals.status==="exact";
  const canBuy = completePrice && !unavailable.length && !unresolved.length;
  const valid = (orgAllowed||personalAllowed) && validCount && lines.length > 0 && !refreshing && !unresolved.length && totals.status!=="invalid";
  const goReview=()=>{setReview(true);window.scrollTo({top:0,behavior:"auto"});};
  async function submit() {
    if (busy || !valid || done) return;
    if (!token) { router.push("/login?next=/pack-builder"); return; }
    setBusy(true); setError("");
    try {
      if (canBuy) {
        for (const l of lines) {
          if (added.current.has(l.slug)) continue;
          // Cart validates offer, stock and quantity on the server; only real SKU IDs are sent.
          await cart.add(token, details[l.slug].product.sku_id, l.quantity * packCount);
          added.current.add(l.slug);
        }
        setDone("cart");
      } else {
        requestKey.current ||= newIdempotencyKey();
        await apiRequest("/requests", { token, method: "POST", headers: { "Idempotency-Key": requestKey.current }, body: JSON.stringify({
          kind: "price", subject: "استعلام قیمت پک سفارشی", message: `تعداد پک: ${packCount}`, organization_id: null,
          items: lines.map(l => ({ slug: l.slug, quantity: l.quantity * packCount })),
        }) });
        setDone("request");
      }
    } catch (e) { setError((e instanceof Error ? e.message : "ثبت ناموفق بود") + (added.current.size ? "؛ اقلام ثبت‌شده در سبد محفوظ‌اند. ادامه فقط اقلام باقی‌مانده را اضافه می‌کند." : "")); }
    finally { setBusy(false); }
  }
  useEffect(() => { onStep(done ? 3 : review ? 2 : 1); }, [done, review, onStep]);
  const locked = busy || added.current.size > 0 || done !== null;
  const units = lines.reduce((n,l) => n+l.quantity,0);
  const composition = <div className="rounded-2xl border bg-white p-4 sm:p-5" style={{ borderColor: UI.line }}>
    <h3 className="mb-2 text-xl font-black" style={{ color: UI.ink }}>ترکیب هر پک</h3>
    {!lines.length && <p className="py-6 text-sm" style={{ color: UI.muted }}>از کاتالوگ پایین، اولین کالا را به پک اضافه کنید.</p>}
    <ul className="divide-y divide-neutral-100">{lines.map(l => <li key={l.slug} className="flex flex-wrap items-center gap-3 py-3">
      <div className="h-16 w-14 shrink-0"><ProductImage src={details[l.slug]?.product.images[0] ?? l.imageUrl} title={l.title} /></div>
      <div className="min-w-0 flex-1"><p className="text-sm font-bold" style={{ color: UI.ink }}>{details[l.slug]?.product.title_fa ?? l.title}</p><p className="mt-1 text-xs" style={{ color: UI.muted }}>{refreshing ? "در حال بررسی…" : !details[l.slug] ? "دریافت اطلاعات ناموفق" : details[l.slug].price_minor != null ? formatPrice(details[l.slug].price_minor!) : details[l.slug].list_price_minor ? `قیمت فهرست ${formatPrice(details[l.slug].list_price_minor!)}` : "استعلام قیمت"}{details[l.slug]?.org_only && " · ویژه خرید سازمانی"}{details[l.slug]?.cta === "request_quote" && " · خرید مستقیم در دسترس نیست"}</p></div>
      <div className="flex items-center gap-2">{!review && <button type="button" disabled={locked || l.quantity <= 1} aria-label={`کاهش تعداد ${l.title}`} onClick={() => changeQty(l.slug, -1)} className="flex h-11 w-11 items-center justify-center rounded-lg border disabled:opacity-40"><Minus className="h-4 w-4" /></button>}<span className="min-w-6 text-center text-sm font-bold">{toPersianNum(l.quantity)}{review && details[l.slug]?.product.unit ? " " + details[l.slug].product.unit : ""}</span>{!review && <><button type="button" disabled={locked} aria-label={`افزایش تعداد ${l.title}`} onClick={() => changeQty(l.slug, 1)} className="flex h-11 w-11 items-center justify-center rounded-lg border"><Plus className="h-4 w-4" /></button><button type="button" disabled={locked} aria-label={`حذف ${l.title}`} onClick={() => update(lines.filter(x => x.slug !== l.slug))} className="flex h-11 w-11 items-center justify-center text-red-700"><Trash2 className="h-4 w-4" /></button></>}</div>
    </li>)}</ul>
    {!!lines.length && !completePrice && !refreshing && <p className="mt-2 text-xs" style={{ color: UI.muted }}>قیمت اقلام فاقد قیمت با استعلام مشخص می‌شود</p>}
  </div>;
  return <section className="space-y-5 pb-24 lg:pb-0" aria-label="ساخت و بررسی پک">
    {!locked && <button type="button" onClick={review ? () => setReview(false) : onBack} className="min-h-11 rounded-xl border bg-white px-4 text-sm font-bold" style={{ color: UI.ink, borderColor: UI.line }}>{review ? "بازگشت به ویرایش" : "تغییر روش ساخت"}</button>}
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_364px]">
      <div className="min-w-0 space-y-5">
        {composition}
        {!review && <div className="space-y-4">
          <h3 className="text-xl font-black md:text-2xl" style={{ color: UI.ink }}>کاتالوگ کالا برای تکمیل پک</h3>
          <div className="grid gap-3 rounded-2xl p-4 sm:grid-cols-2" style={{ background: UI.warm }}>
            <label className="space-y-1 text-sm"><span>جستجوی کالا یا برند</span><input className={inputClass} value={query} onChange={e => {setQuery(e.target.value);setPage(1);}} placeholder="نام کالا یا برند" /></label>
            <label className="space-y-1 text-sm"><span>دسته‌بندی</span><select className={inputClass} value={category} onChange={e => {setCategory(e.target.value);setPage(1);}}><option value="">همه دسته‌ها</option>{categories.map(c => <option key={c.slug} value={c.slug}>{c.name_fa}</option>)}</select></label>
          </div>
          {searchError && <p role="alert" className="py-4 text-sm text-red-700">{searchError}</p>}
          {loading ? <p role="status" className="py-8 text-center" style={{ color: UI.muted }}>در حال دریافت کالاها…</p> : <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">{products.map(p => <article key={p.slug} className="flex min-w-0 flex-col rounded-2xl border bg-white p-3" style={{ borderColor: UI.line }}>
            <div className="mb-3 aspect-square"><ProductImage src={p.image_url} title={p.title_fa} /></div>
            <Link href={`/products/${p.slug}`} className="mb-2 line-clamp-2 min-h-10 text-sm font-bold" style={{ color: UI.ink }}>{p.title_fa}</Link>
            <p className="mb-3 text-sm font-black" style={{ color: UI.ink }}>{p.price_minor != null ? formatPrice(p.price_minor) : p.list_price_minor ? `قیمت فهرست ${formatPrice(p.list_price_minor)}` : "استعلام قیمت"}</p>
            <button type="button" disabled={locked || (!lines.some(l=>l.slug===p.slug) && lines.length>=50)} onClick={() => add(p)} className="mt-auto min-h-11 rounded-xl border text-sm font-bold disabled:opacity-50" style={{ color: UI.ink, borderColor: UI.line }} aria-label={`افزودن ${p.title_fa}`}>افزودن به پک</button>
          </article>)}</div>}
          {!loading&&!searchError&&productTotal>0&&<div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 text-xs" style={{borderColor:UI.line,color:UI.muted}}><span>{toPersianNum(productTotal)} کالای قابل بررسی</span>{pages>1&&<nav aria-label="صفحه‌های کالای پک" className="flex items-center gap-3"><button type="button" disabled={page<=1} onClick={()=>setPage(v=>v-1)} className="min-h-11 rounded-lg border px-3 disabled:opacity-40">قبلی</button><span>{toPersianNum(page)} از {toPersianNum(pages)}</span><button type="button" disabled={page>=pages} onClick={()=>setPage(v=>v+1)} className="min-h-11 rounded-lg border px-3 disabled:opacity-40">بعدی</button></nav>}</div>}
          {!loading && !searchError && !products.length && <p className="py-8 text-center text-sm" style={{ color: UI.muted }}>کالایی یافت نشد؛ عبارت یا دسته را تغییر دهید.</p>}
        </div>}
      </div>
      <aside className="space-y-3 rounded-2xl p-4 sm:p-5 lg:sticky lg:top-44" style={{ background: UI.warm }} aria-label="خلاصه پک">
        <h3 className="text-xl font-black" style={{ color: UI.ink }}>خلاصه پک شما</h3>
        <p className="text-sm" style={{ color: UI.ink }}>{toPersianNum(lines.length)} نوع کالا · {toPersianNum(units)} قلم در هر پک</p>
        <label className="grid grid-cols-2 items-center gap-3 text-sm">تعداد پک<input aria-label="تعداد پک" type="text" inputMode="numeric" role="spinbutton" aria-valuemin={1} aria-valuemax={100000} aria-valuenow={validCount?packCount:undefined} value={count} disabled={locked} onChange={e => { setCount(e.target.value); setReview(false); requestKey.current = ""; }} className={inputClass} /></label>
        {!validCount && <p role="alert" className="text-xs text-red-700">تعداد پک باید عدد صحیح بین ۱ و ۱۰۰٬۰۰۰ باشد.</p>}
        {lines.length>0&&validCount&&totals.status==="invalid"&&<p role="alert" className="text-xs leading-6 text-red-700">تعداد کل هر قلم در همه پک‌ها حداکثر ۱۰۰٬۰۰۰ است؛ مبلغ هم باید بدون خطای عددی قابل محاسبه باشد.</p>}
        {validCount&&lines.length>0&&<p className="text-xs" style={{color:UI.muted}}>در مجموع {toPersianNum(packCount)} پک و {toPersianNum(units*packCount)} قلم درخواست می‌شود.</p>}
        <p className="text-sm font-bold" style={{ color: UI.ink }}>بهای اقلام هر پک: {completePrice ? formatPrice(total) : lines.length ? "استعلام قیمت" : "—"}</p>
        <p className="text-base font-black" style={{ color: UI.ink }}>جمع بهای اقلام: {completePrice && validCount ? formatPrice(totals.totalMinor!) : lines.length ? "پس از استعلام" : "—"}</p>
        {!completePrice && estimate != null && <div className="rounded-xl bg-white p-3 text-xs leading-6" style={{ color: UI.ink }}>
          <p>برآورد هر پک: <b className="tabular-nums">{formatPrice(estimate)}</b>{validCount && packCount > 1 ? <> · برآورد کل: <b className="tabular-nums">{formatPrice(estimatedTotals.totalMinor!)}</b></> : null}</p>
          <p style={{ color: UI.muted }}>برآورد بر اساس آخرین قیمت اعلامی تأمین‌کننده است، نه قیمت نهایی؛ قیمت نهایی و موجودی در استعلام تأیید می‌شود.</p></div>}
        {!orgAllowed&&!personalAllowed&&<p role="alert" className="text-xs">اقلام شخصی و صرفاً سازمانی را در دو پک جدا ثبت کنید؛ این ترکیب کانال مشترک ندارد.</p>}{!!orgOnly.length && <p className="text-[11px] leading-5 text-sky-900">{toPersianNum(orgOnly.length)} کالای عمده/سازمانی در پک است؛ ثبت فقط از مسیر خرید سازمانی.</p>}
        {!!unpriced.length && !refreshing && <p className="text-[11px] leading-5 text-amber-800">{toPersianNum(unpriced.length)} نوع کالا بدون قیمت؛ جمع نهایی با استعلام.</p>}
        {!!unavailable.length && <p className="text-[11px] leading-5 text-amber-800">{toPersianNum(unavailable.length)} نوع کالا نیازمند تأیید موجودی / فروش.</p>}
        {!refreshing && !!unresolved.length && <button type="button" onClick={() => setRefresh(x => x+1)} className="min-h-11 text-sm text-brand-blue">تلاش دوباره برای دریافت قیمت و موجودی</button>}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        {done ? <div role="status"><p className="mb-3 text-sm text-emerald-800">{done === "cart" ? "پک به سبد خرید افزوده شد." : "درخواست استعلام ثبت شد."}</p><Link href={done === "cart" ? "/cart" : "/requests"} className="flex min-h-11 items-center justify-center rounded-xl px-4 text-sm font-bold text-white" style={{ background: UI.ink }}>{done === "cart" ? "ادامه خرید در سبد" : "پیگیری درخواست"}</Link></div> : <button type="button" disabled={!valid || busy} onClick={review ? (orgOnly.length ? () => setOrgOpen(true) : submit) : goReview} className="min-h-11 w-full rounded-xl px-3 py-3 text-sm font-bold text-white disabled:opacity-50" style={{ background: UI.ink }}>{busy ? "در حال ثبت…" : !review ? "بررسی پک و ادامه" : orgOnly.length ? "ادامه در خرید سازمانی" : !token ? "ورود و ادامه" : canBuy ? "افزودن پک به سبد خرید" : "ثبت استعلام قیمت"}</button>}
        {review && valid && !locked && orgAllowed && !orgOnly.length && <button type="button" onClick={() => setOrgOpen(true)} className="min-h-11 w-full rounded-xl border bg-white text-sm font-bold" style={{ color: UI.ink, borderColor: UI.line }}>خرید برای سازمان</button>}
        <p className="text-xs leading-5" style={{ color: UI.muted }}>{review && !canBuy ? "برای اقلام فاقد قیمت، درخواست استعلام ثبت می‌شود. پرداخت پس از تأیید قیمت و موجودی است." : "قیمت و موجودی در زمان ثبت بررسی می‌شود."}</p>
      </aside>
    </div>
    {!review&&lines.length>0&&<div className="fixed inset-x-4 bottom-20 z-40 flex items-center justify-between gap-3 rounded-2xl border bg-white p-3 shadow-lg lg:hidden" style={{borderColor:UI.line}}><div><b className="text-xs" style={{color:UI.ink}}>{toPersianNum(lines.length)} نوع کالا · {validCount?toPersianNum(packCount):"—"} پک</b><p className="mt-1 text-[10px]" style={{color:UI.muted}}>{completePrice&&validCount?formatPrice(totals.totalMinor!):"قیمت نهایی پس از استعلام"}</p></div><button type="button" disabled={!valid||busy} onClick={goReview} className="min-h-11 rounded-xl px-4 text-xs font-bold text-white disabled:opacity-40" style={{background:UI.ink}}>بررسی پک</button></div>}
    {orgOpen && <PackOrgRequest lines={lines.map((l,key) => ({ key, slug:l.slug, name:l.title, qty:l.quantity*packCount, masterProductId:details[l.slug]?.product.master_product_id ?? null, unit:details[l.slug]?.product.unit ?? null }))} purposeLabel="پک سفارشی" onClose={() => setOrgOpen(false)} />}
  </section>;
}
