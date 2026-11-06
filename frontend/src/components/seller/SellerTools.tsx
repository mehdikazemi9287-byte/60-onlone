"use client";

// Seller panel (owner view of /sell): brand registration, own-fulfillment shipments, finance exports.
import { useEffect, useState } from "react";
import { apiRequest, downloadAuthed, errText, SHIP_STATUS_FA, type BrandRegistration, type ExportJob, type Shipment } from "@/lib/commerce";
import { ApiError } from "@/lib/api";
import { faDate } from "@/lib/utils";
import { Card, Flash, ListState, btnCls, btnGhost, inputCls, n } from "@/components/commerce/ui";

type Msg = { ok: boolean; text: string } | null;

function useList<T>(path: string, token: string, retry: number, pick: (r: never) => T[]): [T[] | null, string | null] {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setItems(null); setError(null);
    apiRequest<never>(path, { token })
      .then((r) => { if (!cancelled) setItems(pick(r)); })
      .catch((e) => { if (!cancelled) { if (e instanceof ApiError && e.status === 404) setItems([]); else setError(errText(e, "بارگذاری ناموفق بود")); } });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, token, retry]);
  return [items, error];
}

export function SellerTools({ token, isBrand }: { token: string; isBrand: boolean }) {
  return (
    <div className="space-y-4">
      <nav aria-label="ابزارهای فروشنده" className="flex gap-2 overflow-x-auto pb-1 text-sm">
        {isBrand && <a href="#brand" className="shrink-0 rounded-full bg-neutral-100 px-3 py-1.5">ثبت برند</a>}
        <a href="#shipments" className="shrink-0 rounded-full bg-neutral-100 px-3 py-1.5">ارسال سفارش‌ها</a>
        <a href="#exports" className="shrink-0 rounded-full bg-neutral-100 px-3 py-1.5">خروجی مالی</a>
      </nav>
      {isBrand && <BrandRegistrationCard token={token} />}
      <ShipmentsCard token={token} />
      <ExportsCard token={token} />
    </div>
  );
}

// ── Brand registration ─────────────────────────────────────────────────────
const REG_FA: Record<string, string> = { pending: "در حال بررسی", verified: "تأییدشده", rejected: "ردشده" };
function BrandRegistrationCard({ token }: { token: string }) {
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<{ official: boolean; items: BrandRegistration[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [f, setF] = useState({ brand_name: "", trademark_number: "", document_url: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null); setError(null);
    apiRequest<{ official: boolean; items: BrandRegistration[] }>("/supplier/brand-registration", { token })
      .then((r) => { if (!cancelled) setData(r); }).catch((e) => { if (!cancelled) setError(errText(e)); });
    return () => { cancelled = true; };
  }, [token, retry]);

  const pending = data?.items.some((r) => r.status === "pending");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!f.document_url.startsWith("https://")) { setMsg({ ok: false, text: "نشانی مدرک باید با https:// شروع شود." }); return; }
    setBusy(true); setMsg(null);
    try {
      await apiRequest("/supplier/brand-registration", { token, method: "POST", body: JSON.stringify({ ...f, brand_name: f.brand_name.trim(), trademark_number: f.trademark_number.trim() }) });
      setF({ brand_name: "", trademark_number: "", document_url: "" }); setMsg({ ok: true, text: "درخواست ثبت شد و بررسی می‌شود." }); setRetry((x) => x + 1);
    } catch (e2) { setMsg({ ok: false, text: errText(e2, "ثبت درخواست ناموفق بود") }); } finally { setBusy(false); }
  };

  return (
    <div id="brand"><Card title="ثبت برند رسمی" action={data?.official && <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-800">✓ برند رسمی</span>}>
      {error ? <ListState items={null} error={error} empty="" onRetry={() => setRetry((x) => x + 1)} /> : !data ? <ListState items={null} error={null} empty="" /> : (
        <>
          {data.items.length > 0 && (
            <ul className="divide-y divide-neutral-100 text-sm">
              {data.items.map((r) => (
                <li key={r.id} className="py-2"><b>{r.brand_name}</b> · <span dir="ltr">{r.trademark_number}</span> · {REG_FA[r.status]}
                  {r.review_note && <span className="block text-xs text-neutral-500">{r.review_note}</span>}</li>
              ))}
            </ul>
          )}
          {!pending && !data.official && (
            <form onSubmit={submit} className="grid gap-2 sm:grid-cols-3 sm:items-end">
              <label className="text-xs font-bold">نام برند<input className={inputCls} required maxLength={120} value={f.brand_name} onChange={(e) => setF({ ...f, brand_name: e.target.value })} /></label>
              <label className="text-xs font-bold">شمارهٔ ثبت علامت تجاری<input className={inputCls} required dir="ltr" maxLength={40} value={f.trademark_number} onChange={(e) => setF({ ...f, trademark_number: e.target.value })} /></label>
              <label className="text-xs font-bold">نشانی مدرک (https)<input className={inputCls} required type="url" dir="ltr" maxLength={500} value={f.document_url} onChange={(e) => setF({ ...f, document_url: e.target.value.trim() })} /></label>
              <button type="submit" className={btnCls} disabled={busy}>{busy ? "در حال ثبت…" : "ارسال برای بررسی"}</button>
            </form>
          )}
          {pending && <p className="text-xs text-neutral-500">درخواست قبلی در حال بررسی است.</p>}
        </>
      )}
      <Flash msg={msg} />
    </Card></div>
  );
}

// ── Shipments ───────────────────────────────────────────────────────────────
type FO = { id: number; order_number: string; status: string; shipping_city: string | null };
const SHIPPABLE = ["accepted", "preparing", "ready"];
function ShipmentsCard({ token }: { token: string }) {
  const [retry, setRetry] = useState(0);
  const [ships, sErr] = useList<Shipment>("/supplier/shipments", token, retry, (r: { shipments: Shipment[] }) => r.shipments);
  const [fos, fErr] = useList<FO>("/supplier/orders?limit=100", token, retry, (r: { fulfillment_orders: FO[] }) => r.fulfillment_orders.filter((f) => SHIPPABLE.includes(f.status)));
  const [foId, setFoId] = useState("");
  const [strategy, setStrategy] = useState("cheapest");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [pickupFor, setPickupFor] = useState<number | null>(null);
  const shipped = new Set(ships?.filter((s) => s.status !== "failed" && s.status !== "returned").map((s) => s.fulfillment_order_id));
  const open = fos?.filter((f) => !shipped.has(f.id)) ?? null;

  const create = async (e: React.FormEvent) => {
    e.preventDefault(); if (!foId) return;
    setBusy(true); setMsg(null);
    try {
      const { shipment } = await apiRequest<{ shipment: Shipment }>("/supplier/shipments", { token, method: "POST", body: JSON.stringify({ fulfillment_order_id: Number(foId), strategy }) });
      setMsg({ ok: true, text: `برچسب صادر شد؛ کد رهگیری ${shipment.tracking_number}` }); setFoId(""); setRetry((x) => x + 1);
    } catch (e2) { setMsg({ ok: false, text: errText(e2, "صدور برچسب ناموفق بود") }); } finally { setBusy(false); }
  };

  return (
    <div id="shipments"><Card title="ارسال سفارش‌ها">
      <form onSubmit={create} className="grid gap-2 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
        <label className="text-xs font-bold">سفارش آمادهٔ ارسال
          <select className={inputCls} required value={foId} onChange={(e) => setFoId(e.target.value)} disabled={!open?.length}>
            <option value="">{fErr ? "خطا در دریافت سفارش‌ها" : !open ? "در حال بارگذاری…" : open.length ? "انتخاب کنید" : "سفارش آماده‌ای نیست"}</option>
            {open?.map((f) => <option key={f.id} value={f.id}>{f.order_number}{f.shipping_city ? ` · ${f.shipping_city}` : ""}</option>)}
          </select></label>
        <label className="text-xs font-bold">انتخاب حامل
          <select className={inputCls} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="cheapest">ارزان‌ترین</option><option value="fastest">سریع‌ترین</option>
          </select></label>
        <button type="submit" className={btnCls} disabled={busy || !foId}>{busy ? "در حال صدور…" : "صدور برچسب"}</button>
      </form>
      <Flash msg={msg} />
      <ListState items={ships} error={sErr} empty="هنوز مرسوله‌ای نساخته‌ای." onRetry={() => setRetry((x) => x + 1)} />
      <ul className="divide-y divide-neutral-100 text-sm">
        {ships?.map((s) => {
          const labelUrl = typeof s.label?.url === "string" && s.label.url.startsWith("https://") ? s.label.url : null;
          return (
            <li key={s.id} className="py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0"><span dir="ltr" className="font-bold">{s.tracking_number}</span>
                  <span className="block text-xs text-neutral-500">{SHIP_STATUS_FA[s.status] ?? s.status} · {s.provider_code}{s.pickup_requested_at ? " · جمع‌آوری درخواست شد" : ""}</span></span>
                <span className="flex gap-2">
                  {labelUrl && <a href={labelUrl} target="_blank" rel="noopener noreferrer" className={btnGhost}>برچسب</a>}
                  {s.status === "created" && !s.pickup_requested_at && (
                    <button type="button" className={btnGhost} aria-expanded={pickupFor === s.id} onClick={() => setPickupFor(pickupFor === s.id ? null : s.id)}>درخواست جمع‌آوری</button>)}
                </span>
              </div>
              {pickupFor === s.id && <PickupForm token={token} id={s.id} onDone={(m) => { setMsg(m); if (m.ok) { setPickupFor(null); setRetry((x) => x + 1); } }} />}
            </li>
          );
        })}
      </ul>
    </Card></div>
  );
}

function PickupForm({ token, id, onDone }: { token: string; id: number; onDone: (m: { ok: boolean; text: string }) => void }) {
  const [date, setDate] = useState("");
  const [from, setFrom] = useState("09");
  const [to, setTo] = useState("13");
  const [busy, setBusy] = useState(false);
  const hours = Array.from({ length: 15 }, (_, i) => String(i + 7).padStart(2, "0"));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (Number(to) <= Number(from)) { onDone({ ok: false, text: "پایان بازه باید بعد از شروع باشد." }); return; }
    setBusy(true);
    try {
      const iso = (h: string) => new Date(`${date}T${h}:00:00`).toISOString();
      await apiRequest(`/supplier/shipments/${id}/pickup`, { token, method: "POST", body: JSON.stringify({ window_start: iso(from), window_end: iso(to) }) });
      onDone({ ok: true, text: "درخواست جمع‌آوری ثبت شد." });
    } catch (e2) { onDone({ ok: false, text: errText(e2) }); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4 sm:items-end">
      <label className="col-span-2 text-xs font-bold sm:col-span-1">روز<input type="date" dir="ltr" required className={inputCls} value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <label className="text-xs font-bold">از ساعت<select className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)}>{hours.map((h) => <option key={h} value={h}>{n(Number(h))}</option>)}</select></label>
      <label className="text-xs font-bold">تا ساعت<select className={inputCls} value={to} onChange={(e) => setTo(e.target.value)}>{hours.map((h) => <option key={h} value={h}>{n(Number(h))}</option>)}</select></label>
      <button type="submit" className={`${btnCls} col-span-2 sm:col-span-1`} disabled={busy || !date}>ثبت</button>
    </form>
  );
}

// ── Finance exports ─────────────────────────────────────────────────────────
const CONNECTORS: [string, string][] = [["EXCEL", "اکسل"], ["CSV", "CSV"], ["JSON", "JSON"], ["SEPIDAR", "سپیدار"], ["HAMKARAN", "همکاران سیستم"]];
function ExportsCard({ token }: { token: string }) {
  const [retry, setRetry] = useState(0);
  const [jobs, error] = useList<ExportJob>("/supplier/finance-exports", token, retry, (r: { jobs: ExportJob[] }) => r.jobs);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ start: today.slice(0, 8) + "01", end: today, connector: "EXCEL" });
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);

  const download = async (j: ExportJob) => {
    setBusy(`d${j.id}`); setMsg(null);
    try { await downloadAuthed(`/supplier/finance-exports/${j.id}/download`, token, j.file_name); }
    catch (e) { setMsg({ ok: false, text: errText(e, "دریافت فایل ناموفق بود") }); } finally { setBusy(null); }
  };
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (f.end < f.start) { setMsg({ ok: false, text: "تاریخ پایان باید بعد از شروع باشد." }); return; }
    setBusy("new"); setMsg(null);
    try {
      const { job } = await apiRequest<{ job: ExportJob }>("/supplier/finance-exports", { token, method: "POST",
        body: JSON.stringify({ period_start: f.start, period_end: f.end, connector: f.connector }) });
      setRetry((x) => x + 1);
      await download(job);
    } catch (e2) { setMsg({ ok: false, text: errText(e2, "ساخت خروجی ناموفق بود") }); } finally { setBusy(null); }
  };

  return (
    <div id="exports"><Card title="خروجی مالی برای حسابداری">
      <form onSubmit={create} className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:items-end">
        <label className="text-xs font-bold">از تاریخ<input type="date" dir="ltr" required className={inputCls} value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
        <label className="text-xs font-bold">تا تاریخ<input type="date" dir="ltr" required className={inputCls} value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label>
        <label className="text-xs font-bold">قالب<select className={inputCls} value={f.connector} onChange={(e) => setF({ ...f, connector: e.target.value })}>
          {CONNECTORS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <button type="submit" className={btnCls} disabled={busy !== null}>{busy === "new" ? "در حال ساخت…" : "ساخت و دریافت"}</button>
      </form>
      <Flash msg={msg} />
      <ListState items={jobs} error={error} empty="هنوز خروجی‌ای نساخته‌ای." onRetry={() => setRetry((x) => x + 1)} />
      <ul className="divide-y divide-neutral-100 text-sm">
        {jobs?.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="min-w-0">{faDate(j.period_start)} تا {faDate(j.period_end)} · {j.connector}
              <span className="block text-xs text-neutral-500">{n(j.document_count)} سند · ساخته‌شده {faDate(j.created_at)}</span></span>
            <button type="button" className={btnGhost} disabled={busy !== null} onClick={() => download(j)}>{busy === `d${j.id}` ? "در حال دریافت…" : "دریافت فایل"}</button>
          </li>
        ))}
      </ul>
    </Card></div>
  );
}
