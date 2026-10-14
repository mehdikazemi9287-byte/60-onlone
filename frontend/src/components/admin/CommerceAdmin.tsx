"use client";

// Platform admin: pack management, catalog review → publish, retail returns.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Lock, Package, Plus, RefreshCcw, RotateCcw, Search } from "lucide-react";
import { apiRequest, catalog, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { PackDetail } from "@/lib/storefront";
import type { Product } from "@/lib/types";
import { formatJalaliDateTime } from "@/lib/procurement/jalali";
import { Chip, Drawer, Empty, Notice, cx, n } from "@/components/procurement/ui";
import s from "@/components/procurement/proc.module.css";

const faDigits = (v: string) => v.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
const REQ_STATUS: Record<string, string> = { open: "جدید", reviewing: "در بررسی", answered: "پاسخ داده شد", closed: "بسته" };

function useAdmin<T>(path: string) {
  const { token, user, loading } = useAuth();
  const [d, setD] = useState<T | null>(null), [error, setError] = useState("");
  const load = useCallback(() => { if (token) apiRequest<T>(path, { token }).then((r) => { setD(r); setError(""); }).catch((e) => setError(e.message)); }, [token, path]);
  useEffect(load, [load]);
  const gate = loading ? <div className={s.skeleton} style={{ height: 240 }} /> : !user ? <Empty icon={<Lock />} title="ورود مدیر لازم است" />
    : error ? <Empty icon={<Lock />} title="دسترسی مدیر پلتفرم لازم است">{error}</Empty> : !d ? <div className={s.skeleton} style={{ height: 240 }} /> : null;
  return { token, d, load, gate };
}

// ── Packs ──

type AdminPack = PackDetail & { status: string; events: { action: string; created_at: string; actor: string }[] };
const KIND: Record<string, string> = { livelihood: "معیشتی", occasion: "مناسبتی", theme: "موضوعی", organizational: "سازمانی", custom: "سفارشی" };
const AUD: Record<string, string> = { household: "خانوار", organization: "سازمان", employee_gift: "هدیه کارکنان", office: "محیط اداری" };
const TIER: Record<string, string> = { "": "—", economy: "اقتصادی", standard: "استاندارد", complete: "کامل", premium: "ممتاز", executive: "ویژه مدیران" };

export function AdminPacks() {
  const { token, d, load, gate } = useAdmin<{ items: AdminPack[] }>("/admin/packs");
  const [edit, setEdit] = useState<AdminPack | "new" | null>(null), [flash, setFlash] = useState("");
  if (gate) return <div className={s.root}>{gate}</div>;
  const act = async (p: AdminPack, action: string) => {
    try { await apiRequest(`/admin/packs/${p.id}/${action}`, { token: token!, method: "POST" }); setFlash("وضعیت پک به‌روز شد."); load(); }
    catch (e) { setFlash(e instanceof Error ? e.message : "ناموفق"); }
  };
  return (
    <div className={s.root}>
      <header className={s.head}><div className={s.headRow}><div><div className={s.eyebrow}>مدیریت پلتفرم</div><h1 className={s.title}>مدیریت پک‌ها</h1>
        <div className={s.meta}><span>فقط کالای واقعی و قابل نمایش؛ انتشار با کنترل تنوع ترکیب</span></div></div>
        <button className={cx(s.btn, s.primary)} onClick={() => setEdit("new")}><Plus /> پک جدید</button></div></header>
      {flash && <Notice tone="info" icon={<CheckCircle2 />}>{flash}</Notice>}
      <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
        <thead><tr><th>پک</th><th>نوع</th><th>اقلام</th><th>وضعیت</th><th /></tr></thead>
        <tbody>{d!.items.map((p) => (
          <tr key={p.id}><td className={s.full}><b>{p.title_fa}</b><div className={s.small} style={{ color: "var(--muted)" }}>{p.slug}</div></td>
            <td data-label="نوع">{KIND[p.kind]}{p.tier_fa ? ` · ${p.tier_fa}` : ""}</td><td data-label="اقلام">{n(p.item_count)}</td>
            <td data-label="وضعیت"><Chip tone={p.status === "published" ? "ok" : p.status === "archived" ? "muted" : "warn"} dot>{p.status === "published" ? "منتشرشده" : p.status === "archived" ? "بایگانی" : "پیش‌نویس"}</Chip></td>
            <td><div className={s.row}><button className={cx(s.btn, s.sm)} onClick={() => setEdit(p)}>ویرایش</button>
              {p.status !== "published" && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => act(p, "publish")}>انتشار</button>}
              {p.status === "published" && <button className={cx(s.btn, s.sm)} onClick={() => act(p, "unpublish")}>توقف انتشار</button>}
              {p.status !== "archived" && <button className={cx(s.btn, s.sm, s.danger)} onClick={() => act(p, "archive")}>بایگانی</button>}</div></td></tr>))}</tbody>
      </table></div>
      {edit && token && <PackEditor token={token} pack={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); setFlash("پک ذخیره شد."); load(); }} />}
    </div>
  );
}

function PackEditor({ token, pack, onClose, onSaved }: { token: string; pack: AdminPack | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ slug: pack?.slug ?? "", title_fa: pack?.title_fa ?? "", kind: pack?.kind ?? "theme", tier: pack?.tier ?? "",
    audience: pack?.audience ?? "household", purpose_fa: pack?.purpose_fa ?? "", household_size: pack?.household_size ? String(pack.household_size) : "",
    packaging_fa: pack?.packaging_fa ?? "", substitution_policy: pack?.substitution_policy ?? "same_type" });
  const [items, setItems] = useState<{ master_product_id: number; title_fa: string; quantity: number; required: boolean }[]>(
    pack?.items.map((i) => ({ master_product_id: i.master_product_id, title_fa: i.title_fa, quantity: i.quantity, required: i.required })) ?? []);
  const [q, setQ] = useState(""), [hits, setHits] = useState<Product[]>([]), [busy, setBusy] = useState(false), [err, setErr] = useState(""), [key] = useState(newIdempotencyKey);
  useEffect(() => { if (q.trim().length < 2) { setHits([]); return; } const t = setTimeout(() => catalog.list({ q, page_size: 12 }).then((r) => setHits(r.items)).catch(() => {}), 250); return () => clearTimeout(t); }, [q]);
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    setBusy(true); setErr("");
    const body = { ...f, tier: f.tier || null, household_size: f.household_size ? Number(f.household_size) : null,
      items: items.map((i) => ({ master_product_id: i.master_product_id, quantity: i.quantity, required: i.required })) };
    try { await apiRequest(pack ? `/admin/packs/${pack.id}` : "/admin/packs", { token, method: pack ? "PUT" : "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": key } }); onSaved(); }
    catch (e) { setErr(e instanceof Error ? e.message : "ذخیره ناموفق بود"); } finally { setBusy(false); }
  };
  return (
    <Drawer open title={pack ? `ویرایش ${pack.title_fa}` : "پک جدید"} onClose={onClose} footer={<button className={cx(s.btn, s.primary)} disabled={busy} onClick={save}>{busy ? "در حال ذخیره…" : "ذخیره"}</button>}>
      <div className={s.stack}>
        <div className={s.grid2}>
          {!pack && <label className={s.field}>شناسه نشانی (لاتین)<input className={s.input} dir="ltr" value={f.slug} onChange={(e) => set("slug", e.target.value)} /></label>}
          <label className={s.field}>عنوان<input className={s.input} value={f.title_fa} onChange={(e) => set("title_fa", e.target.value)} /></label>
          <label className={s.field}>نوع<select className={s.select} value={f.kind} onChange={(e) => set("kind", e.target.value)}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>سطح<select className={s.select} value={f.tier} onChange={(e) => set("tier", e.target.value)}>{Object.entries(TIER).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>مخاطب<select className={s.select} value={f.audience} onChange={(e) => set("audience", e.target.value)}>{Object.entries(AUD).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className={s.field}>تعداد نفر (اختیاری)<input className={s.input} inputMode="numeric" value={f.household_size} onChange={(e) => set("household_size", e.target.value)} /></label>
          <label className={s.field}>بسته‌بندی<input className={s.input} value={f.packaging_fa} onChange={(e) => set("packaging_fa", e.target.value)} /></label>
          <label className={s.field}>جایگزینی<select className={s.select} value={f.substitution_policy} onChange={(e) => set("substitution_policy", e.target.value)}>
            <option value="same_type">فقط هم‌نوع</option><option value="same_type_and_size">هم‌نوع و هم‌اندازه</option><option value="ask">با هماهنگی</option><option value="none">بدون جایگزینی</option></select></label>
        </div>
        <label className={s.field}>کاربرد<textarea className={s.textarea} rows={2} value={f.purpose_fa} onChange={(e) => set("purpose_fa", e.target.value)} /></label>
        <div>
          <b className={s.small}>اقلام ({n(items.length)})</b>
          {items.map((i, k) => (
            <div key={i.master_product_id} className={s.row} style={{ marginTop: 6 }}>
              <span className={s.small} style={{ flex: 1, minWidth: 0 }}>{i.title_fa}</span>
              <input className={cx(s.input, s.inputSm)} style={{ width: 70 }} aria-label="تعداد" inputMode="numeric" value={i.quantity} onChange={(e) => setItems((xs) => xs.map((x, j) => j === k ? { ...x, quantity: Math.max(1, Number(e.target.value) || 1) } : x))} />
              <label className={s.row}><input type="checkbox" checked={i.required} onChange={(e) => setItems((xs) => xs.map((x, j) => j === k ? { ...x, required: e.target.checked } : x))} /> الزامی</label>
              <button type="button" className={cx(s.btn, s.sm, s.danger)} onClick={() => setItems((xs) => xs.filter((_, j) => j !== k))}>حذف</button>
            </div>))}
          <label className={s.field} style={{ marginTop: 8 }}>افزودن کالا<span style={{ position: "relative" }}><input className={s.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در کاتالوگ واقعی" style={{ paddingLeft: 34 }} /><Search size={16} style={{ position: "absolute", left: 10, top: 11, color: "var(--muted)" }} /></span></label>
          {hits.filter((h) => h.master_product_id && !items.some((i) => i.master_product_id === h.master_product_id)).map((h) => (
            <button key={h.id} type="button" className={cx(s.btn, s.sm, s.ghost)} style={{ justifyContent: "flex-start" }}
              onClick={() => setItems((xs) => [...xs, { master_product_id: h.master_product_id!, title_fa: h.name, quantity: 1, required: true }])}>+ {h.name}</button>))}
        </div>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}

// ── Catalog review → publish ──

type ReviewRow = { master_product_id: number; title_fa: string; brand: string | null; category: string; slug: string | null; visible: boolean; problems: string[]; publishable: boolean };
type Metrics = { active_products: number; storefront_skus: Record<string, number>; variants: Record<string, number>; priced_skus: number; in_stock_skus: number;
  purchasable_skus: number; brands: number; categories: { by_level_nonempty: Record<string, number>; depth: number }; packs: { published: number } };

export function AdminCatalogReview() {
  const { token, d, load, gate } = useAdmin<{ items: ReviewRow[] }>("/admin/catalog/review");
  const [m, setM] = useState<Metrics | null>(null), [flash, setFlash] = useState(""), [filter, setFilter] = useState("hidden");
  useEffect(() => { if (token) apiRequest<Metrics>("/admin/catalog/metrics", { token }).then(setM).catch(() => {}); }, [token, d]);
  if (gate) return <div className={s.root}>{gate}</div>;
  const visibility = async (r: ReviewRow, visible: boolean) => {
    try { await apiRequest(`/admin/catalog/products/${r.master_product_id}/visibility`, { token: token!, method: "POST", body: JSON.stringify({ visible, reason: visible ? "بازبینی و تأیید مدیر" : "توقف نمایش توسط مدیر" }) }); setFlash("به‌روزرسانی شد."); load(); }
    catch (e) { setFlash(e instanceof Error ? e.message : "ناموفق"); }
  };
  const rebuild = async () => {
    try { const r = await apiRequest<{ structure: Record<string, number> }>("/admin/catalog/structure/apply", { token: token!, method: "POST" }); setFlash(`ساختار بازسازی شد: ${n(r.structure.families)} خانواده، ${n(r.structure.variants)} مدل.`); load(); }
    catch (e) { setFlash(e instanceof Error ? e.message : "ناموفق"); }
  };
  const rows = d!.items.filter((r) => filter === "all" || (filter === "hidden" ? !r.visible : r.visible));
  return (
    <div className={s.root}>
      <header className={s.head}><div className={s.headRow}><div><div className={s.eyebrow}>مدیریت پلتفرم</div><h1 className={s.title}>بازبینی و انتشار کاتالوگ</h1></div>
        <button className={cx(s.btn)} onClick={rebuild}><RefreshCcw /> بازسازی ساختار (خانواده/دسته/SKU)</button></div></header>
      {flash && <Notice tone="info" icon={<CheckCircle2 />}>{flash}</Notice>}
      {m && <div className={s.kpis}>{[["SKU واقعی نمایش", m.storefront_skus.real_visible], ["خانواده محصول", m.variants.families], ["قیمت تأییدشده", m.priced_skus],
        ["موجودی تأییدشده", m.in_stock_skus], ["قابل خرید", m.purchasable_skus], ["برند", m.brands], ["عمق دسته", m.categories.depth], ["پک منتشرشده", m.packs.published]].map(([k, v]) => (
        <div key={k as string} className={s.kpi}><small>{k as string}</small><strong className={s.num} style={{ fontSize: 20 }}>{n(v as number)}</strong></div>))}</div>}
      <div className={s.tabs}>{[["hidden", "نمایش‌داده‌نشده"], ["visible", "در حال نمایش"], ["all", "همه"]].map(([k, l]) => (
        <button key={k} className={cx(s.tab, filter === k && s.tabOn)} onClick={() => setFilter(k)}>{l}</button>))}</div>
      <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
        <thead><tr><th>کالا</th><th>برند</th><th>وضعیت</th><th>ایرادها</th><th /></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.master_product_id}><td className={s.full}><b>{r.title_fa}</b><div className={s.small} style={{ color: "var(--muted)" }}>{r.category}</div></td>
            <td data-label="برند">{r.brand ?? "—"}</td>
            <td data-label="وضعیت"><Chip tone={r.visible ? "ok" : "muted"} dot>{r.visible ? "نمایش" : "پنهان"}</Chip></td>
            <td data-label="ایرادها" className={s.small}>{r.problems.join("، ") || "—"}</td>
            <td>{r.visible ? <button className={cx(s.btn, s.sm)} onClick={() => visibility(r, false)}>توقف نمایش</button>
              : <button className={cx(s.btn, s.sm, s.primary)} disabled={!r.publishable} onClick={() => visibility(r, true)}>انتشار</button>}
              {r.slug && r.visible && <Link className={cx(s.btn, s.sm, s.ghost)} href={`/products/${r.slug}`}>مشاهده</Link>}</td></tr>))}</tbody>
      </table></div>
    </div>
  );
}

// ── Returns ──

type Ret = { id: number; order_number: string; status: string; status_fa: string; reason: string; order_total_minor: number; refund_amount_minor: number | null;
  refund_reference: string | null; items: { title_fa: string; quantity: number }[]; events: { status: string; note: string | null; created_at: string; actor: string }[] };
const NEXT: Record<string, [string, string][]> = { requested: [["approve", "تأیید"], ["reject", "رد"]], approved: [["receive", "دریافت کالا"]],
  received: [["refund_pending", "ارسال به مالی"]], refund_pending: [["refund", "ثبت بازپرداخت"]] };

export function AdminReturns() {
  const [status, setStatus] = useState("");
  const { token, d, load, gate } = useAdmin<{ items: Ret[] }>(`/admin/returns${status ? `?status=${status}` : ""}`);
  const [act, setAct] = useState<{ r: Ret; action: string; label: string } | null>(null);
  if (gate) return <div className={s.root}>{gate}</div>;
  return (
    <div className={s.root}>
      <header className={s.head}><div className={s.eyebrow}>مدیریت پلتفرم</div><h1 className={s.title}><RotateCcw /> مرجوعی‌ها و بازپرداخت خرده</h1>
        <div className={s.meta}><span>بازپرداخت فقط ثبت مبلغ و مرجع بانکی پرداخت‌شده توسط مالی است؛ این سامانه پولی جابه‌جا نمی‌کند.</span></div></header>
      <div className={s.tabs}>{[["", "همه"], ["requested", "جدید"], ["approved", "تأییدشده"], ["received", "دریافت‌شده"], ["refund_pending", "در انتظار بازپرداخت"], ["refunded", "بازپرداخت‌شده"]].map(([k, l]) => (
        <button key={k} className={cx(s.tab, status === k && s.tabOn)} onClick={() => setStatus(k)}>{l}</button>))}</div>
      {!d!.items.length ? <Empty icon={<Package />} title="درخواست مرجوعی وجود ندارد" /> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
          <thead><tr><th>سفارش</th><th>اقلام و علت</th><th>وضعیت</th><th /></tr></thead>
          <tbody>{d!.items.map((r) => (
            <tr key={r.id}><td className={s.full}><b>{r.order_number}</b><div className={s.small}>{formatJalaliDateTime(r.events[0]?.created_at)}</div></td>
              <td data-label="اقلام" className={s.small}>{r.items.map((i) => `${i.title_fa} ×${n(i.quantity)}`).join("، ")}<div style={{ color: "var(--muted)" }}>{r.reason}</div></td>
              <td data-label="وضعیت"><Chip tone={r.status === "refunded" ? "ok" : r.status === "rejected" ? "bad" : "info"} dot>{r.status_fa}</Chip>{r.refund_reference && <div className={s.small}>{r.refund_reference}</div>}</td>
              <td><div className={s.row}>{(NEXT[r.status] ?? []).map(([a, l]) => <button key={a} className={cx(s.btn, s.sm, a === "reject" ? s.danger : undefined)} onClick={() => setAct({ r, action: a, label: l })}>{l}</button>)}</div></td></tr>))}</tbody>
        </table></div>)}
      {act && token && <ReturnAction token={token} {...act} onClose={() => setAct(null)} onDone={() => { setAct(null); load(); }} />}
    </div>
  );
}

function ReturnAction({ token, r, action, label, onClose, onDone }: { token: string; r: Ret; action: string; label: string; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState(""), [amount, setAmount] = useState(""), [ref, setRef] = useState(""), [err, setErr] = useState(""), [key] = useState(newIdempotencyKey);
  const send = async () => {
    try {
      await apiRequest(`/admin/returns/${r.id}/${action}`, { token, method: "POST", headers: { "Idempotency-Key": key },
        body: JSON.stringify({ note, ...(action === "refund" ? { amount_minor: Math.round(Number(faDigits(amount).replace(/[,،٬\s]/g, "")) * 10), reference: ref } : {}) }) });
      onDone();
    } catch (e) { setErr(e instanceof Error ? e.message : "ناموفق"); }
  };
  return (
    <Drawer open title={`${label} · ${r.order_number}`} onClose={onClose} footer={<button className={cx(s.btn, s.primary)} onClick={send}>ثبت</button>}>
      <div className={s.stack}>
        {action === "refund" && <>
          <Notice icon={<AlertTriangle />}>مبلغ و مرجع بانکی پرداختی را که مالی انجام داده ثبت کنید (حداکثر مانده سفارش: {n(Math.round(r.order_total_minor / 10))} تومان).</Notice>
          <label className={s.field}>مبلغ بازپرداخت (تومان)<input className={s.input} inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
          <label className={s.field}>مرجع بانکی<input className={s.input} value={ref} onChange={(e) => setRef(e.target.value)} /></label></>}
        <label className={s.field}>یادداشت{action === "reject" ? " (علت رد، الزامی)" : ""}<textarea className={s.textarea} rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}

// ── Customer inquiries → versioned quotes ──

type Inq = { id: number; kind: string; subject: string; status: string; created_at: string; items: { slug: string; name: string; quantity: number }[] };

export function AdminInquiries() {
  const { token, d, load, gate } = useAdmin<{ items: Inq[] }>("/admin/requests");
  const [open, setOpen] = useState<Inq | null>(null), [flash, setFlash] = useState("");
  if (gate) return <div className={s.root}>{gate}</div>;
  return (
    <div className={s.root}>
      <header className={s.head}><div className={s.eyebrow}>مدیریت پلتفرم</div><h1 className={s.title}>استعلام‌های مشتریان</h1>
        <div className={s.meta}><span>پیشنهاد قیمت نسخه‌دار با مهلت؛ پذیرش مشتری سفارش «در انتظار پرداخت» می‌سازد.</span></div></header>
      {flash && <Notice tone="info" icon={<CheckCircle2 />}>{flash}</Notice>}
      {!d!.items.length ? <Empty icon={<Package />} title="استعلامی ثبت نشده است" /> : (
        <div className={s.tableWrap}><table className={cx(s.table, s.cards)}>
          <thead><tr><th>درخواست</th><th>اقلام</th><th>وضعیت</th><th /></tr></thead>
          <tbody>{d!.items.map((r) => (
            <tr key={r.id}><td className={s.full}><b>{r.subject}</b><div className={s.small}>#{n(r.id)} · {formatJalaliDateTime(r.created_at)}</div></td>
              <td data-label="اقلام" className={s.small}>{r.items.map((i) => `${i.name} ×${n(i.quantity)}`).join("، ")}</td>
              <td data-label="وضعیت"><Chip tone={r.status === "closed" ? "ok" : "info"} dot>{REQ_STATUS[r.status] ?? r.status}</Chip></td>
              <td>{r.status !== "closed" && r.items.length > 0 && <button className={cx(s.btn, s.sm, s.primary)} onClick={() => setOpen(r)}>پیشنهاد قیمت</button>}</td></tr>))}</tbody>
        </table></div>)}
      {open && token && <QuoteComposer token={token} r={open} onClose={() => setOpen(null)} onDone={() => { setOpen(null); setFlash("پیشنهاد قیمت ارسال شد."); load(); }} />}
    </div>
  );
}

function QuoteComposer({ token, r, onClose, onDone }: { token: string; r: Inq; onClose: () => void; onDone: () => void }) {
  const [price, setPrice] = useState<Record<string, string>>({}), [ship, setShip] = useState("0"), [tax, setTax] = useState("0"), [days, setDays] = useState("3"), [note, setNote] = useState(""), [err, setErr] = useState("");
  const toMinor = (v: string) => Math.round(Number(faDigits(v || "0").replace(/[,،٬\s]/g, "")) * 10);
  const send = async () => {
    try {
      await apiRequest(`/admin/requests/${r.id}/quotes`, { token, method: "POST", body: JSON.stringify({ lines: r.items.map((i) => ({ slug: i.slug, quantity: i.quantity, unit_price_minor: toMinor(price[i.slug]) })),
        shipping_minor: toMinor(ship), tax_minor: toMinor(tax), valid_days: Number(faDigits(days)) || 3, note }) });
      onDone();
    } catch (e) { setErr(e instanceof Error ? e.message : "ناموفق"); }
  };
  return (
    <Drawer open title={`پیشنهاد قیمت · ${r.subject}`} onClose={onClose} footer={<button className={cx(s.btn, s.primary)} onClick={send}>ارسال پیشنهاد</button>}>
      <div className={s.stack}>
        {r.items.map((i) => <label key={i.slug} className={s.field}>{i.name} × {n(i.quantity)} — قیمت واحد (تومان)<input className={s.input} inputMode="numeric" value={price[i.slug] ?? ""} onChange={(e) => setPrice({ ...price, [i.slug]: e.target.value })} /></label>)}
        <div className={s.grid3}>
          <label className={s.field}>هزینه ارسال (تومان)<input className={s.input} inputMode="numeric" value={ship} onChange={(e) => setShip(e.target.value)} /></label>
          <label className={s.field}>مالیات (تومان)<input className={s.input} inputMode="numeric" value={tax} onChange={(e) => setTax(e.target.value)} /></label>
          <label className={s.field}>مهلت (روز)<input className={s.input} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></label>
        </div>
        <label className={s.field}>توضیح<textarea className={s.textarea} rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        {err && <Notice tone="bad" icon={<AlertTriangle />}>{err}</Notice>}
      </div>
    </Drawer>
  );
}
