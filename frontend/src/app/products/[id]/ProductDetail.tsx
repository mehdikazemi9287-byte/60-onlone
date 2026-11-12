"use client";

// Marketplace product page. Everything comes from /storefront/products/:slug — REAL products and sellers
// only. A price appears only from a seller offer whose price and stock were confirmed in the last 24h;
// otherwise the page offers a quote / purchase request instead of any estimated price.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, Building2, CheckCircle2, Clock, ImageOff, PackageCheck, ShieldCheck, Store } from "lucide-react";
import { addProductToOrgDraft } from "@/lib/procurement/draft";
import { apiRequest, cart as cartApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useOrganization } from "@/components/organization/Dashboard";
import { PRICING_MODE_FA, SALE_BLOCKER_FA, storefront, type Card, type Offer, type ProductPage, type SpecGroup } from "@/lib/storefront";
import { cn, faDate, formatPrice, toPersianNum } from "@/lib/utils";
import { isTinyImage } from "@/components/product/ProductCard";
import { BuyBoxOffers } from "@/components/product/BuyBoxOffers";
import { WatchButton } from "@/components/price-watch/WatchButton";

const STOCK_FA: Record<Offer["stock_state"], string> = { in_stock: "موجود", out_of_stock: "ناموجود", unknown: "موجودی تأییدنشده" };

function OrgRequestBox({ product }: { product: { name: string; master_product_id?: number | null; image_url?: string | null; sku?: string } }) {
  const [qty, setQty] = useState(1);
  const [lines, setLines] = useState<number | null>(null);
  return (
    <div className="grid gap-2 sm:grid-cols-[120px_1fr]">
      <label className="grid gap-1 text-xs font-bold text-neutral-700">تعداد
        <input type="number" min={1} max={100000} inputMode="numeric" value={qty} aria-label="تعداد برای درخواست سازمانی"
          onChange={(e) => setQty(Math.min(100000, Math.max(1, Math.floor(Number(e.target.value)) || 1)))}
          className="h-11 rounded-xl border border-neutral-200 bg-white px-3 text-center text-sm font-bold tabular-nums" />
      </label>
      {lines == null ? (
        <button type="button" onClick={() => setLines(addProductToOrgDraft(product, qty))}
          className="h-11 self-end rounded-xl bg-brand-navy px-4 text-sm font-bold text-white hover:bg-brand-navyLight">افزودن به درخواست سازمانی</button>
      ) : (
        <Link href="/organization/compose" className="flex h-11 items-center justify-center self-end rounded-xl bg-emerald-600 px-4 text-sm font-bold text-white">
          افزوده شد · ادامه در میز سفارش ({toPersianNum(lines)} قلم)
        </Link>
      )}
    </div>
  );
}

function StockAlert({ slug }: { slug: string }) {
  const { token } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<string | null>(null), [busy, setBusy] = useState(false);
  useEffect(() => { if (token) apiRequest<{ status: string | null }>(`/storefront/products/${encodeURIComponent(slug)}/alert`, { token }).then((r) => setStatus(r.status)).catch(() => {}); }, [token, slug]);
  const toggle = async () => {
    if (!token) { router.push(`/login?next=/products/${encodeURIComponent(slug)}`); return; }
    setBusy(true);
    try { const r = await apiRequest<{ status: string }>(`/storefront/products/${encodeURIComponent(slug)}/alert`, { token, method: status === "active" ? "DELETE" : "POST" }); setStatus(r.status); }
    catch { /* already available or not found: the page state stays honest */ } finally { setBusy(false); }
  };
  return (
    <button type="button" onClick={toggle} disabled={busy} className="flex h-11 w-full items-center justify-center rounded-xl border border-brand-navy text-sm font-bold text-brand-navy disabled:opacity-60">
      {status === "active" ? "خبرم می‌کنید ✓ (لغو)" : status === "notified" ? "موجود شد؛ اطلاع داده شد" : "موجود شد خبرم کن"}
    </button>
  );
}

function MiniCard({ c }: { c: Card }) {
  const [bad, setBad] = useState(false);
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => { const el = ref.current; if (el?.complete && (el.naturalWidth === 0 || isTinyImage(el))) setBad(true); }, []);
  return (
    <Link href={`/products/${c.slug}`} className="flex min-w-0 flex-col gap-2 rounded-2xl border border-neutral-200 bg-white p-3 hover:border-brand-blue">
      <span className="flex aspect-square items-center justify-center overflow-hidden rounded-xl bg-neutral-50">
        {c.image_url && !bad ? <img ref={ref} src={c.image_url} alt={c.title_fa} className="h-full w-full object-contain p-2"
          onError={() => setBad(true)} onLoad={(e) => { if (isTinyImage(e.currentTarget)) setBad(true); }} /> : <ImageOff className="h-8 w-8 text-neutral-300" />}
      </span>
      <span className="line-clamp-2 min-h-[40px] text-sm font-bold text-neutral-900">{c.title_fa}</span>
      <span className="text-xs text-neutral-500">{c.brand_fa}{c.variant_count > 1 ? ` · ${toPersianNum(c.variant_count)} مدل` : ""}</span>
      <span className="text-sm font-black text-brand-navy">{c.price_minor != null ? formatPrice(c.price_minor) : "استعلام قیمت"}</span>
    </Link>
  );
}

export default function ProductDetail({ initial }: { initial: ProductPage }) {
  const { token } = useAuth();
  const router = useRouter();
  const [d, setD] = useState(initial);
  const [img, setImg] = useState(0);
  const eligible = d.offers.find((o) => o.eligible);
  const moq = eligible?.min_order_quantity ?? 1;
  const [qty, setQty] = useState(moq);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const p = d.product;
  const allowed=d.allowed_channels??p.allowed_channels??["retail","organization"];
  const personalAllowed=allowed.includes("retail"),orgAllowed=allowed.includes("organization");
  // Broken or sub-200px source images are dropped so the gallery shows the explicit no-image state.
  const [badImages, setBadImages] = useState<string[]>([]);
  const images = p.images.filter((u) => !badImages.some((b) => b.endsWith(u)));
  const dropImage = (src: string) => { setBadImages((b) => (b.includes(src) ? b : [...b, src])); setImg(0); };
  // Server-rendered images can finish loading before hydration (no onLoad), so re-check them after mount.
  const gallery = useRef<HTMLElement>(null);
  useEffect(() => {
    gallery.current?.querySelectorAll("img").forEach((el) => {
      if (el.complete && (el.naturalWidth === 0 || isTinyImage(el))) dropImage(el.src);
    });
  });
  const org = useOrganization(!!token);
  const inOrg = org.orgs.length > 0;

  // Organization/contract tiers are only returned to signed-in organization members.
  useEffect(() => { if (token) storefront.product(p.slug, token).then(setD).catch(() => {}); }, [token, p.slug]);
  useEffect(() => { setImg(0); setQty(moq); setMsg(null); }, [p.slug, moq]);

  const add = async () => {
    if (!token) { router.push(`/login?next=/products/${encodeURIComponent(p.slug)}`); return; }
    if (busy) return;
    setBusy(true); setMsg(null);
    try { await cartApi.add(token, p.sku_id, qty); setMsg({ ok: true, text: "به سبد خرید افزوده شد." }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "افزودن ناموفق بود" }); }
    finally { setBusy(false); }
  };

  const specGroups = (d.spec_groups ?? []).filter((g) => g.items.length > 0);
  return (
    <div className="container-page py-6" dir="rtl">
      <nav aria-label="مسیر" className="mb-4 flex flex-wrap items-center gap-1 text-xs text-neutral-500">
        <Link href="/" className="hover:text-brand-blue">خانه</Link>
        {d.breadcrumbs.map((b) => <span key={b.slug} className="flex items-center gap-1">/<Link href={`/category/${b.slug}`} className="hover:text-brand-blue">{b.name_fa}</Link></span>)}
        <span className="flex min-w-0 items-center gap-1">/<span aria-current="page" className="max-w-[16rem] truncate text-neutral-700">{p.title_fa}</span></span>
      </nav>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <section ref={gallery} aria-label="تصاویر" className="min-w-0">
          <div className="flex aspect-square items-center justify-center overflow-hidden rounded-3xl border border-neutral-200 bg-white">
            {images[img] ? <img src={images[img]} alt={p.title_fa} className="h-full w-full object-contain p-6"
                onError={(e) => dropImage(e.currentTarget.src)} onLoad={(e) => { if (isTinyImage(e.currentTarget)) dropImage(e.currentTarget.src); }} />
              : <span className="flex flex-col items-center gap-2 text-sm text-neutral-400"><ImageOff className="h-12 w-12" />تصویر معتبر ثبت نشده است</span>}
          </div>
          {images.length > 1 && <div className="mt-3 flex gap-2 overflow-x-auto">{images.map((u, i) => (
            <button key={u} type="button" onClick={() => setImg(i)} aria-label={`تصویر ${toPersianNum(i + 1)}`}
              className={cn("h-16 w-16 flex-none overflow-hidden rounded-xl border bg-white", i === img ? "border-brand-blue" : "border-neutral-200")}>
              <img src={u} alt="" className="h-full w-full object-contain p-1"
                onError={(e) => dropImage(e.currentTarget.src)} onLoad={(e) => { if (isTinyImage(e.currentTarget)) dropImage(e.currentTarget.src); }} /></button>))}</div>}
        </section>

        <section className="min-w-0 space-y-4">
          <div>
            {p.brand_fa && <span className="text-sm font-bold text-brand-blue">{p.brand_fa}</span>}
            <h1 className="mt-1 text-xl font-black leading-9 text-brand-navy md:text-2xl">{p.title_fa}</h1>
            <p className="mt-1 text-xs text-neutral-500">کد کالا: <span dir="ltr">{p.sku}</span>{p.variant_label ? ` · ${p.variant_label}` : ""}</p>
          </div>

          {d.variants.length > 1 && (
            <div>
              <p className="mb-2 text-sm font-bold text-neutral-800">انتخاب مدل / اندازه</p>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="انتخاب مدل">
                {d.variants.map((v) => (
                  <Link key={v.slug} href={`/products/${v.slug}`} role="radio" aria-checked={v.selected} scroll={false}
                    className={cn("rounded-xl border px-3 py-2 text-sm font-bold", v.selected ? "border-brand-navy bg-brand-navy text-white" : "border-neutral-200 bg-white text-neutral-800 hover:border-brand-blue")}>
                    {v.label ?? v.title_fa}
                    {v.price_minor != null && <span className="block text-[11px] font-normal opacity-80">{formatPrice(v.price_minor)}</span>}
                  </Link>))}
              </div>
            </div>
          )}

          <div className="rounded-2xl border border-neutral-200 bg-white p-4">
            {d.price_minor != null ? (
              <>
                <p className="text-2xl font-black text-brand-navy">{formatPrice(d.price_incl_vat_minor ?? d.price_minor)}</p>
                {d.unit_price && <p className="mt-0.5 text-xs font-bold text-neutral-600 tabular-nums">{d.unit_price.label_fa}: {formatPrice(Math.round(d.unit_price.price_minor * (1 + (d.vat_bps ?? 0) / 10000)))}</p>}
                {d.vat_bps ? <p className="text-[11px] text-neutral-500">با احتساب {toPersianNum(d.vat_bps / 100)}٪ مالیات بر ارزش افزوده</p> : null}
                <p className="mt-1 flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-4 w-4" /> قیمت و موجودی تأییدشده فروشنده (۲۴ ساعت اخیر)</p>
              </>
            ) : (
              <>
                {d.list_price_minor ? (
                  <>
                    <p className="text-xs font-bold text-neutral-500">آخرین قیمت اعلامی تأمین‌کننده{faDate(d.list_price_at) ? ` · ${faDate(d.list_price_at)}` : ""}</p>
                    <p className="mt-1 text-2xl font-black text-brand-navy tabular-nums">{formatPrice(d.list_price_minor)}</p>
                    <p className="mt-2 text-xs leading-6 text-neutral-600">این قیمت فهرست تأمین‌کننده است، نه قیمت نهایی فروش؛ قیمت نهایی و موجودی هنگام استعلام تأیید می‌شود.</p>
                  </>
                ) : (
                  <>
                    <p className="inline-flex rounded-full bg-amber-50 px-3 py-1 text-sm font-bold text-amber-800 ring-1 ring-amber-200">قیمت با استعلام</p>
                    <p className="mt-2 text-xs leading-6 text-neutral-600">{SALE_BLOCKER_FA[d.sale_blocker ?? ""] ?? "خرید مستقیم این کالا فعلاً ممکن نیست."}</p>
                  </>
                )}
                {d.org_only && <p className="mt-2 rounded-lg bg-sky-50 px-3 py-2 text-xs font-bold text-sky-900">بسته‌بندی عمده / ویژه سازمان‌ها؛ فقط از مسیر خرید سازمانی قابل سفارش است.</p>}
              </>
            )}
            <div className="mt-4 space-y-3">
              {d.cta === "add_to_cart" ? (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="grid gap-1 text-xs font-bold text-neutral-700">تعداد
                    <input type="number" inputMode="numeric" min={moq} max={eligible?.max_order_quantity ?? 999} value={qty} aria-label="تعداد"
                      onChange={(e) => setQty(Math.max(moq, Math.floor(Number(e.target.value)) || moq))}
                      className="h-11 w-24 rounded-xl border border-neutral-200 px-3 text-center font-bold tabular-nums" />
                  </label>
                  <button type="button" onClick={add} disabled={busy} className="h-11 flex-1 rounded-xl bg-brand-coral px-5 text-sm font-bold text-white disabled:opacity-60">
                    {busy ? "در حال افزودن…" : "افزودن به سبد خرید"}</button>
                </div>
              ) : !personalAllowed ? null : (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="grid gap-1 text-xs font-bold text-neutral-700">تعداد
                    <input type="number" min="1" max="100000" value={qty} aria-label="تعداد" onChange={e => setQty(Math.min(100000, Math.max(1, Math.floor(Number(e.target.value)) || 1)))} className="h-11 w-24 rounded-xl border border-neutral-200 px-3 text-center font-bold" />
                  </label>
                  <Link href={`/requests/new?slug=${encodeURIComponent(p.slug)}&quantity=${qty}`} className="flex min-h-11 flex-1 items-center justify-center rounded-xl bg-brand-coral px-3 py-3 text-center text-sm font-bold text-white">استعلام قیمت / درخواست خرید</Link>
                </div>
              )}
              {d.cta !== "add_to_cart" && personalAllowed ? (
                <StockAlert slug={p.slug} />
              ) : (
                <WatchButton slug={p.slug} fullWidth />
              )}
              {msg && <p role="status" className={cn("rounded-xl px-3 py-2 text-sm", msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800")}>{msg.text}{msg.ok && <> — <Link href="/cart" className="font-bold underline">مشاهده سبد</Link></>}</p>}
              <div className="border-t border-neutral-100 pt-3">
                <p className="mb-2 flex items-center gap-1 text-xs font-bold text-neutral-700"><Building2 className="h-4 w-4" /> خرید سازمانی / عمده</p>
                {orgAllowed ? (inOrg ? <OrgRequestBox product={{ name: p.title_fa, master_product_id: p.master_product_id, image_url: p.images[0], sku: p.sku }} />
                  : <Link href="/org" className="text-xs font-bold text-brand-blue">خرید عمده یا سازمانی این کالا</Link>) : <p className="text-xs">این کالا فقط برای خرید شخصی عرضه می‌شود.</p>}
              </div>
            </div>
          </div>

          <section aria-label="فروشندگان" className="rounded-2xl border border-neutral-200 bg-white p-4">
            <h2 className="mb-3 flex items-center gap-2 text-base font-black text-brand-navy"><Store className="h-5 w-5" /> فروشندگان این کالا</h2>
            {!d.offers.length ? (
              <p className="text-sm leading-7 text-neutral-600">با ثبت استعلام، درخواست شما برای تأمین‌کنندگان این کالا ارسال می‌شود و قیمت روز، موجودی و زمان تحویل به شما اعلام می‌شود.</p>
            ) : (
              <ul className="divide-y divide-neutral-100">
                {d.offers.map((o) => (
                  <li key={o.offer_id} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto]">
                    <div className="min-w-0">
                      <p className="font-bold text-neutral-900">{o.seller}{o.seller_city ? <span className="text-xs font-normal text-neutral-500"> · {o.seller_city}</span> : null}
                        {o.provenance === "test" && <span className="mr-2 rounded bg-violet-100 px-1.5 text-[10px] font-bold text-violet-800">TEST</span>}</p>
                      <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-neutral-600">
                        <span>{PRICING_MODE_FA[o.pricing_mode] ?? o.pricing_mode}</span>
                        <span className="flex items-center gap-1"><PackageCheck className="h-3.5 w-3.5" />{STOCK_FA[o.stock_state]}{o.available != null && o.stock_state === "in_stock" ? ` (${toPersianNum(o.available)})` : ""}</span>
                        <span>حداقل سفارش: {toPersianNum(o.min_order_quantity)}{o.max_order_quantity ? ` · حداکثر ${toPersianNum(o.max_order_quantity)}` : ""}</span>
                        {o.lead_time_days != null && <span className="flex items-center gap-1"><Clock className="h-3.5 w-3.5" />تأمین {toPersianNum(o.lead_time_days)} روز</span>}
                      </p>
                      {(o.tiers.retail.length > 0 || o.tiers.organization.length > 0) && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {o.tiers.retail.map((t, i) => <span key={`r${i}`} className="rounded-lg bg-sky-50 px-2 py-1 text-[11px] text-sky-900">{toPersianNum(t.min_qty)}{t.max_qty ? `–${toPersianNum(t.max_qty)}` : "+"} عدد: {formatPrice(t.unit_price_minor)}</span>)}
                          {o.tiers.organization.map((t, i) => <span key={`o${i}`} className="rounded-lg bg-emerald-50 px-2 py-1 text-[11px] text-emerald-900">سازمانی{t.contract ? " (قرارداد)" : ""} {toPersianNum(t.min_qty)}{t.max_qty ? `–${toPersianNum(t.max_qty)}` : "+"}: {formatPrice(t.unit_price_minor)}</span>)}
                        </div>)}
                    </div>
                    <div className="text-left text-sm font-black text-brand-navy">{o.price_minor != null ? formatPrice(o.price_minor) : o.list_price_minor ? <span className="block">{formatPrice(o.list_price_minor)}<span className="block text-[10px] font-bold text-neutral-500">قیمت فهرست{faDate(o.list_price_at) ? ` · ${faDate(o.list_price_at)}` : ""}</span></span> : <span className="text-xs font-bold text-amber-700">قیمت تأییدنشده</span>}</div>
                  </li>))}
              </ul>
            )}
            {!d.sales_enabled && d.offers.some((o) => o.price_minor != null) && (
              <p className="mt-2 flex items-start gap-1 text-xs text-amber-800"><AlertTriangle className="h-4 w-4 flex-none" /> خرید آنلاین تا اتصال درگاه پرداخت فعال نیست؛ از «درخواست خرید» استفاده کنید.</p>)}
          </section>
          <BuyBoxOffers slug={p.slug} vatBps={d.vat_bps} />
        </section>
      </div>

      {(p.description_fa || p.specs.length > 0 || specGroups.length > 0) && (
        <section className="mt-8 grid gap-6 lg:grid-cols-2">
          {p.description_fa && <div className="rounded-2xl border border-neutral-200 bg-white p-5"><h2 className="mb-2 text-base font-black text-brand-navy">معرفی کالا</h2><p className="text-sm leading-8 text-neutral-700">{p.description_fa}</p></div>}
          {specGroups.length > 0 ? <SpecTable groups={specGroups} /> : p.specs.length > 0 && <div className="rounded-2xl border border-neutral-200 bg-white p-5"><h2 className="mb-2 text-base font-black text-brand-navy">مشخصات</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">{p.specs.map((s) => <div key={s.label} className="contents"><dt className="text-neutral-500">{s.label}</dt><dd className="font-bold text-neutral-800">{typeof s.value === "object" ? JSON.stringify(s.value) : String(s.value)}</dd></div>)}</dl></div>}
        </section>
      )}
      <p className="mt-6 flex items-center gap-1 text-xs text-neutral-500"><ShieldCheck className="h-4 w-4" /> مشخصات کالا از منبع رسمی برند ثبت شده است. قیمتی که می‌بینید همیشه قیمت تأییدشده فروشنده است، نه قیمت تخمینی.</p>

      {d.alternatives.length > 0 && <section className="mt-8"><h2 className="mb-3 text-lg font-black text-brand-navy">جایگزین‌های هم‌نوع</h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{d.alternatives.slice(0, 8).map((c) => <MiniCard key={c.slug} c={c} />)}</div></section>}
      {d.related.length > 0 && <section className="mt-8"><h2 className="mb-3 text-lg font-black text-brand-navy">کالاهای مرتبط</h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{d.related.slice(0, 8).map((c) => <MiniCard key={c.slug} c={c} />)}</div></section>}
    </div>
  );
}

/** Phase 6 grouped specification table (display groups as headings). */
function SpecTable({ groups }: { groups: SpecGroup[] }) {
  return (
    <div className="min-w-0 rounded-2xl border border-neutral-200 bg-white p-5">
      <h2 className="mb-3 text-base font-black text-brand-navy">مشخصات فنی</h2>
      {groups.map((g) => (
        <table key={g.group_fa} className="mb-4 w-full table-fixed border-collapse text-sm last:mb-0">
          <caption className="mb-1 text-right text-xs font-black text-brand-blue">{g.group_fa}</caption>
          <tbody>{g.items.map((i) => (
            <tr key={i.code} className="border-t border-neutral-100">
              <th scope="row" className="w-2/5 py-2 pl-3 text-right align-top font-normal text-neutral-500">{i.label_fa}</th>
              <td className="break-words py-2 font-bold text-neutral-800">{i.value_fa}</td>
            </tr>))}</tbody>
        </table>
      ))}
    </div>
  );
}
