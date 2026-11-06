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
