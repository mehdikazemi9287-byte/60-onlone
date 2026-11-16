"use client";
// Seller shipment sheets (Stitch 2026-11). Data: the stored shipment label + GET /supplier/orders/{id} items.
// Neither sheet writes to the server: the driver checklist and the discrepancy entries live in this page only;
// the discrepancy report is printed/saved as PDF. (No backend endpoint records handover or delivery discrepancies yet.)
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Camera, CheckCircle2, Copy, FileWarning, Package, Phone, Printer, X } from "lucide-react";
import type { Shipment } from "@/lib/commerce";
import { cn, toPersianNum } from "@/lib/utils";
import { Code128, PrintHead, PrintSheet, SignBoxes } from "@/components/print/PrintSheet";

export type FoItem = { product_id: number; title_fa: string; quantity: number };
type Party = { name?: string; phone?: string; province?: string; city?: string; address?: string; postal_code?: string };
type Label = { carrier?: { name_fa?: string }; sender?: Party; receiver?: Party; reference?: { order_number?: string }; parcel_count?: number };
const place = (p?: Party) => [p?.province, p?.city, p?.address].filter(Boolean).join("، ");
const n = (v: number) => toPersianNum(v);

function Sheet({ title, onClose, children, footer }: { title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); document.body.style.overflow = prev; };
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 z-[95] flex items-end justify-center md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={title} dir="rtl">
      <button type="button" aria-label="بستن" className="absolute inset-0 bg-ink/40" onClick={onClose} />
      <div className="relative flex max-h-[96dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-3xl bg-white md:rounded-3xl">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-base font-extrabold text-ink">{title}</h2>
          <button type="button" onClick={onClose} aria-label="بستن" className="flex h-10 w-10 items-center justify-center rounded-full bg-canvas-sunken text-ink"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-line px-5 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">{footer}</div>}
      </div>
    </div>, document.body);
}

/** Mobile exit slip for the fleet driver: barcode, call, copy address, items checklist. */
export function DriverSheet({ s, items, onClose }: { s: Shipment; items: FoItem[]; onClose: () => void }) {
  const l = s.label as Label;
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState(false);
  const allDone = items.length > 0 && checked.size === items.length;
  const addr = place(l.receiver);
  return (
    <Sheet title="برگهٔ خروج — نسخهٔ راننده" onClose={onClose}
      footer={<div className={cn("flex min-h-12 items-center justify-center gap-2 rounded-full text-sm font-bold", allDone ? "bg-emerald-600 text-white" : "bg-canvas-sunken text-ink-muted")} role="status">
        <CheckCircle2 className="h-5 w-5" />{allDone ? "همهٔ اقلام کنترل شد" : `${n(checked.size)} از ${n(items.length)} قلم کنترل شده`}</div>}>
      <div className="flex flex-col items-center gap-1 rounded-2xl p-3" style={{ background: "#fff" }}>
        <Code128 data={s.tracking_number} height={64} /><span className="font-mono text-sm tracking-[0.2em] text-[#0A2735]" dir="ltr">{s.tracking_number}</span>
      </div>
      <dl className="mt-4 space-y-3">
        <div className="flex items-center gap-3 rounded-2xl bg-canvas p-3">
          <div className="min-w-0 flex-1"><dt className="text-[11px] text-ink-faint">گیرنده</dt><dd className="font-bold text-ink">{l.receiver?.name || "—"}</dd></div>
          {l.receiver?.phone && <a href={`tel:${l.receiver.phone}`} className="inline-flex h-12 items-center gap-2 rounded-full bg-ink px-4 text-sm font-bold text-white"><Phone className="h-4 w-4" />تماس</a>}
        </div>
        <div className="flex items-start gap-3 rounded-2xl bg-canvas p-3">
          <div className="min-w-0 flex-1"><dt className="text-[11px] text-ink-faint">نشانی</dt><dd className="text-sm leading-7 text-ink">{addr || "—"}</dd>
            {l.receiver?.postal_code && <dd className="text-xs text-ink-muted">کد پستی: <span dir="ltr">{l.receiver.postal_code}</span></dd>}</div>
          {addr && <button type="button" onClick={() => navigator.clipboard?.writeText(addr).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1800); })}
            className="inline-flex h-12 shrink-0 items-center gap-1.5 rounded-full border border-line-strong px-3.5 text-sm font-bold text-ink"><Copy className="h-4 w-4" />{copied ? "کپی شد" : "کپی"}</button>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-2xl bg-canvas p-3"><dt className="text-[11px] text-ink-faint">سفارش</dt><dd className="font-mono text-sm text-ink" dir="ltr" style={{ textAlign: "right" }}>{l.reference?.order_number || "—"}</dd></div>
          <div className="rounded-2xl bg-canvas p-3"><dt className="flex items-center gap-1 text-[11px] text-ink-faint"><Package className="h-3 w-3" />تعداد بسته</dt><dd className="text-lg font-extrabold text-ink">{l.parcel_count != null ? n(l.parcel_count) : "—"}</dd></div>
        </div>
      </dl>
      <h3 className="mb-2 mt-5 text-sm font-bold text-ink">کنترل اقلام هنگام بارگیری</h3>
      <ul className="space-y-2">{items.map((it) => {
        const on = checked.has(it.product_id);
        return <li key={it.product_id}><label className={cn("flex min-h-14 cursor-pointer items-center gap-3 rounded-2xl border px-3", on ? "border-emerald-500 bg-emerald-50" : "border-line")}>
          <input type="checkbox" className="h-6 w-6 shrink-0" checked={on} onChange={() => setChecked((c) => { const x = new Set(c); if (x.has(it.product_id)) x.delete(it.product_id); else x.add(it.product_id); return x; })} />
          <span className="flex-1 text-sm text-ink">{it.title_fa}</span><b className="text-base text-ink">{n(it.quantity)}×</b></label></li>;
      })}</ul>
      <p className="mt-3 text-[11px] text-ink-faint">این فهرست فقط روی همین صفحه است و وضعیت مرسوله را در سامانه تغییر نمی‌دهد.</p>
    </Sheet>
  );
}

const REASONS = ["کسری", "آسیب‌دیده", "اشتباه ارسالی", "مازاد"] as const;
type Line = { delivered: string; reason: string; note: string };

/** Waybill-vs-order delivery discrepancy: photo of the signed waybill + delivered qty per item → printable report. */
export function DiscrepancySheet({ s, items, onClose }: { s: Shipment; items: FoItem[]; onClose: () => void }) {
  const l = s.label as Label;
  const [lines, setLines] = useState<Record<number, Line>>(() => Object.fromEntries(items.map((i) => [i.product_id, { delivered: String(i.quantity), reason: "", note: "" }])));
  const [photo, setPhoto] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [printing, setPrinting] = useState(false);
  const done = useCallback(() => setPrinting(false), []);
  const qty = (pid: number) => { const v = Number((lines[pid]?.delivered ?? "").replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))); return Number.isFinite(v) && v >= 0 ? Math.floor(v) : NaN; };
  const rows = items.map((it) => { const d = qty(it.product_id); return { it, d, diff: Number.isNaN(d) ? 0 : d - it.quantity, ...lines[it.product_id] }; });
  const invalid = rows.some((r) => Number.isNaN(r.d));
  const flagged = rows.filter((r) => r.diff !== 0 || r.reason);
  const missingReason = rows.some((r) => r.diff !== 0 && !r.reason);
  const set = (pid: number, k: keyof Line, v: string) => setLines((c) => ({ ...c, [pid]: { ...c[pid], [k]: v } }));
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; e.target.value = ""; setErr(null);
    if (!f) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) { setErr("فقط تصویر PNG، JPG یا WebP"); return; }
    if (f.size > 5 * 1024 * 1024) { setErr("حجم تصویر باید کمتر از ۵ مگابایت باشد"); return; }
    const r = new FileReader(); r.onload = () => setPhoto(typeof r.result === "string" ? r.result : null); r.readAsDataURL(f);
  };
  const short = rows.filter((r) => r.diff < 0).reduce((t, r) => t - r.diff, 0), extra = rows.filter((r) => r.diff > 0).reduce((t, r) => t + r.diff, 0);
  const damaged = rows.filter((r) => r.reason === "آسیب‌دیده").length;

  return (
    <Sheet title="ثبت مغایرت تحویل" onClose={onClose}
      footer={<button type="button" disabled={invalid || missingReason} onClick={() => setPrinting(true)} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-ink text-sm font-bold text-white disabled:opacity-40">
        <Printer className="h-4 w-4" />چاپ / PDF گزارش مغایرت</button>}>
      <label className="flex cursor-pointer items-center gap-3 rounded-2xl border border-dashed border-line-strong p-3">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-line" style={{ background: "#fff" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {photo ? <img src={photo} alt="تصویر بارنامهٔ امضاشده" className="h-full w-full object-cover" /> : <Camera className="h-6 w-6 text-ink-faint" />}</span>
        <span className="flex-1"><b className="block text-sm text-ink">{photo ? "تغییر تصویر بارنامه" : "تصویر بارنامهٔ امضاشده"}</b><small className="text-xs text-ink-muted">عکس یا اسکن؛ فقط در همین گزارش استفاده می‌شود</small></span>
        <input type="file" accept="image/png,image/jpeg,image/webp" capture="environment" className="sr-only" onChange={pick} />
      </label>
      {err && <p role="alert" className="mt-2 text-xs text-red-700">{err}</p>}

      <ul className="mt-4 space-y-3">{rows.map((r) => (
        <li key={r.it.product_id} className={cn("rounded-2xl border p-3", r.diff !== 0 ? "border-amber-300" : "border-line")}>
          <p className="text-sm font-bold text-ink">{r.it.title_fa}</p>
          <div className="mt-2 grid grid-cols-3 items-end gap-2">
            <div><span className="text-[11px] text-ink-faint">سفارش</span><p className="text-lg font-extrabold text-ink">{n(r.it.quantity)}</p></div>
            <label className="grid gap-1 text-[11px] text-ink-faint">تحویل‌شده<input inputMode="numeric" value={r.delivered} onChange={(e) => set(r.it.product_id, "delivered", e.target.value)} aria-invalid={Number.isNaN(r.d)} className="form-input text-center text-base" /></label>
            <label className="grid gap-1 text-[11px] text-ink-faint">علت<select value={r.reason} onChange={(e) => set(r.it.product_id, "reason", e.target.value)} className="form-input text-sm"><option value="">—</option>{REASONS.map((x) => <option key={x}>{x}</option>)}</select></label>
          </div>
          {r.diff !== 0 && <p className="mt-1 text-xs font-semibold text-amber-800">{r.diff < 0 ? `${n(-r.diff)} عدد کمتر` : `${n(r.diff)} عدد بیشتر`}{!r.reason && " — علت را انتخاب کنید"}</p>}
          {(r.diff !== 0 || r.reason) && <input value={r.note} onChange={(e) => set(r.it.product_id, "note", e.target.value)} maxLength={200} placeholder="توضیح (اختیاری)" className="form-input mt-2 text-sm" />}
        </li>))}</ul>

      <div className="mt-4 grid grid-cols-3 gap-2 text-center" aria-label="خلاصه">
        <div className="rounded-2xl bg-canvas p-3"><p className="text-[11px] text-ink-faint">بدون مغایرت</p><b className="text-lg text-ink">{n(rows.length - flagged.length)}</b></div>
        <div className="rounded-2xl bg-canvas p-3"><p className="text-[11px] text-ink-faint">کسری / مازاد</p><b className="text-lg text-ink">{n(short)} / {n(extra)}</b></div>
        <div className="rounded-2xl bg-canvas p-3"><p className="text-[11px] text-ink-faint">آسیب‌دیده</p><b className="text-lg text-ink">{n(damaged)}</b></div>
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-[11px] text-ink-faint"><FileWarning className="mt-0.5 h-3.5 w-3.5 shrink-0" />این گزارش در سامانه ثبت نمی‌شود؛ PDF آن را برای پیگیری با حامل یا پشتیبانی نگه دارید.</p>

      {printing && <PrintSheet onDone={done}>
        <PrintHead title="گزارش مغایرت تحویل با سفارش" number={`DR-${s.fulfillment_order_id}`} />
        <table className="cp-kv"><tbody>
          <tr><th>شمارهٔ سفارش</th><td dir="ltr" style={{ textAlign: "right" }}>{l.reference?.order_number || "—"}</td><th>کد رهگیری</th><td dir="ltr" style={{ textAlign: "right" }}>{s.tracking_number}</td></tr>
          <tr><th>حامل</th><td>{l.carrier?.name_fa || s.provider_code}</td><th>گیرنده</th><td>{l.receiver?.name || "—"}</td></tr>
        </tbody></table>
        <table className="cp-items">
          <thead><tr><th>ردیف</th><th>کالا</th><th>سفارش</th><th>تحویل‌شده</th><th>اختلاف</th><th>علت</th><th>توضیح</th></tr></thead>
          <tbody>{rows.map((r, i) => <tr key={r.it.product_id}><td>{n(i + 1)}</td><td>{r.it.title_fa}</td><td>{n(r.it.quantity)}</td><td>{n(r.d)}</td>
            <td>{r.diff === 0 ? "—" : r.diff > 0 ? `+${n(r.diff)}` : `−${n(-r.diff)}`}</td><td>{r.reason || "—"}</td><td>{r.note || ""}</td></tr>)}</tbody>
          <tfoot><tr><td colSpan={7}>اقلام بدون مغایرت: {n(rows.length - flagged.length)} · کسری: {n(short)} · مازاد: {n(extra)} · آسیب‌دیده: {n(damaged)}</td></tr></tfoot>
        </table>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {photo && <div className="cp-box" style={{ marginBottom: 12 }}><h2>تصویر بارنامهٔ امضاشده</h2><img src={photo} alt="" style={{ maxHeight: "95mm", maxWidth: "100%", objectFit: "contain" }} /></div>}
        <SignBoxes labels={["فروشنده / انباردار", "نمایندهٔ حمل", "تحویل‌گیرنده"]} />
      </PrintSheet>}
    </Sheet>
  );
}
