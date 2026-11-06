"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";

type Loc = { id: number; title: string; city: string; address: string | null; opening_hours: string | null };
type Opts = { eligible: boolean; locations: Loc[]; chosen: { location_id: number; status: string; code_last2: string; expires_at: string } | null };

/** «دریافت حضوری»: switch one seller part of the order to collect-in-store; the code is shown once. */
export function PickupChooser({ token, foId }: { token: string; foId: number }) {
  const [o, setO] = useState<Opts | null>(null);
  const [loc, setLoc] = useState<number | "">("");
  const [code, setCode] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => apiRequest<Opts>(`/me/fulfillments/${foId}/pickup`, { token }).then(setO).catch(() => setO(null)),
    [token, foId]);
  useEffect(() => { void load(); }, [load]);

  if (!o || (!o.eligible && !o.chosen) || (o.eligible && o.locations.length === 0)) return null;
  if (o.chosen || code) {
    return (
      <p className="mt-1 rounded-lg bg-emerald-50 p-2 text-xs leading-6 text-emerald-800">
        دریافت حضوری ثبت شده است.{" "}
        {code ? <>کد تحویل: <b dir="ltr" className="text-base tracking-widest">{code}</b> (فقط همین یک‌بار نمایش داده می‌شود؛ یادداشت کن)</>
          : <>کد تحویل به ‎…{o.chosen?.code_last2} ختم می‌شود.</>}
      </p>
    );
  }
  const submit = async () => {
    if (loc === "") return;
    setBusy(true); setErr(null);
    try {
      const r = await apiRequest<{ pickup_code: string }>(`/me/fulfillments/${foId}/pickup`, {
        method: "POST", token, body: JSON.stringify({ location_id: loc }) });
      setCode(r.pickup_code); void load();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "ثبت دریافت حضوری ناموفق بود"); }
    finally { setBusy(false); }
  };
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
      <label htmlFor={`pk-${foId}`} className="text-neutral-600">دریافت حضوری از فروشگاه:</label>
      <select id={`pk-${foId}`} className="rounded-lg border p-1" value={loc} onChange={(e) => setLoc(e.target.value ? Number(e.target.value) : "")}>
        <option value="">انتخاب کن</option>
        {o.locations.map((l) => <option key={l.id} value={l.id}>{l.title} — {l.city}{l.address ? `، ${l.address}` : ""}</option>)}
      </select>
      <button type="button" disabled={busy || loc === ""} onClick={submit} className="rounded-lg border border-neutral-900 px-2 py-1 font-bold disabled:opacity-50">
        {busy ? "…" : "ثبت"}
      </button>
      {err && <span role="alert" className="text-red-600">{err}</span>}
    </div>
  );
}
