"use client";
// سامانهٔ مودیان — admin console over the REAL endpoints in backend/app/api/v1/finance_exports.py:
//   POST /admin/moadian/preview {source_ref}  → payload, not stored
//   POST /admin/moadian/documents {source_ref} → stored (idempotent per source_ref)
//   GET  /admin/moadian/documents[?status&issuer_type], GET …/<id>, POST …/<id>/mark-submitted
// Amounts in the payload are ريال (minor units). Nothing is sent to INTA from here: signing/transport are not wired.
import { useCallback, useEffect, useRef, useState } from "react";
import { FileCheck2, Printer, Receipt, Search, X } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn, toPersianNum } from "@/lib/utils";

type Header = { taxid: string; indatim: number; inty: number; inno: string; inp: number; ins: number; tins: string;
  tob: number | null; bid: string | null; tinb: string | null; tprdis: number; tdis: number; tadis: number; tvam: number;
  todam: number; tbill: number; setm: number; cap: number; insp: number };
type Line = { sstid: string; sstt: string; am: number; mu: string; fee: number; prdis: number; dis: number; adis: number;
  vra: number; vam: number; tsstam: number };
type Payload = { header: Header; body: Line[] };
type Doc = { id: number; source_ref: string; doc_type: string; issuer_type: string; issuer_supplier_id: number | null;
  serial: number; taxid: string; tbill_minor: number; status: string; submission_reference?: string | null;
  submission_error?: string | null; created_at: string; payload: Payload; warnings?: string[]; reused?: boolean };
type Preview = { payload: Payload; doc_type: string; issuer_type: string; warnings: string[] };
type Shown = { kind: "preview"; source_ref: string; data: Preview } | { kind: "doc"; data: Doc };

const STATUS: Record<string, [string, string]> = {
  built: ["ساخته‌شده", "bg-canvas-sunken text-ink-soft"], submitted: ["ارسال‌شده", "bg-sky-50 text-sky-800"],
  accepted: ["پذیرفته‌شده", "bg-emerald-50 text-emerald-800"], rejected: ["ردشده", "bg-red-50 text-red-700"],
  preview: ["پیش‌نمایش (ذخیره نشده)", "bg-amber-50 text-amber-800"],
};
const SETM: Record<number, string> = { 1: "نقدی", 2: "نسیه", 3: "نقد و نسیه" };
const rial = (v: number | null | undefined) => v == null ? "—" : toPersianNum(Math.round(v).toLocaleString("en-US"));
const faDate = (ms: number) => { try { return new Intl.DateTimeFormat("fa-IR", { dateStyle: "long" }).format(new Date(ms)); } catch { return toPersianNum(ms); } };
const DOC_TYPE: Record<string, string> = { seller_sale: "فروش فروشنده", platform_commission: "کارمزد پلتفرم" };

function StatusBadge({ s }: { s: string }) {
  const [label, cls] = STATUS[s] ?? [s, "bg-canvas-sunken text-ink-soft"];
  return <span className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold", cls)}>{label}</span>;
}

function Field({ k, v, ltr }: { k: string; v: React.ReactNode; ltr?: boolean }) {
  return <div className="min-w-0"><dt className="text-[11px] text-ink-faint">{k}</dt>
    <dd className={cn("mt-0.5 truncate text-[13px] font-semibold text-ink", ltr && "font-mono text-[12px]")} dir={ltr ? "ltr" : undefined} style={ltr ? { textAlign: "right" } : undefined}>{v || "—"}</dd></div>;
}

/** Official-style preview of one Moadian invoice (پیش‌نمایش صورتحساب رسمی). */
export function InvoiceModal({ shown, onClose, onChanged }: { shown: Shown; onClose: () => void; onChanged?: (d: Doc) => void }) {
  const { token } = useAuth();
  const box = useRef<HTMLDivElement>(null);
  const p = shown.data.payload, h = p.header;
  const status = shown.kind === "doc" ? shown.data.status : "preview";
  const warnings = shown.kind === "preview" ? shown.data.warnings : shown.data.warnings ?? [];
  const docType = shown.data.doc_type;
  const [ref, setRef] = useState(""), [next, setNext] = useState("submitted"), [err, setErr] = useState("");
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    box.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); document.body.style.overflow = prev; };
  }, [onClose]);

  const build = async () => {
    if (shown.kind !== "preview" || !token) return;
    setBusy(true); setMsg(null);
    try {
      const r = await apiRequest<{ document: Doc }>("/admin/moadian/documents", { method: "POST", token, body: JSON.stringify({ source_ref: shown.source_ref }) });
      setMsg({ ok: true, text: r.document.reused ? "این منبع قبلاً صورتحساب داشت؛ همان نسخهٔ ذخیره‌شده باز شد." : "صورتحساب ساخته و ذخیره شد." });
      onChanged?.(r.document);
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "خطا" }); } finally { setBusy(false); }
  };
  const mark = async (e: React.FormEvent) => {
    e.preventDefault();
    if (shown.kind !== "doc" || !token) return;
    setBusy(true); setMsg(null);
    try {
      const r = await apiRequest<{ document: Doc }>(`/admin/moadian/documents/${shown.data.id}/mark-submitted`, { method: "POST", token,
        body: JSON.stringify({ reference: ref.trim(), status: next, ...(next === "rejected" && err.trim() ? { error: err.trim() } : {}) }) });
      setMsg({ ok: true, text: "وضعیت ثبت شد." }); onChanged?.(r.document);
    } catch (e2) { setMsg({ ok: false, text: e2 instanceof Error ? e2.message : "خطا" }); } finally { setBusy(false); }
  };

  return (
    <div className="moadian-modal fixed inset-0 z-[90] flex items-end justify-center md:items-center md:p-6" role="dialog" aria-modal="true" aria-labelledby="inv-title">
      <button type="button" aria-label="بستن" className="absolute inset-0 bg-ink/40 backdrop-blur-[2px] print:hidden" onClick={onClose} />
      <div ref={box} tabIndex={-1} className="moadian-sheet relative flex max-h-[94dvh] w-full max-w-5xl flex-col overflow-hidden rounded-t-3xl bg-white outline-none md:rounded-3xl">
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4 md:px-7">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-canvas-sunken text-ink"><Receipt className="h-5 w-5" strokeWidth={1.6} /></span>
            <div><p className="text-[11px] text-ink-faint">سامانهٔ مودیان · {DOC_TYPE[docType] ?? docType}</p>
              <h2 id="inv-title" className="text-base font-extrabold text-ink md:text-lg">پیش‌نمایش صورتحساب الکترونیکی</h2></div>
          </div>
          <div className="flex items-center gap-2 print:hidden"><StatusBadge s={status} />
            <button type="button" onClick={() => window.print()} className="hidden h-10 w-10 items-center justify-center rounded-full border border-line-strong text-ink hover:border-ink md:flex" aria-label="چاپ"><Printer className="h-4 w-4" /></button>
            <button type="button" onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-full bg-canvas-sunken text-ink" aria-label="بستن پیش‌نمایش"><X className="h-4 w-4" /></button></div>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5 md:px-7">
          {warnings.length > 0 && <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-[13px] text-amber-900">
            <b className="mb-1 block">پیش از ارسال باید برطرف شود</b>
            <ul className="list-inside list-disc space-y-0.5">{warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>}

          <section aria-label="سرآیند صورتحساب" className="rounded-2xl border border-line p-4">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
              <Field k="شمارهٔ منحصربه‌فرد مالیاتی" v={h.taxid} ltr /><Field k="شمارهٔ صورتحساب" v={h.inno} ltr />
              <Field k="تاریخ صدور" v={faDate(h.indatim)} /><Field k="نوع صورتحساب" v={h.inty === 1 ? "نوع اول (با مشخصات خریدار)" : "نوع دوم"} />
              <Field k="الگو / موضوع" v={`${h.inp === 1 ? "فروش" : toPersianNum(h.inp)} · ${h.ins === 1 ? "اصلی" : toPersianNum(h.ins)}`} />
              <Field k="شمارهٔ اقتصادی فروشنده" v={h.tins} ltr />
              <Field k="خریدار" v={h.tob == null ? "بدون مشخصات" : h.tob === 2 ? "حقوقی" : "حقیقی"} />
              <Field k="شناسه / شمارهٔ اقتصادی خریدار" v={[h.bid, h.tinb].filter(Boolean).join(" / ")} ltr />
            </dl>
          </section>

          <section aria-label="اقلام صورتحساب" className="overflow-hidden rounded-2xl border border-line">
            <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-right text-[12px]">
              <thead><tr className="text-ink-muted">{["ردیف", "شناسهٔ کالا/خدمت", "شرح", "تعداد", "مبلغ واحد", "تخفیف", "پس از تخفیف", "نرخ مالیات", "مالیات", "مبلغ کل"].map((c) =>
                <th key={c} scope="col" className="whitespace-nowrap px-3 py-2.5 font-semibold">{c}</th>)}</tr></thead>
              <tbody>{p.body.map((l, i) => <tr key={i} className="tabular-nums text-ink">
                <td className="px-3 py-3 text-ink-faint">{toPersianNum(i + 1)}</td>
                <td className="px-3 py-3 font-mono text-[11px]" dir="ltr" style={{ textAlign: "right" }}>{l.sstid || <span className="font-sans text-amber-700">تعریف نشده</span>}</td>
                <td className="min-w-[200px] max-w-[280px] px-3 py-3">{l.sstt}</td><td className="px-3 py-3">{toPersianNum(l.am)}</td>
                <td className="px-3 py-3">{rial(l.fee)}</td><td className="px-3 py-3">{rial(l.dis)}</td><td className="px-3 py-3">{rial(l.adis)}</td>
                <td className="px-3 py-3">{toPersianNum(l.vra)}٪</td><td className="px-3 py-3">{rial(l.vam)}</td><td className="px-3 py-3 font-bold">{rial(l.tsstam)}</td>
              </tr>)}</tbody></table></div>
          </section>

          <section aria-label="جمع صورتحساب" className="grid gap-4 md:grid-cols-[1fr_320px]">
            <dl className="grid grid-cols-2 content-start gap-4 rounded-2xl border border-line p-4">
              <Field k="روش تسویه" v={SETM[h.setm] ?? toPersianNum(h.setm)} />
              <Field k="مبلغ نقدی / نسیه (ریال)" v={`${rial(h.cap)} / ${rial(h.insp)}`} />
              {shown.kind === "doc" && <><Field k="منبع" v={shown.data.source_ref} ltr /><Field k="شمارهٔ پیگیری ارسال" v={shown.data.submission_reference} ltr /></>}
              {shown.kind === "doc" && shown.data.submission_error && <div className="col-span-2 rounded-xl bg-red-50 p-3 text-xs text-red-700">{shown.data.submission_error}</div>}
            </dl>
            <dl className="space-y-2 rounded-2xl bg-canvas p-4 text-[13px] tabular-nums">
              {([["جمع قبل از تخفیف", h.tprdis], ["جمع تخفیف", h.tdis], ["جمع پس از تخفیف", h.tadis], ["مالیات بر ارزش افزوده", h.tvam], ["سایر عوارض", h.todam]] as [string, number][]).map(([k, v]) =>
                <div key={k} className="flex justify-between text-ink-soft"><dt>{k}</dt><dd>{rial(v)}</dd></div>)}
              <div className="flex justify-between border-t border-line-strong pt-3 text-base font-extrabold text-ink"><dt>مبلغ کل صورتحساب</dt><dd>{rial(h.tbill)} <small className="text-xs font-normal text-ink-muted">ریال</small></dd></div>
            </dl>
          </section>
          {msg && <p role={msg.ok ? "status" : "alert"} className={cn("rounded-xl p-3 text-sm", msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700")}>{msg.text}</p>}
        </div>

        <div className="border-t border-line px-5 py-4 md:px-7 print:hidden">
          {shown.kind === "preview" ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-ink-muted">این پیش‌نمایش ذخیره نشده است. ساخت صورتحساب برای هر منبع فقط یک‌بار انجام می‌شود.</p>
              <button type="button" disabled={busy} onClick={build} className="inline-flex min-h-11 items-center gap-2 rounded-full bg-ink px-5 text-sm font-bold text-white disabled:opacity-40">
                <FileCheck2 className="h-4 w-4" />{busy ? "در حال ساخت…" : "ساخت و ذخیرهٔ صورتحساب"}</button>
            </div>
          ) : shown.data.status === "accepted" ? <p className="text-xs text-ink-muted">صورتحساب پذیرفته‌شده قابل تغییر نیست.</p> : (
            <form onSubmit={mark} className="flex flex-wrap items-end gap-2">
              <label className="grid flex-1 gap-1 text-xs font-semibold text-ink-soft">شمارهٔ پیگیری سامانه
                <input required value={ref} onChange={(e) => setRef(e.target.value)} maxLength={120} dir="ltr" className="form-input" /></label>
              <label className="grid gap-1 text-xs font-semibold text-ink-soft">وضعیت
                <select value={next} onChange={(e) => setNext(e.target.value)} className="form-input">
                  <option value="submitted">ارسال‌شده</option><option value="accepted">پذیرفته‌شده</option><option value="rejected">ردشده</option></select></label>
              {next === "rejected" && <label className="grid flex-1 gap-1 text-xs font-semibold text-ink-soft">علت رد
                <input value={err} onChange={(e) => setErr(e.target.value)} maxLength={500} className="form-input" /></label>}
              <button disabled={busy || !ref.trim()} className="min-h-11 rounded-full bg-ink px-5 text-sm font-bold text-white disabled:opacity-40">ثبت وضعیت</button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

export function MoadianConsole() {
  const { token } = useAuth();
  const [docs, setDocs] = useState<Doc[] | null>(null), [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState(""), [issuer, setIssuer] = useState("");
  const [source, setSource] = useState(""), [busy, setBusy] = useState(false), [formErr, setFormErr] = useState<string | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setError(null);
    const q = new URLSearchParams(); if (status) q.set("status", status); if (issuer) q.set("issuer_type", issuer);
    try { setDocs((await apiRequest<{ documents: Doc[] }>(`/admin/moadian/documents${q.toString() ? "?" + q.toString() : ""}`, { token })).documents); }
    catch (e) { setError(e instanceof Error ? e.message : "خطا"); setDocs([]); }
  }, [token, status, issuer]);
  useEffect(() => { load(); }, [load]);

  const preview = async (e: React.FormEvent) => {
    e.preventDefault(); if (!token) return;
    setBusy(true); setFormErr(null);
    try {
      const data = await apiRequest<Preview>("/admin/moadian/preview", { method: "POST", token, body: JSON.stringify({ source_ref: source.trim() }) });
      setShown({ kind: "preview", source_ref: source.trim(), data });
    } catch (e2) { setFormErr(e2 instanceof Error ? e2.message : "خطا"); } finally { setBusy(false); }
  };
  const changed = (d: Doc) => { setShown({ kind: "doc", data: d }); load(); };

  return (
    <div className="space-y-6" dir="rtl">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-[11px] font-semibold text-ink-faint">مالی و مالیات</p>
          <h1 className="text-2xl font-extrabold text-ink">صورتحساب‌های سامانهٔ مودیان</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-muted">هر فروشنده صورتحساب کالای خود را صادر می‌کند و شصت‌آنلاین فقط کارمزد خدماتش را. امضا و ارسال به سامانه از این صفحه انجام نمی‌شود؛ پس از ارسال، شمارهٔ پیگیری را ثبت کنید.</p></div>
      </div>

      <form onSubmit={preview} className="rounded-2xl border border-line bg-white p-4 md:p-5">
        <label htmlFor="src" className="mb-2 block text-sm font-bold text-ink">پیش‌نمایش صورتحساب از منبع</label>
        <div className="flex flex-wrap gap-2">
          <input id="src" required value={source} onChange={(e) => setSource(e.target.value)} dir="ltr" placeholder="fo:123   یا   commission:7:2026-10-01:2026-10-31"
            className="form-input min-w-[260px] flex-1 font-mono text-sm" aria-describedby="src-help" />
          <button disabled={busy || !source.trim()} className="inline-flex min-h-11 items-center gap-2 rounded-full bg-ink px-5 text-sm font-bold text-white disabled:opacity-40"><Search className="h-4 w-4" />{busy ? "در حال ساخت…" : "پیش‌نمایش"}</button>
        </div>
        <p id="src-help" className="mt-2 text-xs text-ink-faint">‎fo:‎ شمارهٔ سفارش تأمین فروشنده · ‎commission:‎ شناسهٔ فروشنده و بازهٔ تاریخ کارمزد</p>
        {formErr && <p role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{formErr}</p>}
      </form>

      <section className="rounded-2xl border border-line bg-white" aria-labelledby="docs-h">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4 md:px-5">
          <h2 id="docs-h" className="text-[15px] font-bold text-ink">صورتحساب‌های ساخته‌شده</h2>
          <div className="flex gap-2">
            <select aria-label="وضعیت" value={status} onChange={(e) => setStatus(e.target.value)} className="form-input !min-h-10 !py-1.5 text-sm">
              <option value="">همهٔ وضعیت‌ها</option>{["built", "submitted", "accepted", "rejected"].map((s) => <option key={s} value={s}>{STATUS[s][0]}</option>)}</select>
            <select aria-label="صادرکننده" value={issuer} onChange={(e) => setIssuer(e.target.value)} className="form-input !min-h-10 !py-1.5 text-sm">
              <option value="">همهٔ صادرکنندگان</option><option value="seller">فروشندگان</option><option value="platform">شصت‌آنلاین</option></select>
          </div>
        </div>
        {error ? <p role="alert" className="m-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>
          : docs === null ? <p role="status" className="p-8 text-center text-sm text-ink-faint">در حال بارگذاری…</p>
          : !docs.length ? <p className="p-10 text-center text-sm text-ink-muted">هنوز صورتحسابی ساخته نشده است. از فرم بالا یک منبع را پیش‌نمایش کنید.</p>
          : <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-right text-[13px]">
            <thead><tr>{["شمارهٔ مالیاتی", "نوع", "منبع", "مبلغ کل (ریال)", "وضعیت", "تاریخ ساخت", ""].map((c) => <th key={c} scope="col" className="px-4 py-2.5">{c}</th>)}</tr></thead>
            <tbody>{docs.map((d) => <tr key={d.id} className="text-ink">
              <td className="px-4 py-3 font-mono text-[11px]" dir="ltr" style={{ textAlign: "right" }}>{d.taxid}</td>
              <td className="px-4 py-3">{DOC_TYPE[d.doc_type] ?? d.doc_type}</td>
              <td className="px-4 py-3 font-mono text-[11px]" dir="ltr" style={{ textAlign: "right" }}>{d.source_ref}</td>
              <td className="px-4 py-3 tabular-nums">{rial(d.tbill_minor)}</td><td className="px-4 py-3"><StatusBadge s={d.status} /></td>
              <td className="px-4 py-3 text-ink-muted">{toPersianNum((d.created_at || "").slice(0, 10))}</td>
              <td className="px-4 py-3"><button type="button" onClick={() => setShown({ kind: "doc", data: d })} className="rounded-full border border-line-strong px-3.5 py-1.5 text-xs font-bold text-ink hover:border-ink">مشاهده</button></td>
            </tr>)}</tbody></table></div>}
      </section>
      {shown && <InvoiceModal shown={shown} onClose={() => setShown(null)} onChanged={changed} />}
    </div>
  );
}
