"use client";

// Supplier marketplace offers: price, stock, MOQ/max, lead time, pricing mode, channel, validity and
// quantity tiers per SKU. Prices/stock count as verified for 24h after "confirm"; every change is audited.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Lock, Plus, RefreshCcw, Search, Tag } from "lucide-react";
import { apiRequest, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { PRICING_MODE_FA } from "@/lib/storefront";
import { formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Drawer, Empty, Notice, cx, n } from "./ui";
import s from "./proc.module.css";

type TierRow = { channel: "retail" | "organization"; min_qty: number; max_qty: number | null; unit_price_minor: number; organization_id?: number | null };
type Offer = { effective_channel?:string|null;product_supply_channel?:string;product_active?:boolean;allowed_channels?:string[]; id: number; product_id: number; pricing_mode: string; channel: string; selling_price_minor: number; stock_quantity: number;
  stock_reserved: number; min_order_quantity: number; max_order_quantity: number | null; lead_time_days: number | null; valid_until: string | null;
  supplier_sku: string | null; source_reference:string|null; provenance: string; last_price_confirmed_at: string | null; fresh: boolean; tiers: TierRow[];
  product: { slug: string; sku: string; title_fa: string; variant_label: string | null } | null };
type Sellable = { product_supply_channel?:string;allowed_channels?:string[]; product_id: number; slug: string; sku: string; title_fa: string; variant_label: string | null; brand_fa: string };

const toman = (minor: number | null | undefined) => (minor ? `${n(Math.round(minor / 10))} تومان` : "—");

export default function SupplierOffers() {
  const { token, user, loading } = useAuth();
  const [items, setItems] = useState<Offer[] | null>(null), [error, setError] = useState(""), [flash, setFlash] = useState("");
  const [edit, setEdit] = useState<null | { offer?: Offer; product?: Sellable }>(null), [pick, setPick] = useState(false);
  const load = useCallback(() => {
    if (!token) return;
    apiRequest<{ items: Offer[] }>("/supplier/marketplace/offers", { token }).then((r) => { setItems(r.items); setError(""); }).catch((e) => setError(e.message));
  }, [token]);
  useEffect(load, [load]);
  const confirm = async (o: Offer) => {
    try { await apiRequest(`/supplier/marketplace/offers/${o.id}/confirm`, { token: token!, method: "POST" }); setFlash("قیمت و موجودی برای ۲۴ ساعت آینده تأیید شد."); load(); }
    catch (e) { setFlash(e instanceof Error ? e.message : "تأیید ناموفق بود"); }
  };
  if (loading) return <div className={s.root}><div className={s.skeleton} style={{ height: 200 }} /></div>;
  if (!user) return <div className={s.root}><Empty icon={<Lock />} title="ورود حساب تأمین‌کننده لازم است" action={<Link className={cx(s.btn, s.primary)} href="/login?next=/supplier/offers">ورود</Link>} /></div>;
  if (error) return <div className={s.root}><Notice tone="bad" icon={<AlertTriangle />}>{error}</Notice></div>;
  return (
    <div className={s.root}>
      <header className={s.head}>
        <div className={s.headRow}>
          <div><div className={s.eyebrow}><Link href="/supplier/rfqs">میز کار تأمین‌کننده</Link> / پیشنهادهای فروش</div><h1 className={s.title}>کالاها و پیشنهادهای من</h1>
            <div className={s.meta}><span>قیمت و موجودی فقط تا ۲۴ ساعت پس از تأیید در فروشگاه معتبر است.</span></div></div>
          <button className={cx(s.btn, s.primary)} onClick={() => setPick(true)}><Plus /> پیشنهاد برای کالای جدید</button>
        </div>
      </header>
      {flash && <Notice tone="info" icon={<CheckCircle2 />}>{flash}</Notice>}
      {!items ? <div className={s.skeleton} style={{ height: 200 }} /> : !items.length ? (
        <Empty icon={<Tag />} title="هنوز پیشنهادی ثبت نکرده‌اید" action={<button className={cx(s.btn, s.primary)} onClick={() => setPick(true)}>ثبت اولین پیشنهاد</button>}>کالای خود را از کاتالوگ پیدا کنید و قیمت، موجودی و حداقل سفارش را ثبت کنید.</Empty>
      ) : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
          <thead><tr><th>کالا</th><th>قیمت</th><th>موجودی</th><th>حداقل/حداکثر</th><th>تأمین</th><th>وضعیت</th><th /></tr></thead>
          <tbody>{items.map((o) => (
            <tr key={o.id}>
              <td className={s.full}><b>{o.product?.title_fa ?? `#${o.product_id}`}</b><div className={s.small} style={{ color: "var(--muted)" }}>{o.product?.sku}{o.supplier_sku ? ` · کد شما: ${o.supplier_sku}` : ""}</div>
                {o.provenance !== "real" && <Chip tone="warn">{o.provenance.toUpperCase()}</Chip>}</td>
              <td data-label="قیمت">{PRICING_MODE_FA[o.pricing_mode]}<div className={s.small}>{o.pricing_mode === "fixed" || o.pricing_mode === "bulk" ? toman(o.selling_price_minor) : "—"}{o.tiers.length ? ` · ${n(o.tiers.length)} پله` : ""}</div></td>
              <td data-label="موجودی">{n(o.stock_quantity - o.stock_reserved)}<div className={s.small}>رزرو {n(o.stock_reserved)}</div></td>
              <td data-label="حداقل/حداکثر">{n(o.min_order_quantity)} / {o.max_order_quantity ? n(o.max_order_quantity) : "—"}</td>
              <td data-label="تأمین">{o.lead_time_days != null ? `${n(o.lead_time_days)} روز` : "—"}</td>
              <td data-label="وضعیت">{o.fresh ? <Chip tone="ok" dot>تأییدشده</Chip> : <Chip tone="warn" dot>نیازمند تأیید</Chip>}
                {o.last_price_confirmed_at && <div className={s.small} style={{ color: "var(--muted)" }}>{formatJalaliDateTime(o.last_price_confirmed_at.replace(" ", "T") + "Z")}</div>}</td>
              <td><div className={s.row}><button className={cx(s.btn, s.sm)} onClick={() => setEdit({ offer: o })}>ویرایش</button>
                <button className={cx(s.btn, s.sm)} onClick={() => confirm(o)}><RefreshCcw /> تأیید امروز</button></div></td>
            </tr>))}</tbody>
        </table></div>
      )}
      {pick && token && <PickProduct token={token} onClose={() => setPick(false)} onPick={(p) => { setPick(false); setEdit({ product: p }); }} />}
      {edit && token && <OfferForm token={token} edit={edit} onClose={() => setEdit(null)} onSaved={(m) => { setEdit(null); setFlash(m); load(); }} />}
    </div>
  );
}

function PickProduct({ token, onClose, onPick }: { token: string; onClose: () => void; onPick: (p: Sellable) => void }) {
  const [q, setQ] = useState(""), [items, setItems] = useState<Sellable[]>([]);
  useEffect(() => {
    const c = new AbortController();
    const t = setTimeout(() => apiRequest<{ items: Sellable[] }>(`/supplier/marketplace/catalog?q=${encodeURIComponent(q)}`, { token, signal: c.signal })
      .then((r) => setItems(r.items)).catch(() => {}), 250);
    return () => { clearTimeout(t); c.abort(); };
  }, [q, token]);
  return (
    <Drawer open title="انتخاب کالا از کاتالوگ" onClose={onClose}>
      <div className={s.stack}>
        <label className={s.field}>جستجو<span style={{ position: "relative" }}><input className={s.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="نام، برند، اندازه یا کد کالا" style={{ paddingLeft: 34 }} /><Search size={16} style={{ position: "absolute", left: 10, top: 11, color: "var(--muted)" }} /></span></label>
        {items.map((p) => <button key={p.product_id} type="button" className={cx(s.btn, s.ghost)} style={{ justifyContent: "flex-start", height: "auto", padding: "8px 10px", textAlign: "right" }} onClick={() => onPick(p)}>
          <span><b>{p.title_fa}</b><span className={s.small} style={{ display: "block", color: "var(--muted)" }}>{p.brand_fa} · {p.sku}{p.variant_label ? ` · ${p.variant_label}` : ""}</span></span></button>)}
        {!items.length && <p className={s.small} style={{ color: "var(--muted)" }}>کالایی یافت نشد. اگر کالای شما در کاتالوگ نیست، از بخش «ورود کاتالوگ» فایل محصولات را ارسال کنید.</p>}
      </div>
    </Drawer>
  );
}

function OfferForm({ token, edit, onClose, onSaved }: { token: string; edit: { offer?: Offer; product?: Sellable }; onClose: () => void; onSaved: (m: string) => void }) {
  const o = edit.offer;
  const [mode, setMode] = useState(o?.pricing_mode ?? "fixed"), [channel, setChannel] = useState(o?.effective_channel ?? o?.product_supply_channel ?? edit.product?.product_supply_channel ?? o?.channel ?? "both");
  const [price, setPrice] = useState(o ? String(o.selling_price_minor / 10) : ""), [stock, setStock] = useState(String(o?.stock_quantity ?? ""));
  const [moq, setMoq] = useState(String(o?.min_order_quantity ?? 1)), [max, setMax] = useState(o?.max_order_quantity ? String(o.max_order_quantity) : "");
  const [lead, setLead] = useState(o?.lead_time_days != null ? String(o.lead_time_days) : ""), [valid, setValid] = useState(o?.valid_until ?? "");
  const [sku, setSku] = useState(o?.supplier_sku ?? ""), [tiers, setTiers] = useState<TierRow[]>(o?.tiers.map((t) => ({ ...t, unit_price_minor: t.unit_price_minor / 10 })) ?? []);
  const [confirmNow, setConfirmNow] = useState(true), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [source,setSource]=useState(o?.source_reference??'');
  const [orgs, setOrgs] = useState<{ id: number; display_name: string }[]>([]);
  useEffect(() => { apiRequest<{ items: { id: number; display_name: string }[] }>("/supplier/marketplace/organizations", { token }).then((r) => setOrgs(r.items)).catch(() => {}); }, [token]);
  const [key] = useState(newIdempotencyKey);
  const normalize = (v: string) => v.trim().replace(/[۰-۹]/g, x => String(x.charCodeAt(0)-1776)).replace(/[٠-٩]/g, x => String(x.charCodeAt(0)-1632)).replace(/[,،]/g, "").replace(/٫/g,".");
  const int = (v: string) => { const text=normalize(v); if(!text)return null; return /^\d+$/.test(text)&&Number.isSafeInteger(Number(text))?Number(text):NaN; };
  const minor = (v: string) => { const text=normalize(v); if(!/^\d+(\.\d)?$/.test(text))return null; const [whole,fraction="0"]=text.split(".");const value=Number(whole+fraction);return Number.isSafeInteger(value)&&value<=1e13?value:null; };
  const save = async () => {
    setBusy(true); setErr("");
    if(o?.product_active===false){setErr("کالا در کاتالوگ غیرفعال است؛ ابتدا مدیر کالا باید آن را فعال کند.");setBusy(false);return;}
    const amount=minor(price),quantity=int(stock),minimum=int(moq),maximum=int(max),days=int(lead);
    if(amount===null||(amount===0&&o?.selling_price_minor!==0)||quantity===null||minimum===null||![quantity,minimum,maximum,days].every(x=>x===null||Number.isFinite(x))){setErr("قیمت و موجودی معتبر را صریح وارد کنید؛ مقدار نامعلوم صفر نیست. کالای بدون قیمت همچنان در کاتالوگ برای استعلام سازمانی قابل انتخاب است.");setBusy(false);return;}
    if(tiers.some(t=>minor(String(t.unit_price_minor))===null)){setErr("قیمت هر پله باید مبلغ معتبر با حداکثر یک رقم اعشار تومان باشد.");setBusy(false);return;}
    const body = { product_id: o?.product_id ?? edit.product!.product_id, pricing_mode: mode, channel, selling_price_minor: amount,
      stock_quantity: quantity, min_order_quantity: minimum, max_order_quantity: maximum, lead_time_days: days,
      valid_until: valid || null, supplier_sku: sku || null, source_reference:source.trim()||null, confirm: confirmNow,
      tiers: tiers.map((t) => ({ ...t, unit_price_minor: minor(String(t.unit_price_minor)) })) };
    try {
      await apiRequest(o ? `/supplier/marketplace/offers/${o.id}` : "/supplier/marketplace/offers", { token, method: o ? "PUT" : "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": key } });
      onSaved(o ? "پیشنهاد به‌روزرسانی شد." : "پیشنهاد ثبت شد.");
    } catch (e) { setErr(e instanceof Error ? e.message : "ثبت ناموفق بود"); } finally { setBusy(false); }
  };
  const setTier = (i: number, k: keyof TierRow, v: string) => setTiers((ts) => ts.map((t, j) => j !== i ? t : { ...t, [k]: k === "channel" ? v : (v ? Number(v) : k === "max_qty" || k === "organization_id" ? null : 0),
    ...(k === "channel" && v === "retail" ? { organization_id: null } : {}) }));
  return (
    <Drawer open title={o ? `ویرایش پیشنهاد · ${o.product?.title_fa ?? ""}` : `پیشنهاد جدید · ${edit.product?.title_fa}`} onClose={onClose}
      footer={<button className={cx(s.btn, s.primary)} disabled={busy} onClick={save}>{busy ? "در حال ثبت…" : "ذخیره"}</button>}>
      <div className={s.stack}>
        <div className={s.grid2}>
          <label className={s.field}>نوع قیمت‌گذاری<select className={s.select} value={mode} onChange={(e) => setMode(e.target.value)}>{Object.entries(PRICING_MODE_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>کانال فروش<select className={s.select} value={channel} onChange={(e) => setChannel(e.target.value)}><option value="both" disabled={(o?.product_supply_channel??edit.product?.product_supply_channel??"both")!=="both"}>شخصی و سازمانی</option><option value="retail" disabled={(o?.product_supply_channel??edit.product?.product_supply_channel)==="organization"}>فقط شخصی</option><option value="organization" disabled={(o?.product_supply_channel??edit.product?.product_supply_channel)==="retail"}>فقط سازمانی</option></select></label>
          <label className={s.field}>قیمت واحد تأمین‌کننده (تومان)<input className={s.input} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
          <label className={s.field}>موجودی قابل فروش<input className={s.input} inputMode="numeric" value={stock} onChange={(e) => setStock(e.target.value)} /></label>
          <label className={s.field}>حداقل سفارش<input className={s.input} inputMode="numeric" value={moq} onChange={(e) => setMoq(e.target.value)} /></label>
          <label className={s.field}>حداکثر سفارش (اختیاری)<input className={s.input} inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value)} /></label>
          <label className={s.field}>زمان تأمین (روز)<input className={s.input} inputMode="numeric" value={lead} onChange={(e) => setLead(e.target.value)} /></label>
          <label className={s.field}>اعتبار تا (اختیاری)<input className={s.input} type="date" value={valid} onChange={(e) => setValid(e.target.value)} /></label>
          <label className={s.field}>کد کالای شما (اختیاری)<input className={s.input} value={sku} onChange={(e) => setSku(e.target.value)} /></label>
          <label className={s.field}>مرجع قیمت و موجودی تأمین‌کننده<input className={s.input} maxLength={200} value={source} onChange={e=>setSource(e.target.value)}/></label>
        </div>
        <div>
          <div className={s.row} style={{ justifyContent: "space-between" }}><b className={s.small}>پله‌های قیمت عمده</b>
            <button type="button" className={cx(s.btn, s.sm)} onClick={() => setTiers((t) => [...t, { channel: "retail", min_qty: 10, max_qty: null, unit_price_minor: 0 }])}><Plus /> پله</button></div>
          {tiers.map((t, i) => (
            <div key={i} className={s.grid3} style={{ gap: 6, marginTop: 6 }}>
              <select className={s.select} aria-label="کانال پله" value={t.channel} onChange={(e) => setTier(i, "channel", e.target.value)}><option value="retail" disabled={channel==="organization"}>شخصی</option><option value="organization" disabled={channel==="retail"}>سازمانی</option></select>
              {t.channel === "organization" ? <select className={s.select} aria-label="سازمان قرارداد" value={t.organization_id ?? ""} onChange={(e) => setTier(i, "organization_id", e.target.value)}>
                <option value="">همه سازمان‌ها</option>{orgs.map((o) => <option key={o.id} value={o.id}>قرارداد: {o.display_name}</option>)}</select> : <span />}
              <input className={s.input} aria-label="از تعداد" inputMode="numeric" value={t.min_qty || ""} onChange={(e) => setTier(i, "min_qty", e.target.value)} placeholder="از" />
              <input className={s.input} aria-label="تا تعداد" inputMode="numeric" value={t.max_qty ?? ""} onChange={(e) => setTier(i, "max_qty", e.target.value)} placeholder="تا (خالی=بیشتر)" />
              <div className={s.row}><input className={s.input} aria-label="قیمت پله (تومان)" inputMode="numeric" value={t.unit_price_minor || ""} onChange={(e) => setTier(i, "unit_price_minor", e.target.value)} placeholder="قیمت (تومان)" />
                <button type="button" className={cx(s.btn, s.sm, s.danger)} onClick={() => setTiers((ts) => ts.filter((_, j) => j !== i))}>حذف</button></div>
            </div>))}
          <p className={s.small} style={{ color: "var(--muted)" }}>پله‌ها نباید هم‌پوشانی داشته باشند؛ قیمت سازمانی جدا از قیمت خرده ثبت می‌شود. قیمت قراردادی فقط برای سازمان‌هایی قابل ثبت است که با شما استعلام یا سفارش داشته‌اند{orgs.length ? "" : " (هنوز موردی نیست)"}.</p>
        </div>
        <label className={s.row}><input type="checkbox" checked={confirmNow} onChange={(e) => setConfirmNow(e.target.checked)} /> قیمت و موجودی را همین حالا تأیید می‌کنم (اعتبار ۲۴ ساعت)</label>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}
