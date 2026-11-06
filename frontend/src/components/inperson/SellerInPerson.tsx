"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";
import { latinDigits } from "@/lib/shops";

type Visit = { id: number; starts_at: string; duration_min: number; purpose: string; note: string | null; status: string; full_name: string };
const PURPOSE_FA: Record<string, string> = { showroom: "بازدید", samples: "نمونهٔ سازمانی", consultation: "مشاوره", pickup: "دریافت", other: "سایر" };
const STATUS_FA: Record<string, string> = { requested: "در انتظار", confirmed: "تأییدشده", declined: "ردشده", cancelled: "لغوشده", done: "انجام‌شده" };

/** Seller counter: confirm a collect-in-store code, and manage visit appointments. */
export function SellerInPerson({ token }: { token: string }) {
  const [fo, setFo] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [visits, setVisits] = useState<Visit[]>([]);
  const load = useCallback(() => apiRequest<{ items: Visit[] }>("/supplier/visits", { token }).then((r) => setVisits(r.items)).catch(() => {}), [token]);
  useEffect(() => { void load(); }, [load]);

  const confirm = async (e: React.FormEvent) => {
    e.preventDefault(); setMsg(null);
    try {
      await apiRequest(`/supplier/fulfillments/${Number(fo)}/pickup/confirm`, { method: "POST", token, body: JSON.stringify({ code }) });
      setMsg({ ok: true, text: "تحویل حضوری ثبت شد." }); setCode("");
    } catch (err) { setMsg({ ok: false, text: err instanceof ApiError ? err.message : "ثبت تحویل ناموفق بود" }); }
  };
  const decide = async (id: number, d: "confirm" | "decline" | "done") => {
    try { await apiRequest(`/supplier/visits/${id}/${d}`, { method: "POST", token, body: "{}" }); void load(); } catch { /* list reload shows state */ }
  };

  return (
    <section id="in-person" aria-labelledby="inperson-h" className="rounded-2xl border border-neutral-200 p-4 space-y-4">
      <h2 id="inperson-h" className="font-black text-neutral-900">مراجعهٔ حضوری</h2>
      <LocationSettings token={token} />
      <form onSubmit={confirm} className="flex flex-wrap items-end gap-2 text-sm">
        <label>شمارهٔ بخش سفارش
          <input inputMode="numeric" dir="ltr" required className="mt-1 block w-28 rounded-xl border p-2" value={fo}
            onChange={(e) => setFo(latinDigits(e.target.value).replace(/\D/g, ""))} />
        </label>
        <label>کد تحویل مشتری
          <input inputMode="numeric" dir="ltr" required maxLength={6} className="mt-1 block w-28 rounded-xl border p-2 tracking-widest" value={code}
            onChange={(e) => setCode(latinDigits(e.target.value).replace(/\D/g, ""))} />
        </label>
        <button type="submit" disabled={!fo || code.length !== 6} className="rounded-xl bg-neutral-900 px-4 py-2 font-bold text-white disabled:opacity-50">ثبت تحویل</button>
        {msg && <p role="status" className={`w-full ${msg.ok ? "text-emerald-700" : "text-red-600"}`}>{msg.text}</p>}
      </form>
      <div>
        <p className="mb-2 text-sm font-bold">نوبت‌های مراجعه</p>
        {visits.length === 0 ? <p className="text-sm text-neutral-500">نوبتی ثبت نشده است. «رزرو نوبت» را برای محل فروش‌تان فعال کنید تا در صفحهٔ مراجعهٔ حضوری دیده شوید.</p> : (
          <ul className="space-y-2 text-sm">
            {visits.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-neutral-50 p-2">
                <span>{new Date(v.starts_at).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" })}</span>
                <span>· {v.full_name}</span><span>· {PURPOSE_FA[v.purpose] ?? v.purpose}</span>
                <span className="rounded-full bg-white px-2">{STATUS_FA[v.status] ?? v.status}</span>
                {v.status === "requested" && <>
                  <button type="button" onClick={() => decide(v.id, "confirm")} className="rounded-lg border px-2">تأیید</button>
                  <button type="button" onClick={() => decide(v.id, "decline")} className="rounded-lg border px-2">رد</button>
                </>}
                {v.status === "confirmed" && <button type="button" onClick={() => decide(v.id, "done")} className="rounded-lg border px-2">انجام شد</button>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

type Loc = { id: number; city: string; address: string; status: string; can_pickup: boolean; accepts_walk_in: boolean;
  accepts_appointments: boolean; public_title: string | null; public_phone: string | null; opening_hours: Record<string, string> | null };
const DAYS: [string, string][] = [["sat", "شنبه"], ["sun", "یکشنبه"], ["mon", "دوشنبه"], ["tue", "سه‌شنبه"], ["wed", "چهارشنبه"], ["thu", "پنجشنبه"], ["fri", "جمعه"]];
const FLAGS: [keyof Loc, string][] = [["can_pickup", "تحویل سفارش در محل"], ["accepts_walk_in", "مراجعهٔ بدون نوبت"], ["accepts_appointments", "بازدید با نوبت"]];

/** Per-location in-person options: shown on /stores and used by pickup and visit booking. */
function LocationSettings({ token }: { token: string }) {
  const [locs, setLocs] = useState<Loc[] | null>(null);
  const [msg, setMsg] = useState<{ id: number; ok: boolean; text: string } | null>(null);
  useEffect(() => { apiRequest<{ items: Loc[] }>("/supplier/locations/in-person", { token }).then((r) => setLocs(r.items)).catch(() => setLocs([])); }, [token]);
  if (!locs) return null;
  if (!locs.length) return <p className="text-sm text-neutral-500">هنوز محلی (انبار یا فروشگاه) ثبت نکرده‌ای.</p>;
  const patch = (id: number, p: Partial<Loc>) => setLocs(locs.map((l) => (l.id === id ? { ...l, ...p } : l)));
  const save = async (l: Loc) => {
    setMsg(null);
    const hours = Object.fromEntries(Object.entries(l.opening_hours ?? {}).filter(([, v]) => v && v.trim()).map(([k, v]) => [k, latinDigits(v.trim())]));
    try {
      await apiRequest(`/supplier/locations/${l.id}/in-person`, { method: "PUT", token, body: JSON.stringify({
        can_pickup: l.can_pickup, accepts_walk_in: l.accepts_walk_in, accepts_appointments: l.accepts_appointments,
        public_title: l.public_title || null, public_phone: l.public_phone ? latinDigits(l.public_phone) : null,
        opening_hours: Object.keys(hours).length ? hours : null }) });
      setMsg({ id: l.id, ok: true, text: "ذخیره شد." });
    } catch (err) { setMsg({ id: l.id, ok: false, text: err instanceof ApiError ? err.message : "ذخیره ناموفق بود" }); }
  };
  return (
    <div className="space-y-3">
      {locs.map((l) => (
        <form key={l.id} onSubmit={(e) => { e.preventDefault(); void save(l); }} className="space-y-3 rounded-xl bg-neutral-50 p-3 text-sm">
          <p className="font-bold">{l.city} · <span className="font-normal text-neutral-600">{l.address}</span></p>
          <div className="flex flex-wrap gap-4">
            {FLAGS.map(([k, label]) => (
              <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={Boolean(l[k])} onChange={(e) => patch(l.id, { [k]: e.target.checked } as Partial<Loc>)} />{label}</label>
            ))}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label>نام نمایشی شعبه<input className="mt-1 block w-full rounded-xl border p-2" maxLength={120} value={l.public_title ?? ""} onChange={(e) => patch(l.id, { public_title: e.target.value })} /></label>
            <label>تلفن شعبه<input className="mt-1 block w-full rounded-xl border p-2" dir="ltr" inputMode="tel" maxLength={20} value={l.public_phone ?? ""} onChange={(e) => patch(l.id, { public_phone: e.target.value })} /></label>
          </div>
          <fieldset>
            <legend className="font-bold">ساعت کاری <span className="font-normal text-xs text-neutral-500">(مثل 09:00-18:00 یا دو نوبت 09:00-13:00,16:00-20:00؛ برای تعطیل بنویسید closed؛ خالی = نامشخص)</span></legend>
            <div className="mt-1 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {DAYS.map(([k, label]) => (
                <label key={k} className="text-xs">{label}
                  <input className="mt-1 block w-full rounded-lg border p-1.5" dir="ltr" placeholder="09:00-18:00" value={l.opening_hours?.[k] ?? ""}
                    onChange={(e) => patch(l.id, { opening_hours: { ...(l.opening_hours ?? {}), [k]: e.target.value } })} />
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex items-center gap-3">
            <button className="rounded-xl bg-primary-600 px-4 py-2 font-bold text-white">ذخیره</button>
            {msg?.id === l.id && <span role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-green-700" : "text-red-700"}>{msg.text}</span>}
          </div>
        </form>
      ))}
    </div>
  );
}
